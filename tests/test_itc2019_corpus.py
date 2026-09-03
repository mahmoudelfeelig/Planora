from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.itc2019_corpus import (
    ITC2019_EFFECTIVE_COMPETITION_FILES,
    ITC2019_EFFECTIVE_COMPETITION_MANIFEST_SHA256,
    ITC2019_OFFICIAL_CORRECTED_INPUT_SHA256,
    ITC2019_OFFICIAL_CORRECTIONS,
    ITC2019_PUBLIC_CORPUS_FILES,
    ITC2019_PUBLIC_SOURCE_MANIFEST_SHA256,
    ITC2019PublicCorpusError,
    ITC2019PublicCorpusFile,
    ITC2019PublicCorpusPin,
    ITC2019PublicEvidenceFile,
    fetch_itc2019_public_corpus,
    verify_cached_itc2019_public_corpus,
)


TOY_PROBLEM = b"""\
<problem name="toy" nrDays="1" slotsPerDay="2" nrWeeks="1">
  <rooms><room id="R" capacity="1"/></rooms>
  <courses><course id="C"><config id="CFG"><subpart id="SP">
    <class id="CL" limit="10">
      <room id="R"/><time days="1" start="0" length="1" weeks="1"/>
    </class>
  </subpart></config></course></courses>
</problem>
"""

TOY_SOLUTION = b"""\
<solution name="toy" runtime="0">
  <class id="CL" days="1" start="0" weeks="1" room="R"/>
</solution>
"""

NEGATIVE_LENGTH_PROBLEM = b"""\
<problem name="bad-time" nrDays="1" slotsPerDay="2" nrWeeks="1">
  <rooms><room id="R" capacity="1"/></rooms>
  <courses><course id="C"><config id="CFG"><subpart id="SP">
    <class id="CL" limit="0">
      <room id="R"/><time days="1" start="1" length="-2" weeks="1"/>
    </class>
  </subpart></config></course></courses>
</problem>
"""


def _digests(data: bytes) -> tuple[int, str, str]:
    git_header = f"blob {len(data)}\0".encode("ascii")
    return (
        len(data),
        hashlib.sha1(git_header + data).hexdigest(),  # noqa: S324
        hashlib.sha256(data).hexdigest(),
    )


def _corpus_file(
    kind: str,
    instance: str,
    path: str,
    data: bytes,
) -> ITC2019PublicCorpusFile:
    length, git_sha1, sha256 = _digests(data)
    return ITC2019PublicCorpusFile(
        kind=kind,
        phase="test",
        instance=instance,
        relative_path=path,
        byte_length=length,
        git_blob_sha1=git_sha1,
        sha256=sha256,
    )


def _evidence_file(path: str, data: bytes) -> ITC2019PublicEvidenceFile:
    length, git_sha1, sha256 = _digests(data)
    return ITC2019PublicEvidenceFile(
        relative_path=path,
        byte_length=length,
        git_blob_sha1=git_sha1,
        sha256=sha256,
    )


def _toy_pin(
    *,
    problem: bytes = TOY_PROBLEM,
    include_solution: bool = True,
) -> tuple[ITC2019PublicCorpusPin, dict[str, bytes]]:
    commit = "a" * 40
    tree = "b" * 40
    repository = "https://github.com/example/itc2019-toy"
    files = [
        _corpus_file(
            "problem",
            "toy" if problem is TOY_PROBLEM else "bad-time",
            "data/input/ITC-2019/toy.xml",
            problem,
        )
    ]
    payloads = {files[0].relative_path: problem}
    if include_solution:
        solution = _corpus_file(
            "solution",
            "toy",
            "data/output/ITC-2019/solution-toy.xml",
            TOY_SOLUTION,
        )
        files.append(solution)
        payloads[solution.relative_path] = TOY_SOLUTION
    license_bytes = b"MIT toy license\n"
    readme_bytes = b"Toy public finalist repository\n"
    evidence = (
        _evidence_file("LICENSE", license_bytes),
        _evidence_file("README.md", readme_bytes),
    )
    payloads.update({"LICENSE": license_bytes, "README.md": readme_bytes})
    pin = ITC2019PublicCorpusPin(
        repository=repository,
        commit=commit,
        root_tree=tree,
        committed_at="2020-01-02T03:04:05Z",
        commit_message="Pinned toy",
        files=tuple(files),
        evidence_files=evidence,
        expected_problem_count=1,
        expected_solution_count=int(include_solution),
    )
    return pin, payloads


def _toy_responses(
    pin: ITC2019PublicCorpusPin,
    payloads: dict[str, bytes],
) -> dict[str, bytes]:
    slug = pin.repository.removeprefix("https://github.com/")
    commit_url = f"https://api.github.com/repos/{slug}/commits/{pin.commit}"
    tree_url = (
        f"https://api.github.com/repos/{slug}/git/trees/{pin.root_tree}?recursive=1"
    )
    raw_base = f"https://raw.githubusercontent.com/{slug}/{pin.commit}"
    entries = [
        {
            "path": row.relative_path,
            "type": "blob",
            "sha": row.git_blob_sha1,
            "size": row.byte_length,
        }
        for row in (*pin.files, *pin.evidence_files)
    ]
    responses = {
        commit_url: json.dumps(
            {
                "sha": pin.commit,
                "commit": {
                    "tree": {"sha": pin.root_tree},
                    "committer": {"date": pin.committed_at},
                    "message": pin.commit_message,
                },
            }
        ).encode(),
        tree_url: json.dumps(
            {"sha": pin.root_tree, "truncated": False, "tree": entries}
        ).encode(),
    }
    responses.update({f"{raw_base}/{path}": data for path, data in payloads.items()})
    return responses


def test_checked_in_manifest_pins_all_36_instances_and_18_mirror_outputs() -> None:
    kinds = Counter(row.kind for row in ITC2019_PUBLIC_CORPUS_FILES)
    phases = Counter(
        row.phase for row in ITC2019_PUBLIC_CORPUS_FILES if row.kind == "problem"
    )
    assert kinds == {"problem": 36, "solution": 18}
    assert phases == {"test": 6, "early": 10, "middle": 10, "late": 10}
    assert len({row.relative_path for row in ITC2019_PUBLIC_CORPUS_FILES}) == 54
    assert len({row.sha256 for row in ITC2019_PUBLIC_CORPUS_FILES}) == 54
    assert (
        ITC2019_PUBLIC_SOURCE_MANIFEST_SHA256
        == "d4e8e694892c11d8c7ebb998feccd404ddcd2b5cc60a3780ed808b7eca2a35bb"
    )


def test_effective_competition_manifest_overlays_withdrawn_middle_inputs() -> None:
    public_by_instance = {
        row.instance: row for row in ITC2019_PUBLIC_CORPUS_FILES if row.kind == "problem"
    }
    effective_by_instance = {
        row.instance: row
        for row in ITC2019_EFFECTIVE_COMPETITION_FILES
        if row.kind == "problem"
    }

    assert len(ITC2019_OFFICIAL_CORRECTIONS) == 2
    assert ITC2019_OFFICIAL_CORRECTED_INPUT_SHA256 == {
        "muni-pdf-spr16": (
            "72e851f204de6a74841ac998ecba71ef2a5a913578f5020f9be26d8f62bf9933"
        ),
        "pu-d5-spr17": (
            "8bdaf9d09a736f1fe8b202c29b270a9351fbc99cb7737d4abc34944f074e1547"
        ),
    }
    assert set(public_by_instance) == set(effective_by_instance)
    assert {
        instance
        for instance in public_by_instance
        if public_by_instance[instance].sha256 != effective_by_instance[instance].sha256
    } == {"muni-pdf-spr16", "pu-d5-spr17"}
    assert all(
        effective_by_instance[correction.instance].sha256 == correction.sha256
        for correction in ITC2019_OFFICIAL_CORRECTIONS
    )
    assert (
        ITC2019_EFFECTIVE_COMPETITION_MANIFEST_SHA256
        == "1ca1558f69d3a9be60ae44dcc2661f440fe6679b13754b709c491a889ff91f3a"
    )

def test_fetcher_verifies_remote_metadata_bytes_and_local_semantics(
    tmp_path: Path,
) -> None:
    pin, payloads = _toy_pin()
    responses = _toy_responses(pin, payloads)
    requests: list[str] = []

    def fetch(url: str, _timeout: float) -> bytes:
        requests.append(url)
        return responses[url]

    cache = tmp_path / "ignored-cache"
    report = fetch_itc2019_public_corpus(
        cache,
        pin=pin,
        workers=2,
        fetch_bytes=fetch,
    )

    assert report["cache"] == {
        "reused_verified_files": 0,
        "downloaded_files": 4,
    }
    assert report["problem_parsing"]["semantic_passed"] == 1
    assert report["solution_validation"]["locally_valid_for_implemented_scope"] == 1
    assert report["validation_scope"]["official_validator"].startswith("not_run")
    assert (cache / "PROVENANCE.json").is_file()
    assert len(requests) == 6

    verified = verify_cached_itc2019_public_corpus(cache, pin=pin)
    assert verified["problem_parsing"]["semantic_passed"] == 1
    assert verified["solution_validation"]["locally_invalid_for_implemented_scope"] == 0


def test_fetcher_reuses_only_verified_cached_files(tmp_path: Path) -> None:
    pin, payloads = _toy_pin()
    responses = _toy_responses(pin, payloads)
    cache = tmp_path / "ignored-cache"

    fetch_itc2019_public_corpus(
        cache,
        pin=pin,
        workers=1,
        fetch_bytes=lambda url, _timeout: responses[url],
    )

    raw_urls = {url for url in responses if "raw.githubusercontent.com" in url}

    def metadata_only_fetch(url: str, _timeout: float) -> bytes:
        if url in raw_urls:
            raise AssertionError("verified cached content should be reused")
        return responses[url]

    report = fetch_itc2019_public_corpus(
        cache,
        pin=pin,
        workers=1,
        fetch_bytes=metadata_only_fetch,
    )
    assert report["cache"] == {
        "reused_verified_files": 4,
        "downloaded_files": 0,
    }


def test_verifier_rejects_tampered_cached_content(tmp_path: Path) -> None:
    pin, payloads = _toy_pin()
    responses = _toy_responses(pin, payloads)
    cache = tmp_path / "ignored-cache"
    fetch_itc2019_public_corpus(
        cache,
        pin=pin,
        workers=1,
        fetch_bytes=lambda url, _timeout: responses[url],
    )
    (cache / "raw" / pin.files[0].relative_path).write_bytes(b"tampered")

    with pytest.raises(ITC2019PublicCorpusError, match="Content hash mismatch"):
        verify_cached_itc2019_public_corpus(cache, pin=pin)


def test_nonpositive_mirror_time_is_preserved_and_rejected_fail_closed(
    tmp_path: Path,
) -> None:
    pin, payloads = _toy_pin(
        problem=NEGATIVE_LENGTH_PROBLEM,
        include_solution=False,
    )
    problem_row = replace(pin.files[0], instance="bad-time")
    pin = replace(pin, files=(problem_row,))
    cache = tmp_path / "ignored-cache"
    for row in (*pin.files, *pin.evidence_files):
        destination = cache / "raw" / row.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payloads[row.relative_path])

    report = verify_cached_itc2019_public_corpus(cache, pin=pin)
    problem = report["problem_parsing"]["instances"][0]

    assert report["problem_parsing"]["structural_xml_passed"] == 1
    assert report["problem_parsing"]["semantic_rejected"] == 1
    assert problem["nonpositive_time_anomalies"] == [
        {
            "class_id": "CL",
            "class_limit": "0",
            "time_attributes": {
                "days": "1",
                "length": "-2",
                "start": "1",
                "weeks": "1",
            },
        }
    ]
    assert problem["semantic_parse_error"].endswith(
        "ITC-2019 class time length must be positive"
    )


def test_fetcher_rejects_remote_tree_drift(tmp_path: Path) -> None:
    pin, payloads = _toy_pin()
    responses = _toy_responses(pin, payloads)
    tree_url = next(url for url in responses if "/git/trees/" in url)
    tree = json.loads(responses[tree_url])
    tree["tree"][0]["sha"] = "0" * 40
    responses[tree_url] = json.dumps(tree).encode()

    with pytest.raises(ITC2019PublicCorpusError, match="tree mismatch"):
        fetch_itc2019_public_corpus(
            tmp_path / "ignored-cache",
            pin=pin,
            workers=1,
            fetch_bytes=lambda url, _timeout: responses[url],
        )
