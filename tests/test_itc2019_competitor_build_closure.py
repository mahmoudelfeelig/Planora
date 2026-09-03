from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from benchmarks import itc2019_competitor_build_closure as closure


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/competitor_packages/build-closure-policy.json"
MANIFEST = ROOT / "benchmarks/competitor_packages/build-closure-manifest.json"


def _tar(
    members: list[tuple[str, bytes, str]],
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            if kind == "file":
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "target"
                archive.addfile(info)
            elif kind == "hardlink":
                info.type = tarfile.LNKTYPE
                info.linkname = "target"
                archive.addfile(info)
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
                archive.addfile(info)
            else:
                raise AssertionError(kind)
    return buffer.getvalue()


def _policy() -> dict[str, object]:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def test_real_inventory_replays_and_stays_fail_closed() -> None:
    manifest = closure.verify(ROOT)
    assert manifest["status"] == closure.STATUS
    assert manifest["custody_binding_sha256"] == closure.CUSTODY_BINDING_SHA256
    assert (
        manifest["build_admission_binding_sha256"]
        == closure.BUILD_ADMISSION_BINDING_SHA256
    )
    assert manifest["build_ready"] is False
    assert manifest["claim_grade_ready"] is False
    assert manifest["performance_claims_authorized"] is False
    assert all(solver["closure_complete"] is False for solver in manifest["solvers"])
    assert all(solver["build_ready"] is False for solver in manifest["solvers"])


def test_manifest_generation_is_deterministic() -> None:
    first = closure.build_manifest(ROOT, POLICY)
    second = closure.build_manifest(ROOT, POLICY)
    assert closure._manifest_bytes(first) == closure._manifest_bytes(second)
    assert closure._manifest_bytes(first) == MANIFEST.read_bytes()
    assert first["binding_sha256"] == second["binding_sha256"]


def test_cli_replay_is_byte_identical() -> None:
    command = [
        sys.executable,
        "-B",
        "-m",
        "benchmarks.itc2019_competitor_build_closure",
    ]
    first = subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    second = subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr == b""
    assert b"build_ready=false" in first.stdout
    assert b"performance_claims_authorized=false" in first.stdout


def test_archive_reader_never_extracts_to_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("disk extraction was attempted")

    monkeypatch.setattr(tarfile.TarFile, "extract", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extractall", forbidden)
    manifest = closure.build_manifest(ROOT, POLICY)
    assert manifest["descriptor_inventory"]


def test_only_requested_descriptor_bytes_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names: list[str] = []
    original = tarfile.TarFile.extractfile

    def recording_extractfile(
        self: tarfile.TarFile, member: tarfile.TarInfo | str
    ) -> object:
        names.append(member.name if isinstance(member, tarfile.TarInfo) else member)
        return original(self, member)

    monkeypatch.setattr(tarfile.TarFile, "extractfile", recording_extractfile)
    closure.build_manifest(ROOT, POLICY)
    expected = {item["path"] for item in _policy()["archive_descriptors"]}
    assert set(names) == expected
    assert len(names) == len(expected)
    assert not any(name.endswith(".jar") for name in names)


@pytest.mark.parametrize(
    "name",
    [
        "/absolute/pom.xml",
        "../escape/pom.xml",
        "a/../pom.xml",
        "C:/pom.xml",
        "a\\pom.xml",
    ],
)
def test_archive_rejects_hostile_paths(name: str) -> None:
    encoded = _tar([(name, b"x", "file")])
    with pytest.raises(closure.BuildClosureError, match="path"):
        closure.inspect_archive_bytes(encoded, [])


def test_path_validator_rejects_nul_without_tar_normalization() -> None:
    with pytest.raises(closure.BuildClosureError, match="normalized POSIX path"):
        closure._normalized_path("a\x00b", "archive member path")


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_archive_rejects_links(kind: str) -> None:
    encoded = _tar([("safe", b"", kind)])
    with pytest.raises(closure.BuildClosureError, match="symbolic or hard link"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_rejects_unsupported_member_type() -> None:
    encoded = _tar([("pipe", b"", "fifo")])
    with pytest.raises(closure.BuildClosureError, match="unsupported member type"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_rejects_exact_duplicate_paths() -> None:
    encoded = _tar([("a/pom.xml", b"one", "file"), ("a/pom.xml", b"two", "file")])
    with pytest.raises(closure.BuildClosureError, match="duplicate or ambiguous"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_rejects_casefold_ambiguous_paths() -> None:
    encoded = _tar([("A/pom.xml", b"one", "file"), ("a/POM.xml", b"two", "file")])
    with pytest.raises(closure.BuildClosureError, match="duplicate or ambiguous"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_rejects_duplicate_descriptor_requests() -> None:
    encoded = _tar([("a/pom.xml", b"x", "file")])
    with pytest.raises(closure.BuildClosureError, match="request contains duplicates"):
        closure.inspect_archive_bytes(encoded, ["a/pom.xml", "a/pom.xml"])


def test_archive_rejects_missing_descriptor() -> None:
    encoded = _tar([("a/pom.xml", b"x", "file")])
    with pytest.raises(closure.BuildClosureError, match="is missing"):
        closure.inspect_archive_bytes(encoded, ["other/pom.xml"])


def test_archive_rejects_missing_metadata_only_member() -> None:
    encoded = _tar([("a/pom.xml", b"x", "file")])
    with pytest.raises(closure.BuildClosureError, match="metadata-only member"):
        closure.inspect_archive_bytes(encoded, [], metadata_paths=["missing.jar"])


def test_archive_enforces_member_count(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = _tar([("one", b"1", "file"), ("two", b"2", "file")])
    monkeypatch.setattr(closure, "MAX_MEMBERS", 1)
    with pytest.raises(closure.BuildClosureError, match="member-count"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_enforces_member_size(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = _tar([("one", b"123", "file")])
    monkeypatch.setattr(closure, "MAX_MEMBER_BYTES", 2)
    with pytest.raises(closure.BuildClosureError, match="member-size"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_enforces_total_declared_size(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = _tar([("one", b"12", "file"), ("two", b"34", "file")])
    monkeypatch.setattr(closure, "MAX_TOTAL_DECLARED_BYTES", 3)
    with pytest.raises(closure.BuildClosureError, match="declared-size"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_enforces_decompression_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = _tar([("one", b"x" * 1024, "file")])
    monkeypatch.setattr(closure, "MAX_DECOMPRESSION_RATIO", 0)
    with pytest.raises(closure.BuildClosureError, match="decompression-ratio"):
        closure.inspect_archive_bytes(encoded, [])


def test_archive_enforces_descriptor_size(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = _tar([("pom.xml", b"123", "file")])
    monkeypatch.setattr(closure, "MAX_DESCRIPTOR_BYTES", 2)
    with pytest.raises(closure.BuildClosureError, match="descriptor exceeds"):
        closure.inspect_archive_bytes(encoded, ["pom.xml"])


def test_archive_enforces_descriptor_total(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = _tar([("one.xml", b"12", "file"), ("two.xml", b"34", "file")])
    monkeypatch.setattr(closure, "MAX_DESCRIPTOR_TOTAL_BYTES", 3)
    with pytest.raises(closure.BuildClosureError, match="descriptors exceed"):
        closure.inspect_archive_bytes(encoded, ["one.xml", "two.xml"])


def test_descriptor_rejects_invalid_encoding_and_nul() -> None:
    with pytest.raises(closure.BuildClosureError, match="UTF-8"):
        closure._decode_descriptor(b"\xff", "descriptor")
    with pytest.raises(closure.BuildClosureError, match="NUL"):
        closure._decode_descriptor(b"a\x00b", "descriptor")


@pytest.mark.parametrize(
    "encoded",
    [
        b'<!DOCTYPE x [<!ENTITY e "boom">]><Project>&e;</Project>',
        b"<Project><broken></Project>",
    ],
)
def test_xml_descriptor_rejects_entities_and_malformed_xml(encoded: bytes) -> None:
    with pytest.raises(closure.BuildClosureError):
        closure._msbuild_facts(encoded, "project")


def test_msbuild_parser_derives_target_and_package() -> None:
    encoded = b"""<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
      <TargetFramework>netcoreapp2.1</TargetFramework><OutputType>Exe</OutputType>
      </PropertyGroup><ItemGroup><PackageReference Include="argu" Version="5.2.0" />
      </ItemGroup></Project>"""
    facts = closure._msbuild_facts(encoded, "project")
    assert facts["properties"] == {
        "OutputType": "Exe",
        "TargetFramework": "netcoreapp2.1",
    }
    assert facts["package_references"] == [{"id": "argu", "version": "5.2.0"}]


def test_pom_parser_derives_dependency_plugin_and_compiler() -> None:
    encoded = b"""<project><modelVersion>4.0.0</modelVersion>
      <groupId>g</groupId><artifactId>a</artifactId><version>1</version>
      <dependencies><dependency><groupId>d</groupId><artifactId>x</artifactId>
      <version>2</version></dependency></dependencies><build><plugins><plugin>
      <groupId>p</groupId><artifactId>plug</artifactId><version>3</version>
      <configuration><source>11</source><target>11</target></configuration>
      </plugin></plugins></build></project>"""
    facts = closure._pom_facts(encoded, "pom")
    assert facts["project"] == {
        "group_id": "g",
        "artifact_id": "a",
        "version": "1",
        "packaging": "jar",
    }
    assert facts["dependencies"] == [
        {"group_id": "d", "artifact_id": "x", "version": "2"}
    ]
    assert facts["compiler"] == {"source": "11", "target": "11"}


def test_make_parser_derives_selected_source_declarations() -> None:
    facts = closure._make_facts(
        b"VERSION = core\nSOLVERDIR = glucose4.1\nLFLAGS += -lgmpxx -lgmp\nCXX ?= g++\n",
        "makefile",
    )
    assert {item["name"] for item in facts["assignments"]} == {
        "VERSION",
        "SOLVERDIR",
        "LFLAGS",
        "CXX",
    }
    assert facts["link_libraries"] == ["gmp", "gmpxx"]
    assert facts["tool_tokens"] == ["g++"]


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(closure.BuildClosureError, match="duplicate key"):
        closure._strict_json(b'{"schema":"one","schema":"two"}', "policy")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("claim_boundary", "build_ready"), True),
        (("claim_boundary", "claim_grade_ready"), True),
        (("claim_boundary", "performance_claims_authorized"), True),
        (("acquisition_contract", "network_access_authorized"), True),
        (("local_observations", "scope"), "CLAIM_GRADE"),
    ],
)
def test_policy_rejects_readiness_or_authority_upgrades(
    path: tuple[str, str], value: object
) -> None:
    policy = _policy()
    policy[path[0]][path[1]] = value
    with pytest.raises(closure.BuildClosureError):
        closure._validate_policy(policy)


def test_policy_rejects_mutable_requirement_with_fake_digest() -> None:
    policy = _policy()
    requirement = policy["solvers"][0]["requirements"][1]
    requirement["acquisition"]["expected_sha256"] = "0" * 64
    requirement["acquisition"]["expected_size_bytes"] = 1
    with pytest.raises(closure.BuildClosureError, match="untrusted requirement"):
        closure._validate_policy(policy)


def test_policy_rejects_pinned_requirement_without_identity() -> None:
    policy = _policy()
    requirement = policy["solvers"][0]["requirements"][0]
    requirement["acquisition"]["expected_sha256"] = None
    with pytest.raises(closure.BuildClosureError, match="lacks immutable identity"):
        closure._validate_policy(policy)


def test_policy_rejects_coordinated_descriptor_deletion() -> None:
    policy = _policy()
    descriptor = policy["archive_descriptors"].pop()
    policy["solvers"][2]["descriptor_ids"].remove(descriptor["id"])
    with pytest.raises(closure.BuildClosureError, match="descriptor inventory drifted"):
        closure._validate_policy(policy)


def test_policy_rejects_requirement_deletion() -> None:
    policy = _policy()
    policy["solvers"][0]["requirements"].pop()
    with pytest.raises(
        closure.BuildClosureError, match="requirement inventory drifted"
    ):
        closure._validate_policy(policy)


def test_policy_rejects_pinned_identity_substituted_from_another_archive() -> None:
    policy = _policy()
    requirement = policy["solvers"][0]["requirements"][0]
    _path, size, digest = closure.ARCHIVES["unitime-extension"]
    requirement["evidence"]["archive"] = "unitime-extension"
    requirement["acquisition"]["expected_size_bytes"] = size
    requirement["acquisition"]["expected_sha256"] = digest
    with pytest.raises(closure.BuildClosureError, match="archive binding drifted"):
        closure._validate_policy(policy)


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    (
        ("license_review_required", False, "license review"),
        ("provenance_review_required", False, "provenance review"),
        ("candidate_sources", [], "candidate sources"),
    ),
)
def test_policy_rejects_weakened_unresolved_acquisition_contract(
    field: str, value: object, detail: str
) -> None:
    policy = _policy()
    acquisition = policy["solvers"][0]["requirements"][1]["acquisition"]
    acquisition[field] = value
    with pytest.raises(closure.BuildClosureError, match=detail):
        closure._validate_policy(policy)


def test_all_requirements_are_classified_and_acquirable_later() -> None:
    policy = closure._validate_policy(_policy())
    requirements = [
        requirement
        for solver in policy["solvers"]
        for requirement in solver["requirements"]
    ]
    assert len(requirements) == 33
    assert {item["classification"] for item in requirements} == closure.CLASSIFICATIONS
    for item in requirements:
        acquisition = item["acquisition"]
        assert acquisition["canonical_coordinates"]
        assert acquisition["license_review_required"] is True
        if item["classification"] != "pinned-present":
            assert acquisition["candidate_sources"]
            assert acquisition["expected_sha256"] is None
            assert acquisition["expected_size_bytes"] is None


def test_local_observations_cannot_be_claim_grade() -> None:
    observations = _policy()["local_observations"]
    assert observations["docker"]["trusted_for_closure"] is False
    statuses = {
        item["classification"]
        for key in ("host_tools", "package_caches")
        for item in observations[key]
    }
    assert statuses <= {"mutable-unverified", "missing"}
    assert "pinned-present" not in statuses


def test_policy_tamper_changes_expected_manifest() -> None:
    policy = _policy()
    changed = copy.deepcopy(policy)
    changed["local_observations"]["docker"]["detail"] += " changed"
    assert closure._json_sha256(policy) != closure._json_sha256(changed)
