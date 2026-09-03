from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


POLICY_SCHEMA = "planora.itc2019.competitor-build-closure-policy.v1"
MANIFEST_SCHEMA = "planora.itc2019.competitor-build-closure-manifest.v1"
STATUS = "BUILD_CLOSURE_INVENTORIED_NOT_BUILD_READY"
CUSTODY_BINDING_SHA256 = (
    "c30affdb1a8f7d2866fbdd9b41c38f6cd577f6cc6435b407945ab8c432abc0ec"
)
BUILD_ADMISSION_BINDING_SHA256 = (
    "56be3ad100e604ee1e858396d85e692c6a7d3ac809ec8230945c38b2ff45c2c1"
)
CLAIM_SCOPE = "TOOLCHAIN_DEPENDENCY_INVENTORY_ONLY_NO_BUILD_AUTHORIZATION"
CLASSIFICATIONS = {"pinned-present", "mutable-unverified", "missing"}

MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_DECLARED_BYTES = 384 * 1024 * 1024
MAX_DECOMPRESSION_RATIO = 40
MAX_PATH_BYTES = 512
MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_DESCRIPTOR_TOTAL_BYTES = 512 * 1024

PREDECESSORS = (
    (
        "build-admission-implementation",
        "benchmarks/itc2019_competitor_build_admission.py",
        25424,
        "e6226ff541ba275417252ea3dff6bf8b1325c2463c710bf8957c53aedd2981c8",
    ),
    (
        "build-admission-tests",
        "tests/test_itc2019_competitor_build_admission.py",
        13578,
        "19b23c9528e6b12a1e841850e935b3e724fc7302ba0cfd1e5ab04965ebc06349",
    ),
    (
        "build-admission-policy",
        "benchmarks/competitor_packages/build-admission-policy.json",
        15706,
        "a3eead9b0c8883487b9c5cdee7507a994a3d3b2f7fa733118c34739057f80192",
    ),
    (
        "build-admission-documentation",
        "benchmarks/competitor_packages/BUILD_ADMISSION.md",
        1739,
        "d53fb49651a43591d85edc92dad1b192a0f4ddf951541edefd6a7bd917696675",
    ),
    (
        "build-admission-manifest",
        "benchmarks/competitor_packages/build-admission-manifest.json",
        7453,
        "60097eee95ed15d15cd4c8be082c759fbf1ac08e7279a8688e1f85560af87205",
    ),
)

ARCHIVES = {
    "gashi": (
        "benchmarks/competitor_packages/"
        "gashi-b7b7110d1968758b0b7efe099e7f68aa7f19a4a0.tar.gz",
        43232,
        "d1ac7f6979c03f47fbc247ffb839288f18302963853e1935adfc5ed71480227b",
    ),
    "unitime-extension": (
        "benchmarks/competitor_packages/"
        "cpsolver-itc2019-d1576ac94a8f7b6562e49f9476a89fb741cb226f.tar.gz",
        19377,
        "a6b56f4c0017dc45cb6e3d3c0b0f46cabe06ab08f42ef2b43914280dec846484",
    ),
    "unitime-core": (
        "benchmarks/competitor_packages/"
        "cpsolver-core-3abbcaaf26d739d25e45c8e191b7ef94bc15cc26.tar.gz",
        3243399,
        "af9e8dd246a4f61675a85a0aa7e18296b921ee8524c9d4937bb7237650810f04",
    ),
    "lemos": (
        "benchmarks/competitor_packages/"
        "lemos-c33d15797686a27c192eabb90948baa54d3ddef5.tar.gz",
        12909097,
        "7f70b5c6b9f035a0e8b29069a641cb0f14c7e5f421f19a61a3c2b2397aa25cef",
    ),
}

SOLVER_CONTRACTS: tuple[
    tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], ...
] = (
    (
        "gashi-sa",
        ("gashi-cli", "gashi-common", "gashi-internal", "gashi-make"),
        (
            ("gashi-source", "pinned-present"),
            ("gashi-dotnet-sdk", "missing"),
            ("gashi-argu", "missing"),
            ("gashi-fsharp-core", "missing"),
            ("gashi-netstandard-reference", "missing"),
            ("gashi-linux-x64-runtime-pack", "missing"),
            ("gashi-msbuild-restore-closure", "missing"),
            ("gashi-make-coreutils", "missing"),
            ("gashi-linux-native-runtime", "missing"),
        ),
    ),
    (
        "unitime-cpsolver",
        ("unitime-extension-pom", "unitime-core-pom"),
        (
            ("unitime-extension-source", "pinned-present"),
            ("unitime-core-source", "pinned-present"),
            ("unitime-dom4j", "pinned-present"),
            ("unitime-log4j-api", "pinned-present"),
            ("unitime-log4j-core", "pinned-present"),
            ("unitime-jdk", "missing"),
            ("unitime-maven", "missing"),
            ("unitime-extension-plugins", "mutable-unverified"),
            ("unitime-core-lifecycle-plugins", "missing"),
            ("unitime-declared-nonphase-plugins", "missing"),
            ("unitime-wagon-ftp", "missing"),
            ("unitime-maven-transitives", "missing"),
            ("unitime-linux-runtime", "missing"),
        ),
    ),
    (
        "lemos-maxsat",
        ("lemos-make", "lemos-glucose-template", "lemos-glucose-config"),
        (
            ("lemos-source", "pinned-present"),
            ("lemos-glucose41-core", "pinned-present"),
            ("lemos-gnu-make", "missing"),
            ("lemos-gxx", "missing"),
            ("lemos-binutils", "missing"),
            ("lemos-gmp", "missing"),
            ("lemos-zlib", "missing"),
            ("lemos-pthread", "missing"),
            ("lemos-cxx-runtime", "missing"),
            ("lemos-posix-build-utilities", "missing"),
            ("lemos-linux-rootfs", "missing"),
        ),
    ),
)

PINNED_REQUIREMENT_ARCHIVES = {
    "gashi-source": "gashi",
    "unitime-extension-source": "unitime-extension",
    "unitime-core-source": "unitime-core",
    "unitime-dom4j": "unitime-core",
    "unitime-log4j-api": "unitime-core",
    "unitime-log4j-core": "unitime-core",
    "lemos-source": "lemos",
    "lemos-glucose41-core": "lemos",
}

_PATH_TYPE = type(Path())
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


class BuildClosureError(ValueError):
    """Raised when the fail-closed closure inventory cannot be replayed."""


def _sha256_bytes(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


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
    return _sha256_bytes(encoded)


def _manifest_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")


def _strict_json(encoded: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BuildClosureError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise BuildClosureError(f"{label} contains non-standard constant {value!r}")

    try:
        value = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildClosureError(f"{label} is not strict UTF-8 JSON") from exc
    if type(value) is not dict:
        raise BuildClosureError(f"{label} must contain an object")
    return value


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise BuildClosureError(f"{label} must be a plain string-keyed object")
    if set(value) != keys:
        raise BuildClosureError(f"{label} keys do not exactly match the schema")
    return value


def _normalized_path(value: Any, label: str) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise BuildClosureError(f"{label} must be a normalized POSIX path")
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise BuildClosureError(f"{label} exceeds the path byte limit")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BuildClosureError(f"{label} must remain relative")
    if path.as_posix() != value or ":" in path.parts[0]:
        raise BuildClosureError(f"{label} is not lexically normalized")
    return value


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


def _is_link_or_reparse(path: Path) -> bool:
    stat_result = path.lstat()
    junction = getattr(path, "is_junction", None)
    return bool(
        path.is_symlink()
        or (callable(junction) and junction())
        or getattr(stat_result, "st_file_attributes", 0) & 0x400
    )


TrackedFile = tuple[Path, str, int, tuple[int, int, int, int, int, int, int]]


def _attest_regular(path: Path, label: str) -> TrackedFile:
    if type(path) is not _PATH_TYPE:
        raise BuildClosureError(f"{label} path has an invalid type")
    try:
        lexical = Path(os.path.abspath(os.fspath(path)))
        resolved = path.resolve(strict=True)
        if (
            os.path.normcase(str(lexical)) != os.path.normcase(str(resolved))
            or _is_link_or_reparse(path)
            or not resolved.is_file()
            or resolved.stat().st_nlink != 1
        ):
            raise BuildClosureError(
                f"{label} must be a regular non-linked single-name file"
            )
        before = _identity(resolved)
        digest = _sha256(resolved)
        after = _identity(resolved)
    except BuildClosureError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuildClosureError(f"{label} is unavailable") from exc
    if before != after:
        raise BuildClosureError(f"{label} changed during attestation")
    return resolved, digest, before[3], before


def _read_tracked(tracked: TrackedFile, label: str) -> bytes:
    path, digest, size, identity = tracked
    try:
        before = _identity(path)
        encoded = path.read_bytes()
        after = _identity(path)
    except OSError as exc:
        raise BuildClosureError(f"{label} became unavailable") from exc
    if (
        before != identity
        or after != identity
        or len(encoded) != size
        or _sha256_bytes(encoded) != digest
    ):
        raise BuildClosureError(f"{label} changed during read")
    return encoded


def _attest_pin(root: Path, path: str, size: int, digest: str, label: str) -> bytes:
    relative = _normalized_path(path, f"{label}.path")
    tracked = _attest_regular(root / Path(*PurePosixPath(relative).parts), label)
    if tracked[1] != digest or tracked[2] != size:
        raise BuildClosureError(f"{label} size or SHA-256 does not match")
    return _read_tracked(tracked, label)


def _archive_member_path(name: str) -> str:
    return _normalized_path(name, "archive member path")


def inspect_archive_bytes(
    encoded: bytes,
    descriptor_paths: Sequence[str],
    *,
    metadata_paths: Sequence[str] = (),
    label: str = "archive",
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Inspect metadata and selected regular members without extracting to disk."""
    if type(encoded) is not bytes or not encoded or len(encoded) > MAX_ARCHIVE_BYTES:
        raise BuildClosureError(f"{label} violates the compressed-size limit")
    wanted = tuple(
        _normalized_path(path, "descriptor path") for path in descriptor_paths
    )
    metadata_wanted = tuple(
        _normalized_path(path, "metadata-only path") for path in metadata_paths
    )
    if len(set(wanted)) != len(wanted):
        raise BuildClosureError(f"{label} descriptor request contains duplicates")
    if len(set(metadata_wanted)) != len(metadata_wanted):
        raise BuildClosureError(f"{label} metadata request contains duplicates")

    try:
        archive = tarfile.open(fileobj=io.BytesIO(encoded), mode="r:gz")
        members = archive.getmembers()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BuildClosureError(f"{label} is not a valid gzip-compressed tar") from exc

    if not members or len(members) > MAX_MEMBERS:
        raise BuildClosureError(f"{label} violates the member-count limit")
    names: set[str] = set()
    folded_names: set[str] = set()
    regular: dict[str, tarfile.TarInfo] = {}
    total = 0
    for member in members:
        name = _archive_member_path(member.name)
        folded = name.casefold()
        if name in names or folded in folded_names:
            raise BuildClosureError(f"{label} contains duplicate or ambiguous paths")
        names.add(name)
        folded_names.add(folded)
        if member.issym() or member.islnk():
            raise BuildClosureError(f"{label} contains a symbolic or hard link")
        if not (member.isfile() or member.isdir()):
            raise BuildClosureError(f"{label} contains an unsupported member type")
        if member.size < 0 or member.size > MAX_MEMBER_BYTES:
            raise BuildClosureError(f"{label} violates the member-size limit")
        if member.isfile():
            total += member.size
            regular[name] = member
    if total > MAX_TOTAL_DECLARED_BYTES:
        raise BuildClosureError(f"{label} violates the declared-size limit")
    if total > len(encoded) * MAX_DECOMPRESSION_RATIO:
        raise BuildClosureError(f"{label} violates the decompression-ratio limit")

    selected: dict[str, bytes] = {}
    selected_total = 0
    try:
        for path in wanted:
            member = regular.get(path)
            if member is None:
                raise BuildClosureError(f"{label} descriptor {path!r} is missing")
            if member.size > MAX_DESCRIPTOR_BYTES:
                raise BuildClosureError(f"{label} descriptor exceeds its size limit")
            stream = archive.extractfile(member)
            if stream is None:
                raise BuildClosureError(f"{label} descriptor is not readable")
            content = stream.read(member.size + 1)
            if len(content) != member.size:
                raise BuildClosureError(f"{label} descriptor size is inconsistent")
            selected_total += len(content)
            if selected_total > MAX_DESCRIPTOR_TOTAL_BYTES:
                raise BuildClosureError(f"{label} descriptors exceed their total limit")
            selected[path] = content
    except (tarfile.TarError, OSError) as exc:
        raise BuildClosureError(f"{label} descriptor read failed") from exc
    finally:
        archive.close()

    metadata = {
        "compressed_size_bytes": len(encoded),
        "member_count": len(members),
        "regular_file_count": len(regular),
        "total_declared_regular_bytes": total,
        "descriptor_total_bytes": selected_total,
        "requested_member_sizes": [
            {"path": path, "size_bytes": regular[path].size}
            for path in metadata_wanted
            if path in regular
        ],
    }
    if len(metadata["requested_member_sizes"]) != len(metadata_wanted):
        raise BuildClosureError(f"{label} required metadata-only member is missing")
    return metadata, selected


def _decode_descriptor(encoded: bytes, label: str) -> str:
    if b"\x00" in encoded:
        raise BuildClosureError(f"{label} contains NUL bytes")
    try:
        text = encoded.decode("utf-8-sig")
    except UnicodeError as exc:
        raise BuildClosureError(f"{label} is not UTF-8") from exc
    if not text:
        raise BuildClosureError(f"{label} is empty")
    return text


def _xml_root(encoded: bytes, label: str) -> ET.Element:
    upper = encoded.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise BuildClosureError(f"{label} contains a forbidden XML declaration")
    try:
        return ET.fromstring(encoded)
    except ET.ParseError as exc:
        raise BuildClosureError(f"{label} is malformed XML") from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ET.Element, name: str, default: str = "") -> str:
    for child in node:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return default


def _msbuild_facts(encoded: bytes, label: str) -> dict[str, Any]:
    root = _xml_root(encoded, label)
    if _local_name(root.tag) != "Project":
        raise BuildClosureError(f"{label} is not an MSBuild project")
    properties: dict[str, str] = {}
    projects: list[str] = []
    packages: list[dict[str, str]] = []
    for node in root.iter():
        name = _local_name(node.tag)
        if name in {"TargetFramework", "OutputType", "LangVersion"}:
            value = (node.text or "").strip()
            if value:
                properties[name] = value
        elif name == "ProjectReference":
            projects.append(node.attrib.get("Include", ""))
        elif name == "PackageReference":
            packages.append(
                {
                    "id": node.attrib.get("Include", ""),
                    "version": node.attrib.get("Version", ""),
                }
            )
    return {
        "sdk": root.attrib.get("Sdk", ""),
        "properties": dict(sorted(properties.items())),
        "project_references": sorted(projects),
        "package_references": sorted(
            packages, key=lambda item: (item["id"], item["version"])
        ),
    }


def _coordinate(node: ET.Element) -> dict[str, str]:
    return {
        "group_id": _child_text(node, "groupId"),
        "artifact_id": _child_text(node, "artifactId"),
        "version": _child_text(node, "version"),
    }


def _pom_facts(encoded: bytes, label: str) -> dict[str, Any]:
    root = _xml_root(encoded, label)
    if _local_name(root.tag) != "project":
        raise BuildClosureError(f"{label} is not a Maven POM")
    dependencies: list[dict[str, str]] = []
    plugins: list[dict[str, Any]] = []
    extensions: list[dict[str, str]] = []
    repositories: list[str] = []
    compiler: dict[str, str] = {}
    for parent in root.iter():
        parent_name = _local_name(parent.tag)
        if parent_name == "repository":
            url = _child_text(parent, "url")
            if url:
                repositories.append(url)
    # ElementTree has no parent links; walk the explicit top-level and build sections.
    for child in root:
        if _local_name(child.tag) == "dependencies":
            dependencies.extend(
                _coordinate(item)
                for item in child
                if _local_name(item.tag) == "dependency"
            )
        if _local_name(child.tag) == "build":
            for build_child in child:
                if _local_name(build_child.tag) == "plugins":
                    for plugin in build_child:
                        if _local_name(plugin.tag) != "plugin":
                            continue
                        item: dict[str, Any] = _coordinate(plugin)
                        item["plugin_dependencies"] = []
                        for plugin_child in plugin:
                            if _local_name(plugin_child.tag) == "dependencies":
                                item["plugin_dependencies"] = [
                                    _coordinate(dep)
                                    for dep in plugin_child
                                    if _local_name(dep.tag) == "dependency"
                                ]
                            if _local_name(plugin_child.tag) == "configuration":
                                source = _child_text(plugin_child, "source")
                                target = _child_text(plugin_child, "target")
                                if source:
                                    compiler["source"] = source
                                if target:
                                    compiler["target"] = target
                        plugins.append(item)
                if _local_name(build_child.tag) == "extensions":
                    extensions.extend(
                        _coordinate(ext)
                        for ext in build_child
                        if _local_name(ext.tag) == "extension"
                    )
    return {
        "project": {
            "group_id": _child_text(root, "groupId"),
            "artifact_id": _child_text(root, "artifactId"),
            "version": _child_text(root, "version"),
            "packaging": _child_text(root, "packaging", "jar"),
        },
        "dependencies": sorted(
            dependencies,
            key=lambda item: (item["group_id"], item["artifact_id"], item["version"]),
        ),
        "build_plugins": plugins,
        "build_extensions": extensions,
        "compiler": compiler,
        "repositories": sorted(set(repositories)),
    }


def _make_facts(encoded: bytes, label: str) -> dict[str, Any]:
    text = _decode_descriptor(encoded, label)
    assignments: list[dict[str, str]] = []
    targets: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)\s*([:?+]?=)\s*(.*?)\s*$", line)
        if match:
            key, operator, value = match.groups()
            if key in {
                "VERSION",
                "SOLVERNAME",
                "SOLVERDIR",
                "NSPACE",
                "EXEC",
                "DEPDIR",
                "LFLAGS",
                "CFLAGS",
                "CXX",
            }:
                assignments.append({"name": key, "operator": operator, "value": value})
            continue
        if not line.startswith((" ", "\t")) and ":" in line:
            target = line.split(":", 1)[0].strip()
            if target and "$" not in target and "%" not in target:
                targets.extend(target.split())
    tokens = sorted(
        tool
        for tool in {"dotnet", "g++", "ar", "sed", "rm", "ln", "pwd"}
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(tool)}(?![A-Za-z0-9_])", text)
    )
    libraries = sorted(set(re.findall(r"-l([A-Za-z0-9_+.-]+)", text)))
    publish_rids = sorted(
        set(re.findall(r"dotnet\s+publish\b[^\r\n]*?\s-r\s+([^\s]+)", text))
    )
    return {
        "assignments": assignments,
        "targets": sorted(set(targets)),
        "tool_tokens": tokens,
        "link_libraries": libraries,
        "dotnet_publish_rids": publish_rids,
        "dotnet_self_contained": bool(publish_rids and "--self-contained" in text),
    }


PARSERS = {"msbuild": _msbuild_facts, "maven-pom": _pom_facts, "make": _make_facts}


def _validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    value = _exact(
        policy,
        {
            "schema",
            "custody_binding_sha256",
            "build_admission_binding_sha256",
            "reviewed_predecessors",
            "claim_boundary",
            "archive_descriptors",
            "solvers",
            "local_observations",
            "acquisition_contract",
        },
        "closure policy",
    )
    if value["schema"] != POLICY_SCHEMA:
        raise BuildClosureError("unsupported closure policy schema")
    if value["custody_binding_sha256"] != CUSTODY_BINDING_SHA256:
        raise BuildClosureError("custody binding drifted")
    if value["build_admission_binding_sha256"] != BUILD_ADMISSION_BINDING_SHA256:
        raise BuildClosureError("build-admission binding drifted")
    expected_predecessors = [
        {"role": role, "path": path, "size_bytes": size, "sha256": digest}
        for role, path, size, digest in PREDECESSORS
    ]
    if value["reviewed_predecessors"] != expected_predecessors:
        raise BuildClosureError("reviewed predecessor set drifted")
    boundary = _exact(
        value["claim_boundary"],
        {
            "scope",
            "build_ready",
            "claim_grade_ready",
            "performance_claims_authorized",
            "statement",
        },
        "claim boundary",
    )
    if (
        boundary["scope"] != CLAIM_SCOPE
        or boundary["build_ready"] is not False
        or boundary["claim_grade_ready"] is not False
        or boundary["performance_claims_authorized"] is not False
        or type(boundary["statement"]) is not str
        or not boundary["statement"]
    ):
        raise BuildClosureError("claim boundary must remain explicitly false")

    descriptors = value["archive_descriptors"]
    if type(descriptors) is not list or not descriptors:
        raise BuildClosureError("archive descriptor inventory is empty")
    seen_descriptor_ids: set[str] = set()
    descriptor_ids_in_order: list[str] = []
    for descriptor in descriptors:
        item = _exact(
            descriptor,
            {"id", "archive", "path", "format", "size_bytes", "sha256", "facts"},
            "archive descriptor",
        )
        if (
            type(item["id"]) is not str
            or _ID_RE.fullmatch(item["id"]) is None
            or item["id"] in seen_descriptor_ids
            or item["archive"] not in ARCHIVES
            or item["format"] not in PARSERS
            or type(item["size_bytes"]) is not int
            or not 0 < item["size_bytes"] <= MAX_DESCRIPTOR_BYTES
            or type(item["sha256"]) is not str
            or _SHA256_RE.fullmatch(item["sha256"]) is None
            or type(item["facts"]) is not dict
        ):
            raise BuildClosureError("archive descriptor record is invalid")
        _normalized_path(item["path"], "archive descriptor path")
        seen_descriptor_ids.add(item["id"])
        descriptor_ids_in_order.append(item["id"])

    expected_descriptor_ids = tuple(
        descriptor_id
        for _solver, descriptor_ids, _requirements in SOLVER_CONTRACTS
        for descriptor_id in descriptor_ids
    )
    if tuple(descriptor_ids_in_order) != expected_descriptor_ids:
        raise BuildClosureError("archive descriptor inventory drifted")

    solvers = value["solvers"]
    expected_solver_ids = [
        solver for solver, _descriptors, _requirements in SOLVER_CONTRACTS
    ]
    if (
        type(solvers) is not list
        or [item.get("solver") for item in solvers if type(item) is dict]
        != expected_solver_ids
    ):
        raise BuildClosureError("solver closure order or identity drifted")
    contracts_by_solver = {
        solver: (descriptor_ids, requirements)
        for solver, descriptor_ids, requirements in SOLVER_CONTRACTS
    }
    all_requirements: set[str] = set()
    for solver in solvers:
        entry = _exact(
            solver, {"solver", "descriptor_ids", "requirements"}, "solver closure"
        )
        expected_solver_descriptors, expected_requirements = contracts_by_solver[
            entry["solver"]
        ]
        descriptor_ids = entry["descriptor_ids"]
        if (
            type(descriptor_ids) is not list
            or not descriptor_ids
            or len(set(descriptor_ids)) != len(descriptor_ids)
            or not set(descriptor_ids) <= seen_descriptor_ids
        ):
            raise BuildClosureError("solver descriptor references are invalid")
        if tuple(descriptor_ids) != expected_solver_descriptors:
            raise BuildClosureError("solver descriptor inventory drifted")
        requirements = entry["requirements"]
        if type(requirements) is not list or not requirements:
            raise BuildClosureError("solver requirement inventory is empty")
        observed_requirements: list[tuple[str, str]] = []
        for requirement in requirements:
            req = _exact(
                requirement,
                {
                    "id",
                    "kind",
                    "coordinate",
                    "version",
                    "classification",
                    "evidence",
                    "acquisition",
                },
                "closure requirement",
            )
            if (
                type(req["id"]) is not str
                or _ID_RE.fullmatch(req["id"]) is None
                or req["id"] in all_requirements
                or type(req["kind"]) is not str
                or not req["kind"]
                or type(req["coordinate"]) is not str
                or not req["coordinate"]
                or (type(req["version"]) is not str and req["version"] is not None)
                or req["classification"] not in CLASSIFICATIONS
                or type(req["evidence"]) is not dict
            ):
                raise BuildClosureError("closure requirement is invalid")
            acquisition = _exact(
                req["acquisition"],
                {
                    "canonical_coordinates",
                    "candidate_sources",
                    "expected_sha256",
                    "expected_size_bytes",
                    "license_review_required",
                    "provenance_review_required",
                },
                "acquisition metadata",
            )
            if (
                type(acquisition["canonical_coordinates"]) is not str
                or not acquisition["canonical_coordinates"]
                or type(acquisition["candidate_sources"]) is not list
                or any(
                    type(source) is not str or not source
                    for source in acquisition["candidate_sources"]
                )
                or (
                    acquisition["expected_sha256"] is not None
                    and (
                        type(acquisition["expected_sha256"]) is not str
                        or _SHA256_RE.fullmatch(acquisition["expected_sha256"]) is None
                    )
                )
                or (
                    acquisition["expected_size_bytes"] is not None
                    and (
                        type(acquisition["expected_size_bytes"]) is not int
                        or acquisition["expected_size_bytes"] <= 0
                    )
                )
                or type(acquisition["license_review_required"]) is not bool
                or type(acquisition["provenance_review_required"]) is not bool
            ):
                raise BuildClosureError("acquisition metadata is invalid")
            if acquisition["license_review_required"] is not True:
                raise BuildClosureError("license review must remain required")
            if req["classification"] == "pinned-present":
                archive_id = PINNED_REQUIREMENT_ARCHIVES.get(req["id"])
                if archive_id is None:
                    raise BuildClosureError(
                        "pinned-present requirement identity is not authorized"
                    )
                _archive_path, archive_size, archive_sha256 = ARCHIVES[archive_id]
                if (
                    acquisition["expected_sha256"] is None
                    or acquisition["expected_size_bytes"] is None
                ):
                    raise BuildClosureError(
                        "pinned-present requirement lacks immutable identity"
                    )
                if (
                    req["evidence"].get("archive") != archive_id
                    or acquisition["expected_sha256"] != archive_sha256
                    or acquisition["expected_size_bytes"] != archive_size
                ):
                    raise BuildClosureError(
                        "pinned-present requirement archive binding drifted"
                    )
            elif (
                acquisition["expected_sha256"] is not None
                or acquisition["expected_size_bytes"] is not None
            ):
                raise BuildClosureError(
                    "untrusted requirement cannot carry an expected identity"
                )
            elif (
                not acquisition["candidate_sources"]
                or acquisition["provenance_review_required"] is not True
            ):
                raise BuildClosureError(
                    "unresolved requirement must retain candidate sources and provenance review"
                )
            all_requirements.add(req["id"])
            observed_requirements.append((req["id"], req["classification"]))
        if tuple(observed_requirements) != expected_requirements:
            raise BuildClosureError("solver requirement inventory drifted")

    observations = _exact(
        value["local_observations"],
        {"scope", "docker", "host_tools", "package_caches"},
        "local observations",
    )
    if observations["scope"] != "READ_ONLY_NON_CLAIM_GRADE_SNAPSHOT":
        raise BuildClosureError("local observation scope drifted")
    if (
        type(observations["docker"]) is not dict
        or type(observations["host_tools"]) is not list
        or type(observations["package_caches"]) is not list
    ):
        raise BuildClosureError("local observations are malformed")
    for collection in (observations["host_tools"], observations["package_caches"]):
        for item in collection:
            if type(item) is not dict or item.get("classification") not in {
                "mutable-unverified",
                "missing",
            }:
                raise BuildClosureError("local observations must never be claim-grade")
    docker = observations["docker"]
    if (
        docker.get("classification") not in {"mutable-unverified", "missing"}
        or docker.get("trusted_for_closure") is not False
    ):
        raise BuildClosureError("Docker observation must remain untrusted")

    acquisition = _exact(
        value["acquisition_contract"],
        {"network_access_authorized", "next_actions", "required_fields"},
        "acquisition contract",
    )
    if acquisition["network_access_authorized"] is not False:
        raise BuildClosureError("network acquisition must remain unauthorized")
    for key in ("next_actions", "required_fields"):
        if (
            type(acquisition[key]) is not list
            or not acquisition[key]
            or any(type(item) is not str or not item for item in acquisition[key])
        ):
            raise BuildClosureError("acquisition contract list is invalid")
    return value


def _descriptor_inventory(
    root: Path, policy: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_archive: dict[str, list[dict[str, Any]]] = {key: [] for key in ARCHIVES}
    for descriptor in policy["archive_descriptors"]:
        by_archive[descriptor["archive"]].append(descriptor)
    metadata_by_archive: dict[str, dict[str, int]] = {key: {} for key in ARCHIVES}
    for solver in policy["solvers"]:
        for requirement in solver["requirements"]:
            evidence = requirement["evidence"]
            archive_id = evidence.get("archive")
            member_path = evidence.get("member_path")
            member_size = evidence.get("member_size_bytes")
            if member_path is None:
                continue
            if (
                archive_id not in ARCHIVES
                or type(member_path) is not str
                or type(member_size) is not int
                or member_size <= 0
            ):
                raise BuildClosureError("archive-member evidence is invalid")
            _normalized_path(member_path, "archive-member evidence path")
            prior = metadata_by_archive[archive_id].setdefault(member_path, member_size)
            if prior != member_size:
                raise BuildClosureError("archive-member evidence size conflicts")

    archive_inventory: list[dict[str, Any]] = []
    descriptor_inventory: list[dict[str, Any]] = []
    for archive_id, (path, size, digest) in ARCHIVES.items():
        encoded = _attest_pin(root, path, size, digest, f"source archive {archive_id}")
        descriptors = by_archive[archive_id]
        metadata, selected = inspect_archive_bytes(
            encoded,
            [item["path"] for item in descriptors],
            metadata_paths=sorted(metadata_by_archive[archive_id]),
            label=f"source archive {archive_id}",
        )
        actual_metadata = {
            item["path"]: item["size_bytes"]
            for item in metadata["requested_member_sizes"]
        }
        if actual_metadata != metadata_by_archive[archive_id]:
            raise BuildClosureError(
                f"source archive {archive_id} member metadata drifted"
            )
        archive_inventory.append(
            {
                "id": archive_id,
                "path": path,
                "size_bytes": size,
                "sha256": digest,
                **metadata,
            }
        )
        for item in descriptors:
            content = selected[item["path"]]
            if (
                len(content) != item["size_bytes"]
                or _sha256_bytes(content) != item["sha256"]
            ):
                raise BuildClosureError(f"descriptor {item['id']} identity drifted")
            facts = PARSERS[item["format"]](content, f"descriptor {item['id']}")
            if facts != item["facts"]:
                raise BuildClosureError(
                    f"descriptor {item['id']} semantic facts drifted"
                )
            descriptor_inventory.append(
                {
                    "id": item["id"],
                    "archive": archive_id,
                    "path": item["path"],
                    "format": item["format"],
                    "size_bytes": len(content),
                    "sha256": _sha256_bytes(content),
                    "facts_sha256": _json_sha256(facts),
                }
            )
    return archive_inventory, descriptor_inventory


def build_manifest(root: Path, policy_path: Path) -> dict[str, Any]:
    policy_tracked = _attest_regular(policy_path, "closure policy")
    policy_bytes = _read_tracked(policy_tracked, "closure policy")
    policy = _validate_policy(_strict_json(policy_bytes, "closure policy"))

    reviewed = []
    for role, path, size, digest in PREDECESSORS:
        _attest_pin(root, path, size, digest, role)
        reviewed.append(
            {"role": role, "path": path, "size_bytes": size, "sha256": digest}
        )

    archives, descriptors = _descriptor_inventory(root, policy)
    solver_inventory = []
    for solver in policy["solvers"]:
        counts = Counter(item["classification"] for item in solver["requirements"])
        solver_inventory.append(
            {
                "solver": solver["solver"],
                "descriptor_ids": solver["descriptor_ids"],
                "requirements": solver["requirements"],
                "classification_counts": {
                    key: counts.get(key, 0) for key in sorted(CLASSIFICATIONS)
                },
                "closure_complete": False,
                "build_ready": False,
            }
        )

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "policy": {
            "path": "build-closure-policy.json",
            "size_bytes": policy_tracked[2],
            "sha256": policy_tracked[1],
        },
        "custody_binding_sha256": CUSTODY_BINDING_SHA256,
        "build_admission_binding_sha256": BUILD_ADMISSION_BINDING_SHA256,
        "reviewed_predecessors": reviewed,
        "archive_inventory": archives,
        "descriptor_inventory": descriptors,
        "solvers": solver_inventory,
        "local_observations": policy["local_observations"],
        "acquisition_contract": policy["acquisition_contract"],
        "claim_boundary": policy["claim_boundary"],
        "build_ready": False,
        "claim_grade_ready": False,
        "performance_claims_authorized": False,
        "status": STATUS,
    }
    manifest["binding_sha256"] = _json_sha256(manifest)
    return manifest


def verify(root: Path) -> dict[str, Any]:
    policy_path = root / "benchmarks/competitor_packages/build-closure-policy.json"
    manifest_path = root / "benchmarks/competitor_packages/build-closure-manifest.json"
    expected = build_manifest(root, policy_path)
    manifest_tracked = _attest_regular(manifest_path, "closure manifest")
    manifest = _strict_json(
        _read_tracked(manifest_tracked, "closure manifest"), "closure manifest"
    )
    if manifest != expected:
        raise BuildClosureError("closure manifest does not replay exactly")
    return manifest


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay the fail-closed FOSS build-closure inventory"
    )
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument(
        "--emit-manifest",
        action="store_true",
        help="emit the deterministic expected manifest without writing it",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    policy_path = root / "benchmarks/competitor_packages/build-closure-policy.json"
    if args.emit_manifest:
        print(
            _manifest_bytes(build_manifest(root, policy_path)).decode("utf-8"), end=""
        )
        return 0
    manifest = verify(root)
    counts = Counter(
        requirement["classification"]
        for solver in manifest["solvers"]
        for requirement in solver["requirements"]
    )
    print(f"status={manifest['status']}")
    print(f"custody_binding_sha256={manifest['custody_binding_sha256']}")
    print(
        f"build_admission_binding_sha256={manifest['build_admission_binding_sha256']}"
    )
    print(f"pinned_present={counts['pinned-present']}")
    print(f"mutable_unverified={counts['mutable-unverified']}")
    print(f"missing={counts['missing']}")
    print("build_ready=false")
    print("claim_grade_ready=false")
    print("performance_claims_authorized=false")
    print(f"binding_sha256={manifest['binding_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
