from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


PROVENANCE_SCHEMA = "planora.itc2019.competitor-provenance.v1"
PROVENANCE_SCHEMA_V2 = "planora.itc2019.competitor-provenance.v2"
BUILD_RECEIPT_SCHEMA = "planora.itc2019.competitor-build-receipt.v1"
BUILD_RECEIPT_SCHEMA_V2 = "planora.itc2019.competitor-build-receipt.v2"

_SOLVER_KEYS_V1 = {
    "upstream",
    "license",
    "build",
    "image_digest",
}
_SOLVER_KEYS_V2 = {"upstreams", "build", "image_digest"}
_UPSTREAM_KEYS = {"repository_url", "commit_sha", "source_archive"}
_UPSTREAM_V2_KEYS = {
    "repository_url",
    "commit_sha",
    "source_archive",
    "license",
}
_LICENSE_KEYS = {"spdx", "path", "sha256"}
_BUILD_KEYS = {"recipe", "adapter", "receipt"}
_FILE_KEYS = {"path", "sha256"}
_SIZED_FILE_KEYS = {"path", "sha256", "size_bytes"}
_RECEIPT_KEYS = {
    "schema",
    "solver",
    "upstream_commit",
    "source_archive_sha256",
    "license_sha256",
    "recipe_sha256",
    "adapter_sha256",
    "image_digest",
    "base_images",
    "argv",
    "network_mode",
    "build_success",
}
_RECEIPT_V2_KEYS = {
    "schema",
    "solver",
    "upstreams",
    "recipe_sha256",
    "adapter_sha256",
    "image_digest",
    "base_images",
    "argv",
    "network_mode",
    "build_success",
}
_BASE_IMAGE_KEYS = {"reference", "digest"}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SOLVER_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_PINNED_IMAGE_RE = re.compile(r"(?P<name>[^@]+)@sha256:(?P<digest>[0-9a-f]{64})\Z")
_REPOSITORY_COMPONENT_RE = re.compile(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*\Z")
_REGISTRY_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_PLATFORM_RE = re.compile(
    r"(?:linux|windows)/(?:386|amd64|arm|arm64|ppc64le|s390x)"
    r"(?:/[a-z0-9][a-z0-9._-]*)?\Z"
)
_STAGE_ALIAS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_PATH_TYPE = type(Path())
SUPPORTED_SPDX_LICENSES = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "MIT",
        "MPL-2.0",
    }
)


class CompetitorProvenanceError(ValueError):
    """Raised when a competitor package cannot support reproducible custody."""


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


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CompetitorProvenanceError(f"{label} must be a plain object")
    if not all(type(key) is str for key in value):
        raise CompetitorProvenanceError(f"{label} keys must be strings")
    actual = set(value)
    if actual != keys:
        raise CompetitorProvenanceError(
            f"{label} keys mismatch: expected {sorted(keys)}, got {sorted(actual)}"
        )
    return value


def provenance_bindings_match_exactly(left: Any, right: Any) -> bool:
    """Compare JSON-shaped provenance values without Python bool/int coercion."""

    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (
            all(type(key) is str for key in left)
            and all(type(key) is str for key in right)
            and set(left) == set(right)
            and all(
                provenance_bindings_match_exactly(left[key], right[key]) for key in left
            )
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            provenance_bindings_match_exactly(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if type(left) in {str, int, float, bool, type(None)}:
        return bool(left == right)
    return False


def _lower_sha256(value: Any, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise CompetitorProvenanceError(f"{label} must be lowercase SHA-256")
    return value


def _image_digest(value: Any, label: str) -> str:
    if type(value) is not str or not value.startswith("sha256:"):
        raise CompetitorProvenanceError(f"{label} must be an immutable image digest")
    _lower_sha256(value.removeprefix("sha256:"), label)
    return value


def _read_plain_json(
    path: Path,
    label: str,
    *,
    expected_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    def reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CompetitorProvenanceError(
                    f"{label} contains duplicate JSON member {key!r}"
                )
            result[key] = value
        return result

    def reject_nonstandard_constant(value: str) -> None:
        raise CompetitorProvenanceError(
            f"{label} contains non-standard JSON constant {value!r}"
        )

    try:
        encoded = path.read_bytes()
        digest = hashlib.sha256(encoded).hexdigest()
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=reject_duplicate_members,
            parse_constant=reject_nonstandard_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompetitorProvenanceError(f"{label} is not readable strict JSON") from exc
    if expected_sha256 is not None and digest != expected_sha256:
        raise CompetitorProvenanceError(f"{label} changed after its file attestation")
    if type(payload) is not dict:
        raise CompetitorProvenanceError(f"{label} must contain a plain object")
    return payload, digest


def _has_symlink_component(candidate: Path, root: Path) -> bool:
    current = root
    for part in candidate.relative_to(root).parts:
        current /= part
        if _is_link_or_reparse(current):
            return True
    return False


def _is_link_or_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError:
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(
        path.is_symlink()
        or (callable(is_junction) and is_junction())
        or getattr(stat, "st_file_attributes", 0) & 0x400
    )


def _file_identity(path: Path) -> tuple[int, int, int, int, int, int]:
    stat = path.stat()
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_mode,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _same_lexical_and_resolved_path(path: Path, resolved: Path) -> bool:
    lexical = Path(os.path.abspath(os.fspath(path)))
    return os.path.normcase(str(lexical)) == os.path.normcase(str(resolved))


def _attested_file(
    payload: Any,
    *,
    root: Path,
    label: str,
) -> tuple[
    Path,
    Path,
    dict[str, str],
    tuple[int, int, int, int, int, int],
]:
    item = _exact_object(payload, _FILE_KEYS, label)
    relative = item["path"]
    expected = _lower_sha256(item["sha256"], f"{label}.sha256")
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or Path(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise CompetitorProvenanceError(
            f"{label}.path must be a normalized manifest-relative path"
        )
    candidate = root.joinpath(*relative.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if (
            _has_symlink_component(candidate, root)
            or not _same_lexical_and_resolved_path(candidate, resolved)
            or not resolved.is_file()
        ):
            raise CompetitorProvenanceError(
                f"{label}.path must be a regular non-symlink file"
            )
        if resolved.stat().st_nlink != 1:
            raise CompetitorProvenanceError(f"{label}.path must not be hard-linked")
        identity = _file_identity(resolved)
        actual = _sha256(resolved)
    except CompetitorProvenanceError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise CompetitorProvenanceError(f"{label}.path escapes or is missing") from exc
    if actual != expected:
        raise CompetitorProvenanceError(f"{label}.sha256 mismatch")
    return candidate, resolved, {"path": relative, "sha256": actual}, identity


def _attested_sized_file(
    payload: Any,
    *,
    root: Path,
    label: str,
) -> tuple[
    Path,
    Path,
    dict[str, str | int],
    tuple[int, int, int, int, int, int],
]:
    item = _exact_object(payload, _SIZED_FILE_KEYS, label)
    size_bytes = item["size_bytes"]
    if type(size_bytes) is not int or size_bytes < 1:
        raise CompetitorProvenanceError(
            f"{label}.size_bytes must be a positive integer"
        )
    lexical, resolved, attestation, identity = _attested_file(
        {"path": item["path"], "sha256": item["sha256"]},
        root=root,
        label=label,
    )
    if identity[3] != size_bytes:
        raise CompetitorProvenanceError(f"{label}.size_bytes mismatch")
    return (
        lexical,
        resolved,
        {**attestation, "size_bytes": size_bytes},
        identity,
    )


def _repository_url(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or len(value) > 2048
        or "\\" in value
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise CompetitorProvenanceError(f"{label} must be an HTTPS repository URL")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise CompetitorProvenanceError(
            f"{label} must be an HTTPS repository URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.netloc != parsed.netloc.lower()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CompetitorProvenanceError(f"{label} must be an HTTPS repository URL")
    if port is not None and not 1 <= port <= 65535:
        raise CompetitorProvenanceError(f"{label} has an invalid HTTPS port")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if any(
            _REGISTRY_LABEL_RE.fullmatch(part) is None for part in hostname.split(".")
        ):
            raise CompetitorProvenanceError(f"{label} has an invalid HTTPS host")
    path_parts = parsed.path.split("/")
    if (
        not parsed.path.startswith("/")
        or parsed.path == "/"
        or any(part in {"", ".", ".."} for part in path_parts[1:])
        or "%" in parsed.path
    ):
        raise CompetitorProvenanceError(f"{label} has an invalid repository path")
    return value


def _string_argv(value: Any, label: str) -> list[str]:
    if type(value) is not list or not value:
        raise CompetitorProvenanceError(f"{label} must be a non-empty argv list")
    result: list[str] = []
    for item in value:
        if (
            type(item) is not str
            or not item
            or len(item) > 4096
            or any(
                ord(char) == 127 or unicodedata.category(char) in {"Cc", "Cf"}
                for char in item
            )
        ):
            raise CompetitorProvenanceError(f"{label} contains an invalid argument")
        result.append(item)
    return result


def _pinned_base_reference(value: Any, label: str) -> tuple[str, str]:
    if (
        type(value) is not str
        or not value.isascii()
        or len(value) > 2048
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise CompetitorProvenanceError(f"{label} is invalid")
    match = _PINNED_IMAGE_RE.fullmatch(value)
    if match is None:
        raise CompetitorProvenanceError(
            f"{label} must pin the base as name@sha256:digest"
        )
    name = match.group("name")
    if ":" in name.rsplit("/", 1)[-1]:
        repository_name, tag = name.rsplit(":", 1)
        if not tag or _TAG_RE.fullmatch(tag) is None:
            raise CompetitorProvenanceError(f"{label} has an invalid tag")
    else:
        repository_name = name
    if len(repository_name) > 255:
        raise CompetitorProvenanceError(f"{label} repository name exceeds 255 bytes")
    components = repository_name.split("/")
    if not components or any(not component for component in components):
        raise CompetitorProvenanceError(f"{label} has an invalid repository name")
    first = components[0]
    path_components = components
    if "." in first or ":" in first or first == "localhost":
        registry = first
        path_components = components[1:]
        if not path_components:
            raise CompetitorProvenanceError(f"{label} has no repository path")
        if ":" in registry:
            host, port = registry.rsplit(":", 1)
            if not port.isdigit() or not 1 <= int(port) <= 65535:
                raise CompetitorProvenanceError(f"{label} has an invalid registry port")
        else:
            host = registry
        if host != "localhost" and any(
            _REGISTRY_LABEL_RE.fullmatch(part) is None for part in host.split(".")
        ):
            raise CompetitorProvenanceError(f"{label} has an invalid registry host")
    if any(
        _REPOSITORY_COMPONENT_RE.fullmatch(part) is None for part in path_components
    ):
        raise CompetitorProvenanceError(f"{label} has an invalid repository path")
    return value, match.group("digest")


def _dockerfile_base_references(path: Path, label: str) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CompetitorProvenanceError(f"{label} is not readable UTF-8") from exc
    references: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        if tokens[0].upper() != "FROM":
            continue
        if raw_line.rstrip().endswith("\\"):
            raise CompetitorProvenanceError(
                f"{label}:{line_number} uses an unsupported continued FROM"
            )
        index = 1
        if index < len(tokens) and tokens[index].startswith("--platform="):
            platform_value = tokens[index].removeprefix("--platform=")
            if (
                not platform_value.isascii()
                or _PLATFORM_RE.fullmatch(platform_value) is None
            ):
                raise CompetitorProvenanceError(
                    f"{label}:{line_number} has an invalid platform"
                )
            index += 1
        remaining = tokens[index:]
        if len(remaining) == 3 and remaining[1].upper() == "AS":
            image_value = remaining[0]
            alias = remaining[2]
            if not alias.isascii() or _STAGE_ALIAS_RE.fullmatch(alias) is None:
                raise CompetitorProvenanceError(
                    f"{label}:{line_number} has an invalid stage alias"
                )
        elif len(remaining) == 1:
            image_value = remaining[0]
        else:
            raise CompetitorProvenanceError(
                f"{label}:{line_number} has an unsupported FROM instruction"
            )
        reference, _ = _pinned_base_reference(
            image_value, f"{label}:{line_number} base reference"
        )
        references.append(reference)
    if not references:
        raise CompetitorProvenanceError(f"{label} contains no digest-pinned FROM")
    if len(set(references)) != len(references):
        raise CompetitorProvenanceError(f"{label} repeats a base image reference")
    return references


def _validate_receipt_base_images(
    value: dict[str, Any], solver: str
) -> list[dict[str, str]]:
    base_images = value["base_images"]
    if type(base_images) is not list or not base_images:
        raise CompetitorProvenanceError(
            f"{solver}.build.receipt.base_images must be non-empty"
        )
    normalized_images: list[dict[str, str]] = []
    seen_digests: set[str] = set()
    for index, raw in enumerate(base_images):
        item = _exact_object(
            raw,
            _BASE_IMAGE_KEYS,
            f"{solver}.build.receipt.base_images[{index}]",
        )
        reference, pinned_digest = _pinned_base_reference(
            item["reference"],
            f"{solver}.build.receipt.base_images[{index}].reference",
        )
        digest = _image_digest(
            item["digest"],
            f"{solver}.build.receipt.base_images[{index}].digest",
        )
        if digest != f"sha256:{pinned_digest}":
            raise CompetitorProvenanceError(
                f"{solver}.build.receipt.base_images[{index}] digest does not "
                "match its pinned reference"
            )
        if digest in seen_digests:
            raise CompetitorProvenanceError(
                f"{solver}.build.receipt.base_images contains a duplicate digest"
            )
        seen_digests.add(digest)
        normalized_images.append({"reference": reference, "digest": digest})
    return normalized_images


def _validate_receipt(
    receipt: dict[str, Any],
    *,
    solver: str,
    commit_sha: str,
    source_sha256: str,
    license_sha256: str,
    recipe_sha256: str,
    adapter_sha256: str,
    image_digest: str,
) -> dict[str, Any]:
    value = _exact_object(receipt, _RECEIPT_KEYS, f"{solver}.build.receipt")
    expected_scalars = {
        "schema": BUILD_RECEIPT_SCHEMA,
        "solver": solver,
        "upstream_commit": commit_sha,
        "source_archive_sha256": source_sha256,
        "license_sha256": license_sha256,
        "recipe_sha256": recipe_sha256,
        "adapter_sha256": adapter_sha256,
        "image_digest": image_digest,
        "network_mode": "none",
        "build_success": True,
    }
    for field, expected in expected_scalars.items():
        if type(value[field]) is not type(expected) or value[field] != expected:
            raise CompetitorProvenanceError(
                f"{solver}.build.receipt.{field} does not match its attestation"
            )
    normalized_images = _validate_receipt_base_images(value, solver)
    return {
        **expected_scalars,
        "base_images": normalized_images,
        "argv": _string_argv(value["argv"], f"{solver}.build.receipt.argv"),
    }


def _validate_receipt_v2(
    receipt: dict[str, Any],
    *,
    solver: str,
    upstreams: list[dict[str, Any]],
    recipe_sha256: str,
    adapter_sha256: str,
    image_digest: str,
) -> dict[str, Any]:
    value = _exact_object(receipt, _RECEIPT_V2_KEYS, f"{solver}.build.receipt")
    expected_scalars = {
        "schema": BUILD_RECEIPT_SCHEMA_V2,
        "solver": solver,
        "recipe_sha256": recipe_sha256,
        "adapter_sha256": adapter_sha256,
        "image_digest": image_digest,
        "network_mode": "none",
        "build_success": True,
    }
    for field, expected in expected_scalars.items():
        if type(value[field]) is not type(expected) or value[field] != expected:
            raise CompetitorProvenanceError(
                f"{solver}.build.receipt.{field} does not match its attestation"
            )
    if not provenance_bindings_match_exactly(value["upstreams"], upstreams):
        raise CompetitorProvenanceError(
            f"{solver}.build.receipt.upstreams do not exactly match the ordered "
            "manifest upstreams"
        )
    return {
        **expected_scalars,
        "upstreams": upstreams,
        "base_images": _validate_receipt_base_images(value, solver),
        "argv": _string_argv(value["argv"], f"{solver}.build.receipt.argv"),
    }


def verify_competitor_provenance(
    manifest_path: Path,
    *,
    expected_solvers: Sequence[str],
    selected_images: Mapping[str, str],
) -> dict[str, Any]:
    """Verify a packaged source-to-image chain without executing build artifacts."""

    if type(manifest_path) is not _PATH_TYPE:
        raise CompetitorProvenanceError("provenance manifest path has an invalid type")
    try:
        resolved_manifest = manifest_path.resolve(strict=True)
        if (
            not _same_lexical_and_resolved_path(manifest_path, resolved_manifest)
            or not resolved_manifest.is_file()
            or resolved_manifest.stat().st_nlink != 1
        ):
            raise CompetitorProvenanceError(
                "provenance manifest must be a regular file"
            )
        manifest_identity = _file_identity(resolved_manifest)
        root = resolved_manifest.parent.resolve(strict=True)
        manifest_payload, manifest_snapshot_sha256 = _read_plain_json(
            resolved_manifest, "provenance manifest"
        )
    except CompetitorProvenanceError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise CompetitorProvenanceError("provenance manifest does not exist") from exc
    manifest = _exact_object(
        manifest_payload,
        {"schema", "solvers"},
        "provenance manifest",
    )
    manifest_schema = manifest["schema"]
    if manifest_schema not in {PROVENANCE_SCHEMA, PROVENANCE_SCHEMA_V2}:
        raise CompetitorProvenanceError("unsupported provenance manifest schema")

    if (
        type(expected_solvers) not in {tuple, list}
        or not expected_solvers
        or any(
            type(item) is not str or _SOLVER_RE.fullmatch(item) is None
            for item in expected_solvers
        )
        or len(set(expected_solvers)) != len(expected_solvers)
    ):
        raise CompetitorProvenanceError("expected_solvers is invalid")
    if type(selected_images) is not dict:
        raise CompetitorProvenanceError("selected_images must be a plain object")
    expected_set = set(expected_solvers)
    if set(selected_images) != expected_set:
        raise CompetitorProvenanceError("selected image solver set mismatch")
    solvers = manifest["solvers"]
    if type(solvers) is not dict or set(solvers) != expected_set:
        raise CompetitorProvenanceError("provenance solver set mismatch")

    normalized: dict[str, Any] = {}
    used_paths: set[Path] = {resolved_manifest}
    attested_files: dict[
        Path,
        tuple[Path, str, tuple[int, int, int, int, int, int]],
    ] = {}
    for solver in expected_solvers:
        selected_image = _image_digest(
            selected_images[solver], f"{solver}.selected_image"
        )
        solver_keys = (
            _SOLVER_KEYS_V1 if manifest_schema == PROVENANCE_SCHEMA else _SOLVER_KEYS_V2
        )
        entry = _exact_object(solvers[solver], solver_keys, solver)
        custody_artifacts: list[
            tuple[
                Path,
                Path,
                str,
                tuple[int, int, int, int, int, int],
            ]
        ] = []
        source_binding: dict[str, Any]
        normalized_upstreams: list[dict[str, Any]] | None = None
        if manifest_schema == PROVENANCE_SCHEMA:
            upstream = _exact_object(
                entry["upstream"], _UPSTREAM_KEYS, f"{solver}.upstream"
            )
            repository_url = _repository_url(
                upstream["repository_url"], f"{solver}.upstream.repository_url"
            )
            commit_sha = upstream["commit_sha"]
            if type(commit_sha) is not str or _COMMIT_RE.fullmatch(commit_sha) is None:
                raise CompetitorProvenanceError(
                    f"{solver}.upstream.commit_sha must be a full lowercase commit hash"
                )
            source_lexical, source_path, source, source_identity = _attested_file(
                upstream["source_archive"],
                root=root,
                label=f"{solver}.upstream.source_archive",
            )
            license_item = _exact_object(
                entry["license"], _LICENSE_KEYS, f"{solver}.license"
            )
            spdx = license_item["spdx"]
            if type(spdx) is not str or spdx not in SUPPORTED_SPDX_LICENSES:
                raise CompetitorProvenanceError(f"{solver}.license.spdx is invalid")
            (
                license_lexical,
                license_path,
                license_file,
                license_identity,
            ) = _attested_file(
                {"path": license_item["path"], "sha256": license_item["sha256"]},
                root=root,
                label=f"{solver}.license",
            )
            custody_artifacts.extend(
                [
                    (
                        source_lexical,
                        source_path,
                        source["sha256"],
                        source_identity,
                    ),
                    (
                        license_lexical,
                        license_path,
                        license_file["sha256"],
                        license_identity,
                    ),
                ]
            )
            source_binding = {
                "upstream": {
                    "repository_url": repository_url,
                    "commit_sha": commit_sha,
                    "source_archive": source,
                },
                "license": {"spdx": spdx, **license_file},
            }
        else:
            raw_upstreams = entry["upstreams"]
            if type(raw_upstreams) is not list or not raw_upstreams:
                raise CompetitorProvenanceError(
                    f"{solver}.upstreams must be a non-empty ordered list"
                )
            normalized_upstreams = []
            seen_upstreams: set[tuple[str, str]] = set()
            seen_source_sha256: set[str] = set()
            for index, raw_upstream in enumerate(raw_upstreams):
                label = f"{solver}.upstreams[{index}]"
                upstream = _exact_object(raw_upstream, _UPSTREAM_V2_KEYS, label)
                repository_url = _repository_url(
                    upstream["repository_url"], f"{label}.repository_url"
                )
                commit_sha = upstream["commit_sha"]
                if (
                    type(commit_sha) is not str
                    or _COMMIT_RE.fullmatch(commit_sha) is None
                ):
                    raise CompetitorProvenanceError(
                        f"{label}.commit_sha must be a full lowercase commit hash"
                    )
                upstream_identity = (repository_url, commit_sha)
                if upstream_identity in seen_upstreams:
                    raise CompetitorProvenanceError(
                        f"{solver}.upstreams contains a duplicate upstream identity"
                    )
                seen_upstreams.add(upstream_identity)
                (
                    source_lexical,
                    source_path,
                    source,
                    source_identity,
                ) = _attested_sized_file(
                    upstream["source_archive"],
                    root=root,
                    label=f"{label}.source_archive",
                )
                source_sha256 = str(source["sha256"])
                if source_sha256 in seen_source_sha256:
                    raise CompetitorProvenanceError(
                        f"{solver}.upstreams contains a duplicate source archive"
                    )
                seen_source_sha256.add(source_sha256)
                license_item = _exact_object(
                    upstream["license"], _LICENSE_KEYS, f"{label}.license"
                )
                spdx = license_item["spdx"]
                if type(spdx) is not str or spdx not in SUPPORTED_SPDX_LICENSES:
                    raise CompetitorProvenanceError(f"{label}.license.spdx is invalid")
                (
                    license_lexical,
                    license_path,
                    license_file,
                    license_identity,
                ) = _attested_file(
                    {
                        "path": license_item["path"],
                        "sha256": license_item["sha256"],
                    },
                    root=root,
                    label=f"{label}.license",
                )
                custody_artifacts.extend(
                    [
                        (
                            source_lexical,
                            source_path,
                            source_sha256,
                            source_identity,
                        ),
                        (
                            license_lexical,
                            license_path,
                            license_file["sha256"],
                            license_identity,
                        ),
                    ]
                )
                normalized_upstreams.append(
                    {
                        "repository_url": repository_url,
                        "commit_sha": commit_sha,
                        "source_archive": source,
                        "license": {"spdx": spdx, **license_file},
                    }
                )
            source_binding = {"upstreams": normalized_upstreams}
        build = _exact_object(entry["build"], _BUILD_KEYS, f"{solver}.build")
        recipe_lexical, recipe_path, recipe, recipe_identity = _attested_file(
            build["recipe"], root=root, label=f"{solver}.build.recipe"
        )
        adapter_lexical, adapter_path, adapter, adapter_identity = _attested_file(
            build["adapter"], root=root, label=f"{solver}.build.adapter"
        )
        receipt_lexical, receipt_path, receipt_file, receipt_identity = _attested_file(
            build["receipt"], root=root, label=f"{solver}.build.receipt_file"
        )
        build_artifacts = [
            (recipe_lexical, recipe_path, recipe["sha256"], recipe_identity),
            (adapter_lexical, adapter_path, adapter["sha256"], adapter_identity),
            (
                receipt_lexical,
                receipt_path,
                receipt_file["sha256"],
                receipt_identity,
            ),
        ]
        for _, path, _, _ in [*custody_artifacts, *build_artifacts]:
            if path in used_paths:
                raise CompetitorProvenanceError(
                    f"{solver} reuses an artifact path already bound elsewhere"
                )
            used_paths.add(path)
        for lexical, path, digest, identity in [
            *custody_artifacts,
            *build_artifacts,
        ]:
            attested_files[lexical] = (path, digest, identity)
        image = _image_digest(entry["image_digest"], f"{solver}.image_digest")
        if image != selected_image:
            raise CompetitorProvenanceError(
                f"{solver}.image_digest does not match the controller image"
            )
        receipt_payload, _ = _read_plain_json(
            receipt_path,
            f"{solver}.build.receipt",
            expected_sha256=receipt_file["sha256"],
        )
        if manifest_schema == PROVENANCE_SCHEMA:
            receipt = _validate_receipt(
                receipt_payload,
                solver=solver,
                commit_sha=commit_sha,
                source_sha256=source["sha256"],
                license_sha256=license_file["sha256"],
                recipe_sha256=recipe["sha256"],
                adapter_sha256=adapter["sha256"],
                image_digest=image,
            )
        else:
            assert normalized_upstreams is not None
            receipt = _validate_receipt_v2(
                receipt_payload,
                solver=solver,
                upstreams=normalized_upstreams,
                recipe_sha256=recipe["sha256"],
                adapter_sha256=adapter["sha256"],
                image_digest=image,
            )
        recipe_base_references = _dockerfile_base_references(
            recipe_path, f"{solver}.build.recipe"
        )
        receipt_base_references = [item["reference"] for item in receipt["base_images"]]
        if receipt_base_references != recipe_base_references:
            raise CompetitorProvenanceError(
                f"{solver}.build.receipt.base_images do not match recipe FROM inputs"
            )
        normalized[solver] = {
            **source_binding,
            "build": {
                "recipe": recipe,
                "adapter": adapter,
                "receipt": receipt_file,
                "receipt_payload_sha256": _json_sha256(receipt),
            },
            "image_digest": image,
        }

    try:
        final_manifest = manifest_path.resolve(strict=True)
        if (
            not _same_lexical_and_resolved_path(manifest_path, final_manifest)
            or final_manifest != resolved_manifest
            or _is_link_or_reparse(manifest_path)
            or _file_identity(final_manifest) != manifest_identity
            or final_manifest.stat().st_nlink != 1
            or _sha256(final_manifest) != manifest_snapshot_sha256
        ):
            raise CompetitorProvenanceError(
                "provenance manifest changed during validation"
            )
        for lexical, (
            expected_resolved,
            expected_sha256,
            expected_identity,
        ) in attested_files.items():
            current_resolved = lexical.resolve(strict=True)
            if (
                _has_symlink_component(lexical, root)
                or not _same_lexical_and_resolved_path(lexical, current_resolved)
                or current_resolved != expected_resolved
                or not current_resolved.is_file()
                or current_resolved.stat().st_nlink != 1
                or _file_identity(current_resolved) != expected_identity
            ):
                raise CompetitorProvenanceError(
                    "an attested artifact changed file identity"
                )
            if _sha256(current_resolved) != expected_sha256:
                raise CompetitorProvenanceError(
                    "an attested artifact changed during validation"
                )
    except CompetitorProvenanceError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise CompetitorProvenanceError(
            "a custody path changed during validation"
        ) from exc

    canonical_binding = {
        "schema": manifest_schema,
        "manifest_sha256": manifest_snapshot_sha256,
        "solvers": normalized,
    }
    binding = {
        **canonical_binding,
        "binding_sha256": _json_sha256(canonical_binding),
        "manifest_path": str(resolved_manifest),
    }
    return binding


__all__ = [
    "BUILD_RECEIPT_SCHEMA",
    "BUILD_RECEIPT_SCHEMA_V2",
    "PROVENANCE_SCHEMA",
    "PROVENANCE_SCHEMA_V2",
    "SUPPORTED_SPDX_LICENSES",
    "CompetitorProvenanceError",
    "provenance_bindings_match_exactly",
    "verify_competitor_provenance",
]
