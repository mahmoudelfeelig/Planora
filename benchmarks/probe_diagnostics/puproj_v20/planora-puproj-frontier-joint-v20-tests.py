#!/usr/bin/env python3
"""Focused regression and freeze gates for the PU-PROJ v20 control plane."""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest


ARTIFACT_ROOT = Path(__file__).resolve().parent
ROOT = ARTIFACT_ROOT.parents[2]
SUPERVISOR = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v20-supervisor.py"
LAUNCHER = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v20-launcher.py"
FREEZE = ARTIFACT_ROOT / "planora-puproj-frontier-joint-v20-freeze.json"
V19_ROOT = ARTIFACT_ROOT.parent / "puproj_v19"

OBSERVED_V19_GROUP_RSS_KIB = 1_336_416
OBSERVED_V19_WHOLE_LAUNCH_KIB = 1_400_740


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load(SUPERVISOR, "puproj_v20_supervisor_tested")
sealed_launcher = load(LAUNCHER, "puproj_v20_launcher_tested")


class ResourceContractTests(unittest.TestCase):
    def test_observed_v19_peak_is_admitted_with_bounded_headroom(self) -> None:
        self.assertEqual(guard.PROCESS_GROUP_RSS_LIMIT_KIB, 1_550_000)
        self.assertEqual(guard.WHOLE_LAUNCH_MEMORY_LIMIT_KIB, 1_600_000)
        self.assertLess(
            OBSERVED_V19_GROUP_RSS_KIB,
            guard.PROCESS_GROUP_RSS_LIMIT_KIB,
        )
        self.assertIsNone(
            guard.whole_launch_breach(OBSERVED_V19_WHOLE_LAUNCH_KIB, 0)
        )
        self.assertGreaterEqual(
            guard.WHOLE_LAUNCH_MEMORY_LIMIT_KIB - OBSERVED_V19_WHOLE_LAUNCH_KIB,
            190_000,
        )

    def test_new_limits_remain_strict_boundaries(self) -> None:
        self.assertIsNone(
            guard.whole_launch_breach(
                guard.WHOLE_LAUNCH_MEMORY_LIMIT_KIB - 1,
                0,
            )
        )
        self.assertEqual(
            guard.whole_launch_breach(
                guard.WHOLE_LAUNCH_MEMORY_LIMIT_KIB,
                0,
            ),
            "whole_launch_vmrss_plus_vmswap_limit",
        )
        sample = {
            "mem_available_kib": guard.RUNTIME_MIN_MEM_AVAILABLE_KIB,
            "pswpin_pages": 0,
            "pswpout_pages": 0,
        }
        self.assertEqual(
            guard.breach_reason(
                elapsed=0.0,
                group_rss_kib=guard.PROCESS_GROUP_RSS_LIMIT_KIB,
                group_vmswap_kib=0,
                sample=sample,
                launch=False,
            ),
            "process_group_rss_limit",
        )

    def test_probe_limits_are_not_relaxed(self) -> None:
        self.assertEqual(guard.PROBE_PROCESS_GROUP_RSS_LIMIT_KIB, 1_200_000)
        self.assertEqual(guard.PROBE_WHOLE_LAUNCH_MEMORY_LIMIT_KIB, 1_300_000)
        self.assertEqual(guard.PROBE_RUNTIME_MIN_MEM_AVAILABLE_KIB, 600_000)


class FreezeLinkageTests(unittest.TestCase):
    def test_launcher_pins_exact_v20_supervisor(self) -> None:
        self.assertEqual(sealed_launcher.SUPERVISOR, SUPERVISOR)
        self.assertEqual(
            sealed_launcher.EXPECTED_SUPERVISOR_SHA256,
            sha256(SUPERVISOR.read_bytes()).hexdigest(),
        )

    def test_v20_reuses_exact_frozen_v19_solver_runtime_closure(self) -> None:
        self.assertEqual(guard.ARTIFACT_ROOT, V19_ROOT)
        self.assertEqual(
            guard.EXPECTED_RUNNER_SHA256,
            "43772c50e4804a56fc995542c1fbe61bef66e9e360eae7d7c24aeda8f0023548",
        )
        self.assertEqual(
            sha256(guard.RUNNER.read_bytes()).hexdigest(),
            guard.EXPECTED_RUNNER_SHA256,
        )

    def test_v19_frozen_artifacts_remain_byte_identical(self) -> None:
        expected = {
            "planora-puproj-frontier-joint-v19-bootstrap": "a4230de58dd5cca9e2e5e4c85cab40b669a354c3c960068d6a54ec094d0e64de",
            "planora-puproj-frontier-joint-v19-launcher.py": "a31a189c8aec149c527ac91a83c099c581949aa26f0f8326bd706e7982d46e21",
            "planora-puproj-frontier-joint-v19-supervisor.py": "6ef096d3708352096aade8289a094a5640fff18df8994d46c5e3c96c483318f9",
            "planora-puproj-frontier-joint-v19-runner.py": "43772c50e4804a56fc995542c1fbe61bef66e9e360eae7d7c24aeda8f0023548",
            "planora-puproj-frontier-joint-v19-freeze.json": "163fbf0e9cea0ce25e881fb3ea563286c97c6d7291ef93338088acfff24b0ac9",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(sha256((V19_ROOT / name).read_bytes()).hexdigest(), digest)

    def test_v20_freeze_matches_exact_control_plane_and_remains_no_go(self) -> None:
        freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(
            freeze["verdict"],
            "GO_FOR_SEALED_IMPORT_PROBE_NO_GO_FOR_OFFICIAL_LAUNCH",
        )
        self.assertFalse(freeze["verification"]["official_launch_authorized"])
        for label, path in {
            "supervisor": SUPERVISOR,
            "launcher": LAUNCHER,
            "tests": Path(__file__).resolve(),
        }.items():
            row = freeze["control_plane"][label]
            self.assertEqual(row["size"], path.stat().st_size)
            self.assertEqual(row["sha256"], sha256(path.read_bytes()).hexdigest())
        self.assertEqual(
            freeze["reused_frozen_v19_closure"]["runner"]["sha256"],
            guard.EXPECTED_RUNNER_SHA256,
        )


@unittest.skipUnless(
    os.name == "posix" and hasattr(signal, "pidfd_send_signal"),
    "Linux pidfd process-generation semantics required",
)
class CleanupRegressionTests(unittest.TestCase):
    def test_sigkill_generation_is_reaped_before_final_empty_proof(self) -> None:
        child = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                "import signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(30)",
            ],
            preexec_fn=os.setsid,
        )
        ownership = guard.create_owned_group(child.pid)
        try:
            exit_code, wait_error, cleanup = guard.wait_child_and_drain(
                child,
                ownership,
                timeout=0.05,
            )
            self.assertEqual(exit_code, -signal.SIGKILL)
            self.assertIsNotNone(wait_error)
            self.assertIn("TimeoutExpired", wait_error)
            self.assertTrue(cleanup["empty"], cleanup)
            self.assertEqual(cleanup["final_owned_pids"], [])
            self.assertEqual(cleanup["errors"], [])
            self.assertTrue(cleanup["leader_generation_gone"])
            self.assertTrue(
                any(
                    action["signal"] == signal.SIGKILL
                    for action in cleanup["actions"]
                )
            )
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
