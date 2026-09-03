from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import tarfile
from typing import Any

import pytest

from benchmarks import itc2019_competitor_source_custody as custody
from benchmarks.itc2019_competitor_source_custody import (
    SOURCE_CUSTODY_MANIFEST_SCHEMA,
    SOURCE_CUSTODY_STATUS,
    SourceCustodyError,
    build_source_custody_manifest,
    create_source_custody_manifest,
    verify_source_custody_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _add_directory(archive: tarfile.TarFile, name: str) -> None:
    item = tarfile.TarInfo(name=name)
    item.type = tarfile.DIRTYPE
    item.mode = 0o755
    archive.addfile(item)


def _add_file(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    item = tarfile.TarInfo(name=name)
    item.mode = 0o644
    item.size = len(content)
    archive.addfile(item, BytesIO(content))


def _write_archive(
    path: Path,
    root: str,
    *,
    extra_member: tuple[str, bytes | None, bytes | None] | None = None,
    extra_pax_headers: dict[str, str] | None = None,
) -> None:
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        _add_directory(archive, root)
        _add_file(archive, f"{root}/LICENSE", b"license\n")
        _add_file(archive, f"{root}/pom.xml", b"<project/>\n")
        if extra_member is not None:
            name, content, member_type = extra_member
            item = tarfile.TarInfo(name=name)
            item.mode = 0o644
            item.pax_headers = dict(extra_pax_headers or {})
            if member_type is None:
                assert content is not None
                item.size = len(content)
                archive.addfile(item, BytesIO(content))
            else:
                item.type = member_type
                item.linkname = f"{root}/LICENSE"
                archive.addfile(item)


def _source(
    archive: Path,
    *,
    role: str,
    repository_url: str,
    commit_sha: str,
) -> dict[str, Any]:
    return {
        "role": role,
        "archive_path": archive.name,
        "archive_sha256": _sha256(archive),
        "archive_size_bytes": archive.stat().st_size,
        "commit_sha": commit_sha,
        "license_spdx": "LGPL-3.0-only",
        "repository_url": repository_url,
    }


def _policy_source(source: dict[str, Any], root: str) -> dict[str, Any]:
    return {
        "archive_path": source["archive_path"],
        "repository_url": source["repository_url"],
        "commit_sha": source["commit_sha"],
        "archive_root": root,
        "license_evidence": {
            "spdx": source["license_spdx"],
            "scope": custody.LICENSE_SCOPE,
            "members": ["LICENSE"],
        },
        "toolchain_intent": {
            "ecosystem": "java-maven",
            "status": custody.TOOLCHAIN_INTENT_STATUS,
            "descriptor_members": ["pom.xml"],
        },
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "custody"
    root.mkdir()
    extension_archive = root / "extension.tar.gz"
    core_archive = root / "core.tar.gz"
    _write_archive(extension_archive, "extension-root")
    _write_archive(core_archive, "core-root")
    extension = _source(
        extension_archive,
        role="primary",
        repository_url="https://github.com/example/extension",
        commit_sha="a" * 40,
    )
    core = _source(
        core_archive,
        role="required-source-dependency",
        repository_url="https://github.com/example/core",
        commit_sha="b" * 40,
    )
    inventory_payload = {
        "schema": custody.SOURCE_INVENTORY_SCHEMA,
        "claim_grade_ready": False,
        "solvers": [
            {
                "solver": "unitime-cpsolver",
                "sources": [extension, core],
            }
        ],
        "status": custody.SOURCE_INVENTORY_STATUS,
    }
    inventory = root / "source-inventory.json"
    inventory.write_text(json.dumps(inventory_payload), encoding="utf-8")
    policy_payload = {
        "schema": custody.SOURCE_CUSTODY_POLICY_SCHEMA,
        "source_inventory": {
            "path": inventory.name,
            "sha256": _sha256(inventory),
        },
        "claim_boundary": {
            "scope": custody.SOURCE_CUSTODY_SCOPE,
            "build_ready": False,
            "claim_grade_ready": False,
            "performance_claims_authorized": False,
            "statement": "Archive custody only; no build or performance claim.",
        },
        "solvers": [
            {
                "solver": "unitime-cpsolver",
                "sources": [
                    _policy_source(extension, "extension-root"),
                    _policy_source(core, "core-root"),
                ],
            }
        ],
    }
    policy = root / "source-custody-policy.json"
    policy.write_text(json.dumps(policy_payload), encoding="utf-8")
    manifest = root / "source-custody-manifest.json"
    return inventory, policy, manifest


def _rewrite_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _rebind_policy_inventory_hash(policy: Path, inventory: Path) -> None:
    _rewrite_json(
        policy,
        lambda payload: payload["source_inventory"].__setitem__(
            "sha256", _sha256(inventory)
        ),
    )


def test_real_vendored_archives_have_exact_ordered_custody() -> None:
    package_root = Path(custody.__file__).resolve().parent / "competitor_packages"
    manifest = build_source_custody_manifest(
        package_root / "source-inventory.json",
        package_root / "source-custody-policy.json",
    )
    replayed = verify_source_custody_manifest(
        package_root / "source-custody-manifest.json",
        inventory_path=package_root / "source-inventory.json",
        policy_path=package_root / "source-custody-policy.json",
    )

    assert replayed == manifest
    assert manifest["binding_sha256"] == (
        "c30affdb1a8f7d2866fbdd9b41c38f6cd577f6cc6435b407945ab8c432abc0ec"
    )
    assert manifest["schema"] == SOURCE_CUSTODY_MANIFEST_SCHEMA
    assert manifest["status"] == SOURCE_CUSTODY_STATUS
    assert manifest["claim_boundary"]["build_ready"] is False
    assert manifest["claim_boundary"]["claim_grade_ready"] is False
    assert manifest["claim_boundary"]["performance_claims_authorized"] is False
    assert [solver["solver"] for solver in manifest["solvers"]] == [
        "gashi-sa",
        "unitime-cpsolver",
        "lemos-maxsat",
    ]
    cpsolver_sources = manifest["solvers"][1]["sources"]
    assert [source["commit_sha"] for source in cpsolver_sources] == [
        "d1576ac94a8f7b6562e49f9476a89fb741cb226f",
        "3abbcaaf26d739d25e45c8e191b7ef94bc15cc26",
    ]
    assert [source["role"] for source in cpsolver_sources] == [
        "primary",
        "required-source-dependency",
    ]
    assert {
        source["archive"]["path"]: source["archive"]["sha256"]
        for solver in manifest["solvers"]
        for source in solver["sources"]
    } == {
        "gashi-b7b7110d1968758b0b7efe099e7f68aa7f19a4a0.tar.gz": (
            "d1ac7f6979c03f47fbc247ffb839288f18302963853e1935adfc5ed71480227b"
        ),
        "cpsolver-itc2019-d1576ac94a8f7b6562e49f9476a89fb741cb226f.tar.gz": (
            "a6b56f4c0017dc45cb6e3d3c0b0f46cabe06ab08f42ef2b43914280dec846484"
        ),
        "cpsolver-core-3abbcaaf26d739d25e45c8e191b7ef94bc15cc26.tar.gz": (
            "af9e8dd246a4f61675a85a0aa7e18296b921ee8524c9d4937bb7237650810f04"
        ),
        "lemos-c33d15797686a27c192eabb90948baa54d3ddef5.tar.gz": (
            "7f70b5c6b9f035a0e8b29069a641cb0f14c7e5f421f19a61a3c2b2397aa25cef"
        ),
    }
    assert [
        source["tree"]["member_identity_sha256"]
        for solver in manifest["solvers"]
        for source in solver["sources"]
    ] == [
        "f54b7a443a2ae1abeac96f2a7e043518001fed71c6fe7ff5ed66bff1fb6c6f84",
        "1d378de51003f8b76aa94ca60da95a89c7e6b8a30edc73eebd3b19c24f04326f",
        "38f08ba5d633650ff5e69018fe0158a1c9fab2512b46a220869196d832b7e9d1",
        "d4a32cd065f019ae71d0cf5b96425ae2d7350d32da8ea1481cf79c78bb2e063e",
    ]
    for solver in manifest["solvers"]:
        for source in solver["sources"]:
            assert len(source["tree"]["member_identity_sha256"]) == 64
            assert source["license_evidence"]["members"][0]["kind"] == "file"
            assert all(
                member["kind"] == "file"
                for member in source["toolchain_intent"]["descriptor_members"]
            )


def test_create_and_verify_are_deterministic_and_create_only(tmp_path: Path) -> None:
    inventory, policy, manifest = _fixture(tmp_path)
    expected = build_source_custody_manifest(inventory, policy)

    created = create_source_custody_manifest(
        manifest,
        inventory_path=inventory,
        policy_path=policy,
    )
    replayed = verify_source_custody_manifest(
        manifest,
        inventory_path=inventory,
        policy_path=policy,
    )

    assert created == expected == replayed
    with pytest.raises(SourceCustodyError, match="already exists"):
        create_source_custody_manifest(
            manifest,
            inventory_path=inventory,
            policy_path=policy,
        )


@pytest.mark.parametrize(
    "member_name",
    [
        "extension-root/../escape",
        "/extension-root/absolute",
        "extension-root\\backslash",
        "extension-root/control\x01",
        "extension-root/cafe\u0301",
        "extension-root/C:/drive",
        "extension-root/file.",
        "extension-root/NUL.txt",
    ],
)
def test_rejects_unsafe_or_non_normalized_archive_member_paths(
    tmp_path: Path, member_name: str
) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    _write_archive(archive, "extension-root", extra_member=(member_name, b"x", None))
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="unsafe archive member path"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_duplicate_archive_member_path(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    _write_archive(
        archive,
        "extension-root",
        extra_member=("extension-root/LICENSE", b"duplicate", None),
    )
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="duplicate member path"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_case_insensitive_archive_member_collision(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    _write_archive(
        archive,
        "extension-root",
        extra_member=("extension-root/license", b"collision", None),
    )
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="case-insensitive"):
        build_source_custody_manifest(inventory, policy)


@pytest.mark.parametrize(
    "member_type",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CONTTYPE,
        tarfile.GNUTYPE_SPARSE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
    ],
)
def test_rejects_non_regular_archive_member_types(
    tmp_path: Path, member_type: bytes
) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    _write_archive(
        archive,
        "extension-root",
        extra_member=("extension-root/alias", None, member_type),
    )
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="unsupported"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_sparse_pax_metadata_on_directory_member(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    _write_archive(
        archive,
        "extension-root",
        extra_member=("extension-root/sparse-directory", None, tarfile.DIRTYPE),
        extra_pax_headers={"GNU.sparse.map": "0,0"},
    )
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="unsupported sparse metadata"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_sparse_pax_metadata_on_root_directory(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    with tarfile.open(archive, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        root = tarfile.TarInfo(name="extension-root")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        root.pax_headers = {"GNU.sparse.map": "0,0"}
        tar.addfile(root)
        _add_file(tar, "extension-root/LICENSE", b"license\n")
        _add_file(tar, "extension-root/pom.xml", b"<project/>\n")
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="unsupported sparse metadata"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_sparse_pax_metadata_on_regular_member(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    _write_archive(
        archive,
        "extension-root",
        extra_member=("extension-root/sparse", b"x", None),
        extra_pax_headers={"GNU.sparse.map": "0,1"},
    )
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="unsupported sparse metadata"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_wrong_archive_root_even_when_inventory_is_rebound(
    tmp_path: Path,
) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    _write_archive(archive, "lookalike-root")
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].update(
            archive_sha256=_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="outside the expected root"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_archive_byte_drift_against_inventory(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"drift")

    with pytest.raises(SourceCustodyError, match="archive attestation mismatch"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_policy_source_order_confusion(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    _rewrite_json(
        policy,
        lambda payload: payload["solvers"][0]["sources"].reverse(),
    )

    with pytest.raises(SourceCustodyError, match="upstream identity/order mismatch"):
        build_source_custody_manifest(inventory, policy)


@pytest.mark.parametrize("wrong_value", [True, 1.0])
def test_rejects_inventory_archive_size_type_confusion(
    tmp_path: Path, wrong_value: bool | float
) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    _rewrite_json(
        inventory,
        lambda payload: payload["solvers"][0]["sources"][0].__setitem__(
            "archive_size_bytes", wrong_value
        ),
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="archive_size_bytes is invalid"):
        build_source_custody_manifest(inventory, policy)


@pytest.mark.parametrize("wrong_value", [True, 2.0])
def test_replay_rejects_nested_tree_number_type_confusion(
    tmp_path: Path, wrong_value: bool | float
) -> None:
    inventory, policy, manifest = _fixture(tmp_path)
    create_source_custody_manifest(
        manifest,
        inventory_path=inventory,
        policy_path=policy,
    )
    _rewrite_json(
        manifest,
        lambda payload: payload["solvers"][0]["sources"][0]["tree"].__setitem__(
            "member_count", wrong_value
        ),
    )

    with pytest.raises(SourceCustodyError, match="does not exactly match"):
        verify_source_custody_manifest(
            manifest,
            inventory_path=inventory,
            policy_path=policy,
        )


def test_replay_rejects_source_order_confusion(tmp_path: Path) -> None:
    inventory, policy, manifest = _fixture(tmp_path)
    create_source_custody_manifest(
        manifest,
        inventory_path=inventory,
        policy_path=policy,
    )
    _rewrite_json(
        manifest,
        lambda payload: payload["solvers"][0]["sources"].reverse(),
    )

    with pytest.raises(SourceCustodyError, match="does not exactly match"):
        verify_source_custody_manifest(
            manifest,
            inventory_path=inventory,
            policy_path=policy,
        )


def test_replay_rejects_selected_member_identity_confusion(tmp_path: Path) -> None:
    inventory, policy, manifest = _fixture(tmp_path)
    create_source_custody_manifest(
        manifest,
        inventory_path=inventory,
        policy_path=policy,
    )
    _rewrite_json(
        manifest,
        lambda payload: payload["solvers"][0]["sources"][0]["license_evidence"][
            "members"
        ][0].__setitem__("path", "pom.xml"),
    )

    with pytest.raises(SourceCustodyError, match="does not exactly match"):
        verify_source_custody_manifest(
            manifest,
            inventory_path=inventory,
            policy_path=policy,
        )


def test_rejects_duplicate_json_member(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    encoded = inventory.read_text(encoding="utf-8")
    inventory.write_text(
        encoded.replace(
            '"claim_grade_ready": false',
            '"claim_grade_ready": false, "claim_grade_ready": false',
            1,
        ),
        encoding="utf-8",
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="duplicate JSON member"):
        build_source_custody_manifest(inventory, policy)


def test_rejects_nonstandard_json_constant(tmp_path: Path) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    encoded = inventory.read_text(encoding="utf-8")
    inventory.write_text(
        encoded.replace('"claim_grade_ready": false', '"claim_grade_ready": NaN', 1),
        encoding="utf-8",
    )
    _rebind_policy_inventory_hash(policy, inventory)

    with pytest.raises(SourceCustodyError, match="non-standard JSON constant"):
        build_source_custody_manifest(inventory, policy)


def test_final_replay_rejects_same_byte_archive_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory, policy, _ = _fixture(tmp_path)
    archive = inventory.parent / "extension.tar.gz"
    original_scan = custody._scan_archive
    replaced = False

    def replace_after_scan(path: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal replaced
        result = original_scan(path, **kwargs)
        if path == archive.resolve() and not replaced:
            replacement = archive.with_suffix(".replacement")
            replacement.write_bytes(archive.read_bytes())
            os.replace(replacement, archive)
            replaced = True
        return result

    monkeypatch.setattr(custody, "_scan_archive", replace_after_scan)

    with pytest.raises(SourceCustodyError, match="changed file identity"):
        build_source_custody_manifest(inventory, policy)


def test_interrupted_create_cleans_temporary_file_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory, policy, manifest = _fixture(tmp_path)

    with monkeypatch.context() as context:

        def fail_fsync(_descriptor: int) -> None:
            raise OSError("injected fsync failure")

        context.setattr(custody.os, "fsync", fail_fsync)
        with pytest.raises(SourceCustodyError, match="could not be created"):
            create_source_custody_manifest(
                manifest,
                inventory_path=inventory,
                policy_path=policy,
            )

    assert not manifest.exists()
    assert not list(manifest.parent.glob(f".{manifest.name}.*.tmp"))
    created = create_source_custody_manifest(
        manifest,
        inventory_path=inventory,
        policy_path=policy,
    )
    assert created["schema"] == SOURCE_CUSTODY_MANIFEST_SCHEMA


def test_post_link_identity_failure_cleans_publication_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory, policy, manifest = _fixture(tmp_path)
    original_identity = custody._file_identity
    injected = False

    with monkeypatch.context() as context:

        def fail_first_published_identity(path: Path):
            nonlocal injected
            if path == manifest.resolve() and not injected:
                injected = True
                raise OSError("injected identity failure")
            return original_identity(path)

        context.setattr(custody, "_file_identity", fail_first_published_identity)
        with pytest.raises(SourceCustodyError, match="could not be created"):
            create_source_custody_manifest(
                manifest,
                inventory_path=inventory,
                policy_path=policy,
            )

    assert injected
    assert not manifest.exists()
    assert not list(manifest.parent.glob(f".{manifest.name}.*.tmp"))
    created = create_source_custody_manifest(
        manifest,
        inventory_path=inventory,
        policy_path=policy,
    )
    assert created["schema"] == SOURCE_CUSTODY_MANIFEST_SCHEMA
