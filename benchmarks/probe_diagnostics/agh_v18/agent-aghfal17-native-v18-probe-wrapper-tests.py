#!/usr/bin/env python3
"""Windows-safe static and mocked tests for the inert AGH v18 probe wrapper."""

from __future__ import annotations

import ast
from contextlib import redirect_stderr
import copy
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
CHAIN = Path(__file__).resolve().parent
WRAPPER_PATH = ROOT / "scripts" / "run_agh_v18_canonical_probe.py"
AUTHORIZATION_PATH = CHAIN / (
    "agent-aghfal17-native-v18-probe-authorization-20260827T063650Z-b06b75d9.json"
)


def load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "agh_v18_probe_wrapper_tested", WRAPPER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("wrapper import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load_wrapper()


class AuthorizationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authorization_raw = AUTHORIZATION_PATH.read_bytes()
        self.authorization = wrapper.exact_json_bytes(
            self.authorization_raw, "authorization"
        )
        self.wrapper_raw = WRAPPER_PATH.read_bytes()

    def test_authorization_is_canonical_and_binds_current_wrapper(self) -> None:
        wrapper.validate_authorization(
            self.authorization, self.wrapper_raw, wrapper.WRAPPER
        )
        row = self.authorization["execution_wrapper"]
        self.assertEqual(row["size_bytes"], len(self.wrapper_raw))
        self.assertEqual(row["sha256"], sha256(self.wrapper_raw).hexdigest())

    def test_authorization_is_exactly_one_probe_and_nothing_more(self) -> None:
        self.assertEqual(
            self.authorization["decision"],
            "AUTHORIZE_EXACTLY_ONE_BOUNDED_CANONICAL_PROBE",
        )
        self.assertIs(self.authorization["retained_probe_authorized"], True)
        self.assertEqual(self.authorization["authorized_execution_count"], 1)
        for key in (
            "official_launch_authorized",
            "official_input_authorized",
            "solver_authorized",
            "checkpoint_authorized",
            "certified_incumbent_authorized",
            "competitor_route_authorized",
            "publication_authorized",
            "automatic_retry_authorized",
        ):
            self.assertIs(self.authorization[key], False, key)
        self.assertEqual(
            self.authorization["static_chain_review"]["wrapper_execution_review"],
            "PENDING_SEPARATE_REVIEWER",
        )
        isolation = self.authorization["isolation_contract"]
        self.assertEqual(isolation["snapshot_mount_path"], "/snapshot")
        self.assertEqual(
            isolation["private_snapshot_host_path"], wrapper.SNAPSHOT_HOST_WSL
        )
        self.assertIs(isolation["snapshot_read_only_bind"], True)
        self.assertIs(isolation["tmp_mirrors_read_only_from_snapshot"], True)
        self.assertIs(isolation["snapshot_cleanup_required_before_pass_receipt"], True)
        self.assertIs(isolation["live_host_root_bound_read_only"], True)
        self.assertIs(isolation["live_repository_root_bound"], False)
        self.assertIs(isolation["live_drive_root_bound"], False)
        self.assertEqual(isolation["private_live_drive_mask"], "/mnt")
        self.assertEqual(isolation["working_directory"], "/snapshot")
        self.assertEqual(
            isolation["repository_visible_subtree"], wrapper.SITE_PACKAGES_WSL
        )

    def test_predecessor_and_mutated_authorizations_reject(self) -> None:
        mutations = (
            ("candidate", "native-v17"),
            ("run_id", "0" * 32),
            ("authorized_execution_count", 2),
            ("automatic_retry_authorized", True),
            ("checkpoint_authorized", True),
            ("competitor_route_authorized", True),
        )
        for key, value in mutations:
            candidate = copy.deepcopy(self.authorization)
            candidate[key] = value
            with self.assertRaises(wrapper.ContractError, msg=key):
                wrapper.validate_authorization(
                    candidate, self.wrapper_raw, wrapper.WRAPPER
                )

        predecessor = self.authorization["rejected_predecessor"]
        self.assertEqual(predecessor["candidate"], "native-v17")
        self.assertIs(predecessor["accepted_by_this_wrapper"], False)

    def test_mutated_wrapper_hash_and_unknown_authorization_key_reject(self) -> None:
        changed = copy.deepcopy(self.authorization)
        changed["execution_wrapper"]["sha256"] = "0" * 64
        with self.assertRaises(wrapper.ContractError):
            wrapper.validate_authorization(changed, self.wrapper_raw, wrapper.WRAPPER)

    def test_recursive_type_exact_authorization_rejects_bool_int_substitutions(
        self,
    ) -> None:
        mutations = (
            (("retained_probe_authorized",), 1),
            (("authorized_execution_count",), True),
            (("frozen_limits", "initial_sample_count"), 2.0),
            (("static_chain_review", "windows_tests_passed"), 72.0),
            (("isolation_contract", "live_host_root_bound"), 0),
            (("watcher_contract", "postflight_zero_snapshots"), 2.0),
            (("execution_wrapper", "size_bytes"), True),
        )
        for path, replacement in mutations:
            candidate = copy.deepcopy(self.authorization)
            target = candidate
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.assertRaises(wrapper.ContractError, msg=str(path)):
                wrapper.validate_authorization(
                    candidate, self.wrapper_raw, wrapper.WRAPPER
                )
        changed = copy.deepcopy(self.authorization)
        changed["unexpected"] = False
        with self.assertRaises(wrapper.ContractError):
            wrapper.validate_authorization(changed, self.wrapper_raw, wrapper.WRAPPER)

    def test_unconsumed_real_run_id_has_no_claim_or_receipt(self) -> None:
        self.assertFalse(wrapper.CLAIM.exists())
        self.assertFalse(wrapper.RESULT_RECEIPT.exists())


class AtomicStateTests(unittest.TestCase):
    def test_explicit_flag_is_required_before_claim(self) -> None:
        with redirect_stderr(io.StringIO()):
            self.assertEqual(wrapper.main([]), 64)
        self.assertFalse(wrapper.CLAIM.exists())

    def test_claim_and_receipt_are_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claim = root / "run.claim"
            owner = claim / "owner.json"
            payload = wrapper.claim_once(claim, owner, Path("/mock/wrapper.py"))
            self.assertEqual(payload["run_id"], wrapper.RUN_ID)
            self.assertTrue(claim.is_dir())
            self.assertTrue(owner.is_file())
            with self.assertRaises(FileExistsError):
                wrapper.claim_once(claim, owner, Path("/mock/wrapper.py"))

            receipt = root / "result.json"
            wrapper.write_create_only(receipt, b"{}\n")
            with self.assertRaises(FileExistsError):
                wrapper.write_create_only(receipt, b"{}\n")

    def test_preexisting_retained_output_is_rejected(self) -> None:
        original = wrapper.RETAINED_OUTPUTS
        with tempfile.TemporaryDirectory() as temporary:
            retained = Path(temporary) / "preexisting.json"
            retained.write_bytes(b"{}\n")
            wrapper.RETAINED_OUTPUTS = (retained,)
            try:
                with self.assertRaises(wrapper.ContractError):
                    wrapper.assert_retained_outputs_absent()
            finally:
                wrapper.RETAINED_OUTPUTS = original


class ResourceAndExecutionContractTests(unittest.TestCase):
    @staticmethod
    def frozen_outer_argv() -> list[str]:
        raw = (CHAIN / "agent-aghfal17-native-v18-invocations.json").read_bytes()
        return json.loads(raw)["probe"]["argv"]

    @staticmethod
    def frozen_official_path() -> str:
        raw = (CHAIN / "agent-aghfal17-native-v18-review-freeze.json").read_bytes()
        return json.loads(raw)["official_input"]["path"]

    def test_two_sample_gate_requires_both_samples_interval_and_census(self) -> None:
        times = iter((10.0, 15.0))
        gate = wrapper.two_sample_resource_gate(
            sample=lambda: 1_900_000,
            census=lambda: {"status": "PASS", "rejected_count": 0},
            sleeper=lambda _seconds: None,
            clock=lambda: next(times),
        )
        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(len(gate["samples"]), 2)

        low_times = iter((10.0, 15.0))
        samples = iter((1_900_000, 1_899_999))
        rejected = wrapper.two_sample_resource_gate(
            sample=lambda: next(samples),
            census=lambda: {"status": "PASS", "rejected_count": 0},
            sleeper=lambda _seconds: None,
            clock=lambda: next(low_times),
        )
        self.assertEqual(rejected["status"], "NO_GO")

    def test_host_execution_has_strict_timeout_mask_and_single_bwrap(self) -> None:
        official = self.frozen_official_path()
        argv = wrapper.host_execution_argv(official, self.frozen_outer_argv())
        self.assertEqual(
            argv[:4],
            [
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=5s",
                "250s",
            ],
        )
        self.assertEqual(argv.count("/usr/bin/bwrap"), 1)
        mask_index = argv.index("/dev/null")
        self.assertEqual(argv[mask_index + 1], official)
        self.assertIn("--unshare-all", argv)
        self.assertIn("--new-session", argv)
        self.assertIn("--die-with-parent", argv)
        self.assertIn("--tmpfs", argv)
        chdir = argv.index("--chdir")
        self.assertEqual(argv[chdir + 1], "/snapshot")
        snapshot_index = argv.index(wrapper.SNAPSHOT_HOST_WSL)
        self.assertEqual(argv[snapshot_index + 1], "/snapshot")
        for name in wrapper.STAGED_NAMES:
            source = f"/snapshot/{name}"
            source_index = argv.index(source)
            self.assertEqual(argv[source_index - 1], "--ro-bind")
            self.assertEqual(argv[source_index + 1], f"/tmp/{name}")
        read_only_binds = {
            (argv[index + 1], argv[index + 2])
            for index, token in enumerate(argv[:-2])
            if token == "--ro-bind"
        }
        self.assertIn(("/", "/"), read_only_binds)
        self.assertNotIn(
            (wrapper.REPOSITORY_WSL, wrapper.REPOSITORY_WSL), read_only_binds
        )
        self.assertNotIn(("/mnt/d", "/mnt/d"), read_only_binds)
        self.assertIn(
            (wrapper.SITE_PACKAGES_WSL, wrapper.RUNTIME_ALIAS_WSL),
            read_only_binds,
        )
        self.assertIn(
            (wrapper.RUNTIME_ALIAS_WSL, wrapper.SITE_PACKAGES_WSL),
            read_only_binds,
        )
        repository_sources = {
            source
            for source, _destination in read_only_binds
            if source.startswith(f"{wrapper.REPOSITORY_WSL}/")
        }
        self.assertEqual(repository_sources, {wrapper.SITE_PACKAGES_WSL})
        drive_mask = next(
            index
            for index, token in enumerate(argv[:-1])
            if token == "--tmpfs" and argv[index + 1] == "/mnt"
        )
        runtime_capture = argv.index(wrapper.SITE_PACKAGES_WSL)
        runtime_replay = argv.index(wrapper.SITE_PACKAGES_WSL, runtime_capture + 1)
        self.assertLess(runtime_capture, drive_mask)
        self.assertLess(drive_mask, runtime_replay)
        private_tmp = next(
            index
            for index, token in enumerate(argv[:-1])
            if token == "--tmpfs" and argv[index + 1] == "/tmp"
        )
        self.assertLess(snapshot_index, private_tmp)
        self.assertFalse(wrapper.FORBIDDEN_ROUTE_TOKENS.intersection(argv))

    def test_snapshot_is_private_create_only_hash_bound_and_removed(self) -> None:
        captures = {name: (CHAIN / name).read_bytes() for name in wrapper.FROZEN_TREE}
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "snapshot"
            with mock.patch.object(wrapper, "SNAPSHOT_HOST", snapshot):
                evidence = wrapper.stage_private_snapshot(captures)
                self.assertEqual(evidence["host_path"], str(snapshot))
                self.assertEqual(evidence["mount_path"], "/snapshot")
                self.assertEqual(set(evidence["files"]), set(wrapper.STAGED_NAMES))
                for name in wrapper.STAGED_NAMES:
                    self.assertEqual(
                        sha256((snapshot / name).read_bytes()).hexdigest(),
                        wrapper.FROZEN_TREE[name]["sha256"],
                    )
                self.assertTrue(wrapper.cleanup_private_snapshot(evidence))
                self.assertFalse(snapshot.exists())


class HostileFailureRegressionTests(unittest.TestCase):
    def test_watcher_identity_exception_terminates_kills_and_waits(self) -> None:
        class FakeChild:
            pid = 4242

            def __init__(self) -> None:
                self.reaped = False
                self.wait_arguments: list[object] = []

            def poll(self):
                return -9 if self.reaped else None

            def wait(self, timeout=None):
                self.wait_arguments.append(timeout)
                if timeout == 5:
                    raise wrapper.subprocess.TimeoutExpired("mock", timeout)
                self.reaped = True
                return -9

        fake = FakeChild()
        signals: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            replacements = {
                "STDOUT": root / "stdout.json",
                "STDERR": root / "stderr.log",
                "WATCHER": root / "watcher.json",
                "EXIT_CODE": root / "exit-code.txt",
            }
            with (
                mock.patch.multiple(wrapper, **replacements),
                mock.patch.object(wrapper.subprocess, "Popen", return_value=fake),
                mock.patch.object(
                    wrapper,
                    "process_identity",
                    side_effect=wrapper.ContractError("hostile watcher identity"),
                ),
                mock.patch.object(
                    wrapper.os,
                    "killpg",
                    side_effect=lambda pgid, sent: signals.append((pgid, sent)),
                    create=True,
                ),
            ):
                with self.assertRaises(wrapper.ContractError):
                    wrapper.run_with_watcher(("mock-child",))
        self.assertIn((4242, wrapper.signal.SIGTERM), signals)
        self.assertIn((4242, getattr(wrapper.signal, "SIGKILL", 9)), signals)
        self.assertEqual(fake.wait_arguments, [5, None])
        self.assertTrue(fake.reaped)

    def test_normal_root_exit_still_terminates_kills_and_waits_descendants(
        self,
    ) -> None:
        class FakeChild:
            pid = 4242

            def __init__(self) -> None:
                self.wait_arguments: list[object] = []

            def poll(self):
                return 0

            def wait(self, timeout=None):
                self.wait_arguments.append(timeout)
                return 0

        fake = FakeChild()
        descendant = (5001, 200)
        descendant_alive = True
        group_signals: list[tuple[int, int]] = []
        pid_signals: list[tuple[int, int]] = []

        def alive(identities):
            if descendant_alive and descendant in identities:
                return [
                    {
                        "pid": descendant[0],
                        "starttime_ticks": descendant[1],
                        "process_group": 5000,
                        "session": 5000,
                    }
                ]
            return []

        def signal_group(group, sent):
            nonlocal descendant_alive
            group_signals.append((group, sent))
            if group == 5000 and sent == getattr(wrapper.signal, "SIGKILL", 9):
                descendant_alive = False

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            replacements = {
                "STDOUT": root / "stdout.json",
                "STDERR": root / "stderr.log",
                "WATCHER": root / "watcher.json",
                "EXIT_CODE": root / "exit-code.txt",
            }
            with (
                mock.patch.multiple(wrapper, **replacements),
                mock.patch.object(wrapper.subprocess, "Popen", return_value=fake),
                mock.patch.object(
                    wrapper, "process_identity", return_value=(4242, 1, 100)
                ),
                mock.patch.object(
                    wrapper,
                    "_descendant_tracking_snapshot",
                    return_value=({(4242, 100), descendant}, {4242, 5000}),
                ),
                mock.patch.object(wrapper, "_usage_kib", return_value=(0, 0)),
                mock.patch.object(wrapper, "_alive_tracking", side_effect=alive),
                mock.patch.object(wrapper, "_alive_identities", return_value=[]),
                mock.patch.object(
                    wrapper.os, "killpg", side_effect=signal_group, create=True
                ),
                mock.patch.object(
                    wrapper.os,
                    "kill",
                    side_effect=lambda pid, sent: pid_signals.append((pid, sent)),
                ),
            ):
                watcher = wrapper.run_with_watcher(("mock-child",))

        self.assertEqual(watcher["status"], "PASS")
        self.assertIs(watcher["mandatory_cleanup"]["cleanup_complete"], True)
        self.assertIn((5000, wrapper.signal.SIGTERM), group_signals)
        self.assertIn((5000, getattr(wrapper.signal, "SIGKILL", 9)), group_signals)
        self.assertIn((5001, wrapper.signal.SIGTERM), pid_signals)
        self.assertEqual(fake.wait_arguments, [5, None])
        self.assertFalse(descendant_alive)

    def test_hostile_baseexception_creates_minimal_receipt_without_stringifying(
        self,
    ) -> None:
        stringified = False

        class Hostile(BaseException):
            def __str__(self) -> str:
                nonlocal stringified
                stringified = True
                raise AssertionError("hostile __str__ invoked")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claim = root / "run.claim"
            claim.mkdir()
            receipt = root / "result.json"
            with (
                mock.patch.object(wrapper, "CLAIM", claim),
                mock.patch.object(wrapper, "RESULT_RECEIPT", receipt),
                mock.patch.object(wrapper, "_main_impl", side_effect=Hostile()),
            ):
                self.assertEqual(wrapper.main([]), 2)
            result = wrapper.exact_json_bytes(receipt.read_bytes(), "result")
        self.assertFalse(stringified)
        self.assertEqual(result["status"], "NO_GO")
        self.assertIs(result["authorization_consumed"], True)
        self.assertIs(result["automatic_retry_authorized"], False)
        self.assertIs(result["minimal_post_claim_failure_receipt"], True)
        self.assertEqual(result["failure_type"], "Hostile")

    def test_memoryerror_uses_precomputed_low_level_static_receipt(self) -> None:
        failure_modes = ("serialization", "publication")
        for failure_mode in failure_modes:
            with self.subTest(failure_mode=failure_mode):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    claim = root / "run.claim"
                    claim.mkdir()
                    receipt = root / "result.json"
                    patches = [
                        mock.patch.object(wrapper, "CLAIM", claim),
                        mock.patch.object(wrapper, "RESULT_RECEIPT", receipt),
                        mock.patch.object(
                            wrapper, "_main_impl", side_effect=MemoryError()
                        ),
                    ]
                    if failure_mode == "serialization":
                        patches.append(
                            mock.patch.object(
                                wrapper, "canonical_bytes", side_effect=MemoryError()
                            )
                        )
                    else:
                        patches.append(
                            mock.patch.object(
                                wrapper,
                                "write_create_only",
                                side_effect=MemoryError(),
                            )
                        )
                    with patches[0], patches[1], patches[2], patches[3]:
                        self.assertEqual(wrapper.main([]), 2)
                    self.assertEqual(
                        receipt.read_bytes(), wrapper.STATIC_FAILURE_RECEIPT
                    )
                    payload = json.loads(receipt.read_bytes())
                    self.assertEqual(payload["status"], "NO_GO")
                    self.assertIs(payload["authorization_consumed"], True)

    def test_static_receipt_os_failure_is_the_explicit_storage_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claim = root / "run.claim"
            claim.mkdir()
            receipt = root / "result.json"
            with (
                mock.patch.object(wrapper, "CLAIM", claim),
                mock.patch.object(wrapper, "RESULT_RECEIPT", receipt),
                mock.patch.object(wrapper, "_main_impl", side_effect=MemoryError()),
                mock.patch.object(
                    wrapper, "canonical_bytes", side_effect=MemoryError()
                ),
                mock.patch.object(
                    wrapper,
                    "low_level_static_failure_receipt",
                    side_effect=OSError("mock storage boundary"),
                ),
            ):
                with self.assertRaises(OSError):
                    wrapper.main([])
            self.assertFalse(receipt.exists())

    def test_postflight_dependency_and_runtime_drift_reject(self) -> None:
        captures = {
            "agent-aghfal17-native-v18-review-freeze.json": wrapper.canonical_bytes({})
        }
        with (
            mock.patch.object(wrapper, "verify_frozen_chain", return_value=captures),
            mock.patch.object(
                wrapper,
                "verify_runtime_closure",
                return_value={"runtime_record_rows": 3, "runtime_pin_rows": 2},
            ),
            mock.patch.object(
                wrapper,
                "verify_source_closure",
                side_effect=wrapper.ContractError("dependency drift"),
            ),
        ):
            with self.assertRaises(wrapper.ContractError):
                wrapper.postflight_revalidate()

        with (
            mock.patch.object(wrapper, "verify_frozen_chain", return_value=captures),
            mock.patch.object(
                wrapper,
                "verify_runtime_closure",
                side_effect=wrapper.ContractError("runtime drift"),
            ),
        ):
            with self.assertRaises(wrapper.ContractError):
                wrapper.postflight_revalidate()


def valid_payloads() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    child: dict[str, object] = {key: None for key in wrapper.CHILD_KEYS}
    child.update(
        {
            "schema": "planora.agh-fal17.native-v18-sealed-import-probe.v1",
            "status": "PASS",
            "official_instance_opened": False,
            "official_opened": False,
            "official_solution_xml_published": False,
            "solver_child_process_started": False,
            "solver_execution_started": False,
            "publication": False,
        }
    )
    inner: dict[str, object] = {key: None for key in wrapper.INNER_KEYS}
    inner.update(
        {
            "schema": "planora.agh-fal17.native-v18-sealed-import-supervisor.v1",
            "status": "PASS",
            "errors": [],
            "breach": None,
            "checkpoint_or_certified_provenance_used": False,
            "official_instance_opened": False,
            "official_opened": False,
            "official_solution_xml_published": False,
            "solver_child_process_started": False,
            "solver_execution_started": False,
            "publication": False,
            "process_group_cleanup": {"empty": True, "errors": []},
            "child_payload": child,
        }
    )
    outer: dict[str, object] = {key: None for key in wrapper.OUTER_KEYS}
    outer.update(
        {
            "schema": "planora.agh-fal17.native-v18-outer-controller.v1",
            "status": "PASS",
            "mode": "probe",
            "errors": [],
            "breach": None,
            "checkpoint_or_certified_provenance_used": False,
            "official_instance_opened": False,
            "solver_child_process_started": False,
            "publication": False,
            "inner_payload": inner,
            "post_exit_empty": True,
            "cleanup": {
                "empty": True,
                "errors": [],
                "final_discovery_snapshots": [
                    {"status": "ZERO"},
                    {"status": "ZERO"},
                ],
            },
        }
    )
    watcher = {
        "status": "PASS",
        "child_exit_code": 0,
        "wrapper_guard_triggered": False,
        "live_until_child_exit": True,
        "live_through_postflight": True,
        "mandatory_cleanup": {
            "term_attempted": True,
            "kill_attempted": True,
            "wait_attempted": True,
            "wait_completed": True,
            "remaining_after_kill": [],
            "cleanup_complete": True,
        },
        "postflight_zero_snapshots": [
            {"status": "ZERO", "alive": []},
            {"status": "ZERO", "alive": []},
        ],
    }
    return outer, watcher, inner


class StrictResultContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preflight = {"status": "PASS", "forbidden_routes_present": False}
        self.postflight = {
            "pins_stable_after_execution": True,
            "dependency_closure_stable_after_execution": True,
            "runtime_records_stable_after_execution": True,
            "runtime_pins_stable_after_execution": True,
            "authorization_snapshot_stable": True,
            "wrapper_pin_stable": True,
            "snapshot_cleanup_verified": True,
            "shared_lock_release_verified": True,
        }

    def evaluate(self, outer: dict[str, object], watcher: dict[str, object]):
        return wrapper.evaluate_result(outer, watcher, self.preflight, self.postflight)

    def test_exact_truthful_pass_fixture_accepts(self) -> None:
        outer, watcher, _inner = valid_payloads()
        predicates, errors = self.evaluate(outer, watcher)
        self.assertEqual(errors, [])
        self.assertTrue(all(predicates.values()))

    def test_absent_null_zero_string_false_true_and_mismatch_reject(self) -> None:
        key = "checkpoint_or_certified_provenance_used"
        attacks: tuple[object, ...] = (None, 0, "false", True)
        for value in attacks:
            outer, watcher, inner = valid_payloads()
            outer[key] = value
            _predicates, errors = self.evaluate(outer, watcher)
            self.assertIn("acceptance:checkpoint_pair_exact_false", errors)
            outer, watcher, inner = valid_payloads()
            inner[key] = value
            _predicates, errors = self.evaluate(outer, watcher)
            self.assertIn("acceptance:checkpoint_pair_exact_false", errors)

        outer, watcher, inner = valid_payloads()
        del outer[key]
        _predicates, errors = self.evaluate(outer, watcher)
        self.assertIn("acceptance:outer_keys_exact", errors)
        self.assertIn("acceptance:checkpoint_pair_exact_false", errors)
        outer, watcher, inner = valid_payloads()
        del inner[key]
        _predicates, errors = self.evaluate(outer, watcher)
        self.assertIn("acceptance:inner_keys_exact", errors)
        self.assertIn("acceptance:checkpoint_pair_exact_false", errors)

        outer, watcher, inner = valid_payloads()
        outer[key] = True
        inner[key] = False
        self.assertIn(
            "acceptance:checkpoint_pair_exact_false",
            self.evaluate(outer, watcher)[1],
        )
        outer[key] = False
        inner[key] = True
        self.assertIn(
            "acceptance:checkpoint_pair_exact_false",
            self.evaluate(outer, watcher)[1],
        )

    def test_unknown_or_missing_schema_keys_reject(self) -> None:
        outer, watcher, inner = valid_payloads()
        outer["unexpected"] = False
        self.assertIn("acceptance:outer_keys_exact", self.evaluate(outer, watcher)[1])
        outer, watcher, inner = valid_payloads()
        inner["unexpected"] = False
        self.assertIn("acceptance:inner_keys_exact", self.evaluate(outer, watcher)[1])
        outer, watcher, inner = valid_payloads()
        inner["child_payload"]["unexpected"] = False
        self.assertIn("acceptance:child_keys_exact", self.evaluate(outer, watcher)[1])

    def test_cleanup_watcher_postflight_and_lock_fail_closed(self) -> None:
        outer, watcher, _inner = valid_payloads()
        outer["cleanup"]["final_discovery_snapshots"][-1]["status"] = "NONZERO"
        self.assertIn(
            "acceptance:outer_two_zero_snapshots",
            self.evaluate(outer, watcher)[1],
        )
        outer, watcher, _inner = valid_payloads()
        watcher["live_through_postflight"] = False
        self.assertIn("acceptance:watcher_pass", self.evaluate(outer, watcher)[1])
        outer, watcher, _inner = valid_payloads()
        watcher["mandatory_cleanup"]["cleanup_complete"] = False
        self.assertIn(
            "acceptance:watcher_mandatory_cleanup",
            self.evaluate(outer, watcher)[1],
        )
        outer, watcher, _inner = valid_payloads()
        self.postflight["shared_lock_release_verified"] = False
        self.assertIn(
            "acceptance:shared_lock_release_verified",
            self.evaluate(outer, watcher)[1],
        )
        for field in (
            "dependency_closure_stable_after_execution",
            "runtime_records_stable_after_execution",
            "runtime_pins_stable_after_execution",
            "snapshot_cleanup_verified",
        ):
            self.setUp()
            self.postflight[field] = False
            outer, watcher, _inner = valid_payloads()
            self.assertIn(f"acceptance:{field}", self.evaluate(outer, watcher)[1])

    def test_exact_json_requires_canonical_single_object_lf(self) -> None:
        value = {"b": 2, "a": False}
        canonical = b'{"a":false,"b":2}\n'
        self.assertEqual(wrapper.exact_json_bytes(canonical, "fixture"), value)
        for invalid in (
            b'{"b":2,"a":false}\n',
            b'{"a": false,"b":2}\n',
            b"{}\n{}\n",
            b'{"a":NaN}\n',
        ):
            with self.assertRaises(wrapper.ContractError):
                wrapper.exact_json_bytes(invalid, "fixture")


class StaticOrderingTests(unittest.TestCase):
    def test_claim_precedes_preflight_and_pass_receipt_follows_cleanup(self) -> None:
        source = WRAPPER_PATH.read_text(encoding="utf-8")
        main_start = source.index("def _main_impl(")
        main_source = source[main_start:]
        self.assertLess(
            main_source.index("claim_once("), main_source.index("verify_frozen_chain()")
        )
        self.assertLess(
            main_source.index("release_heavy_lock("),
            main_source.index("write_create_only(RESULT_RECEIPT"),
        )
        self.assertLess(
            main_source.index("run_with_watcher("),
            main_source.index("evaluate_result("),
        )

    def test_wrapper_ast_contains_one_process_launch_and_no_shell_execution(
        self,
    ) -> None:
        tree = ast.parse(WRAPPER_PATH.read_text(encoding="utf-8"))
        popen_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "Popen"
        ]
        self.assertEqual(len(popen_calls), 1)
        source = WRAPPER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("{exc}", source)

    def test_original_frozen_13_file_hashes_still_match(self) -> None:
        self.assertEqual(len(wrapper.FROZEN_TREE), 13)
        for name, row in wrapper.FROZEN_TREE.items():
            raw = (CHAIN / name).read_bytes()
            self.assertEqual(len(raw), row["size_bytes"], name)
            self.assertEqual(sha256(raw).hexdigest(), row["sha256"], name)

    def test_hash_pinned_frozen_chain_parses_without_byte_reencoding(self) -> None:
        captures = wrapper.verify_frozen_chain()
        self.assertEqual(set(captures), set(wrapper.FROZEN_TREE))


if __name__ == "__main__":
    unittest.main()
