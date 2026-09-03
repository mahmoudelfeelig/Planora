from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from benchmarks.cbctt_corpus import (
    CBCTT_CORPUS_FILES,
    CBCTT_EXCLUDED_ARCHIVE_VARIANTS,
    CBCTT_REPOSITORY_ROOT,
    SWH_API_BASE_URL,
    CBCTTArchiveError,
    CBCTTArchiveFile,
    CBCTTArchivePin,
    CBCTTExcludedArchiveVariant,
    fetch_cbctt_corpus,
    validate_cbctt_projection_compatibility,
    verify_cached_cbctt_corpus,
)


TOY_ECTT = b"""\
Name: toy-external
Courses: 1
Rooms: 1
Days: 1
Periods_per_day: 2
Curricula: 1
Min_Max_Daily_Lectures: 0 2
UnavailabilityConstraints: 0
RoomConstraints: 0
COURSES:
C1 T1 1 1 10 0
ROOMS:
R1 20 0
CURRICULA:
Q1 1 C1
UNAVAILABILITY_CONSTRAINTS:
ROOM_CONSTRAINTS:
END.
"""


def _digest(data: bytes) -> tuple[str, str, str]:
    sha1_git = hashlib.sha1(  # noqa: S324
        f"blob {len(data)}\0".encode("ascii") + data
    ).hexdigest()
    return (
        sha1_git,
        hashlib.sha1(data).hexdigest(),  # noqa: S324
        hashlib.sha256(data).hexdigest(),
    )


def _toy_archive() -> tuple[CBCTTArchivePin, dict[str, bytes]]:
    sha1_git, sha1, sha256 = _digest(TOY_ECTT)
    revision = "d" * 40
    root = "a" * 40
    instances = "b" * 40
    family = "c" * 40
    snapshot = "1" * 40
    archived = CBCTTArchiveFile(
        family="Toy",
        filename="toy.ectt",
        length=len(TOY_ECTT),
        sha1_git=sha1_git,
        sha1=sha1,
        sha256=sha256,
    )
    pin = CBCTTArchivePin(
        origin="https://example.invalid/toy",
        revision=revision,
        revision_swhid=f"swh:1:rev:{revision}",
        root_directory_swhid=f"swh:1:dir:{root}",
        instances_directory_swhid=f"swh:1:dir:{instances}",
        origin_visit=7,
        origin_visit_type="hg",
        snapshot_swhid=f"swh:1:snp:{snapshot}",
        snapshot_branch="branch-tip/default",
        family_directory_swhids={"Toy": f"swh:1:dir:{family}"},
        root_license_filenames=(),
        files=(archived,),
    )

    def encoded(value: Any) -> bytes:
        return json.dumps(value).encode("utf-8")

    responses = {
        f"{SWH_API_BASE_URL}/origin/https%3A%2F%2Fexample.invalid%2Ftoy/get/": encoded(
            {"url": pin.origin, "visit_types": ["hg"]}
        ),
        f"{SWH_API_BASE_URL}/origin/https%3A%2F%2Fexample.invalid%2Ftoy/visit/7/": encoded(
            {
                "origin": pin.origin,
                "visit": 7,
                "status": "full",
                "snapshot": snapshot,
                "type": "hg",
            }
        ),
        f"{SWH_API_BASE_URL}/snapshot/{snapshot}/": encoded(
            {
                "id": snapshot,
                "branches": {
                    "branch-tip/default": {
                        "target": revision,
                        "target_type": "revision",
                    }
                },
                "next_branch": None,
            }
        ),
        f"{SWH_API_BASE_URL}/revision/{revision}/": encoded(
            {"id": revision, "directory": root}
        ),
        f"{SWH_API_BASE_URL}/directory/{root}/": encoded(
            [
                {
                    "name": "README.md",
                    "type": "file",
                    "target": "e" * 40,
                },
                {"name": "instances", "type": "dir", "target": instances},
            ]
        ),
        f"{SWH_API_BASE_URL}/directory/{instances}/": encoded(
            [{"name": "Toy", "type": "dir", "target": family}]
        ),
        f"{SWH_API_BASE_URL}/directory/{family}/": encoded(
            [
                {
                    "name": "toy.ectt",
                    "type": "file",
                    "target": sha1_git,
                    "length": len(TOY_ECTT),
                    "checksums": {
                        "sha1_git": sha1_git,
                        "sha1": sha1,
                        "sha256": sha256,
                    },
                }
            ]
        ),
        f"{SWH_API_BASE_URL}/content/sha1_git:{sha1_git}/raw/": TOY_ECTT,
    }
    return pin, responses


def test_pinned_manifest_contains_34_distinct_institutional_instances() -> None:
    family_counts = Counter(row.family for row in CBCTT_CORPUS_FILES)

    assert len(CBCTT_CORPUS_FILES) == 34
    assert len({row.relative_path for row in CBCTT_CORPUS_FILES}) == 34
    assert len({row.sha256 for row in CBCTT_CORPUS_FILES}) == 34
    assert family_counts == {
        "DDS": 7,
        "EasyAcademy": 12,
        "Erlangen": 6,
        "Udine": 9,
    }
    assert {row.filename for row in CBCTT_CORPUS_FILES if row.family == "Erlangen"} == {
        "erlangen2011_2.ectt",
        "erlangen2012_1.ectt",
        "erlangen2012_2.ectt",
        "erlangen2013_1.ectt",
        "erlangen2013_2.ectt",
        "erlangen2014_1.ectt",
    }
    assert {row.archive_file.filename for row in CBCTT_EXCLUDED_ARCHIVE_VARIANTS} == {
        "erlangen-2013-2.ectt",
        "erlangen-2014-1.ectt",
    }
    assert {row.archive_file.sha256 for row in CBCTT_EXCLUDED_ARCHIVE_VARIANTS} == {
        "06274217a279930d1839ce238c31dd1a6d2e42cfdcbc69ef169473f750f8dbb2",
        "8d8e7f293c66e21231f4201a8669bea97239c0130bfb61cb7afeae55aecc79e9",
    }


def test_fetcher_verifies_archive_hashes_and_builds_non_vendored_projection_cache(
    tmp_path: Path,
) -> None:
    pin, responses = _toy_archive()
    requests: list[str] = []

    def fetch(url: str, _timeout: float) -> bytes:
        requests.append(url)
        return responses[url]

    cache = tmp_path / "external-cache"
    report = fetch_cbctt_corpus(
        cache,
        pin=pin,
        fetch_bytes=fetch,
        workers=1,
    )

    assert report["corpus"]["distinct_instance_files"] == 1
    assert report["corpus"]["distinct_sha256_contents"] == 1
    assert report["corpus"]["families"] == {"Toy": 1}
    assert report["corpus"]["projection_scope"] == "standard_itc2007_four_term_only"
    assert report["licensing"] == {
        "root_license_filenames": [],
        "status": "no_license_file_in_pinned_archive_root",
        "redistribution_rights": "not_established",
        "storage_policy": "ignored_local_cache_only_not_vendored",
    }
    assert report["cache"] == {
        "reused_verified_source_files": 0,
        "downloaded_source_files": 1,
        "reused_verified_excluded_variant_files": 0,
        "downloaded_excluded_variant_files": 0,
    }
    assert (cache / "raw/Toy/toy.ectt").read_bytes() == TOY_ECTT
    assert (cache / "projected-itc2007/Toy/toy.ctt").is_file()
    assert (cache / "PROVENANCE.json").is_file()
    assert (cache / "PROVENANCE.sha256").is_file()
    assert len(requests) == 8

    verified = verify_cached_cbctt_corpus(cache, pin=pin)
    assert verified["distinct_instance_files"] == 1
    assert (
        verified["projection_set_sha256"] == report["corpus"]["projection_set_sha256"]
    )


def test_fetcher_reuses_only_hash_verified_sources(tmp_path: Path) -> None:
    pin, responses = _toy_archive()
    cache = tmp_path / "external-cache"

    def fetch(url: str, _timeout: float) -> bytes:
        return responses[url]

    fetch_cbctt_corpus(cache, pin=pin, fetch_bytes=fetch, workers=1)
    raw_url = next(url for url in responses if "/content/" in url)

    def metadata_only_fetch(url: str, _timeout: float) -> bytes:
        if url == raw_url:
            raise AssertionError("verified source content should have been reused")
        return responses[url]

    report = fetch_cbctt_corpus(
        cache,
        pin=pin,
        fetch_bytes=metadata_only_fetch,
        workers=1,
    )
    assert report["cache"] == {
        "reused_verified_source_files": 1,
        "downloaded_source_files": 0,
        "reused_verified_excluded_variant_files": 0,
        "downloaded_excluded_variant_files": 0,
    }


def test_fetcher_hashes_and_parses_excluded_archive_variants(tmp_path: Path) -> None:
    pin, responses = _toy_archive()
    excluded_bytes = TOY_ECTT.replace(b"Name: toy-external", b"Name: test_instance")
    sha1_git, sha1, sha256 = _digest(excluded_bytes)
    archived = CBCTTArchiveFile(
        family="Toy",
        filename="toy-alternate.ectt",
        length=len(excluded_bytes),
        sha1_git=sha1_git,
        sha1=sha1,
        sha256=sha256,
    )
    excluded = CBCTTExcludedArchiveVariant(
        archive_file=archived,
        archived_problem_name="test_instance",
        archived_curricula=1,
        reason="Alternate representation used only for a provenance regression.",
    )
    pin = replace(pin, excluded_variants=(excluded,))
    family_url = f"{SWH_API_BASE_URL}/directory/{'c' * 40}/"
    family_rows = json.loads(responses[family_url])
    family_rows.append(
        {
            "name": archived.filename,
            "type": "file",
            "target": sha1_git,
            "length": len(excluded_bytes),
            "checksums": {
                "sha1_git": sha1_git,
                "sha1": sha1,
                "sha256": sha256,
            },
        }
    )
    responses[family_url] = json.dumps(family_rows).encode("utf-8")
    responses[f"{SWH_API_BASE_URL}/content/sha1_git:{sha1_git}/raw/"] = excluded_bytes

    cache = tmp_path / "external-cache"
    report = fetch_cbctt_corpus(
        cache,
        pin=pin,
        fetch_bytes=lambda url, _timeout: responses[url],
        workers=1,
    )

    cached = cache / "excluded-archive-variants/Toy/toy-alternate.ectt"
    assert cached.read_bytes() == excluded_bytes
    evidence = report["selection"]["excluded_archive_variants"][0]
    assert evidence["observed_problem_name"] == "test_instance"
    assert evidence["observed_curricula"] == 1
    assert evidence["sha256"] == sha256
    assert (
        verify_cached_cbctt_corpus(cache, pin=pin)["excluded_archive_variant_files"]
        == 1
    )


def test_fetcher_rejects_archive_metadata_drift(tmp_path: Path) -> None:
    pin, responses = _toy_archive()
    family_id = "c" * 40
    family_url = f"{SWH_API_BASE_URL}/directory/{family_id}/"
    payload = json.loads(responses[family_url])
    payload[0]["checksums"]["sha256"] = "0" * 64
    responses[family_url] = json.dumps(payload).encode("utf-8")

    with pytest.raises(CBCTTArchiveError, match="metadata mismatch"):
        fetch_cbctt_corpus(
            tmp_path / "external-cache",
            pin=pin,
            fetch_bytes=lambda url, _timeout: responses[url],
            workers=1,
        )


def test_fetcher_rejects_origin_snapshot_revision_mismatch(tmp_path: Path) -> None:
    pin, responses = _toy_archive()
    snapshot_url = f"{SWH_API_BASE_URL}/snapshot/{'1' * 40}/"
    payload = json.loads(responses[snapshot_url])
    payload["branches"]["branch-tip/default"]["target"] = "e" * 40
    responses[snapshot_url] = json.dumps(payload).encode("utf-8")

    with pytest.raises(CBCTTArchiveError, match="snapshot branch"):
        fetch_cbctt_corpus(
            tmp_path / "external-cache",
            pin=pin,
            fetch_bytes=lambda url, _timeout: responses[url],
            workers=1,
        )


def test_fetcher_rejects_internally_inconsistent_revision_pin(tmp_path: Path) -> None:
    pin, responses = _toy_archive()
    inconsistent = replace(pin, revision_swhid=f"swh:1:rev:{'f' * 40}")

    with pytest.raises(ValueError, match="revision and revision SWHID"):
        fetch_cbctt_corpus(
            tmp_path / "external-cache",
            pin=inconsistent,
            fetch_bytes=lambda url, _timeout: responses[url],
            workers=1,
        )


def test_verify_only_detects_source_and_projection_tampering(tmp_path: Path) -> None:
    pin, responses = _toy_archive()
    cache = tmp_path / "external-cache"
    fetch_cbctt_corpus(
        cache,
        pin=pin,
        fetch_bytes=lambda url, _timeout: responses[url],
        workers=1,
    )

    projection = cache / "projected-itc2007/Toy/toy.ctt"
    projection.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(
        CBCTTArchiveError, match="projection is missing or does not match"
    ):
        verify_cached_cbctt_corpus(cache, pin=pin)

    projection.write_text(
        "", encoding="utf-8"
    )  # Source failure is checked before projection content.
    source = cache / "raw/Toy/toy.ectt"
    source.write_bytes(TOY_ECTT + b"\n")
    with pytest.raises(CBCTTArchiveError, match="Content hash mismatch"):
        verify_cached_cbctt_corpus(cache, pin=pin)


def test_verify_only_detects_provenance_tampering(tmp_path: Path) -> None:
    pin, responses = _toy_archive()
    cache = tmp_path / "external-cache"
    fetch_cbctt_corpus(
        cache,
        pin=pin,
        fetch_bytes=lambda url, _timeout: responses[url],
        workers=1,
    )
    provenance = cache / "PROVENANCE.json"
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload["licensing"]["redistribution_rights"] = "asserted-without-evidence"
    provenance.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CBCTTArchiveError, match="provenance SHA-256 sidecar"):
        verify_cached_cbctt_corpus(cache, pin=pin)


def test_repository_local_cache_cannot_target_tracked_source_tree() -> None:
    pin, responses = _toy_archive()
    unsafe = CBCTT_REPOSITORY_ROOT / "benchmarks" / "external-corpus-cache"

    with pytest.raises(ValueError, match="ignored data/ tree"):
        fetch_cbctt_corpus(
            unsafe,
            pin=pin,
            fetch_bytes=lambda url, _timeout: responses[url],
            workers=1,
        )
    assert not unsafe.exists()


def test_official_validator_compatibility_probe_has_a_narrow_claim_boundary(
    tmp_path: Path,
) -> None:
    pin, responses = _toy_archive()
    cache = tmp_path / "external-cache"
    fetch_cbctt_corpus(
        cache,
        pin=pin,
        fetch_bytes=lambda url, _timeout: responses[url],
        workers=1,
    )
    validator = tmp_path / "validator.py"
    validator.write_text(
        """\
print("Violations of Lectures (hard) : 1")
print("Violations of Conflicts (hard) : 0")
print("Violations of Availability (hard) : 0")
print("Violations of RoomOccupation (hard) : 0")
print("Cost of RoomCapacity (soft) : 0")
print("Cost of MinWorkingDays (soft) : 5")
print("Cost of CurriculumCompactness (soft) : 0")
print("Cost of RoomStability (soft) : 0")
print("Summary: Violations = 1, Total Cost = 5")
""",
        encoding="utf-8",
    )

    report = validate_cbctt_projection_compatibility(
        [sys.executable, validator],
        cache,
        pin=pin,
    )

    assert report["all_compatible"] is True
    assert report["checked_instances"] == 1
    assert report["compatible_instances"] == 1
    assert "not feasible-solver evidence" in report["claim_boundary"]
    assert "zero baselines do not exercise" in report["claim_boundary"]
    assert report["validated_nonzero_components"] == [
        "lecture_violations",
        "minimum_working_days",
    ]
    assert (
        report["validator_sha256"] == hashlib.sha256(validator.read_bytes()).hexdigest()
    )
    assert [row["argv_index"] for row in report["validator_command_artifacts"]] == [
        0,
        1,
    ]
    assert report["instances"][0]["expected"] == report["instances"][0]["observed"]


def test_validator_probe_fails_closed_for_unresolved_interpreter_logic(
    tmp_path: Path,
) -> None:
    with pytest.raises(CBCTTArchiveError, match="provenance is unresolved"):
        validate_cbctt_projection_compatibility(
            [sys.executable, "-c", "print('not a hashed validator artifact')"],
            tmp_path,
            pin=_toy_archive()[0],
        )
