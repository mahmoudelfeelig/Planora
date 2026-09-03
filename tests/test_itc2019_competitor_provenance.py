from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from benchmarks.itc2019_competitor_provenance import (
    BUILD_RECEIPT_SCHEMA,
    BUILD_RECEIPT_SCHEMA_V2,
    PROVENANCE_SCHEMA,
    PROVENANCE_SCHEMA_V2,
    CompetitorProvenanceError,
    verify_competitor_provenance,
)
from benchmarks import itc2019_competitor_provenance as provenance


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: bytes) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return {"path": path.relative_to(path.parents[1]).as_posix(), "sha256": _sha(path)}


def _write_sized(path: Path, value: bytes) -> dict[str, str | int]:
    item = _write(path, value)
    return {**item, "size_bytes": path.stat().st_size}


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    solver = "gashi-sa"
    root = tmp_path / "custody"
    source = _write(root / solver / "source.tar", b"source")
    license_file = _write(root / solver / "LICENSE", b"MIT\n")
    base_reference = "example/runtime@sha256:" + "c" * 64
    recipe = _write(root / solver / "Dockerfile", f"FROM {base_reference}\n".encode())
    adapter = _write(root / solver / "solver-adapter", b"#!/bin/sh\n")
    image = "sha256:" + "a" * 64
    commit = "b" * 40
    receipt_payload = {
        "schema": BUILD_RECEIPT_SCHEMA,
        "solver": solver,
        "upstream_commit": commit,
        "source_archive_sha256": source["sha256"],
        "license_sha256": license_file["sha256"],
        "recipe_sha256": recipe["sha256"],
        "adapter_sha256": adapter["sha256"],
        "image_digest": image,
        "base_images": [{"reference": base_reference, "digest": "sha256:" + "c" * 64}],
        "argv": ["docker", "build", "--network=none", "."],
        "network_mode": "none",
        "build_success": True,
    }
    receipt_path = root / solver / "build-receipt.json"
    receipt_path.write_text(json.dumps(receipt_payload), encoding="utf-8")
    receipt = {
        "path": receipt_path.relative_to(root).as_posix(),
        "sha256": _sha(receipt_path),
    }
    manifest = {
        "schema": PROVENANCE_SCHEMA,
        "solvers": {
            solver: {
                "upstream": {
                    "repository_url": "https://github.com/example/solver",
                    "commit_sha": commit,
                    "source_archive": source,
                },
                "license": {"spdx": "MIT", **license_file},
                "build": {
                    "recipe": recipe,
                    "adapter": adapter,
                    "receipt": receipt,
                },
                "image_digest": image,
            }
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, {solver: image}


def _fixture_v2(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    solver = "unitime-cpsolver"
    root = tmp_path / "custody-v2"
    extension_source = _write_sized(root / solver / "extension.tar", b"x")
    extension_license = _write(root / solver / "LICENSE-extension", b"LGPL\n")
    core_source = _write_sized(root / solver / "core.tar", b"y")
    core_license = _write(root / solver / "LICENSE-core", b"LGPL\n")
    upstreams = [
        {
            "repository_url": "https://github.com/tomas-muller/cpsolver-itc2019",
            "commit_sha": "d1576ac94a8f7b6562e49f9476a89fb741cb226f",
            "source_archive": extension_source,
            "license": {"spdx": "LGPL-3.0-only", **extension_license},
        },
        {
            "repository_url": "https://github.com/UniTime/cpsolver",
            "commit_sha": "3abbcaaf26d739d25e45c8e191b7ef94bc15cc26",
            "source_archive": core_source,
            "license": {"spdx": "LGPL-3.0-only", **core_license},
        },
    ]
    base_reference = "example/runtime@sha256:" + "c" * 64
    recipe = _write(root / solver / "Dockerfile", f"FROM {base_reference}\n".encode())
    adapter = _write(root / solver / "solver-adapter", b"#!/bin/sh\n")
    image = "sha256:" + "a" * 64
    receipt_payload = {
        "schema": BUILD_RECEIPT_SCHEMA_V2,
        "solver": solver,
        "upstreams": upstreams,
        "recipe_sha256": recipe["sha256"],
        "adapter_sha256": adapter["sha256"],
        "image_digest": image,
        "base_images": [{"reference": base_reference, "digest": "sha256:" + "c" * 64}],
        "argv": ["docker", "build", "--network=none", "."],
        "network_mode": "none",
        "build_success": True,
    }
    receipt_path = root / solver / "build-receipt.json"
    receipt_path.write_text(json.dumps(receipt_payload), encoding="utf-8")
    receipt = {
        "path": receipt_path.relative_to(root).as_posix(),
        "sha256": _sha(receipt_path),
    }
    manifest = {
        "schema": PROVENANCE_SCHEMA_V2,
        "solvers": {
            solver: {
                "upstreams": upstreams,
                "build": {
                    "recipe": recipe,
                    "adapter": adapter,
                    "receipt": receipt,
                },
                "image_digest": image,
            }
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, {solver: image}


def _replace_recipe_and_rebind(manifest: Path, line: str) -> None:
    recipe = manifest.parent / "gashi-sa" / "Dockerfile"
    recipe.write_text(line, encoding="utf-8")
    receipt_path = manifest.parent / "gashi-sa" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["recipe_sha256"] = _sha(recipe)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["build"]["recipe"]["sha256"] = _sha(recipe)
    payload["solvers"]["gashi-sa"]["build"]["receipt"]["sha256"] = _sha(receipt_path)
    manifest.write_text(json.dumps(payload), encoding="utf-8")


def test_verifies_complete_source_to_image_chain(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    result = verify_competitor_provenance(
        manifest,
        expected_solvers=("gashi-sa",),
        selected_images=images,
    )
    assert result["schema"] == PROVENANCE_SCHEMA
    assert len(result["binding_sha256"]) == 64
    assert result["solvers"]["gashi-sa"]["image_digest"] == images["gashi-sa"]


def test_v2_verifies_exact_ordered_multi_upstream_source_chain(
    tmp_path: Path,
) -> None:
    manifest, images = _fixture_v2(tmp_path)
    result = verify_competitor_provenance(
        manifest,
        expected_solvers=("unitime-cpsolver",),
        selected_images=images,
    )

    assert result["schema"] == PROVENANCE_SCHEMA_V2
    upstreams = result["solvers"]["unitime-cpsolver"]["upstreams"]
    assert [item["commit_sha"] for item in upstreams] == [
        "d1576ac94a8f7b6562e49f9476a89fb741cb226f",
        "3abbcaaf26d739d25e45c8e191b7ef94bc15cc26",
    ]
    assert [item["source_archive"]["size_bytes"] for item in upstreams] == [1, 1]


def test_v2_accepts_one_upstream_without_weakening_v1_compatibility(
    tmp_path: Path,
) -> None:
    manifest, images = _fixture_v2(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["unitime-cpsolver"]["upstreams"].pop()
    receipt_path = manifest.parent / "unitime-cpsolver" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["upstreams"].pop()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload["solvers"]["unitime-cpsolver"]["build"]["receipt"]["sha256"] = _sha(
        receipt_path
    )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = verify_competitor_provenance(
        manifest,
        expected_solvers=("unitime-cpsolver",),
        selected_images=images,
    )
    assert len(result["solvers"]["unitime-cpsolver"]["upstreams"]) == 1


@pytest.mark.parametrize(
    "receipt_mutation",
    (
        "reverse",
        "drop",
        "repository",
        "commit",
        "archive-hash",
        "archive-size",
        "license-spdx",
        "license-hash",
    ),
)
def test_v2_rejects_non_exact_receipt_upstream_reconciliation(
    tmp_path: Path, receipt_mutation: str
) -> None:
    manifest, images = _fixture_v2(tmp_path)
    receipt_path = manifest.parent / "unitime-cpsolver" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt_mutation == "reverse":
        receipt["upstreams"].reverse()
    elif receipt_mutation == "drop":
        receipt["upstreams"].pop()
    elif receipt_mutation == "repository":
        receipt["upstreams"][1]["repository_url"] = "https://github.com/example/other"
    elif receipt_mutation == "commit":
        receipt["upstreams"][1]["commit_sha"] = "e" * 40
    elif receipt_mutation == "archive-hash":
        receipt["upstreams"][1]["source_archive"]["sha256"] = "f" * 64
    elif receipt_mutation == "archive-size":
        receipt["upstreams"][1]["source_archive"]["size_bytes"] = 2
    elif receipt_mutation == "license-spdx":
        receipt["upstreams"][1]["license"]["spdx"] = "MIT"
    else:
        receipt["upstreams"][1]["license"]["sha256"] = "f" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["unitime-cpsolver"]["build"]["receipt"]["sha256"] = _sha(
        receipt_path
    )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CompetitorProvenanceError, match="upstreams"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("unitime-cpsolver",),
            selected_images=images,
        )


def test_v2_rejects_duplicate_upstream_identity(tmp_path: Path) -> None:
    manifest, images = _fixture_v2(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    first, second = payload["solvers"]["unitime-cpsolver"]["upstreams"]
    second["repository_url"] = first["repository_url"]
    second["commit_sha"] = first["commit_sha"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CompetitorProvenanceError, match="duplicate upstream"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("unitime-cpsolver",),
            selected_images=images,
        )


def test_v2_rejects_duplicate_source_archive_digest(tmp_path: Path) -> None:
    manifest, images = _fixture_v2(tmp_path)
    solver_root = manifest.parent / "unitime-cpsolver"
    extension_archive = solver_root / "extension.tar"
    core_archive = solver_root / "core.tar"
    core_archive.write_bytes(extension_archive.read_bytes())
    duplicate_sha256 = _sha(core_archive)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    receipt_path = solver_root / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for upstreams in (
        payload["solvers"]["unitime-cpsolver"]["upstreams"],
        receipt["upstreams"],
    ):
        upstreams[1]["source_archive"]["sha256"] = duplicate_sha256
        upstreams[1]["source_archive"]["size_bytes"] = core_archive.stat().st_size
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload["solvers"]["unitime-cpsolver"]["build"]["receipt"]["sha256"] = _sha(
        receipt_path
    )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CompetitorProvenanceError, match="duplicate source archive"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("unitime-cpsolver",),
            selected_images=images,
        )


def test_v2_rejects_empty_upstream_list(tmp_path: Path) -> None:
    manifest, images = _fixture_v2(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["unitime-cpsolver"]["upstreams"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CompetitorProvenanceError, match="non-empty"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("unitime-cpsolver",),
            selected_images=images,
        )


@pytest.mark.parametrize("target", ("manifest", "receipt"))
def test_v2_rejects_bool_for_archive_size_without_int_coercion(
    tmp_path: Path, target: str
) -> None:
    manifest, images = _fixture_v2(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    receipt_path = manifest.parent / "unitime-cpsolver" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if target == "manifest":
        payload["solvers"]["unitime-cpsolver"]["upstreams"][0]["source_archive"][
            "size_bytes"
        ] = True
    else:
        receipt["upstreams"][0]["source_archive"]["size_bytes"] = True
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        payload["solvers"]["unitime-cpsolver"]["build"]["receipt"]["sha256"] = _sha(
            receipt_path
        )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CompetitorProvenanceError, match="size_bytes|upstreams"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("unitime-cpsolver",),
            selected_images=images,
        )


def test_v2_rejects_archive_size_drift_even_when_hash_is_rebound(
    tmp_path: Path,
) -> None:
    manifest, images = _fixture_v2(tmp_path)
    archive = manifest.parent / "unitime-cpsolver" / "core.tar"
    archive.write_bytes(b"changed")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["unitime-cpsolver"]["upstreams"][1]["source_archive"][
        "sha256"
    ] = _sha(archive)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CompetitorProvenanceError, match="size_bytes"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("unitime-cpsolver",),
            selected_images=images,
        )


def test_v2_binding_hash_is_package_location_independent(tmp_path: Path) -> None:
    manifest, images = _fixture_v2(tmp_path)
    copied_root = tmp_path / "copy-v2"
    shutil.copytree(manifest.parent, copied_root)
    first = verify_competitor_provenance(
        manifest,
        expected_solvers=("unitime-cpsolver",),
        selected_images=images,
    )
    second = verify_competitor_provenance(
        copied_root / "manifest.json",
        expected_solvers=("unitime-cpsolver",),
        selected_images=images,
    )

    assert first["manifest_path"] != second["manifest_path"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["binding_sha256"] == second["binding_sha256"]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda payload: payload.update(schema="wrong"), "schema"),
        (lambda payload: payload.update(extra=True), "keys mismatch"),
        (
            lambda payload: payload["solvers"]["gashi-sa"]["upstream"].update(
                repository_url="http://github.com/example/solver"
            ),
            "HTTPS",
        ),
        (
            lambda payload: payload["solvers"]["gashi-sa"]["upstream"].update(
                commit_sha="short"
            ),
            "commit",
        ),
        (
            lambda payload: payload["solvers"]["gashi-sa"]["license"].update(
                spdx="MIT OR GPL"
            ),
            "spdx",
        ),
        (
            lambda payload: payload["solvers"]["gashi-sa"].update(
                image_digest="sha256:" + "d" * 64
            ),
            "controller image",
        ),
    ],
)
def test_rejects_manifest_mutations(tmp_path: Path, mutate, match: str) -> None:
    manifest, images = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    mutate(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match=match):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_artifact_hash_drift(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    (manifest.parent / "gashi-sa" / "solver-adapter").write_bytes(b"changed")
    with pytest.raises(CompetitorProvenanceError, match="sha256 mismatch"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("network_mode", "default", "network_mode"),
        ("build_success", False, "build_success"),
        ("upstream_commit", "d" * 40, "upstream_commit"),
        ("image_digest", "sha256:" + "d" * 64, "image_digest"),
        ("base_images", [], "base_images"),
        ("argv", ["docker", "bad\narg"], "invalid argument"),
    ],
)
def test_rejects_build_receipt_mutations(
    tmp_path: Path, field: str, value, match: str
) -> None:
    manifest, images = _fixture(tmp_path)
    receipt_path = manifest.parent / "gashi-sa" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt[field] = value
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["solvers"]["gashi-sa"]["build"]["receipt"]["sha256"] = _sha(
        receipt_path
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match=match):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_missing_or_extra_solver(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    with pytest.raises(CompetitorProvenanceError, match="solver set mismatch"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa", "unitime-cpsolver"),
            selected_images={**images, "unitime-cpsolver": "sha256:" + "e" * 64},
        )


def test_rejects_path_escape_and_symlink(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["license"]["path"] = "../outside"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="normalized"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_hard_linked_artifact(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    adapter = manifest.parent / "gashi-sa" / "solver-adapter"
    os.link(adapter, manifest.parent / "gashi-sa" / "adapter-alias")
    with pytest.raises(CompetitorProvenanceError, match="hard-linked"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_manifest_snapshot_drift(tmp_path: Path, monkeypatch) -> None:
    manifest, images = _fixture(tmp_path)
    original = provenance._sha256

    def drifted(path: Path) -> str:
        if path == manifest.resolve():
            return "0" * 64
        return original(path)

    monkeypatch.setattr(provenance, "_sha256", drifted)
    with pytest.raises(CompetitorProvenanceError, match="changed during validation"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_duplicate_manifest_json_member(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    text = manifest.read_text(encoding="utf-8")
    text = text.replace(
        f'"schema": "{PROVENANCE_SCHEMA}"',
        f'"schema": "wrong", "schema": "{PROVENANCE_SCHEMA}"',
        1,
    )
    manifest.write_text(text, encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="duplicate JSON member"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_duplicate_receipt_json_member(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    receipt_path = manifest.parent / "gashi-sa" / "build-receipt.json"
    text = receipt_path.read_text(encoding="utf-8")
    text = text.replace(
        '"network_mode": "none"',
        '"network_mode": "default", "network_mode": "none"',
        1,
    )
    receipt_path.write_text(text, encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["build"]["receipt"]["sha256"] = _sha(receipt_path)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="duplicate JSON member"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_hard_linked_manifest(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    os.link(manifest, manifest.with_name("manifest-alias.json"))
    with pytest.raises(CompetitorProvenanceError, match="regular file"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_same_byte_artifact_identity_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    manifest, images = _fixture(tmp_path)
    adapter = manifest.parent / "gashi-sa" / "solver-adapter"
    original = provenance._dockerfile_base_references

    def replace_adapter(path: Path, label: str) -> list[str]:
        replacement = adapter.with_suffix(".replacement")
        replacement.write_bytes(adapter.read_bytes())
        os.replace(replacement, adapter)
        return original(path, label)

    monkeypatch.setattr(provenance, "_dockerfile_base_references", replace_adapter)
    with pytest.raises(CompetitorProvenanceError, match="file identity"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


@pytest.mark.parametrize(
    "recipe_line",
    [
        "FROM ubuntu:latest\n",
        "FROM ubuntu@sha256:" + "d" * 64 + "\n",
        "FROM ${BASE_IMAGE}\n",
    ],
)
def test_rejects_unbound_or_mutable_recipe_base(
    tmp_path: Path, recipe_line: str
) -> None:
    manifest, images = _fixture(tmp_path)
    recipe = manifest.parent / "gashi-sa" / "Dockerfile"
    recipe.write_text(recipe_line, encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["build"]["recipe"]["sha256"] = _sha(recipe)
    receipt_path = manifest.parent / "gashi-sa" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["recipe_sha256"] = _sha(recipe)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload["solvers"]["gashi-sa"]["build"]["receipt"]["sha256"] = _sha(receipt_path)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="pin|match"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_invented_spdx_identifier(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["license"]["spdx"] = "Definitely-Not-An-SPDX-License"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="spdx"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_binding_hash_is_package_location_independent(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    copied_root = tmp_path / "copy"
    shutil.copytree(manifest.parent, copied_root)
    first = verify_competitor_provenance(
        manifest,
        expected_solvers=("gashi-sa",),
        selected_images=images,
    )
    second = verify_competitor_provenance(
        copied_root / "manifest.json",
        expected_solvers=("gashi-sa",),
        selected_images=images,
    )
    assert first["manifest_path"] != second["manifest_path"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["binding_sha256"] == second["binding_sha256"]


@pytest.mark.parametrize(
    "repository_url",
    [
        "https://example.com/repo\x00suffix",
        "https://[malformed/repo",
        "https://example.com/repo\x7f",
        "https://example.com:abc/repo",
        "https://example.com:65536/repo",
        "https://[::1]:abc/repo",
        "https://example.com\\evil/repo",
        "https://Example.com/repo",
        "https://example.com//repo",
        "https://example.com/repo/../other",
        "https://example.com/repo%2fother",
    ],
)
def test_rejects_malformed_repository_url(tmp_path: Path, repository_url: str) -> None:
    manifest, images = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["upstream"]["repository_url"] = repository_url
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


@pytest.mark.parametrize(
    "repository_url",
    [
        "https://example.com:1/repo",
        "https://example.com:65535/repo.git",
        "https://127.0.0.1/repo",
        "https://[::1]:443/repo",
    ],
)
def test_accepts_normalized_repository_authority(
    tmp_path: Path, repository_url: str
) -> None:
    manifest, images = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["upstream"]["repository_url"] = repository_url
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    result = verify_competitor_provenance(
        manifest,
        expected_solvers=("gashi-sa",),
        selected_images=images,
    )
    assert result["solvers"]["gashi-sa"]["upstream"]["repository_url"] == (
        repository_url
    )


def test_rejects_hostile_manifest_path_without_accessing_it(tmp_path: Path) -> None:
    _, images = _fixture(tmp_path)

    class HostilePath:
        def __getattribute__(self, _name: str):
            raise RuntimeError("must not access hostile path")

    with pytest.raises(CompetitorProvenanceError, match="invalid type"):
        verify_competitor_provenance(  # type: ignore[arg-type]
            HostilePath(),
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


@pytest.mark.parametrize(
    "reference",
    [
        "https://registry.example.com/repo@sha256:" + "c" * 64,
        "registry.example.com/Upper/repo@sha256:" + "c" * 64,
        "registry.example.com//repo@sha256:" + "c" * 64,
        "registry.example.com:port/repo@sha256:" + "c" * 64,
        "registry.example.com/repo:@sha256:" + "c" * 64,
    ],
)
def test_rejects_invalid_docker_reference(tmp_path: Path, reference: str) -> None:
    manifest, images = _fixture(tmp_path)
    recipe = manifest.parent / "gashi-sa" / "Dockerfile"
    recipe.write_text(f"FROM {reference}\n", encoding="utf-8")
    receipt_path = manifest.parent / "gashi-sa" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["recipe_sha256"] = _sha(recipe)
    receipt["base_images"] = [{"reference": reference, "digest": "sha256:" + "c" * 64}]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["build"]["recipe"]["sha256"] = _sha(recipe)
    payload["solvers"]["gashi-sa"]["build"]["receipt"]["sha256"] = _sha(receipt_path)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="invalid|pin"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


@pytest.mark.parametrize("control", ["\u0085", "\u202e"])
def test_rejects_unicode_control_or_format_in_argv(
    tmp_path: Path, control: str
) -> None:
    manifest, images = _fixture(tmp_path)
    receipt_path = manifest.parent / "gashi-sa" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["argv"].append(f"spoof{control}argument")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["build"]["receipt"]["sha256"] = _sha(receipt_path)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="invalid argument"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_manifest_removal_race_uses_public_error_contract(
    tmp_path: Path, monkeypatch
) -> None:
    manifest, images = _fixture(tmp_path)
    original = provenance._dockerfile_base_references

    def remove_manifest(path: Path, label: str) -> list[str]:
        result = original(path, label)
        manifest.unlink()
        return result

    monkeypatch.setattr(provenance, "_dockerfile_base_references", remove_manifest)
    with pytest.raises(CompetitorProvenanceError, match="custody path changed"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_artifact_parent_symlink_swap_is_rejected(tmp_path: Path, monkeypatch) -> None:
    manifest, images = _fixture(tmp_path)
    solver_directory = manifest.parent / "gashi-sa"
    moved_directory = manifest.parent / "gashi-sa-moved"
    original = provenance._dockerfile_base_references

    def swap_parent(path: Path, label: str) -> list[str]:
        result = original(path, label)
        solver_directory.rename(moved_directory)
        try:
            solver_directory.symlink_to(moved_directory, target_is_directory=True)
        except OSError as exc:
            moved_directory.rename(solver_directory)
            pytest.skip(f"directory symlinks unavailable: {exc}")
        return result

    monkeypatch.setattr(provenance, "_dockerfile_base_references", swap_parent)
    with pytest.raises(CompetitorProvenanceError, match="file identity"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_rejects_repository_name_over_255_bytes(tmp_path: Path) -> None:
    manifest, images = _fixture(tmp_path)
    reference = "a" * 256 + "@sha256:" + "c" * 64
    _replace_recipe_and_rebind(manifest, f"FROM {reference}\n")
    receipt_path = manifest.parent / "gashi-sa" / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["base_images"] = [{"reference": reference, "digest": "sha256:" + "c" * 64}]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["solvers"]["gashi-sa"]["build"]["receipt"]["sha256"] = _sha(receipt_path)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompetitorProvenanceError, match="exceeds 255"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


@pytest.mark.parametrize(
    "platform",
    ["linux//amd64", "../linux", "https://evil", "linux@amd64", "a/b/c/d"],
)
def test_rejects_invalid_platform(tmp_path: Path, platform: str) -> None:
    manifest, images = _fixture(tmp_path)
    reference = "example/runtime@sha256:" + "c" * 64
    _replace_recipe_and_rebind(
        manifest, f"FROM --platform={platform} {reference} AS valid\n"
    )
    with pytest.raises(CompetitorProvenanceError, match="invalid platform"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


@pytest.mark.parametrize("alias", [".", "..", "-bad", "_bad"])
def test_rejects_invalid_stage_alias(tmp_path: Path, alias: str) -> None:
    manifest, images = _fixture(tmp_path)
    reference = "example/runtime@sha256:" + "c" * 64
    _replace_recipe_and_rebind(manifest, f"FROM {reference} AS {alias}\n")
    with pytest.raises(CompetitorProvenanceError, match="invalid stage alias"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_initial_manifest_stat_race_is_contained(tmp_path: Path, monkeypatch) -> None:
    manifest, images = _fixture(tmp_path)
    path_type = type(Path())
    original = path_type.is_file

    def racing_is_file(path: Path) -> bool:
        result = original(path)
        if path == manifest.resolve() and result:
            path.unlink()
        return result

    monkeypatch.setattr(path_type, "is_file", racing_is_file)
    with pytest.raises(CompetitorProvenanceError, match="manifest does not exist"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_initial_artifact_stat_race_is_contained(tmp_path: Path, monkeypatch) -> None:
    manifest, images = _fixture(tmp_path)
    target = (manifest.parent / "gashi-sa" / "source.tar").resolve()
    path_type = type(Path())
    original = path_type.is_file

    def racing_is_file(path: Path) -> bool:
        result = original(path)
        if path == target and result:
            path.unlink()
        return result

    monkeypatch.setattr(path_type, "is_file", racing_is_file)
    with pytest.raises(CompetitorProvenanceError, match="escapes or is missing"):
        verify_competitor_provenance(
            manifest,
            expected_solvers=("gashi-sa",),
            selected_images=images,
        )


def test_source_inventory_v2_groups_exact_ordered_unique_upstreams() -> None:
    inventory_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "competitor_packages"
        / "source-inventory.json"
    )
    inventory, _ = provenance._read_plain_json(inventory_path, "source inventory")

    assert set(inventory) == {"schema", "claim_grade_ready", "solvers", "status"}
    assert inventory["schema"] == "planora.itc2019.competitor-source-inventory.v2"
    assert inventory["claim_grade_ready"] is False
    assert inventory["status"] == "SOURCE_ARCHIVES_ONLY_NOT_BUILD_OR_CUSTODY_EVIDENCE"
    assert [item["solver"] for item in inventory["solvers"]] == [
        "gashi-sa",
        "unitime-cpsolver",
        "lemos-maxsat",
    ]
    cpsolver = inventory["solvers"][1]
    assert [source["commit_sha"] for source in cpsolver["sources"]] == [
        "d1576ac94a8f7b6562e49f9476a89fb741cb226f",
        "3abbcaaf26d739d25e45c8e191b7ef94bc15cc26",
    ]
    seen: set[tuple[str, str]] = set()
    for solver in inventory["solvers"]:
        assert type(solver["sources"]) is list and solver["sources"]
        for source in solver["sources"]:
            identity = (source["repository_url"], source["commit_sha"])
            assert identity not in seen
            seen.add(identity)
            archive = inventory_path.parent / source["archive_path"]
            assert type(source["archive_size_bytes"]) is int
            assert archive.stat().st_size == source["archive_size_bytes"]
            assert _sha(archive) == source["archive_sha256"]
