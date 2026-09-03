#!/usr/bin/env python3
"""Lightweight static and adversarial gates for PU-PROJ v19."""

from __future__ import annotations

import base64
import contextlib
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
ARTIFACT_ROOT = ROOT / "benchmarks/probe_diagnostics/puproj_v19"
RUNNER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-runner.py"
SUPERVISOR = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-supervisor.py"
LAUNCHER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-launcher.py"
BOOTSTRAP = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-bootstrap"
BOOTSTRAP_SOURCE = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-bootstrap.c"
GENERIC = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-generic-validator.py"
STDLIB_MANIFEST = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-stdlib.sha256"
FREEZE = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-freeze.json"
CERTIFICATE = (
    ARTIFACT_ROOT / "planora-puproj-frontier-joint-v19-completion-certificate.json"
)
REPOSITORY_VIOLATION_TEST = ROOT / "tests/test_itc2019_violation_lns.py"
EXPECTED_REPOSITORY_VIOLATION_TEST_SHA256 = "a738894d4393d8d5bf8a240f493fa92e2e12e820cd885b40518e13cc0d91efdb"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(RUNNER, "puproj_v19_runner_tested")
guard = load(SUPERVISOR, "puproj_v19_supervisor_tested")
sealed_launcher = load(LAUNCHER, "puproj_v19_launcher_tested")


def write_child(directory: Path, payload: dict[str, object]) -> None:
    payload.setdefault("runner_sha256_start", guard.EXPECTED_RUNNER_SHA256)
    payload.setdefault("runner_sha256_end", guard.EXPECTED_RUNNER_SHA256)
    payload.setdefault("runner_hash_stable", True)
    (directory / "child.stdout.log").write_text(json.dumps(payload), encoding="utf-8")
    (directory / "child.stderr.log").write_bytes(b"")


def loaded_runtime_row(
    path: str,
    *,
    digest: str = "b" * 64,
    size: int = 1,
    transport: str = "sealed_native_descriptor",
) -> dict[str, object]:
    return {
        "path": path,
        "sha256": digest,
        "size": size,
        "transport": transport,
    }


def loaded_runtime_manifest_sha256(rows: list[dict[str, object]]) -> str:
    return sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ArchitectureTests(unittest.TestCase):
    TEMPFILE_PATH = Path("/usr/lib/python3.12/tempfile.py")
    TEMPFILE_SHA256 = (
        "8c8033ed1426ace79e07a6608887d2a1694d817d63d61b04c3d59339f24b4269"
    )

    @staticmethod
    def stdlib_manifest() -> tuple[bytes, dict[str, str]]:
        raw = STDLIB_MANIFEST.read_bytes()
        return raw, runner._parse_stdlib_manifest(raw)

    def test_fresh_mode_excludes_all_resume_sources(self) -> None:
        for label in ("checkpoint", "stripped_instance", "derivation", "frontier"):
            self.assertNotIn(label, guard.CAPTURE_SOURCES)
            self.assertNotIn(label, runner.EXPECTED_HASHES)

    def test_exact_official_hash_and_cardinality(self) -> None:
        self.assertEqual(runner.EXPECTED_CLASS_COUNT, 8_813)
        self.assertEqual(runner.EXPECTED_STUDENT_COUNT, 38_437)
        self.assertEqual(runner.EXPECTED_HASHES["full_instance"], "2fa848bf039f8ef86f65e280b5302afd37c48a03e1bc7e09364cf91bebd86e42")

    def test_tempfile_import_path_is_required_and_exactly_pinned(self) -> None:
        raw, manifest = self.stdlib_manifest()
        self.assertEqual(Path(tempfile.__file__).resolve(), self.TEMPFILE_PATH)
        self.assertEqual(
            sha256(self.TEMPFILE_PATH.read_bytes()).hexdigest(),
            self.TEMPFILE_SHA256,
        )
        for module in (runner, guard):
            with self.subTest(module=module.__name__):
                self.assertEqual(
                    module._parse_stdlib_manifest(raw)[self.TEMPFILE_PATH.as_posix()],
                    self.TEMPFILE_SHA256,
                )
        self.assertEqual(manifest[self.TEMPFILE_PATH.as_posix()], self.TEMPFILE_SHA256)

    def test_full_stdlib_manifest_is_authoritative_and_complete(self) -> None:
        raw, runner_manifest = self.stdlib_manifest()
        guard_manifest = guard._parse_stdlib_manifest(raw)
        self.assertEqual(sha256(raw).hexdigest(), guard.EXPECTED_STDLIB_MANIFEST_SHA256)
        self.assertEqual(len(runner_manifest), 619)
        self.assertEqual(runner_manifest, guard_manifest)
        self.assertIn(
            "/usr/lib/python3.12/importlib/resources/abc.py", runner_manifest
        )
        self.assertEqual(guard.CAPTURE_SOURCES["stdlib_manifest"], STDLIB_MANIFEST)
        self.assertIn("stdlib_manifest", runner.EXPECTED_CAPTURE_LABELS)
        self.assertNotIn("SYSTEM_PYTHON_HASHES", RUNNER.read_text(encoding="utf-8"))
        self.assertNotIn("SYSTEM_PYTHON_HASHES", SUPERVISOR.read_text(encoding="utf-8"))

    def test_loaded_runtime_identical_duplicate_paths_collapse(self) -> None:
        row = loaded_runtime_row("ortools/.libs/libortools.so")
        normalized = runner._normalize_loaded_runtime_rows([dict(row), dict(row)])
        self.assertEqual(normalized, [row])

    def test_loaded_runtime_conflicting_duplicate_paths_are_rejected(self) -> None:
        original = loaded_runtime_row("ortools/.libs/libortools.so")
        mutations = (
            {**original, "sha256": "c" * 64},
            {**original, "size": 2},
            {**original, "transport": "sealed_descriptor_loader"},
        )
        for conflicting in mutations:
            with self.subTest(conflicting=conflicting), self.assertRaisesRegex(
                RuntimeError, "conflicting duplicate loaded runtime observation"
            ):
                runner._normalize_loaded_runtime_rows([original, conflicting])

    def test_loaded_runtime_normalization_has_deterministic_order_and_hash(self) -> None:
        first = loaded_runtime_row("a/module.py", transport="sealed_descriptor_loader")
        second = loaded_runtime_row("z/libnative.so", digest="c" * 64, size=2)
        expected = [first, second]
        forward = runner._loaded_runtime_manifest([second, first, dict(second)])
        reverse = runner._loaded_runtime_manifest([dict(first), second, first])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward[0], expected)
        self.assertEqual(forward[1], loaded_runtime_manifest_sha256(expected))

    def test_loaded_runtime_normalization_preserves_unique_valid_rows(self) -> None:
        rows = [
            loaded_runtime_row("a/module.py", transport="sealed_descriptor_loader"),
            loaded_runtime_row("z/libnative.so", digest="c" * 64, size=2),
        ]
        normalized, manifest_sha256 = runner._loaded_runtime_manifest(rows)
        self.assertEqual(normalized, rows)
        self.assertEqual(manifest_sha256, loaded_runtime_manifest_sha256(rows))

    def test_stdlib_manifest_mutation_is_rejected(self) -> None:
        raw = bytearray(STDLIB_MANIFEST.read_bytes())
        raw[0] = ord("0") if raw[0] != ord("0") else ord("1")
        for module in (runner, guard):
            with self.subTest(module=module.__name__), self.assertRaisesRegex(
                RuntimeError, "stdlib manifest SHA-256 rejected"
            ):
                module._parse_stdlib_manifest(bytes(raw))

    @staticmethod
    def sealed_capture_module(
        label: str = "benchmarks_corpus",
        digest: str = guard.EXPECTED_HASHES["benchmarks_corpus"],
    ) -> types.ModuleType:
        module = types.ModuleType("benchmarks.corpus")
        module.__file__ = f"<sealed:{label}:{digest}>"
        module.__captured_sha256__ = digest
        return module

    @staticmethod
    def sealed_capture_evidence(
        label: str = "benchmarks_corpus",
        digest: str = guard.EXPECTED_HASHES["benchmarks_corpus"],
    ) -> dict[str, dict[str, object]]:
        return {
            label: {
                "label": label,
                "sha256": digest,
                "seals": runner.REQUIRED_SEALS,
                "required_seals": runner.REQUIRED_SEALS,
                "transport": "sealed_memfd",
            }
        }

    def test_exact_sealed_capture_pseudopath_binding_is_admitted(self) -> None:
        digest = guard.EXPECTED_HASHES["benchmarks_corpus"]
        admitted: set[str] = set()
        row = runner._admit_sealed_capture_module_origin(
            self.sealed_capture_module(),
            f"<sealed:benchmarks_corpus:{digest}>",
            self.sealed_capture_evidence(),
            admitted,
        )
        self.assertEqual(
            row,
            {
                "label": "benchmarks_corpus",
                "sha256": digest,
                "origin": f"<sealed:benchmarks_corpus:{digest}>",
                "transport": "supervisor_sealed_capture_replay",
            },
        )
        self.assertEqual(admitted, {"benchmarks_corpus"})

    def test_unknown_sealed_capture_label_is_rejected(self) -> None:
        digest = "1" * 64
        module = self.sealed_capture_module("unknown", digest)
        with self.assertRaisesRegex(RuntimeError, "unknown sealed capture label"):
            runner._admit_sealed_capture_module_origin(
                module,
                module.__file__,
                self.sealed_capture_evidence(),
                set(),
            )

    def test_malformed_sealed_capture_origins_and_relative_paths_are_rejected(self) -> None:
        malformed = (
            "<sealed:benchmarks_corpus>",
            "<sealed::" + "1" * 64 + ">",
            "<sealed:benchmarks_corpus:" + "A" * 64 + ">",
            "<sealed:benchmarks_corpus:" + "1" * 63 + ">",
            "<sealed:benchmarks_corpus:" + "1" * 64,
        )
        for origin in malformed:
            module = self.sealed_capture_module()
            module.__file__ = origin
            with self.subTest(origin=origin), self.assertRaisesRegex(
                RuntimeError, "malformed sealed capture module origin"
            ):
                runner._admit_sealed_capture_module_origin(
                    module, origin, self.sealed_capture_evidence(), set()
                )
        module = self.sealed_capture_module()
        module.__file__ = "benchmarks/corpus.py"
        with self.assertRaisesRegex(RuntimeError, "arbitrary relative Python module"):
            runner._admit_sealed_capture_module_origin(
                module, module.__file__, self.sealed_capture_evidence(), set()
            )

    def test_sealed_capture_origin_hash_mismatch_is_rejected(self) -> None:
        digest = guard.EXPECTED_HASHES["benchmarks_corpus"]
        module = self.sealed_capture_module(digest="1" * 64)
        with self.assertRaisesRegex(RuntimeError, "sealed capture origin hash mismatch"):
            runner._admit_sealed_capture_module_origin(
                module,
                f"<sealed:benchmarks_corpus:{digest}>",
                self.sealed_capture_evidence(),
                set(),
            )

    def test_sealed_capture_replay_digest_mismatch_is_rejected(self) -> None:
        digest = guard.EXPECTED_HASHES["benchmarks_corpus"]
        evidence = self.sealed_capture_evidence(digest="1" * 64)
        with self.assertRaisesRegex(RuntimeError, "sealed capture replay hash mismatch"):
            runner._admit_sealed_capture_module_origin(
                self.sealed_capture_module(),
                f"<sealed:benchmarks_corpus:{digest}>",
                evidence,
                set(),
            )

    def test_unsealed_capture_origin_is_rejected(self) -> None:
        digest = guard.EXPECTED_HASHES["benchmarks_corpus"]
        for field, value in (
            ("seals", 0),
            ("required_seals", 0),
            ("transport", "named_file"),
        ):
            evidence = self.sealed_capture_evidence()
            evidence["benchmarks_corpus"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                RuntimeError, "unsealed capture origin rejected"
            ):
                runner._admit_sealed_capture_module_origin(
                    self.sealed_capture_module(),
                    f"<sealed:benchmarks_corpus:{digest}>",
                    evidence,
                    set(),
                )

    def test_duplicate_sealed_capture_origin_is_rejected(self) -> None:
        digest = guard.EXPECTED_HASHES["benchmarks_corpus"]
        with self.assertRaisesRegex(RuntimeError, "duplicate sealed capture origin"):
            runner._admit_sealed_capture_module_origin(
                self.sealed_capture_module(),
                f"<sealed:benchmarks_corpus:{digest}>",
                self.sealed_capture_evidence(),
                {"benchmarks_corpus"},
            )

    def test_tempfile_import_path_is_admitted_by_the_identity_contract(self) -> None:
        _raw, manifest = self.stdlib_manifest()
        observed_uid = self.TEMPFILE_PATH.stat().st_uid
        for module, admission in (
            (runner, runner._hash_admitted_system_python_file),
            (guard, guard._hash_stable_system_file),
        ):
            with self.subTest(module=module.__name__), mock.patch.object(
                module, "SYSTEM_PYTHON_OWNER_UID", observed_uid
            ), mock.patch.object(
                module.os,
                "statvfs",
                return_value=mock.Mock(f_flag=getattr(os, "ST_RDONLY", 1)),
            ):
                row = admission(self.TEMPFILE_PATH, manifest)
                self.assertEqual(row["path"], self.TEMPFILE_PATH.as_posix())
                self.assertEqual(row["sha256"], self.TEMPFILE_SHA256)
                self.assertEqual(row["size"], self.TEMPFILE_PATH.stat().st_size)
                self.assertEqual(row["owner_uid"], observed_uid)
                self.assertTrue(row["read_only_filesystem"])

    def test_tempfile_mutation_still_fails_closed(self) -> None:
        _raw, manifest = self.stdlib_manifest()
        observed_uid = self.TEMPFILE_PATH.stat().st_uid
        for module, admission in (
            (runner, runner._hash_admitted_system_python_file),
            (guard, guard._hash_stable_system_file),
        ):
            mutated = dict(manifest)
            mutated[self.TEMPFILE_PATH.as_posix()] = "0" * 64
            with self.subTest(module=module.__name__), mock.patch.object(
                module, "SYSTEM_PYTHON_OWNER_UID", observed_uid
            ), mock.patch.object(
                module.os,
                "statvfs",
                return_value=mock.Mock(f_flag=getattr(os, "ST_RDONLY", 1)),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    r"unpinned or mutated system Python file rejected: .*/tempfile\.py",
                ):
                    admission(self.TEMPFILE_PATH, mutated)

    def test_unlisted_stdlib_file_fails_closed(self) -> None:
        _raw, manifest = self.stdlib_manifest()
        manifest.pop(self.TEMPFILE_PATH.as_posix())
        observed_uid = self.TEMPFILE_PATH.stat().st_uid
        for module, admission in (
            (runner, runner._hash_admitted_system_python_file),
            (guard, guard._hash_stable_system_file),
        ):
            with self.subTest(module=module.__name__), mock.patch.object(
                module, "SYSTEM_PYTHON_OWNER_UID", observed_uid
            ), mock.patch.object(
                module.os,
                "statvfs",
                return_value=mock.Mock(f_flag=getattr(os, "ST_RDONLY", 1)),
            ), self.assertRaisesRegex(
                RuntimeError,
                r"unpinned or mutated system Python file rejected: .*/tempfile\.py",
            ):
                admission(self.TEMPFILE_PATH, manifest)

    def test_stdlib_owner_regular_and_read_only_contracts_fail_closed(self) -> None:
        _raw, manifest = self.stdlib_manifest()
        observed_uid = self.TEMPFILE_PATH.stat().st_uid
        for module, admission in (
            (runner, runner._hash_admitted_system_python_file),
            (guard, guard._hash_stable_system_file),
        ):
            with self.subTest(module=module.__name__, contract="owner"), mock.patch.object(
                module, "SYSTEM_PYTHON_OWNER_UID", observed_uid + 1
            ), self.assertRaisesRegex(RuntimeError, "ownership/mode drift"):
                admission(self.TEMPFILE_PATH, manifest)
            with self.subTest(module=module.__name__, contract="read_only"), mock.patch.object(
                module, "SYSTEM_PYTHON_OWNER_UID", observed_uid
            ), mock.patch.object(
                module.os, "statvfs", return_value=mock.Mock(f_flag=0)
            ), self.assertRaisesRegex(RuntimeError, "filesystem is no longer read-only"):
                admission(self.TEMPFILE_PATH, manifest)
            directory = Path("/usr/lib/python3.12/importlib/resources")
            with self.subTest(module=module.__name__, contract="regular"), self.assertRaisesRegex(
                RuntimeError, "ownership/mode drift"
            ):
                admission(directory, {directory.as_posix(): "0" * 64})

    def test_imported_subset_reporting_is_explicit(self) -> None:
        for path in (RUNNER, SUPERVISOR):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn('"stdlib_manifest_sha256"', source)
                self.assertIn('"stdlib_manifest_file_count"', source)
                self.assertIn('"imported_subset_sha256"', source)
                self.assertIn('"imported_subset_file_count"', source)

    def test_auto_solver_and_fairness_contract(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("solve_itc2019_native", source)
        self.assertIn('formulation="auto"', source)
        self.assertIn('"solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH"', source)
        self.assertNotIn("prepare_itc2019_context", source)

    def test_current_module_closure_exact(self) -> None:
        expected = {
            "itc2019_compact_joint", "itc2019_corpus", "itc2019_decomposed",
            "itc2019_decomposed_quality", "itc2019_factorized",
            "itc2019_generalized_occurrences", "itc2019_global_components",
            "itc2019_global_quality", "itc2019_grouped_calendar",
            "itc2019_resource_seed", "itc2019_sparse_joint", "itc2019_structural",
            "itc2019_violation_lns",
        }
        self.assertEqual(set(guard.PLANORA_FRESH_MODULES), expected)
        self.assertTrue(expected.issubset(runner.EXPECTED_HASHES))
        for name, path in guard.PLANORA_FRESH_MODULES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), guard.EXPECTED_HASHES[name], name)
            self.assertEqual(guard.EXPECTED_HASHES[name], runner.EXPECTED_HASHES[name], name)
        self.assertEqual(
            sha256(REPOSITORY_VIOLATION_TEST.read_bytes()).hexdigest(),
            EXPECTED_REPOSITORY_VIOLATION_TEST_SHA256,
        )

    def test_generic_validator_hash_pin(self) -> None:
        digest = sha256(GENERIC.read_bytes()).hexdigest()
        self.assertEqual(digest, runner.EXPECTED_HASHES["generic_validator"])
        self.assertEqual(digest, guard.EXPECTED_HASHES["generic_validator"])

    def test_generic_validator_is_a_distinct_isolated_child(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("subprocess.run(", source)
        self.assertIn('"-I", "-S", "-B", "-c"', source)
        self.assertIn('result["fresh_process_isolated"] = True', source)
        self.assertNotIn('prepared.modules["generic_validator"]', source)

    def test_runner_self_test_inert(self) -> None:
        result = runner.self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["solver_input_mode"], "OFFICIAL_INPUT_ONLY_FRESH")
        self.assertFalse(result["official_instance_opened"])

    def test_supervisor_self_test_union_accounting(self) -> None:
        result = guard.self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["whole_launch_vmrss_plus_vmswap_enforced"])
        self.assertTrue(result["whole_launch_pid_union_no_double_count"])

    def test_dry_run_no_official_open(self) -> None:
        sample = {"mem_available_kib": 1_000_000, "swap_free_kib": 0, "pswpin_pages": 0, "pswpout_pages": 0}
        with mock.patch.object(guard, "host_sample", return_value=sample), mock.patch.object(guard, "static_pins", return_value={}):
            result = guard.dry_run()
        self.assertEqual(result["status"], "NO_GO")
        self.assertFalse(result["full_official_input_opened"])
        self.assertFalse(result["checkpoint_or_incumbent_opened"])

    def test_launch_floor_and_sanitized_environment(self) -> None:
        self.assertEqual(guard.INITIAL_MIN_MEM_AVAILABLE_KIB, 1_900_000)
        source = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn('"PATH": "/usr/bin:/bin"', source)
        self.assertNotIn("os.environ.copy()", source)


class AcceptanceTests(unittest.TestCase):
    def test_generic_report_same_uid_name_swap_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "report.json", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o400,
                dir_fd=dirfd,
            )
            created = os.fstat(report_fd)
            os.write(report_fd, b'{"status":"COMPLETE_VALID"}\n')
            os.rename("report.json", "original.json", src_dir_fd=dirfd, dst_dir_fd=dirfd)
            attacker = os.open("report.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400, dir_fd=dirfd)
            os.write(attacker, b'{"status":"ATTACKER"}\n')
            os.close(attacker)
            try:
                with self.assertRaisesRegex(RuntimeError, "identity drift"):
                    runner.consume_exclusive_report_fd(
                        dirfd, "report.json", report_fd, created
                    )
                self.assertEqual(
                    os.stat("report.json", dir_fd=dirfd).st_size,
                    len(b'{"status":"ATTACKER"}\n'),
                )
            finally:
                os.close(report_fd)
                os.close(dirfd)

    def test_controlled_unknown_report_only(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            report = {"schema": "planora.pu-proj.frontier-joint-v19.fresh-report.v1", "status": "CONTROLLED_UNKNOWN", "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH", "checkpoint_or_incumbent_accessed": False, "admissible_as_solution": False}
            (directory / "runner-report.json").write_text(json.dumps(report), encoding="utf-8")
            write_child(directory, {"status": "CONTROLLED_UNKNOWN_PUBLISHED", "admissible_as_solution": False, "official_solution_xml_published": False})
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                status, errors, _ = guard.child_acceptance_v19(dirfd=fd, run_dir=directory, child_exit_code=3, observed_child_elapsed_seconds=1.0)
            finally:
                os.close(fd)
        self.assertEqual((status, errors), ("CONTROLLED_UNKNOWN", []))

    def test_controlled_unknown_rejects_xml(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            (directory / "solution.xml").write_bytes(b"x")
            (directory / "runner-report.json").write_text("{}", encoding="utf-8")
            write_child(directory, {"status": "CONTROLLED_UNKNOWN_PUBLISHED"})
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                status, errors, _ = guard.child_acceptance_v19(dirfd=fd, run_dir=directory, child_exit_code=3, observed_child_elapsed_seconds=1.0)
            finally:
                os.close(fd)
        self.assertEqual(status, "FAILED")
        self.assertIn("controlled_unknown_output_set_mismatch", errors)

    def test_complete_schema_and_report_last(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            solution = b"<solution/>\n"
            report = {"schema": "planora.pu-proj.frontier-joint-v19.fresh-report.v1", "status": "COMPLETE_VALID", "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH", "checkpoint_or_incumbent_accessed": False, "competitor_schedule_or_result_used": False, "competitor_placement_or_hint_used": False, "class_count": 8_813, "student_count": 38_437, "local_semantic_errors": [], "local_document_errors": [], "generic_validation": {"status": "COMPLETE_VALID", "classes": 8_813, "students": 38_437}}
            report_raw = json.dumps(report).encode()
            (directory / "solution.xml").write_bytes(solution)
            (directory / "runner-report.json").write_bytes(report_raw)
            write_child(directory, {"status": "COMPLETE_VALID_PUBLISHED", "class_count": 8_813, "student_count": 38_437, "admissible_as_solution": True, "official_solution_xml_published": True, "publication": {"solution.xml": {"publication_order": 1, "sha256": sha256(solution).hexdigest()}, "runner-report.json": {"publication_order": 2, "sha256": sha256(report_raw).hexdigest()}}})
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                status, errors, _ = guard.child_acceptance_v19(dirfd=fd, run_dir=directory, child_exit_code=0, observed_child_elapsed_seconds=1.0)
            finally:
                os.close(fd)
        self.assertEqual((status, errors), ("COMPLETE_VALID", []))

    def test_report_last_publication(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            row = os.fstat(fd)
            binding = {"fd": fd, "path": str(directory), "device": row.st_dev, "inode": row.st_ino, "mode": 0o700, "uid": os.getuid()}
            with mock.patch.dict(os.environ, {runner.OUTPUT_BINDING_ENV: json.dumps(binding)}):
                evidence = runner.publish_bundle({runner.OUTPUT_SOLUTION: b"xml", runner.OUTPUT_REPORT: b"report"})
            os.close(fd)
        self.assertEqual(evidence[runner.OUTPUT_SOLUTION]["publication_order"], 1)
        self.assertEqual(evidence[runner.OUTPUT_REPORT]["publication_order"], 2)


class SignalCleanupTests(unittest.TestCase):
    def test_blocked_parent_signals_are_unblocked(self) -> None:
        stop = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
        old = signal.pthread_sigmask(signal.SIG_BLOCK, stop)
        parent_pid = os.getpid()
        try:
            code = "import signal; print(sorted(s.name for s in signal.pthread_sigmask(signal.SIG_BLOCK, [])))"
            child = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, preexec_fn=lambda: guard._arm_child(parent_pid))
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
        self.assertEqual(child.returncode, 0)
        self.assertNotIn("SIGTERM", child.stdout)
        self.assertNotIn("SIGINT", child.stdout)
        self.assertNotIn("SIGHUP", child.stdout)

    def test_cooperative_stop_default_disposition(self) -> None:
        parent_pid = os.getpid()
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], preexec_fn=lambda: guard._arm_child(parent_pid))
        os.kill(child.pid, signal.SIGTERM)
        self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)

    def test_exited_leader_descendant_is_drained(self) -> None:
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(0.5)"
        leader = subprocess.Popen([sys.executable, "-c", code], preexec_fn=os.setsid)
        ownership = guard.create_owned_group(leader.pid)
        deadline = time.monotonic() + 2.0
        while len(ownership["members"]) < 2 and time.monotonic() < deadline:
            guard.admit_owned_members(ownership)
            time.sleep(0.02)
        self.assertGreaterEqual(len(ownership["members"]), 2)
        leader.wait(timeout=5)
        cleanup = guard.ensure_owned_group_empty(ownership)
        self.assertTrue(cleanup["empty"], cleanup)

    def test_reused_generation_before_first_snapshot_gets_zero_signals(self) -> None:
        ownership = {
            "leader_pid": 4242,
            "leader_identity": (1, 4242, 4242, 100),
            "leader_pidfd": 10,
            "members": {},
            "admission_errors": [],
            "leader_generation_gone": False,
        }
        reused = (1, 4242, 4242, 200)
        with mock.patch.object(guard, "_process_identity", return_value=None), mock.patch.object(
            guard, "_candidate_group_identities", return_value=[(4243, reused)]
        ), mock.patch.object(guard.signal, "pidfd_send_signal") as send, mock.patch.object(
            guard.os, "killpg"
        ) as killpg:
            cleanup = guard.ensure_owned_group_empty(ownership)
        send.assert_not_called()
        killpg.assert_not_called()
        self.assertEqual(cleanup["ambiguous_unowned_numeric_group_pids"], [4243])
        self.assertFalse(cleanup["empty"])

    def test_anchor_loss_during_scan_discards_pending_reused_member(self) -> None:
        anchor = (1, 4242, 4242, 100)
        reused_descendant = (4242, 4242, 4242, 200)
        ownership = {
            "leader_pid": 4242,
            "leader_identity": anchor,
            "leader_pidfd": 10,
            "members": {(4242, 100): {"pid": 4242, "identity": anchor, "pidfd": 10}},
            "admission_errors": [],
            "leader_generation_gone": False,
            "admission_sealed": False,
        }
        leader_replays = iter((anchor, anchor, None, None))

        def identity(pid: int):
            if pid == 4242:
                return next(leader_replays, None)
            if pid == 4243:
                return reused_descendant
            return None

        with mock.patch.object(guard, "_process_identity", side_effect=identity), mock.patch.object(
            guard, "_candidate_group_identities", return_value=[(4243, reused_descendant)]
        ), mock.patch.object(guard.os, "pidfd_open", return_value=77), mock.patch.object(
            guard.os, "close"
        ) as close, mock.patch.object(guard.signal, "pidfd_send_signal") as send:
            guard.admit_owned_members(ownership)
            result = guard.signal_owned_members(ownership, signal.SIGTERM)
        self.assertTrue(ownership["admission_sealed"])
        self.assertTrue(ownership["leader_generation_gone"])
        self.assertNotIn((4243, 200), ownership["members"])
        close.assert_called_once_with(77)
        send.assert_not_called()
        self.assertEqual(result["sent_pids"], [])

    def test_pidfd_member_errors_do_not_skip_later_members(self) -> None:
        identities = {
            100: (1, 100, 100, 10),
            101: (100, 100, 100, 11),
            102: (100, 100, 100, 12),
        }
        ownership = {
            "leader_pid": 100,
            "leader_identity": identities[100],
            "leader_pidfd": 20,
            "members": {(100, 10): {"pid": 100, "identity": identities[100], "pidfd": 20}},
            "admission_errors": [],
            "leader_generation_gone": False,
        }
        def open_pidfd(pid: int, _flags: int) -> int:
            if pid == 101:
                raise OSError("injected open failure")
            return 22
        with mock.patch.object(guard, "_process_identity", side_effect=lambda pid: identities.get(pid)), mock.patch.object(
            guard, "_candidate_group_identities", return_value=sorted(identities.items())
        ), mock.patch.object(guard.os, "pidfd_open", side_effect=open_pidfd):
            guard.admit_owned_members(ownership)
        self.assertIn((102, 12), ownership["members"])
        self.assertTrue(any(value.startswith("pidfd_open:101") for value in ownership["admission_errors"]))
        sends: list[int] = []
        def send_pidfd(fd: int, _signum: int) -> None:
            sends.append(fd)
            if fd == 22:
                raise OSError("injected send failure")
        with mock.patch.object(guard, "admit_owned_members"), mock.patch.object(
            guard, "_process_identity", side_effect=lambda pid: identities.get(pid)
        ), mock.patch.object(guard.signal, "pidfd_send_signal", side_effect=send_pidfd):
            result = guard.signal_owned_members(ownership, signal.SIGTERM)
        self.assertEqual(sends, [22, 20])
        self.assertEqual(result["sent_pids"], [100])
        self.assertTrue(result["errors"][0].startswith("pidfd_send:102"))

    def test_wait_failure_cannot_skip_final_drain(self) -> None:
        child = mock.Mock()
        child.wait.side_effect = OSError("injected wait failure")
        cleanup = {"empty": True, "errors": []}
        with mock.patch.object(guard, "ensure_owned_group_empty", return_value=cleanup) as drain:
            exit_code, error, observed = guard.wait_child_and_drain(child, {}, timeout=0.01)
        drain.assert_called_once_with({})
        self.assertEqual(exit_code, -1)
        self.assertIn("injected wait failure", error)
        self.assertIs(observed, cleanup)

    def test_post_popen_fault_is_inside_finally_drain(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        hook = source.index("POST_POPEN_ADMISSION_TEST_HOOK(child, process_group)")
        final = source.index("finally:", hook)
        self.assertLess(hook, final)
        self.assertIn("wait_child_and_drain(", source[final:final + 800])

    def test_provisional_pgid_precedes_monitoring(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        popen = source.index("child = subprocess.Popen(")
        pgid = source.index("process_group = child.pid", popen)
        ownership = source.index("ownership = create_owned_group(process_group)", pgid)
        release = source.index('os.write(barrier_write_fd, b"G")', ownership)
        monitor = source.index("while child.poll() is None", release)
        self.assertLess(pgid, ownership)
        self.assertLess(ownership, release)
        self.assertLess(release, monitor)


class RuntimeCompileWarningTests(unittest.TestCase):
    def test_sealed_loader_captures_compile_warnings_without_stderr(self) -> None:
        source = b"first = ~False\nsecond = ~True\n"
        descriptor = os.memfd_create(
            "puproj-v19-compile-warning-source",
            getattr(os, "MFD_ALLOW_SEALING", 2),
        )
        os.write(descriptor, source)
        os.fchmod(descriptor, 0o400)
        os.lseek(descriptor, 0, os.SEEK_SET)
        entry = {
            "fd": descriptor,
            "size": len(source),
            "sha256": sha256(source).hexdigest(),
        }
        bundle = runner.RuntimeBundleAdmission(
            3,
            4,
            "0" * 64,
            {"synthetic.py": entry},
            {},
            {},
            compile_warnings=[],
        )
        try:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = runner._SealedSourceLoader(
                    "synthetic", "synthetic.py", entry, bundle, False
                ).get_code("synthetic")
            self.assertIsInstance(code, types.CodeType)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(len(bundle.compile_warnings or []), 2)
            self.assertTrue(
                all(
                    row["category"] == "DeprecationWarning"
                    and row["source_relative_path"] == "synthetic.py"
                    and row["source_sha256"] == entry["sha256"]
                    for row in bundle.compile_warnings or []
                )
            )
        finally:
            os.close(descriptor)

    def test_compile_warning_contract_accepts_only_exact_two_pinned_rows(self) -> None:
        expected = {
            "category": "DeprecationWarning",
            "message": runner.CP_MODEL_COMPILE_WARNING_MESSAGE,
            "source_relative_path": runner.CP_MODEL_SOURCE_PATH,
            "source_sha256": runner.CP_MODEL_SOURCE_SHA256,
        }

        def bundle(rows):
            return runner.RuntimeBundleAdmission(
                3,
                4,
                "0" * 64,
                {
                    runner.CP_MODEL_SOURCE_PATH: {
                        "sha256": runner.CP_MODEL_SOURCE_SHA256,
                    }
                },
                {},
                {},
                compile_warnings=rows,
            )

        admitted = runner.admit_sealed_runtime_compile_warnings(
            bundle([dict(expected), dict(expected)])
        )
        self.assertEqual(admitted["count"], 2)
        self.assertEqual(admitted["observed_v17_stderr_bytes"], 411)
        self.assertEqual(
            admitted["observed_v17_stderr_sha256"],
            "59a10aaa235579022a6e84a089c42427f794e6de05ab74ded64de5874346c988",
        )
        self.assertEqual(admitted["child_stderr_bytes"], 0)
        mutations = (
            [dict(expected)],
            [dict(expected), dict(expected), dict(expected)],
            [{**expected, "category": "RuntimeWarning"}, dict(expected)],
            [{**expected, "message": "different"}, dict(expected)],
            [{**expected, "source_relative_path": "other.py"}, dict(expected)],
            [{**expected, "source_sha256": "0" * 64}, dict(expected)],
            [dict(expected), {"category": "UserWarning", "message": "unrelated"}],
        )
        for rows in mutations:
            with self.subTest(rows=rows), self.assertRaisesRegex(
                RuntimeError, "compile-warning contract"
            ):
                runner.admit_sealed_runtime_compile_warnings(bundle(rows))

        wrong_source = bundle([dict(expected), dict(expected)])
        wrong_source.entries_by_path[runner.CP_MODEL_SOURCE_PATH]["sha256"] = (
            "0" * 64
        )
        with self.assertRaisesRegex(RuntimeError, "source pin"):
            runner.admit_sealed_runtime_compile_warnings(wrong_source)

        missing_sink = bundle(None)
        with self.assertRaisesRegex(RuntimeError, "sink"):
            runner.admit_sealed_runtime_compile_warnings(missing_sink)


class ProbeTests(unittest.TestCase):
    def _valid_probe_child_report(self) -> dict[str, object]:
        expected_records = {
            root: guard.EXPECTED_HASHES[label]
            for root, label in {
                "ortools": "runtime_ortools_record", "numpy": "runtime_numpy_record",
                "pandas": "runtime_pandas_record", "dateutil": "runtime_dateutil_record",
                "six": "runtime_six_record", "lxml": "runtime_lxml_record",
                "absl": "runtime_absl_record", "immutabledict": "runtime_immutabledict_record",
                "google": "runtime_protobuf_record",
                "typing_extensions": "runtime_typing_extensions_record",
            }.items()
        }
        loaded_files = [loaded_runtime_row("package/libnative.so")]
        return {
            "schema": "planora.puproj.frontier-joint-v19-sealed-import-probe-child.v1",
            "status": "PASS",
            "elapsed_seconds": 1.0,
            "executing_python": {
                "sha256": guard.EXPECTED_HASHES["python_binary"],
                "identity": [1, 2, 6_831_736, 0o100000, 0o500, os.getuid(), 0],
                "sys_executable": "/proc/self/fd/9",
                "proc_self_exe_bound": True,
                "isolated": True,
                "no_site": True,
                "dont_write_bytecode": True,
                "transport": "sealed_executable_memfd",
            },
            "runtime_bundle": {
                "manifest_sha256": "a" * 64,
                "manifest_size": 100,
                "file_count": 3_077,
                "total_bytes": 191_956_270,
                "excluded_record_row_count": 2_098,
                "root_identity": [1, 2, 0o500, os.getuid()],
                "all_files_sealed_before_third_party_import": True,
                "pyc_entries_excluded": True,
                "transport": "read_only_symlink_tree_to_sealed_memfds",
            },
            "runtime_install": {
                "sealed_source_finder_installed": True,
                "native_dependency_memfds_preloaded": 1,
                "native_dependency_paths": ["package/libnative.so"],
                "native_dependency_preload_failures": [],
                "live_site_packages_on_sys_path": False,
            },
            "compile_warnings": {
                "schema": "planora.puproj.frontier-joint-v19.compile-warnings.v1",
                "status": "ADMITTED",
                "count": 2,
                "category": "DeprecationWarning",
                "message": runner.CP_MODEL_COMPILE_WARNING_MESSAGE,
                "source_relative_path": runner.CP_MODEL_SOURCE_PATH,
                "source_sha256": runner.CP_MODEL_SOURCE_SHA256,
                "observed_v17_stderr_bytes": 411,
                "observed_v17_stderr_sha256": (
                    "59a10aaa235579022a6e84a089c42427f794e6de05ab74ded64de5874346c988"
                ),
                "child_stderr_bytes": 0,
            },
            "loaded_runtime": {
                "python_version": "3.12",
                "python_cache_tag": "cpython-312",
                "python_executable_realpath": "/memfd:puproj-v19-python_binary (deleted)",
                "python_binary_sha256": guard.EXPECTED_HASHES["python_binary"],
                "pyc_reads_disabled_by_private_prefix": True,
                "dont_write_bytecode": True,
                "sealed_record_hashes": expected_records,
                "loaded_files": loaded_files,
                "loaded_file_count": 1,
                "loaded_manifest_sha256": loaded_runtime_manifest_sha256(
                    loaded_files
                ),
            },
            "system_runtime_comparison": {
                "start_file_count": 1,
                "end_file_count": 1,
                "start_subset_stable": True,
                "new_post_import_files": [],
                "start_python_module_count": 1,
                "end_python_module_count": 1,
                "new_post_import_python_modules": [],
                "boundary": "trusted_system_runtime_observed_and_hashed_not_sealed",
            },
            "imported_planora_modules": [
                {"module": f"benchmarks.{label}", "sha256": guard.EXPECTED_HASHES[label]}
                for label in sorted(guard.PLANORA_FRESH_MODULES)
            ],
            "imported_planora_module_count": 13,
            "official_instance_opened": False,
            "checkpoint_or_incumbent_opened": False,
            "solver_execution_started": False,
            "solver_child_process_started": False,
            "probe_child_process_started": True,
            "solve_call_count": 0,
            "official_solution_xml_published": False,
            "runner_sha256_start": guard.EXPECTED_RUNNER_SHA256,
            "runner_sha256_end": guard.EXPECTED_RUNNER_SHA256,
            "runner_hash_stable": True,
        }

    def test_probe_floor_blocks_before_any_capture(self) -> None:
        sample = {"mem_available_kib": guard.PROBE_INITIAL_MIN_MEM_AVAILABLE_KIB - 1,
                  "swap_free_kib": 0, "pswpin_pages": 0, "pswpout_pages": 0}
        with mock.patch.object(guard, "host_sample", return_value=sample), mock.patch.object(
            guard, "whole_launch_usage", return_value=(1, 0, (os.getpid(),))
        ), mock.patch.object(guard, "_stream_capture") as capture:
            result = guard.sealed_import_probe()
        capture.assert_not_called()
        self.assertEqual(result["resource_gate"], "probe_initial_memavailable_floor")
        self.assertFalse(result["official_instance_opened"])
        self.assertFalse(result["solver_child_process_started"])

    def test_probe_runtime_floor_timeout_and_caps(self) -> None:
        sample = {"mem_available_kib": guard.PROBE_RUNTIME_MIN_MEM_AVAILABLE_KIB,
                  "swap_free_kib": 0, "pswpin_pages": 0, "pswpout_pages": 0}
        base = dict(elapsed=0.0, group_rss_kib=0, group_vmswap_kib=0,
                    whole_rss_kib=0, whole_vmswap_kib=0, sample=sample)
        self.assertIsNone(guard.probe_breach(**base))
        for key, value, expected in (
            ("elapsed", guard.PROBE_HARD_WALL_SECONDS, "probe_hard_wall"),
            ("group_rss_kib", guard.PROBE_PROCESS_GROUP_RSS_LIMIT_KIB, "probe_process_group_rss_limit"),
            ("group_vmswap_kib", guard.PROBE_PROCESS_GROUP_VMSWAP_LIMIT_KIB, "probe_process_group_vmswap_limit"),
            ("whole_rss_kib", guard.PROBE_WHOLE_LAUNCH_MEMORY_LIMIT_KIB, "probe_whole_launch_vmrss_plus_vmswap_limit"),
        ):
            row = dict(base)
            row[key] = value
            self.assertEqual(guard.probe_breach(**row), expected)
        low = dict(base)
        low["sample"] = {**sample, "mem_available_kib": guard.PROBE_RUNTIME_MIN_MEM_AVAILABLE_KIB - 1}
        self.assertEqual(guard.probe_breach(**low), "probe_runtime_memavailable_floor")

    def test_probe_tamper_fails_before_child(self) -> None:
        sample = {"mem_available_kib": guard.PROBE_INITIAL_MIN_MEM_AVAILABLE_KIB,
                  "swap_free_kib": 0, "pswpin_pages": 0, "pswpout_pages": 0}
        with mock.patch.object(guard, "host_sample", return_value=sample), mock.patch.object(
            guard, "whole_launch_usage", return_value=(1, 0, (os.getpid(),))
        ), mock.patch.object(guard, "_stream_capture", side_effect=RuntimeError("tampered capture")), mock.patch.object(
            guard.subprocess, "Popen"
        ) as popen:
            with self.assertRaisesRegex(RuntimeError, "tampered capture"):
                guard.sealed_import_probe()
        popen.assert_not_called()

    def test_probe_excludes_official_and_has_no_solve_call(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        start = source.index("def sealed_import_probe()")
        end = source.index("def dry_run()", start)
        probe_source = source[start:end]
        self.assertIn('if label == "full_instance":', probe_source)
        self.assertNotIn("FULL_INSTANCE.read", probe_source)
        self.assertNotIn("solve_itc2019_native", runner.run_sealed_import_probe.__code__.co_names)

    def test_probe_chain_cleanup_and_report_last_are_explicit(self) -> None:
        bootstrap = BOOTSTRAP_SOURCE.read_text(encoding="utf-8")
        source = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn('"--sealed-import-probe"', bootstrap)
        command = guard.planned_command(16, 17, 18, 19, Path("/tmp/probe"), sealed_import_probe=True)
        self.assertEqual(command[-1], "--sealed-import-probe")
        start = source.index("def sealed_import_probe()")
        end = source.index("def dry_run()", start)
        segment = source[start:end]
        self.assertIn('run_dir / ".pycache-v19",', segment)
        self.assertNotIn(".pycache-v19-probe", segment)
        self.assertLess(segment.index("monitor_probe_child("), segment.index("publish_supervisor_report("))
        monitor_start = source.index("def monitor_probe_child(")
        monitor_end = source.index("def planned_command(", monitor_start)
        monitor_segment = source[monitor_start:monitor_end]
        self.assertIn("finally:", monitor_segment)
        self.assertIn("wait_child_and_drain(", monitor_segment)
        self.assertNotIn('"supervisor-report.json"', segment)
        self.assertLess(segment.index("publish_supervisor_report("), segment.index("consume_supervisor_report("))

    def test_probe_pycache_prefix_matches_environment_and_output_binding(self) -> None:
        output_path = Path("/tmp/planora-puproj-frontier-v19-test-output")
        output_binding = {
            "fd": 23,
            "path": str(output_path),
            "device": 1,
            "inode": 2,
            "mode": 0o700,
            "uid": os.getuid(),
        }
        runtime_binding = {"root_fd": 29}
        captures: dict[str, object] = {}
        environment = guard.minimal_child_environment(
            captures=captures,
            output_binding=output_binding,
            runtime_binding=runtime_binding,
            scratch_dir=Path("/tmp/scratch"),
        )
        expected_prefix = output_path / ".pycache-v19"
        command = guard.planned_command(
            16,
            17,
            29,
            19,
            expected_prefix,
            sealed_import_probe=True,
        )
        self.assertEqual(
            environment[guard.PYCACHE_PREFIX_ENV], str(expected_prefix)
        )
        self.assertEqual(
            command[command.index("-X") + 1], f"pycache_prefix={expected_prefix}"
        )

    def test_supervisor_emits_one_final_stdout_envelope_without_named_authority(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        main = source[source.index("def main() -> int:"):]
        self.assertEqual(main.count("sys.stdout.buffer.write(final_envelope)"), 1)
        self.assertNotIn("print(", main)
        self.assertIn('_probe_check_deadline(probe_deadline, "stdout:after_final_envelope")', main)
        self.assertNotIn('"path": str(parent / "supervisor-report.json")', source)

    def test_absolute_deadline_covers_capture_build_replay_and_publication(self) -> None:
        expired = time.monotonic() - 1.0
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            source = directory / "source"
            source.write_bytes(b"x")
            root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            identity = os.fstat(root_fd)
            parent_identity = (
                identity.st_dev, identity.st_ino, 0o700, os.getuid()
            )
            try:
                with self.assertRaisesRegex(TimeoutError, "capture"):
                    guard._stream_capture(source, sha256(b"x").hexdigest(), "late", probe_deadline=expired)
                with self.assertRaisesRegex(TimeoutError, "runtime_bundle"):
                    guard.build_runtime_bundle(runtime_root_fd=root_fd, captures={}, probe_mode=True, probe_deadline=expired)
                with self.assertRaisesRegex(TimeoutError, "runtime_replay"):
                    guard.replay_runtime_bundle({}, probe_deadline=expired)
                with self.assertRaisesRegex(TimeoutError, "publication"):
                    guard.publish_supervisor_report(
                        dirfd=root_fd,
                        parent=directory,
                        parent_identity=parent_identity,
                        payload={"status": "late"},
                        probe_deadline=expired,
                    )
                self.assertFalse((directory / "supervisor-report.json").exists())
            finally:
                os.close(root_fd)

    def test_monitor_exception_always_enters_drain(self) -> None:
        child = mock.Mock()
        child.poll.return_value = None
        cleanup = {"empty": True, "errors": []}
        with mock.patch.object(
            guard, "probe_accounting_snapshot", side_effect=RuntimeError("snapshot fault")
        ), mock.patch.object(
            guard, "wait_child_and_drain", return_value=(9, "wait fault", cleanup)
        ) as drain:
            result = guard.monitor_probe_child(
                child, {"leader_pid": 123}, deadline=time.monotonic() + 10
            )
        drain.assert_called_once()
        self.assertIn("snapshot fault", result["monitor_error"])
        self.assertIs(result["cleanup"], cleanup)

    def test_probe_accounting_snapshot_reconciles_exact_read_set(self) -> None:
        supervisor = 10
        child = 20
        sup_identity = (1, 10, 10, 100)
        child_identity = (1, 20, 20, 200)
        ownership = {
            "leader_pid": child,
            "members": {},
        }
        rows = [{"pid": child, "identity": child_identity, "pidfd": 1}]
        statuses = {
            f"/proc/{supervisor}/status": {"VmRSS": 7, "VmSwap": 2},
            f"/proc/{child}/status": {"VmRSS": 11, "VmSwap": 3},
        }
        with mock.patch.object(guard, "admit_owned_members"), mock.patch.object(
            guard, "_live_owned_members", return_value=rows
        ), mock.patch.object(
            guard,
            "_process_identity",
            side_effect=lambda pid: sup_identity if pid == supervisor else child_identity,
        ), mock.patch.object(
            guard, "_read_key_values", side_effect=lambda path: statuses[str(path)]
        ):
            snapshot = guard.probe_accounting_snapshot(supervisor, ownership)
        self.assertEqual(snapshot["group_rss_kib"], 11)
        self.assertEqual(snapshot["group_vmswap_kib"], 3)
        self.assertEqual(snapshot["whole_rss_kib"], 18)
        self.assertEqual(snapshot["whole_vmswap_kib"], 5)
        self.assertEqual(snapshot["pids"], [10, 20])
        self.assertTrue(snapshot["reconciled"])

    def test_probe_accounting_snapshot_rejects_identity_drift(self) -> None:
        identity = (1, 20, 20, 200)
        ownership = {"leader_pid": 20, "members": {}}
        calls = {20: 0}
        def identities(pid: int):
            if pid == 10:
                return (1, 10, 10, 100)
            calls[20] += 1
            return identity if calls[20] < 2 else (1, 20, 20, 201)
        with mock.patch.object(guard, "admit_owned_members"), mock.patch.object(
            guard, "_live_owned_members", return_value=[{"pid": 20, "identity": identity, "pidfd": 1}]
        ), mock.patch.object(guard, "_process_identity", side_effect=identities), mock.patch.object(
            guard, "_read_key_values", return_value={"VmRSS": 1, "VmSwap": 0}
        ):
            with self.assertRaisesRegex(RuntimeError, "identity drift"):
                guard.probe_accounting_snapshot(10, ownership)

    def test_retained_stdout_rejects_same_uid_name_swap(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            retained = os.open("child.stdout.log", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o400, dir_fd=dirfd)
            os.write(retained, b'{"status":"PASS"}\n')
            os.rename("child.stdout.log", "original.log", src_dir_fd=dirfd, dst_dir_fd=dirfd)
            swapped = os.open("child.stdout.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400, dir_fd=dirfd)
            os.write(swapped, b'{"status":"ATTACKER"}\n')
            os.close(swapped)
            try:
                with self.assertRaisesRegex(RuntimeError, "identity drift"):
                    guard._pread_retained_named(
                        dirfd, "child.stdout.log", retained,
                        maximum_bytes=1 << 20,
                        probe_deadline=time.monotonic() + 10,
                    )
            finally:
                os.close(retained)
                os.close(dirfd)

    def test_probe_child_report_exact_schema_and_malformed_rejection(self) -> None:
        valid = self._valid_probe_child_report()
        self.assertEqual(len(guard.PROBE_CHILD_SUCCESS_KEYS), 21)
        self.assertEqual(set(valid), guard.PROBE_CHILD_SUCCESS_KEYS)
        self.assertIs(guard.admit_probe_child_report(valid), valid)
        with self.assertRaisesRegex(RuntimeError, "exact schema"):
            guard.admit_probe_child_report({})
        malformed = dict(valid)
        malformed["runtime_bundle"] = {**valid["runtime_bundle"], "file_count": True}
        with self.assertRaisesRegex(RuntimeError, "runtime bundle"):
            guard.admit_probe_child_report(malformed)

    def test_probe_child_report_enforces_loaded_runtime_canonicalization_and_hash(
        self,
    ) -> None:
        first = loaded_runtime_row(
            "a/module.py", transport="sealed_descriptor_loader"
        )
        second = loaded_runtime_row("z/libnative.so", digest="c" * 64, size=2)
        for rows in ([second, first], [first, dict(first)]):
            report = self._valid_probe_child_report()
            report["loaded_runtime"] = {
                **report["loaded_runtime"],
                "loaded_files": rows,
                "loaded_file_count": len(rows),
                "loaded_manifest_sha256": loaded_runtime_manifest_sha256(rows),
            }
            with self.subTest(rows=rows), self.assertRaisesRegex(
                RuntimeError, "canonical order"
            ):
                guard.admit_probe_child_report(report)

        report = self._valid_probe_child_report()
        report["loaded_runtime"] = {
            **report["loaded_runtime"],
            "loaded_manifest_sha256": "0" * 64,
        }
        with self.assertRaisesRegex(RuntimeError, "manifest hash"):
            guard.admit_probe_child_report(report)

    def test_probe_child_report_rejects_compile_warning_evidence_drift(self) -> None:
        mutations = {
            "count": 1,
            "category": "RuntimeWarning",
            "message": "different",
            "source_relative_path": "other.py",
            "source_sha256": "0" * 64,
            "observed_v17_stderr_bytes": 410,
            "observed_v17_stderr_sha256": "0" * 64,
            "child_stderr_bytes": 1,
        }
        for key, value in mutations.items():
            report = self._valid_probe_child_report()
            report["compile_warnings"] = {
                **report["compile_warnings"],
                key: value,
            }
            with self.subTest(key=key), self.assertRaisesRegex(
                RuntimeError, "compile-warning evidence"
            ):
                guard.admit_probe_child_report(report)

    def test_probe_child_report_rejects_nan_inf_null_and_nested_type_drift(self) -> None:
        for elapsed in (float("nan"), float("inf"), float("-inf"), True, -1.0, guard.PROBE_HARD_WALL_SECONDS):
            report = self._valid_probe_child_report()
            report["elapsed_seconds"] = elapsed
            with self.assertRaisesRegex(RuntimeError, "elapsed"):
                guard.admit_probe_child_report(report)
        for key in ("executing_python", "runtime_install", "loaded_runtime", "system_runtime_comparison"):
            report = self._valid_probe_child_report()
            report[key] = None
            with self.assertRaises(RuntimeError):
                guard.admit_probe_child_report(report)
        report = self._valid_probe_child_report()
        report["runtime_install"] = {
            **report["runtime_install"],
            "native_dependency_memfds_preloaded": True,
        }
        with self.assertRaisesRegex(RuntimeError, "runtime install"):
            guard.admit_probe_child_report(report)

    def test_probe_child_diagnostics_distinguish_transport_and_json_failures(self) -> None:
        cases = (
            (b"", "empty_stdout"),
            (b"\xff", "stdout_decoding_failure"),
            (b'{"status":', "json_decode_failure"),
            (b"[]", "non_object_json"),
        )
        for stdout_raw, expected in cases:
            with self.subTest(expected=expected):
                report, rejection, streams = guard.diagnose_probe_child_report(
                    stdout_raw,
                    b"child failed\n",
                    child_exit_code=7,
                )
                self.assertIsNone(report)
                self.assertEqual(rejection["classification"], expected)
                self.assertEqual(rejection["child_exit_code"], 7)
                self.assertEqual(
                    rejection["transport_failures"],
                    ["child_exit_failure", "child_stderr_failure"],
                )
                self.assertEqual(rejection["streams"], streams)
                self.assertEqual(streams["stdout"]["size"], len(stdout_raw))
                self.assertEqual(
                    streams["stdout"]["sha256"],
                    sha256(stdout_raw).hexdigest(),
                )

        payload = json.dumps(self._valid_probe_child_report()).encode("utf-8")
        report, rejection, _ = guard.diagnose_probe_child_report(
            payload,
            b"",
            child_exit_code=7,
        )
        self.assertIsNone(report)
        self.assertEqual(rejection["classification"], "child_exit_failure")
        self.assertEqual(rejection["transport_failures"], ["child_exit_failure"])

        report, rejection, _ = guard.diagnose_probe_child_report(
            payload,
            b"warning\n",
            child_exit_code=0,
        )
        self.assertIsNone(report)
        self.assertEqual(rejection["classification"], "child_stderr_failure")
        self.assertEqual(rejection["transport_failures"], ["child_stderr_failure"])

    def test_probe_child_diagnostics_report_actual_schema_delta(self) -> None:
        payload = self._valid_probe_child_report()
        del payload["status"]
        payload["attacker"] = True
        report, rejection, _ = guard.diagnose_probe_child_report(
            json.dumps(payload).encode("utf-8"),
            b"",
            child_exit_code=0,
        )
        self.assertIsNone(report)
        self.assertEqual(rejection["classification"], "schema_key_mismatch")
        self.assertEqual(rejection["missing_keys"], ["status"])
        self.assertEqual(rejection["unexpected_keys"], ["attacker"])

    def test_probe_child_diagnostics_preserve_exact_success_admission(self) -> None:
        payload = self._valid_probe_child_report()
        report, rejection, streams = guard.diagnose_probe_child_report(
            json.dumps(payload).encode("utf-8"),
            b"",
            child_exit_code=0,
        )
        self.assertEqual(report, payload)
        self.assertIsNone(rejection)
        self.assertEqual(streams["child_exit_code"], 0)

        malformed = self._valid_probe_child_report()
        malformed["elapsed_seconds"] = None
        report, rejection, _ = guard.diagnose_probe_child_report(
            json.dumps(malformed).encode("utf-8"),
            b"",
            child_exit_code=0,
        )
        self.assertIsNone(report)
        self.assertEqual(
            rejection["classification"],
            "success_schema_admission_rejected",
        )
        self.assertEqual(rejection["missing_keys"], [])
        self.assertEqual(rejection["unexpected_keys"], [])
        self.assertIn("elapsed", rejection["admission_error"])

    def test_probe_child_diagnostics_bound_stderr_tail_as_base64(self) -> None:
        stderr_raw = b"prefix" + b"x" * (guard.PROBE_DIAGNOSTIC_TAIL_BYTES + 17)
        _, rejection, streams = guard.diagnose_probe_child_report(
            b"",
            stderr_raw,
            child_exit_code=23,
        )
        stderr = streams["stderr"]
        self.assertEqual(stderr["size"], len(stderr_raw))
        self.assertEqual(stderr["sha256"], sha256(stderr_raw).hexdigest())
        self.assertEqual(stderr["tail_size"], guard.PROBE_DIAGNOSTIC_TAIL_BYTES)
        self.assertTrue(stderr["tail_truncated"])
        self.assertEqual(
            base64.b64decode(stderr["tail_base64"], validate=True),
            stderr_raw[-guard.PROBE_DIAGNOSTIC_TAIL_BYTES:],
        )
        self.assertEqual(rejection["streams"], streams)

    def test_supervisor_envelope_never_creates_or_opens_a_named_report(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            parent = os.fstat(dirfd)
            parent_identity = (parent.st_dev, parent.st_ino, 0o700, os.getuid())
            try:
                with mock.patch.object(
                    guard, "_rename_noreplace",
                    side_effect=AssertionError("named publication forbidden"),
                ) as rename:
                    binding = guard.publish_supervisor_report(
                        dirfd=dirfd, parent=directory,
                        parent_identity=parent_identity, payload={"status": "PASS"},
                    )
                    evidence = guard.consume_supervisor_report(binding)
                rename.assert_not_called()
                self.assertEqual(list(directory.iterdir()), [])
                self.assertIsNone(evidence["authoritative_path"])
                self.assertIs(evidence["named_publication"], False)
            finally:
                os.close(dirfd)

    def test_supervisor_envelope_post_publish_aliases_cannot_replace_bytes(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            parent = os.fstat(dirfd)
            parent_identity = (parent.st_dev, parent.st_ino, 0o700, os.getuid())
            payload = {"status": "PASS", "truth": "original"}
            try:
                binding = guard.publish_supervisor_report(
                    dirfd=dirfd, parent=directory,
                    parent_identity=parent_identity, payload=payload,
                    probe_deadline=time.monotonic() + guard.PROBE_HARD_WALL_SECONDS,
                )
                (directory / "supervisor-report.json").write_text('{"attacker":true}\n')
                (directory / "stolen-report.json").write_text('{"attacker":true}\n')
                expected = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
                evidence = guard.consume_supervisor_report(binding)
                self.assertEqual(evidence["sha256"], sha256(expected).hexdigest())
                self.assertEqual(
                    evidence["verification_transport"],
                    "sealed_memfd_creation_binding_retained_fd_pread",
                )
                self.assertIsNotNone(evidence["publication_completed_elapsed_seconds"])
                self.assertEqual(list(directory.iterdir()), [])
            finally:
                os.close(dirfd)

    def test_late_descriptor_consumption_unlinks_all_report_aliases(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            parent = os.fstat(dirfd)
            parent_identity = (parent.st_dev, parent.st_ino, 0o700, os.getuid())
            def deadline(_deadline: float, phase: str) -> None:
                if phase == "publication:after_descriptor_replay":
                    raise TimeoutError("late final envelope")
            try:
                binding = guard.publish_supervisor_report(
                    dirfd=dirfd, parent=directory,
                    parent_identity=parent_identity, payload={"status": "PASS"},
                    probe_deadline=time.monotonic() + 10,
                )
                (directory / ".supervisor-report.pending-attacker").write_bytes(b"x")
                with mock.patch.object(guard, "_probe_check_deadline", side_effect=deadline):
                    with self.assertRaisesRegex(TimeoutError, "late final envelope"):
                        guard.consume_supervisor_report(binding)
                self.assertEqual(list(directory.iterdir()), [])
            finally:
                os.close(dirfd)

    def test_alias_swaps_during_pread_and_after_publisher_return_are_non_authoritative(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            parent = os.fstat(dirfd)
            parent_identity = (parent.st_dev, parent.st_ino, 0o700, os.getuid())
            original_pread = os.pread
            swapped = False
            def swap_during_pread(fd: int, size: int, offset: int) -> bytes:
                nonlocal swapped
                block = original_pread(fd, size, offset)
                if not swapped:
                    swapped = True
                    (directory / "supervisor-report.json").write_bytes(b'{"attacker":true}\n')
                    (directory / "replacement-report.json").write_bytes(b'{"attacker":2}\n')
                return block
            try:
                binding = guard.publish_supervisor_report(
                    dirfd=dirfd, parent=directory,
                    parent_identity=parent_identity,
                    payload={"status": "PASS", "truth": "original"},
                )
                # This is deliberately after publish_supervisor_report returned.
                (directory / "post-return-report.json").write_bytes(b'{"attacker":3}\n')
                with mock.patch.object(guard.os, "pread", side_effect=swap_during_pread):
                    evidence = guard.consume_supervisor_report(binding)
                self.assertTrue(swapped)
                self.assertEqual(evidence["size"], len(binding["raw"]))
                self.assertEqual(list(directory.iterdir()), [])
            finally:
                os.close(dirfd)

    def test_alias_created_after_final_descriptor_replay_is_purged(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            parent = os.fstat(dirfd)
            parent_identity = (parent.st_dev, parent.st_ino, 0o700, os.getuid())
            binding = guard.publish_supervisor_report(
                dirfd=dirfd, parent=directory,
                parent_identity=parent_identity,
                payload={"status": "PASS", "truth": "original"},
            )
            original_lstat = os.lstat
            injected = False
            def inject_after_parent_replay(path: object, *args: object, **kwargs: object) -> os.stat_result:
                nonlocal injected
                row = original_lstat(path, *args, **kwargs)
                if not injected and Path(path) == directory:
                    injected = True
                    (directory / "after-final-open-report.json").write_bytes(b'{"attacker":true}\n')
                return row
            try:
                with mock.patch.object(guard.os, "lstat", side_effect=inject_after_parent_replay):
                    evidence = guard.consume_supervisor_report(binding)
                self.assertTrue(injected)
                self.assertEqual(evidence["size"], len(binding["raw"]))
                self.assertEqual(list(directory.iterdir()), [])
            finally:
                os.close(dirfd)


class TrustTests(unittest.TestCase):
    def test_native_bootstrap_seals_before_execution(self) -> None:
        source = BOOTSTRAP_SOURCE.read_text(encoding="utf-8")
        self.assertIn("launcher stable-read SHA-256 drift", source)
        self.assertIn("launcher memfd sealing failed", source)
        self.assertIn("pre-exec launcher mutation", source)

    def test_direct_entries_fail_closed(self) -> None:
        launcher = subprocess.run([sys.executable, str(LAUNCHER)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        supervisor = subprocess.run([sys.executable, str(SUPERVISOR), "--self-test"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(launcher.returncode, 0)
        self.assertNotEqual(supervisor.returncode, 0)

    def test_v12_frozen_artifacts_preserved(self) -> None:
        expected = {
            "bootstrap": "70fcc016e76042b622ddfa6e7d4d98175791ec1d7dae388daabba7d0c9e201f0",
            "bootstrap-rebuild": "70fcc016e76042b622ddfa6e7d4d98175791ec1d7dae388daabba7d0c9e201f0",
            "bootstrap.c": "2de8972b5ba8ce0372ed71a18fc56fa56779f6ac0d9b6ea27bc22c0a9d13601e",
            "completion-certificate.json": "f4750d6b297d4419d7ecba5dfc55aaced2f82f19fc7b0b865e7f6a5c01006b18",
            "freeze.json": "1af3adfcfb8df4294e4113fa60cd23c86b841c91ca0aebb6482a3176d875f26f",
            "generic-validator.py": "eb9a4360e3f4a33afd84109b5bf32664439604a09601daeaeb0a66a8b36101dc",
            "launcher.py": "60d050eaecf678544e49238f2d8a2a4fa4289e36126be16fe15a67f7202f761c",
            "runner.py": "f647bf45168f392b9deb3274c498305a0cc892b8638af8535569dc2d0a03a6f2",
            "supervisor.py": "c1cf1d7ba1cf23b7870d7eaa9005a821dbe9a847f8d2dbd09d4f898e95de89c2",
            "tests.py": "35575480b412f02fbcd84c10a273cc2a99c236f0757929f3b1983c36647ca9a5",
        }
        for suffix, digest in expected.items():
            with self.subTest(suffix=suffix):
                source = Path(f"/tmp/planora-puproj-frontier-joint-v12-{suffix}")
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest)

    def test_v13_frozen_artifacts_preserved(self) -> None:
        source_root = ROOT / "benchmarks/probe_diagnostics/puproj_v13"
        expected = {
            "bootstrap": "2513884b035414bbd328724c4d6d884572931001b09b928d37d2e51ef9e0dde6",
            "bootstrap-rebuild": "2513884b035414bbd328724c4d6d884572931001b09b928d37d2e51ef9e0dde6",
            "bootstrap.c": "6d7b4f603a99fb22e6af7d64952a022bb4b8ab8cea00a1b67e6527ef9615c1d1",
            "completion-certificate.json": "6461a87ebd19889165b01ec05d42d42894f30017b0d5b2dbbf4ee72066cd8ded",
            "freeze.json": "0836ced34739218ad240853461f8044a15f88598a4c99f6484a76bdfec008bfc",
            "generic-validator.py": "7ca75fbe256c212130307d574ca1ef2592f46461b3eb33ef0ba2d5b4f8cfcc8c",
            "launcher.py": "04381450d30ef86077c0101b16f700768db605ff17aa006c29a3bcdfd23eef39",
            "runner.py": "f639590511d2d4de5de9caf722bbc2cdb1fba692951cb38e580634cf24ff6e1b",
            "supervisor.py": "e3cc3701b4f08f1dea0ead3adfd7b4ee2f3fc4e830f5df170d649ed5c5e30ec7",
            "tests.py": "94b6e7e3ba2a9ada1bdd849ef60eedd07ff79d18a6d5c701bb63c02789f2d274",
        }
        for suffix, digest in expected.items():
            with self.subTest(suffix=suffix):
                source = source_root / f"planora-puproj-frontier-joint-v13-{suffix}"
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest)

    def test_v14_frozen_artifacts_preserved(self) -> None:
        source_root = ROOT / "benchmarks/probe_diagnostics/puproj_v14"
        expected = {
            "bootstrap": "ced513c673e12cc0923e2261bff37287011eb52d9501ef1aa99d830f8a5e5c7b",
            "bootstrap-rebuild": "ced513c673e12cc0923e2261bff37287011eb52d9501ef1aa99d830f8a5e5c7b",
            "bootstrap.c": "5e2e00881d0a5a0873999747019411aa0184df1f5945dbacda4f320f0d997425",
            "completion-certificate.json": "cbda1f16f30640e11cc5df9c33a4ffa2e4ae4edd3265af71c55b9ca897937b9e",
            "freeze.json": "a3ec337d9d02e137655141654fccb5cceab7949fc528776d98d546452cf46b40",
            "generic-validator.py": "6a0809dab1787967147f02d788511705ef7eca661e07edc128ad66792ce9a2af",
            "launcher.py": "c75e0236a99dc60ec9b5bf1426e25fd61864540adad721b339b1dd605366b849",
            "runner.py": "a5983d898eee5240bca1e23901f4f6d5e0ee3025b730b42205ea530f509bd9de",
            "supervisor.py": "995d592eff641800c01b1621e06ff13bcfbffb1fe4106ad9ab93fa44f294e20f",
            "tests.py": "c8ecb191a17fe6733d757518f04306e854dd9c86ec151f7bfc79f4571c409dc5",
        }
        for suffix, digest in expected.items():
            with self.subTest(suffix=suffix):
                source = source_root / f"planora-puproj-frontier-joint-v14-{suffix}"
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest)

    def test_v15_frozen_artifacts_preserved(self) -> None:
        source_root = ROOT / "benchmarks/probe_diagnostics/puproj_v15"
        expected = {
            "bootstrap": "b8814856dceaee3e9c1b9d5cb6dcfc3eb6d73d7392dbc76934d6891e357d2879",
            "bootstrap-rebuild": "b8814856dceaee3e9c1b9d5cb6dcfc3eb6d73d7392dbc76934d6891e357d2879",
            "bootstrap.c": "9860fe6f7948b1730d6bcdb83604b835dcba904b707c2d6b1e21bd71e415988b",
            "completion-certificate.json": "02c4604a1fa85cc90ed1f99a0bea77e348a755f3fcbb3165398656cce806b8c2",
            "freeze.json": "b4b3a5486ca13339185c7c5b0c0e95b3f51a8d9d939726002d42d1a6f4fda8b3",
            "generic-validator.py": "77aa7390efeb19fd329c1686f23ab580ddbcd3efd81f0802a5a60bcb9e471370",
            "launcher.py": "5c47b9369c7b4d488c0c78d41ae1cc206f5d21364d500799e5020afdb3aff5b2",
            "runner.py": "43d3badb2edd1329d2b18cfa5cb0a7453e947b3e2904780305288d427975af16",
            "supervisor.py": "64f94250645f1288c25f62c5ce333d0c2eef44b094e61d60d693c02263851e88",
            "tests.py": "fad7b848a7b29aa562423436dab5a5aee8992a1739368d3df5c8fca515a6250e",
        }
        for suffix, digest in expected.items():
            with self.subTest(suffix=suffix):
                source = source_root / f"planora-puproj-frontier-joint-v15-{suffix}"
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest)

    def test_v16_frozen_artifacts_preserved(self) -> None:
        source_root = ROOT / "benchmarks/probe_diagnostics/puproj_v16"
        expected = {
            "bootstrap": "130fc1e8b3008dbfa06e93fa8d90f191edb6cf495420c9525762f0dd7faa7a92",
            "bootstrap-rebuild": "130fc1e8b3008dbfa06e93fa8d90f191edb6cf495420c9525762f0dd7faa7a92",
            "bootstrap.c": "2257cdf22e38f04be44b282850136d4889b18b3270202a965f390a922e3025a1",
            "completion-certificate.json": "edd47c41585df720e14f310130f9d5b12715146ba45e1e7a5adef2c98743b3dd",
            "freeze.json": "27c9c8df4ccc7028456b567a470c79a27b3c7239ad6fc46b210d0c98632c2a5c",
            "generic-validator.py": "a42091c4caf96bbab3ae78771b4d5a013ab90df327423f976cd615aff8d913a3",
            "launcher.py": "c278835e21563039e1baa4564d19432dbf972b0c84c3da301019088d1349b69f",
            "runner.py": "e2a10c4d1e934d86523a4680fc0d77620a7f260112ca75361766ed1a5f5d78e9",
            "stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
            "supervisor.py": "4fee7a5084beba30e2948e7fa0db31d2bf1399ad6012c0c7be1c2fc97f7c8e22",
            "tests.py": "f5221ec905bf43d32744ec7b84b04c162e288193ccc3a71aabb6841da4b1c0c8",
        }
        for suffix, digest in expected.items():
            with self.subTest(suffix=suffix):
                source = source_root / f"planora-puproj-frontier-joint-v16-{suffix}"
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest)

    def test_v17_frozen_artifacts_preserved(self) -> None:
        source_root = ROOT / "benchmarks/probe_diagnostics/puproj_v17"
        expected = {
            "bootstrap": "0da05d3dc001279ba04dff15c5d9677dc131c3f332641b2ed8276188a425bf8e",
            "bootstrap-rebuild": "0da05d3dc001279ba04dff15c5d9677dc131c3f332641b2ed8276188a425bf8e",
            "bootstrap.c": "d2f6f492309193683f2c35bc6fc124b5c982514e1609505ad052bd2f2ce19547",
            "completion-certificate.json": "d9dd330b662b6a156221c9d64054d6a3bef92454b99a6a76f4a634cc7c03e043",
            "freeze.json": "f26d95e3dd035943bbb85fa4164a76baeb8d3e7f94df51e96f732ba4983db315",
            "generic-validator.py": "dec76fcfbdc384135a0f2e1f134d1a0e31d73cdd520164a11fcaa1bb679d3dd3",
            "launcher.py": "ba66eab59248eb90fd5649bae58eb5fbddb46270cdb79bc20fb32bbd394a198b",
            "runner.py": "e2aee5251b73437b59b023a7de061420f90276baaed8d867e2ad9f9ef03b21f0",
            "stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
            "supervisor.py": "0bfe6f0209575ae7e78cf125f1c15ca59d4e455584c5e66238d7b73f46c55c6a",
            "tests.py": "92f89e8aeab7aa2d7b4aad4593450031070cdfc08d2238f0720f7c9a0016f6f3",
        }
        for suffix, digest in expected.items():
            with self.subTest(suffix=suffix):
                source = source_root / f"planora-puproj-frontier-joint-v17-{suffix}"
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest)

    def test_v18_frozen_artifacts_preserved(self) -> None:
        source_root = ROOT / "benchmarks/probe_diagnostics/puproj_v18"
        expected = {
            "bootstrap": "36f1d8c87230dfa4ecfba8154c9a973ee9d2e8739710709155c3ff3507e65d4a",
            "bootstrap-rebuild": "36f1d8c87230dfa4ecfba8154c9a973ee9d2e8739710709155c3ff3507e65d4a",
            "bootstrap.c": "9cf1fb26534c3db07a875d6894305814ad412ccd57c0bd2383177a46b14a646c",
            "completion-certificate.json": "14571e69cb4fb192a5223c636f8445d451fd1dac4fcd4949c1482f80c1f5ecc1",
            "freeze.json": "cf08aae157dda8c96161678ef98c3862ad48f42aecdffe7d85ecffd1b2ebfa24",
            "generic-validator.py": "883b9457428aec1e1521f5800e2726c39a0620439fd49bec338e8b12fc75c7e2",
            "launcher.py": "fdc8f7e1ba37eefef5b67afe5e69bcc476970ef99d6fbf27b1ad1c7bee542b4d",
            "runner.py": "a6a016ed13db09879a9c9d3ad9ae7dd565f92a8ac0a225063ec5f6ddafe2b2d6",
            "stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
            "supervisor.py": "6b43d34ad8056e863e0a164faac76ebc709c8acdaf09e34af9867792dd85c0f4",
            "tests.py": "a13ef43852bbe1eddc5c3aacd9090a752d359c28a51f0375490f7d4886405669",
        }
        for suffix, digest in expected.items():
            with self.subTest(suffix=suffix):
                source = source_root / f"planora-puproj-frontier-joint-v18-{suffix}"
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest)

    def test_v19_manifest_certificate_and_internal_pins_match_exact_bytes(self) -> None:
        freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
        certificate = json.loads(CERTIFICATE.read_text(encoding="utf-8"))
        self.assertEqual(
            freeze["schema"],
            "planora.pu-proj.frontier-joint-v19-freeze.v1",
        )
        self.assertEqual(
            certificate["schema"],
            "planora.pu-proj.frontier-joint-v19.completion-certificate.v1",
        )
        self.assertEqual(
            freeze["trust_root"]["path"],
            str(BOOTSTRAP),
        )
        self.assertEqual(
            freeze["trust_root"]["sha256"],
            sha256(BOOTSTRAP.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            freeze["trust_root"]["source_sha256"],
            sha256(BOOTSTRAP_SOURCE.read_bytes()).hexdigest(),
        )
        paths = {
            "launcher": LAUNCHER,
            "supervisor": SUPERVISOR,
            "runner": RUNNER,
            "generic_validator": GENERIC,
            "stdlib_manifest": STDLIB_MANIFEST,
            "tests": Path(__file__).resolve(),
        }
        for label, path in paths.items():
            with self.subTest(label=label):
                row = freeze["artifacts"][label]
                digest = sha256(path.read_bytes()).hexdigest()
                self.assertEqual(row["path"], str(path))
                self.assertEqual(row["sha256"], digest)
                self.assertEqual(row["size"], path.stat().st_size)
                self.assertEqual(certificate["artifacts"][label], digest)
        self.assertEqual(
            guard.EXPECTED_RUNNER_SHA256,
            sha256(RUNNER.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            sealed_launcher.EXPECTED_SUPERVISOR_SHA256,
            sha256(SUPERVISOR.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            runner.EXPECTED_HASHES["generic_validator"],
            sha256(GENERIC.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            guard.EXPECTED_HASHES["generic_validator"],
            sha256(GENERIC.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            certificate["freeze_manifest"]["sha256"],
            sha256(FREEZE.read_bytes()).hexdigest(),
        )
        self.assertFalse(freeze["verification"]["official_launch_authorized"])
        self.assertEqual(
            certificate["verification"]["official_launch_or_solve"],
            "NOT_RUN",
        )

    def test_v3_hashes_preserved(self) -> None:
        expected = {"bootstrap": "4760e1c23c3784a5cec7aee4bc359076166a4f5de1e67f0c9cf914ee8eac215d", "bootstrap.c": "5333ac60014aeb5d86eea364e9b836c348549c61697daa243fcdc20a8582d77f", "launcher.py": "b1d4fb78f4efbd329e59c44afbfe7d45e47e44af765ba7ef184fb2a605fbbb6f", "runner.py": "554100e2db00f5ff3d512357b1a0c0819eb29813e0c898204f107880f550728d", "supervisor.py": "472c8853ce651e2cd1191c2322e83dcd8d95a2703ffabe2835e8e4cd3fcf46e2", "tests.py": "6756580cc6d8bb3aa036bf0575954ade68f18dc2920c47cd42c26981f0d9266d", "freeze.json": "2e875b495d03aa522487467a92e1c1d8c5e807f4aa5751346a1c4900408c3d0a"}
        for suffix, digest in expected.items():
            self.assertEqual(sha256(Path(f"/tmp/planora-puproj-frontier-joint-v3-{suffix}").read_bytes()).hexdigest(), digest)

    def test_v6_hashes_preserved(self) -> None:
        expected = {
            "bootstrap": "c6be018b77d1cef4f9af8a6ba3ef382c6b1e3055692a57f7776b13689a97d0bf",
            "bootstrap.c": "cf507dd788e639ee3c1598a763961fbe21adedee59bfd97f6de796116197e9fb",
            "launcher.py": "8100d3212db15247f7170956d22185d332a79f2d7b1a5469f0ca5180d725aa6f",
            "supervisor.py": "0c813bcdad89e83f622587c8eb523086a1107d1b4b4bd75e6afc742890e4f45b",
            "runner.py": "935934b73e2df6bbe48ddad855cfbe4089f40a43a51b84a8d70391be957cc9f4",
            "generic-validator.py": "3737d1579d8da80c28397dc030f7b3533dd70e9f0a78b670ab506166569618e6",
            "tests.py": "afa310cc0ceeff07071e8271406bfd3f5ec9881ed0dbf055912ec224795deb07",
            "freeze.json": "15443925b448c98df0fdea8c421237920e4de5c344dd6b2d49c1cfd14478a131",
            "completion-certificate.json": "b55ca28d7aaa35dfe5594703259f0e06a4fc55ed861f8f4aef679abcdd108ee1",
        }
        for suffix, digest in expected.items():
            self.assertEqual(
                sha256(Path(f"/tmp/planora-puproj-frontier-joint-v6-{suffix}").read_bytes()).hexdigest(),
                digest,
            )

    def test_v7_hashes_preserved(self) -> None:
        expected = {
            "bootstrap": "a9dcdd7165cdf569dac0f7caac59e2c151dcc51e89627e00d89f708f48fe4ad7",
            "bootstrap.c": "373d71445187e10de54454a6ec29815dc619ab33ef91af772664bd845ff9b554",
            "launcher.py": "2a4a4a7a6f1ecfd3adae03d18a3e33fdbda9641727bbb52a884d507a157dcb76",
            "supervisor.py": "9cdc9077aa66853ba1f9810d55b6bbead2afe84171b86526e7b08824cba45ecd",
            "runner.py": "df99ba079fd1e5fa546cabcb58f1b843f8c4f1a481680a472df6398baf3e935f",
            "generic-validator.py": "1c28645b2491941c41a23252e30107217c84b6ad0f24e68c4e57eae221dcbb68",
            "tests.py": "a8960a08be7f1442d4c918ef0c69d7a54ba29816c0e8b065a212f456e481e908",
            "freeze.json": "22747134545a0a65bed827c8936e3e3d78bd1ee21eab5f6113028e069f835b43",
            "completion-certificate.json": "d4c4e56ff858e1cf63d635d1ba7ee22098fabc7f0292bfc9070f702c17b996fc",
        }
        for suffix, digest in expected.items():
            self.assertEqual(
                sha256(Path(f"/tmp/planora-puproj-frontier-joint-v7-{suffix}").read_bytes()).hexdigest(),
                digest,
            )

    def test_v8_hashes_preserved(self) -> None:
        expected = {
            "bootstrap": "ed5c84c1d4d50294c30a24943aea402355833f64bc7d994499a8a3ba418a1fb6",
            "bootstrap.c": "998131863c4baee4d4f20f00e36ffbddc9cd7d0548fa26c2ffdecd769a98da89",
            "launcher.py": "73d0a4cf0f57eec9ddee123b7e0fada984b95169016f3dcd73c3b21683959b26",
            "supervisor.py": "474ba04e7807bb5510993bc1db58b0ce99c5469dd58411d51610c2311e6ab80b",
            "runner.py": "0f168386e1ecb7bf6c8291453035c2e37301bb4cf994bd7bdb98c4a929cfe709",
            "generic-validator.py": "f7ce15bd5428309df642f51a40c58468473a3a4ef87c83ee4e9deb992d21421f",
            "tests.py": "ae82b05752fabbfec6edb8f96ebb0681fbae7e9d0d200fcab2647730520e6b4a",
            "freeze.json": "a4ebb8cb0da941c0af3ae5a7b97ac72300d2bde0c1a678a38338ab5c44a0f062",
            "completion-certificate.json": "4991e776e4008136b4bc2d924ac966ad3d4318700515ecbf10a01abd73354f49",
        }
        for suffix, digest in expected.items():
            self.assertEqual(
                sha256(Path(f"/tmp/planora-puproj-frontier-joint-v8-{suffix}").read_bytes()).hexdigest(),
                digest,
            )

    def test_v9_hashes_preserved(self) -> None:
        expected = {
            "bootstrap": "c6663860f1b426b3c79c2b16d030ea5c94b48da7d8cfaf307b05b31b6a276871",
            "bootstrap.c": "a5274aab5aa18135f2d27d82001bb022ab2cb2a0b3f1ed09f9e7778e39ef7045",
            "launcher.py": "a5b899bd69f4ba69987a8a552596850f350912a6337d3ad9f1c89733d28a043a",
            "supervisor.py": "2961e8e9ba2b615c42f6043bb7deda7360a9d202a98acf7e9c20c1fd103bbb79",
            "runner.py": "49476742c4a783ae090ce7d606f943d288da402e45a85514ab16c070867a08df",
            "generic-validator.py": "8f77a5b4e71450523894111b7a6db07957f438ccc31b42a1afd7eb94dde4101e",
            "tests.py": "a7e8edaf9c1b132f0cdba39fe8c3b0f0157133cf2069a4052b8a12d373ab3a22",
            "freeze.json": "84452591c62b7512d599c9f8bea3207391dbfa987be34d06b456785dc1337415",
            "completion-certificate.json": "612f70f422da8b69e78b191256f02067a28ff1bacdd639ee0240c9ebae0ac189",
        }
        for suffix, digest in expected.items():
            self.assertEqual(
                sha256(Path(f"/tmp/planora-puproj-frontier-joint-v9-{suffix}").read_bytes()).hexdigest(),
                digest,
            )

    def test_v10_hashes_preserved(self) -> None:
        expected = {
            "bootstrap": "e74ced20593cee8301a4547818a5ade9bb38d4d6e1ed0edc8eaa51394f53f1e0",
            "bootstrap.c": "7f84cd0073d52ddebf9740d620904ab2aa8150d02d1ab7b98c31da9a58dcd18d",
            "launcher.py": "6b726b95437999cefd893258e9f4cc32c73d682c56ade491a9bed6d41cf4cb4c",
            "supervisor.py": "b3f4924bd6e7e873d2200865109b04107d2b6b13fa559ccabc14ab6c008abcb9",
            "runner.py": "0b352378662f4ba46ee0c142dcc26c8285f0215078fafcbfd338b917031ca912",
            "generic-validator.py": "ef46b683d01f869a9a0f321477d12f6fb00f6f9233b37511d71cdd900d37acba",
            "tests.py": "0a84b178ec94e40f7776c2155e517a935c8aa363a36b1c00de27e93d11c836e0",
            "freeze.json": "3700a3f3dcf9af94a803c009bcbb5a2d67a53a4267c5b877653663512962f667",
            "completion-certificate.json": "c62fec3921cd9ecaa74a0ac4c7f80062849867d9ccd08d25c418a0212139de11",
        }
        for suffix, digest in expected.items():
            self.assertEqual(
                sha256(Path(f"/tmp/planora-puproj-frontier-joint-v10-{suffix}").read_bytes()).hexdigest(),
                digest,
            )

    def test_v11_hashes_preserved(self) -> None:
        expected = {
            "bootstrap": "0b5764dc0fc510ed2462338b935792118ea0aedeff945a9bec780fa6ba210d03",
            "bootstrap.c": "55d319f53e78acd417a47c07a627d9d6c41435fac2543363d7cd8b42d2ee9fcf",
            "launcher.py": "78fd07c38f23dbf6a2555c6c565dcecc2f9eeac808cb5f37f6fc8cb93b51ad32",
            "supervisor.py": "eef788959da2e4a9f06f0c9297826f9a2ccaefbfb930dbc4abf3f6dd591dda35",
            "runner.py": "22c62b4cca368fa214b832a33ff40fb7c86259f24348558f53527178f2487334",
            "generic-validator.py": "60a5f713d5bdca30c7f3b2d792118a68309c1d903292fdb24f1cac3dad0191ee",
            "tests.py": "0e0524118a2653b8eda4c9b168867c6dad0e9fff131d32fd3fe3851ebd3b51e1",
            "freeze.json": "11b0fc56f8d7b4009d4d410d055b140c181bdf35348e2d03a5d1eae6ef3ca1b7",
            "completion-certificate.json": "5b5d2c7fad92128c7d247803c0750ecc84bce1d89832ddb0fc9f1164d4934efb",
        }
        for suffix, digest in expected.items():
            self.assertEqual(
                sha256(Path(f"/tmp/planora-puproj-frontier-joint-v11-{suffix}").read_bytes()).hexdigest(),
                digest,
            )

    def test_sources_compile(self) -> None:
        for path in (RUNNER, SUPERVISOR, LAUNCHER, GENERIC):
            compile(path.read_bytes(), str(path), "exec")


if __name__ == "__main__":
    unittest.main(verbosity=2)
