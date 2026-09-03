#!/usr/bin/env python3
"""Focused adversarial tests for the AGH-FAL17 v17 outer control plane.

The pure contract tests are safe on Windows.  Linux process-boundary checks are
explicitly gated and do not open the official input or invoke solver code.
"""

from __future__ import annotations

import ast
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ARTIFACT_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ARTIFACT_ROOT.parents[2]
OUTER_PATH = ARTIFACT_ROOT / "agent-aghfal17-native-v17-outer-controller.py"
FREEZE_PATH = ARTIFACT_ROOT / "agent-aghfal17-native-v17-review-freeze.json"
INVOCATIONS_PATH = ARTIFACT_ROOT / "agent-aghfal17-native-v17-invocations.json"
BOOTSTRAP_PATH = ARTIFACT_ROOT / "agent-aghfal17-native-v17-bootstrap.py"
SUPERVISOR_PATH = ARTIFACT_ROOT / "agent-aghfal17-native-v17-supervisor.py"
RUNNER_PATH = ARTIFACT_ROOT / "agent-aghfal17-native-v17-runner.py"
LAUNCHER_PATH = ARTIFACT_ROOT / "agent-aghfal17-native-v17-launcher.sh"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test target: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"assignment not found: {path.name}:{name}")


outer = load(OUTER_PATH, "aghfal17_native_v17_outer_tested")


class ResourceContractTests(unittest.TestCase):
    def test_wrapper_only_memory_can_breach_whole_launch_limit(self) -> None:
        process_rss = 12_345
        sealed_kib = outer.WHOLE_LAUNCH_MEMORY_LIMIT_KIB - process_rss
        reason = outer.resource_breach(
            elapsed_seconds=0,
            process_rss_kib=process_rss,
            process_swap_kib=0,
            process_group_charges_kib={"controller": process_rss},
            sealed_bytes=sealed_kib * 1024,
            report_bytes=0,
            mem_available_kib=2_000_000,
            wall_seconds=240,
        )
        self.assertEqual(
            reason, "whole_launch_process_plus_sealed_plus_report_limit"
        )

    def test_exact_lower_whole_launch_boundary_is_admitted(self) -> None:
        process_rss = 12_345
        sealed_kib = outer.WHOLE_LAUNCH_MEMORY_LIMIT_KIB - process_rss - 1
        reason = outer.resource_breach(
            elapsed_seconds=0,
            process_rss_kib=process_rss,
            process_swap_kib=0,
            process_group_charges_kib={"controller": process_rss},
            sealed_bytes=sealed_kib * 1024,
            report_bytes=0,
            mem_available_kib=2_000_000,
            wall_seconds=240,
        )
        self.assertIsNone(reason)

    def test_wrapper_swap_is_charged(self) -> None:
        self.assertEqual(
            outer.resource_breach(
                elapsed_seconds=0,
                process_rss_kib=1,
                process_swap_kib=outer.WHOLE_LAUNCH_MEMORY_LIMIT_KIB - 1,
                process_group_charges_kib={"a": 1},
                sealed_bytes=0,
                report_bytes=0,
                mem_available_kib=2_000_000,
                wall_seconds=240,
            ),
            "whole_launch_process_plus_sealed_plus_report_limit",
        )

    def test_process_generation_cap_is_independent(self) -> None:
        self.assertEqual(
            outer.resource_breach(
                elapsed_seconds=0,
                process_rss_kib=100,
                process_swap_kib=0,
                process_group_charges_kib={
                    "42": outer.PROCESS_GENERATION_MEMORY_LIMIT_KIB
                },
                sealed_bytes=0,
                report_bytes=0,
                mem_available_kib=2_000_000,
                wall_seconds=240,
            ),
            "process_generation_vmrss_plus_vmswap_limit",
        )

    def test_accounting_error_fails_closed_before_resource_values(self) -> None:
        self.assertEqual(
            outer.resource_breach(
                elapsed_seconds=0,
                process_rss_kib=0,
                process_swap_kib=0,
                process_group_charges_kib={},
                sealed_bytes=0,
                report_bytes=0,
                mem_available_kib=2_000_000,
                wall_seconds=240,
                accounting_errors=({"pid": 99, "error": "identity drift"},),
            ),
            "exact_generation_accounting_unavailable",
        )

    def test_duplicate_sealed_allocation_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "sealed allocation row rejected"):
            outer.sealed_reservation(
                {
                    "allocations": [
                        {"allocation_id": "same", "size_bytes": 10},
                        {"allocation_id": "same", "size_bytes": 20},
                    ]
                }
            )

    def test_retained_report_descriptor_is_deduplicated_by_inode(self) -> None:
        with tempfile.TemporaryFile() as stream:
            stream.write(b"retained")
            stream.flush()
            duplicate = os.dup(stream.fileno())
            try:
                self.assertEqual(
                    outer.retained_report_bytes(stream.fileno(), duplicate),
                    len(b"retained"),
                )
            finally:
                os.close(duplicate)


class ExactGenerationTests(unittest.TestCase):
    def identity(self, starttime: int) -> outer.ProcessIdentity:
        return outer.ProcessIdentity(starttime)

    def topology(self, ppid: int, pgid: int, session: int) -> outer.ProcessTopology:
        return outer.ProcessTopology(ppid, pgid, session)

    def record(
        self, ppid: int, pgid: int, session: int, starttime: int
    ) -> outer.ProcessRecord:
        return outer.ProcessRecord(
            identity=self.identity(starttime),
            topology=self.topology(ppid, pgid, session),
        )

    def member(
        self, record: outer.ProcessRecord, pidfd: int = 77
    ) -> outer.AdmittedMember:
        return outer.AdmittedMember(
            identity=record.identity,
            pidfd=pidfd,
            topology=record.topology,
        )

    def test_controller_and_admitted_duplicate_are_counted_once(self) -> None:
        record = self.record(1, 10, 10, 100)
        identity = record.identity
        admitted = {10: self.member(record)}
        with mock.patch.object(
            outer,
            "identity_bound_status",
            return_value={
                "pid": 10,
                "identity": [10, 100],
                "topology": [1, 10, 10],
                "vmrss_kib": 50,
                "vmswap_kib": 5,
            },
        ) as status:
            sample = outer.accounting_sample(
                wrapper_pid=10,
                wrapper_identity=identity,
                admitted=admitted,
            )
        status.assert_called_once_with(10, identity, None)
        self.assertEqual(sample["unique_identity_count"], 1)
        self.assertEqual(sample["process_vmrss_kib"], 50)
        self.assertEqual(sample["process_vmswap_kib"], 5)

    def test_identity_drift_is_reported_as_unavailable(self) -> None:
        record = self.record(1, 20, 20, 200)
        with mock.patch.object(
            outer,
            "identity_bound_status",
            side_effect=RuntimeError("identity replay failed"),
        ):
            sample = outer.accounting_sample(
                wrapper_pid=10,
                wrapper_identity=self.identity(100),
                admitted={20: self.member(record, pidfd=88)},
            )
        self.assertTrue(sample["unavailable"])
        self.assertEqual(sample["unavailable"][0]["pid"], 10)

    def test_descendant_fixed_point_crosses_sessions_and_admits_orphan(self) -> None:
        wrapper_pid = 10
        root_pid = 20
        root = self.record(wrapper_pid, 20, 20, 200)
        child = self.record(root_pid, 20, 20, 201)
        escaped = self.record(21, 22, 22, 202)
        orphan = self.record(wrapper_pid, 30, 30, 203)
        snapshot = {root_pid: root, 21: child, 22: escaped, 30: orphan}
        admitted = {root_pid: self.member(root, pidfd=70)}

        def fake_admit(target, pid, record):
            target[pid] = self.member(record, pidfd=70 + pid)

        with mock.patch.object(outer, "admit_member", side_effect=fake_admit):
            evidence = outer.refresh_descendant_registry(
                wrapper_pid=wrapper_pid,
                root_pid=root_pid,
                admitted=admitted,
                baseline_direct_children={},
                snapshot=snapshot,
            )
        self.assertEqual(set(evidence["added_pids"]), {21, 22, 30})
        self.assertLess(
            evidence["added_pids"].index(21), evidence["added_pids"].index(22)
        )
        self.assertEqual(set(admitted), {20, 21, 22, 30})

    def assert_topology_transition(self, after: outer.ProcessTopology) -> None:
        original = self.record(10, 20, 20, 200)
        admitted = {20: self.member(original)}
        evidence = outer.refresh_descendant_registry(
            wrapper_pid=10,
            root_pid=20,
            admitted=admitted,
            baseline_direct_children={},
            snapshot={
                20: outer.ProcessRecord(
                    identity=original.identity,
                    topology=after,
                )
            },
        )
        self.assertEqual(evidence["live_admitted_pids"], [20])
        self.assertEqual(admitted[20].identity, original.identity)
        self.assertEqual(admitted[20].topology, after)

    def test_setsid_transition_does_not_invalidate_generation(self) -> None:
        self.assert_topology_transition(self.topology(10, 20, 99))

    def test_setpgid_transition_does_not_invalidate_generation(self) -> None:
        self.assert_topology_transition(self.topology(10, 99, 20))

    def test_subreaper_reparent_transition_does_not_invalidate_generation(self) -> None:
        self.assert_topology_transition(self.topology(1, 20, 20))

    def test_preexisting_direct_child_is_not_claimed_as_launch_orphan(self) -> None:
        wrapper_pid = 10
        root = self.record(wrapper_pid, 20, 20, 200)
        unrelated = self.record(wrapper_pid, 40, 40, 400)
        admitted = {20: self.member(root, pidfd=70)}
        with mock.patch.object(outer, "admit_member") as admit:
            outer.refresh_descendant_registry(
                wrapper_pid=wrapper_pid,
                root_pid=20,
                admitted=admitted,
                baseline_direct_children={40: unrelated.identity},
                snapshot={20: root, 40: unrelated},
            )
        admit.assert_not_called()

    def test_pid_reuse_is_never_signalled(self) -> None:
        expected = self.record(10, 20, 20, 200)
        reused = self.record(1, 20, 20, 900)
        admitted = {20: self.member(expected)}
        with (
            mock.patch.object(outer, "proc_record", return_value=reused),
            mock.patch.object(
                outer.signal, "pidfd_send_signal", create=True
            ) as send_signal,
        ):
            result = outer.signal_admitted(admitted, outer.SIGKILL)
        send_signal.assert_not_called()
        self.assertEqual(result["identity_mismatch_pids"], [20])

    def test_proc_disappearance_is_the_only_absent_state(self) -> None:
        with mock.patch.object(
            outer.Path, "read_text", side_effect=FileNotFoundError()
        ):
            self.assertIsNone(outer.proc_record(20))

    def test_proc_read_malformed_and_parse_failures_are_not_disappearance(self) -> None:
        failures = (
            PermissionError(13, "denied"),
            OSError(5, "io"),
            "20 (cmd) S 1",
            "20 (cmd) " + " ".join(["S", *(["1"] * 18), "bad"]),
        )
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                effect = failure if isinstance(failure, OSError) else None
                returned = failure if isinstance(failure, str) else mock.DEFAULT
                with mock.patch.object(
                    outer.Path,
                    "read_text",
                    side_effect=effect,
                    return_value=returned,
                ):
                    with self.assertRaises(outer.ProcInspectionError):
                        outer.proc_record(20)

    def test_proc_unknown_is_signalled_by_pidfd_but_never_called_vanished(self) -> None:
        expected = self.record(10, 20, 20, 200)
        admitted = {20: self.member(expected)}
        with (
            mock.patch.object(
                outer,
                "proc_record",
                side_effect=outer.ProcInspectionError("permission denied"),
            ),
            mock.patch.object(
                outer.signal, "pidfd_send_signal", create=True
            ) as send_signal,
        ):
            result = outer.signal_admitted(admitted, outer.SIGKILL)
        send_signal.assert_called_once_with(77, outer.SIGKILL, None, 0)
        self.assertEqual(result["proc_unknown_pids"], [20])
        self.assertEqual(result["vanished_pids"], [])
        self.assertTrue(result["errors"])

    def test_final_fixed_point_requires_two_successive_zero_snapshots(self) -> None:
        with (
            mock.patch.object(
                outer,
                "refresh_descendant_registry",
                return_value={"added_pids": [], "live_admitted_pids": []},
            ) as refresh,
            mock.patch.object(outer, "_reap_known_children", return_value=[]),
            mock.patch.object(outer, "live_admitted", side_effect=[[], []]),
            mock.patch.object(outer.time, "sleep"),
        ):
            result = outer.final_zero_fixed_point(
                wrapper_pid=10,
                root=None,
                root_pid=20,
                admitted={},
                baseline_direct_children={},
            )
        self.assertTrue(result["empty"], result)
        self.assertEqual(result["stable_zero_snapshots"], 2)
        self.assertEqual(refresh.call_count, 2)
        self.assertEqual(
            [row["status"] for row in result["final_discovery_snapshots"]],
            ["ZERO", "ZERO"],
        )

    def test_final_fixed_point_discovers_and_drains_late_orphan(self) -> None:
        orphan = self.record(10, 30, 30, 300)
        admitted: dict[int, outer.AdmittedMember] = {}
        refresh_count = 0

        def refresh(**_kwargs):
            nonlocal refresh_count
            refresh_count += 1
            if refresh_count == 2:
                admitted[30] = self.member(orphan, pidfd=88)
                return {"added_pids": [30], "live_admitted_pids": [30]}
            return {"added_pids": [], "live_admitted_pids": []}

        residual = {
            "pid": 30,
            "identity": [30, 300],
            "topology": [10, 30, 30],
        }
        action = {
            "signal": outer.SIGKILL,
            "signaled_pids": [30],
            "vanished_pids": [],
            "identity_mismatch_pids": [],
            "proc_unknown_pids": [],
            "errors": [],
            "numeric_process_group_signal_sent": False,
        }
        with (
            mock.patch.object(outer, "refresh_descendant_registry", side_effect=refresh),
            mock.patch.object(outer, "_reap_known_children", return_value=[]),
            mock.patch.object(
                outer, "live_admitted", side_effect=[[], [residual], [], []]
            ),
            mock.patch.object(outer, "signal_admitted", return_value=action) as send,
            mock.patch.object(outer.time, "sleep"),
        ):
            result = outer.final_zero_fixed_point(
                wrapper_pid=10,
                root=None,
                root_pid=20,
                admitted=admitted,
                baseline_direct_children={},
            )
        self.assertTrue(result["empty"], result)
        self.assertEqual(result["stable_zero_snapshots"], 2)
        self.assertEqual(refresh_count, 4)
        self.assertEqual(
            [row["status"] for row in result["final_discovery_snapshots"]],
            ["ZERO", "NONZERO", "ZERO", "ZERO"],
        )
        send.assert_called_once_with(admitted, outer.SIGKILL)

    def test_final_fixed_point_fails_closed_on_proc_error(self) -> None:
        with (
            mock.patch.object(
                outer,
                "refresh_descendant_registry",
                side_effect=outer.ProcInspectionError("malformed stat"),
            ),
            mock.patch.object(outer, "_reap_known_children", return_value=[]),
            mock.patch.object(outer, "TERMINATION_GRACE_SECONDS", 0.0),
        ):
            result = outer.final_zero_fixed_point(
                wrapper_pid=10,
                root=None,
                root_pid=20,
                admitted={},
                baseline_direct_children={},
            )
        self.assertFalse(result["empty"])
        self.assertEqual(result["stable_zero_snapshots"], 0)
        self.assertIn("outer_stable_zero_not_established", result["errors"])
        self.assertEqual(result["final_discovery_snapshots"][0]["status"], "UNKNOWN")

    def test_empty_cleanup_proof_has_no_numeric_group_signal(self) -> None:
        root = mock.Mock()
        root.pid = 20
        root.poll.return_value = 0
        expected = self.record(10, 20, 20, 200)
        admitted = {20: self.member(expected)}
        with (
            mock.patch.object(
                outer,
                "refresh_descendant_registry",
                return_value={"added_pids": [], "live_admitted_pids": []},
            ),
            mock.patch.object(outer, "proc_record", return_value=None),
            mock.patch.object(outer, "POLL_SECONDS", 0.0),
        ):
            result = outer.drain_generation(
                wrapper_pid=10,
                root=root,
                root_pid=20,
                admitted=admitted,
                baseline_direct_children={},
            )
        self.assertTrue(result["empty"])
        self.assertFalse(result["numeric_process_group_signal_sent"])
        self.assertEqual(result["residual_identities"], [])
        self.assertEqual(result["stable_zero_snapshots"], 2)


class CommandAndFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
        cls.invocations = json.loads(INVOCATIONS_PATH.read_text(encoding="utf-8"))

    def test_probe_and_launch_have_distinct_exact_canonical_digests(self) -> None:
        probe = self.freeze["commands"]["probe"]
        launch = self.freeze["commands"]["launch"]
        self.assertNotEqual(
            probe["canonical_argv_sha256"], launch["canonical_argv_sha256"]
        )
        self.assertEqual(probe["argv"][-1], "--sealed-import-probe")
        self.assertEqual(launch["argv"][-1], "--launch")
        self.assertEqual(
            outer._canonical_argv_sha256(probe["argv"]),
            probe["canonical_argv_sha256"],
        )
        self.assertEqual(
            outer._canonical_argv_sha256(launch["argv"]),
            launch["canonical_argv_sha256"],
        )

    def test_outer_controller_is_authoritative_for_both_modes(self) -> None:
        contract = self.freeze["resource_contract"]
        self.assertEqual(contract["authoritative_component"], "outer_controller")
        self.assertEqual(
            contract["whole_launch_process_plus_sealed_plus_report_limit_kib"],
            614_400,
        )
        self.assertEqual(
            contract["process_generation_vmrss_plus_vmswap_limit_kib"],
            368_640,
        )
        self.assertEqual(contract["initial_sample_count"], 2)
        self.assertEqual(contract["initial_sample_interval_seconds"], 5.0)
        self.assertEqual(contract["exact_identity"], "pid_plus_starttime_plus_pidfd")
        self.assertEqual(
            contract["mutable_topology"],
            "ppid_pgid_sid_refreshed_without_generation_invalidation",
        )
        self.assertEqual(
            contract["proc_observation"],
            "only_enoent_esrch_mean_vanished_all_other_failures_fail_closed",
        )
        self.assertEqual(contract["final_zero_snapshots_required"], 2)

    def test_entry_loader_seals_controller_and_freeze_before_execution(self) -> None:
        contract = self.freeze["sealed_entry_loader"]
        source = contract["source"]
        ast.parse(source, filename="<sealed-entry-loader>")
        self.assertEqual(
            sha256(source.encode("utf-8")).hexdigest(), contract["source_sha256"]
        )
        self.assertIn("F_ADD_SEALS", source)
        self.assertIn("/proc/self/fd/196", source)
        self.assertTrue(
            contract["controller_and_freeze_captured_to_sealed_memfds_before_execution"]
        )

    def test_top_level_invocations_pin_freeze_and_have_distinct_digests(self) -> None:
        freeze_hash = sha256(FREEZE_PATH.read_bytes()).hexdigest()
        self.assertEqual(
            self.invocations["freeze_manifest"]["sha256"], freeze_hash
        )
        probe = self.invocations["probe"]
        launch = self.invocations["launch"]
        self.assertEqual(
            outer._canonical_argv_sha256(probe["argv"]),
            probe["canonical_argv_sha256"],
        )
        self.assertEqual(
            outer._canonical_argv_sha256(launch["argv"]),
            launch["canonical_argv_sha256"],
        )
        self.assertNotEqual(
            probe["canonical_argv_sha256"], launch["canonical_argv_sha256"]
        )
        self.assertIn(freeze_hash, probe["argv"])
        self.assertIn(freeze_hash, launch["argv"])

    def test_frozen_artifact_hashes_replay(self) -> None:
        for label, row in self.freeze["artifacts"].items():
            local = ARTIFACT_ROOT / Path(row["path"]).name
            self.assertTrue(local.is_file(), label)
            self.assertEqual(local.stat().st_size, row["size_bytes"], label)
            self.assertEqual(sha256(local.read_bytes()).hexdigest(), row["sha256"], label)

    def test_launcher_supervisor_runner_and_source_pins_form_one_chain(self) -> None:
        artifacts = self.freeze["artifacts"]
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
        self.assertIn(artifacts["supervisor"]["sha256"], launcher)
        self.assertEqual(
            literal_assignment(SUPERVISOR_PATH, "EXPECTED_RUNNER_SHA256"),
            artifacts["runner"]["sha256"],
        )
        supervisor_hashes = literal_assignment(SUPERVISOR_PATH, "EXPECTED_HASHES")
        runner_hashes = literal_assignment(RUNNER_PATH, "EXPECTED_HASHES")
        self.assertEqual(
            supervisor_hashes["generic_validator"],
            artifacts["generic_validator"]["sha256"],
        )
        self.assertEqual(
            runner_hashes["generic_validator"],
            artifacts["generic_validator"]["sha256"],
        )
        labels = {
            "benchmarks/itc2019_decomposed.py": "planora_itc2019_decomposed",
            "benchmarks/itc2019_sparse_joint.py": "planora_itc2019_sparse_joint",
            "benchmarks/itc2019_violation_lns.py": "planora_itc2019_violation_lns",
        }
        for relative, label in labels.items():
            expected = self.freeze["source_closure"][relative]["sha256"]
            self.assertEqual(supervisor_hashes[label], expected)
            self.assertEqual(runner_hashes[label], expected)

    def test_current_planora_source_closure_replays(self) -> None:
        for relative, row in self.freeze["source_closure"].items():
            local = REPOSITORY_ROOT / relative
            self.assertEqual(local.stat().st_size, row["size_bytes"], relative)
            self.assertEqual(
                sha256(local.read_bytes()).hexdigest(), row["sha256"], relative
            )

    def test_sealed_allocation_ids_are_unique_per_mode(self) -> None:
        for mode in ("probe", "launch"):
            rows = self.freeze["sealed_storage_contract"][mode]["allocations"]
            identifiers = [row["allocation_id"] for row in rows]
            self.assertEqual(len(identifiers), len(set(identifiers)), mode)
            self.assertTrue(all(row["size_bytes"] >= 0 for row in rows))
            freeze_rows = [
                row for row in rows if row["allocation_id"] == "freeze-manifest-sealed"
            ]
            self.assertEqual(len(freeze_rows), 1)
            self.assertEqual(freeze_rows[0]["size_bytes"], FREEZE_PATH.stat().st_size)

    def test_probe_truth_contract_forbids_input_solver_and_publication(self) -> None:
        self.assertEqual(
            outer.validate_inner_truth(
                "probe",
                {
                    "status": "PASS",
                    "official_instance_opened": False,
                    "solver_child_process_started": False,
                    "solver_execution_started": False,
                    "publication": False,
                },
            ),
            [],
        )
        errors = outer.validate_inner_truth(
            "probe",
            {
                "status": "PASS",
                "official_instance_opened": True,
                "solver_child_process_started": False,
                "solver_execution_started": False,
                "publication": False,
            },
        )
        self.assertIn("probe_truth:official_instance_opened", errors)

    def test_bootstrap_no_longer_routes_probe_through_inner_harness(self) -> None:
        source = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        self.assertNotIn("PROBE_HARNESS", source)
        self.assertNotIn("probe-harness", source)
        self.assertIn("os.execve(bash_exec_fd, argv, environment)", source)

    def test_barrier_admission_occurs_before_release(self) -> None:
        source = OUTER_PATH.read_text(encoding="utf-8")
        popen = source.index("root = subprocess.Popen(")
        admit = source.index("admit_member(admitted, root_pid, root_record)", popen)
        release = source.index("os.write(barrier_write, BARRIER_TOKEN)", admit)
        self.assertLess(popen, admit)
        self.assertLess(admit, release)

    def test_no_numeric_process_group_signalling_in_outer_controller(self) -> None:
        source = OUTER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("killpg(", source)
        self.assertIn("signal.pidfd_send_signal", source)
        self.assertIn("starttime", source)

    def test_no_v13_protocol_tokens_in_active_v14_artifacts(self) -> None:
        for path in (
            OUTER_PATH,
            BOOTSTRAP_PATH,
            SUPERVISOR_PATH,
            RUNNER_PATH,
            LAUNCHER_PATH,
        ):
            self.assertNotIn("native-v13", path.read_text(encoding="utf-8"), path.name)
            self.assertNotIn("NATIVE_V13", path.read_text(encoding="utf-8"), path.name)

    def test_no_v15_protocol_tokens_in_active_v17_runtime_artifacts(self) -> None:
        for path in (
            OUTER_PATH,
            BOOTSTRAP_PATH,
            SUPERVISOR_PATH,
            RUNNER_PATH,
            LAUNCHER_PATH,
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("native-v15", source, path.name)
            self.assertNotIn("NATIVE_V15", source, path.name)

    def test_no_v16_protocol_tokens_in_active_v17_runtime_artifacts(self) -> None:
        for path in (
            OUTER_PATH,
            BOOTSTRAP_PATH,
            SUPERVISOR_PATH,
            RUNNER_PATH,
            LAUNCHER_PATH,
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("native-v16", source, path.name)
            self.assertNotIn("NATIVE_V16", source, path.name)


class V17FreezeReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
        cls.invocations = json.loads(INVOCATIONS_PATH.read_text(encoding="utf-8"))

    def test_v17_is_review_ready_but_execution_unauthorized(self) -> None:
        self.assertEqual(
            self.freeze["status"],
            "READY_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH",
        )
        verification = self.freeze["verification"]
        self.assertFalse(verification["probe_run_authorized"])
        self.assertFalse(verification["official_launch_authorized"])
        self.assertFalse(verification["official_input_opened"])
        self.assertFalse(verification["solver_started"])
        self.assertFalse(self.invocations["authorization"]["probe_run"])
        self.assertFalse(self.invocations["authorization"]["official_launch"])

    def test_v15_no_go_context_is_retained(self) -> None:
        context = self.freeze["predecessor_v15_static_review_no_go"]
        self.assertEqual(context["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(
            context["outer_controller_sha256"],
            "1326027d0447c76be37f112d2e6ede2bdf7b8e2eb95c6afcb6ef8597369c325b",
        )
        self.assertEqual(
            context["tests_sha256"],
            "8067172a13d3719260a842f1e138efdcc654e3950c04487c95212ade78841422",
        )

    def test_v16_no_go_context_and_predecessor_snapshot_are_retained(self) -> None:
        context = self.freeze["predecessor_v16_static_review_no_go"]
        self.assertEqual(context["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(
            context["outer_controller_sha256"],
            "0178d2c04e2e0d1e82bb11defa965d947ea5527e7270d838e32a9ef6d385a558",
        )
        self.assertEqual(
            context["tests_sha256"],
            "6b931292d4b65e00461202c57157be0bf8805403cb6de90f613ce79d730fea9f",
        )
        preserved = self.freeze["preserved_predecessors"]
        self.assertEqual(preserved["versions"], [12, 13, 14, 15, 16])
        self.assertEqual(preserved["file_count"], 63)
        self.assertEqual(len(preserved["snapshot_sha256"]), 64)

    def test_final_shared_core_and_focused_regression_are_frozen(self) -> None:
        closure = self.freeze["source_closure"]
        self.assertEqual(
            closure["benchmarks/itc2019_decomposed.py"]["sha256"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )
        self.assertEqual(
            closure["tests/test_itc2019_decomposed_extended_budget.py"]["sha256"],
            "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d",
        )

    def test_v12_and_v13_source_drift_no_go_context_is_retained(self) -> None:
        context = self.freeze["predecessor_source_drift_no_go"]
        self.assertEqual(context["v12"]["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(context["v13"]["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(
            context["v12"]["frozen_source"]["sha256"],
            "3f4b92f91867cd1205f1702f36923b3c19cb8ad8d39b43d34a3b15e07f502e05",
        )
        self.assertEqual(
            context["v13"]["frozen_source"]["sha256"],
            "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
        )
        self.assertEqual(
            context["v13"]["reviewed_current_source"]["sha256"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )

class StrictTerminationObservationRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = outer.ProcessIdentity(200)
        self.running = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "S"
        )
        self.zombie = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "Z"
        )
        self.member = outer.AdmittedMember(
            identity=self.identity,
            pidfd=77,
            topology=self.running.topology,
        )

    def test_proc_record_parses_and_retains_zombie_state(self) -> None:
        fields = ["Z", "10", "20", "20", *(["0"] * 15), "200"]
        raw = "20 (worker name) " + " ".join(fields)
        with mock.patch.object(outer.Path, "read_text", return_value=raw):
            record = outer.proc_record(20)
        self.assertEqual(record, self.zombie)

    def test_malformed_proc_state_fails_closed(self) -> None:
        fields = ["ZZ", "10", "20", "20", *(["0"] * 15), "200"]
        raw = "20 (worker) " + " ".join(fields)
        with mock.patch.object(outer.Path, "read_text", return_value=raw):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "proc stat state malformed"
            ):
                outer.proc_record(20)

    def test_permission_and_eio_remain_fail_closed_after_pidfd_termination(self) -> None:
        failures = (PermissionError(13, "denied"), OSError(5, "io"))
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                with (
                    mock.patch.object(outer, "proc_record", return_value=self.running),
                    mock.patch.object(outer, "_status_values", side_effect=failure),
                    mock.patch.object(
                        outer, "pidfd_exit_confirmed", return_value=True
                    ) as confirmed,
                ):
                    with self.assertRaisesRegex(
                        outer.ProcInspectionError, "proc status read failed"
                    ):
                        outer.identity_bound_status(
                            20, self.identity, self.member.pidfd
                        )
                confirmed.assert_not_called()

    def test_malformed_vmrss_is_distinct_from_missing_vmrss(self) -> None:
        malformed = (
            "VmRSS: nope kB\n",
            "VmRSS: 12 MB\n",
            "VmRSS:\n",
            "VmRSS 12 kB\n",
            "VmRSS: 12 kB\nVmRSS: 13 kB\n",
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                with mock.patch.object(outer.Path, "read_text", return_value=raw):
                    with self.assertRaises(outer.ProcInspectionError):
                        outer._status_values(20)

    def test_malformed_vmswap_fails_closed(self) -> None:
        raw = "VmRSS: 12 kB\nVmSwap: bad kB\n"
        with mock.patch.object(outer.Path, "read_text", return_value=raw):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "proc status VmSwap malformed"
            ):
                outer._status_values(20)

    def test_non_zombie_missing_vmrss_fails_even_after_pidfd_termination(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.running]
            ),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "VmRSS unavailable for non-zombie admitted identity",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_genuine_zombie_without_vmrss_is_zero_only_after_pidfd_exit(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.zombie]
            ),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            self.assertIsNone(
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
            )
        confirmed.assert_called_once_with(self.member.pidfd)

    def test_zombie_without_vmrss_fails_when_pidfd_is_not_ready(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", return_value=self.zombie),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(outer, "pidfd_exit_confirmed", return_value=False),
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "zombie VmRSS unavailable without confirmed generation exit",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)

    def test_pid_reuse_before_status_is_ambiguous_even_after_pidfd_exit(self) -> None:
        reused = outer.ProcessRecord(
            outer.ProcessIdentity(900), outer.ProcessTopology(1, 20, 20), "S"
        )
        with (
            mock.patch.object(outer, "proc_record", return_value=reused),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "identity replay failed before status read",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_pid_reuse_after_status_is_ambiguous_even_after_pidfd_exit(self) -> None:
        reused = outer.ProcessRecord(
            outer.ProcessIdentity(900), outer.ProcessTopology(1, 20, 20), "Z"
        )
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, reused]
            ),
            mock.patch.object(outer, "_status_values", return_value={"VmRSS": 1}),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "identity replay failed after status read",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_pidfd_poll_failure_is_observation_failure(self) -> None:
        with mock.patch.object(
            outer.select, "poll", side_effect=OSError(5, "io"), create=True
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "pidfd exit observation failed"
            ):
                outer.pidfd_exit_confirmed(77)

    def test_pidfd_invalid_event_is_observation_failure(self) -> None:
        poller = mock.Mock()
        poller.poll.return_value = [(77, getattr(outer.select, "POLLNVAL", 0x020))]
        with mock.patch.object(outer.select, "poll", return_value=poller, create=True):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "pidfd exit observation invalid"
            ):
                outer.pidfd_exit_confirmed(77)

    def test_confirmed_zombie_is_reported_as_vanished_without_accounting_error(self) -> None:
        wrapper = {
            "pid": 10,
            "identity": [10, 100],
            "topology": [1, 10, 10],
            "process_state": "R",
            "vmrss_kib": 40,
            "vmswap_kib": 0,
        }
        with mock.patch.object(
            outer, "identity_bound_status", side_effect=[wrapper, None]
        ):
            sample = outer.accounting_sample(
                wrapper_pid=10,
                wrapper_identity=outer.ProcessIdentity(100),
                admitted={20: self.member},
            )
        self.assertEqual(sample["unavailable"], [])
        self.assertEqual(
            sample["vanished"],
            [
                {
                    "role": "launch_generation",
                    "pid": 20,
                    "basis": "pidfd_exit_confirmed",
                }
            ],
        )
        self.assertEqual(sample["process_vmrss_kib"], 40)

class V17IndependentReviewerRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = outer.ProcessIdentity(200)
        self.running = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "S"
        )
        self.zombie = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "Z"
        )
        self.reused = outer.ProcessRecord(
            outer.ProcessIdentity(900), outer.ProcessTopology(10, 20, 20), "S"
        )
        self.member = outer.AdmittedMember(
            identity=self.identity,
            pidfd=77,
            topology=self.running.topology,
        )

    def test_noncanonical_tracked_status_keys_are_explicitly_rejected(self) -> None:
        malformed = (
            " VmRSS: invalid kB\n",
            "VmRSS : invalid kB\n",
            "\tVmRSS:\t12 kB\n",
            "VmRSS\t:\t12 kB\n",
            " VmSwap: invalid kB\n",
            "VmSwap : invalid kB\n",
            "\tVmSwap:\t0 kB\n",
            "VmSwap\t:\t0 kB\n",
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                with mock.patch.object(outer.Path, "read_text", return_value=raw):
                    with self.assertRaisesRegex(
                        outer.ProcInspectionError, "key syntax malformed"
                    ):
                        outer._status_values(20)

    def test_malformed_whitespace_vmrss_cannot_be_forgiven_as_zombie_absence(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.zombie]
            ),
            mock.patch.object(
                outer.Path,
                "read_text",
                return_value=" VmRSS: invalid kB\nVmSwap: 0 kB\n",
            ),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "VmRSS key syntax malformed"
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_truly_absent_vmrss_still_requires_zombie_and_positive_pidfd(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.zombie]
            ),
            mock.patch.object(
                outer.Path, "read_text", return_value="VmSwap: 0 kB\n"
            ),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            self.assertIsNone(
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
            )
        confirmed.assert_called_once_with(self.member.pidfd)

    def test_descendant_refresh_rejects_admitted_pid_reuse(self) -> None:
        with self.assertRaisesRegex(
            outer.ProcInspectionError,
            "admitted PID generation ambiguity:descendant_refresh",
        ):
            outer.refresh_descendant_registry(
                wrapper_pid=10,
                root_pid=20,
                admitted={20: self.member},
                baseline_direct_children={},
                snapshot={20: self.reused},
            )

    def test_live_admitted_rejects_pid_reuse_instead_of_returning_empty(self) -> None:
        with mock.patch.object(outer, "proc_record", return_value=self.reused):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "admitted PID generation ambiguity:live_admitted",
            ):
                outer.live_admitted({20: self.member})

    def test_memory_snapshot_records_pid_reuse_as_unavailable(self) -> None:
        wrapper = {
            "pid": 10,
            "identity": [10, 100],
            "topology": [1, 10, 10],
            "process_state": "R",
            "vmrss_kib": 40,
            "vmswap_kib": 0,
        }

        def status(pid, _identity, _pidfd):
            if pid == 20:
                raise outer._generation_ambiguity_error(
                    "memory_snapshot",
                    pid,
                    self.identity,
                    self.reused.identity,
                )
            return wrapper

        with mock.patch.object(outer, "identity_bound_status", side_effect=status):
            sample = outer.accounting_sample(
                wrapper_pid=10,
                wrapper_identity=outer.ProcessIdentity(100),
                admitted={20: self.member},
            )
        self.assertEqual(len(sample["unavailable"]), 1)
        self.assertIn(
            "admitted PID generation ambiguity:memory_snapshot",
            sample["unavailable"][0]["error"],
        )

    def test_reap_known_children_rejects_observed_pid_reuse(self) -> None:
        with mock.patch.object(outer, "proc_record", return_value=self.reused):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "admitted PID generation ambiguity:reap_known_children",
            ):
                outer._reap_known_children(10, None, {20: self.member})

    def test_cleanup_fixed_point_cannot_certify_zero_after_pid_reuse(self) -> None:
        with (
            mock.patch.object(outer, "_reap_known_children", return_value=[]),
            mock.patch.object(
                outer,
                "refresh_descendant_registry",
                return_value={
                    "added_pids": [],
                    "live_admitted_pids": [],
                    "generation_ambiguities": [],
                },
            ),
            mock.patch.object(outer, "proc_record", return_value=self.reused),
            mock.patch.object(outer, "TERMINATION_GRACE_SECONDS", 0.0),
        ):
            result = outer.final_zero_fixed_point(
                wrapper_pid=10,
                root=None,
                root_pid=20,
                admitted={20: self.member},
                baseline_direct_children={},
            )
        self.assertFalse(result["empty"])
        self.assertEqual(result["stable_zero_snapshots"], 0)
        self.assertEqual(result["final_discovery_snapshots"][0]["status"], "UNKNOWN")
        self.assertTrue(
            any("admitted PID generation ambiguity" in row for row in result["errors"])
        )

    def test_pid_reuse_is_recorded_but_wrong_generation_is_never_signaled(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", return_value=self.reused),
            mock.patch.object(
                outer.signal, "pidfd_send_signal", create=True
            ) as send_signal,
        ):
            result = outer.signal_admitted({20: self.member}, outer.SIGKILL)
        send_signal.assert_not_called()
        self.assertEqual(result["identity_mismatch_pids"], [20])
        self.assertTrue(
            any("admitted PID generation ambiguity" in row for row in result["errors"])
        )

@unittest.skipUnless(
    os.name == "posix"
    and hasattr(os, "pidfd_open")
    and hasattr(signal, "pidfd_send_signal"),
    "Linux pidfd semantics required",
)
class LinuxContainmentTests(unittest.TestCase):
    def test_setsided_orphan_is_discovered_and_drained(self) -> None:
        wrapper_pid = os.getpid()
        previous = outer._enable_subreaper()
        child = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                (
                    "import os,subprocess,sys,time;"
                    "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
                    "'import os,time;os.setsid();time.sleep(30)']);"
                    "time.sleep(0.2)"
                ),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        record = outer.proc_record(child.pid)
        self.assertIsNotNone(record)
        admitted: dict[int, outer.AdmittedMember] = {}
        outer.admit_member(admitted, child.pid, record)
        try:
            deadline = outer.time.monotonic() + 2
            while outer.time.monotonic() < deadline:
                outer.refresh_descendant_registry(
                    wrapper_pid=wrapper_pid,
                    root_pid=child.pid,
                    admitted=admitted,
                    baseline_direct_children={},
                )
                if len(admitted) >= 2:
                    break
                outer.time.sleep(0.01)
            self.assertGreaterEqual(len(admitted), 2)
            cleanup = outer.drain_generation(
                wrapper_pid=wrapper_pid,
                root=child,
                root_pid=child.pid,
                admitted=admitted,
                baseline_direct_children={},
            )
            self.assertTrue(cleanup["empty"], cleanup)
            self.assertFalse(cleanup["numeric_process_group_signal_sent"])
        finally:
            for member in admitted.values():
                try:
                    os.close(member.pidfd)
                except OSError:
                    pass
            try:
                child.kill()
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
            outer._restore_subreaper(previous)


if __name__ == "__main__":
    unittest.main()
