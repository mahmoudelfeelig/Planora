#!/usr/bin/env python3
"""Lightweight static and adversarial gates for PU-PROJ v12."""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

RUNNER = Path("/tmp/planora-puproj-frontier-joint-v12-runner.py")
SUPERVISOR = Path("/tmp/planora-puproj-frontier-joint-v12-supervisor.py")
LAUNCHER = Path("/tmp/planora-puproj-frontier-joint-v12-launcher.py")
BOOTSTRAP = Path("/tmp/planora-puproj-frontier-joint-v12-bootstrap")
BOOTSTRAP_SOURCE = Path("/tmp/planora-puproj-frontier-joint-v12-bootstrap.c")
GENERIC = Path("/tmp/planora-puproj-frontier-joint-v12-generic-validator.py")
ROOT = Path("/mnt/d/Stuff/Projects/Sites/Planora")
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


runner = load(RUNNER, "puproj_v12_runner_tested")
guard = load(SUPERVISOR, "puproj_v12_supervisor_tested")


def write_child(directory: Path, payload: dict[str, object]) -> None:
    payload.setdefault("runner_sha256_start", guard.EXPECTED_RUNNER_SHA256)
    payload.setdefault("runner_sha256_end", guard.EXPECTED_RUNNER_SHA256)
    payload.setdefault("runner_hash_stable", True)
    (directory / "child.stdout.log").write_text(json.dumps(payload), encoding="utf-8")
    (directory / "child.stderr.log").write_bytes(b"")


class ArchitectureTests(unittest.TestCase):
    def test_fresh_mode_excludes_all_resume_sources(self) -> None:
        for label in ("checkpoint", "stripped_instance", "derivation", "frontier"):
            self.assertNotIn(label, guard.CAPTURE_SOURCES)
            self.assertNotIn(label, runner.EXPECTED_HASHES)

    def test_exact_official_hash_and_cardinality(self) -> None:
        self.assertEqual(runner.EXPECTED_CLASS_COUNT, 8_813)
        self.assertEqual(runner.EXPECTED_STUDENT_COUNT, 38_437)
        self.assertEqual(runner.EXPECTED_HASHES["full_instance"], "2fa848bf039f8ef86f65e280b5302afd37c48a03e1bc7e09364cf91bebd86e42")

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
            report = {"schema": "planora.pu-proj.frontier-joint-v12.fresh-report.v1", "status": "CONTROLLED_UNKNOWN", "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH", "checkpoint_or_incumbent_accessed": False, "admissible_as_solution": False}
            (directory / "runner-report.json").write_text(json.dumps(report), encoding="utf-8")
            write_child(directory, {"status": "CONTROLLED_UNKNOWN_PUBLISHED", "admissible_as_solution": False, "official_solution_xml_published": False})
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                status, errors, _ = guard.child_acceptance_v12(dirfd=fd, run_dir=directory, child_exit_code=3, observed_child_elapsed_seconds=1.0)
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
                status, errors, _ = guard.child_acceptance_v12(dirfd=fd, run_dir=directory, child_exit_code=3, observed_child_elapsed_seconds=1.0)
            finally:
                os.close(fd)
        self.assertEqual(status, "FAILED")
        self.assertIn("controlled_unknown_output_set_mismatch", errors)

    def test_complete_schema_and_report_last(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            solution = b"<solution/>\n"
            report = {"schema": "planora.pu-proj.frontier-joint-v12.fresh-report.v1", "status": "COMPLETE_VALID", "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH", "checkpoint_or_incumbent_accessed": False, "competitor_schedule_or_result_used": False, "competitor_placement_or_hint_used": False, "class_count": 8_813, "student_count": 38_437, "local_semantic_errors": [], "local_document_errors": [], "generic_validation": {"status": "COMPLETE_VALID", "classes": 8_813, "students": 38_437}}
            report_raw = json.dumps(report).encode()
            (directory / "solution.xml").write_bytes(solution)
            (directory / "runner-report.json").write_bytes(report_raw)
            write_child(directory, {"status": "COMPLETE_VALID_PUBLISHED", "class_count": 8_813, "student_count": 38_437, "admissible_as_solution": True, "official_solution_xml_published": True, "publication": {"solution.xml": {"publication_order": 1, "sha256": sha256(solution).hexdigest()}, "runner-report.json": {"publication_order": 2, "sha256": sha256(report_raw).hexdigest()}}})
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                status, errors, _ = guard.child_acceptance_v12(dirfd=fd, run_dir=directory, child_exit_code=0, observed_child_elapsed_seconds=1.0)
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
        return {
            "schema": "planora.puproj.frontier-joint-v12-sealed-import-probe-child.v1",
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
            "loaded_runtime": {
                "python_version": "3.12",
                "python_cache_tag": "cpython-312",
                "python_executable_realpath": "/memfd:puproj-v12-python_binary (deleted)",
                "python_binary_sha256": guard.EXPECTED_HASHES["python_binary"],
                "pyc_reads_disabled_by_private_prefix": True,
                "dont_write_bytecode": True,
                "sealed_record_hashes": expected_records,
                "loaded_files": [{
                    "path": "package/libnative.so",
                    "sha256": "b" * 64,
                    "size": 1,
                    "transport": "sealed_native_descriptor",
                }],
                "loaded_file_count": 1,
                "loaded_manifest_sha256": "c" * 64,
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
        self.assertLess(segment.index("monitor_probe_child("), segment.index("publish_supervisor_report("))
        monitor_start = source.index("def monitor_probe_child(")
        monitor_end = source.index("def planned_command(", monitor_start)
        monitor_segment = source[monitor_start:monitor_end]
        self.assertIn("finally:", monitor_segment)
        self.assertIn("wait_child_and_drain(", monitor_segment)
        self.assertNotIn('"supervisor-report.json"', segment)
        self.assertLess(segment.index("publish_supervisor_report("), segment.index("consume_supervisor_report("))

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
        self.assertIs(guard.admit_probe_child_report(valid), valid)
        with self.assertRaisesRegex(RuntimeError, "exact schema"):
            guard.admit_probe_child_report({})
        malformed = dict(valid)
        malformed["runtime_bundle"] = {**valid["runtime_bundle"], "file_count": True}
        with self.assertRaisesRegex(RuntimeError, "runtime bundle"):
            guard.admit_probe_child_report(malformed)

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
