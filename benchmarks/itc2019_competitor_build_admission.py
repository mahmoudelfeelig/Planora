from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


POLICY_SCHEMA = "planora.itc2019.competitor-build-admission-policy.v1"
MANIFEST_SCHEMA = "planora.itc2019.competitor-build-admission-manifest.v1"
STATUS = "BUILD_ADMISSION_SPECIFIED_NOT_BUILD_READY"
CUSTODY_BINDING_SHA256 = (
    "c30affdb1a8f7d2866fbdd9b41c38f6cd577f6cc6435b407945ab8c432abc0ec"
)
NOT_READY = "REQUIRED_NOT_PRESENT_OR_INDEPENDENTLY_REVIEWED"
CLAIM_SCOPE = "OFFLINE_BUILD_PREREQUISITES_ONLY_NO_BUILD_AUTHORIZATION"

REVIEWED_CONTRACTS = (
    (
        "source-custody-implementation",
        "benchmarks/itc2019_competitor_source_custody.py",
        40169,
        "d611a20781be29e9eac446bd725f50e8f62a35d615e5178716e9dc777b8531d7",
    ),
    (
        "source-custody-tests",
        "tests/test_itc2019_competitor_source_custody.py",
        23614,
        "13d28572947a499b363835868e6310ff2b691152be3914770d61a002bbf9e812",
    ),
    (
        "source-custody-policy",
        "benchmarks/competitor_packages/source-custody-policy.json",
        4257,
        "8f635d45dde0e3b444c3db2d54d6047ae64e841b2efb01d864b549608773f080",
    ),
    (
        "source-custody-documentation",
        "benchmarks/competitor_packages/SOURCE_CUSTODY.md",
        1467,
        "3370ff07cc55d1692c31c69a70df4c464af7cf32a08058b66bd244ecdd614534",
    ),
    (
        "source-custody-manifest",
        "benchmarks/competitor_packages/source-custody-manifest.json",
        10534,
        "3c3382166d0861071340b5eb2216efe895de2c3022170918fd809c60cec0c912",
    ),
    (
        "source-inventory",
        "benchmarks/competitor_packages/source-inventory.json",
        2218,
        "6a7c940793b1088c0c13762e83dac5d4bb4ca0652568e1d044b32d9900697054",
    ),
    (
        "competitor-provenance-verifier",
        "benchmarks/itc2019_competitor_provenance.py",
        35774,
        "9187e80e621cfe2a286c047483536c6d72b14c05f2178fbd59d6cc91bc3e5a53",
    ),
    (
        "competitor-harness",
        "scripts/benchmark_itc2019_competitors.py",
        155789,
        "bbd57cf6bbcfb8955cd9a2f3dc3e4ab700c4a2bc1e347c63bf51f216323970e4",
    ),
)

SOURCE_ARCHIVES = {
    "gashi-sa": (
        (
            "primary",
            "benchmarks/competitor_packages/"
            "gashi-b7b7110d1968758b0b7efe099e7f68aa7f19a4a0.tar.gz",
            43232,
            "d1ac7f6979c03f47fbc247ffb839288f18302963853e1935adfc5ed71480227b",
            "b7b7110d1968758b0b7efe099e7f68aa7f19a4a0",
            "MIT",
        ),
    ),
    "unitime-cpsolver": (
        (
            "primary",
            "benchmarks/competitor_packages/"
            "cpsolver-itc2019-d1576ac94a8f7b6562e49f9476a89fb741cb226f.tar.gz",
            19377,
            "a6b56f4c0017dc45cb6e3d3c0b0f46cabe06ab08f42ef2b43914280dec846484",
            "d1576ac94a8f7b6562e49f9476a89fb741cb226f",
            "LGPL-3.0-only",
        ),
        (
            "required-source-dependency",
            "benchmarks/competitor_packages/"
            "cpsolver-core-3abbcaaf26d739d25e45c8e191b7ef94bc15cc26.tar.gz",
            3243399,
            "af9e8dd246a4f61675a85a0aa7e18296b921ee8524c9d4937bb7237650810f04",
            "3abbcaaf26d739d25e45c8e191b7ef94bc15cc26",
            "LGPL-3.0-only",
        ),
    ),
    "lemos-maxsat": (
        (
            "primary",
            "benchmarks/competitor_packages/"
            "lemos-c33d15797686a27c192eabb90948baa54d3ddef5.tar.gz",
            12909097,
            "7f70b5c6b9f035a0e8b29069a641cb0f14c7e5f421f19a61a3c2b2397aa25cef",
            "c33d15797686a27c192eabb90948baa54d3ddef5",
            "MIT",
        ),
    ),
}

ARGV_CONTRACTS = {
    "gashi-sa": (
        "solver-adapter",
        "--input",
        "{input}",
        "--output",
        "{output}",
        "--seed",
        "{seed}",
        "--seconds",
        "{seconds}",
    ),
    "unitime-cpsolver": (
        "solver-adapter",
        "--input",
        "{input}",
        "--output",
        "{output}",
        "--seed",
        "{seed}",
        "--seconds",
        "{seconds}",
    ),
    "lemos-maxsat": (
        "solver-adapter",
        "--input",
        "{input}",
        "--output",
        "{output}",
        "--seconds",
        "{seconds}",
    ),
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SOLVER_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_PATH_TYPE = type(Path())
_POLICY_KEYS = {
    "schema",
    "custody_binding_sha256",
    "reviewed_contracts",
    "claim_boundary",
    "global_gates",
    "solvers",
}
_CLAIM_KEYS = {
    "scope",
    "build_ready",
    "claim_grade_ready",
    "performance_claims_authorized",
    "statement",
}
_CONTRACT_KEYS = {"role", "path", "size_bytes", "sha256"}
_SOLVER_KEYS = {
    "solver",
    "source_archives",
    "toolchain_dependency_closure",
    "deterministic_recipe_contract",
    "adapter_output_contract",
    "build_receipt_contract",
    "artifact_digest_replay",
}
_SOURCE_KEYS = {"role", "path", "size_bytes", "sha256", "commit_sha", "license_spdx"}
_GATE_KEYS = {"status", "evidence_path", "requirements"}
_ADAPTER_KEYS = {
    "status",
    "adapter_path",
    "argv_template",
    "input_format",
    "output_format",
    "requirements",
}
_RECEIPT_KEYS = {"status", "receipt_path", "schema", "requirements"}
_REPLAY_KEYS = {"status", "digest_manifest_path", "requirements"}
_GLOBAL_GATES_KEYS = {"license_review", "matched_resources"}


class BuildAdmissionError(ValueError):
    """Raised when the fail-closed offline-build admission cannot be replayed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    ).encode()


def _json_values_match_exactly(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (
            all(type(key) is str for key in left)
            and all(type(key) is str for key in right)
            and set(left) == set(right)
            and all(_json_values_match_exactly(left[key], right[key]) for key in left)
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _json_values_match_exactly(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if type(left) in {str, int, float, bool, type(None)}:
        return bool(left == right)
    return False


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise BuildAdmissionError(f"{label} must be a plain string-keyed object")
    if set(value) != keys:
        raise BuildAdmissionError(f"{label} keys do not exactly match the schema")
    return value


def _strict_json_bytes(encoded: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BuildAdmissionError(f"{label} contains duplicate member {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise BuildAdmissionError(f"{label} contains non-standard constant {value!r}")

    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildAdmissionError(f"{label} is not strict UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise BuildAdmissionError(f"{label} must contain an object")
    return payload


def _is_link_or_reparse(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except OSError:
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(
        path.is_symlink()
        or (callable(is_junction) and is_junction())
        or getattr(stat_result, "st_file_attributes", 0) & 0x400
    )


def _identity(path: Path) -> tuple[int, int, int, int, int, int, int]:
    stat_result = path.stat()
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_mode,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
        stat_result.st_nlink,
    )


def _normalized_relative_path(value: Any, label: str) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise BuildAdmissionError(f"{label} must be a normalized POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BuildAdmissionError(f"{label} must remain inside the repository")
    if path.as_posix() != value or ":" in path.parts[0]:
        raise BuildAdmissionError(f"{label} must be lexically normalized")
    return value


TrackedFile = tuple[Path, str, int, tuple[int, int, int, int, int, int, int]]


def _attest_regular(path: Path, label: str) -> TrackedFile:
    if type(path) is not _PATH_TYPE:
        raise BuildAdmissionError(f"{label} path has an invalid type")
    try:
        lexical = Path(os.path.abspath(os.fspath(path)))
        resolved = path.resolve(strict=True)
        if (
            os.path.normcase(str(lexical)) != os.path.normcase(str(resolved))
            or _is_link_or_reparse(path)
            or not resolved.is_file()
            or resolved.stat().st_nlink != 1
        ):
            raise BuildAdmissionError(
                f"{label} must be a regular non-linked single-name file"
            )
        before = _identity(resolved)
        digest = _sha256(resolved)
        after = _identity(resolved)
    except BuildAdmissionError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildAdmissionError(f"{label} is unavailable") from exc
    if before != after:
        raise BuildAdmissionError(f"{label} changed during attestation")
    return resolved, digest, before[3], before


def _attest_bound_file(root: Path, record: dict[str, Any], label: str) -> TrackedFile:
    relative = _normalized_relative_path(record["path"], f"{label}.path")
    tracked = _attest_regular(root / Path(*PurePosixPath(relative).parts), label)
    _, digest, size, _ = tracked
    if digest != record["sha256"] or size != record["size_bytes"]:
        raise BuildAdmissionError(f"{label} size or SHA-256 does not match")
    return tracked


def _read_tracked_bytes(tracked: TrackedFile, label: str) -> bytes:
    path, expected_digest, expected_size, expected_identity = tracked
    try:
        before = _identity(path)
        encoded = path.read_bytes()
        after = _identity(path)
    except OSError as exc:
        raise BuildAdmissionError(f"{label} is unavailable during read") from exc
    if (
        before != expected_identity
        or after != expected_identity
        or len(encoded) != expected_size
        or hashlib.sha256(encoded).hexdigest() != expected_digest
    ):
        raise BuildAdmissionError(f"{label} changed during read")
    return encoded


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], TrackedFile]:
    tracked = _attest_regular(path, label)
    return _strict_json_bytes(_read_tracked_bytes(tracked, label), label), tracked


def _string_list(value: Any, label: str) -> list[str]:
    if (
        type(value) is not list
        or not value
        or any(type(item) is not str or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise BuildAdmissionError(f"{label} must be a non-empty unique string list")
    return list(value)


def _validate_gate(value: Any, label: str) -> dict[str, Any]:
    gate = _exact_object(value, _GATE_KEYS, label)
    if gate["status"] != NOT_READY:
        raise BuildAdmissionError(f"{label} must remain fail-closed")
    _normalized_relative_path(gate["evidence_path"], f"{label}.evidence_path")
    _string_list(gate["requirements"], f"{label}.requirements")
    return gate


def _validate_policy(policy: Any) -> dict[str, Any]:
    value = _exact_object(policy, _POLICY_KEYS, "build admission policy")
    if value["schema"] != POLICY_SCHEMA:
        raise BuildAdmissionError("unsupported build admission policy schema")
    if value["custody_binding_sha256"] != CUSTODY_BINDING_SHA256:
        raise BuildAdmissionError("reviewed custody binding does not match")

    expected_contracts = [
        {"role": role, "path": path, "size_bytes": size, "sha256": digest}
        for role, path, size, digest in REVIEWED_CONTRACTS
    ]
    if value["reviewed_contracts"] != expected_contracts:
        raise BuildAdmissionError("reviewed contract set or identity drifted")

    boundary = _exact_object(value["claim_boundary"], _CLAIM_KEYS, "claim boundary")
    if (
        boundary["scope"] != CLAIM_SCOPE
        or boundary["build_ready"] is not False
        or boundary["claim_grade_ready"] is not False
        or boundary["performance_claims_authorized"] is not False
        or type(boundary["statement"]) is not str
        or not boundary["statement"]
    ):
        raise BuildAdmissionError("claim boundary must remain explicitly false")

    global_gates = _exact_object(
        value["global_gates"], _GLOBAL_GATES_KEYS, "global gates"
    )
    _validate_gate(global_gates["license_review"], "global license review gate")
    _validate_gate(global_gates["matched_resources"], "matched resource gate")

    solvers = value["solvers"]
    if type(solvers) is not list or len(solvers) != len(SOURCE_ARCHIVES):
        raise BuildAdmissionError("solver admission list is incomplete")
    if [item.get("solver") if type(item) is dict else None for item in solvers] != list(
        SOURCE_ARCHIVES
    ):
        raise BuildAdmissionError("solver order or identity drifted")

    for entry in solvers:
        solver_entry = _exact_object(entry, _SOLVER_KEYS, "solver admission")
        solver = solver_entry["solver"]
        if type(solver) is not str or _SOLVER_RE.fullmatch(solver) is None:
            raise BuildAdmissionError("solver identity is invalid")
        expected_sources = [
            {
                "role": role,
                "path": path,
                "size_bytes": size,
                "sha256": digest,
                "commit_sha": commit,
                "license_spdx": license_spdx,
            }
            for role, path, size, digest, commit, license_spdx in SOURCE_ARCHIVES[
                solver
            ]
        ]
        if solver_entry["source_archives"] != expected_sources:
            raise BuildAdmissionError(f"{solver} immutable source inputs drifted")
        for source in solver_entry["source_archives"]:
            _exact_object(source, _SOURCE_KEYS, f"{solver} source")
            _normalized_relative_path(source["path"], f"{solver} source path")

        _validate_gate(
            solver_entry["toolchain_dependency_closure"],
            f"{solver} toolchain and dependency closure",
        )
        _validate_gate(
            solver_entry["deterministic_recipe_contract"],
            f"{solver} deterministic recipe",
        )
        adapter = _exact_object(
            solver_entry["adapter_output_contract"],
            _ADAPTER_KEYS,
            f"{solver} adapter contract",
        )
        if adapter["status"] != NOT_READY:
            raise BuildAdmissionError(f"{solver} adapter must remain fail-closed")
        _normalized_relative_path(adapter["adapter_path"], f"{solver} adapter path")
        if adapter["argv_template"] != list(ARGV_CONTRACTS[solver]):
            raise BuildAdmissionError(
                f"{solver} argv contract drifted from the harness"
            )
        if adapter["input_format"] != "ITC-2019 competition instance XML":
            raise BuildAdmissionError(f"{solver} input contract is invalid")
        if adapter["output_format"] != "ITC-2019 competition solution XML":
            raise BuildAdmissionError(f"{solver} output contract is invalid")
        _string_list(adapter["requirements"], f"{solver} adapter requirements")

        receipt = _exact_object(
            solver_entry["build_receipt_contract"],
            _RECEIPT_KEYS,
            f"{solver} receipt contract",
        )
        if receipt["status"] != NOT_READY or receipt["schema"] != (
            "planora.itc2019.competitor-build-receipt.v2"
        ):
            raise BuildAdmissionError(f"{solver} receipt contract is not fail-closed")
        _normalized_relative_path(receipt["receipt_path"], f"{solver} receipt path")
        _string_list(receipt["requirements"], f"{solver} receipt requirements")

        replay = _exact_object(
            solver_entry["artifact_digest_replay"],
            _REPLAY_KEYS,
            f"{solver} artifact replay",
        )
        if replay["status"] != NOT_READY:
            raise BuildAdmissionError(
                f"{solver} artifact replay must remain fail-closed"
            )
        _normalized_relative_path(
            replay["digest_manifest_path"], f"{solver} digest manifest path"
        )
        _string_list(replay["requirements"], f"{solver} replay requirements")
    return value


def _replay(tracked: Sequence[TrackedFile]) -> None:
    seen: set[Path] = set()
    for path, digest, size, identity in tracked:
        if path in seen:
            raise BuildAdmissionError("tracked input path is duplicated")
        seen.add(path)
        current = _attest_regular(path, "tracked admission input")
        if current[1:] != (digest, size, identity):
            raise BuildAdmissionError("tracked admission input changed during replay")


def _build(
    policy_path: Path, repo_root: Path
) -> tuple[dict[str, Any], list[TrackedFile]]:
    root = repo_root.resolve(strict=True)
    if _is_link_or_reparse(root) or not root.is_dir():
        raise BuildAdmissionError("repository root must be a non-linked directory")
    policy_payload, policy_tracked = _read_json(policy_path, "build admission policy")
    policy = _validate_policy(policy_payload)
    tracked = [policy_tracked]
    attested_contracts = []
    for record in policy["reviewed_contracts"]:
        tracked_file = _attest_bound_file(root, record, record["role"])
        tracked.append(tracked_file)
        attested_contracts.append(dict(record))

    custody_record = next(
        item
        for item in policy["reviewed_contracts"]
        if item["role"] == "source-custody-manifest"
    )
    custody_path = root / Path(*PurePosixPath(custody_record["path"]).parts)
    custody_tracked = next(
        tracked_file
        for tracked_file in tracked
        if tracked_file[0] == custody_path.resolve(strict=True)
    )
    custody_payload = _strict_json_bytes(
        _read_tracked_bytes(custody_tracked, "source custody manifest"),
        "source custody manifest",
    )
    if (
        custody_payload.get("schema")
        != "planora.itc2019.competitor-source-custody-manifest.v1"
        or custody_payload.get("binding_sha256") != CUSTODY_BINDING_SHA256
        or custody_payload.get("status") != "SOURCE_CUSTODY_PREPARED_NOT_BUILD_READY"
        or (custody_payload.get("claim_boundary") or {}).get("build_ready") is not False
        or (custody_payload.get("claim_boundary") or {}).get("claim_grade_ready")
        is not False
        or (custody_payload.get("claim_boundary") or {}).get(
            "performance_claims_authorized"
        )
        is not False
    ):
        raise BuildAdmissionError(
            "source custody manifest is outside its reviewed boundary"
        )

    admitted_solvers = []
    for entry in policy["solvers"]:
        solver = entry["solver"]
        for source in entry["source_archives"]:
            tracked.append(_attest_bound_file(root, source, f"{solver} source archive"))
        admitted_solvers.append(
            {
                "solver": solver,
                "source_archives": entry["source_archives"],
                "admission": {
                    "toolchain_dependency_closure_ready": False,
                    "deterministic_recipe_ready": False,
                    "adapter_output_contract_ready": False,
                    "build_receipt_ready": False,
                    "artifact_digest_replay_ready": False,
                    "license_review_ready": False,
                    "matched_resource_ready": False,
                    "build_ready": False,
                },
                "required_evidence_paths": [
                    entry["toolchain_dependency_closure"]["evidence_path"],
                    entry["deterministic_recipe_contract"]["evidence_path"],
                    entry["adapter_output_contract"]["adapter_path"],
                    entry["build_receipt_contract"]["receipt_path"],
                    entry["artifact_digest_replay"]["digest_manifest_path"],
                    policy["global_gates"]["license_review"]["evidence_path"],
                    policy["global_gates"]["matched_resources"]["evidence_path"],
                ],
            }
        )

    canonical = {
        "schema": MANIFEST_SCHEMA,
        "policy": {
            "path": policy_path.name,
            "sha256": policy_tracked[1],
            "size_bytes": policy_tracked[2],
        },
        "custody_binding_sha256": CUSTODY_BINDING_SHA256,
        "reviewed_contracts": attested_contracts,
        "claim_boundary": policy["claim_boundary"],
        "global_gates": {
            "license_review_ready": False,
            "matched_resources_ready": False,
        },
        "solvers": admitted_solvers,
        "status": STATUS,
    }
    manifest = {**canonical, "binding_sha256": _json_sha256(canonical)}
    _replay(tracked)
    return manifest, tracked


def build_build_admission_manifest(
    policy_path: Path, *, repo_root: Path
) -> dict[str, Any]:
    """Build the deterministic, deliberately not-ready admission manifest."""

    manifest, _ = _build(policy_path, repo_root)
    return manifest


def verify_build_admission_manifest(
    manifest_path: Path,
    *,
    policy_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """Replay all bound inputs and exactly compare a stored admission manifest."""

    observed, manifest_tracked = _read_json(manifest_path, "build admission manifest")
    expected, tracked = _build(policy_path, repo_root)
    if not _json_values_match_exactly(observed, expected):
        raise BuildAdmissionError("build admission manifest drifted from live inputs")
    _replay([*tracked, manifest_tracked])
    return expected


def _main(argv: Sequence[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    package_root = repo_root / "benchmarks" / "competitor_packages"
    parser = argparse.ArgumentParser(
        description="Verify fail-closed competitor build admission."
    )
    parser.add_argument(
        "--policy", type=Path, default=package_root / "build-admission-policy.json"
    )
    parser.add_argument(
        "--manifest", type=Path, default=package_root / "build-admission-manifest.json"
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--print-manifest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.print_manifest:
            result = build_build_admission_manifest(
                args.policy, repo_root=args.repo_root
            )
            print(_manifest_bytes(result).decode("utf-8"), end="")
        else:
            result = verify_build_admission_manifest(
                args.manifest,
                policy_path=args.policy,
                repo_root=args.repo_root,
            )
            print(
                json.dumps(
                    {
                        "binding_sha256": result["binding_sha256"],
                        "build_ready": result["claim_boundary"]["build_ready"],
                        "claim_grade_ready": result["claim_boundary"][
                            "claim_grade_ready"
                        ],
                        "performance_claims_authorized": result["claim_boundary"][
                            "performance_claims_authorized"
                        ],
                        "schema": result["schema"],
                        "status": result["status"],
                    },
                    sort_keys=True,
                )
            )
    except BuildAdmissionError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "BuildAdmissionError",
    "build_build_admission_manifest",
    "verify_build_admission_manifest",
]
