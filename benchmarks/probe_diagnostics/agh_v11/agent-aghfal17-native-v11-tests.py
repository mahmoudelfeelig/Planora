#!/usr/bin/env python3
"""Lightweight adversarial tests for the AGH-FAL17 native v11 diagnostic chain.

These tests never open the official instance and never invoke a solver.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import importlib.util
import errno
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock


ARTIFACT_DIR = Path(os.environ.get("AGHFAL_NATIVE_V11_ARTIFACT_DIR", "/tmp"))
RUNNER_PATH = ARTIFACT_DIR / "agent-aghfal17-native-v11-runner.py"
SUPERVISOR_PATH = ARTIFACT_DIR / "agent-aghfal17-native-v11-supervisor.py"
GENERIC_PATH = ARTIFACT_DIR / "agent-aghfal17-native-v11-generic-validator.py"
LAUNCHER_PATH = ARTIFACT_DIR / "agent-aghfal17-native-v11-launcher.sh"
BOOTSTRAP_PATH = ARTIFACT_DIR / "agent-aghfal17-native-v11-bootstrap.py"
HARNESS_PATH = ARTIFACT_DIR / "agent-aghfal17-native-v11-probe-harness.py"

V3_HASHES = {
    "/tmp/agent-aghfal17-completion-v3-bootstrap.py": "8484e7fbc8767fec5366a8b6be193920877752e9b894ca1c86abb1ca55259dcd",
    "/tmp/agent-aghfal17-completion-v3-runner.py": "ea8286d2773c3a7788bd86b2761692df7f247edce3a047369e3ba0d3b0c29e07",
    "/tmp/agent-aghfal17-completion-v3-supervisor.py": "b4146c29032415cfbd2ee52fe8f3714226a8c683863379cbca4eb647a5afe03b",
    "/tmp/agent-aghfal17-completion-v3-launcher.sh": "2d06af3925beeca443221594d9905b3b55323a0319543fbbfc6e45095afbf717",
    "/tmp/agent-aghfal17-completion-v3-tests.py": "8b84db45b3a9482136a5591b8f6b44c1dab81bde045dbfdfa94a062e586f4900",
}
V4_HASHES = {
    "/tmp/agent-aghfal17-native-v4-bootstrap.py": "8f639c37083900552ca381523d72756656b71ffe1f33f4cbdb758a2727e78fed",
    "/tmp/agent-aghfal17-native-v4-generic-validator.py": "a81fd8af314f24e1c2dc586b9d9dc31d2bb015d2049de7d0bacda9684b7da882",
    "/tmp/agent-aghfal17-native-v4-launcher.sh": "dbd217ddace77273d3bb92790eb681b98a789d7da508b6466963fd35e1ce2695",
    "/tmp/agent-aghfal17-native-v4-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/agent-aghfal17-native-v4-runner.py": "f91b960f59989d863ef36aa791f3b0632100161246637d06a390520c14a1d59c",
    "/tmp/agent-aghfal17-native-v4-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/agent-aghfal17-native-v4-supervisor.py": "375adad34f005a35b0d7586278441a4b14307a5b8b80b52bad2096d3a9f6f85d",
    "/tmp/agent-aghfal17-native-v4-tests.py": "0fa4c8d4f2000094e51f56cca3bbf12666e18b1b4dc3eaca64f61b435aa26e62",
    "/tmp/agent-aghfal17-native-v4-review-freeze.json": "8b7d73188525e9eee8cd476618fec1c8f40ae996084c6ea26572f5debacc72f2",
    "/tmp/agent-aghfal17-native-v4-review-certificate.md": "a1d6d437b7c2102e42b004d6e962caa675fe0a9e38045669fb5adaa94c196104",
}
V5_HASHES = {
    "/tmp/agent-aghfal17-native-v5-bootstrap.py": "43e4388f50e775a719f770285eda94216fbfd0ffd3552a66dd8adf380464e8bb",
    "/tmp/agent-aghfal17-native-v5-generic-validator.py": "bb0b0301c7574a06440e4a357b4f841b213cd054bf2faf713784b8d5d2640fc9",
    "/tmp/agent-aghfal17-native-v5-launcher.sh": "e27176f0662ea238e4536289f230b22b73c177b661676a4a65040f7aec8903bb",
    "/tmp/agent-aghfal17-native-v5-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/agent-aghfal17-native-v5-runner.py": "6c56adf684add680299326896b2b8d4f25b4d2cdfa2ad6adf8201338d5b0bf42",
    "/tmp/agent-aghfal17-native-v5-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/agent-aghfal17-native-v5-supervisor.py": "c89353cb53b0c1d1a831ce0ec4742d2937cdf43ed118e333b0e55fdb71bc0522",
    "/tmp/agent-aghfal17-native-v5-tests.py": "9d09ce279acb53d669d442f9973e681304795c0da423f37ef33e1aecbaf518e2",
    "/tmp/agent-aghfal17-native-v5-review-freeze.json": "289620ced109c04925b219c3a9080cbda870ac2b291c7ab1a393870028ee7797",
    "/tmp/agent-aghfal17-native-v5-review-certificate.md": "5fe4f977d588a5e1e8f978ff6a6359653ec04a31939fef20e13378a04a52fc6d",
}
V6_HASHES = {
    "/tmp/agent-aghfal17-native-v6-bootstrap.py": "6bafeb0e7577425587fbfdaba0e9aa794a6f869dcb97a4992f79a2c5e581c9b5",
    "/tmp/agent-aghfal17-native-v6-generic-validator.py": "cfb16833d35ff9a597a5db45aac7a2509c155e7e5171a1535818436a95762572",
    "/tmp/agent-aghfal17-native-v6-launcher.sh": "b36f53cf8f32bd73beca1033947c914c582fb44c221cc3d55260e02378897c28",
    "/tmp/agent-aghfal17-native-v6-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/agent-aghfal17-native-v6-review-certificate.md": "40c75675365ca4263f1eb07264f5b6f3be1f43b36a115dd5e4672ec34aef3c27",
    "/tmp/agent-aghfal17-native-v6-review-freeze.json": "9b27368522e1f75274a0d52db10f50c875d3befc1be920ce9b44bf03a1328ff1",
    "/tmp/agent-aghfal17-native-v6-runner.py": "37a93acc9d26ead0c68806a7e56d403ceac77b69c89fe037d8f4b02f1643b071",
    "/tmp/agent-aghfal17-native-v6-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/agent-aghfal17-native-v6-supervisor.py": "f6f3540f683d125363a3d09c37b408004ecdfc269904eb9a6f0cc6905624719b",
    "/tmp/agent-aghfal17-native-v6-tests.py": "4637f81e695ee8abe813bd1d003caf36f2521fd2e93a002ace5fb37ed9dc96d3",
}
V7_HASHES = {
    "/tmp/agent-aghfal17-native-v7-bootstrap.py": "745eb1c1d6cf9fe76291ccf09ed50771213c35b38f60a249ef6b2aeed8322b11",
    "/tmp/agent-aghfal17-native-v7-generic-validator.py": "e36f4d88344dc7c1b376a25ba7995d0df44101c1b86961b4e42238effe8a3f73",
    "/tmp/agent-aghfal17-native-v7-launcher.sh": "c045369faaeb732ea5a98f4cdff526be1dcb86d800822e496eca40ae4b7245f4",
    "/tmp/agent-aghfal17-native-v7-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/agent-aghfal17-native-v7-probe-harness.py": "9d7f73b2a78b18c05fd765a49cfdade007b11aca83230a1b56effb918b836317",
    "/tmp/agent-aghfal17-native-v7-review-certificate.md": "ef7ad6502c47fe08277d20c7ec65caf563678bafeffa2da71732bed47fb9ea6e",
    "/tmp/agent-aghfal17-native-v7-review-freeze.json": "18e780cd54fc0d5f977fb384549e581b467cfd68fd3473f1c3f974e8f55a1050",
    "/tmp/agent-aghfal17-native-v7-runner.py": "b119d147533d098712a33e259d0e2b3275c20e97ec27afc6172b49783cd160b9",
    "/tmp/agent-aghfal17-native-v7-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/agent-aghfal17-native-v7-supervisor.py": "75bd13455a9a4061512e23705dd0f5082e7e5ec258cc7a4c72b69dd28657f985",
    "/tmp/agent-aghfal17-native-v7-tests.py": "12b27a19add70d2fe2fe1ad5144d39f8a9c97777b4474d3812d9851e819ec9a9",
}
V8_HASHES = {
    "/tmp/agent-aghfal17-native-v8-bootstrap.py": "f24e9e58867003a43b2a9cc69cdc01c741c559bf992a066881b863650c47dbb4",
    "/tmp/agent-aghfal17-native-v8-generic-validator.py": "ec3bac5289dffebf5edc7f39936a1cbaeed559dd9ea1c1231cf7e51886744cd3",
    "/tmp/agent-aghfal17-native-v8-launcher.sh": "2933a0f21f7b720efda21b639276211bb63fca3aea671d6ee585ab4c1d694199",
    "/tmp/agent-aghfal17-native-v8-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/agent-aghfal17-native-v8-probe-harness.py": "69e1e2b06c219a97341974f6995242af704f3f327c3d2b80235b8a83c95e4bba",
    "/tmp/agent-aghfal17-native-v8-review-certificate.md": "85b56b3a1ce8f9d23cd8a5bfead2b681e583d116bb2cc379f17a99ce9c4c0f2d",
    "/tmp/agent-aghfal17-native-v8-review-freeze.json": "147dc954f83cd95e68ea04611c8898205903c780ad9d4ded31721ca2e4626f9d",
    "/tmp/agent-aghfal17-native-v8-runner.py": "269c1d9fa1503560814674288733aeb1dab4ca564d9fd316e0426f9e95b3c401",
    "/tmp/agent-aghfal17-native-v8-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/agent-aghfal17-native-v8-supervisor.py": "4163b340cdf9e2ba875e61683717bece963cba971a7cc2dc2396ae3771e87299",
    "/tmp/agent-aghfal17-native-v8-tests.py": "dbdea882e378e24d2280c72661eab7848bc7d70b8cef0eb0010a39cc2d18bdec",
}
V9_ARTIFACT_DIR = Path(
    "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/agh_v9"
)
V9_HASHES = {
    "agent-aghfal17-native-v9-bootstrap.py": "4d6009e44cb24240d8b7e5a1cdf4f91a1c065eb18f05af2eb3d61be244f2da8e",
    "agent-aghfal17-native-v9-generic-validator.py": "80a04b60460f536db7e7198a611b713e048df789974e11520190f7f8c64825e7",
    "agent-aghfal17-native-v9-launcher.sh": "6093d7c99f0740094aff3094ea2fd534aca29d059844a9a57cafe009b3c04bf5",
    "agent-aghfal17-native-v9-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "agent-aghfal17-native-v9-probe-harness.py": "c750a03b800a02289c5850a5bca51ca8828e83636a4fe5238e3f3d6181724849",
    "agent-aghfal17-native-v9-review-freeze.json": "8fa00b4f8116e1cecc625d1d77ac57f77ddd27804a1c6f9567a176925f8cb01f",
    "agent-aghfal17-native-v9-runner.py": "60b06dcb827279542f049a43723a2abd8381c50273e354c48c83f81868bb5236",
    "agent-aghfal17-native-v9-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "agent-aghfal17-native-v9-supervisor.py": "cee9f8853492cfdf7b67f79f04590facdc468ba6f9e4f0eb4cf2440ba7434f0b",
    "agent-aghfal17-native-v9-tests.py": "f30874caf4521cfccf747d78053242087e2c03c9fc744316915f5599d1e1ef57",
}
V10_ARTIFACT_DIR = Path(
    "/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/agh_v10"
)
V10_HASHES = {
    "agent-aghfal17-native-v10-bootstrap.py": "7e5df97e30de91df1f804f7ca4b72b342f8f88c397fa4b9243dd011bdf34b39f",
    "agent-aghfal17-native-v10-generic-validator.py": "5a64e57fb81d088e97dd6f471657b9a5599d31e9fbf014dce2b31f3fd0bf09b6",
    "agent-aghfal17-native-v10-launcher.sh": "eeeb93396b7ae48ba9dd86544c5230dc8113b4b8a99a5d07b72903c276b0a1b2",
    "agent-aghfal17-native-v10-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "agent-aghfal17-native-v10-probe-harness.py": "131fad18891ebbfd9140290dfb95c83dc64060c8645a84df801bb5786238af43",
    "agent-aghfal17-native-v10-review-freeze.json": "42f7fb65d339148f0714f749c59fc1bcd6fee0a8102830a2b750de7e9c386c9b",
    "agent-aghfal17-native-v10-runner.py": "a12bd626aab4d74212aa63c6c202504ec3994d200cdacf1faa53581ef6fdcf32",
    "agent-aghfal17-native-v10-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "agent-aghfal17-native-v10-supervisor.py": "ca162e1e72054837c4dd0d505d6ba037a8516e805011aabbd7b9e42374c714a0",
    "agent-aghfal17-native-v10-tests.py": "06cfe6d1f363ac6b23ae8da8ce7f3eec3fec84ba4ec87f9d792daf3ef767c7cd",
}


def load_module(path: Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module(RUNNER_PATH, "aghfal17_native_v11_runner_tests")
supervisor = load_module(SUPERVISOR_PATH, "aghfal17_native_v11_supervisor_tests")
bootstrap = load_module(BOOTSTRAP_PATH, "aghfal17_native_v11_bootstrap_tests")
harness = load_module(HARNESS_PATH, "aghfal17_native_v11_harness_tests")


class ProvenanceAndBoundaryTests(unittest.TestCase):
    def test_v3_exact_bytes_remain_preserved(self) -> None:
        for raw_path, expected in V3_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v4_exact_bytes_remain_preserved(self) -> None:
        for raw_path, expected in V4_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v5_exact_bytes_remain_preserved(self) -> None:
        for raw_path, expected in V5_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v6_exact_bytes_remain_preserved(self) -> None:
        for raw_path, expected in V6_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v7_exact_bytes_remain_preserved(self) -> None:
        for raw_path, expected in V7_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v8_exact_bytes_remain_preserved(self) -> None:
        for raw_path, expected in V8_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_frozen_v9_directory_exact_bytes_remain_preserved(self) -> None:
        self.assertEqual(
            {path.name for path in V9_ARTIFACT_DIR.iterdir() if path.is_file()},
            set(V9_HASHES),
        )
        for name, expected in V9_HASHES.items():
            self.assertEqual(
                sha256((V9_ARTIFACT_DIR / name).read_bytes()).hexdigest(),
                expected,
                name,
            )

    def test_frozen_v10_directory_exact_bytes_remain_preserved(self) -> None:
        self.assertEqual(
            {path.name for path in V10_ARTIFACT_DIR.iterdir() if path.is_file()},
            set(V10_HASHES),
        )
        for name, expected in V10_HASHES.items():
            self.assertEqual(
                sha256((V10_ARTIFACT_DIR / name).read_bytes()).hexdigest(),
                expected,
                name,
            )

    def test_capture_surface_has_no_placement_bearing_inputs(self) -> None:
        forbidden = {
            "algorithm",
            "room_core",
            "validator",
            "matcher",
            "checkpoint",
            "certified_child",
            "certified_supervisor",
        }
        self.assertTrue(forbidden.isdisjoint(supervisor.CAPTURE_SOURCES))
        self.assertEqual(
            set(supervisor.CAPTURE_SOURCES),
            {
                "runner",
                "generic_validator",
                "official_instance",
                "python_binary",
                "stdlib_manifest",
                "minimal_tcb_manifest",
                *supervisor.PLANORA_SOURCES,
                *supervisor.RUNTIME_RECORDS,
            },
        )

    def test_fresh_native_solver_and_cardinality_source_are_explicit(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn("native.solve_itc2019_native(", source)
        self.assertIn('formulation="auto"', source)
        self.assertIn("len(class_ids) != EXPECTED_CLASS_COUNT", source)
        self.assertIn("len(problem.students)", source)
        self.assertNotIn("_compile_algorithm", source)
        self.assertNotIn("room_core", runner.EXPECTED_HASHES)

    def test_full_planora_source_closure_is_hash_pinned(self) -> None:
        self.assertEqual(len(supervisor.PLANORA_SOURCES), 15)
        self.assertEqual(len(runner.PLANORA_MODULE_LABELS), 15)
        for label, path in supervisor.PLANORA_SOURCES.items():
            self.assertEqual(
                sha256(path.read_bytes()).hexdigest(),
                supervisor.EXPECTED_HASHES[label],
            )
        self.assertEqual(
            supervisor.EXPECTED_HASHES["planora_itc2019_violation_lns"],
            "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b",
        )

    def test_runtime_record_closure_is_complete(self) -> None:
        self.assertEqual(
            set(supervisor.RUNTIME_RECORDS),
            {
                "runtime_ortools_record",
                "runtime_numpy_record",
                "runtime_pandas_record",
                "runtime_dateutil_record",
                "runtime_six_record",
                "runtime_lxml_record",
                "runtime_absl_record",
                "runtime_immutabledict_record",
                "runtime_protobuf_record",
                "runtime_typing_extensions_record",
            },
        )

    def test_generic_command_passes_solution_and_report_fds(self) -> None:
        command = supervisor.planned_generic_command(
            11, 12, 13, Path("/tmp/no-pyc"), 14, 15
        )
        self.assertEqual(command[0], "/proc/self/fd/11")
        self.assertEqual(command[-4:], ["--solution-fd", "14", "--report-fd", "15"])
        source = GENERIC_PATH.read_text(encoding="utf-8")
        self.assertIn("_write_report(int(sys.argv[4]), payload)", source)
        self.assertNotIn("Path(sys.argv[4])", source)

    def test_launcher_uses_pinned_fd_interpreter_chain(self) -> None:
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        self.assertIn("exec 9</usr/bin/python3.12", source)
        self.assertIn('"/proc/$$/fd/9" -I -S -B', source)
        self.assertIn("/usr/bin/env -i", source)
        self.assertNotIn(".venv/bin/python", source)

    def test_outer_harness_is_exact_hash_captured_before_probe_execution(self) -> None:
        self.assertEqual(
            sha256(HARNESS_PATH.read_bytes()).hexdigest(),
            bootstrap.EXPECTED_PROBE_HARNESS_SHA256,
        )
        source = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        self.assertIn("capture_sealed_source", source)
        self.assertIn('"probe-harness"', source)
        self.assertIn("O_NOFOLLOW", source)
        self.assertIn('f"/proc/self/fd/{harness_fd}"', source)

    def test_sealed_bootstrap_launcher_supervisor_self_test(self) -> None:
        bootstrap_hash = sha256(BOOTSTRAP_PATH.read_bytes()).hexdigest()
        launcher_hash = sha256(LAUNCHER_PATH.read_bytes()).hexdigest()
        bash_path = Path("/usr/bin/bash")
        command = [
            "/usr/bin/python3.12",
            "-I",
            "-S",
            "-B",
            "-c",
            bootstrap.BOOTSTRAP_FD_LOADER,
            str(BOOTSTRAP_PATH),
            bootstrap_hash,
            supervisor.EXPECTED_HASHES["python_binary"],
            "--expected-bootstrap-sha256",
            bootstrap_hash,
            "--launcher",
            str(LAUNCHER_PATH),
            "--expected-launcher-sha256",
            launcher_hash,
            "--bash",
            str(bash_path),
            "--expected-bash-sha256",
            sha256(bash_path.read_bytes()).hexdigest(),
            "--",
            "--self-test",
        ]
        completed = subprocess.run(command, capture_output=True, timeout=20)
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "replace"),
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["official_instance_opened"])
        self.assertFalse(payload["solver_child_process_started"])

    def test_exact_stdlib_manifest_and_namespace_contract(self) -> None:
        raw = Path("/tmp/agent-aghfal17-native-v11-stdlib.sha256").read_bytes()
        evidence = runner.verify_stdlib_manifest(
            {"stdlib_manifest": raw}, phase="lightweight_test"
        )
        self.assertEqual(evidence["file_count"], 619)
        self.assertEqual((evidence["expected_uid"], evidence["expected_gid"]), (65534, 65534))
        self.assertTrue(evidence["root_mount_read_only"])
        self.assertFalse(evidence["group_or_world_writable_file_or_ancestor_allowed"])
        minimal = Path("/tmp/agent-aghfal17-native-v11-minimal-tcb.sha256")
        self.assertEqual(
            sha256(minimal.read_bytes()).hexdigest(),
            "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
        )
        self.assertEqual(len(minimal.read_text(encoding="utf-8").splitlines()), 50)


class SealedRuntimeFinderRegressionTests(unittest.TestCase):
    @staticmethod
    def _empty_bundle() -> object:
        return runner.RuntimeBundleAdmission(
            root_fd=-1,
            manifest_fd=-1,
            manifest_sha256="0" * 64,
            entries_by_path={},
            entries_by_identity={},
            evidence={},
        )

    def test_find_spec_never_imports_from_inside_the_custom_finder(self) -> None:
        finder = runner._SealedRuntimeFinder(self._empty_bundle())
        with mock.patch(
            "builtins.__import__",
            side_effect=AssertionError("find_spec re-entered Python import machinery"),
        ):
            self.assertIsNone(finder.find_spec("not_in_the_sealed_runtime"))

    def test_cached_importlib_bindings_survive_package_attribute_poisoning(self) -> None:
        entry = {"fd": -1, "sha256": "0" * 64, "size": 0}
        bundle = self._empty_bundle()
        bundle.entries_by_path["sealed_probe.py"] = entry
        finder = runner._SealedRuntimeFinder(bundle)
        with (
            mock.patch.object(runner.importlib, "machinery", object()),
            mock.patch.object(runner.importlib, "util", object()),
            mock.patch(
                "builtins.__import__",
                side_effect=AssertionError("find_spec attempted a nested import"),
            ),
        ):
            spec = finder.find_spec("sealed_probe")
        self.assertIsNotNone(spec)
        self.assertIsInstance(spec.loader, runner._SealedSourceLoader)

    def test_unmatched_name_delegates_to_the_next_meta_path_finder(self) -> None:
        module_name = "agh_v11_delegation_probe"
        events: list[str] = []

        class ProbeLoader:
            def create_module(self, _spec: object) -> None:
                return None

            def exec_module(self, module: types.ModuleType) -> None:
                module.delegated = True

        class NextFinder:
            def find_spec(
                self, fullname: str, _path: object = None, _target: object = None
            ) -> object:
                events.append(fullname)
                if fullname != module_name:
                    return None
                return runner._importlib_machinery.ModuleSpec(fullname, ProbeLoader())

        sealed_finder = runner._SealedRuntimeFinder(self._empty_bundle())
        next_finder = NextFinder()
        original_meta_path = list(sys.meta_path)
        sys.modules.pop(module_name, None)
        try:
            sys.meta_path[:0] = [sealed_finder, next_finder]
            imported = importlib.import_module(module_name)
            self.assertTrue(imported.delegated)
            self.assertEqual(events, [module_name])
        finally:
            sys.meta_path[:] = original_meta_path
            sys.modules.pop(module_name, None)


class RetainedReportTests(unittest.TestCase):
    def test_parent_retained_report_accepts_exact_named_inode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agh-v11-report-") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "generic-validator-report.json",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o400,
                dir_fd=dirfd,
            )
            try:
                payload = b'{"status":"PASS"}\n'
                os.write(report_fd, payload)
                observed, evidence = supervisor._read_retained_named_regular(
                    dirfd,
                    "generic-validator-report.json",
                    report_fd,
                    maximum_bytes=1024,
                )
                self.assertEqual(observed, payload)
                self.assertTrue(evidence["parent_pread_retained_fd"])
            finally:
                os.close(report_fd)
                os.close(dirfd)

    def test_same_uid_pathname_swap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agh-v11-swap-") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "generic-validator-report.json",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o400,
                dir_fd=dirfd,
            )
            try:
                payload = b'{"status":"PASS"}\n'
                os.write(report_fd, payload)
                os.rename(
                    "generic-validator-report.json",
                    "retained-but-unnamed.json",
                    src_dir_fd=dirfd,
                    dst_dir_fd=dirfd,
                )
                replacement = os.open(
                    "generic-validator-report.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o400,
                    dir_fd=dirfd,
                )
                os.write(replacement, payload)
                os.close(replacement)
                with self.assertRaisesRegex(RuntimeError, "identity drift"):
                    supervisor._read_retained_named_regular(
                        dirfd,
                        "generic-validator-report.json",
                        report_fd,
                        maximum_bytes=1024,
                    )
            finally:
                os.close(report_fd)
                os.close(dirfd)


class ProbeRejectionDiagnosticTests(unittest.TestCase):
    EXPECTED_MODULES = {
        "ortools.sat.python.cp_model",
        "numpy",
        "pandas",
        "dateutil",
        "six",
        "lxml.etree",
        "absl",
        "immutabledict",
        "google.protobuf",
        "typing_extensions",
    }

    def _valid_payload(self) -> dict[str, object]:
        return {
            "schema": "planora.agh-fal17.native-v11-sealed-import-probe.v1",
            "status": "PASS",
            "imported_modules": sorted(self.EXPECTED_MODULES),
            "probe_child_process_started": True,
            "solver_child_process_started": False,
            "official_opened": False,
            "publication": False,
            "official_instance_opened": False,
            "solver_execution_started": False,
            "official_solution_xml_published": False,
            "runner_sha256_start": supervisor.EXPECTED_RUNNER_SHA256,
            "runner_sha256_end": supervisor.EXPECTED_RUNNER_SHA256,
            "runner_hash_stable": True,
        }

    def test_stdout_failure_classes_are_not_collapsed(self) -> None:
        cases = (
            (b"", ("empty", "empty_bytes")),
            (b"{", ("non_json", "invalid_json")),
            (b"\xff", ("non_json", "invalid_utf8")),
            (b"[]", ("non_object", "json_value_not_object")),
            (b"{}", ("object", "json_object")),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                classification, detail, _payload = (
                    supervisor.classify_probe_stdout(raw)
                )
                self.assertEqual((classification, detail), expected)

    def test_exact_valid_claim_still_requires_every_original_predicate(self) -> None:
        payload = self._valid_payload()
        predicates = supervisor.sealed_import_probe_claim_predicates(
            "object", payload, self.EXPECTED_MODULES
        )
        self.assertTrue(all(predicates.values()), predicates)

        mutations = {
            "schema_exact": ("schema", "wrong"),
            "status_pass": ("status", "FAILED"),
            "imported_modules_exact": ("imported_modules", []),
            "official_instance_unopened": ("official_instance_opened", True),
            "solver_execution_not_started": ("solver_execution_started", True),
            "official_solution_not_published": (
                "official_solution_xml_published",
                True,
            ),
            "runner_sha256_start_exact": ("runner_sha256_start", "0" * 64),
            "runner_sha256_end_exact": ("runner_sha256_end", "0" * 64),
            "runner_hash_stable": ("runner_hash_stable", False),
        }
        for predicate, (key, value) in mutations.items():
            mutated = dict(payload)
            mutated[key] = value
            observed = supervisor.sealed_import_probe_claim_predicates(
                "object", mutated, self.EXPECTED_MODULES
            )
            with self.subTest(predicate=predicate):
                self.assertFalse(observed[predicate])

    def test_malformed_payload_reports_individual_failed_predicates(self) -> None:
        predicates = supervisor.sealed_import_probe_claim_predicates(
            "malformed", {}, self.EXPECTED_MODULES
        )
        self.assertTrue(predicates)
        self.assertTrue(all(value is False for value in predicates.values()))
        self.assertIn("schema_exact", predicates)
        self.assertIn("runner_hash_stable", predicates)

    def test_rejection_diagnostics_are_bounded_and_hash_exact(self) -> None:
        stdout_raw = b"prefix:" + (b"y" * 5_000)
        stderr_raw = b"prefix:" + (b"x" * 5_000)
        diagnostics = supervisor.bounded_probe_rejection_diagnostics(
            child_exit_code=73,
            stdout_raw=stdout_raw,
            stderr_raw=stderr_raw,
            stdout_classification="non_json",
            stdout_detail="invalid_json",
            acceptance_predicates={"child_exit_zero": False, "schema_exact": False},
        )
        self.assertEqual(diagnostics["child_exit_code"], 73)
        self.assertEqual(
            diagnostics["failed_predicates"],
            ["child_exit_zero", "schema_exact"],
        )
        self.assertEqual(
            diagnostics["predicate_results"],
            {"child_exit_zero": False, "schema_exact": False},
        )
        self.assertEqual(diagnostics["stdout"]["size_bytes"], len(stdout_raw))
        self.assertEqual(
            diagnostics["stdout"]["sha256"], sha256(stdout_raw).hexdigest()
        )
        self.assertTrue(diagnostics["stdout"]["tail"]["truncated"])
        self.assertEqual(
            base64.b64decode(diagnostics["stdout"]["tail"]["data"]),
            stdout_raw[-supervisor.REJECTION_STDOUT_TAIL_BYTES :],
        )
        stderr = diagnostics["stderr"]
        self.assertEqual(stderr["size_bytes"], len(stderr_raw))
        self.assertEqual(stderr["sha256"], sha256(stderr_raw).hexdigest())
        self.assertTrue(stderr["tail"]["truncated"])
        self.assertEqual(
            base64.b64decode(stderr["tail"]["data"]),
            stderr_raw[-supervisor.REJECTION_STDERR_TAIL_BYTES :],
        )

    def test_diagnostic_envelope_is_attached_only_on_rejection(self) -> None:
        source = SUPERVISOR_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'if errors:\n            payload["rejection_diagnostics"]', source
        )
        self.assertNotIn('payload["rejection_diagnostics"] = {}', source)


class ResourceAndLifecycleTests(unittest.TestCase):
    def test_probe_accounting_excludes_reused_numeric_pgid_occupant(self) -> None:
        supervisor_pid = 101
        leader_pid = 202
        descendant_pid = 203
        reused_pgid_occupant = 299
        supervisor_identity = (100, 100, 700)
        leader_identity = (leader_pid, leader_pid, 800)
        descendant_identity = (leader_pid, leader_pid, 801)
        admitted = {
            leader_pid: leader_identity,
            descendant_pid: descendant_identity,
        }
        identities = {
            supervisor_pid: supervisor_identity,
            leader_pid: leader_identity,
            descendant_pid: descendant_identity,
            reused_pgid_occupant: (leader_pid, leader_pid, 9_999),
        }
        usage = {
            supervisor_pid: (10, 1),
            leader_pid: (20, 2),
            descendant_pid: (30, 3),
            reused_pgid_occupant: (999_999, 999_999),
        }
        with (
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=lambda pid: identities.get(pid),
            ),
            mock.patch.object(
                supervisor,
                "process_usage",
                side_effect=lambda pid: usage[pid],
            ) as process_usage,
            mock.patch.object(
                supervisor,
                "process_group_usage",
                side_effect=AssertionError("numeric PGID accounting forbidden"),
            ),
        ):
            sample = supervisor.generation_accounting_sample(
                supervisor_pid, admitted
            )
        self.assertEqual(
            {row["pid"] for row in sample["sampled_processes"]},
            {supervisor_pid, leader_pid, descendant_pid},
        )
        self.assertNotIn(reused_pgid_occupant, [call.args[0] for call in process_usage.call_args_list])
        self.assertEqual(sample["group_vmrss_plus_vmswap_kib"], 55)
        self.assertEqual(sample["whole_launch_vmrss_plus_vmswap_kib"], 66)
        self.assertFalse(sample["numeric_pgid_rescan_used"])
        self.assertTrue(sample["deduplicated"])

    def test_probe_accounting_fails_closed_on_identity_drift_during_status_read(self) -> None:
        supervisor_pid = 101
        member_pid = 202
        supervisor_identity = (100, 100, 700)
        member_identity = (member_pid, member_pid, 800)
        changed_identity = (member_pid, member_pid, 801)
        member_calls = 0

        def identity(pid: int):
            nonlocal member_calls
            if pid == supervisor_pid:
                return supervisor_identity
            member_calls += 1
            return member_identity if member_calls == 1 else changed_identity

        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(supervisor, "process_usage", return_value=(20, 2)),
        ):
            sample = supervisor.generation_accounting_sample(
                supervisor_pid, {member_pid: member_identity}
            )
        self.assertNotIn(member_pid, [row["pid"] for row in sample["sampled_processes"]])
        self.assertTrue(
            any(
                row.get("reason") == "identity_drift_during_status_read"
                for row in sample["unavailable_identities"]
            )
        )
        self.assertTrue(
            sample["identity_replayed_before_and_after_each_status_read"]
        )

    @staticmethod
    def _vanished_leader_accounting(
        member_pid: object,
        member_identity: tuple[int, int, int],
        *,
        reason: str = "identity_replay_mismatch",
        observed: tuple[int, int, int] | None = None,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "role": "generation_member",
            "pid": member_pid,
            "expected_identity": list(member_identity),
            "reason": reason,
        }
        if reason == "identity_replay_mismatch":
            row["observed_identity"] = (
                None if observed is None else list(observed)
            )
        else:
            row["observed_identity_after_status"] = (
                None if observed is None else list(observed)
            )
        return {
            "sampled_processes": [],
            "unavailable_identities": [row],
        }

    def test_vanish_after_valid_sample_and_successful_reap_contributes_zero(self) -> None:
        member_pid = 202
        identity = (member_pid, member_pid, 800)
        child = mock.Mock(pid=member_pid)
        child.poll.return_value = 0
        accounting = self._vanished_leader_accounting(member_pid, identity)

        with mock.patch.object(supervisor, "proc_stat_identity", return_value=None):
            resolved = supervisor.reconcile_successfully_reaped_generation_member(
                accounting,
                child,
                identity,
                {member_pid: identity},
                {(member_pid, identity)},
            )

        self.assertEqual(resolved["unavailable_identities"], [])
        self.assertTrue(resolved["successful_reap_zero_contribution_used"])
        self.assertEqual(
            resolved["successfully_reaped_zero_contributions"],
            [
                {
                    "role": "generation_member",
                    "pid": member_pid,
                    "identity": {
                        "process_group": member_pid,
                        "session": member_pid,
                        "starttime_ticks": 800,
                    },
                    "vmrss_kib": 0,
                    "vmswap_kib": 0,
                    "vmrss_plus_vmswap_kib": 0,
                    "basis": "prior_valid_identity_bound_sample_successful_zero_exit_reap_and_final_absence",
                }
            ],
        )
        child.poll.assert_called_once_with()

    def test_vanish_during_status_read_after_valid_sample_and_reap_contributes_zero(self) -> None:
        member_pid = 202
        identity = (member_pid, member_pid, 800)
        child = mock.Mock(pid=member_pid)
        child.poll.return_value = 0
        accounting = self._vanished_leader_accounting(
            member_pid,
            identity,
            reason="identity_drift_during_status_read",
        )
        with mock.patch.object(supervisor, "proc_stat_identity", return_value=None):
            resolved = supervisor.reconcile_successfully_reaped_generation_member(
                accounting,
                child,
                identity,
                {member_pid: identity},
                {(member_pid, identity)},
            )
        self.assertEqual(resolved["unavailable_identities"], [])
        self.assertTrue(resolved["successful_reap_zero_contribution_used"])

    def test_reaped_zero_contribution_rejects_every_unsafe_case(self) -> None:
        member_pid = 202
        identity = (member_pid, member_pid, 800)
        changed_identity = (member_pid, member_pid, 801)

        cases = {
            "never_sampled": {
                "accounting": self._vanished_leader_accounting(member_pid, identity),
                "child_pid": member_pid,
                "exit_code": 0,
                "leader": identity,
                "admitted": {member_pid: identity},
                "sampled": set(),
                "observed_after": None,
            },
            "nonzero_reap": {
                "accounting": self._vanished_leader_accounting(member_pid, identity),
                "child_pid": member_pid,
                "exit_code": 1,
                "leader": identity,
                "admitted": {member_pid: identity},
                "sampled": {(member_pid, identity)},
                "observed_after": None,
            },
            "identity_reused": {
                "accounting": self._vanished_leader_accounting(
                    member_pid, identity, observed=changed_identity
                ),
                "child_pid": member_pid,
                "exit_code": 0,
                "leader": identity,
                "admitted": {member_pid: identity},
                "sampled": {(member_pid, identity)},
                "observed_after": changed_identity,
            },
            "unreadable_live_status": {
                "accounting": {
                    "sampled_processes": [],
                    "unavailable_identities": [
                        {
                            "role": "generation_member",
                            "pid": member_pid,
                            "identity": list(identity),
                            "reason": "required process accounting unavailable: 202",
                        }
                    ],
                },
                "child_pid": member_pid,
                "exit_code": 0,
                "leader": identity,
                "admitted": {member_pid: identity},
                "sampled": {(member_pid, identity)},
                "observed_after": None,
            },
            "identity_drift": {
                "accounting": self._vanished_leader_accounting(
                    member_pid,
                    identity,
                    reason="identity_drift_during_status_read",
                    observed=changed_identity,
                ),
                "child_pid": member_pid,
                "exit_code": 0,
                "leader": identity,
                "admitted": {member_pid: identity},
                "sampled": {(member_pid, identity)},
                "observed_after": changed_identity,
            },
            "untrusted_numeric_pid": {
                "accounting": self._vanished_leader_accounting(True, (1, 1, 800)),
                "child_pid": True,
                "exit_code": 0,
                "leader": (1, 1, 800),
                "admitted": {True: (1, 1, 800)},
                "sampled": {(True, (1, 1, 800))},
                "observed_after": None,
            },
            "admitted_identity_drift": {
                "accounting": self._vanished_leader_accounting(member_pid, identity),
                "child_pid": member_pid,
                "exit_code": 0,
                "leader": identity,
                "admitted": {member_pid: changed_identity},
                "sampled": {(member_pid, identity)},
                "observed_after": None,
            },
            "different_child_pid": {
                "accounting": self._vanished_leader_accounting(member_pid, identity),
                "child_pid": 303,
                "exit_code": 0,
                "leader": identity,
                "admitted": {member_pid: identity},
                "sampled": {(member_pid, identity)},
                "observed_after": None,
            },
        }

        for name, case in cases.items():
            with self.subTest(name=name):
                child = mock.Mock(pid=case["child_pid"])
                child.poll.return_value = case["exit_code"]
                with mock.patch.object(
                    supervisor,
                    "proc_stat_identity",
                    return_value=case["observed_after"],
                ):
                    resolved = supervisor.reconcile_successfully_reaped_generation_member(
                        case["accounting"],
                        child,
                        case["leader"],
                        case["admitted"],
                        case["sampled"],
                    )
                self.assertTrue(resolved["unavailable_identities"])
                self.assertFalse(resolved["successful_reap_zero_contribution_used"])
                self.assertEqual(
                    resolved["successfully_reaped_zero_contributions"], []
                )

    def test_probe_truth_schema_is_exact(self) -> None:
        payload = {
            "probe_child_process_started": True,
            "solver_child_process_started": False,
            "official_opened": False,
            "publication": False,
        }
        self.assertTrue(supervisor.validate_probe_truth_schema(payload))
        for key in tuple(payload):
            mutated = dict(payload)
            mutated[key] = not bool(mutated[key])
            with self.subTest(key=key):
                self.assertFalse(supervisor.validate_probe_truth_schema(mutated))

    def test_outer_hard_wall_drains_spawned_descendant_tree(self) -> None:
        child = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);time.sleep(30)"
        )
        command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            child,
            "--sealed-import-probe",
        ]
        command_hash = sha256(
            json.dumps(command, separators=(",", ":")).encode()
        ).hexdigest()
        payload = harness.run_contained(
            command,
            0.10,
            expected_command_sha256=command_hash,
        )
        self.assertEqual(payload["reason"], "outer_hard_wall")
        self.assertTrue(payload["post_exit_empty"])
        self.assertEqual(payload["final_residual_identities"], [])
        self.assertFalse(payload["numeric_process_group_signal_sent"])
        self.assertTrue(payload["probe_child_process_started"])
        self.assertFalse(payload["solver_child_process_started"])
        self.assertFalse(payload["official_opened"])
        self.assertFalse(payload["publication"])

    def test_external_stop_signal_still_runs_outer_cleanup(self) -> None:
        child = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);time.sleep(30)"
        )
        command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            child,
            "--sealed-import-probe",
        ]
        command_hash = sha256(
            json.dumps(command, separators=(",", ":")).encode()
        ).hexdigest()
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(HARNESS_PATH),
                "--wall-seconds",
                "5",
                "--expected-command-sha256",
                command_hash,
                "--",
                *command,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(0.15)
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        self.assertNotEqual(process.returncode, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["reason"].startswith("signal:"))
        self.assertTrue(payload["post_exit_empty"])
        self.assertEqual(payload["final_residual_identities"], [])

    def test_retained_inner_json_is_exact_and_failure_status_propagates(self) -> None:
        cases = (
            ("import json;print(json.dumps({'status':'PASS'}))", 0, "PASS"),
            ("print('{\"status\":\"NO_GO\"}')", 0, "FAILED"),
            ("print('{\"status\":\"PASS\"}');raise SystemExit(3)", 3, "FAILED"),
            ("print('{\"status\":\"PASS\"}{\"status\":\"PASS\"}')", 0, "FAILED"),
        )
        for script, _exit, expected in cases:
            command = [
                sys.executable, "-I", "-S", "-B", "-c", script,
                "--sealed-import-probe",
            ]
            command_hash = sha256(
                json.dumps(command, separators=(",", ":")).encode()
            ).hexdigest()
            with self.subTest(expected=expected, script=script):
                payload = harness.run_contained(
                    command,
                    2,
                    expected_command_sha256=command_hash,
                )
                self.assertEqual(payload["status"], expected)
                self.assertEqual(
                    payload["inner_stdout"]["transport"],
                    "parent_created_retained_memfd",
                )
                self.assertEqual(
                    payload["report_transport"],
                    "parent_created_retained_memfd",
                )

    def test_sigkill_harness_parent_death_chain_leaves_no_root_or_grandchild(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="agh-v11-pdeath-") as raw:
            pid_path = Path(raw) / "pids"
            root_script = (
                "import ctypes,os,signal,subprocess,sys,time;"
                "libc=ctypes.CDLL(None);"
                "exec('def arm():\\n libc.prctl(1,int(signal.SIGKILL),0,0,0)');"
                "child=subprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(30)'],preexec_fn=arm);"
                "open(sys.argv[1],'w').write(str(os.getpid())+' '+str(child.pid));"
                "time.sleep(30)"
            )
            command = [
                sys.executable, "-I", "-S", "-B", "-c", root_script,
                str(pid_path), "--sealed-import-probe",
            ]
            command_hash = sha256(
                json.dumps(command, separators=(",", ":")).encode()
            ).hexdigest()
            outer = subprocess.Popen(
                [
                    sys.executable, "-I", "-S", "-B", str(HARNESS_PATH),
                    "--wall-seconds", "5",
                    "--expected-command-sha256", command_hash,
                    "--", *command,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not pid_path.exists():
                    time.sleep(0.02)
                self.assertTrue(pid_path.exists())
                root_pid, grandchild_pid = map(int, pid_path.read_text().split())
                identities = {
                    root_pid: harness.proc_identity(root_pid),
                    grandchild_pid: harness.proc_identity(grandchild_pid),
                }
                self.assertTrue(all(value is not None for value in identities.values()))
                os.kill(outer.pid, signal.SIGKILL)
                outer.wait(timeout=3)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if all(
                        harness.proc_identity(pid) != identity
                        for pid, identity in identities.items()
                    ):
                        break
                    time.sleep(0.02)
                self.assertTrue(
                    all(
                        harness.proc_identity(pid) != identity
                        for pid, identity in identities.items()
                    ),
                    identities,
                )
            finally:
                if outer.poll() is None:
                    outer.kill()
                    outer.wait()

    def test_child_signal_state_is_reset_and_unblocked(self) -> None:
        with (
            mock.patch.object(supervisor.signal, "signal") as install,
            mock.patch.object(supervisor.signal, "pthread_sigmask") as unblock,
        ):
            supervisor._reset_child_stop_signals()
        self.assertEqual(
            install.call_args_list,
            [mock.call(value, signal.SIG_DFL) for value in supervisor.STOP_SIGNALS],
        )
        unblock.assert_called_once_with(signal.SIG_UNBLOCK, supervisor.STOP_SIGNALS)

    def test_member_pid_reuse_before_pidfd_signal_fails_closed(self) -> None:
        pgid = 424_242
        admitted = (pgid, pgid, 1000)
        replaced = (pgid, pgid, 2000)
        with (
            mock.patch.object(supervisor.os, "pidfd_open", return_value=77),
            mock.patch.object(supervisor, "proc_stat_identity", return_value=replaced),
            mock.patch.object(supervisor.os, "close") as close_fd,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as send_signal,
        ):
            result = supervisor.signal_process_group_snapshot(
                pgid,
                ((pgid, admitted),),
                signal.SIGTERM,
                {pgid: admitted},
            )
        close_fd.assert_called_once_with(77)
        send_signal.assert_not_called()
        self.assertIn(f"member_identity_replay:{pgid}", result["errors"])

    def test_generation_refresh_admits_only_while_leader_is_anchored(self) -> None:
        pgid = 434_343
        leader = (pgid, pgid, 1000)
        descendant = (pgid, pgid, 1001)
        admitted = {pgid: leader}
        with (
            mock.patch.object(
                supervisor, "proc_stat_identity", side_effect=[leader, leader]
            ),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                return_value=((pgid, leader), (pgid + 1, descendant)),
            ),
        ):
            evidence = supervisor.refresh_group_generation(
                pgid, leader, admitted
            )
        self.assertEqual(evidence["added_pids"], [pgid + 1])
        self.assertEqual(admitted[pgid + 1], descendant)

    def test_generation_refresh_discards_snapshot_if_leader_anchor_is_lost(self) -> None:
        pgid = 444_444
        leader = (pgid, pgid, 1000)
        descendant = (pgid, pgid, 1001)
        admitted = {pgid: leader}
        with (
            mock.patch.object(
                supervisor, "proc_stat_identity", side_effect=[leader, None]
            ),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                return_value=((pgid + 1, descendant),),
            ),
        ):
            evidence = supervisor.refresh_group_generation(
                pgid, leader, admitted
            )
        self.assertIn(
            "original_leader_anchor_lost_during_snapshot", evidence["errors"]
        )
        self.assertNotIn(pgid + 1, admitted)

    def test_pre_first_snapshot_reused_orphan_group_is_never_signalled(self) -> None:
        pgid = 515_151
        original = (pgid, pgid, 1000)
        reused_descendant_pid = pgid + 1
        reused = ((reused_descendant_pid, (pgid, pgid, 9001)),)
        child = mock.Mock()
        child.pid = pgid
        child.returncode = 0
        child.wait.return_value = 0
        with (
            mock.patch.object(supervisor, "proc_stat_identity", return_value=None),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                side_effect=[reused, reused],
            ),
            mock.patch.object(supervisor, "TERMINATION_GRACE_SECONDS", 0),
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as send_signal,
        ):
            result = supervisor.stop_group(
                child, pgid, original, 99, {pgid: original}
            )
        send_signal.assert_not_called()
        self.assertFalse(result["empty"])
        self.assertFalse(result["numeric_pgid_signal_sent"])
        self.assertEqual(result["untrusted_generation_pids"], [reused_descendant_pid])
        self.assertTrue(
            all(not action["signaled_pids"] for action in result["actions"])
        )

    def test_pidfd_open_emfile_does_not_skip_later_member_in_each_pass(self) -> None:
        pgid = 525_252
        first = (pgid, pgid, 1000)
        second = (pgid, pgid, 1001)
        snapshot = ((pgid, first), (pgid + 1, second))
        admitted = {pgid: first, pgid + 1: second}
        for signum in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signum=signum):
                with (
                    mock.patch.object(
                        supervisor.os,
                        "pidfd_open",
                        side_effect=[OSError(errno.EMFILE, "fd table full"), 78],
                    ),
                    mock.patch.object(
                        supervisor,
                        "proc_stat_identity",
                        return_value=second,
                    ),
                    mock.patch.object(supervisor.os, "close") as close_fd,
                    mock.patch.object(
                        supervisor.signal, "pidfd_send_signal"
                    ) as send_signal,
                ):
                    result = supervisor.signal_process_group_snapshot(
                        pgid, snapshot, signum, admitted
                    )
            send_signal.assert_called_once_with(78, signum, None, 0)
            close_fd.assert_called_once_with(78)
            self.assertEqual(result["signaled_pids"], [pgid + 1])
            self.assertTrue(
                any(value.startswith(f"pidfd_open:{pgid}:{errno.EMFILE}") for value in result["errors"])
            )

    def test_pidfd_send_eperm_does_not_skip_later_member_in_each_pass(self) -> None:
        pgid = 535_353
        first = (pgid, pgid, 1000)
        second = (pgid, pgid, 1001)
        snapshot = ((pgid, first), (pgid + 1, second))
        admitted = {pgid: first, pgid + 1: second}
        for signum in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signum=signum):
                with (
                    mock.patch.object(
                        supervisor.os, "pidfd_open", side_effect=[77, 78]
                    ),
                    mock.patch.object(
                        supervisor,
                        "proc_stat_identity",
                        side_effect=[first, second],
                    ),
                    mock.patch.object(supervisor.os, "close"),
                    mock.patch.object(
                        supervisor.signal,
                        "pidfd_send_signal",
                        side_effect=[OSError(errno.EPERM, "denied"), None],
                    ) as send_signal,
                ):
                    result = supervisor.signal_process_group_snapshot(
                        pgid, snapshot, signum, admitted
                    )
            self.assertEqual(send_signal.call_count, 2)
            self.assertEqual(result["signaled_pids"], [pgid + 1])
            self.assertTrue(
                any(value.startswith(f"pidfd_send_signal:{pgid}:{errno.EPERM}") for value in result["errors"])
            )

    def test_wait_exception_does_not_skip_final_descendant_drain(self) -> None:
        pgid = 616_161
        original = (pgid, pgid, 1000)
        initial = ((pgid, original),)
        child = mock.Mock()
        child.pid = pgid
        child.returncode = 0
        child.wait.side_effect = [OSError("deterministic wait fault"), 0]
        signal_evidence = {
            "signal": int(signal.SIGTERM),
            "snapshot_pids": [pgid],
            "eligible_pids": [pgid],
            "untrusted_pids": [],
            "signaled_pids": [pgid],
            "vanished_pids": [],
            "errors": [],
            "numeric_pgid_signal_sent": False,
        }
        with (
            mock.patch.object(
                supervisor,
                "refresh_group_generation",
                return_value={
                    "leader_anchored_before": True,
                    "leader_anchored_after": True,
                    "added_pids": [],
                    "errors": [],
                },
            ),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                side_effect=[initial, ()],
            ),
            mock.patch.object(supervisor, "TERMINATION_GRACE_SECONDS", 0),
            mock.patch.object(
                supervisor,
                "signal_process_group_snapshot",
                return_value=signal_evidence,
            ) as signal_members,
        ):
            result = supervisor.stop_group(
                child, pgid, original, 99, {pgid: original}
            )
        self.assertEqual(signal_members.call_count, 2)
        signal_members.assert_any_call(
            pgid, initial, signal.SIGTERM, {pgid: original}
        )
        signal_members.assert_any_call(
            pgid, initial, signal.SIGKILL, {pgid: original}
        )
        self.assertTrue(result["empty"])
        self.assertTrue(
            any(value.startswith("initial_wait:OSError") for value in result["errors"])
        )

    def test_production_cleanup_has_no_numeric_process_group_signal(self) -> None:
        source = SUPERVISOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn("killpg(", source)
        self.assertIn("signal.pidfd_send_signal", source)
        self.assertIn("proc_stat_identity", source)

    def test_unreaped_zombie_leader_is_reaped_and_descendants_drained(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);time.sleep(0.2)"
        )
        child = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        leader_identity = supervisor.proc_stat_identity(child.pid)
        self.assertIsNotNone(leader_identity)
        leader_pidfd = os.pidfd_open(child.pid, 0)
        admitted_members = {child.pid: leader_identity}
        try:
            admission_deadline = supervisor.time.monotonic() + 2
            while supervisor.time.monotonic() < admission_deadline:
                snapshot = supervisor.process_group_snapshot(child.pid)
                if len(snapshot) >= 2:
                    generation = supervisor.refresh_group_generation(
                        child.pid, leader_identity, admitted_members
                    )
                    self.assertFalse(generation["errors"], generation)
                    break
                supervisor.time.sleep(0.01)
            self.assertGreaterEqual(len(admitted_members), 2)
            deadline = supervisor.time.monotonic() + 3
            state = None
            while supervisor.time.monotonic() < deadline:
                try:
                    raw = (Path("/proc") / str(child.pid) / "stat").read_text()
                except FileNotFoundError:
                    break
                state = raw[raw.rfind(")") + 2 :].split()[0]
                if state == "Z":
                    break
                supervisor.time.sleep(0.01)
            self.assertEqual(state, "Z")
            self.assertIsNone(child.returncode)
            result = supervisor.stop_group(
                child,
                child.pid,
                leader_identity,
                leader_pidfd,
                admitted_members,
            )
            self.assertTrue(result["leader_reaped_before_group_interpretation"])
            self.assertTrue(result["empty"], result)
        finally:
            os.close(leader_pidfd)
            for pid, _identity in supervisor.process_group_snapshot(child.pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def test_whole_launch_cap_includes_supervisor_without_double_count(self) -> None:
        sample = {
            "mem_available_kib": 2_000_000,
            "swap_free_kib": 0,
            "pswpin_pages": 10**12,
            "pswpout_pages": 10**12,
        }
        self.assertEqual(
            supervisor.breach_reason(
                elapsed=0,
                group_rss_kib=supervisor.PROCESS_GROUP_MEMORY_LIMIT_KIB - 1,
                group_vmswap_kib=0,
                supervisor_rss_kib=(
                    supervisor.WHOLE_LAUNCH_MEMORY_LIMIT_KIB
                    - supervisor.PROCESS_GROUP_MEMORY_LIMIT_KIB
                    + 1
                ),
                supervisor_vmswap_kib=0,
                supervisor_in_group=False,
                sample=sample,
                launch=False,
            ),
            "whole_launch_vmrss_plus_vmswap_limit",
        )
        self.assertIsNone(
            supervisor.breach_reason(
                elapsed=0,
                group_rss_kib=100,
                group_vmswap_kib=100,
                supervisor_rss_kib=100,
                supervisor_vmswap_kib=100,
                supervisor_in_group=True,
                sample=sample,
                launch=False,
            )
        )

    def test_host_swap_is_telemetry_only(self) -> None:
        sample = {
            "mem_available_kib": 2_000_000,
            "swap_free_kib": 0,
            "pswpin_pages": 10**15,
            "pswpout_pages": 10**15,
        }
        self.assertIsNone(
            supervisor.breach_reason(
                elapsed=0,
                group_rss_kib=0,
                group_vmswap_kib=0,
                sample=sample,
                launch=False,
            )
        )


class PublicationTests(unittest.TestCase):
    def test_report_last_no_replace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agh-v11-publish-") as raw:
            directory = Path(raw)
            os.chmod(directory, 0o700)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            row = os.fstat(dirfd)
            binding = {
                "fd": dirfd,
                "path": str(directory),
                "device": int(row.st_dev),
                "inode": int(row.st_ino),
                "mode": stat.S_IMODE(row.st_mode),
                "uid": int(row.st_uid),
            }
            try:
                with mock.patch.dict(
                    os.environ,
                    {runner.OUTPUT_BINDING_ENV: json.dumps(binding)},
                    clear=False,
                ):
                    evidence = runner.publish_bundle(
                        {runner.OUTPUT_XML: b"<solution/>", runner.OUTPUT_REPORT: b"{}\n"}
                    )
                self.assertEqual(evidence[runner.OUTPUT_XML]["publication_order"], 1)
                self.assertEqual(evidence[runner.OUTPUT_REPORT]["publication_order"], 2)
                with mock.patch.dict(
                    os.environ,
                    {runner.OUTPUT_BINDING_ENV: json.dumps(binding)},
                    clear=False,
                ):
                    with self.assertRaises(FileExistsError):
                        runner.publish_bundle({runner.OUTPUT_REPORT: b"replacement"})
            finally:
                os.close(dirfd)


class NoResultAcceptanceTests(unittest.TestCase):
    def test_no_result_publishes_nothing_and_xml_tamper_is_rejected(self) -> None:
        child = {
            "schema": "planora.agh-fal17.native-v11-runner.v1",
            "status": "NO_RESULT",
            "elapsed_seconds": 1.0,
            "cooperative_deadline_seconds": 1_680.0,
            "runner_sha256_start": supervisor.EXPECTED_RUNNER_SHA256,
            "runner_sha256_end": supervisor.EXPECTED_RUNNER_SHA256,
            "runner_hash_stable": True,
            "native_validation_complete": False,
            "xml_published": False,
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
        }
        with tempfile.TemporaryDirectory(prefix="agh-v11-no-result-") as raw:
            directory = Path(raw)
            (directory / "child.stdout.log").write_text(
                json.dumps(child), encoding="utf-8"
            )
            (directory / "child.stderr.log").write_bytes(b"")
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                status, errors, _ = supervisor.agh_child_acceptance(
                    dirfd=dirfd,
                    run_dir=directory,
                    child_exit_code=2,
                    observed_child_elapsed_seconds=1.1,
                )
                self.assertEqual((status, errors), ("NO_RESULT", []))
                (directory / "solution.xml").write_bytes(b"<solution/>")
                status, errors, _ = supervisor.agh_child_acceptance(
                    dirfd=dirfd,
                    run_dir=directory,
                    child_exit_code=2,
                    observed_child_elapsed_seconds=1.1,
                )
                self.assertEqual(status, "FAILED")
                self.assertIn("no_result_published_completion_artifacts", errors)
            finally:
                os.close(dirfd)


if __name__ == "__main__":
    unittest.main()
