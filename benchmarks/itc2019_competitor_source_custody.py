from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Sequence

from benchmarks.itc2019_competitor_provenance import (
    SUPPORTED_SPDX_LICENSES,
    _repository_url,
    provenance_bindings_match_exactly,
)


SOURCE_INVENTORY_SCHEMA = "planora.itc2019.competitor-source-inventory.v2"
SOURCE_CUSTODY_POLICY_SCHEMA = "planora.itc2019.competitor-source-custody-policy.v1"
SOURCE_CUSTODY_MANIFEST_SCHEMA = "planora.itc2019.competitor-source-custody-manifest.v1"
SOURCE_INVENTORY_STATUS = "SOURCE_ARCHIVES_ONLY_NOT_BUILD_OR_CUSTODY_EVIDENCE"
SOURCE_CUSTODY_STATUS = "SOURCE_CUSTODY_PREPARED_NOT_BUILD_READY"
SOURCE_CUSTODY_SCOPE = "IMMUTABLE_VENDORED_SOURCE_ARCHIVE_CUSTODY_ONLY"
LICENSE_SCOPE = "UPSTREAM_ROOT_DECLARED_LICENSE_ONLY"
TOOLCHAIN_INTENT_STATUS = "INTENT_ONLY_NOT_TOOLCHAIN_OR_BUILD_READINESS"
TREE_IDENTITY_ALGORITHM = (
    "sha256-canonical-json-sorted-root-relative-path-kind-mode-size-content"
)

_CLAIM_BOUNDARY_KEYS = {
    "scope",
    "build_ready",
    "claim_grade_ready",
    "performance_claims_authorized",
    "statement",
}
_INVENTORY_KEYS = {"schema", "claim_grade_ready", "solvers", "status"}
_INVENTORY_SOLVER_KEYS = {"solver", "sources"}
_INVENTORY_SOURCE_KEYS = {
    "role",
    "archive_path",
    "archive_sha256",
    "archive_size_bytes",
    "commit_sha",
    "license_spdx",
    "repository_url",
}
_POLICY_KEYS = {"schema", "source_inventory", "claim_boundary", "solvers"}
_POLICY_INVENTORY_KEYS = {"path", "sha256"}
_POLICY_SOLVER_KEYS = {"solver", "sources"}
_POLICY_SOURCE_KEYS = {
    "archive_path",
    "repository_url",
    "commit_sha",
    "archive_root",
    "license_evidence",
    "toolchain_intent",
}
_LICENSE_EVIDENCE_KEYS = {"spdx", "scope", "members"}
_TOOLCHAIN_INTENT_KEYS = {"ecosystem", "status", "descriptor_members"}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SOLVER_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_ROLE_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
_ECOSYSTEM_RE = re.compile(r"[a-z0-9][a-z0-9+.-]*\Z")
_ARCHIVE_ROOT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_PATH_TYPE = type(Path())
_WINDOWS_RESERVED_STEMS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TREE_BYTES = 512 * 1024 * 1024


class SourceCustodyError(ValueError):
    """Raised when vendored source custody is ambiguous or cannot be replayed."""


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
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise SourceCustodyError(f"{label} must be a plain object")
    if not all(type(key) is str for key in value):
        raise SourceCustodyError(f"{label} keys must be strings")
    if set(value) != keys:
        raise SourceCustodyError(
            f"{label} keys mismatch: expected {sorted(keys)}, got {sorted(value)}"
        )
    return value


def _strict_json_bytes(encoded: bytes, label: str) -> dict[str, Any]:
    def reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SourceCustodyError(
                    f"{label} contains duplicate JSON member {key!r}"
                )
            result[key] = value
        return result

    def reject_nonstandard_constant(value: str) -> None:
        raise SourceCustodyError(
            f"{label} contains non-standard JSON constant {value!r}"
        )

    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=reject_duplicate_members,
            parse_constant=reject_nonstandard_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceCustodyError(f"{label} is not readable strict JSON") from exc
    if type(payload) is not dict:
        raise SourceCustodyError(f"{label} must contain a plain object")
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


def _same_lexical_and_resolved_path(path: Path, resolved: Path) -> bool:
    lexical = Path(os.path.abspath(os.fspath(path)))
    return os.path.normcase(str(lexical)) == os.path.normcase(str(resolved))


def _file_identity(path: Path) -> tuple[int, int, int, int, int, int, int]:
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


def _attest_file(
    path: Path,
    label: str,
) -> tuple[Path, str, int, tuple[int, int, int, int, int, int, int]]:
    if type(path) is not _PATH_TYPE:
        raise SourceCustodyError(f"{label} path has an invalid type")
    try:
        resolved = path.resolve(strict=True)
        if (
            not _same_lexical_and_resolved_path(path, resolved)
            or _is_link_or_reparse(path)
            or not resolved.is_file()
            or resolved.stat().st_nlink != 1
        ):
            raise SourceCustodyError(
                f"{label} must be a regular non-linked single-name file"
            )
        before = _file_identity(resolved)
        digest = _sha256(resolved)
        after = _file_identity(resolved)
    except SourceCustodyError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SourceCustodyError(f"{label} is unavailable") from exc
    if before != after:
        raise SourceCustodyError(f"{label} changed during attestation")
    return resolved, digest, before[3], before


def _read_strict_json_file(
    path: Path,
    label: str,
) -> tuple[
    dict[str, Any],
    Path,
    str,
    int,
    tuple[int, int, int, int, int, int, int],
]:
    resolved, digest, size_bytes, identity = _attest_file(path, label)
    try:
        encoded = resolved.read_bytes()
        after = _file_identity(resolved)
    except OSError as exc:
        raise SourceCustodyError(f"{label} is unavailable") from exc
    if (
        len(encoded) != size_bytes
        or hashlib.sha256(encoded).hexdigest() != digest
        or after != identity
    ):
        raise SourceCustodyError(f"{label} changed while reading")
    return (
        _strict_json_bytes(encoded, label),
        resolved,
        digest,
        size_bytes,
        identity,
    )


def _normalized_relative_path(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or not value.isascii()
        or "\\" in value
        or value.startswith("/")
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise SourceCustodyError(f"{label} must be a normalized relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SourceCustodyError(f"{label} must be a normalized relative path")
    return value


def _normalized_member_name(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or "\\" in value
        or value.startswith("/")
        or unicodedata.normalize("NFC", value) != value
        or any(
            ord(char) == 127 or unicodedata.category(char) in {"Cc", "Cf"}
            for char in value
        )
    ):
        raise SourceCustodyError(f"{label} is an unsafe archive member path")
    parts = value.split("/")
    if any(
        part in {"", ".", ".."}
        or ":" in part
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_STEMS
        for part in parts
    ):
        raise SourceCustodyError(f"{label} is an unsafe archive member path")
    return value


def _lower_sha256(value: Any, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise SourceCustodyError(f"{label} must be lowercase SHA-256")
    return value


def _full_commit(value: Any, label: str) -> str:
    if type(value) is not str or _COMMIT_RE.fullmatch(value) is None:
        raise SourceCustodyError(f"{label} must be a full lowercase commit hash")
    return value


def _non_empty_unique_paths(value: Any, label: str) -> list[str]:
    if type(value) is not list or not value:
        raise SourceCustodyError(f"{label} must be a non-empty ordered list")
    result = [
        _normalized_relative_path(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise SourceCustodyError(f"{label} contains duplicate paths")
    return result


def _validate_claim_boundary(value: Any, label: str) -> dict[str, Any]:
    boundary = _exact_object(value, _CLAIM_BOUNDARY_KEYS, label)
    if boundary["scope"] != SOURCE_CUSTODY_SCOPE:
        raise SourceCustodyError(f"{label}.scope is unsupported")
    for field in (
        "build_ready",
        "claim_grade_ready",
        "performance_claims_authorized",
    ):
        if boundary[field] is not False:
            raise SourceCustodyError(f"{label}.{field} must remain false")
    statement = boundary["statement"]
    if type(statement) is not str or not statement or not statement.isascii():
        raise SourceCustodyError(f"{label}.statement is invalid")
    return dict(boundary)


def _validate_inventory(payload: Any) -> list[dict[str, Any]]:
    inventory = _exact_object(payload, _INVENTORY_KEYS, "source inventory")
    if inventory["schema"] != SOURCE_INVENTORY_SCHEMA:
        raise SourceCustodyError("unsupported source inventory schema")
    if inventory["claim_grade_ready"] is not False:
        raise SourceCustodyError("source inventory claim_grade_ready must remain false")
    if inventory["status"] != SOURCE_INVENTORY_STATUS:
        raise SourceCustodyError("source inventory status is unsupported")
    raw_solvers = inventory["solvers"]
    if type(raw_solvers) is not list or not raw_solvers:
        raise SourceCustodyError("source inventory solvers must be non-empty")
    normalized: list[dict[str, Any]] = []
    seen_solvers: set[str] = set()
    seen_archives: set[str] = set()
    seen_archive_hashes: set[str] = set()
    seen_upstreams: set[tuple[str, str]] = set()
    for solver_index, raw_solver in enumerate(raw_solvers):
        solver_item = _exact_object(
            raw_solver,
            _INVENTORY_SOLVER_KEYS,
            f"source inventory solvers[{solver_index}]",
        )
        solver = solver_item["solver"]
        if type(solver) is not str or _SOLVER_RE.fullmatch(solver) is None:
            raise SourceCustodyError("source inventory solver is invalid")
        if solver in seen_solvers:
            raise SourceCustodyError("source inventory contains a duplicate solver")
        seen_solvers.add(solver)
        raw_sources = solver_item["sources"]
        if type(raw_sources) is not list or not raw_sources:
            raise SourceCustodyError(f"{solver}.sources must be non-empty")
        sources: list[dict[str, Any]] = []
        for source_index, raw_source in enumerate(raw_sources):
            label = f"{solver}.sources[{source_index}]"
            source = _exact_object(raw_source, _INVENTORY_SOURCE_KEYS, label)
            role = source["role"]
            if type(role) is not str or _ROLE_RE.fullmatch(role) is None:
                raise SourceCustodyError(f"{label}.role is invalid")
            archive_path = _normalized_relative_path(
                source["archive_path"], f"{label}.archive_path"
            )
            if "/" in archive_path or not archive_path.endswith(".tar.gz"):
                raise SourceCustodyError(
                    f"{label}.archive_path must name one package-root tar.gz"
                )
            archive_sha256 = _lower_sha256(
                source["archive_sha256"], f"{label}.archive_sha256"
            )
            archive_size_bytes = source["archive_size_bytes"]
            if (
                type(archive_size_bytes) is not int
                or archive_size_bytes < 1
                or archive_size_bytes > MAX_ARCHIVE_BYTES
            ):
                raise SourceCustodyError(f"{label}.archive_size_bytes is invalid")
            commit_sha = _full_commit(source["commit_sha"], f"{label}.commit_sha")
            try:
                repository_url = _repository_url(
                    source["repository_url"], f"{label}.repository_url"
                )
            except ValueError as exc:
                raise SourceCustodyError(str(exc)) from exc
            spdx = source["license_spdx"]
            if type(spdx) is not str or spdx not in SUPPORTED_SPDX_LICENSES:
                raise SourceCustodyError(f"{label}.license_spdx is invalid")
            upstream_identity = (repository_url, commit_sha)
            if upstream_identity in seen_upstreams:
                raise SourceCustodyError("source inventory repeats an upstream")
            if archive_path in seen_archives or archive_sha256 in seen_archive_hashes:
                raise SourceCustodyError("source inventory repeats an archive")
            seen_upstreams.add(upstream_identity)
            seen_archives.add(archive_path)
            seen_archive_hashes.add(archive_sha256)
            sources.append(
                {
                    "role": role,
                    "archive_path": archive_path,
                    "archive_sha256": archive_sha256,
                    "archive_size_bytes": archive_size_bytes,
                    "commit_sha": commit_sha,
                    "license_spdx": spdx,
                    "repository_url": repository_url,
                }
            )
        normalized.append({"solver": solver, "sources": sources})
    return normalized


def _validate_policy(
    payload: Any,
    *,
    inventory_path: Path,
    inventory_sha256: str,
    inventory_solvers: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = _exact_object(payload, _POLICY_KEYS, "source custody policy")
    if policy["schema"] != SOURCE_CUSTODY_POLICY_SCHEMA:
        raise SourceCustodyError("unsupported source custody policy schema")
    inventory_binding = _exact_object(
        policy["source_inventory"],
        _POLICY_INVENTORY_KEYS,
        "source custody policy source_inventory",
    )
    inventory_name = _normalized_relative_path(
        inventory_binding["path"], "source custody policy source_inventory.path"
    )
    if "/" in inventory_name or inventory_name != inventory_path.name:
        raise SourceCustodyError("source custody policy inventory path mismatch")
    if (
        _lower_sha256(
            inventory_binding["sha256"],
            "source custody policy source_inventory.sha256",
        )
        != inventory_sha256
    ):
        raise SourceCustodyError("source custody policy inventory hash mismatch")
    claim_boundary = _validate_claim_boundary(
        policy["claim_boundary"], "source custody policy claim_boundary"
    )
    raw_solvers = policy["solvers"]
    if type(raw_solvers) is not list:
        raise SourceCustodyError(
            "source custody policy solvers must be an ordered list"
        )
    if len(raw_solvers) != len(inventory_solvers):
        raise SourceCustodyError("source custody policy solver order mismatch")
    normalized: list[dict[str, Any]] = []
    for solver_index, (raw_solver, inventory_solver) in enumerate(
        zip(raw_solvers, inventory_solvers, strict=True)
    ):
        solver_item = _exact_object(
            raw_solver,
            _POLICY_SOLVER_KEYS,
            f"source custody policy solvers[{solver_index}]",
        )
        if solver_item["solver"] != inventory_solver["solver"]:
            raise SourceCustodyError("source custody policy solver order mismatch")
        solver = inventory_solver["solver"]
        raw_sources = solver_item["sources"]
        inventory_sources = inventory_solver["sources"]
        if type(raw_sources) is not list or len(raw_sources) != len(inventory_sources):
            raise SourceCustodyError(f"{solver} custody source order mismatch")
        sources: list[dict[str, Any]] = []
        for source_index, (raw_source, inventory_source) in enumerate(
            zip(raw_sources, inventory_sources, strict=True)
        ):
            label = f"{solver}.custody_sources[{source_index}]"
            source = _exact_object(raw_source, _POLICY_SOURCE_KEYS, label)
            archive_path = _normalized_relative_path(
                source["archive_path"], f"{label}.archive_path"
            )
            repository_url = source["repository_url"]
            commit_sha = source["commit_sha"]
            if (
                archive_path != inventory_source["archive_path"]
                or repository_url != inventory_source["repository_url"]
                or commit_sha != inventory_source["commit_sha"]
            ):
                raise SourceCustodyError(f"{label} upstream identity/order mismatch")
            archive_root = source["archive_root"]
            if (
                type(archive_root) is not str
                or _ARCHIVE_ROOT_RE.fullmatch(archive_root) is None
            ):
                raise SourceCustodyError(f"{label}.archive_root is invalid")
            license_item = _exact_object(
                source["license_evidence"], _LICENSE_EVIDENCE_KEYS, f"{label}.license"
            )
            if license_item["spdx"] != inventory_source["license_spdx"]:
                raise SourceCustodyError(f"{label}.license.spdx mismatch")
            if license_item["scope"] != LICENSE_SCOPE:
                raise SourceCustodyError(f"{label}.license.scope is invalid")
            license_members = _non_empty_unique_paths(
                license_item["members"], f"{label}.license.members"
            )
            toolchain = _exact_object(
                source["toolchain_intent"],
                _TOOLCHAIN_INTENT_KEYS,
                f"{label}.toolchain_intent",
            )
            ecosystem = toolchain["ecosystem"]
            if type(ecosystem) is not str or _ECOSYSTEM_RE.fullmatch(ecosystem) is None:
                raise SourceCustodyError(f"{label}.toolchain_intent.ecosystem invalid")
            if toolchain["status"] != TOOLCHAIN_INTENT_STATUS:
                raise SourceCustodyError(f"{label}.toolchain_intent.status invalid")
            descriptor_members = _non_empty_unique_paths(
                toolchain["descriptor_members"],
                f"{label}.toolchain_intent.descriptor_members",
            )
            sources.append(
                {
                    "archive_path": archive_path,
                    "repository_url": repository_url,
                    "commit_sha": commit_sha,
                    "archive_root": archive_root,
                    "license_evidence": {
                        "spdx": license_item["spdx"],
                        "scope": LICENSE_SCOPE,
                        "members": license_members,
                    },
                    "toolchain_intent": {
                        "ecosystem": ecosystem,
                        "status": TOOLCHAIN_INTENT_STATUS,
                        "descriptor_members": descriptor_members,
                    },
                }
            )
        normalized.append({"solver": solver, "sources": sources})
    return claim_boundary, normalized


def _member_content_sha256(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    label: str,
) -> str:
    try:
        stream = archive.extractfile(member)
    except (KeyError, OSError, tarfile.TarError) as exc:
        raise SourceCustodyError(f"{label} cannot be read") from exc
    if stream is None:
        raise SourceCustodyError(f"{label} has no regular-file stream")
    digest = hashlib.sha256()
    observed_size = 0
    try:
        with stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                observed_size += len(chunk)
                if observed_size > member.size:
                    raise SourceCustodyError(f"{label} exceeds its declared size")
                digest.update(chunk)
    except (OSError, tarfile.TarError) as exc:
        raise SourceCustodyError(f"{label} cannot be read") from exc
    if observed_size != member.size:
        raise SourceCustodyError(f"{label} size does not match its tar header")
    return digest.hexdigest()


def _scan_archive(
    archive_path: Path,
    *,
    archive_root: str,
    license_paths: Sequence[str],
    descriptor_paths: Sequence[str],
) -> dict[str, Any]:
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise SourceCustodyError("archive member count is invalid")
            records: list[dict[str, Any]] = []
            seen_paths: set[str] = set()
            seen_portable_paths: set[str] = set()
            root_members = 0
            regular_file_count = 0
            directory_count = 0
            total_regular_bytes = 0
            for index, member in enumerate(members):
                label = f"archive member[{index}]"
                raw_name = member.name.removesuffix("/")
                normalized_name = _normalized_member_name(raw_name, f"{label}.name")
                if member.sparse is not None or any(
                    key.casefold().startswith("gnu.sparse")
                    for key in member.pax_headers
                ):
                    raise SourceCustodyError(
                        f"{label} contains unsupported sparse metadata"
                    )
                parts = normalized_name.split("/")
                if parts[0] != archive_root:
                    raise SourceCustodyError(f"{label} is outside the expected root")
                if len(parts) == 1:
                    root_members += 1
                    if not member.isdir():
                        raise SourceCustodyError("archive root must be a directory")
                    continue
                logical_path = "/".join(parts[1:])
                _normalized_member_name(logical_path, f"{label}.logical_path")
                if logical_path in seen_paths:
                    raise SourceCustodyError(
                        f"archive contains duplicate member path {logical_path!r}"
                    )
                portable_path = logical_path.casefold()
                if portable_path in seen_portable_paths:
                    raise SourceCustodyError(
                        "archive contains a case-insensitive member-path collision"
                    )
                seen_paths.add(logical_path)
                seen_portable_paths.add(portable_path)
                mode = member.mode
                if type(mode) is not int or not 0 <= mode <= 0o7777:
                    raise SourceCustodyError(f"{label}.mode is invalid")
                if member.isdir():
                    directory_count += 1
                    records.append(
                        {"path": logical_path, "kind": "directory", "mode": mode}
                    )
                    continue
                if member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}:
                    raise SourceCustodyError(
                        f"{label} has unsupported member type {member.type!r}"
                    )
                size_bytes = member.size
                if (
                    type(size_bytes) is not int
                    or size_bytes < 0
                    or size_bytes > MAX_MEMBER_BYTES
                ):
                    raise SourceCustodyError(f"{label}.size is invalid")
                total_regular_bytes += size_bytes
                if total_regular_bytes > MAX_TREE_BYTES:
                    raise SourceCustodyError(
                        "archive expanded tree exceeds custody limit"
                    )
                regular_file_count += 1
                records.append(
                    {
                        "path": logical_path,
                        "kind": "file",
                        "mode": mode,
                        "size_bytes": size_bytes,
                        "sha256": _member_content_sha256(archive, member, label),
                    }
                )
    except SourceCustodyError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise SourceCustodyError(
            "archive is not a readable gzip-compressed tar"
        ) from exc
    if root_members != 1:
        raise SourceCustodyError(
            "archive must contain exactly one expected root member"
        )
    records.sort(key=lambda item: item["path"].encode("utf-8"))
    by_path = {item["path"]: item for item in records}
    critical_paths = [*license_paths, *descriptor_paths]
    missing = [path for path in critical_paths if path not in by_path]
    if missing:
        raise SourceCustodyError(
            "archive is missing custody-selected members: " + ", ".join(missing)
        )
    non_files = [path for path in critical_paths if by_path[path]["kind"] != "file"]
    if non_files:
        raise SourceCustodyError(
            "custody-selected members must be regular files: " + ", ".join(non_files)
        )
    return {
        "tree": {
            "identity_algorithm": TREE_IDENTITY_ALGORITHM,
            "member_count": len(records),
            "regular_file_count": regular_file_count,
            "directory_count": directory_count,
            "total_regular_bytes": total_regular_bytes,
            "member_identity_sha256": _json_sha256(records),
        },
        "license_members": [dict(by_path[path]) for path in license_paths],
        "descriptor_members": [dict(by_path[path]) for path in descriptor_paths],
    }


TrackedFile = tuple[
    Path,
    str,
    int,
    tuple[int, int, int, int, int, int, int],
]


def _replay_tracked_files(tracked: Sequence[TrackedFile]) -> None:
    seen: set[Path] = set()
    for resolved, expected_sha256, expected_size, expected_identity in tracked:
        if resolved in seen:
            raise SourceCustodyError("custody replay contains a duplicate file path")
        seen.add(resolved)
        try:
            current = resolved.resolve(strict=True)
            if (
                current != resolved
                or _is_link_or_reparse(resolved)
                or not current.is_file()
                or current.stat().st_nlink != 1
                or _file_identity(current) != expected_identity
                or current.stat().st_size != expected_size
            ):
                raise SourceCustodyError(
                    "a custody input changed file identity during replay"
                )
            if _sha256(current) != expected_sha256:
                raise SourceCustodyError("a custody input changed during replay")
        except SourceCustodyError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise SourceCustodyError(
                "a custody input is unavailable during replay"
            ) from exc


def _build_source_custody_manifest(
    inventory_path: Path,
    policy_path: Path,
) -> tuple[dict[str, Any], list[TrackedFile]]:
    (
        inventory_payload,
        resolved_inventory,
        inventory_sha256,
        inventory_size,
        inventory_identity,
    ) = _read_strict_json_file(inventory_path, "source inventory")
    inventory_solvers = _validate_inventory(inventory_payload)
    (
        policy_payload,
        resolved_policy,
        policy_sha256,
        policy_size,
        policy_identity,
    ) = _read_strict_json_file(policy_path, "source custody policy")
    claim_boundary, policy_solvers = _validate_policy(
        policy_payload,
        inventory_path=resolved_inventory,
        inventory_sha256=inventory_sha256,
        inventory_solvers=inventory_solvers,
    )
    if resolved_inventory.parent != resolved_policy.parent:
        raise SourceCustodyError("inventory and policy must share one package root")
    package_root = resolved_inventory.parent
    tracked: list[TrackedFile] = [
        (
            resolved_inventory,
            inventory_sha256,
            inventory_size,
            inventory_identity,
        ),
        (resolved_policy, policy_sha256, policy_size, policy_identity),
    ]
    normalized_solvers: list[dict[str, Any]] = []
    for inventory_solver, policy_solver in zip(
        inventory_solvers, policy_solvers, strict=True
    ):
        solver = inventory_solver["solver"]
        normalized_sources: list[dict[str, Any]] = []
        for inventory_source, policy_source in zip(
            inventory_solver["sources"], policy_solver["sources"], strict=True
        ):
            archive_path = package_root / inventory_source["archive_path"]
            (
                resolved_archive,
                archive_sha256,
                archive_size,
                archive_identity,
            ) = _attest_file(archive_path, f"{solver} source archive")
            if (
                archive_sha256 != inventory_source["archive_sha256"]
                or archive_size != inventory_source["archive_size_bytes"]
            ):
                raise SourceCustodyError(
                    f"{solver} source archive attestation mismatch"
                )
            tracked.append(
                (
                    resolved_archive,
                    archive_sha256,
                    archive_size,
                    archive_identity,
                )
            )
            scan = _scan_archive(
                resolved_archive,
                archive_root=policy_source["archive_root"],
                license_paths=policy_source["license_evidence"]["members"],
                descriptor_paths=policy_source["toolchain_intent"][
                    "descriptor_members"
                ],
            )
            normalized_sources.append(
                {
                    "role": inventory_source["role"],
                    "repository_url": inventory_source["repository_url"],
                    "commit_sha": inventory_source["commit_sha"],
                    "archive": {
                        "path": inventory_source["archive_path"],
                        "format": "tar+gzip",
                        "sha256": archive_sha256,
                        "size_bytes": archive_size,
                        "root": policy_source["archive_root"],
                    },
                    "tree": scan["tree"],
                    "license_evidence": {
                        "spdx": inventory_source["license_spdx"],
                        "scope": LICENSE_SCOPE,
                        "members": scan["license_members"],
                    },
                    "toolchain_intent": {
                        "ecosystem": policy_source["toolchain_intent"]["ecosystem"],
                        "status": TOOLCHAIN_INTENT_STATUS,
                        "descriptor_members": scan["descriptor_members"],
                    },
                }
            )
        normalized_solvers.append({"solver": solver, "sources": normalized_sources})
    canonical = {
        "schema": SOURCE_CUSTODY_MANIFEST_SCHEMA,
        "source_inventory": {
            "path": resolved_inventory.name,
            "sha256": inventory_sha256,
            "size_bytes": inventory_size,
        },
        "custody_policy": {
            "path": resolved_policy.name,
            "sha256": policy_sha256,
            "size_bytes": policy_size,
        },
        "claim_boundary": claim_boundary,
        "solvers": normalized_solvers,
        "status": SOURCE_CUSTODY_STATUS,
    }
    manifest = {**canonical, "binding_sha256": _json_sha256(canonical)}
    _replay_tracked_files(tracked)
    return manifest, tracked


def build_source_custody_manifest(
    inventory_path: Path,
    policy_path: Path,
) -> dict[str, Any]:
    """Build a deterministic custody value without extracting or executing sources."""

    manifest, _ = _build_source_custody_manifest(inventory_path, policy_path)
    return manifest


def verify_source_custody_manifest(
    manifest_path: Path,
    *,
    inventory_path: Path,
    policy_path: Path,
) -> dict[str, Any]:
    """Replay every custody input and compare the stored manifest with exact types."""

    (
        observed,
        resolved_manifest,
        manifest_sha256,
        manifest_size,
        manifest_identity,
    ) = _read_strict_json_file(manifest_path, "source custody manifest")
    expected, tracked = _build_source_custody_manifest(inventory_path, policy_path)
    if not provenance_bindings_match_exactly(observed, expected):
        raise SourceCustodyError(
            "source custody manifest does not exactly match live archive custody"
        )
    _replay_tracked_files(
        [
            *tracked,
            (
                resolved_manifest,
                manifest_sha256,
                manifest_size,
                manifest_identity,
            ),
        ]
    )
    return expected


def create_source_custody_manifest(
    manifest_path: Path,
    *,
    inventory_path: Path,
    policy_path: Path,
) -> dict[str, Any]:
    """Create one deterministic manifest without replacing an existing artifact."""

    if type(manifest_path) is not _PATH_TYPE:
        raise SourceCustodyError("source custody manifest path has an invalid type")
    manifest, tracked = _build_source_custody_manifest(inventory_path, policy_path)
    encoded = _manifest_bytes(manifest)
    temporary_path: Path | None = None
    linked_candidate = False
    linked_candidate_key: tuple[int, int] | None = None
    published_identity: tuple[int, int, int, int, int, int, int] | None = None
    result: dict[str, Any] | None = None
    try:
        resolved_parent = manifest_path.parent.resolve(strict=True)
        candidate = resolved_parent / manifest_path.name
        if not _same_lexical_and_resolved_path(manifest_path, candidate):
            raise SourceCustodyError(
                "source custody manifest path must be lexically normalized"
            )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{candidate.name}.",
            suffix=".tmp",
            dir=resolved_parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        _replay_tracked_files(tracked)
        try:
            os.link(temporary_path, candidate, follow_symlinks=False)
        except FileExistsError as exc:
            raise SourceCustodyError("source custody manifest already exists") from exc
        linked_candidate = True
        linked_stat = candidate.stat()
        linked_candidate_key = (linked_stat.st_dev, linked_stat.st_ino)
        temporary_path.unlink()
        temporary_path = None
        published_identity = _file_identity(candidate)
        result = verify_source_custody_manifest(
            candidate,
            inventory_path=inventory_path,
            policy_path=policy_path,
        )
    except SourceCustodyError:
        raise
    except OSError as exc:
        raise SourceCustodyError(
            "source custody manifest could not be created"
        ) from exc
    finally:
        if linked_candidate and result is None:
            try:
                same_temporary = temporary_path is not None and os.path.samefile(
                    candidate, temporary_path
                )
                current_stat = candidate.stat()
                same_published = (
                    linked_candidate_key is not None
                    and (current_stat.st_dev, current_stat.st_ino)
                    == linked_candidate_key
                    and (
                        published_identity is None
                        or _file_identity(candidate) == published_identity
                    )
                    and _sha256(candidate) == hashlib.sha256(encoded).hexdigest()
                )
                if same_temporary or same_published:
                    candidate.unlink()
            except (OSError, ValueError):
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
    if result is None:
        raise SourceCustodyError("source custody manifest publication failed")
    return result


def _main(argv: Sequence[str] | None = None) -> int:
    package_root = Path(__file__).resolve().parent / "competitor_packages"
    parser = argparse.ArgumentParser(
        description="Create or verify deterministic ITC-2019 competitor source custody."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=package_root / "source-inventory.json",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=package_root / "source-custody-policy.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=package_root / "source-custody-manifest.json",
    )
    args = parser.parse_args(argv)
    try:
        if args.create:
            result = create_source_custody_manifest(
                args.manifest,
                inventory_path=args.inventory,
                policy_path=args.policy,
            )
        else:
            result = verify_source_custody_manifest(
                args.manifest,
                inventory_path=args.inventory,
                policy_path=args.policy,
            )
    except SourceCustodyError as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "schema": result["schema"],
                "status": result["status"],
                "binding_sha256": result["binding_sha256"],
                "build_ready": result["claim_boundary"]["build_ready"],
                "claim_grade_ready": result["claim_boundary"]["claim_grade_ready"],
                "performance_claims_authorized": result["claim_boundary"][
                    "performance_claims_authorized"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "SOURCE_CUSTODY_MANIFEST_SCHEMA",
    "SOURCE_CUSTODY_POLICY_SCHEMA",
    "SOURCE_CUSTODY_SCOPE",
    "SOURCE_CUSTODY_STATUS",
    "SOURCE_INVENTORY_SCHEMA",
    "SourceCustodyError",
    "build_source_custody_manifest",
    "create_source_custody_manifest",
    "verify_source_custody_manifest",
]
