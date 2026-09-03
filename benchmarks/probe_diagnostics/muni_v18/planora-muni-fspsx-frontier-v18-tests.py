#!/usr/bin/env python3
"""Synthetic/adversarial gates for MUNI-FSPSX frontier v18.

This suite deliberately never opens the official instance or v35 progress.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import errno
from hashlib import sha256
import importlib.util
import inspect
import io
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
from xml.etree import ElementTree


CHAIN_ROOT = Path(__file__).resolve().parent
RUNNER = CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-runner.py"
SUPERVISOR = CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-supervisor.py"
LAUNCHER = CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-launcher.sh"
BOOTSTRAP = CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-bootstrap.py"
INLINE_TRUST = CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-inline-trust-root.txt"
STDLIB_MANIFEST = CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-stdlib.sha256"
PYTHON = Path("/usr/bin/python3.12")
V12_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v12-bootstrap.py": "332ec8fd4e428098dd5199ef27668d95b048d531fe5a6520f228adfc6db45a6f",
    "/tmp/planora-muni-fspsx-frontier-v12-freeze-manifest.json": "31f8ce0fdc08046c05ed2aaf0d0f7f2ff6715d617fd04255c0b1bb6b5d4c25e1",
    "/tmp/planora-muni-fspsx-frontier-v12-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v12-inline-trust-root.txt": "96ddcd4dee6430b8cef56d8b595a8614ee90fad4bcdfb5e99265c0cc240857c2",
    "/tmp/planora-muni-fspsx-frontier-v12-launcher.sh": "71dd37dbb8b3195ef2397a9a8682c5a060b31176850eb79c48739d371c095e9a",
    "/tmp/planora-muni-fspsx-frontier-v12-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v12-runner.py": "1ce9d2b98328e978aa5a09d0486ff7f323ab45dda66c0e730e3ab5ba6a07a46b",
    "/tmp/planora-muni-fspsx-frontier-v12-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v12-supervisor.py": "cc12bcfe504f677afa03bf8dc8f37eabb85f599ac6784f3093eb8ae2053ed53b",
    "/tmp/planora-muni-fspsx-frontier-v12-tests.py": "4a603f9940b4e11029a5d93ee63841f512e82542cbbb5f69617afd996253b10d",
    "/tmp/planora_muni_v12_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v12-certificate.json": "175a02ea6bc14612d56293637a461430812b826890bcab97829bb841f8d77b2b",
}
V13_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v13-bootstrap.py": "b2cecc1fdac3693e5609f629bcb75cf5e80ecfc7eac7af06876f918ece02ff61",
    "/tmp/planora-muni-fspsx-frontier-v13-freeze-manifest.json": "75c55c6afa4ca6a97bbdc4f224d3db4741ec87854d22e00c7ee2a53895b5fbd7",
    "/tmp/planora-muni-fspsx-frontier-v13-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v13-inline-trust-root.txt": "a124a1f5b4146f883b6a42d47f28f7000126cd07e20da98f9aa2bdf9ea978838",
    "/tmp/planora-muni-fspsx-frontier-v13-launcher.sh": "e16543251b163c6ea117591241c5932460935a004f0c6380060e03d2cc94916b",
    "/tmp/planora-muni-fspsx-frontier-v13-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v13-runner.py": "3e0493d59a604dc7c99a73535662ebf868a96aa158f7c4ebdddb228f72c64051",
    "/tmp/planora-muni-fspsx-frontier-v13-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v13-supervisor.py": "38464e78c14c901b25d9ad32a1981cfc4703607dc543fe5484d9a131a1087d0b",
    "/tmp/planora-muni-fspsx-frontier-v13-tests.py": "b77b492ba801ac1533008affe83033fb96ef52ca7f1e10e58daeeae5c515d81b",
    "/tmp/planora_muni_v13_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v13-certificate.json": "0ba69667fb96c02d2cd2b574e7fec7ea30f32d179058eefee4b9315256775425",
}
V14_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v14-bootstrap.py": "9ae7a20b7b16ae37d72571685f1f3d0cf392b6062558704170ecf4b92fdd1d1a",
    "/tmp/planora-muni-fspsx-frontier-v14-freeze-manifest.json": "d2a4ada2b647b948299638296fb75b297b7206984ff10201bfddcb0aecee6eaf",
    "/tmp/planora-muni-fspsx-frontier-v14-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v14-inline-trust-root.txt": "cd0096caf80f8e0816fd21fb03b44d19680408bad818ddc0c2be148c5a1e68a0",
    "/tmp/planora-muni-fspsx-frontier-v14-launcher.sh": "1ffc6d61359724d473b302ca389bab4f4bec35f4489451751df897730af23ec0",
    "/tmp/planora-muni-fspsx-frontier-v14-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v14-runner.py": "789f2b2d7a937a52888445f7694a1868dffb3237b138920ecb45f694be40d1fb",
    "/tmp/planora-muni-fspsx-frontier-v14-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v14-supervisor.py": "8bc764e2619216759ceb626e4b7012df6c0d7198747729de14519886737e21e7",
    "/tmp/planora-muni-fspsx-frontier-v14-tests.py": "6d27ab4e1ace702c179bac2d50d03bfc723a0a828a9e0b6677d22c8350a8f050",
    "/tmp/planora_muni_v14_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v14-certificate.json": "be8a43faa45e24d11f62ad11e0491ef305be83f47c46d60000df7033a53982a2",
}
V15_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v15-bootstrap.py": "241831946a30916e2900cc6b894f7a3e197bb881769b377baeca3b648d84c35f",
    "/tmp/planora-muni-fspsx-frontier-v15-freeze-manifest.json": "60a88df99a46562b951ea66e45c330a00550700155304040da2c62ac37ce009e",
    "/tmp/planora-muni-fspsx-frontier-v15-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v15-inline-trust-root.txt": "74584fe8e044c16aa357f7390ab5ca8b8b5d67c41f74d5bd384e26dc613d4e74",
    "/tmp/planora-muni-fspsx-frontier-v15-launcher.sh": "a447e6d2e99cc14fa097710ba08cbcae4585b5aeadca2d3349cdadd8218f7205",
    "/tmp/planora-muni-fspsx-frontier-v15-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v15-runner.py": "a4b8abbfea794d7192268d62722d3a29e2933900d57f8051b4301ae6be42162c",
    "/tmp/planora-muni-fspsx-frontier-v15-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v15-supervisor.py": "4007a788a4631d1a485121c25bc254a6fedff5755ff88fedc3c998f814f7ef2f",
    "/tmp/planora-muni-fspsx-frontier-v15-tests.py": "91c510dbd8cfb217c47004beaea1b5fa2301196d749a8588506532456789f1b9",
    "/tmp/planora_muni_v15_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v15-certificate.json": "42625671a2f4db85ba9d26e8898c59bc611fbc2dcd459b0019890be71c80f918",
}
V16_ROOT = CHAIN_ROOT.parent / "muni_v16"
V16_PRESERVED_HASHES = {
    V16_ROOT / "planora_muni_v16_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-bootstrap.py": "5f7f0920092c6ea8212300964086340d6c61c3c08d0c4bbfcb1a82956be1eaa2",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-certificate.json": "4fafe8e0cd5ee2c36ea226fe97daa5d950b5b7ee567e3a6f30fa4820644449be",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-freeze-manifest.json": "43eebfa7a4eebd561830b2b20b0ce684c250dd03c5d901b20993e35feb968306",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-inline-trust-root.txt": "6f4e5a357f8e4747166521764302f61a93c5f1d154529cd8cc3066b35f984203",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-launcher.sh": "471c3d7895eecff5036e48603993787b443a9f68403316ef194667f5d416ecce",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-runner.py": "7ae1cba5487fbc3cba22487f7ed16d7b99c2eaa3c7cdf5487d91b00b3258cef7",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-supervisor.py": "576d108bbc63d03353cb562d68b06d1ca5d2fac3baaa54ab55fc3e46ac638891",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-tests.py": "b9f4c2b613b693cf51f56af1bfc5c5e4bfac507ddbe13d35ab8c2fbcd685af23",
    V16_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}
V17_ROOT = CHAIN_ROOT.parent / "muni_v17"
V17_PRESERVED_HASHES = {
    V17_ROOT / "planora_muni_v17_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-bootstrap.py": "370acafcb53b5fdabfe602baec98f2cedf5fca4f581671dac219ce7d1f3ef67a",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-certificate.json": "1e3e415b361ac91307b2f5193a801f90ddf0941bfbc21a3dcfaa730291adda03",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-freeze-manifest.json": "ceb97e6d74ac7e68dcd2f22f4749870d63b384b99a13d1347b818d7d5bffe683",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-inline-trust-root.txt": "a3ea0d882a935ac119f44366bda493a4a36caada855c1df4e861c508dd8abd0b",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-launcher.sh": "54a4fa69d3d382bf0c04fde96f8f209db0e2c2770c799d3f8ef2e9193a2873da",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-runner.py": "5e10b3ad9e33d3f70212b3d44f2b691e5828997d7571588146edde4775830eb9",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-supervisor.py": "681e5fa4e16ce2210952c54c2f9a7be930fcb0808d4be7c33884473e0aa8fa9b",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-tests.py": "dce9044b5562518390b846e5fbce99522d92f1603d4da02d1a093303021a2bd2",
    V17_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(RUNNER, "planora_muni_v18_runner_tests")
supervisor = load(SUPERVISOR, "planora_muni_v18_supervisor_tests")
bootstrap = load(BOOTSTRAP, "planora_muni_v18_bootstrap_tests")


def memfd(name: str, value: bytes) -> int:
    descriptor = os.memfd_create(name, getattr(os, "MFD_ALLOW_SEALING", 2))
    os.write(descriptor, value)
    os.fchmod(descriptor, 0o400)
    import fcntl

    fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, runner.ALL_SEALS)
    return descriptor


def empty_bundle() -> runner.RuntimeBundleAdmission:
    return runner.RuntimeBundleAdmission(3, 4, "0" * 64, {}, {}, {})


def python_capture_evidence() -> dict[str, dict[str, int]]:
    row = os.stat("/proc/self/exe")
    return {
        "python_binary": {
            "device": int(row.st_dev),
            "inode": int(row.st_ino),
            "size": int(row.st_size),
            "file_type": stat.S_IFMT(row.st_mode),
            "mode": stat.S_IMODE(row.st_mode),
            "uid": int(row.st_uid),
            "nlink": int(row.st_nlink),
        }
    }


def maps_row(row: os.stat_result, path: str) -> str:
    return (
        "00400000-00401000 r-xp 00000000 "
        f"{os.major(row.st_dev):02x}:{os.minor(row.st_dev):02x} "
        f"{row.st_ino} {path}"
    )


def run_inline_trust_race(
    source: Path, expected: str, *, phase: str
) -> tuple[subprocess.Popen[bytes], int, int]:
    ready_read, ready_write = os.pipe()
    continue_read, continue_write = os.pipe()
    payload = INLINE_TRUST.read_text()
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PLANORA_V10_TRUST_TEST_PHASE": phase,
        "PLANORA_V10_TRUST_TEST_READY_FD": str(ready_write),
        "PLANORA_V10_TRUST_TEST_CONTINUE_FD": str(continue_read),
    }
    process = subprocess.Popen(
        [
            str(PYTHON), "-I", "-S", "-B", "-c", payload,
            "--inline-trust-v1", str(source), expected,
            sha256(payload.encode()).hexdigest(),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(ready_write, continue_read),
        env=environment,
    )
    os.close(ready_write)
    os.close(continue_read)
    return process, ready_read, continue_write


def run_validator_bootstrap(source: bytes) -> subprocess.CompletedProcess[bytes]:
    stdlib_fd = memfd("stdlib-manifest", STDLIB_MANIFEST.read_bytes())
    runtime_manifest = json.dumps(
        {"entries": []}, sort_keys=True, separators=(",", ":")
    ).encode()
    runtime_manifest_fd = memfd("runtime-manifest", runtime_manifest)
    validator_fd = memfd("validator", source)
    with tempfile.TemporaryDirectory(dir="/tmp") as raw:
        os.chmod(raw, 0o500)
        runtime_root_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return subprocess.run(
                [
                    str(PYTHON), "-I", "-S", "-B", "-c",
                    runner.VALIDATOR_BOOTSTRAP,
                    str(stdlib_fd), runner.EXPECTED_HASHES["stdlib_manifest"],
                    str(runtime_root_fd), str(runtime_manifest_fd),
                    sha256(runtime_manifest).hexdigest(), "{}",
                    str(validator_fd), sha256(source).hexdigest(),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(
                    stdlib_fd, runtime_manifest_fd, validator_fd,
                    runtime_root_fd,
                ),
                env={
                    "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "TZ": "UTC",
                },
                timeout=10,
                check=False,
            )
        finally:
            os.close(runtime_root_fd)
            os.close(stdlib_fd)
            os.close(runtime_manifest_fd)
            os.close(validator_fd)


class StaticContractTests(unittest.TestCase):
    def test_v17_frozen_artifacts_remain_byte_exact(self) -> None:
        for path, expected in V17_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)

    def test_v16_frozen_artifacts_remain_byte_exact(self) -> None:
        for path, expected in V16_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)

    def test_v15_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V15_PRESERVED_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v14_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V14_PRESERVED_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v13_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V13_PRESERVED_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v12_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V12_PRESERVED_HASHES.items():
            self.assertEqual(
                sha256(Path(raw_path).read_bytes()).hexdigest(), expected
            )

    def test_final_shared_open_hint_hashes_are_pinned(self) -> None:
        self.assertEqual(
            runner.EXPECTED_HASHES["frontier"],
            "ade6b42c3baa08a53454db3842b0c4f3cd2e2738c6eb0c54108f419a148d7793",
        )
        source = SUPERVISOR.read_text()
        self.assertIn("ef125a8c9ea64500074700fe0f6b445f5f686832f0f32bf39bc6f35430615ed0", source)

    def test_current_quality_closure_and_certificate_paths_are_unambiguous(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-freeze-manifest.json").read_bytes()
        )
        rows = {row["label"]: row for row in manifest["files"]}
        self.assertEqual(
            rows["itc2019_violation_lns"]["sha256"],
            "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b",
        )
        self.assertEqual(
            rows["test_violation_lns"]["sha256"],
            "a738894d4393d8d5bf8a240f493fa92e2e12e820cd885b40518e13cc0d91efdb",
        )
        self.assertEqual(
            manifest["code_review_certificate_path"],
            str(CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-certificate.json"),
        )
        fairness = manifest["fairness_provenance"]
        self.assertNotIn("certificate_path", fairness)
        self.assertEqual(
            fairness["derivation_audit_path"],
            "/tmp/planora-muni-fspsx-v35-derivation-audit-v1.json",
        )
        self.assertEqual(
            rows["fairness_certificate"]["path"],
            fairness["derivation_audit_path"],
        )
        self.assertEqual(
            rows["fairness_certificate"]["sha256"],
            fairness["derivation_audit_sha256"],
        )

    def test_runtime_manifest_contract_rejects_repository_fairness_path(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-freeze-manifest.json").read_bytes()
        )
        broken = copy.deepcopy(manifest)
        repository_path = str(
            CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json"
        )
        broken["fairness_provenance"]["derivation_audit_path"] = repository_path
        rows = {row["label"]: row for row in broken["files"]}
        rows["fairness_certificate"]["path"] = repository_path
        with self.assertRaisesRegex(
            RuntimeError, "fairness provenance certificate pin rejected"
        ):
            supervisor.validate_manifest_contract(broken)

    def test_runtime_manifest_contract_accepts_exact_staged_fairness_pin(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-freeze-manifest.json").read_bytes()
        )
        audit_bytes = (
            CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json"
        ).read_bytes()
        requested: list[Path] = []

        def capture(path: Path) -> tuple[bytes, tuple[int, ...]]:
            requested.append(path)
            if path != Path("/tmp/planora-muni-fspsx-v35-derivation-audit-v1.json"):
                raise AssertionError(f"unexpected manifest-contract read: {path}")
            return audit_bytes, ()

        with mock.patch.object(supervisor, "capture_regular", side_effect=capture):
            supervisor.validate_manifest_contract(manifest)
        self.assertEqual(
            requested,
            [Path("/tmp/planora-muni-fspsx-v35-derivation-audit-v1.json")],
        )
        self.assertEqual(
            sha256(audit_bytes).hexdigest(),
            manifest["fairness_provenance"]["derivation_audit_sha256"],
        )

    def test_complete_runtime_record_closure_is_declared(self) -> None:
        expected = {
            "ortools", "numpy", "pandas", "dateutil", "six", "absl",
            "immutabledict", "google", "typing_extensions",
        }
        self.assertEqual(set(runner.RUNTIME_RECORD_LABELS), expected)
        self.assertEqual(set(supervisor.RUNTIME_RECORDS), set(runner.RUNTIME_RECORD_LABELS.values()))

    def test_fresh_planora_source_closure_is_complete_and_progress_excluded(self) -> None:
        expected_modules = {
            f"benchmarks.{label}" for label in supervisor.PLANORA_FRESH_MODULES
        }
        self.assertTrue(expected_modules <= set(runner.SEALED_SOURCE_MODULE_LABELS))
        self.assertNotIn("progress", runner.EXPECTED_CAPTURE_LABELS)
        self.assertIn("fairness_certificate", runner.EXPECTED_CAPTURE_LABELS)
        self.assertNotIn('"progress": (PROGRESS', SUPERVISOR.read_text())
        self.assertNotIn('SEALED_SOURCE_EVIDENCE["progress"]', RUNNER.read_text())
        self.assertIn("solve_itc2019_native", RUNNER.read_text())

    def test_runner_and_supervisor_import_without_repo_or_third_party_import(self) -> None:
        script = (
            "import importlib.util,sys;"
            f"paths={[str(RUNNER), str(SUPERVISOR)]!r};"
            "exec('for i,p in enumerate(paths):\\n s=importlib.util.spec_from_file_location(\"isolated_\"+str(i),p)\\n m=importlib.util.module_from_spec(s)\\n sys.modules[s.name]=m\\n s.loader.exec_module(m)');"
            "assert 'ortools' not in sys.modules and 'benchmarks' not in sys.modules "
            "and 'pandas' not in sys.modules"
        )
        completed = subprocess.run(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_direct_entries_are_inert_and_open_no_official_sources(self) -> None:
        for path in (RUNNER, SUPERVISOR):
            completed = subprocess.run(
                [str(PYTHON), "-I", "-S", "-B", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "NOT_LAUNCHED")

    def test_launcher_gate_is_inert_without_irreversible_flag(self) -> None:
        completed = subprocess.run(
            [str(LAUNCHER)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "NOT_LAUNCHED")

    def test_direct_bootstrap_pathname_invocation_fails_closed(self) -> None:
        completed = subprocess.run(
            [str(PYTHON), "-I", "-S", "-B", str(BOOTSTRAP)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(
            "direct bootstrap pathname execution rejected" in completed.stderr
            or "inline trust evidence absent" in completed.stderr,
            completed.stderr,
        )


class CaptureAndBootstrapTests(unittest.TestCase):
    def test_live_file_drift_and_restore_after_capture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            path = Path(raw) / "source.py"
            original = b"reviewed\n"
            path.write_bytes(original)
            descriptor, evidence = supervisor._stream_capture(
                path, sha256(original).hexdigest(), "synthetic"
            )
            try:
                # The WSL-backed filesystem can expose one-second ctime granularity.
                time.sleep(1.05)
                path.write_bytes(b"attacker\n")
                path.write_bytes(original)
                self.assertEqual(
                    supervisor.verify_sealed_capture(descriptor, evidence)["sha256"],
                    sha256(original).hexdigest(),
                )
                with self.assertRaisesRegex(RuntimeError, "mutation event|mutation-clock"):
                    supervisor.verify_source_contract(evidence)
            finally:
                os.close(descriptor)
                os.close(int(evidence["source_watch_fd"]))

    def test_capture_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            root = Path(raw)
            target = root / "target"
            target.write_bytes(b"x")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                supervisor._stream_capture(link, sha256(b"x").hexdigest(), "link")

    def test_mutable_or_symlink_launcher_bootstrap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            link = Path(raw) / "launcher.sh"
            link.symlink_to(LAUNCHER)
            with self.assertRaises(OSError):
                bootstrap.capture_launcher(
                    link, sha256(LAUNCHER.read_bytes()).hexdigest()
                )
            completed = subprocess.run(
                [
                    "/bin/bash", str(LAUNCHER), "--dry-run",
                    "--expected-launcher-sha256", sha256(LAUNCHER.read_bytes()).hexdigest(),
                    "--expected-supervisor-sha256", "0" * 64,
                    "--expected-manifest-sha256", "0" * 64,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("bootstrap-launcher-evidence", completed.stderr)

    def test_inline_trust_executes_sealed_bootstrap_after_live_restore(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            root = Path(raw)
            marker = root / "marker"
            source = root / "bootstrap.py"
            original = (
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('original')\n"
                + "#" * 4096
                + "\n"
            ).encode()
            attacker = (
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('attacker')\n"
                + "#" * 4096
                + "\n"
            ).encode()
            source.write_bytes(original)
            process, ready, proceed = run_inline_trust_race(
                source, sha256(original).hexdigest(), phase="after_seal"
            )
            try:
                self.assertEqual(os.read(ready, 1), b"1")
                source.write_bytes(attacker)
                source.write_bytes(original)
                os.write(proceed, b"1")
                stdout, stderr = process.communicate(timeout=10)
            finally:
                os.close(ready)
                os.close(proceed)
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertEqual(stdout, b"")
            self.assertEqual(marker.read_text(), "original")

    def test_inline_trust_rejects_mutate_restore_during_capture(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            root = Path(raw)
            marker = root / "marker"
            source = root / "bootstrap.py"
            original = (
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('original')\n"
                + "#" * 4096
                + "\n"
            ).encode()
            attacker = b"# attacker\n" + b"x" * 4096
            source.write_bytes(original)
            process, ready, proceed = run_inline_trust_race(
                source, sha256(original).hexdigest(), phase="during_capture"
            )
            try:
                self.assertEqual(os.read(ready, 1), b"1")
                source.write_bytes(attacker)
                source.write_bytes(original)
                os.write(proceed, b"1")
                _stdout, stderr = process.communicate(timeout=10)
            finally:
                os.close(ready)
                os.close(proceed)
            self.assertNotEqual(process.returncode, 0)
            self.assertTrue(
                b"mutation" in stderr
                or b"identity drift" in stderr
                or b"descriptor drift" in stderr,
                stderr.decode(),
            )
            self.assertFalse(marker.exists())

    def test_interpreter_identity_or_hash_mismatch_fails_closed(self) -> None:
        raw = Path("/proc/self/exe").read_bytes()
        evidence = python_capture_evidence()
        evidence["python_binary"]["inode"] += 1
        with self.assertRaisesRegex(RuntimeError, "executing Python"):
            runner.verify_executing_python({"python_binary": raw}, evidence)

    def test_child_environment_is_exact_allowlist(self) -> None:
        env = supervisor.sanitized_child_environment(
            run_directory=Path("/tmp/synthetic-run"),
            run_directory_fd=9,
            captures={"runner": {"fd": 7}},
            runtime_binding={"root_fd": 8},
        )
        self.assertEqual(
            set(env),
            {
                "PATH", "LANG", "LC_ALL", "TZ", "TMPDIR",
                supervisor.CAPTURE_MANIFEST_ENV,
                supervisor.RUNTIME_BUNDLE_ENV,
            },
        )
        for forbidden in (
            "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "OMP_NUM_THREADS", "MALLOC_ARENA_MAX",
        ):
            self.assertNotIn(forbidden, env)
        source = LAUNCHER.read_text()
        self.assertIn("exec /usr/bin/env -i", source)
        self.assertIn("/usr/bin/python3.12 -I -S -B", source)
        self.assertEqual(env["TMPDIR"], "/proc/self/fd/9")


class RuntimeClosureTests(unittest.TestCase):
    def test_sealed_loader_captures_compile_warnings_without_stderr(self) -> None:
        source = b"first = ~False\nsecond = ~True\n"
        descriptor = memfd("compile-warning-source", source)
        entry = {
            "fd": descriptor,
            "size": len(source),
            "sha256": sha256(source).hexdigest(),
        }
        bundle = runner.RuntimeBundleAdmission(
            3, 4, "0" * 64, {"synthetic.py": entry}, {}, {},
            compile_warnings=[],
        )
        try:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                runner._SealedSourceLoader(
                    "synthetic", "synthetic.py", entry, bundle, False
                ).get_code("synthetic")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(len(bundle.compile_warnings or []), 2)
            self.assertTrue(all(
                row["category"] == "DeprecationWarning"
                and row["source_relative_path"] == "synthetic.py"
                and row["source_sha256"] == entry["sha256"]
                for row in bundle.compile_warnings or []
            ))
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
                3, 4, "0" * 64,
                {runner.CP_MODEL_SOURCE_PATH: {
                    "sha256": runner.CP_MODEL_SOURCE_SHA256,
                }},
                {}, {}, compile_warnings=rows,
            )

        admitted = runner.admit_sealed_runtime_compile_warnings(
            bundle([dict(expected), dict(expected)])
        )
        self.assertEqual(admitted["count"], 2)
        self.assertEqual(admitted["child_stderr_bytes"], 0)
        mutations = (
            [dict(expected)],
            [dict(expected), dict(expected), dict(expected)],
            [{**expected, "category": "RuntimeWarning"}, dict(expected)],
            [{**expected, "message": "different"}, dict(expected)],
            [{**expected, "source_relative_path": "other.py"}, dict(expected)],
            [{**expected, "source_sha256": "0" * 64}, dict(expected)],
        )
        for rows in mutations:
            with self.subTest(rows=rows), self.assertRaisesRegex(
                RuntimeError, "compile-warning contract"
            ):
                runner.admit_sealed_runtime_compile_warnings(bundle(rows))

        wrong_source = bundle([dict(expected), dict(expected)])
        wrong_source.entries_by_path[runner.CP_MODEL_SOURCE_PATH]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "source pin"):
            runner.admit_sealed_runtime_compile_warnings(wrong_source)

    def test_real_sealed_runtime_imports_ortools_without_live_site_packages(self) -> None:
        mem_available_kib = next(
            int(line.split()[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
        if mem_available_kib < 1_900_000:
            self.skipTest(
                "heavy sealed-runtime import probe requires MemAvailable >= 1,900,000 KiB"
            )
        completed = subprocess.run(
            [
                str(PYTHON), "-I", "-S", "-B", "-X",
                "pycache_prefix=/tmp/muni-v18-probe-pyc",
                str(Path(__file__)), "--runtime-import-probe",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "SEALED_RUNTIME_IMPORT_OK")
        self.assertGreater(payload["loaded_file_count"], 0)
        self.assertNotIn("site-packages", payload["module_file"])
        self.assertEqual(payload["compile_warnings"]["count"], 2)
        self.assertEqual(payload["captured_stderr"], "")

    def test_real_record_bundle_builds_and_replays_without_official_sources(self) -> None:
        captures: dict[str, dict[str, object]] = {}
        capture_fds: list[int] = []
        runtime_fds: list[int] = []
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="muni-v18-runtime-test-") as raw:
            root = Path(raw)
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for label, path in supervisor.RUNTIME_RECORDS.items():
                    descriptor, evidence = supervisor._stream_capture(
                        path, runner.EXPECTED_HASHES[label], label
                    )
                    captures[label] = evidence
                    capture_fds.append(descriptor)
                    capture_fds.append(int(evidence["source_watch_fd"]))
                with mock.patch.object(
                    supervisor, "LAUNCH_MEMAVAILABLE_FLOOR_KIB", 0
                ):
                    (
                        admitted_root,
                        manifest_fd,
                        files,
                        binding,
                        summary,
                    ) = supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )
                runtime_fds.extend((admitted_root, manifest_fd, *files))
                replay = supervisor.verify_runtime_bundle_end(binding)
                self.assertEqual(replay["file_count"], summary["file_count"])
                self.assertGreater(replay["file_count"], 1_000)
                self.assertTrue(replay["all_memfds_sealed"])
                self.assertTrue(replay["all_link_targets_replayed"])
            finally:
                os.close(root_fd)
                for descriptor in runtime_fds + capture_fds:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

    def test_omitted_runtime_record_module_is_rejected(self) -> None:
        payloads = {label: b"" for label in runner.RUNTIME_RECORD_LABELS.values()}
        payloads.pop(runner.RUNTIME_RECORD_LABELS["six"])
        with self.assertRaises(KeyError):
            runner._expected_runtime_bundle_entries(payloads)

    def test_record_path_escape_is_excluded_and_never_admitted(self) -> None:
        payloads = {label: b"" for label in runner.RUNTIME_RECORD_LABELS.values()}
        payloads[runner.RUNTIME_RECORD_LABELS["six"]] = (
            b"../evil.py,sha256=eA==,1\n"
        )
        entries, excluded = runner._expected_runtime_bundle_entries(payloads)
        self.assertEqual(entries, {})
        self.assertEqual(len(excluded), 1)

    def test_unexpected_site_packages_module_is_rejected(self) -> None:
        payloads = {label: b"" for label in runner.RUNTIME_RECORD_LABELS.values()}
        payloads["stdlib_manifest"] = STDLIB_MANIFEST.read_bytes()
        injected = types.ModuleType("injected_runtime")
        injected.__file__ = "/tmp/evil/site-packages/injected.py"
        sys.modules[injected.__name__] = injected
        old_prefix = sys.pycache_prefix
        old_dont = sys.dont_write_bytecode
        try:
            sys.pycache_prefix = "/tmp/disabled-pyc"
            sys.dont_write_bytecode = True
            with self.assertRaisesRegex(RuntimeError, "unexpected site-packages"):
                runner.verify_loaded_runtime(payloads, empty_bundle())
        finally:
            sys.pycache_prefix = old_prefix
            sys.dont_write_bytecode = old_dont
            sys.modules.pop(injected.__name__, None)

    def test_real_argparse_is_exactly_freeze_pinned(self) -> None:
        payloads = {"stdlib_manifest": STDLIB_MANIFEST.read_bytes()}
        allowed = runner._stdlib_manifest_rows(payloads)
        row = runner._stdlib_module_evidence(
            "/usr/lib/python3.12/argparse.py", allowed
        )
        self.assertEqual(row["sha256"], allowed[row["path"]])
        self.assertEqual(
            row["boundary"], "freeze_pinned_read_only_system_file"
        )

    def test_mutated_allowed_root_fixture_is_rejected_by_exact_hash(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            fixture = Path(raw) / "fixture.py"
            fixture.write_bytes(b"trusted = True\n")
            expected = sha256(fixture.read_bytes()).hexdigest()
            fixture.write_bytes(b"trusted = False\n")
            with (
                mock.patch.object(runner, "STDLIB_ROOTS", (Path(raw),)),
                mock.patch.object(
                    runner, "_verify_stdlib_ancestor_chain", return_value=None
                ),
                self.assertRaisesRegex(RuntimeError, "hash absent"),
            ):
                runner._stdlib_module_evidence(
                    str(fixture.resolve()), {str(fixture.resolve()): expected}
                )

    def test_unpinned_root_shaped_stdlib_module_is_rejected(self) -> None:
        allowed = {
            "/usr/lib/python3.12/argparse.py": sha256(
                Path("/usr/lib/python3.12/argparse.py").read_bytes()
            ).hexdigest()
        }
        with self.assertRaisesRegex(RuntimeError, "absent from frozen manifest"):
            runner._stdlib_module_evidence(
                "/usr/lib/python3.12/antigravity.py", allowed
            )

    def test_validator_admits_real_argparse_and_rejects_tmp_injection(self) -> None:
        accepted = run_validator_bootstrap(b"import argparse\n")
        self.assertEqual(
            accepted.returncode, 0,
            accepted.stderr.decode("utf-8", "replace"),
        )
        injected = run_validator_bootstrap(
            b"import argparse,sys,types\n"
            b"evil=types.ModuleType('evil')\n"
            b"evil.__file__='/tmp/evil.py'\n"
            b"sys.modules['evil']=evil\n"
        )
        self.assertNotEqual(injected.returncode, 0)
        self.assertIn(b"unexpected package runtime", injected.stderr)

    def test_unbound_native_memfd_mapping_is_rejected(self) -> None:
        python_row = os.stat("/proc/self/exe")
        synthetic = "\n".join(
            (
                maps_row(python_row, "/memfd:python (deleted)"),
                "00500000-00501000 r-xp 00000000 00:01 999999 /memfd:evil (deleted)",
            )
        )
        with mock.patch.object(Path, "read_text", return_value=synthetic):
            with self.assertRaisesRegex(RuntimeError, "mapped memfd"):
                runner.mapped_runtime_snapshot(
                    empty_bundle(), python_capture_evidence(), phase="synthetic"
                )

    def test_admitted_native_memfd_map_closure_is_accepted(self) -> None:
        descriptor = memfd("native-map", b"native")
        try:
            native = os.fstat(descriptor)
            python_row = os.stat("/proc/self/exe")
            entry = {
                "relative_path": "pkg/libnative.so",
                "fd": descriptor,
                "device": int(native.st_dev),
                "inode": int(native.st_ino),
                "sha256": sha256(b"native").hexdigest(),
                "size": 6,
            }
            bundle = runner.RuntimeBundleAdmission(
                3, 4, "0" * 64,
                {entry["relative_path"]: entry},
                {(int(native.st_dev), int(native.st_ino)): entry},
                {},
            )
            synthetic = "\n".join(
                (
                    maps_row(python_row, "/memfd:python (deleted)"),
                    maps_row(native, "/memfd:native-map (deleted)"),
                )
            )
            with mock.patch.object(Path, "read_text", return_value=synthetic):
                result = runner.mapped_runtime_snapshot(
                    bundle, python_capture_evidence(), phase="synthetic"
                )
            self.assertEqual(result["sealed_package_mappings"], ["pkg/libnative.so"])
            self.assertTrue(result["sealed_python_mapped"])
        finally:
            os.close(descriptor)

    def test_non_system_native_map_is_rejected(self) -> None:
        python_row = os.stat("/proc/self/exe")
        synthetic = "\n".join(
            (
                maps_row(python_row, "/memfd:python (deleted)"),
                "00500000-00501000 r-xp 00000000 08:01 12345 /tmp/evil.so",
            )
        )
        with mock.patch.object(Path, "read_text", return_value=synthetic):
            with self.assertRaisesRegex(RuntimeError, "outside admitted system roots"):
                runner.mapped_runtime_snapshot(
                    empty_bundle(), python_capture_evidence(), phase="synthetic"
                )


class SealedImportProbeTests(unittest.TestCase):
    def test_rejection_diagnostics_hash_logs_and_bound_binary_stdio_tails(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            value = b"prefix:" + (b"x" * 5000) + b"\xff\x00tail"
            try:
                for name in ("probe.stdout.log", "probe.stderr.log"):
                    stream_fd = os.open(
                        name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o400,
                        dir_fd=directory_fd,
                    )
                    created = os.fstat(stream_fd)
                    os.write(stream_fd, value)
                    os.close(stream_fd)
                    observed = supervisor.capture_probe_log_diagnostic(
                        directory_fd,
                        name,
                        created,
                        include_tail=True,
                    )
                    self.assertTrue(observed["present"])
                    self.assertEqual(observed["size_bytes"], len(value))
                    self.assertEqual(observed["sha256"], sha256(value).hexdigest())
                    self.assertEqual(
                        observed["tail_bytes"], supervisor.PROBE_STDIO_TAIL_BYTES
                    )
                    self.assertTrue(observed["tail_truncated"])
                    self.assertEqual(
                        base64.b64decode(observed["tail_base64"]),
                        value[-supervisor.PROBE_STDIO_TAIL_BYTES :],
                    )
            finally:
                os.close(directory_fd)

    def test_report_presence_exposes_exact_size_hash_and_bound_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "sealed-import-probe-child.json",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            created = os.fstat(report_fd)
            value = b'{"status":"synthetic"}'
            os.write(report_fd, value)
            try:
                observed = supervisor.probe_report_presence(
                    directory_fd, report_fd, created
                )
            finally:
                os.close(report_fd)
                os.close(directory_fd)
        self.assertTrue(observed["parent_created"])
        self.assertTrue(observed["retained_fd_present"])
        self.assertTrue(observed["named_entry_present"])
        self.assertTrue(observed["named_entry_matches_retained_fd"])
        self.assertEqual(observed["size_bytes"], len(value))
        self.assertEqual(observed["sha256"], sha256(value).hexdigest())

    def test_child_crash_classification_preserves_empty_report_and_stdio_facts(self) -> None:
        report = supervisor.probe_report_presence(None, None, None)
        report.update({"parent_created": True, "retained_fd_present": True, "size_bytes": 0})
        stdout = supervisor._absent_probe_log_diagnostic(include_tail=True)
        stderr = supervisor._absent_probe_log_diagnostic(include_tail=True)
        stderr.update(
            {
                "present": True,
                "size_bytes": 9,
                "sha256": sha256(b"traceback").hexdigest(),
                "tail_base64": base64.b64encode(b"traceback").decode("ascii"),
                "tail_bytes": 9,
            }
        )
        diagnostic = supervisor.build_probe_rejection_diagnostics(
            child_started=True,
            child_exit=1,
            stop_reason="probe_exception",
            cleanup={"errors": (), "original_pgid_asserted_empty": True},
            report=report,
            stdout=stdout,
            stderr=stderr,
            errors=("RuntimeError: probe report size rejected",),
        )
        self.assertEqual(diagnostic["primary_failure_classification"], "child_exit_nonzero")
        self.assertEqual(
            diagnostic["failure_classifications"],
            ["child_exit_nonzero", "report_empty", "child_stderr_nonempty", "probe_exception"],
        )
        self.assertNotIn("traceback", json.dumps(diagnostic))

    def test_success_omits_rejection_diagnostics_and_rejection_requires_them(self) -> None:
        accepted = supervisor.probe_result_payload(
            accepted=True,
            stop_reason="normal_exit",
            child_exit=0,
            final_elapsed_seconds=1.0,
            peak_whole_memory_kib=1,
            errors=(),
            evidence={"sha256": "a" * 64},
            rejection_diagnostics=None,
        )
        self.assertNotIn("rejection_diagnostics", accepted)
        with self.assertRaisesRegex(RuntimeError, "missing diagnostics"):
            supervisor.probe_result_payload(
                accepted=False,
                stop_reason="probe_exception",
                child_exit=1,
                final_elapsed_seconds=1.0,
                peak_whole_memory_kib=1,
                errors=("failure",),
                evidence=None,
                rejection_diagnostics=None,
            )

    def test_nonempty_stdio_remains_rejected(self) -> None:
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                self.assertFalse(
                    supervisor.sealed_import_probe_accepted(
                        errors=(f"probe_child_{stream}_not_empty",),
                        stop_reason="normal_exit",
                        child_exit=0,
                        cleanup={
                            "errors": (),
                            "original_pgid_asserted_empty": True,
                        },
                        child_report={"status": "PASS"},
                        final_elapsed_seconds=1.0,
                        peak_whole_memory_kib=1,
                    )
                )

    def test_real_chain_reaches_probe_admission_without_opening_inputs(self) -> None:
        available = supervisor.host_sample()["mem_available_kib"]
        if available >= supervisor.LAUNCH_MEMAVAILABLE_FLOOR_KIB:
            self.skipTest("heavy probe admission is possible; lightweight suite must not start it")
        manifest_path = CHAIN_ROOT / "planora-muni-fspsx-frontier-v18-freeze-manifest.json"
        if not manifest_path.exists():
            self.skipTest("freeze manifest is built after final source hashes")
        payload = INLINE_TRUST.read_text()
        command = [
            str(PYTHON), "-I", "-S", "-B", "-c", payload,
            "--inline-trust-v1", str(BOOTSTRAP), sha256(BOOTSTRAP.read_bytes()).hexdigest(),
            sha256(payload.encode()).hexdigest(),
            "--sealed-import-probe",
            "--expected-launcher-sha256", sha256(LAUNCHER.read_bytes()).hexdigest(),
            "--expected-supervisor-sha256", sha256(SUPERVISOR.read_bytes()).hexdigest(),
            "--expected-manifest-sha256", sha256(manifest_path.read_bytes()).hexdigest(),
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"},
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "NO_GO_RESOURCE_GATE")
        self.assertEqual(payload["chain_traversed"], ["bootstrap", "launcher", "supervisor"])
        self.assertFalse(payload["official_input_opened"])
        self.assertFalse(payload["solve_called"])

    def test_probe_path_has_no_input_capture_or_solver_reference(self) -> None:
        self.assertNotIn("instance", runner.PROBE_CAPTURE_LABELS)
        self.assertEqual(
            runner.PROBE_CAPTURE_LABELS,
            runner.EXPECTED_CAPTURE_LABELS - {"instance"},
        )
        supervisor_source = inspect.getsource(supervisor.run_sealed_import_probe)
        runner_source = inspect.getsource(runner.run_sealed_import_probe)
        for forbidden in ("INSTANCE", "PROGRESS"):
            self.assertNotIn(forbidden, supervisor_source)
        self.assertNotIn("solve_itc2019_native", runner_source)
        self.assertNotIn("parse_itc2019_xml", runner_source)
        for path in (BOOTSTRAP, LAUNCHER, SUPERVISOR, RUNNER):
            self.assertIn("--sealed-import-probe", path.read_text())

    def test_set_union_memory_does_not_double_count_supervisor(self) -> None:
        self.assertEqual(
            supervisor.set_union_memory_kib(100, 700, (11, 12), supervisor_pid=10),
            800,
        )
        self.assertEqual(
            supervisor.set_union_memory_kib(100, 700, (10, 12), supervisor_pid=10),
            700,
        )

    def test_cap_timeout_and_cleanup_errors_fail_closed(self) -> None:
        healthy = supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB
        self.assertEqual(
            supervisor.sealed_import_probe_stop_reason(
                elapsed_seconds=180.0, group_memory_kib=1,
                whole_memory_kib=2, mem_available_kib=healthy,
            ),
            "probe_wall_deadline",
        )
        self.assertEqual(
            supervisor.sealed_import_probe_stop_reason(
                elapsed_seconds=1, group_memory_kib=1,
                whole_memory_kib=700_001, mem_available_kib=healthy,
            ),
            "whole_launch_memory_cap",
        )
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            errors=(), stop_reason="normal_exit", child_exit=0,
            cleanup={"errors": ("pidfd_send:EPERM",)}, child_report={"status": "PASS"},
            final_elapsed_seconds=1.0, peak_whole_memory_kib=1,
        ))
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            errors=(), stop_reason="probe_wall_deadline", child_exit=0,
            cleanup={"errors": ()}, child_report={"status": "PASS"},
            final_elapsed_seconds=1.0, peak_whole_memory_kib=1,
        ))

    def test_just_exited_child_cannot_bypass_cap_deadline_or_floor(self) -> None:
        cases = (
            ({"elapsed_seconds": 180.0, "group_memory_kib": 1, "whole_memory_kib": 2,
              "mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB}, "probe_wall_deadline"),
            ({"elapsed_seconds": 1.0, "group_memory_kib": 1, "whole_memory_kib": 700_001,
              "mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB}, "whole_launch_memory_cap"),
            ({"elapsed_seconds": 1.0, "group_memory_kib": 1, "whole_memory_kib": 2,
              "mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB - 1},
             "host_pressure:memavailable_floor"),
        )
        for values, expected in cases:
            self.assertEqual(
                supervisor.sealed_import_probe_iteration_decision(
                    **values, received_signal=None, process_exited=True
                ),
                expected,
            )

    def test_unreaped_just_exited_child_has_identity_pinned_zero_memory(self) -> None:
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", "import time;time.sleep(.1)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            identity = supervisor.proc_stat_identity(process.pid)
            self.assertIsNotNone(identity)
            generation = supervisor.ProcessGroupGeneration(
                process.pid, process.pid, identity
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                status = (Path("/proc") / str(process.pid) / "status").read_text()
                if "State:\tZ" in status:
                    break
                time.sleep(0.01)
            else:
                self.fail("child did not reach unreaped zombie state")
            supervisor_identity = supervisor.proc_stat_identity(os.getpid())
            self.assertIsNotNone(supervisor_identity)
            sample = supervisor.identity_pinned_process_memory_snapshot(
                generation,
                supervisor_pid=os.getpid(),
                supervisor_identity=supervisor_identity,
            )
            child_row = next(row for row in sample["rows"] if row["pid"] == process.pid)
            self.assertEqual(child_row["memory_kib"], 0)
        finally:
            process.wait(timeout=3)

    def test_reaped_zero_exit_leader_is_represented_once_after_valid_sample(self) -> None:
        leader = (10, 10, 1)
        own = (99, 99, 9)
        generation = supervisor.ProcessGroupGeneration(10, 10, leader)
        generation.sampled_members.add((10, leader))
        process = mock.Mock(pid=10)
        process.poll.return_value = 0
        with mock.patch.object(
            supervisor, "proc_stat_identity",
            side_effect=lambda pid: None if pid == 10 else own,
        ):
            proof = supervisor.successful_reaped_leader_zero_memory_proof(
                process, generation
            )
            with mock.patch.object(
                supervisor, "read_process_memory_status_once",
                return_value={"VmRSS": 7, "VmSwap": 1},
            ):
                sample = supervisor.identity_pinned_process_memory_snapshot(
                    generation,
                    supervisor_pid=99,
                    supervisor_identity=own,
                    reaped_zero_proof=proof,
                )
        leader_rows = [row for row in sample["rows"] if row["pid"] == 10]
        self.assertEqual(len(leader_rows), 1)
        self.assertEqual(leader_rows[0]["memory_kib"], 0)
        self.assertTrue(leader_rows[0]["reaped_gone_zero_memory"])
        self.assertEqual(sample["reaped_gone_zero_memory_pids"], (10,))

    def test_reaped_zero_proof_rejects_nonzero_live_reused_or_never_sampled(self) -> None:
        leader = (10, 10, 1)
        generation = supervisor.ProcessGroupGeneration(10, 10, leader)
        process = mock.Mock(pid=10)
        process.poll.return_value = 0
        with (
            mock.patch.object(supervisor, "proc_stat_identity", return_value=None),
            self.assertRaisesRegex(RuntimeError, "never identity-bound sampled"),
        ):
            supervisor.successful_reaped_leader_zero_memory_proof(
                process, generation
            )
        generation.sampled_members.add((10, leader))
        process.poll.return_value = 3
        with mock.patch.object(supervisor, "proc_stat_identity") as identity:
            self.assertIsNone(
                supervisor.successful_reaped_leader_zero_memory_proof(
                    process, generation
                )
            )
        identity.assert_not_called()
        process.poll.return_value = 0
        with (
            mock.patch.object(
                supervisor, "proc_stat_identity", return_value=(10, 10, 2)
            ),
            self.assertRaisesRegex(RuntimeError, "still live or was reused"),
        ):
            supervisor.successful_reaped_leader_zero_memory_proof(
                process, generation
            )

    def test_untrusted_reaped_zero_proofs_fail_closed(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))
        generation.sampled_members.add((10, (10, 10, 1)))
        proofs = (
            (11, (10, 10, 1), 0),
            (10, (10, 10, 2), 0),
            (10, (10, 10, 1), 1),
        )
        for proof in proofs:
            with self.subTest(proof=proof), self.assertRaisesRegex(
                RuntimeError, "not the admitted zero-exit leader"
            ):
                supervisor.identity_pinned_process_memory_snapshot(
                    generation,
                    supervisor_pid=99,
                    supervisor_identity=(99, 99, 1),
                    reaped_zero_proof=proof,
                )

    def test_live_status_missing_one_memory_field_fails_closed(self) -> None:
        status = "State:\tR (running)\nVmRSS:\t4 kB\n"
        with (
            mock.patch.object(Path, "open", mock.mock_open(read_data=status)),
            self.assertRaisesRegex(
                supervisor.ProcessStatusMemoryUnavailable,
                "memory fields missing",
            ),
        ):
            supervisor.read_process_memory_status_once(10)

    def test_reaped_proof_does_not_admit_pid_reuse(self) -> None:
        leader = (10, 10, 1)
        generation = supervisor.ProcessGroupGeneration(10, 10, leader)
        generation.sampled_members.add((10, leader))
        with (
            mock.patch.object(
                supervisor, "proc_stat_identity",
                side_effect=lambda pid: (10, 10, 2) if pid == 10 else (99, 99, 1),
            ),
            self.assertRaisesRegex(RuntimeError, "replaced before memory snapshot"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation,
                supervisor_pid=99,
                supervisor_identity=(99, 99, 1),
                reaped_zero_proof=(10, leader, 0),
            )

    def test_numeric_pid_replacement_is_not_measured(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))

        def identity(pid: int):
            return (10, 10, 2) if pid == 10 else (99, 99, 1)

        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(supervisor, "read_process_memory_status_once") as status,
            self.assertRaisesRegex(RuntimeError, "replaced before memory snapshot"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation, supervisor_pid=99, supervisor_identity=(99, 99, 1)
            )
        status.assert_not_called()

    def test_unique_snapshot_reads_each_status_once_and_supervisor_once(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))
        generation.members[99] = (10, 10, 9)

        def identity(pid: int):
            return generation.members[pid]

        def status(pid: int):
            return {"VmRSS": pid, "VmSwap": 1}

        reader = mock.Mock(side_effect=status)
        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(supervisor, "read_process_memory_status_once", reader),
        ):
            sample = supervisor.identity_pinned_process_memory_snapshot(
                generation,
                supervisor_pid=99,
                supervisor_identity=(10, 10, 9),
            )
        self.assertEqual(sample["pids"], (10, 99))
        self.assertEqual(reader.call_args_list, [mock.call(10), mock.call(99)])
        self.assertEqual(sample["whole_launch_set_union_memory_kib"], 111)
        self.assertEqual(sample["group_memory_kib"], 111)
        self.assertEqual(sample["supervisor_memory_kib"], 100)

    def test_identity_drift_during_single_status_read_fails_closed(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))
        counts = {10: 0, 99: 0}

        def identity(pid: int):
            counts[pid] += 1
            if pid == 10 and counts[pid] >= 3:
                return (10, 10, 2)
            return (10, 10, 1) if pid == 10 else (99, 99, 1)

        status = mock.Mock(return_value={"VmRSS": 4, "VmSwap": 1})
        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(supervisor, "read_process_memory_status_once", status),
            self.assertRaisesRegex(RuntimeError, "drifted during status read"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation, supervisor_pid=99, supervisor_identity=(99, 99, 1)
            )
        self.assertEqual(status.call_args_list, [mock.call(10)])

    def test_missing_status_after_identity_pin_fails_closed(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))

        def identity(pid: int):
            return (10, 10, 1) if pid == 10 else (99, 99, 1)

        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(
                supervisor, "read_process_memory_status_once",
                side_effect=RuntimeError("process status missing"),
            ),
            self.assertRaisesRegex(RuntimeError, "process status missing"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation, supervisor_pid=99, supervisor_identity=(99, 99, 1)
            )

    def test_memory_sampler_uses_admitted_registry_not_numeric_group_scan(self) -> None:
        source = inspect.getsource(supervisor.identity_pinned_process_memory_snapshot)
        self.assertNotIn("process_group_snapshot", source)
        self.assertNotIn("process_group_pids", source)
        self.assertNotIn("process_group_memory_kib", source)
        self.assertIn("generation.members", source)

    def test_late_replay_runs_every_stage_and_rejects(self) -> None:
        captures = {"one": {"fd": 3}, "two": {"fd": 4}}
        clock_values = iter((100.0, 181.0, 181.0, 181.0, 181.0, 181.0))
        sealed = mock.Mock()
        source = mock.Mock()
        runtime = mock.Mock()
        with (
            mock.patch.object(supervisor, "verify_sealed_capture", sealed),
            mock.patch.object(supervisor, "verify_source_contract", source),
            mock.patch.object(supervisor, "verify_runtime_bundle_end", runtime),
        ):
            errors = supervisor.replay_probe_closure_with_deadline(
                captures, {}, 180.0,
                external_rows=({"fd": 5}, {"fd": 6}),
                clock=lambda: next(clock_values),
            )
        self.assertEqual(sealed.call_count, 4)
        self.assertEqual(source.call_count, 4)
        runtime.assert_called_once_with({})
        self.assertTrue(any("probe_deadline_exceeded" in value for value in errors))

    def test_late_report_publication_is_unlinked_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            os.chmod(directory, 0o700)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            observed = directory.stat()
            identity = {
                "device": observed.st_dev, "inode": observed.st_ino,
                "uid": observed.st_uid, "mode": 0o700,
            }
            clock_values = iter((100.0, 181.0))
            try:
                evidence, error = supervisor.publish_probe_monitor_with_deadline(
                    path=directory / "sealed-import-probe-report.json",
                    value=b'{}\n', run_directory=directory,
                    run_directory_fd=directory_fd, run_identity=identity,
                    absolute_deadline=180.0,
                    clock=lambda: next(clock_values),
                )
                self.assertIsNone(evidence)
                self.assertEqual(error, "probe_deadline_exceeded:after_report_publication")
                self.assertFalse((directory / "sealed-import-probe-report.json").exists())
            finally:
                os.close(directory_fd)

    def test_final_acceptance_requires_elapsed_and_peak_within_limits(self) -> None:
        common = {
            "errors": (), "stop_reason": "normal_exit", "child_exit": 0,
            "cleanup": {"errors": ()}, "child_report": {"status": "PASS"},
        }
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=180.001, peak_whole_memory_kib=1
        ))
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=1.0, peak_whole_memory_kib=700_001
        ))
        self.assertTrue(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=180.0, peak_whole_memory_kib=700_000
        ))

    def test_descriptor_report_transport_and_same_uid_swap_reject(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "sealed-import-probe-child.json",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            created = os.fstat(report_fd)
            payload = {
                "schema": "planora.muni-fspsx.frontier-v18.sealed-import-probe-child.v1",
                "status": "PASS",
            }
            try:
                runner.write_sealed_import_probe_report(
                    report_fd,
                    (created.st_dev, created.st_ino, created.st_uid),
                    payload,
                )
                observed, evidence = supervisor.consume_probe_report(
                    directory_fd, report_fd, created
                )
                self.assertEqual(observed, payload)
                self.assertEqual(
                    evidence["transport"],
                    "parent_created_retained_fd_and_named_identity_replay",
                )
                os.close(report_fd)
                report_fd = os.open(
                    "sealed-import-probe-child.json",
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                created = os.fstat(report_fd)
                runner.write_sealed_import_probe_report(
                    report_fd,
                    (created.st_dev, created.st_ino, created.st_uid),
                    payload,
                )
                os.rename(
                    "sealed-import-probe-child.json", "original.json",
                    src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                )
                attacker = os.open(
                    "sealed-import-probe-child.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o400,
                    dir_fd=directory_fd,
                )
                os.write(attacker, b'{"status":"ATTACKER"}\n')
                os.close(attacker)
                with self.assertRaisesRegex(RuntimeError, "identity drift"):
                    supervisor.consume_probe_report(directory_fd, report_fd, created)
            finally:
                os.close(report_fd)
                os.close(directory_fd)


class ResourceAndCleanupTests(unittest.TestCase):
    def test_empty_group_never_signals_numeric_pgid(self) -> None:
        process = mock.Mock()
        process.pid = 424_242
        process.returncode = 0
        process.wait.return_value = 0
        generation = supervisor.ProcessGroupGeneration(
            process.pid, process.pid, (process.pid, process.pid, 1000)
        )
        with (
            mock.patch.object(supervisor, "proc_stat_identity", return_value=None),
            mock.patch.object(supervisor, "process_group_snapshot", return_value=()),
            mock.patch.object(supervisor.os, "killpg") as raw_killpg,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as pidfd_signal,
        ):
            result = supervisor.stop_process_group(
                process, generation, 99
            )
        raw_killpg.assert_not_called()
        pidfd_signal.assert_not_called()
        self.assertEqual(result["members_before"], ())
        self.assertTrue(result["group_observed_empty_before_any_later_signal"])
        self.assertFalse(result["numeric_pgid_signal_sent"])
        self.assertEqual(result["term_signal"]["signaled_pids"], ())
        self.assertEqual(result["kill_signal"]["signaled_pids"], ())

    def test_member_pid_reuse_between_snapshot_and_pidfd_replay_is_aggregated(self) -> None:
        pgid = 123_456
        admitted = (pgid, pgid, 1000)
        replaced = (pgid, pgid, 2000)
        with (
            mock.patch.object(supervisor.os, "pidfd_open", return_value=77),
            mock.patch.object(supervisor, "proc_stat_identity", return_value=replaced),
            mock.patch.object(supervisor.os, "close") as close_fd,
            mock.patch.object(supervisor.os, "killpg") as raw_killpg,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as pidfd_signal,
        ):
            result = supervisor.signal_process_group_snapshot(
                pgid, ((pgid, admitted),), signal.SIGTERM
            )
        close_fd.assert_called_once_with(77)
        raw_killpg.assert_not_called()
        pidfd_signal.assert_not_called()
        self.assertEqual(result["identity_mismatch_pids"], (pgid,))

    def test_reused_group_after_original_empty_and_reused_leader_exit_gets_zero_signals(self) -> None:
        process = mock.Mock()
        process.pid = 515_151
        process.returncode = 0
        process.wait.return_value = 0
        original = (process.pid, process.pid, 1000)
        generation = supervisor.ProcessGroupGeneration(
            process.pid, process.pid, original
        )
        # The numeric session/PGID was reused, its replacement leader has
        # already exited, and only that replacement generation's descendant
        # remains at the first cleanup enumeration.
        reused_descendant = (515_152, (process.pid, process.pid, 9000))
        with (
            mock.patch.object(supervisor, "proc_stat_identity", return_value=None),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                return_value=(reused_descendant,),
            ),
            mock.patch.object(supervisor.os, "killpg") as raw_killpg,
            mock.patch.object(supervisor.os, "pidfd_open") as pidfd_open,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as pidfd_signal,
        ):
            result = supervisor.stop_process_group(process, generation, 99)
        raw_killpg.assert_not_called()
        pidfd_open.assert_not_called()
        pidfd_signal.assert_not_called()
        self.assertFalse(result["original_pgid_asserted_empty"])
        self.assertTrue(
            any("unregistered survivors" in value for value in result["errors"])
        )

    def test_emfile_for_first_member_does_not_block_later_admitted_member(self) -> None:
        pgid = 616_161
        first = (616_162, (pgid, pgid, 1000))
        second = (616_163, (pgid, pgid, 1001))

        def open_member(pid: int, _flags: int) -> int:
            if pid == first[0]:
                raise OSError(errno.EMFILE, "descriptor table full")
            return 88

        def replay(pid: int):
            return dict((first, second))[pid]

        with (
            mock.patch.object(supervisor.os, "pidfd_open", side_effect=open_member),
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=replay),
            mock.patch.object(supervisor.os, "close") as close_fd,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as send,
        ):
            result = supervisor.signal_process_group_snapshot(
                pgid, (first, second), signal.SIGTERM
            )
        self.assertEqual(
            result["pidfd_open_failures"],
            ({"pid": first[0], "errno": errno.EMFILE},),
        )
        self.assertEqual(result["signaled_pids"], (second[0],))
        send.assert_called_once_with(88, signal.SIGTERM, None, 0)
        close_fd.assert_called_once_with(88)

    def test_persistent_wait_fault_does_not_skip_term_kill_or_throw(self) -> None:
        pgid = 717_171
        leader = (pgid, (pgid, pgid, 1000))
        first = (717_172, (pgid, pgid, 1001))
        later = (717_173, (pgid, pgid, 1002))
        identities = dict((leader, first, later))
        generation = supervisor.ProcessGroupGeneration(
            pgid, pgid, leader[1]
        )
        generation.members[first[0]] = first[1]
        generation.members[later[0]] = later[1]
        process = mock.Mock()
        process.pid = pgid
        process.returncode = None
        process.wait.side_effect = OSError(errno.EIO, "persistent wait fault")

        def send_member(
            descriptor: int, signum: int, _info: object, _flags: int
        ) -> None:
            if descriptor == 82:
                raise OSError(errno.EPERM, "first descendant signal denied")

        with (
            mock.patch.object(supervisor, "TERMINATION_GRACE_SECONDS", 0),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=lambda pid: identities.get(pid),
            ),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                return_value=(leader, first, later),
            ),
            mock.patch.object(
                supervisor.os,
                "pidfd_open",
                side_effect=lambda pid, _flags: {
                    leader[0]: 81,
                    first[0]: 82,
                    later[0]: 83,
                }[pid],
            ),
            mock.patch.object(supervisor.os, "close"),
            mock.patch.object(
                supervisor.signal,
                "pidfd_send_signal",
                side_effect=send_member,
            ) as send,
        ):
            result = supervisor.stop_process_group(process, generation, 99)

        self.assertIn(
            mock.call(83, signal.SIGTERM, None, 0), send.call_args_list
        )
        self.assertIn(
            mock.call(83, signal.SIGKILL, None, 0), send.call_args_list
        )
        self.assertEqual(
            result["term_signal"]["pidfd_send_failures"],
            ({"pid": first[0], "errno": errno.EPERM},),
        )
        self.assertEqual(
            result["kill_signal"]["pidfd_send_failures"],
            ({"pid": first[0], "errno": errno.EPERM},),
        )
        self.assertTrue(
            any(value.startswith("initial_wait:OSError") for value in result["errors"])
        )
        self.assertTrue(
            any(value.startswith("final_wait:OSError") for value in result["errors"])
        )
        self.assertFalse(result["original_pgid_asserted_empty"])

    def test_unreaped_zombie_leader_is_reaped_then_descendants_drained(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);"
            "print('ready',flush=True);time.sleep(0.2)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        pidfd = os.pidfd_open(process.pid, 0) if hasattr(os, "pidfd_open") else None
        try:
            assert process.stdout is not None
            self.assertEqual(process.stdout.readline(), b"ready\n")
            _pgid, _identity, _pidfd, generation = (
                supervisor.admit_spawned_process_group(process, process.pid, pidfd)
            )
            supervisor.refresh_process_group_generation(generation)
            deadline = time.monotonic() + 3
            state = None
            while time.monotonic() < deadline:
                try:
                    raw = (Path("/proc") / str(process.pid) / "stat").read_text()
                except FileNotFoundError:
                    break
                state = raw[raw.rfind(")") + 2 :].split()[0]
                if state == "Z":
                    break
                time.sleep(0.01)
            self.assertEqual(state, "Z")
            self.assertIsNone(process.returncode)
            cleanup = supervisor.stop_process_group(
                process, generation, pidfd
            )
            self.assertTrue(
                cleanup["known_leader_reaped_before_group_interpretation"]
            )
            self.assertEqual(cleanup["final_survivors"], ())
            self.assertEqual(supervisor.process_group_pids(process.pid), ())
        finally:
            if pidfd is not None:
                os.close(pidfd)
            if process.stdout is not None:
                process.stdout.close()
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

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

    def test_resource_semantics_and_mandatory_launch_floor(self) -> None:
        healthy = {"mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB}
        self.assertIsNone(
            supervisor.resource_decision(
                elapsed_seconds=1,
                group_memory_kib=600_000,
                supervisor_memory_kib=100_000,
                sample={**healthy, "pswpin_pages": 10**12, "pswpout_pages": 10**12},
            )
        )
        self.assertEqual(supervisor.WALL_SECONDS, 630.0)
        self.assertEqual(supervisor.RUNNER_SECONDS, 600.0)
        self.assertEqual(supervisor.PROCESS_GROUP_MEMORY_CAP_KIB, 700_000)
        self.assertEqual(supervisor.WHOLE_LAUNCH_MEMORY_CAP_KIB, 700_000)
        self.assertEqual(
            supervisor.resource_decision(
                elapsed_seconds=1,
                group_memory_kib=600_000,
                supervisor_memory_kib=100_001,
                sample=healthy,
            ),
            "whole_launch_memory_cap",
        )
        self.assertEqual(supervisor.LAUNCH_MEMAVAILABLE_FLOOR_KIB, 1_900_000)
        self.assertEqual(supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB, 650_000)

    def test_timeout_cleanup_reaches_grandchild(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(30)']);"
            "time.sleep(30)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            _pgid, _identity, _pidfd, generation = (
                supervisor.admit_spawned_process_group(process, process.pid, None)
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if len(supervisor.process_group_pids(process.pid)) >= 2:
                    supervisor.refresh_process_group_generation(generation)
                    break
                time.sleep(0.02)
            result = supervisor.stop_process_group(process, generation, None)
            self.assertEqual(result["final_survivors"], ())
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def test_exited_leader_orphan_group_is_always_drained(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);"
            "print('ready',flush=True);time.sleep(0.2)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        self.assertEqual(process.stdout.readline(), b"ready\n")
        _pgid, _identity, _pidfd, generation = (
            supervisor.admit_spawned_process_group(process, process.pid, None)
        )
        supervisor.refresh_process_group_generation(generation)
        process.wait(timeout=3)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if supervisor.process_group_pids(process.pid):
                break
            time.sleep(0.02)
        self.assertTrue(supervisor.process_group_pids(process.pid))
        result = supervisor.stop_process_group(process, generation, None)
        self.assertTrue(result["leader_exited_before_cleanup"])
        self.assertTrue(result["original_pgid_asserted_empty"])
        self.assertEqual(result["final_survivors"], ())
        process.stdout.close()
        assert process.stderr is not None
        process.stderr.close()

    def test_post_popen_admission_fault_always_drains_provisional_pgid(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);"
            "time.sleep(0.3);raise SystemExit(0)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        provisional_pgid = process.pid

        def fail_after_anchored_admission(
            observed_process: subprocess.Popen[bytes],
            observed_pgid: int,
            generation: supervisor.ProcessGroupGeneration,
        ) -> None:
            self.assertIs(observed_process, process)
            self.assertEqual(observed_pgid, provisional_pgid)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if len(supervisor.process_group_pids(provisional_pgid)) >= 2:
                    supervisor.refresh_process_group_generation(generation)
                    break
                time.sleep(0.005)
            self.assertGreaterEqual(len(generation.members), 2)
            process.wait(timeout=3)
            raise RuntimeError("deterministic post-Popen admission fault")

        cleanup = None
        generation = None
        try:
            _pgid, _identity, _pidfd, generation = (
                supervisor.admit_spawned_process_group(
                    process, provisional_pgid, None
                )
            )
            with self.assertRaisesRegex(RuntimeError, "post-Popen"):
                fail_after_anchored_admission(
                    process, provisional_pgid, generation
                )
        finally:
            if generation is not None and supervisor.process_group_pids(provisional_pgid):
                cleanup = supervisor.stop_process_group(
                    process, generation, None
                )
        self.assertIsNotNone(cleanup)
        self.assertTrue(cleanup["leader_identity_available"])
        self.assertTrue(cleanup["original_pgid_asserted_empty"])
        self.assertEqual(supervisor.process_group_pids(provisional_pgid), ())

    def test_child_preexec_unblocks_inherited_stop_mask_and_cooperates(self) -> None:
        child = (
            "import json,signal,sys,time;"
            "stops={signal.SIGHUP,signal.SIGINT,signal.SIGTERM};"
            "masked=signal.pthread_sigmask(signal.SIG_BLOCK,[]);"
            "print(json.dumps({'masked':sorted(int(x) for x in masked&stops)}),flush=True);"
            "exec('def stop(signum,frame):\\n sys.exit(42)');"
            "[signal.signal(s,stop) for s in stops];"
            "time.sleep(30)"
        )
        old = signal.pthread_sigmask(signal.SIG_BLOCK, supervisor.STOP_SIGNALS)
        parent_pid = os.getpid()
        try:
            process = subprocess.Popen(
                [str(PYTHON), "-I", "-S", "-B", "-c", child],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                preexec_fn=lambda: supervisor.arm_parent_death_signal(parent_pid),
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
        assert process.stdout is not None
        line = process.stdout.readline()
        if not line:
            assert process.stderr is not None
            self.fail(process.stderr.read().decode("utf-8", "replace"))
        self.assertEqual(json.loads(line)["masked"], [])
        os.kill(process.pid, signal.SIGTERM)
        self.assertEqual(process.wait(timeout=5), 42)
        process.stdout.close()
        assert process.stderr is not None
        process.stderr.close()


class ArtifactSchemaTests(unittest.TestCase):
    def fairness(self) -> dict[str, object]:
        return {
            "certificate_sha256": runner.EXPECTED_HASHES[
                "fairness_certificate"
            ],
            "verdict": "NO_GO_UNPROVEN",
            "excluded_progress_sha256": supervisor.EXPECTED_PROGRESS_SHA256,
            "excluded_component_checkpoint_sha256": "b462c82cddaf78f43002cc4ce1f357a64e06876665f587d072bab6aa78e1aa80",
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "progress_runtime_accessed": False,
            "component_checkpoint_runtime_accessed": False,
        }

    def partial(self) -> dict[str, object]:
        return {
            "schema": "planora.muni-fspsx.frontier-v18.fresh-partial.v1",
            "status": "FRESH_SOLVE_NOT_YET_ADMISSIBLE",
            "admissible_as_solution": False,
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
            "lineage": {
                "instance_sha256": supervisor.EXPECTED_INSTANCE_SHA256,
                "runner_sha256": "a" * 64,
                "supervisor_sha256": "b" * 64,
                "planora_source_manifest_sha256": "c" * 64,
                "unsolved_classes": 1623,
                "unsolved_students": 1152,
            },
            "fairness_exclusion": self.fairness(),
            "runtime_lineage": {
                "python_binary_sha256": runner.EXPECTED_HASHES["python_binary"],
                "runtime_manifest_sha256": "d" * 64,
                "loaded_manifest_sha256": "e" * 64,
                "stdlib_manifest_sha256": "f" * 64,
                "residual_system_boundary": "observed_and_hashed_not_sealed",
            },
        }

    def test_partial_schema_is_exact_and_extra_field_fails(self) -> None:
        payload = self.partial()
        self.assertTrue(supervisor.validate_partial_payload(payload))
        payload["unreviewed"] = True
        self.assertFalse(supervisor.validate_partial_payload(payload))

    def test_controlled_unknown_schema_is_exact(self) -> None:
        payload = {
            "schema": "planora.muni-fspsx.frontier-v18.controlled-unknown.v1",
            "status": "CONTROLLED_UNKNOWN",
            "admissible_as_solution": False,
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "fairness_exclusion": self.fairness(),
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
            "partial": {"sha256": "a" * 64},
            "runtime_closure": {"phase": "controlled-unknown-pre-exit"},
            "reason": "synthetic",
        }
        self.assertTrue(supervisor.validate_controlled_stdout(payload))
        payload["solution"] = "forbidden"
        self.assertFalse(supervisor.validate_controlled_stdout(payload))

    def test_solution_xml_schema_and_cardinality_are_exact(self) -> None:
        root = ElementTree.Element(
            "solution", {"name": "synthetic", "technique": "planora-v10"}
        )
        for index in range(1623):
            klass = ElementTree.SubElement(
                root,
                "class",
                {
                    "id": str(index), "days": "1", "start": "0",
                    "weeks": "1", "room": "r",
                },
            )
            if index < 1152:
                ElementTree.SubElement(klass, "student", {"id": str(index)})
        value = ElementTree.tostring(root, encoding="utf-8")
        self.assertTrue(supervisor.validate_solution_document_bytes(value))
        root.attrib["technique"] = "attacker"
        self.assertFalse(
            supervisor.validate_solution_document_bytes(
                ElementTree.tostring(root, encoding="utf-8")
            )
        )

    def test_no_replace_collision_and_alias_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            path = Path(raw)
            os.chmod(path, 0o700)
            row = path.stat()
            identity = {
                "device": row.st_dev, "inode": row.st_ino,
                "uid": row.st_uid, "mode": 0o700,
            }
            target = path / "artifact"
            directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, directory_fd)
            runner.publish_no_replace(
                target, b"reviewed", run_directory=path,
                run_directory_fd=directory_fd, run_identity=identity
            )
            with self.assertRaises(FileExistsError):
                runner.publish_no_replace(
                    target, b"replacement", run_directory=path,
                    run_directory_fd=directory_fd, run_identity=identity
                )

            attacked = path / "attacked"
            stash = path / "retained-alias"
            original = runner.os.link

            def retain(source, destination, *args, **kwargs):
                original(source, destination, *args, **kwargs)
                if destination == attacked.name:
                    original(attacked, stash)

            with (
                mock.patch.object(runner.os, "link", side_effect=retain),
                self.assertRaisesRegex(RuntimeError, "differs"),
            ):
                runner.publish_no_replace(
                    attacked, b"reviewed", run_directory=path,
                    run_directory_fd=directory_fd, run_identity=identity
                )

    def test_bound_directory_rename_swap_and_diverted_open_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            parent = Path(raw)
            bound = parent / "run"
            moved = parent / "moved"
            bound.mkdir(mode=0o700)
            directory_fd = os.open(bound, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, directory_fd)
            row = os.fstat(directory_fd)
            identity = {
                "device": row.st_dev,
                "inode": row.st_ino,
                "uid": row.st_uid,
                "mode": 0o700,
            }
            bound.rename(moved)
            bound.mkdir(mode=0o700)
            with self.assertRaisesRegex(RuntimeError, "bound FD|binding"):
                runner.publish_no_replace(
                    bound / "artifact", b"reviewed",
                    run_directory=bound,
                    run_directory_fd=directory_fd,
                    run_identity=identity,
                )
            self.assertFalse((bound / "artifact").exists())
            self.assertFalse((moved / "artifact").exists())

    def test_artifact_classification_rejects_report_or_output_tampering(self) -> None:
        partial = self.partial()
        controlled = {
            "schema": "planora.muni-fspsx.frontier-v18.controlled-unknown.v1",
            "status": "CONTROLLED_UNKNOWN",
            "admissible_as_solution": False,
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "fairness_exclusion": self.fairness(),
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
            "partial": {"sha256": "a" * 64},
            "runtime_closure": {"phase": "controlled-unknown-pre-exit"},
            "reason": "synthetic",
        }
        accepted, partial_ok = supervisor.classify_artifacts(
            child_exit=3,
            stop_reason="normal_exit",
            received_signal=None,
            partial_payload=partial,
            partial_capture={"sha256": "a" * 64},
            report_payload=None,
            child_stdout_payload=controlled,
            output_bytes=None,
            output_capture=None,
            report_capture=None,
            errors=(),
        )
        self.assertEqual((accepted, partial_ok), (False, True))
        accepted, partial_ok = supervisor.classify_artifacts(
            child_exit=3,
            stop_reason="normal_exit",
            received_signal=None,
            partial_payload=partial,
            partial_capture={"sha256": "a" * 64},
            report_payload={"status": "forged"},
            child_stdout_payload=controlled,
            output_bytes=b"forged",
            output_capture={"sha256": "0" * 64},
            report_capture={"sha256": "1" * 64},
            errors=(),
        )
        self.assertEqual((accepted, partial_ok), (False, False))


def runtime_import_probe() -> None:
    captures: dict[str, dict[str, object]] = {}
    capture_fds: list[int] = []
    runtime_fds: list[int] = []
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="muni-v18-import-probe-") as raw:
        root_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
        try:
            payloads: dict[str, bytes] = {}
            payloads["stdlib_manifest"] = STDLIB_MANIFEST.read_bytes()
            for label, path in supervisor.RUNTIME_RECORDS.items():
                descriptor, evidence = supervisor._stream_capture(
                    path, runner.EXPECTED_HASHES[label], label
                )
                captures[label] = evidence
                capture_fds.extend(
                    (descriptor, int(evidence["source_watch_fd"]))
                )
                payloads[label] = os.pread(
                    descriptor, os.fstat(descriptor).st_size, 0
                )
            with mock.patch.object(
                supervisor, "LAUNCH_MEMAVAILABLE_FLOOR_KIB", 0
            ):
                (
                    admitted_root,
                    manifest_fd,
                    files,
                    binding,
                    _summary,
                ) = supervisor.build_runtime_bundle(
                    runtime_root_fd=root_fd,
                    captures=captures,
                )
            runtime_fds.extend((admitted_root, manifest_fd, *files))
            with mock.patch.dict(
                os.environ,
                {
                    runner.RUNTIME_BUNDLE_ENV: json.dumps(
                        binding, sort_keys=True, separators=(",", ":")
                    )
                },
            ):
                admitted = runner.verify_runtime_bundle(payloads)
                runner.install_sealed_runtime(admitted)
                captured_stderr = io.StringIO()
                with contextlib.redirect_stderr(captured_stderr):
                    from ortools.sat.python import cp_model
                compile_warnings = runner.admit_sealed_runtime_compile_warnings(
                    admitted
                )

                audit_modules = {
                    name: module
                    for name, module in sys.modules.items()
                    if not isinstance(getattr(module, "__file__", None), str)
                    or getattr(module, "__file__").startswith(
                        ("<frozen ", "<sealed-runtime:", "/proc/self/fd/")
                    )
                    or any(
                        Path(getattr(module, "__file__")).resolve().is_relative_to(
                            root
                        )
                        for root in runner.STDLIB_ROOTS
                    )
                }
                with mock.patch.dict(sys.modules, audit_modules, clear=True):
                    loaded = runner.verify_loaded_runtime(payloads, admitted)
                replay = supervisor.verify_runtime_bundle_end(binding)
            print(
                json.dumps(
                    {
                        "status": "SEALED_RUNTIME_IMPORT_OK",
                        "loaded_file_count": loaded["loaded_file_count"],
                        "module_file": str(cp_model.__file__),
                        "compile_warnings": compile_warnings,
                        "captured_stderr": captured_stderr.getvalue(),
                        "replay_file_count": replay["file_count"],
                    },
                    sort_keys=True,
                )
            )
        finally:
            os.close(root_fd)
            for descriptor in runtime_fds + capture_fds:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--runtime-import-probe":
        runtime_import_probe()
    else:
        unittest.main(verbosity=2)
