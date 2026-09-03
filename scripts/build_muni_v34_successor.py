from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
V33_RUN_ID = "2339df35f57e441a8f92bd1f890fa68f"
RUN_ID = "3c3ed012febd407da5202423b2a67d32"
HOST_ADMISSION_ID = "a5329b8ce4d7458ea26cb4351bb551fe"
V33_RUNNER = REPO / "scripts/run_muni_v33_canonical_tests.ps1"
V34_RUNNER = REPO / "scripts/run_muni_v34_canonical_tests.ps1"
V34_AUTH = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v34-canonical-tests-authorization-20260828T141639Z.receipt.json"
)
V34_GATE = REPO / "scripts/run_muni_v34_terminal_gate_once.ps1"
V33_REJECTION = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v33-terminal-gate-rejection-20260830T000900Z.receipt.json"
)
V33_CUSTODY_TEST = REPO / "tests/test_muni_v33_terminal_gate_rejection.py"
V33_REJECTION_REVIEW = REPO / (
    "output/diagnostic-receipts/"
    "muni-fspsx-v33-terminal-gate-rejection-independent-review-"
    "20260830T002100Z.receipt.json"
)
HOST_READINESS = REPO / (
    "output/diagnostic-receipts/"
    f"muni-fspsx-v34-host-readiness-{HOST_ADMISSION_ID}.receipt.json"
)
HOST_READINESS_REVIEW = REPO / (
    "output/diagnostic-receipts/"
    f"muni-fspsx-v34-host-readiness-{HOST_ADMISSION_ID}."
    "independent-review.receipt.json"
)
SHARED_LOCK = REPO / "output/diagnostic-receipts/planora-shared-heavy-wsl.lock"
RETAINED_ARCHIVE = (
    "output/diagnostic-receipts/"
    "retained-stale-planora-shared-heavy-wsl-v28-"
    "e7cf1df162074402994a9d0ad763c824.lock.json"
)
FORENSIC_REVIEW_SHA256 = (
    "131a4273ad86e98608e6e2f0335fca8363a7abe8232264ec6e05dc27430bec83"
)
V33_REJECTION_SHA256 = (
    "dcd267009e2a440cc120886a1e01aad3d643971336f7935a70454e89c81cdc1e"
)
V33_CUSTODY_TEST_SHA256 = (
    "2533e6f7c881f3259abed8b179211bbc62a085fdf6c322f5f3fb28d2f7699b22"
)
V33_RUNNER_SHA256 = "1899d5c5e89e886181e951dbaf38b7671c640c9aa01d2d21d6d68863048fb0fb"
CORE_ROWS_CANONICAL_SHA256 = (
    "3dbd75c245bd4dd7f22a7d81169b1cfc70e3439638750ee47f239b359f74ddff"
)
PIN_FIELDS = ("path", "size", "sha256", "file_id", "last_write_utc_ticks")
V33_LOWER_TOKEN_COUNT = 104
V33_UPPER_TOKEN_COUNT = 14
V33_RUN_ID_TOKEN_COUNT = 2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        seen: set[str] = set()
        for key, value in pairs:
            folded = key.casefold()
            if folded in seen:
                raise RuntimeError(f"duplicate or case-alias JSON key: {key}")
            seen.add(folded)
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError(f"UTF-8 BOM rejected: {path}")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)


def windows_pin(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["fsutil.exe", "file", "queryfileid", str(path)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"File ID is 0x([0-9a-fA-F]{32})", result.stdout)
    if not match:
        raise RuntimeError(f"file ID parse failed: {path}")
    stat = path.stat()
    return {
        "path": path.relative_to(REPO).as_posix(),
        "size": stat.st_size,
        "sha256": sha256(path),
        "file_id": match.group(1).lower(),
        "last_write_utc_ticks": stat.st_mtime_ns // 100 + 621355968000000000,
    }


def normalized_pin(pin: dict[str, Any]) -> dict[str, Any]:
    return {field: pin[field] for field in PIN_FIELDS}


def assert_live_pin(pin: dict[str, Any]) -> None:
    expected = normalized_pin(pin)
    actual = windows_pin(REPO / expected["path"])
    if actual != expected:
        raise RuntimeError(
            f"live pin mismatch: {expected['path']}: actual={actual} expected={expected}"
        )


def extract_contract(source: str, name: str) -> dict[str, Any]:
    match = re.search(rf"\${re.escape(name)}\s*=\s*@'\n(.*?)\n'@", source, re.S)
    if not match:
        raise RuntimeError(f"embedded contract missing: {name}")
    return json.loads(match.group(1))


def v33_rejection_receipt_pin() -> dict[str, Any]:
    pin = windows_pin(V33_REJECTION)
    if pin["sha256"] != V33_REJECTION_SHA256:
        raise RuntimeError("frozen v33 rejection hash mismatch")
    return pin


def v33_rejection_review_pin() -> dict[str, Any]:
    pin = windows_pin(V33_REJECTION_REVIEW)
    if pin["sha256"] != FORENSIC_REVIEW_SHA256:
        raise RuntimeError("frozen v33 rejection review hash mismatch")
    return pin


def validate_rejection_semantics() -> tuple[dict[str, Any], dict[str, Any]]:
    rejection = strict_json(V33_REJECTION)
    review = strict_json(V33_REJECTION_REVIEW)
    if (
        rejection.get("schema") != "planora.muni-v33.terminal-gate-rejection.v1"
        or rejection.get("status") != "REJECTED_TERMINAL_GATE_INVOCATION_CONSUMED"
        or rejection.get("run_id") != V33_RUN_ID
        or rejection.get("decision") != "NO_RETRY_BUILD_NEW_SUCCESSOR"
        or rejection.get("automatic_retry_authorized") is not False
        or rejection.get("receipt_publication_blockers") != []
        or rejection.get("post_failure_state", {}).get("v33_root_state")
        != "UNKNOWN_WSL_DISTRIBUTION_DID_NOT_START"
    ):
        raise RuntimeError("v33 rejection semantics rejected")
    lifecycle = rejection["lifecycle"]
    forbidden_true = (
        "default_runner_invocation_attempted",
        "atomic_claim_creation_attempted",
        "shared_lock_acquisition_attempted",
        "resource_monitor_launch_attempted",
        "canonical_launch_attempted",
        "canonical_suite_executed",
        "pass_publication_attempted",
    )
    if any(bool(lifecycle[name]) for name in forbidden_true):
        raise RuntimeError("v33 rejection lifecycle overclaims execution")
    disposition = rejection["authorization_disposition"]
    if (
        disposition.get("terminal_gate_invocation_authority_exhausted") is not True
        or disposition.get("runner_default_authorization_claim_consumed") is not False
        or disposition.get("runner_authorization_must_not_be_reused") is not True
        or disposition.get("new_successor_run_id_required") is not True
    ):
        raise RuntimeError("v33 authorization disposition rejected")
    if (
        review.get("schema")
        != "planora.muni-v33.terminal-gate-rejection-independent-review.v1"
        or review.get("status") != "GO_FOR_EXACT_V33_REJECTION_CUSTODY"
        or review.get("successor_admission_status")
        != "NO_GO_ACTIVE_HOST_WSL_STORAGE_INSTABILITY"
        or review.get("run_id") != V33_RUN_ID
        or review.get("receipt_publication_blockers") != []
        or len(review.get("successor_admission_blockers", [])) != 4
        or review.get("host_forensics", {})
        .get("causality_limits", {})
        .get("event_141_proves_ubuntu_vhd_root_cause")
        is not False
    ):
        raise RuntimeError("v33 rejection independent review semantics rejected")
    if review["frozen_rejection_pair"]["receipt"] != v33_rejection_receipt_pin():
        raise RuntimeError("independent review rejection pin mismatch")
    if review["frozen_rejection_pair"]["custody_test"] != windows_pin(V33_CUSTODY_TEST):
        raise RuntimeError("independent review custody test pin mismatch")
    return rejection, review


def historic_v28_through_v32_pins(source: str) -> list[dict[str, Any]]:
    contract = extract_contract(source, "v32FailureContractJson")
    rejection_path = REPO / contract["artifacts"]["rejection"]["path"]
    predecessor_rejection = strict_json(rejection_path)
    carried = [
        normalized_pin(pin)
        for pin in predecessor_rejection["predecessor_evidence"]["runtime"][
            "validated_pins"
        ]
    ]
    direct = [
        normalized_pin(pin)
        for group in (
            contract["sources"],
            contract["launch_provenance"],
            contract["artifacts"],
        )
        for pin in group.values()
    ]
    if len(carried) != 61 or len(direct) != 28:
        raise RuntimeError(
            f"historic predecessor partition rejected: {len(carried)} + {len(direct)}"
        )
    rows = carried + direct
    if len(rows) != 89 or len({row["path"] for row in rows}) != 89:
        raise RuntimeError("historic predecessor cardinality rejected")
    return rows


def v33_rejection_rows(rejection: dict[str, Any]) -> list[dict[str, Any]]:
    embedded = [normalized_pin(pin) for pin in rejection["evidence_pins"].values()]
    rows = (
        embedded
        + [normalized_pin(rejection["custody_test_pin"])]
        + [v33_rejection_receipt_pin(), v33_rejection_review_pin()]
    )
    if len(rows) != 12:
        raise RuntimeError("v33 rejection row count rejected")
    return rows


def core_predecessor_contract(source: str | None = None) -> dict[str, Any]:
    runner_bytes = V33_RUNNER.read_bytes()
    if hashlib.sha256(runner_bytes).hexdigest() != V33_RUNNER_SHA256:
        raise RuntimeError("frozen v33 runner hash mismatch")
    decoded_source = runner_bytes.decode("utf-8")
    if source is not None and source != decoded_source:
        raise RuntimeError("v33 runner changed during predecessor construction")
    rejection, review = validate_rejection_semantics()
    historic = historic_v28_through_v32_pins(decoded_source)
    additions = v33_rejection_rows(rejection)
    combined = historic + additions
    counts = Counter(row["path"] for row in combined)
    duplicates = sorted(path for path, count in counts.items() if count > 1)
    if duplicates != [RETAINED_ARCHIVE] or counts[RETAINED_ARCHIVE] != 2:
        raise RuntimeError(f"unexpected predecessor overlap: {duplicates}")
    grouped: dict[str, dict[str, Any]] = {}
    for pin in combined:
        previous = grouped.setdefault(pin["path"], pin)
        if previous != pin:
            raise RuntimeError(f"overlapping pin differs: {pin['path']}")
    rows = list(grouped.values())
    if len(rows) != 100:
        raise RuntimeError(f"v34 core predecessor count rejected: {len(rows)}")
    for pin in rows:
        assert_live_pin(pin)
    ordinary = [pin for pin in rows if pin["path"] != RETAINED_ARCHIVE]
    archive = [pin for pin in rows if pin["path"] == RETAINED_ARCHIVE]
    if len(ordinary) != 99 or len(archive) != 1:
        raise RuntimeError("v34 guardable/archive partition rejected")
    rows_json = json.dumps(rows, separators=(",", ":"))
    canonical_rows_json = json.dumps(rows, separators=(",", ":"), sort_keys=True)
    canonical_rows_sha256 = hashlib.sha256(
        canonical_rows_json.encode("utf-8")
    ).hexdigest()
    if canonical_rows_sha256 != CORE_ROWS_CANONICAL_SHA256:
        raise RuntimeError("independent canonical v34 predecessor digest rejected")
    return {
        "schema": "planora.muni-v34.draft-core-predecessor-contract.v1",
        "run_id": RUN_ID,
        "historic_rows": len(historic),
        "v33_rejection_rows": len(additions),
        "raw_rows": len(combined),
        "unique_rows": len(rows),
        "ordinary_read_guards": len(ordinary),
        "archive_replay_only": len(archive),
        "single_overlap": RETAINED_ARCHIVE,
        "rows": rows,
        "rows_sha256": hashlib.sha256(rows_json.encode("utf-8")).hexdigest(),
        "rows_canonical_sha256": canonical_rows_sha256,
        "v33_direct_rows": additions,
        "v33_rejection": rejection,
        "v33_rejection_review": review,
    }


def load_input_snapshot() -> dict[str, Any]:
    source = V33_RUNNER.read_text("utf-8")
    core = core_predecessor_contract(source)
    return {
        "v33_runner_source": source,
        "v33_runner_sha256": V33_RUNNER_SHA256,
        "core": core,
        "future_host_path_exists": {
            path.relative_to(REPO).as_posix(): path.exists()
            for path in (HOST_READINESS, HOST_READINESS_REVIEW)
        },
    }


def assert_input_snapshot_unchanged(snapshot: dict[str, Any]) -> None:
    if sha256(V33_RUNNER) != snapshot["v33_runner_sha256"]:
        raise RuntimeError("v33 runner changed after draft render")
    for pin in snapshot["core"]["rows"]:
        assert_live_pin(pin)
    expected_host_state = snapshot["future_host_path_exists"]
    live_host_state = {
        path.relative_to(REPO).as_posix(): path.exists()
        for path in (HOST_READINESS, HOST_READINESS_REVIEW)
    }
    if live_host_state != expected_host_state:
        raise RuntimeError(
            "future host-readiness path state changed after draft render"
        )


def replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"anchor count {count}, expected 1: {old[:120]!r}")
    return source.replace(old, new, 1)


def replace_count(source: str, old: str, new: str, expected: int) -> str:
    count = source.count(old)
    if count != expected:
        raise RuntimeError(f"anchor count {count}, expected {expected}: {old[:120]!r}")
    return source.replace(old, new)


def replace_region(source: str, start: str, end: str, replacement: str) -> str:
    start_index = source.find(start)
    if start_index < 0:
        raise RuntimeError(f"start anchor missing: {start[:120]!r}")
    end_index = source.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"end anchor missing: {end[:120]!r}")
    return source[:start_index] + replacement + source[end_index:]


def v33_runtime_contract(core: dict[str, Any]) -> dict[str, Any]:
    def row(path: Path) -> dict[str, Any]:
        relative = path.relative_to(REPO).as_posix()
        matches = [pin for pin in core["v33_direct_rows"] if pin["path"] == relative]
        if len(matches) != 1:
            raise RuntimeError(f"v33 direct pin lookup rejected: {relative}")
        return matches[0]

    rejection = core["v33_rejection"]
    review = core["v33_rejection_review"]
    direct_json = json.dumps(core["v33_direct_rows"], separators=(",", ":"))
    return {
        "schema": "planora.muni-v34.v33-terminal-gate-rejection-contract.v1",
        "run_id": V33_RUN_ID,
        "successor_run_id": RUN_ID,
        "rejection_pin": row(V33_REJECTION),
        "custody_test_pin": row(V33_CUSTODY_TEST),
        "independent_review_pin": row(V33_REJECTION_REVIEW),
        "evidence_pins": rejection["evidence_pins"],
        "direct_rows": core["v33_direct_rows"],
        "direct_rows_sha256": hashlib.sha256(direct_json.encode("utf-8")).hexdigest(),
        "direct_rows_count": 12,
        "unique_addition_count": 11,
        "historic_base_count": 89,
        "complete_unique_count": 100,
        "ordinary_read_guard_count": 99,
        "archive_replay_only_count": 1,
        "archive_path": RETAINED_ARCHIVE,
        "complete_rows_sha256": core["rows_sha256"],
        "complete_rows_canonical_sha256": core["rows_canonical_sha256"],
        "rejection_schema": rejection["schema"],
        "rejection_status": rejection["status"],
        "rejection_decision": rejection["decision"],
        "unknown_root_state": rejection["post_failure_state"]["v33_root_state"],
        "canonical_namespace_prefix": rejection["post_failure_state"][
            "canonical_namespace_prefix"
        ],
        "review_schema": review["schema"],
        "review_status": review["status"],
        "review_successor_status": review["successor_admission_status"],
        "automatic_retry_authorized": False,
    }


PASS_ABSENCE_FUNCTION = r"""function Assert-V28V29V30V31V32V33PassEvidenceAbsent([string]$Phase){
    $result=[ordered]@{phase=$Phase;v28_receipt_absent=(-not(Test-Path -LiteralPath $v28ReceiptPath));v28_seal_absent=(-not(Test-Path -LiteralPath $v28PassSealPath));v29_receipt_absent=(-not(Test-Path -LiteralPath $v29ReceiptPath));v29_seal_absent=(-not(Test-Path -LiteralPath $v29PassSealPath));v30_receipt_absent=(-not(Test-Path -LiteralPath $v30ReceiptPath));v30_seal_absent=(-not(Test-Path -LiteralPath $v30PassSealPath));v31_receipt_absent=(-not(Test-Path -LiteralPath $v31ReceiptPath));v31_seal_absent=(-not(Test-Path -LiteralPath $v31PassSealPath));v32_receipt_absent=(-not(Test-Path -LiteralPath $v32ReceiptPath));v32_seal_absent=(-not(Test-Path -LiteralPath $v32PassSealPath));v33_receipt_absent=(-not(Test-Path -LiteralPath $v33ReceiptPath));v33_seal_absent=(-not(Test-Path -LiteralPath $v33PassSealPath));observed_at_utc=[DateTime]::UtcNow.ToString('o')}
    foreach($property in @('v28_receipt_absent','v28_seal_absent','v29_receipt_absent','v29_seal_absent','v30_receipt_absent','v30_seal_absent','v31_receipt_absent','v31_seal_absent','v32_receipt_absent','v32_seal_absent','v33_receipt_absent','v33_seal_absent')){if(-not[bool]$result[$property]){throw "v28/v29/v30/v31/v32/v33 PASS evidence unexpectedly exists: $Phase ($property)"}}
    return $result
}
"""


V33_TERMINAL_AND_COMPLETE_FUNCTIONS = r"""function Get-ValidatedV33TerminalGateRejectionEvidence([bool]$RequireSharedLockAbsent){
    $c=$v33TerminalGateRejectionContractJson|ConvertFrom-Json
    if($c.schema-cne'planora.muni-v34.v33-terminal-gate-rejection-contract.v1'-or$c.run_id-cne'2339df35f57e441a8f92bd1f890fa68f'-or$c.successor_run_id-cne$runId-or$c.direct_rows_count-ne12-or$c.unique_addition_count-ne11-or$c.historic_base_count-ne89-or$c.complete_unique_count-ne100-or$c.ordinary_read_guard_count-ne99-or$c.archive_replay_only_count-ne1-or[bool]$c.automatic_retry_authorized){throw 'v33 terminal rejection contract header rejected'}
    $rows=@($c.direct_rows);if($rows.Count-ne12){throw 'v33 terminal rejection direct row cardinality rejected'}
    $archiveRows=@($rows|Where-Object{$_.path-ceq$c.archive_path});if($archiveRows.Count-ne1){throw 'v33 terminal rejection archive row cardinality rejected'}
    $directUnique=@();foreach($pin in $rows){$prior=@($directUnique|Where-Object{$_.path-ceq$pin.path});if($prior.Count-eq0){$directUnique+=,$pin}elseif($prior.Count-ne1-or(ConvertTo-JsonTokenStream ($prior[0]|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($pin|ConvertTo-Json -Depth 8 -Compress))){throw "v33 terminal rejection duplicate pin differs: $($pin.path)"}}
    if($directUnique.Count-ne12){throw 'v33 terminal rejection direct uniqueness rejected'};$unique=@($directUnique|Where-Object{$_.path-cne$c.archive_path});if($unique.Count-ne11){throw 'v33 terminal rejection unique addition cardinality rejected'}
    foreach($pin in $rows){if($pin.path-cne$c.archive_path){[void](Assert-LocalEvidencePin $pin)}}
    [void](Assert-FinalArchivedStaleLockIdentity $archiveRows[0] 'v33_terminal_gate_rejection_validation' $RequireSharedLockAbsent)
    $rejectionPath=Join-Path $repo $c.rejection_pin.path.Replace('/','\');$reviewPath=Join-Path $repo $c.independent_review_pin.path.Replace('/','\')
    $rejectionRaw=[IO.File]::ReadAllText($rejectionPath,$utf8);$reviewRaw=[IO.File]::ReadAllText($reviewPath,$utf8);$rejection=$rejectionRaw|ConvertFrom-Json;$review=$reviewRaw|ConvertFrom-Json
    if($rejection.schema-cne$c.rejection_schema-or$rejection.status-cne$c.rejection_status-or$rejection.run_id-cne$c.run_id-or$rejection.decision-cne$c.rejection_decision-or[bool]$rejection.automatic_retry_authorized-or@($rejection.receipt_publication_blockers).Count-ne0-or$rejection.post_failure_state.v33_root_state-cne$c.unknown_root_state-or$rejection.post_failure_state.canonical_namespace_artifact_count-ne0-or[bool]$rejection.post_failure_state.shared_lock_present){throw 'v33 terminal rejection receipt semantics rejected'}
    if(-not[bool]$rejection.authorization_disposition.terminal_gate_invocation_authority_exhausted-or[bool]$rejection.authorization_disposition.runner_default_authorization_claim_consumed-or-not[bool]$rejection.authorization_disposition.runner_authorization_must_not_be_reused-or-not[bool]$rejection.authorization_disposition.new_successor_run_id_required){throw 'v33 exhausted authorization disposition rejected'}
    foreach($property in @('default_runner_invocation_attempted','atomic_claim_creation_attempted','shared_lock_acquisition_attempted','resource_monitor_launch_attempted','canonical_launch_attempted','canonical_suite_executed','pass_publication_attempted')){if([bool]$rejection.lifecycle.$property){throw "v33 terminal rejection lifecycle overclaim: $property"}}
    if($review.schema-cne$c.review_schema-or$review.status-cne$c.review_status-or$review.successor_admission_status-cne$c.review_successor_status-or$review.run_id-cne$c.run_id-or@($review.receipt_publication_blockers).Count-ne0-or@($review.successor_admission_blockers).Count-ne4-or[bool]$review.host_forensics.causality_limits.event_141_proves_ubuntu_vhd_root_cause){throw 'v33 terminal rejection review semantics rejected'}
    if((ConvertTo-JsonTokenStream ($rejection.evidence_pins|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($c.evidence_pins|ConvertTo-Json -Depth 8 -Compress))-or(ConvertTo-JsonTokenStream ($rejection.custody_test_pin|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($c.custody_test_pin|ConvertTo-Json -Depth 8 -Compress))-or(ConvertTo-JsonTokenStream ($review.frozen_rejection_pair.receipt|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($c.rejection_pin|ConvertTo-Json -Depth 8 -Compress))-or(ConvertTo-JsonTokenStream ($review.frozen_rejection_pair.custody_test|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($c.custody_test_pin|ConvertTo-Json -Depth 8 -Compress))){throw 'v33 terminal rejection embedded pin replay rejected'}
    $receiptRows=@($rejection.evidence_pins.PSObject.Properties|ForEach-Object{$_.Value})+@($rejection.custody_test_pin,$c.rejection_pin,$c.independent_review_pin);if((ConvertTo-JsonTokenStream ($receiptRows|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($rows|ConvertTo-Json -Depth 8 -Compress))){throw 'v33 terminal rejection direct row replay rejected'}
    $leaf=$c.canonical_namespace_prefix;$entries=@(Get-ChildItem -LiteralPath (Join-Path $repo 'output\diagnostic-receipts') -Force|Where-Object{$_.Name.StartsWith($leaf,[StringComparison]::Ordinal)});if($entries.Count-ne0){throw 'v33 canonical namespace is no longer empty'}
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){throw 'Shared lock present during v33 terminal rejection validation'}
    $passAbsence=Assert-V28V29V30V31V32V33PassEvidenceAbsent 'v33_terminal_gate_rejection_validation'
    return [ordered]@{schema='planora.muni-v34.validated-v33-terminal-gate-rejection-evidence.v1';status='VALIDATED_EXACT_V33_TERMINAL_GATE_REJECTION_AND_REVIEW';contract=$c;runtime=[ordered]@{validated_pins=$rows;unique_addition_pins=$unique;raw_pin_count=12;unique_addition_count=11;canonical_namespace_artifact_count=$entries.Count;shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));pass_absence=$passAbsence};rejection=[ordered]@{pin=$c.rejection_pin;status=$rejection.status;decision=$rejection.decision;root_state=$rejection.post_failure_state.v33_root_state;terminal_gate_authority_exhausted=$rejection.authorization_disposition.terminal_gate_invocation_authority_exhausted;runner_authorization_must_not_be_reused=$rejection.authorization_disposition.runner_authorization_must_not_be_reused};independent_review=[ordered]@{pin=$c.independent_review_pin;status=$review.status;successor_admission_status=$review.successor_admission_status}}
}
function New-ExpectedCompletePredecessorEvidence{
    $base=New-ExpectedThroughV32PredecessorEvidence;$c=$v33TerminalGateRejectionContractJson|ConvertFrom-Json;$base.status='EXPECTED_UNVALIDATED_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY';$base['v33_terminal_gate_rejection_evidence']=[ordered]@{schema='planora.muni-v34.expected-v33-terminal-gate-rejection-evidence.v1';status='EXPECTED_UNVALIDATED_EXACT_V33_TERMINAL_GATE_REJECTION_AND_REVIEW';contract=$c;runtime=[ordered]@{expected_direct_rows=12;expected_unique_additions=11;expected_historic_pins=89}};$base.runtime.expected_pin_count=100;return $base
}
function Resolve-CompletePredecessorRejectionEvidence([object]$Current,[object]$Replay){
    $e=$Current;$phase=$(if($null-ne$Replay.phase){[string]$Replay.phase}else{'rejection_publication'});$priorStatus=$(if($null-ne$Current){[string]$Current.status}else{'MISSING'});$errors=@($Replay.errors);$r=$null
    if($Replay.status-ceq'REPLAYED'-and$null-ne$Replay.evidence){$candidate=$Replay.evidence;if($candidate.status-ceq'VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY'-and@($candidate.runtime.validated_pins).Count-eq100){$e=$candidate;$r=[ordered]@{phase=$phase;status='REPLAYED';prior_evidence_status=$priorStatus;evidence_status=$candidate.status;validated_pin_count=100;errors=@()}}else{$errors+=,'Complete predecessor rejection replay promotion rejected'}}elseif($Replay.status-ceq'REPLAYED'){$errors+=,'Complete predecessor rejection replay evidence missing'}
    if($null-eq$r){if($errors.Count-eq0){$errors+=,"Complete predecessor rejection replay status rejected: $($Replay.status)"};$r=[ordered]@{phase=$phase;status='REPLAY_ERRORS_RECORDED';prior_evidence_status=$priorStatus;errors=$errors}}
    if($null-eq$e-or$null-eq$e.v31_failure_evidence-or$null-eq$e.v32_failure_evidence-or$null-eq$e.v33_terminal_gate_rejection_evidence){$errors=@($r.errors)+@('Complete predecessor rejection fallback evidence missing');$e=New-ExpectedCompletePredecessorEvidence;$r=[ordered]@{phase=$phase;status='REPLAY_ERRORS_RECORDED';prior_evidence_status=$priorStatus;errors=$errors}}
    $v31Hash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e.v31_failure_evidence|ConvertTo-Json -Depth 70 -Compress));$v32Hash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e.v32_failure_evidence|ConvertTo-Json -Depth 70 -Compress));$v33Hash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e.v33_terminal_gate_rejection_evidence|ConvertTo-Json -Depth 70 -Compress));$e['rejection_replay']=$r;$eHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e|ConvertTo-Json -Depth 70 -Compress));return [ordered]@{evidence=$e;replay=$r;v31_failure_evidence_sha256=$v31Hash;v32_failure_evidence_sha256=$v32Hash;v33_terminal_gate_rejection_evidence_sha256=$v33Hash;predecessor_evidence_sha256=$eHash}
}
function Get-ValidatedCompletePredecessorEvidence([bool]$RequireSharedLockAbsent){
    $base=Get-ValidatedThroughV32PredecessorEvidence $RequireSharedLockAbsent;$v33=Get-ValidatedV33TerminalGateRejectionEvidence $RequireSharedLockAbsent;$basePins=@($base.runtime.validated_pins);$direct=@($v33.runtime.validated_pins);if($basePins.Count-ne89-or$direct.Count-ne12){throw 'v33 predecessor partition cardinality rejected'}
    $overlap=@($direct|Where-Object{$basePins.path-ccontains$_.path});if($overlap.Count-ne1-or$overlap[0].path-cne$v33.contract.archive_path){throw 'v33 predecessor overlap rejected'};$baseArchive=@($basePins|Where-Object{$_.path-ceq$v33.contract.archive_path});if($baseArchive.Count-ne1-or(ConvertTo-JsonTokenStream ($baseArchive[0]|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($overlap[0]|ConvertTo-Json -Depth 8 -Compress))){throw 'v33 predecessor archive overlap identity differs'}
    $all=@();foreach($pin in @($basePins)+@($direct)){if(@($all|Where-Object{$_.path-ceq$pin.path}).Count-eq0){$all+=,$pin}};if($all.Count-ne100-or@($all.path|Sort-Object -Unique).Count-ne100){throw 'complete v34 predecessor pin cardinality rejected'}
    $base.status='VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY';$base['v33_terminal_gate_rejection_evidence']=$v33;$base.runtime.validated_pins=$all;$base.runtime.pass_absence=Assert-V28V29V30V31V32V33PassEvidenceAbsent 'complete_predecessor_validation';return $base
}
function Get-CompletePredecessorPinArray([object]$Evidence){if($null-eq$Evidence-or$Evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY'){throw 'Complete v34 predecessor evidence is not replay-ready'};return @($Evidence.runtime.validated_pins)}
function Get-NonThrowingCompletePredecessorReplay([object]$Evidence,[object]$ArchivePin){try{return [ordered]@{phase='rejection_publication';status='REPLAYED';evidence=(Get-ValidatedCompletePredecessorEvidence $false);prior_evidence_status=$Evidence.status;errors=@()}}catch{return [ordered]@{phase='rejection_publication';status='REPLAY_ERRORS_RECORDED';evidence=$null;prior_evidence_status=$Evidence.status;errors=@($_.Exception.Message)}}}

"""


def draft_manifest(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    current = snapshot if snapshot is not None else load_input_snapshot()
    core = current["core"]
    future_host_path_exists = current["future_host_path_exists"]
    missing_host_paths = [
        relative for relative, exists in future_host_path_exists.items() if not exists
    ]
    return {
        "schema": "planora.muni-v34.successor-draft.v1",
        "status": "MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING",
        "candidate": "muni_v34",
        "run_id": RUN_ID,
        "host_admission_id": HOST_ADMISSION_ID,
        "build_ready": False,
        "claim_grade_ready": False,
        "performance_claims_authorized": False,
        "core_predecessor_paths": core["unique_rows"],
        "ordinary_predecessor_read_guards": core["ordinary_read_guards"],
        "archive_replay_only_paths": core["archive_replay_only"],
        "core_predecessor_rows_sha256": core["rows_sha256"],
        "core_predecessor_rows_canonical_sha256": core["rows_canonical_sha256"],
        "v33_rejection_receipt_sha256": V33_REJECTION_SHA256,
        "v33_rejection_review_sha256": FORENSIC_REVIEW_SHA256,
        "v33_rejection_custody_test_sha256": V33_CUSTODY_TEST_SHA256,
        "operational_predecessor_contract_embedded": True,
        "future_direct_host_readiness_pins": 2,
        "authorization_schema_target": "planora.itc2019.canonical-test-authorization.v14",
        "expected_final_protected_guards": 106,
        "expected_final_total_guards": 108,
        "missing_host_paths": missing_host_paths,
        "frozen_forensic_review_sha256": FORENSIC_REVIEW_SHA256,
        "automatic_retry_authorized": False,
        "wsl_executed": False,
        "canonical_suite_executed": False,
        "final_artifacts_written": False,
    }


def render_draft_runner(snapshot: dict[str, Any] | None = None) -> str:
    current = snapshot if snapshot is not None else load_input_snapshot()
    core = current["core"]
    manifest = draft_manifest(current)
    source = current["v33_runner_source"]
    source = replace_count(source, V33_RUN_ID, RUN_ID, expected=V33_RUN_ID_TOKEN_COUNT)
    source = replace_count(source, "v33", "v34", expected=V33_LOWER_TOKEN_COUNT)
    source = replace_count(source, "V33", "V34", expected=V33_UPPER_TOKEN_COUNT)
    source = replace_once(
        source,
        "[switch]$ResourceMonitorReadinessSelfTest)",
        "[switch]$ResourceMonitorReadinessSelfTest,"
        "[switch]$HostReadinessBindingSelfTest,"
        "[switch]$PredecessorBindingSelfTest)",
    )

    v33_top = r"""
$v33Prefix = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v33-canonical-readonly-tests-2339df35f57e441a8f92bd1f890fa68f'
$v33ReceiptPath = $v33Prefix+'.receipt.json'
$v33PassSealPath = $v33Prefix+'.pass-publication-shutdown-seal.json'
$v33TerminalGateRejectionPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v33-terminal-gate-rejection-20260830T000900Z.receipt.json'
$v33TerminalGateRejectionReviewPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v33-terminal-gate-rejection-independent-review-20260830T002100Z.receipt.json'
"""
    top_anchor = (
        "$v32StagingInventoryWsl = "
        "'/mnt/d/Stuff/Projects/Sites/Planora/output/diagnostic-receipts/"
        "muni-fspsx-v32-canonical-readonly-tests-"
        "4dc45edcd74446909290afadd5d3ecf0.staging-inventory.json'"
    )
    source = replace_once(source, top_anchor, top_anchor + v33_top)

    runtime_contract_json = json.dumps(
        v33_runtime_contract(core), separators=(",", ":")
    )
    source = replace_once(
        source,
        "'@\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
        "'@\n$v33TerminalGateRejectionContractJson = @'\n"
        + runtime_contract_json
        + "\n'@\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
    )

    source = replace_region(
        source,
        "function Assert-V28V29V30V31V32PassEvidenceAbsent([string]$Phase){",
        "function Assert-RetainedArchivePin",
        PASS_ABSENCE_FUNCTION,
    )
    source = replace_count(
        source,
        "Assert-V28V29V30V31V32PassEvidenceAbsent",
        "Assert-V28V29V30V31V32V33PassEvidenceAbsent",
        expected=7,
    )

    region_start = "function New-ExpectedCompletePredecessorEvidence{"
    region_end = "function Invoke-LockSelfReadRegressionModel{"
    start_index = source.find(region_start)
    end_index = source.find(region_end, start_index)
    if start_index < 0 or end_index < 0:
        raise RuntimeError("v33 complete predecessor function region missing")
    through_v32 = source[start_index:end_index]
    renames = {
        "New-ExpectedCompletePredecessorEvidence": "New-ExpectedThroughV32PredecessorEvidence",
        "Resolve-CompletePredecessorRejectionEvidence": "Resolve-ThroughV32PredecessorRejectionEvidence",
        "Get-ValidatedCompletePredecessorEvidence": "Get-ValidatedThroughV32PredecessorEvidence",
        "Get-CompletePredecessorPinArray": "Get-ThroughV32PredecessorPinArray",
        "Get-NonThrowingCompletePredecessorReplay": "Get-NonThrowingThroughV32PredecessorReplay",
    }
    for old, new in renames.items():
        through_v32 = through_v32.replace(old, new)
    source = (
        source[:start_index]
        + through_v32
        + V33_TERMINAL_AND_COMPLETE_FUNCTIONS
        + source[end_index:]
    )

    source = replace_once(
        source,
        "$predecessorPins=@(Get-CompletePredecessorPinArray $predecessorEvidence);"
        "if($predecessorPins.Count-ne89){throw 'Complete predecessor pin cardinality rejected'}",
        "$predecessorPins=@(Get-CompletePredecessorPinArray $predecessorEvidence);"
        "if($predecessorPins.Count-ne100){throw 'Complete predecessor pin cardinality rejected'}",
    )
    source = replace_once(
        source,
        "if(@($predecessorModel.runtime.validated_pins).Count-ne89-or",
        "if(@($predecessorModel.runtime.validated_pins).Count-ne100-or",
    )
    source = replace_once(
        source,
        "$v32FailureEvidenceHash='';$stagingExited=",
        "$v32FailureEvidenceHash='';$v33TerminalGateRejectionEvidenceHash='';"
        "$stagingExited=",
    )
    source = replace_once(
        source,
        "$v32FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream "
        "($predecessorEvidence.v32_failure_evidence|ConvertTo-Json -Depth 40 "
        "-Compress));$predecessorPins=@();",
        "$v32FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream "
        "($predecessorEvidence.v32_failure_evidence|ConvertTo-Json -Depth 40 "
        "-Compress));$v33TerminalGateRejectionEvidenceHash="
        "Get-Utf8StringSha256 (ConvertTo-JsonTokenStream "
        "($predecessorEvidence.v33_terminal_gate_rejection_evidence|"
        "ConvertTo-Json -Depth 40 -Compress));$predecessorPins=@();",
    )
    source = replace_once(
        source,
        "$v32FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream "
        "($predecessorEvidence.v32_failure_evidence|ConvertTo-Json -Depth 40 "
        "-Compress))\n    $legacy=",
        "$v32FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream "
        "($predecessorEvidence.v32_failure_evidence|ConvertTo-Json -Depth 40 "
        "-Compress));$v33TerminalGateRejectionEvidenceHash="
        "Get-Utf8StringSha256 (ConvertTo-JsonTokenStream "
        "($predecessorEvidence.v33_terminal_gate_rejection_evidence|"
        "ConvertTo-Json -Depth 40 -Compress))\n    $legacy=",
    )
    source = replace_once(
        source,
        "v32_failure_evidence_sha256=$v32FailureEvidenceHash;archive_identity_replay=",
        "v32_failure_evidence_sha256=$v32FailureEvidenceHash;"
        "v33_terminal_gate_rejection_evidence="
        "$predecessorEvidence.v33_terminal_gate_rejection_evidence;"
        "v33_terminal_gate_rejection_evidence_sha256="
        "$v33TerminalGateRejectionEvidenceHash;archive_identity_replay=",
    )
    source = replace_once(
        source,
        "$custodyV32RawHash=Get-RawTopLevelJsonObjectPropertyTokenHash $custodyRaw "
        "'v32_failure_evidence';if(",
        "$custodyV32RawHash=Get-RawTopLevelJsonObjectPropertyTokenHash $custodyRaw "
        "'v32_failure_evidence';$custodyV33RawHash="
        "Get-RawTopLevelJsonObjectPropertyTokenHash $custodyRaw "
        "'v33_terminal_gate_rejection_evidence';if(",
    )
    source = replace_once(
        source,
        "-or$custodyV32RawHash-cne$v32FailureEvidenceHash){throw "
        "'Pre-lock predecessor custody replay rejected'}",
        "-or$custodyV32RawHash-cne$v32FailureEvidenceHash-or"
        "$custodyReplay.v33_terminal_gate_rejection_evidence_sha256-cne"
        "$v33TerminalGateRejectionEvidenceHash-or$custodyV33RawHash-cne"
        "$v33TerminalGateRejectionEvidenceHash){throw "
        "'Pre-lock predecessor custody replay rejected'}",
    )
    source = replace_once(
        source,
        "$plan['v32_failure_evidence_sha256']=$v32FailureEvidenceHash;"
        "$plan['predecessor_custody']",
        "$plan['v32_failure_evidence_sha256']=$v32FailureEvidenceHash;"
        "$plan['v33_terminal_gate_rejection_evidence']="
        "$predecessorEvidence.v33_terminal_gate_rejection_evidence;"
        "$plan['v33_terminal_gate_rejection_evidence_sha256']="
        "$v33TerminalGateRejectionEvidenceHash;$plan['predecessor_custody']",
    )
    source = replace_once(
        source,
        "$receipt['v32_failure_evidence_sha256']=$v32FailureEvidenceHash;"
        "$receipt['predecessor_pass_absence_at_publication']",
        "$receipt['v32_failure_evidence_sha256']=$v32FailureEvidenceHash;"
        "$receipt['v33_terminal_gate_rejection_evidence']="
        "$predecessorEvidence.v33_terminal_gate_rejection_evidence;"
        "$receipt['v33_terminal_gate_rejection_evidence_sha256']="
        "$v33TerminalGateRejectionEvidenceHash;"
        "$receipt['predecessor_pass_absence_at_publication']",
    )
    source = replace_count(
        source,
        "v32_failure_evidence_sha256=$v32FailureEvidenceHash;"
        "predecessor_custody_sha256=",
        "v32_failure_evidence_sha256=$v32FailureEvidenceHash;"
        "v33_terminal_gate_rejection_evidence="
        "$predecessorEvidence.v33_terminal_gate_rejection_evidence;"
        "v33_terminal_gate_rejection_evidence_sha256="
        "$v33TerminalGateRejectionEvidenceHash;predecessor_custody_sha256=",
        expected=3,
    )
    source = replace_once(
        source,
        "$v32FailureEvidenceHash=$resolvedPredecessorRejection."
        "v32_failure_evidence_sha256;$predecessorEvidenceHash=",
        "$v32FailureEvidenceHash=$resolvedPredecessorRejection."
        "v32_failure_evidence_sha256;$v33TerminalGateRejectionEvidenceHash="
        "$resolvedPredecessorRejection."
        "v33_terminal_gate_rejection_evidence_sha256;"
        "$predecessorEvidenceHash=",
    )
    source = replace_count(
        source,
        "EXACT_V28_V29_V30_V31_V32_CUSTODY_VALIDATED_BEFORE_V34_LOCK",
        "EXACT_V28_V29_V30_V31_V32_V33_CUSTODY_VALIDATED_BEFORE_V34_LOCK",
        expected=2,
    )
    source = replace_once(
        source,
        "$custodyReplay.predecessor_evidence.status-cne"
        "'VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'",
        "$custodyReplay.predecessor_evidence.status-cne"
        "'VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY'",
    )
    source = replace_once(
        source,
        "$custodyPins.Count-ne89-or@($custodyPins.path|Sort-Object -Unique).Count-ne89",
        "$custodyPins.Count-ne100-or@($custodyPins.path|Sort-Object -Unique).Count-ne100",
    )
    source = replace_once(
        source,
        "$failure.evidence.status-cne"
        "'EXPECTED_UNVALIDATED_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'",
        "$failure.evidence.status-cne"
        "'EXPECTED_UNVALIDATED_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY'",
    )
    source = replace_once(
        source,
        "$success.evidence.status-cne"
        "'VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'",
        "$success.evidence.status-cne"
        "'VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY'",
    )
    source = replace_once(
        source,
        "@($success.evidence.runtime.validated_pins).Count-ne89",
        "@($success.evidence.runtime.validated_pins).Count-ne100",
    )
    source = replace_once(
        source,
        "$success.replay.validated_pin_count-ne89",
        "$success.replay.validated_pin_count-ne100",
    )
    source = replace_count(
        source,
        "$failure.v32_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or",
        "$failure.v32_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or"
        "$failure.v33_terminal_gate_rejection_evidence_sha256-cnotmatch"
        "'^[0-9a-f]{64}$'-or",
        expected=1,
    )
    source = replace_count(
        source,
        "$success.v32_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or",
        "$success.v32_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or"
        "$success.v33_terminal_gate_rejection_evidence_sha256-cnotmatch"
        "'^[0-9a-f]{64}$'-or",
        expected=1,
    )
    source = replace_count(
        source,
        "v32_failure_evidence_sha256=$failure.v32_failure_evidence_sha256;"
        "predecessor_evidence_sha256=",
        "v32_failure_evidence_sha256=$failure.v32_failure_evidence_sha256;"
        "v33_terminal_gate_rejection_evidence_sha256="
        "$failure.v33_terminal_gate_rejection_evidence_sha256;"
        "predecessor_evidence_sha256=",
        expected=1,
    )
    source = replace_count(
        source,
        "v32_failure_evidence_sha256=$success.v32_failure_evidence_sha256;"
        "predecessor_evidence_sha256=",
        "v32_failure_evidence_sha256=$success.v32_failure_evidence_sha256;"
        "v33_terminal_gate_rejection_evidence_sha256="
        "$success.v33_terminal_gate_rejection_evidence_sha256;"
        "predecessor_evidence_sha256=",
        expected=1,
    )
    source = replace_once(
        source,
        "schema='planora.itc2019.canonical-test-authorization.v13'",
        "schema='planora.itc2019.canonical-test-authorization.v14-draft-blocked'",
    )
    source = replace_once(
        source,
        "GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_"
        "AUTHENTICATED_V32_NAMESPACE_PERMISSION_FAILURE",
        "DRAFT_NO_GO_HOST_READINESS_AND_INDEPENDENT_REVIEW_PENDING",
    )
    source = replace_once(
        source,
        "complete_v28_v29_v30_v31_v32_predecessor_evidence_bound_to_plan_pass_"
        "and_all_rejections=$true;all_89_predecessor_file_ids_and_timestamps_"
        "authorized=$true",
        "complete_v28_v29_v30_v31_v32_v33_predecessor_evidence_bound_to_plan_"
        "pass_and_all_rejections=$true;all_100_predecessor_file_ids_and_"
        "timestamps_draft_bound=$true",
    )
    source = replace_once(
        source,
        "v28_v29_v30_v31_v32_pass_absence_replayed_through_final_pass_seal_"
        "publication=$true",
        "v28_v29_v30_v31_v32_v33_pass_absence_replayed_through_final_pass_"
        "seal_publication=$true",
    )

    contract_json = json.dumps(manifest, separators=(",", ":"))
    early = (
        "$v34DraftContractJson = @'\n"
        + contract_json
        + "\n'@\n"
        + "$draftModeCount=0\n"
        + "foreach($draftMode in @($StaticSelfTest,$EmitExpectedAuthorization,"
        + "$LogBridgeSelfTest,$ReadinessPredicateSelfTest,"
        + "$RetainedV30SnapshotSelfTest,$RetainedPredecessorSnapshotsSelfTest,"
        + "$CanonicalMonitorContractSelfTest,$RejectionPromotionSelfTest,"
        + "$ResourceMonitorReadinessSelfTest,$HostReadinessBindingSelfTest,"
        + "$PredecessorBindingSelfTest)){if([bool]$draftMode){$draftModeCount++}}\n"
        + "if($HostReadinessBindingSelfTest-and$draftModeCount-eq1){\n"
        + "    [Console]::Out.WriteLine($v34DraftContractJson)\n"
        + "    return\n"
        + "}\n"
        + "if(-not($PredecessorBindingSelfTest-and$draftModeCount-eq1)){"
        + "throw 'MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING'}\n"
    )
    source = replace_once(
        source,
        "$ErrorActionPreference = 'Stop'\n",
        "$ErrorActionPreference = 'Stop'\n" + early,
    )
    predecessor_self_test = r"""if($PredecessorBindingSelfTest){
    $evidence=Get-ValidatedCompletePredecessorEvidence $true;$pins=@(Get-CompletePredecessorPinArray $evidence);$contract=$v33TerminalGateRejectionContractJson|ConvertFrom-Json;$pinsJson=ConvertTo-JsonTokenStream ($pins|ConvertTo-Json -Depth 8 -Compress);$pinsHash=Get-Utf8StringSha256 $pinsJson
    if($evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY'-or$pins.Count-ne100-or@($pins.path|Sort-Object -Unique).Count-ne100-or$pinsHash-cne$contract.complete_rows_sha256-or@($evidence.v33_terminal_gate_rejection_evidence.runtime.validated_pins).Count-ne12-or@($evidence.v33_terminal_gate_rejection_evidence.runtime.unique_addition_pins).Count-ne11-or-not[bool]$evidence.runtime.pass_absence.v33_receipt_absent-or-not[bool]$evidence.runtime.pass_absence.v33_seal_absent){throw 'v34 predecessor binding self-test rejected'}
    [Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v34.predecessor-binding-self-test.v1';status='PASS';run_id=$runId;validated_pins=$pins.Count;unique_pins=@($pins.path|Sort-Object -Unique).Count;v33_direct_rows=@($evidence.v33_terminal_gate_rejection_evidence.runtime.validated_pins).Count;v33_unique_additions=@($evidence.v33_terminal_gate_rejection_evidence.runtime.unique_addition_pins).Count;complete_rows_sha256=$pinsHash;shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));wsl_executed=$false;canonical_suite_executed=$false;artifacts_written=$false}|ConvertTo-Json -Depth 8 -Compress));return
}
throw 'MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING'
"""
    source = replace_once(
        source,
        "if($ResourceMonitorReadinessSelfTest){",
        predecessor_self_test + "if($ResourceMonitorReadinessSelfTest){",
    )
    if (
        source.count(
            "$canonicalLaunchAttempted=$true;$executionHandle=Start-SafeLoggedProcess"
        )
        != 1
    ):
        raise RuntimeError("draft inherited canonical launch cardinality rejected")
    if "automatic_retry_authorized=$true" in source:
        raise RuntimeError("draft inherited automatic retry authorization")
    barrier_index = source.index("throw 'MUNI_V34_DRAFT_NO_GO_HOST_READINESS_PENDING'")
    for unsafe in (
        "if($EmitExpectedAuthorization)",
        "if($LogBridgeSelfTest)",
        "if($ResourceMonitorReadinessSelfTest)",
        "$lockStream=$null;",
        "$canonicalLaunchAttempted=$true;$executionHandle=Start-SafeLoggedProcess",
    ):
        if source.index(unsafe) <= barrier_index:
            raise RuntimeError(f"draft no-go does not dominate: {unsafe}")
    required_runtime_markers = (
        V33_REJECTION_SHA256,
        V33_CUSTODY_TEST_SHA256,
        FORENSIC_REVIEW_SHA256,
        core["rows_sha256"],
        "Get-ValidatedV33TerminalGateRejectionEvidence",
        "VALIDATED_EXACT_V28_V29_V30_V31_V32_V33_PREDECESSOR_CUSTODY",
        "v33_terminal_gate_rejection_evidence_sha256",
        "predecessorPins.Count-ne100",
        "Assert-V28V29V30V31V32V33PassEvidenceAbsent",
    )
    for marker in required_runtime_markers:
        if marker not in source:
            raise RuntimeError(f"v34 operational predecessor marker missing: {marker}")
    if "/tmp/planora-muni-v33-canonical-tests-" in re.search(
        r"(?s)\$cleanupSource = @'\n(.*?)\n'@", source
    ).group(1):
        raise RuntimeError("draft cleanup can target the unknown v33 root")
    return source


def main() -> int:
    before = {path: path.exists() for path in (V34_RUNNER, V34_AUTH, V34_GATE)}
    if any(before.values()):
        raise RuntimeError("unexpected final v34 artifact already exists")
    snapshot = load_input_snapshot()
    manifest = draft_manifest(snapshot)
    rendered = render_draft_runner(snapshot)
    assert_input_snapshot_unchanged(snapshot)
    manifest["draft_runner_bytes"] = len(rendered.encode("utf-8"))
    manifest["draft_runner_sha256"] = hashlib.sha256(
        rendered.encode("utf-8")
    ).hexdigest()
    after = {path: path.exists() for path in before}
    if before != after or any(after.values()):
        raise RuntimeError("draft builder wrote a forbidden final artifact")
    print(json.dumps(manifest, separators=(",", ":")))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
