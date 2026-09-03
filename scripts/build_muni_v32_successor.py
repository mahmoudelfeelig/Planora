from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
V31_RUN_ID = "5f2d84640f40404a82dd180d7043d9c5"
RUN_ID = "4dc45edcd74446909290afadd5d3ecf0"
CREATED_AT = "2026-08-28T13:01:14Z"
STAMP = "20260828T130114Z"
V31_RUNNER = REPO / "scripts/run_muni_v31_canonical_tests.ps1"
V32_RUNNER = REPO / "scripts/run_muni_v32_canonical_tests.ps1"
V32_TESTS = REPO / "tests/test_run_muni_v32_successor.py"
V32_AUTH = (
    REPO
    / "output/diagnostic-receipts"
    / f"muni-fspsx-v32-canonical-tests-authorization-{STAMP}.receipt.json"
)


def pin(
    path: str,
    size: int,
    sha256: str,
    file_id: str,
    last_write_utc_ticks: int,
) -> dict[str, Any]:
    return {
        "path": path,
        "size": size,
        "sha256": sha256,
        "file_id": file_id,
        "last_write_utc_ticks": last_write_utc_ticks,
    }


V31_SOURCES = {
    "builder": pin(
        "scripts/build_muni_v31_successor.py",
        69_258,
        "c08338a076d08336f704e4fe364cdd15ba78904bbc9b4cdc2a96d262e493079e",
        "0000000000000000000900000017267f",
        639235163968391371,
    ),
    "runner": pin(
        "scripts/run_muni_v31_canonical_tests.ps1",
        238_063,
        "ee8fcdd6cb1fdc03e9e7ac9eb792746239afbb8f9c818fc216427e8dbdd3b71c",
        "0000000000000000000400000017be91",
        639235164588218285,
    ),
    "tests": pin(
        "tests/test_run_muni_v31_successor.py",
        27_636,
        "be3eb15ba49c3c9b0a5ed0c6d579ab0e83775dc054ff3e9e65ffdef48be5c9fb",
        "0000000000000000000200000017be40",
        639235164237482474,
    ),
    "authorization": pin(
        "output/diagnostic-receipts/muni-fspsx-v31-canonical-tests-authorization-20260828T113225Z.receipt.json",
        20_872,
        "8b1530c6afb5ef0dd0e1469ab69d798e91c70fe2070956517a6f164ec8c4d6ff",
        "0000000000000000000300000017be92",
        639235164595640475,
    ),
}

V31_PROVENANCE = {
    "independent_review": pin(
        "output/diagnostic-receipts/muni-fspsx-v31-independent-review-20260828T-final.receipt.json",
        5_988,
        "ce446aa17a55b7e4fc4259cde8916b1205bcd4a5fe9065dfb778810a63bec1ed",
        "0000000000000000000400000017be5c",
        639235169407805911,
    ),
    "terminal_gate": pin(
        "scripts/run_muni_v31_terminal_gate_once.ps1",
        13_714,
        "e079620b52b8b6b2684dc97390105d4d7a14b68daf8c4c6e6ced7acb3fe933ee",
        "0000000000000000000400000017be62",
        639235174873750374,
    ),
}

V31_PREFIX = (
    f"output/diagnostic-receipts/muni-fspsx-v31-canonical-readonly-tests-{V31_RUN_ID}"
)
V31_ARTIFACTS = {
    "claim": pin(
        f"{V31_PREFIX}.claim.json",
        541,
        "3f22ab20a950b5b67e2d74953a308586917ace21115a151d133de4a6bec3b1b1",
        "0000000000000000000e00000017266d",
        639235181565649542,
    ),
    "heavy_lock_release": pin(
        f"{V31_PREFIX}.heavy-lock-release.json",
        460,
        "9b7a34fd1f3e182a5bd8dbffc56ec114d12e0ad2cf0144c9b60c55cce8184e22",
        "0000000000000000000400000017bfe2",
        639235182142640210,
    ),
    "heavy_lock": pin(
        f"{V31_PREFIX}.heavy-lock.json",
        2_402,
        "bf713a6c9cba5390b2773a54fb924785117eaabee8ca520c16ba675ae2427d7b",
        "0000000000000000000200000017bfe4",
        639235181616266225,
    ),
    "watch_error": pin(
        f"{V31_PREFIX}.mutation-watch.error.log",
        179,
        "608ec8ead061d977f88c3aafe366cc8f51a2851e095590b9947dc3b1403c503d",
        "0000000000000000000200000017bfe6",
        639235182102330106,
    ),
    "watch_log": pin(
        f"{V31_PREFIX}.mutation-watch.jsonl",
        44_163,
        "3227810831809c1aee32f5c22c04afdf9c93b10019cd26b55bfaeb48fb1935f1",
        "0000000000000000000200000017bfe5",
        639235182090755839,
    ),
    "watch_stop": pin(
        f"{V31_PREFIX}.mutation-watch.stop",
        146,
        "1984fc0fe16459721375791ca6a7234c5c45770479479b100e74cb7c3dba4565",
        "0000000000000000000200000017bfff",
        639235182101946382,
    ),
    "watch_wrapper_stderr": pin(
        f"{V31_PREFIX}.mutation-watch.wrapper.stderr.log",
        218,
        "7e860067f2756a2196e9396d05307695fd14197d1a22029e70cc3e55f3ce1d84",
        "0000000000000000000200000017c001",
        639235182102765160,
    ),
    "watch_wrapper_stdout": pin(
        f"{V31_PREFIX}.mutation-watch.wrapper.stdout.log",
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "0000000000000000000200000017c000",
        639235182102745169,
    ),
    "pre_inventory": pin(
        f"{V31_PREFIX}.pre-inventory.json",
        847_403,
        "e184534d26b0ec73670688726c02cf0b4d3c532213660f678b0dd99713c4438d",
        "0000000000000000000200000017bffe",
        639235182096641147,
    ),
    "predecessor_custody": pin(
        f"{V31_PREFIX}.predecessor-custody.json",
        1_050_136,
        "0f85a09b20fdc1ad9998f7487c4dd74044a46c232fb4c7a0ae016eb730e763e6",
        "0000000000000000000500000017bfe1",
        639235181608753716,
    ),
    "rejection": pin(
        f"{V31_PREFIX}.rejection.json",
        634_441,
        "a52cc1deb06e20b535b6feda80e950825cc79772c6c4dc69d9945359c042e3b6",
        "0000000000000000000200000017c002",
        639235182142455088,
    ),
    "retained_v30_snapshot_custody": pin(
        f"{V31_PREFIX}.retained-v30-snapshot-custody.json",
        1_433,
        "8778df173746d78f6d98b6abe46ec5aedd808b0643503fac905a669a8b7c3d57",
        "0000000000000000000200000017bfe3",
        639235181615399642,
    ),
    "staging_inventory": pin(
        f"{V31_PREFIX}.staging-inventory.json",
        847_403,
        "e184534d26b0ec73670688726c02cf0b4d3c532213660f678b0dd99713c4438d",
        "0000000000000000000200000017bffd",
        639235182067042604,
    ),
    "static_evidence": pin(
        f"{V31_PREFIX}.static-adversarial.json",
        2_916,
        "d21cf2fb37625912a95c8e2250d2297dd1ad75bb8c9737a52761253087db4ab2",
        "0000000000000000000700000017bfe0",
        639235181607256270,
    ),
}

V31_EXPECTED_ABSENT_SUFFIXES = [
    "receipt.json",
    "pass-publication-shutdown-seal.json",
    "rejection-emergency.json",
    "post-inventory.json",
    "plan.json",
    "stdout.log",
    "stderr.log",
    "exit-code.txt",
    "acceptance-commitment.json",
    "cleanup.json",
    "mutation-watch.cleanup.json",
    "resource-exclusivity.jsonl",
    "resource-exclusivity.error.log",
    "resource-exclusivity.stop",
    "resource-exclusivity.wrapper.stdout.log",
    "resource-exclusivity.wrapper.stderr.log",
    "retained-v30-snapshot-terminal-custody.json",
]

V31_FAILURE_CONTRACT = {
    "schema": "planora.muni-v32.v31-failure-custody-contract.v1",
    "run_id": V31_RUN_ID,
    "sources": V31_SOURCES,
    "launch_provenance": V31_PROVENANCE,
    "artifacts": V31_ARTIFACTS,
    "artifact_count": 14,
    "carried_predecessor_pin_count": 41,
    "initial_predecessor_evidence_sha256": (
        "4c6163f21641007f36a595cc42e274ca2dc2730d97b0d626030a1a024d9e8f96"
    ),
    "post_rejection_predecessor_evidence_sha256": (
        "2ca92e886f0da1c6864abd3342fab6a5f8d71617c8d09f389fa0be6f54453ce6"
    ),
    "failure": {
        "status": "REJECTED_AUTHORIZATION_CONSUMED",
        "message": (
            "Canonical monitor argv boundaries rejected; "
            "watcher_stop=Watcher wrapper rejected: exit=1"
        ),
        "phase": "after_preinventory_before_resource_monitor_and_canonical_launch",
        "primary_root_cause": (
            "PowerShell_pipeline_output_contamination_from_unsuppressed_"
            "Assert_CanonicalArguments_true"
        ),
        "canonical_atom_count": 253,
        "polluted_output_count": 254,
        "polluted_first_type": "System.Boolean",
        "expected_timeout_index": 3,
        "polluted_timeout_index": 4,
        "expected_bwrap_index": 7,
        "polluted_bwrap_index": 8,
        "expected_python_index": 248,
        "resource_launch_attempted": False,
        "canonical_launch_attempted": False,
        "canonical_suite_executed": False,
        "automatic_retry_authorized": False,
    },
    "snapshot": {
        "root": f"/tmp/planora-muni-v31-canonical-tests-{V31_RUN_ID}",
        "inventory": V31_ARTIFACTS["staging_inventory"],
        "pre_inventory": V31_ARTIFACTS["pre_inventory"],
        "files": 3_146,
        "directories": 368,
        "bytes": 190_900_047,
        "retained_for_forensics": True,
        "must_not_be_reused_or_deleted_by_v32": True,
    },
    "predecessor_custody_status": (
        "EXACT_V28_V29_V30_CUSTODY_VALIDATED_BEFORE_V31_LOCK"
    ),
    "retained_v30_snapshot": {
        "root": (
            "/tmp/planora-muni-v30-canonical-tests-e358bc6417224fe6a329ad3775853f01"
        ),
        "inventory_sha256": (
            "b596146131ff2634d55a7f0907497f2fa44ae438174efcb67ee75023ecdb50bb"
        ),
        "files": 3_146,
        "directories": 368,
        "bytes": 190_900_047,
        "custody_status": ("EXACT_RETAINED_V30_SNAPSHOT_VALIDATED_WHILE_V31_LOCK_HELD"),
    },
    "expected_absent_suffixes": V31_EXPECTED_ABSENT_SUFFIXES,
    "pass_receipt": f"{V31_PREFIX}.receipt.json",
    "pass_seal": f"{V31_PREFIX}.pass-publication-shutdown-seal.json",
    "core_pin_count_after_merge": 59,
    "pin_count_with_launch_provenance": 61,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"anchor count {count}, expected 1: {old[:160]!r}")
    return text.replace(old, new, 1)


def replace_region(text: str, start: str, end: str, replacement: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"start anchor missing: {start[:160]!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"end anchor missing: {end[:160]!r}")
    return text[:start_index] + replacement + text[end_index:]


def assert_pin(expected: dict[str, Any]) -> None:
    path = REPO / expected["path"]
    stat_result = path.stat()
    if stat_result.st_size != expected["size"] or sha256(path) != expected["sha256"]:
        raise RuntimeError(f"pinned v31 predecessor drift: {path}")
    if os.name != "nt":
        return
    result = subprocess.run(
        ["fsutil.exe", "file", "queryfileid", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"File ID is 0x([0-9a-fA-F]{32})", result.stdout)
    ticks = int(stat_result.st_mtime_ns // 100) + 621355968000000000
    if (
        not match
        or match.group(1).lower() != expected["file_id"]
        or ticks != expected["last_write_utc_ticks"]
    ):
        raise RuntimeError(f"pinned v31 predecessor identity drift: {path}")


V31_FAILURE_FUNCTIONS = r"""function Get-ValidatedV31FailureEvidence{
    $c=$v31FailureContractJson|ConvertFrom-Json;$pins=@()
    foreach($group in @($c.sources,$c.launch_provenance,$c.artifacts)){foreach($property in $group.PSObject.Properties){[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value}}
    if($pins.Count-ne20-or@($pins.path|Sort-Object -Unique).Count-ne20){throw 'v31 direct/provenance pin cardinality rejected'}
    $expected=@($c.artifacts.PSObject.Properties|ForEach-Object{[IO.Path]::GetFullPath((Join-Path $repo $_.Value.path.Replace('/','\')))}|Sort-Object);$leaf=(Split-Path -Leaf $v31Prefix)+'.';$entries=@(Get-ChildItem -LiteralPath (Split-Path -Parent $v31Prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if(@($entries|Where-Object{$_.PSIsContainer}).Count-ne0){throw 'v31 artifact directory rejected'};$observed=@($entries|ForEach-Object{$_.FullName}|Sort-Object);if($entries.Count-ne14-or(ConvertTo-JsonTokenStream ($observed|ConvertTo-Json -Compress))-cne(ConvertTo-JsonTokenStream ($expected|ConvertTo-Json -Compress))){throw 'v31 exact artifact inventory rejected'}
    $claim=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.claim.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$release=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.heavy_lock_release.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$lock=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.heavy_lock.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$authorization=[IO.File]::ReadAllText((Join-Path $repo $c.sources.authorization.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$retainedV30=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.retained_v30_snapshot_custody.path.Replace('/','\')),$utf8)|ConvertFrom-Json
    $rejectionRaw=[IO.File]::ReadAllText($v31RejectionPath,$utf8);$rejection=$rejectionRaw|ConvertFrom-Json;$custodyRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.predecessor_custody.path.Replace('/','\')),$utf8);$custody=$custodyRaw|ConvertFrom-Json;$stageRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.staging_inventory.path.Replace('/','\')),$utf8);$preRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.pre_inventory.path.Replace('/','\')),$utf8);$stage=$stageRaw|ConvertFrom-Json
    if($claim.schema-cne'planora.muni-v31.atomic-run-claim.v2'-or$claim.run_id-cne$c.run_id-or$claim.authorization-cne$c.sources.authorization.path-or$claim.status-cne'CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS'-or-not[bool]$claim.irreversible-or-not[bool]$claim.failure_consumes_authorization-or$claim.default_outcome_on_any_unsealed_failure-cne'REJECTED_AUTHORIZATION_CONSUMED'){throw 'v31 claim semantics rejected'}
    if($rejection.schema-cne'planora.muni-v31.overall-rejection.v6'-or$rejection.run_id-cne$c.run_id-or$rejection.status-cne'REJECTED_AUTHORIZATION_CONSUMED'-or$rejection.failure-cne$c.failure.message-or-not[bool]$rejection.claim_publication_complete-or$rejection.claim_publication_phase-cne'durably_published'-or$rejection.claim_sha256-cne$c.artifacts.claim.sha256-or$rejection.claim_size-ne$c.artifacts.claim.size-or[bool]$rejection.pass_receipt_present-or-not[bool]$rejection.pass_shutdown_seal_absent-or$rejection.acceptance_commitment_sha256-cne''-or-not[bool]$rejection.snapshot_retained_for_forensics-or$rejection.snapshot_root-cne$c.snapshot.root-or$rejection.predecessor_custody_sha256-cne$c.artifacts.predecessor_custody.sha256){throw 'v31 rejection semantics rejected'}
    if(-not[bool]$rejection.lifecycle.staging_exited-or-not[bool]$rejection.lifecycle.watcher_ready-or-not[bool]$rejection.lifecycle.preinventory_started-or[bool]$rejection.lifecycle.resource_launch_attempted-or[bool]$rejection.lifecycle.canonical_launch_attempted-or[bool]$rejection.lifecycle.canonical_started-or[bool]$rejection.lifecycle.canonical_exited){throw 'v31 failure lifecycle rejected'}
    if($release.run_id-cne$c.run_id-or$release.decision-cne'REJECTED'-or-not[bool]$release.same_handle_verified-or-not[bool]$release.delete_on_close-or-not[bool]$release.lock_path_absent-or$release.lock_sha256-cne$lock.lock_sha256){throw 'v31 lock release rejected'}
    if($custody.schema-cne'planora.muni-v31.predecessor-custody.v1'-or$custody.status-cne$c.predecessor_custody_status-or$custody.run_id-cne$c.run_id-or-not[bool]$custody.shared_lock_absent-or$custody.predecessor_evidence_sha256-cne$c.initial_predecessor_evidence_sha256-or$rejection.predecessor_custody_sha256-cne$c.artifacts.predecessor_custody.sha256){throw 'v31 predecessor custody semantics rejected'}
    if($lock.lock.schema-cne'planora.shared-heavy-wsl-lock.v2'-or$lock.lock.run_id-cne$c.run_id-or$lock.lock.authorization_sha256-cne$c.sources.authorization.sha256-or$lock.lock.runner_sha256-cne$c.sources.runner.sha256-or$lock.lock.predecessor_custody_sha256-cne$c.artifacts.predecessor_custody.sha256-or-not[bool]$lock.held_open-or-not[bool]$lock.same_handle_verified-or-not[bool]$lock.delete_on_close-or$lock.predecessor_custody_sha256-cne$c.artifacts.predecessor_custody.sha256-or$lock.retained_v30_snapshot_custody_sha256-cne$c.artifacts.retained_v30_snapshot_custody.sha256-or$lock.predecessor_evidence_sha256-cne$c.initial_predecessor_evidence_sha256){throw 'v31 heavy lock semantics rejected'}
    $v30Replay=$retainedV30.replay;$expectedV30Pin=$rejection.predecessor_evidence.v30_evidence.staging_inventory_pin;if($retainedV30.schema-cne'planora.muni-v31.retained-v30-snapshot-custody.v1'-or$retainedV30.status-cne$c.retained_v30_snapshot.custody_status-or$retainedV30.run_id-cne$c.run_id-or$v30Replay.schema-cne'planora.muni-v31.retained-v30-snapshot-replay.v1'-or$v30Replay.status-cne'EXACT_RETAINED_V30_SNAPSHOT_REPLAY'-or$v30Replay.phase-cne'initial_after_v31_lock'-or$v30Replay.root-cne$c.retained_v30_snapshot.root-or$v30Replay.files-ne$c.retained_v30_snapshot.files-or$v30Replay.directories-ne$c.retained_v30_snapshot.directories-or$v30Replay.bytes-ne$c.retained_v30_snapshot.bytes-or$v30Replay.inventory_sha256-cne$c.retained_v30_snapshot.inventory_sha256-or-not[bool]$v30Replay.all_nlink_one-or(ConvertTo-JsonTokenStream ($retainedV30.source_inventory_pin|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($expectedV30Pin|ConvertTo-Json -Depth 8 -Compress))-or$rejection.retained_v30_snapshot_custody_sha256-cne$c.artifacts.retained_v30_snapshot_custody.sha256-or$rejection.retained_v30_snapshot_custody_pin.sha256-cne$c.artifacts.retained_v30_snapshot_custody.sha256){throw 'v31 retained v30 custody semantics rejected'}
    if($authorization.schema-cne'planora.itc2019.canonical-test-authorization.v11'-or$authorization.test_id-cne$c.run_id-or$authorization.candidate-cne'muni_v31'-or[bool]$authorization.automatic_retry_authorized-or$authorization.runner.sha256-cne$c.sources.runner.sha256-or$authorization.successor_admission.builder.sha256-cne$c.sources.builder.sha256-or$authorization.successor_admission.tests.sha256-cne$c.sources.tests.sha256){throw 'v31 authorization rejected'}
    $initialHash=Get-RawJsonObjectPropertyTokenHash $custodyRaw 'predecessor_evidence';$postHash=Get-RawJsonObjectPropertyTokenHash $rejectionRaw 'predecessor_evidence';if($custody.predecessor_evidence_sha256-cne$c.initial_predecessor_evidence_sha256-or$initialHash-cne$c.initial_predecessor_evidence_sha256-or$rejection.predecessor_evidence_sha256-cne$c.post_rejection_predecessor_evidence_sha256-or$postHash-cne$c.post_rejection_predecessor_evidence_sha256-or$rejection.predecessor_rejection_replay.status-cne'REPLAYED'-or@($rejection.predecessor_rejection_replay.errors).Count-ne0){throw 'v31 carried predecessor evidence rejected'}
    $priorPins=@($rejection.predecessor_evidence.runtime.validated_pins);if($priorPins.Count-ne41-or@($priorPins.path|Sort-Object -Unique).Count-ne41){throw 'v31 carried pin cardinality rejected'}
    if($stage.schema-cne'planora.muni-v31.snapshot-inventory.v1'-or$stage.root-cne$c.snapshot.root-or$stage.file_count-ne$c.snapshot.files-or$stage.directory_count-ne$c.snapshot.directories-or$stage.total_bytes-ne$c.snapshot.bytes-or(ConvertTo-JsonTokenStream $stageRaw)-cne(ConvertTo-JsonTokenStream $preRaw)){throw 'v31 retained inventory semantics rejected'}
    $watchRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_log.path.Replace('/','\')),$utf8);$watchRows=@($watchRaw.TrimEnd("`n").Split("`n")|ForEach-Object{$_|ConvertFrom-Json});if($watchRows.Count-ne201-or$watchRows[0].kind-cne'ARMED'-or$watchRows[-1].kind-cne'READY'-or@($watchRows|Where-Object{$_.kind-ceq'STAGING_EVENT'}).Count-ne199-or$watchRows[-1].root-cne$c.snapshot.root-or-not[bool]$watchRows[-1].watch_started_before_staging-or-not[bool]$watchRows[-1].parent_watch_active-or$watchRows[-1].staging_event_count-ne199-or$watchRows[-1].file_count-ne$c.snapshot.files-or$watchRows[-1].inventory_sha256-cne$c.artifacts.staging_inventory.sha256-or-not[bool]$watchRows[-1].all_nlink_one-or-not[bool]$watchRows[-1].device_inode_frozen-or$watchRows[-1].parent_watch_loss_events-ne0){throw 'v31 watcher failure-phase evidence rejected'}
    $watchError=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_error.path.Replace('/','\')),$utf8);$watchWrapper=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_wrapper_stderr.path.Replace('/','\')),$utf8);$watchStop=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_stop.path.Replace('/','\')),$utf8)|ConvertFrom-Json;if($watchError-cnotmatch'watcher stopped before cleanup authorization'-or$watchWrapper-cnotmatch'watcher stopped before cleanup authorization'-or$watchStop.schema-cne'planora.muni-v31.watcher-abort-control.v1'-or$watchStop.run_id-cne$c.run_id){throw 'v31 watcher terminal evidence rejected'}
    foreach($suffix in $c.expected_absent_suffixes){if(Test-Path -LiteralPath ($v31Prefix+'.'+$suffix)){throw "Unexpected v31 artifact exists: $suffix"}}
    $v31RunnerSource=[IO.File]::ReadAllText((Join-Path $repo $c.sources.runner.path.Replace('/','\')),$utf8);if(([regex]::Matches($v31RunnerSource,'(?m)^    Assert-CanonicalArguments \$args \$Legacy$')).Count-ne1-or([regex]::Matches($v31RunnerSource,'(?m)^    \[void\]\(Assert-CanonicalArguments \$args \$Legacy\)$')).Count-ne0){throw 'v31 Boolean pipeline root-cause source witness rejected'}
    $review=[IO.File]::ReadAllText((Join-Path $repo $c.launch_provenance.independent_review.path.Replace('/','\')),$utf8)|ConvertFrom-Json;if($review.status-cne'GO'-or$review.run_id-cne$c.run_id-or@($review.blockers).Count-ne0-or[bool]$review.review_scope.default_runner_execution_performed){throw 'v31 independent review provenance rejected'}
    $gateSource=[IO.File]::ReadAllText((Join-Path $repo $c.launch_provenance.terminal_gate.path.Replace('/','\')),$utf8);if(([regex]::Matches($gateSource,'(?m)^    & \$runner$')).Count-ne1-or$gateSource-cnotmatch'defaultInvocationCount = 1'){throw 'v31 terminal gate provenance rejected'}
    return [ordered]@{schema='planora.muni-v32.validated-v31-failure-evidence.v1';status='VALIDATED_EXACT_V31_FAILURE_AND_LAUNCH_PROVENANCE';contract=$c;runtime=[ordered]@{validated_pins=$pins;carried_predecessor_pins=$priorPins;artifact_count=$entries.Count;pass_absence=(Assert-V28V29V30V31PassEvidenceAbsent 'v31_failure_validation');shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath))};claim=$claim;rejection=[ordered]@{status=$rejection.status;failure=$rejection.failure;lifecycle=$rejection.lifecycle;predecessor_evidence_sha256=$rejection.predecessor_evidence_sha256};snapshot_inventory=$stage}
}
function New-ExpectedCompletePredecessorEvidence{
    $base=New-ExpectedCombinedPredecessorEvidence;$c=$v31FailureContractJson|ConvertFrom-Json;$base.status='EXPECTED_UNVALIDATED_V28_V29_V30_V31_PREDECESSOR_CUSTODY';$base['v31_failure_evidence']=[ordered]@{schema='planora.muni-v32.expected-v31-failure-evidence.v1';status='EXPECTED_UNVALIDATED_EXACT_V31_FAILURE_AND_LAUNCH_PROVENANCE';contract=$c;runtime=[ordered]@{expected_direct_and_provenance_pins=20;expected_carried_pins=41}};$base.runtime.expected_pin_count=61;return $base
}
function Resolve-CompletePredecessorRejectionEvidence([object]$Current,[object]$Replay){
    $e=$Current;$phase=$(if($null-ne$Replay.phase){[string]$Replay.phase}else{'rejection_publication'});$priorStatus=$(if($null-ne$Current){[string]$Current.status}else{'MISSING'});$errors=@($Replay.errors);$r=$null
    if($Replay.status-ceq'REPLAYED'-and$null-ne$Replay.evidence){$candidate=$Replay.evidence;if($candidate.status-ceq'VALIDATED_EXACT_V28_V29_V30_V31_PREDECESSOR_CUSTODY'-and@($candidate.runtime.validated_pins).Count-eq61){$e=$candidate;$r=[ordered]@{phase=$phase;status='REPLAYED';prior_evidence_status=$priorStatus;evidence_status=$candidate.status;validated_pin_count=61;errors=@()}}else{$errors+=,'Complete predecessor rejection replay promotion rejected'}}elseif($Replay.status-ceq'REPLAYED'){$errors+=,'Complete predecessor rejection replay evidence missing'}
    if($null-eq$r){if($errors.Count-eq0){$errors+=,"Complete predecessor rejection replay status rejected: $($Replay.status)"};$r=[ordered]@{phase=$phase;status='REPLAY_ERRORS_RECORDED';prior_evidence_status=$priorStatus;errors=$errors}}
    if($null-eq$e-or$null-eq$e.v31_failure_evidence){$errors=@($r.errors)+@('Complete predecessor rejection fallback evidence missing');$e=New-ExpectedCompletePredecessorEvidence;$r=[ordered]@{phase=$phase;status='REPLAY_ERRORS_RECORDED';prior_evidence_status=$priorStatus;errors=$errors}}
    $v31Hash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e.v31_failure_evidence|ConvertTo-Json -Depth 70 -Compress));$e['rejection_replay']=$r;$eHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e|ConvertTo-Json -Depth 70 -Compress));return [ordered]@{evidence=$e;replay=$r;v31_failure_evidence_sha256=$v31Hash;predecessor_evidence_sha256=$eHash}
}
function Get-ValidatedCompletePredecessorEvidence([bool]$RequireSharedLockAbsent){
    $base=Get-ValidatedCombinedPredecessorEvidence $RequireSharedLockAbsent;$v31=Get-ValidatedV31FailureEvidence;$basePins=@($base.runtime.validated_pins);$carried=@($v31.runtime.carried_predecessor_pins);if((ConvertTo-JsonTokenStream ($basePins|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($carried|ConvertTo-Json -Depth 8 -Compress))){throw 'v31 carried/base predecessor pins differ'};$all=@($basePins)+@($v31.runtime.validated_pins);if($all.Count-ne61-or@($all.path|Sort-Object -Unique).Count-ne61){throw 'complete v32 predecessor pin cardinality rejected'};$base.status='VALIDATED_EXACT_V28_V29_V30_V31_PREDECESSOR_CUSTODY';$base['v31_failure_evidence']=$v31;$base.runtime.validated_pins=$all;$base.runtime.pass_absence=Assert-V28V29V30V31PassEvidenceAbsent 'complete_predecessor_validation';return $base
}
function Get-CompletePredecessorPinArray([object]$Evidence){if($null-eq$Evidence-or$Evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_V31_PREDECESSOR_CUSTODY'){throw 'Complete v32 predecessor evidence is not replay-ready'};return @($Evidence.runtime.validated_pins)}
function Get-NonThrowingCompletePredecessorReplay([object]$Evidence,[object]$ArchivePin){try{return [ordered]@{phase='rejection_publication';status='REPLAYED';evidence=(Get-ValidatedCompletePredecessorEvidence $false);prior_evidence_status=$Evidence.status;errors=@()}}catch{return [ordered]@{phase='rejection_publication';status='REPLAY_ERRORS_RECORDED';evidence=$null;prior_evidence_status=$Evidence.status;errors=@($_.Exception.Message)}}}

"""


PASS_ABSENCE_FUNCTION = r"""function Assert-V28V29V30V31PassEvidenceAbsent([string]$Phase){
    $result=[ordered]@{phase=$Phase;v28_receipt_absent=(-not(Test-Path -LiteralPath $v28ReceiptPath));v28_seal_absent=(-not(Test-Path -LiteralPath $v28PassSealPath));v29_receipt_absent=(-not(Test-Path -LiteralPath $v29ReceiptPath));v29_seal_absent=(-not(Test-Path -LiteralPath $v29PassSealPath));v30_receipt_absent=(-not(Test-Path -LiteralPath $v30ReceiptPath));v30_seal_absent=(-not(Test-Path -LiteralPath $v30PassSealPath));v31_receipt_absent=(-not(Test-Path -LiteralPath $v31ReceiptPath));v31_seal_absent=(-not(Test-Path -LiteralPath $v31PassSealPath));observed_at_utc=[DateTime]::UtcNow.ToString('o')}
    if(-not$result.v28_receipt_absent-or-not$result.v28_seal_absent-or-not$result.v29_receipt_absent-or-not$result.v29_seal_absent-or-not$result.v30_receipt_absent-or-not$result.v30_seal_absent-or-not$result.v31_receipt_absent-or-not$result.v31_seal_absent){throw "v28/v29/v30/v31 PASS evidence unexpectedly exists: $Phase"};return $result
}
"""


CANONICAL_MONITOR_FUNCTION = r"""function New-CanonicalMonitorContract([object[]]$Arguments,[object[]]$Legacy){
    if($Arguments.Count-ne253){throw "Canonical argument count rejected: $($Arguments.Count)"};for($i=0;$i-lt$Arguments.Count;$i++){if($Arguments[$i]-isnot[string]){throw "Canonical non-string argument rejected at index $i"}}
    [string[]]$tokens=@($Arguments);[void](Assert-CanonicalArguments $tokens $Legacy);$timeoutIndex=[Array]::IndexOf($tokens,[string]'/usr/bin/timeout');$bwrapIndex=[Array]::IndexOf($tokens,[string]'/usr/bin/bwrap');$testIndex=$tokens.Count-5;if($timeoutIndex-ne3-or$bwrapIndex-ne7-or$testIndex-ne248-or$tokens[$testIndex]-cne'/usr/bin/python3.12'){throw 'Canonical monitor boundary contract rejected'}
    $digest=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($tokens|ConvertTo-Json -Compress));return [ordered]@{schema='planora.muni-v32.canonical-monitor-contract.v1';argument_count=$tokens.Count;all_arguments_strings=$true;timeout_index=$timeoutIndex;bwrap_index=$bwrapIndex;python_index=$testIndex;timeout_argv=@($tokens[$timeoutIndex..($tokens.Count-1)]);bwrap_argv=@($tokens[$bwrapIndex..($tokens.Count-1)]);test_argv=@($tokens[$testIndex..($tokens.Count-1)]);token_sha256=$digest}
}
"""


RETAINED_V31_FUNCTIONS = r"""function Invoke-RetainedV31SnapshotVerifier([string]$Phase){
    $cfg=[ordered]@{root=$v31SnapshotRoot;expected=$v31StagingInventoryWsl;expected_size=847403;expected_sha256='e184534d26b0ec73670688726c02cf0b4d3c532213660f678b0dd99713c4438d';phase=$Phase};$result=Invoke-BoundedSafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $cfg)) $retainedV30SnapshotVerifierSource "retained v31 snapshot $Phase" 180
    $lines=@($result.stdout.Trim()-split"`r?`n"|Where-Object{$_});if($lines.Count-ne1-or$result.stderr.Length-ne0){throw "Retained v31 snapshot verifier output rejected: $Phase"};$row=$lines[0]|ConvertFrom-Json
    if($row.schema-cne'planora.muni-v32.retained-snapshot-replay.v1'-or$row.status-cne'EXACT_RETAINED_SNAPSHOT_REPLAY'-or$row.phase-cne$Phase-or$row.root-cne$v31SnapshotRoot-or$row.files-ne3146-or$row.directories-ne368-or$row.bytes-ne190900047-or$row.inventory_sha256-cne'e184534d26b0ec73670688726c02cf0b4d3c532213660f678b0dd99713c4438d'-or-not[bool]$row.all_nlink_one){throw "Retained v31 snapshot replay semantics rejected: $Phase"};return $row
}
function Get-NonThrowingRetainedV31SnapshotReplay([string]$Phase){try{return [ordered]@{phase=$Phase;status='REPLAYED';evidence=(Invoke-RetainedV31SnapshotVerifier $Phase);errors=@()}}catch{return [ordered]@{phase=$Phase;status='REPLAY_ERRORS_RECORDED';evidence=$null;errors=@($_.Exception.Message)}}}

"""


def render_runner(
    builder_size: int, builder_hash: str, tests_size: int, tests_hash: str
) -> str:
    for expected in [
        *V31_SOURCES.values(),
        *V31_PROVENANCE.values(),
        *V31_ARTIFACTS.values(),
    ]:
        assert_pin(expected)

    source = V31_RUNNER.read_text(encoding="utf-8")
    source = source.replace(V31_RUN_ID, RUN_ID)
    source = source.replace("v31", "v32").replace("V31", "V32")
    source = source.replace("20260828T113225Z", STAMP)
    source = source.replace("2026-08-28T11:32:25Z", CREATED_AT)
    source = source.replace(
        "complete-v28-v29-v30-predecessor-evidence.v1",
        "complete-v28-v29-v30-v31-predecessor-evidence.v1",
    )
    source = source.replace(
        "planora.muni-v32.retained-v30-snapshot-replay.v1",
        "planora.muni-v32.retained-snapshot-replay.v1",
    ).replace("EXACT_RETAINED_V30_SNAPSHOT_REPLAY", "EXACT_RETAINED_SNAPSHOT_REPLAY")

    source = replace_once(
        source,
        "$ErrorActionPreference = 'Stop'",
        "$ErrorActionPreference = 'Stop'\n$env:COLUMNS='32768';$env:LINES='1000';$env:WSLENV='COLUMNS:LINES'",
    )
    source = replace_once(
        source,
        "[switch]$RetainedV30SnapshotSelfTest)",
        "[switch]$RetainedV30SnapshotSelfTest,[switch]$RetainedPredecessorSnapshotsSelfTest,[switch]$CanonicalMonitorContractSelfTest,[switch]$RejectionPromotionSelfTest)",
    )

    top_anchor = "$v30StagingInventoryWsl = '/mnt/d/Stuff/Projects/Sites/Planora/output/diagnostic-receipts/muni-fspsx-v30-canonical-readonly-tests-e358bc6417224fe6a329ad3775853f01.staging-inventory.json'"
    top_addition = r"""
$v31Prefix = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v31-canonical-readonly-tests-5f2d84640f40404a82dd180d7043d9c5'
$v31ReceiptPath = $v31Prefix+'.receipt.json'
$v31PassSealPath = $v31Prefix+'.pass-publication-shutdown-seal.json'
$v31RejectionPath = $v31Prefix+'.rejection.json'
$v31SnapshotRoot = '/tmp/planora-muni-v31-canonical-tests-5f2d84640f40404a82dd180d7043d9c5'
$v31StagingInventoryWsl = '/mnt/d/Stuff/Projects/Sites/Planora/output/diagnostic-receipts/muni-fspsx-v31-canonical-readonly-tests-5f2d84640f40404a82dd180d7043d9c5.staging-inventory.json'
"""
    source = replace_once(source, top_anchor, top_anchor + top_addition)
    source = replace_once(
        source,
        '$retainedV30SnapshotTerminalCustodyFile = "$prefix.retained-v30-snapshot-terminal-custody.json"',
        '$retainedV30SnapshotTerminalCustodyFile = "$prefix.retained-v30-snapshot-terminal-custody.json"\n$retainedV31SnapshotCustodyFile = "$prefix.retained-v31-snapshot-custody.json"\n$retainedV31SnapshotTerminalCustodyFile = "$prefix.retained-v31-snapshot-terminal-custody.json"',
    )

    contract_json = json.dumps(V31_FAILURE_CONTRACT, separators=(",", ":"))
    source = replace_once(
        source,
        "'@\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
        "'@\n$v31FailureContractJson = @'\n"
        + contract_json
        + "\n'@\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
    )

    source = source.replace(
        "Assert-V28V29V30PassEvidenceAbsent", "Assert-V28V29V30V31PassEvidenceAbsent"
    )
    source = replace_region(
        source,
        "function Assert-V28V29V30V31PassEvidenceAbsent",
        "function Assert-RetainedArchivePin",
        PASS_ABSENCE_FUNCTION,
    )
    source = replace_once(
        source,
        "function Invoke-LockSelfReadRegressionModel{",
        V31_FAILURE_FUNCTIONS + "function Invoke-LockSelfReadRegressionModel{",
    )
    source = source.replace(
        "Get-ValidatedCombinedPredecessorEvidence $true",
        "Get-ValidatedCompletePredecessorEvidence $true",
    )
    source = source.replace(
        "Get-CombinedPredecessorPinArray $predecessorEvidence",
        "Get-CompletePredecessorPinArray $predecessorEvidence",
    )
    source = source.replace(
        "Get-NonThrowingCombinedPredecessorReplay $predecessorEvidence $staleArchivePin",
        "Get-NonThrowingCompletePredecessorReplay $predecessorEvidence $staleArchivePin",
    )
    source = source.replace(
        "'Get-NonThrowingCombinedPredecessorReplay'",
        "'Get-NonThrowingCompletePredecessorReplay $predecessorEvidence $staleArchivePin'",
    )
    source = source.replace(
        "$predecessorPins.Count-ne41", "$predecessorPins.Count-ne61"
    )
    source = source.replace(
        "41_EXACT_IDENTITY_PINS_V28_V29_V30_PLUS_TRIPLE_PASS_ABSENCE_VALIDATED",
        "61_EXACT_IDENTITY_PINS_V28_V29_V30_V31_PLUS_QUADRUPLE_PASS_ABSENCE_VALIDATED",
    )
    source = source.replace(
        "@($predecessorModel.runtime.validated_pins).Count-ne41",
        "@($predecessorModel.runtime.validated_pins).Count-ne61",
    )

    source = replace_once(
        source,
        "    Assert-CanonicalArguments $args $Legacy\n    return $args",
        "    [void](Assert-CanonicalArguments $args $Legacy)\n    return $args",
    )
    source = replace_once(
        source,
        "if($ReadinessPredicateSelfTest){",
        CANONICAL_MONITOR_FUNCTION
        + r"""if($CanonicalMonitorContractSelfTest){
    $auth=Get-AuthorizationState;$legacy=@(Get-LegacyRows);$canonical=@(Get-CanonicalArguments $legacy);$contract=New-CanonicalMonitorContract $canonical $legacy;$polluted=@($true)+@($canonical);$pollutedTimeout=[Array]::IndexOf($polluted,[string]'/usr/bin/timeout');$pollutedBwrap=[Array]::IndexOf($polluted,[string]'/usr/bin/bwrap');$pollutedRejected=$false;$pollutedFailure='';try{[void](New-CanonicalMonitorContract $polluted $legacy)}catch{$pollutedRejected=$true;$pollutedFailure=$_.Exception.Message};$psi=New-SafeStartInfo $wsl $canonical $false;if($polluted.Count-ne254-or$polluted[0]-isnot[bool]-or$pollutedTimeout-ne4-or$pollutedBwrap-ne8-or-not$pollutedRejected-or$pollutedFailure-cne'Canonical argument count rejected: 254'-or$psi.Arguments-cne($canonical-join' ')){throw 'Canonical monitor negative-baseline or render self-test rejected'}
    [Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v32.canonical-monitor-contract-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;fixed=$contract;v31_negative_baseline=[ordered]@{count=$polluted.Count;first_type=$polluted[0].GetType().FullName;timeout_index=$pollutedTimeout;bwrap_index=$pollutedBwrap;contract_rejected=$pollutedRejected;rejection=$pollutedFailure};process_start_info_render='EXACT_JOINED_SAFE_ATOMS_NOT_STARTED';wsl_executed=$false;canonical_suite_executed=$false;shared_lock_used=$false}|ConvertTo-Json -Depth 10 -Compress));return
}
if($RejectionPromotionSelfTest){
    $auth=Get-AuthorizationState;$failureCurrent=New-ExpectedCompletePredecessorEvidence;$failure=Resolve-CompletePredecessorRejectionEvidence $failureCurrent ([ordered]@{phase='injected_early_failure';status='REPLAY_ERRORS_RECORDED';errors=@('injected predecessor validation failure')});$successCurrent=New-ExpectedCompletePredecessorEvidence;$validated=Get-ValidatedCompletePredecessorEvidence $false;$success=Resolve-CompletePredecessorRejectionEvidence $successCurrent ([ordered]@{phase='injected_successful_replay';status='REPLAYED';evidence=$validated;errors=@()});$failureJson=$failure|ConvertTo-Json -Depth 70 -Compress;$successJson=$success|ConvertTo-Json -Depth 70 -Compress
    if($failure.evidence.status-cne'EXPECTED_UNVALIDATED_V28_V29_V30_V31_PREDECESSOR_CUSTODY'-or$failure.replay.status-cne'REPLAY_ERRORS_RECORDED'-or$failure.replay.Contains('evidence')-or$failure.v31_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$failure.predecessor_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$success.evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_V31_PREDECESSOR_CUSTODY'-or@($success.evidence.runtime.validated_pins).Count-ne61-or$success.replay.status-cne'REPLAYED'-or$success.replay.Contains('evidence')-or$success.replay.validated_pin_count-ne61-or$success.v31_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$success.predecessor_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$failureJson.Length-eq0-or$successJson.Length-eq0){throw 'Complete predecessor rejection promotion self-test rejected'}
    [Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v32.rejection-promotion-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;early_failure=[ordered]@{evidence_status=$failure.evidence.status;replay_status=$failure.replay.status;v31_failure_evidence_sha256=$failure.v31_failure_evidence_sha256;predecessor_evidence_sha256=$failure.predecessor_evidence_sha256;json_serialized=$true};successful_replay=[ordered]@{evidence_status=$success.evidence.status;replay_status=$success.replay.status;validated_pin_count=$success.replay.validated_pin_count;v31_failure_evidence_sha256=$success.v31_failure_evidence_sha256;predecessor_evidence_sha256=$success.predecessor_evidence_sha256;json_serialized=$true};wsl_executed=$false;canonical_suite_executed=$false;shared_lock_used=$false;claim_created=$false;v32_artifacts_created=$false}|ConvertTo-Json -Depth 8 -Compress));return
}
if($ReadinessPredicateSelfTest){""",
    )
    source = replace_once(
        source,
        "$canonical=@(Get-CanonicalArguments $rows)\n    $closure=Assert-LocalFrozenClosure",
        "$canonical=@(Get-CanonicalArguments $rows);$canonicalMonitorContract=New-CanonicalMonitorContract $canonical $rows\n    $closure=Assert-LocalFrozenClosure",
    )
    source = replace_once(
        source,
        "canonical_argument_count=$canonical.Count;",
        "canonical_argument_count=$canonical.Count;canonical_monitor_contract=$canonicalMonitorContract;",
    )
    source = replace_once(
        source,
        "$canonical=@(Get-CanonicalArguments $legacy)\n    $watchCfg=",
        "$canonical=@(Get-CanonicalArguments $legacy);$canonicalMonitorContract=New-CanonicalMonitorContract $canonical $legacy\n    $watchCfg=",
    )
    old_boundary = "$timeoutIndex=[Array]::IndexOf($canonical,[string]'/usr/bin/timeout');$bwrapIndex=[Array]::IndexOf($canonical,[string]'/usr/bin/bwrap');$testIndex=$canonical.Count-5\n    if($timeoutIndex-ne3-or$bwrapIndex-ne7-or$testIndex-le$bwrapIndex){throw 'Canonical monitor argv boundaries rejected'}\n    $resourceCfg=[ordered]@{stop=\"$prefixWsl.resource-exclusivity.stop\";log=\"$prefixWsl.resource-exclusivity.jsonl\";error=\"$prefixWsl.resource-exclusivity.error.log\";watcher_pid=$ready.pid;timeout_argv=@($canonical[$timeoutIndex..($canonical.Count-1)]);bwrap_argv=@($canonical[$bwrapIndex..($canonical.Count-1)]);test_argv=@($canonical[$testIndex..($canonical.Count-1)]);minimum_kib=1900000;target_interval_ms=100;maximum_gap_ms=750;subprocess_sites=16}"
    new_boundary = '$resourceCfg=[ordered]@{stop="$prefixWsl.resource-exclusivity.stop";log="$prefixWsl.resource-exclusivity.jsonl";error="$prefixWsl.resource-exclusivity.error.log";watcher_pid=$ready.pid;timeout_argv=$canonicalMonitorContract.timeout_argv;bwrap_argv=$canonicalMonitorContract.bwrap_argv;test_argv=$canonicalMonitorContract.test_argv;minimum_kib=1900000;target_interval_ms=100;maximum_gap_ms=750;subprocess_sites=16;canonical_token_sha256=$canonicalMonitorContract.token_sha256}'
    source = replace_once(source, old_boundary, new_boundary)
    source = replace_once(
        source,
        "subprocess_sites=int(c['subprocess_sites'])",
        "subprocess_sites=int(c['subprocess_sites']);canonical_token_sha256=str(c['canonical_token_sha256'])\nif len(canonical_token_sha256)!=64 or any(ch not in '0123456789abcdef' for ch in canonical_token_sha256): raise RuntimeError('canonical token digest rejected')",
    )
    source = replace_once(
        source,
        "'pinned_subprocess_sites':subprocess_sites});emit(first)",
        "'pinned_subprocess_sites':subprocess_sites,'canonical_token_sha256':canonical_token_sha256});emit(first)",
    )
    source = replace_once(
        source,
        "'pinned_subprocess_sites':subprocess_sites})\nexcept BaseException:",
        "'pinned_subprocess_sites':subprocess_sites,'canonical_token_sha256':canonical_token_sha256})\nexcept BaseException:",
    )
    source = replace_once(
        source,
        "descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'};$cadenceGood=",
        "descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace';canonical_token_sha256=('a'*64)};$cadenceGood=",
    )
    source = replace_once(
        source,
        "$Rows[0].descendant_policy-cne'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'){throw 'Resource monitor cadence contract rejected'}",
        "$Rows[0].descendant_policy-cne'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'-or$Rows[0].canonical_token_sha256-cnotmatch'^[0-9a-f]{64}$'){throw 'Resource monitor cadence contract rejected'}",
    )
    source = replace_once(
        source,
        "$done.maximum_observed_gap_ns-ne$maximum-or$done.admitted_descendant_identities-lt1-or$identityRows.Count-ne$done.admitted_descendant_identities){throw 'Resource monitor final cadence/descendant evidence rejected'}",
        "$done.maximum_observed_gap_ns-ne$maximum-or$done.canonical_token_sha256-cne$Rows[0].canonical_token_sha256-or$done.admitted_descendant_identities-lt1-or$identityRows.Count-ne$done.admitted_descendant_identities){throw 'Resource monitor final cadence/descendant evidence rejected'}",
    )
    source = replace_once(
        source,
        "cadence_claim='bounded_maximum_gap_not_exact_interval'}\n}",
        "cadence_claim='bounded_maximum_gap_not_exact_interval';canonical_token_sha256=$Rows[0].canonical_token_sha256}\n}",
    )
    source = replace_once(
        source,
        "if($resourceSequence-lt1){throw 'Resource monitor did not reach READY with a sample'}",
        "if($resourceSequence-lt1){throw 'Resource monitor did not reach READY with a sample'};$resourceReadyRows=@(Get-ResourceMonitorRows $resourceMonitor.Process);if($resourceReadyRows[0].canonical_token_sha256-cne$canonicalMonitorContract.token_sha256){throw 'Resource monitor canonical token binding rejected'}",
    )
    source = replace_once(
        source,
        "pinned_subprocess_sites=16};timeouts=[ordered]@{",
        "pinned_subprocess_sites=16;canonical_token_sha256=$canonicalMonitorContract.token_sha256};timeouts=[ordered]@{",
    )
    source = replace_once(
        source,
        "launch_namespace_bound=$rows[-1].launch_namespace_bound}\n}",
        "launch_namespace_bound=$rows[-1].launch_namespace_bound;canonical_token_sha256=$cadence.canonical_token_sha256}\n}",
    )
    source = replace_once(
        source,
        "canonical_argv=$canonical;canonical_execute_sites=1",
        "canonical_argv=$canonical;canonical_monitor_contract=$canonicalMonitorContract;canonical_execute_sites=1",
    )

    source = replace_once(
        source,
        "function Get-NonThrowingRetainedV30SnapshotReplay([string]$Phase){try{return [ordered]@{phase=$Phase;status='REPLAYED';evidence=(Invoke-RetainedV30SnapshotVerifier $Phase);errors=@()}}catch{return [ordered]@{phase=$Phase;status='REPLAY_ERRORS_RECORDED';evidence=$null;errors=@($_.Exception.Message)}}}\n\n",
        "function Get-NonThrowingRetainedV30SnapshotReplay([string]$Phase){try{return [ordered]@{phase=$Phase;status='REPLAYED';evidence=(Invoke-RetainedV30SnapshotVerifier $Phase);errors=@()}}catch{return [ordered]@{phase=$Phase;status='REPLAY_ERRORS_RECORDED';evidence=$null;errors=@($_.Exception.Message)}}}\n"
        + RETAINED_V31_FUNCTIONS,
    )
    source = replace_once(
        source,
        "if($LogBridgeSelfTest){",
        r"""if($RetainedPredecessorSnapshotsSelfTest){
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock present before retained predecessor snapshot self-test'};$leaf=(Split-Path -Leaf $prefix)+'.';$existing=@(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if($existing.Count-ne0){throw 'Fresh v32 artifact namespace is not empty before retained predecessor snapshot self-test'};$auth=Get-AuthorizationState;$v30=Invoke-RetainedV30SnapshotVerifier 'isolated_nonconsuming_v30_preflight';$v31=Invoke-RetainedV31SnapshotVerifier 'isolated_nonconsuming_v31_preflight';$existingAfter=@(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if($existingAfter.Count-ne0-or(Test-Path -LiteralPath $claimFile)){throw 'Retained predecessor snapshot self-test created v32 evidence'};if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock appeared during retained predecessor snapshot self-test'}
    [Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v32.retained-predecessor-snapshots-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;v30=$v30;v31=$v31;canonical_suite_executed=$false;shared_lock_used=$false;claim_created=$false;v32_artifacts_created=$false}|ConvertTo-Json -Depth 10 -Compress));return
}
if($LogBridgeSelfTest){""",
    )

    source = replace_once(
        source,
        "$reserved=@($retainedV30SnapshotCustodyFile,$retainedV30SnapshotTerminalCustodyFile,",
        "$reserved=@($retainedV30SnapshotCustodyFile,$retainedV30SnapshotTerminalCustodyFile,$retainedV31SnapshotCustodyFile,$retainedV31SnapshotTerminalCustodyFile,",
    )
    source = replace_once(
        source,
        "$retainedV30SnapshotCustodyPin=$null;$retainedV30SnapshotTerminalCustodyPin=$null;$retainedV30FinalReplay=$null;$retainedV30RejectionReplay=$null;",
        "$retainedV30SnapshotCustodyPin=$null;$retainedV30SnapshotTerminalCustodyPin=$null;$retainedV30FinalReplay=$null;$retainedV30RejectionReplay=$null;$retainedV31SnapshotCustodyHash='';$retainedV31SnapshotTerminalCustodyHash='';$retainedV31SnapshotCustodyPin=$null;$retainedV31SnapshotTerminalCustodyPin=$null;$retainedV31FinalReplay=$null;$retainedV31RejectionReplay=$null;$v31FailureEvidenceHash='';",
    )
    source = replace_once(
        source,
        "$predecessorEvidence=New-ExpectedCombinedPredecessorEvidence;$predecessorEvidenceHash='';$predecessorPins=@();",
        "$predecessorEvidence=New-ExpectedCompletePredecessorEvidence;$predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 40 -Compress));$v31FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v31_failure_evidence|ConvertTo-Json -Depth 40 -Compress));$predecessorPins=@();",
    )
    source = replace_once(
        source,
        "EXACT_V28_V29_V30_CUSTODY_VALIDATED_BEFORE_V32_LOCK",
        "EXACT_V28_V29_V30_V31_CUSTODY_VALIDATED_BEFORE_V32_LOCK",
    )
    source = replace_once(
        source,
        "    $predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 40 -Compress))",
        "    $predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 40 -Compress));$v31FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v31_failure_evidence|ConvertTo-Json -Depth 40 -Compress))",
    )
    source = source.replace(
        "predecessor_evidence_sha256=$predecessorEvidenceHash;",
        "predecessor_evidence_sha256=$predecessorEvidenceHash;v31_failure_evidence=$predecessorEvidence.v31_failure_evidence;v31_failure_evidence_sha256=$v31FailureEvidenceHash;",
    )
    source = source.replace(
        "$plan['predecessor_evidence_sha256']=$predecessorEvidenceHash;",
        "$plan['predecessor_evidence_sha256']=$predecessorEvidenceHash;$plan['v31_failure_evidence']=$predecessorEvidence.v31_failure_evidence;$plan['v31_failure_evidence_sha256']=$v31FailureEvidenceHash;",
    )
    source = source.replace(
        "$receipt['predecessor_evidence_sha256']=$predecessorEvidenceHash;",
        "$receipt['predecessor_evidence_sha256']=$predecessorEvidenceHash;$receipt['v31_failure_evidence']=$predecessorEvidence.v31_failure_evidence;$receipt['v31_failure_evidence_sha256']=$v31FailureEvidenceHash;",
    )
    source = replace_once(
        source,
        "$receipt['retained_v30_snapshot_terminal_custody_sha256']=$retainedV30SnapshotTerminalCustodyHash;",
        "$receipt['retained_v30_snapshot_terminal_custody_sha256']=$retainedV30SnapshotTerminalCustodyHash;$receipt['retained_v31_snapshot_custody_sha256']=$retainedV31SnapshotCustodyHash;$receipt['retained_v31_snapshot_custody_pin']=$retainedV31SnapshotCustodyPin;$receipt['retained_v31_snapshot_terminal_custody_sha256']=$retainedV31SnapshotTerminalCustodyHash;$receipt['retained_v31_snapshot_terminal_custody_pin']=$retainedV31SnapshotTerminalCustodyPin;",
    )
    initial_anchor = "$retainedV30SnapshotCustodyHash=Get-Sha256 $retainedV30SnapshotCustodyFile;$retainedV30SnapshotCustodyPin=Get-LocalEvidencePin $retainedV30SnapshotCustodyFile\n    Write-NewUtf8 $lockEvidenceFile"
    initial_new = "$retainedV30SnapshotCustodyHash=Get-Sha256 $retainedV30SnapshotCustodyFile;$retainedV30SnapshotCustodyPin=Get-LocalEvidencePin $retainedV30SnapshotCustodyFile\n    $retainedV31Initial=Invoke-RetainedV31SnapshotVerifier 'initial_after_v32_lock';$retainedV31SnapshotCustody=[ordered]@{schema='planora.muni-v32.retained-v31-snapshot-custody.v1';status='EXACT_RETAINED_V31_SNAPSHOT_VALIDATED_WHILE_V32_LOCK_HELD';run_id=$runId;replay=$retainedV31Initial;source_inventory_pin=$predecessorEvidence.v31_failure_evidence.contract.snapshot.inventory;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $retainedV31SnapshotCustodyFile ($retainedV31SnapshotCustody|ConvertTo-Json -Depth 12);$retainedV31SnapshotCustodyHash=Get-Sha256 $retainedV31SnapshotCustodyFile;$retainedV31SnapshotCustodyPin=Get-LocalEvidencePin $retainedV31SnapshotCustodyFile\n    Write-NewUtf8 $lockEvidenceFile"
    source = replace_once(source, initial_anchor, initial_new)
    source = source.replace(
        "retained_v30_snapshot_custody_pin=$retainedV30SnapshotCustodyPin;stale_archive_pin=",
        "retained_v30_snapshot_custody_pin=$retainedV30SnapshotCustodyPin;retained_v31_snapshot_custody_sha256=$retainedV31SnapshotCustodyHash;retained_v31_snapshot_custody_pin=$retainedV31SnapshotCustodyPin;stale_archive_pin=",
    )
    source = replace_once(
        source,
        "$plan['retained_v30_snapshot_custody']=[ordered]@{sha256=$retainedV30SnapshotCustodyHash;pin=$retainedV30SnapshotCustodyPin};",
        "$plan['retained_v30_snapshot_custody']=[ordered]@{sha256=$retainedV30SnapshotCustodyHash;pin=$retainedV30SnapshotCustodyPin};$plan['retained_v31_snapshot_custody']=[ordered]@{sha256=$retainedV31SnapshotCustodyHash;pin=$retainedV31SnapshotCustodyPin};",
    )
    source = replace_once(
        source,
        "$preAcceptancePins=@($predecessorPins)+@(@($runnerPath,$retainedV30SnapshotCustodyFile,",
        "$preAcceptancePins=@($predecessorPins)+@(@($runnerPath,$retainedV30SnapshotCustodyFile,$retainedV31SnapshotCustodyFile,",
    )
    terminal_anchor = "$retainedV30SnapshotTerminalCustodyHash=Get-Sha256 $retainedV30SnapshotTerminalCustodyFile;$retainedV30SnapshotTerminalCustodyPin=Get-LocalEvidencePin $retainedV30SnapshotTerminalCustodyFile\n    $protectedPins=@($preAcceptancePins)+@((Get-LocalEvidencePin $acceptanceFile),(Get-LocalEvidencePin $cleanupFile),(Get-LocalEvidencePin $watchCleanupFile),$retainedV30SnapshotTerminalCustodyPin)"
    terminal_new = "$retainedV30SnapshotTerminalCustodyHash=Get-Sha256 $retainedV30SnapshotTerminalCustodyFile;$retainedV30SnapshotTerminalCustodyPin=Get-LocalEvidencePin $retainedV30SnapshotTerminalCustodyFile\n    $retainedV31Terminal=Invoke-RetainedV31SnapshotVerifier 'post_cleanup_while_v32_lock_held_before_final_census';$retainedV31SnapshotTerminalCustody=[ordered]@{schema='planora.muni-v32.retained-v31-snapshot-terminal-custody.v1';status='EXACT_RETAINED_V31_SNAPSHOT_REPLAYED_AFTER_V32_CLEANUP_WHILE_LOCK_HELD';run_id=$runId;initial_custody_sha256=$retainedV31SnapshotCustodyHash;replay=$retainedV31Terminal;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $retainedV31SnapshotTerminalCustodyFile ($retainedV31SnapshotTerminalCustody|ConvertTo-Json -Depth 12);$retainedV31SnapshotTerminalCustodyHash=Get-Sha256 $retainedV31SnapshotTerminalCustodyFile;$retainedV31SnapshotTerminalCustodyPin=Get-LocalEvidencePin $retainedV31SnapshotTerminalCustodyFile\n    $protectedPins=@($preAcceptancePins)+@((Get-LocalEvidencePin $acceptanceFile),(Get-LocalEvidencePin $cleanupFile),(Get-LocalEvidencePin $watchCleanupFile),$retainedV30SnapshotTerminalCustodyPin,$retainedV31SnapshotTerminalCustodyPin)"
    source = replace_once(source, terminal_anchor, terminal_new)
    source = replace_once(
        source,
        "$retainedV30FinalReplay=Invoke-RetainedV30SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$terminalArchiveGuard=",
        "$retainedV30FinalReplay=Invoke-RetainedV30SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$retainedV31FinalReplay=Invoke-RetainedV31SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$terminalArchiveGuard=",
    )
    source = source.replace(
        "retained_v30_snapshot_final_replay=$retainedV30FinalReplay;stale_lock_archive_pin=",
        "retained_v30_snapshot_final_replay=$retainedV30FinalReplay;retained_v31_snapshot_custody_sha256=$retainedV31SnapshotCustodyHash;retained_v31_snapshot_terminal_custody_sha256=$retainedV31SnapshotTerminalCustodyHash;retained_v31_snapshot_final_replay=$retainedV31FinalReplay;stale_lock_archive_pin=",
    )
    source = source.replace(
        "$retainedV30RejectionReplay=Get-NonThrowingRetainedV30SnapshotReplay 'rejection_before_optional_v32_lock_release';",
        "$retainedV30RejectionReplay=Get-NonThrowingRetainedV30SnapshotReplay 'rejection_before_optional_v32_lock_release';$retainedV31RejectionReplay=Get-NonThrowingRetainedV31SnapshotReplay 'rejection_before_optional_v32_lock_release';",
    )
    source = source.replace(
        "retained_v30_snapshot_rejection_replay=$retainedV30RejectionReplay;stale_lock_archive_pin=",
        "retained_v30_snapshot_rejection_replay=$retainedV30RejectionReplay;retained_v31_snapshot_custody_sha256=$retainedV31SnapshotCustodyHash;retained_v31_snapshot_custody_pin=$retainedV31SnapshotCustodyPin;retained_v31_snapshot_terminal_custody_sha256=$retainedV31SnapshotTerminalCustodyHash;retained_v31_snapshot_terminal_custody_pin=$retainedV31SnapshotTerminalCustodyPin;retained_v31_snapshot_final_replay=$retainedV31FinalReplay;retained_v31_snapshot_rejection_replay=$retainedV31RejectionReplay;stale_lock_archive_pin=",
    )
    source = source.replace(
        "retained_v30_final_replay_completed=($null-ne$retainedV30FinalReplay)",
        "retained_v30_final_replay_completed=($null-ne$retainedV30FinalReplay);retained_v31_initial_custody_published=($null-ne$retainedV31SnapshotCustodyPin);retained_v31_post_cleanup_custody_published=($null-ne$retainedV31SnapshotTerminalCustodyPin);retained_v31_final_replay_completed=($null-ne$retainedV31FinalReplay)",
    )
    rejection_replay_anchor = "$predecessorRejectionReplay=$null;try{$predecessorRejectionReplay=Get-NonThrowingCompletePredecessorReplay $predecessorEvidence $staleArchivePin}catch{$predecessorRejectionReplay=[ordered]@{phase='rejection_publication';status='REPLAY_HELPER_FAILED';errors=@($_.Exception.Message)}};$predecessorEvidence['rejection_replay']=$predecessorRejectionReplay;$predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 70 -Compress))"
    rejection_replay_replacement = "$predecessorRejectionReplay=$null;try{$predecessorRejectionReplay=Get-NonThrowingCompletePredecessorReplay $predecessorEvidence $staleArchivePin}catch{$predecessorRejectionReplay=[ordered]@{phase='rejection_publication';status='REPLAY_HELPER_FAILED';prior_evidence_status=$predecessorEvidence.status;errors=@($_.Exception.Message)}};$resolvedPredecessorRejection=Resolve-CompletePredecessorRejectionEvidence $predecessorEvidence $predecessorRejectionReplay;$predecessorEvidence=$resolvedPredecessorRejection.evidence;$predecessorRejectionReplay=$resolvedPredecessorRejection.replay;$v31FailureEvidenceHash=$resolvedPredecessorRejection.v31_failure_evidence_sha256;$predecessorEvidenceHash=$resolvedPredecessorRejection.predecessor_evidence_sha256"
    source = replace_once(source, rejection_replay_anchor, rejection_replay_replacement)

    source = source.replace(
        "schema='planora.itc2019.canonical-test-authorization.v11'",
        "schema='planora.itc2019.canonical-test-authorization.v12'",
    )
    source = replace_once(
        source,
        "$closure=$snapshotContractJson|ConvertFrom-Json;$predecessor=$predecessorContractJson|ConvertFrom-Json",
        "$closure=$snapshotContractJson|ConvertFrom-Json;$predecessor=$predecessorContractJson|ConvertFrom-Json;$v31Failure=$v31FailureContractJson|ConvertFrom-Json",
    )
    source = replace_once(
        source,
        "predecessor_custody_contract=$predecessor",
        "predecessor_custody_contract=$predecessor;v31_failure_custody_contract=$v31Failure",
    )
    admission_pattern = re.compile(
        r"successor_admission=\[ordered\]@\{builder=\[ordered\]@\{path='scripts/build_muni_v32_successor\.py';size=\d+;sha256='[0-9a-f]{64}'\};tests=\[ordered\]@\{path='tests/test_run_muni_v32_successor\.py';size=\d+;sha256='[0-9a-f]{64}'\}\}"
    )
    admission = (
        "successor_admission=[ordered]@{builder=[ordered]@{path='scripts/build_muni_v32_successor.py';size="
        f"{builder_size};sha256='{builder_hash}'"
        "};tests=[ordered]@{path='tests/test_run_muni_v32_successor.py';size="
        f"{tests_size};sha256='{tests_hash}'"
        "}}"
    )
    source, count = admission_pattern.subn(admission, source, count=1)
    if count != 1:
        raise RuntimeError("v32 successor admission replacement failed")
    source = source.replace(
        "GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_AUTHENTICATED_V30_PREINVENTORY_BINDING_FAILURE",
        "GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_AUTHENTICATED_V31_ARGV_PIPELINE_FAILURE",
    )
    source = source.replace(
        "all_41_predecessor_file_ids_and_timestamps_authorized=$true",
        "all_61_predecessor_file_ids_and_timestamps_authorized=$true",
    )
    source = source.replace(
        "complete_v28_v29_v30_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true",
        "complete_v28_v29_v30_v31_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true",
    )
    source = source.replace(
        "v28_v29_v30_pass_absence_replayed_through_final_pass_seal_publication=$true",
        "v28_v29_v30_v31_pass_absence_replayed_through_final_pass_seal_publication=$true",
    )
    retained_contract_pattern = re.compile(
        r"(?m)^(        retained_v30_snapshot_contract=\[ordered\]@\{.*\})$"
    )
    retained_contract_addition = (
        r"\1"
        "\n        retained_predecessor_snapshots_contract=[ordered]@{"
        "v30_root=$predecessor.v30.snapshot.root;"
        "v31_root=$v31Failure.snapshot.root;"
        "v30_inventory=$predecessor.v30.snapshot.inventory;"
        "v31_inventory=$v31Failure.snapshot.inventory;"
        "isolated_switch='RetainedPredecessorSnapshotsSelfTest';"
        "read_only_identity_replay=$true;"
        "initial_post_cleanup_rejection_and_final_replay_required=$true;"
        "v32_cleanup_must_not_target_v30_or_v31=$true}"
    )
    source, retained_contract_count = retained_contract_pattern.subn(
        retained_contract_addition, source, count=1
    )
    if retained_contract_count != 1:
        raise RuntimeError("v32 retained predecessor authorization contract failed")
    source = replace_once(
        source,
        "retained_v30_snapshot_initial_and_terminal_replay_bound=$true;",
        "retained_v30_snapshot_initial_and_terminal_replay_bound=$true;"
        "retained_v31_snapshot_initial_and_terminal_replay_bound=$true;",
    )
    source = replace_once(
        source,
        "        heavy_gate=[ordered]@{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';",
        "        canonical_argv_contract=[ordered]@{exact_string_atoms=253;timeout_index=3;bwrap_index=7;python_index=248;unsuppressed_validator_output_regression=$true;isolated_switch='CanonicalMonitorContractSelfTest';powershell5_and_7_required=$true}\n"
        "        rejection_promotion_contract=[ordered]@{expected_complete_evidence_present_before_claim=$true;successful_replay_promoted_without_cycle=$true;failed_replay_summarized_without_evidence_reference=$true;v31_failure_hash_nonempty_on_early_rejection=$true;isolated_switch='RejectionPromotionSelfTest';powershell5_and_7_required=$true}\n"
        "        wsl_geometry_contract=[ordered]@{columns=32768;lines=1000;wslenv='COLUMNS:LINES';canonical_environment_cleared=$true}\n"
        "        heavy_gate=[ordered]@{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';",
    )

    required = (
        "[void](Assert-CanonicalArguments $args $Legacy)",
        "CanonicalMonitorContractSelfTest",
        "RejectionPromotionSelfTest",
        "argument_count=$tokens.Count",
        "Get-ValidatedCompletePredecessorEvidence",
        "Get-ValidatedV31FailureEvidence",
        "predecessorPins.Count-ne61",
        "Invoke-RetainedV31SnapshotVerifier 'initial_after_v32_lock'",
        "Invoke-RetainedV31SnapshotVerifier 'post_cleanup_while_v32_lock_held_before_final_census'",
        "RetainedPredecessorSnapshotsSelfTest",
        "$env:COLUMNS='32768'",
        "Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream",
    )
    for marker in required:
        if marker not in source:
            raise RuntimeError(f"v32 required marker missing: {marker}")
    if re.search(r"(?m)^    Assert-CanonicalArguments \$args \$Legacy$", source):
        raise RuntimeError("bare canonical validator invocation survived")
    if "prefix='/tmp/planora-muni-v32-canonical-tests-'" not in source:
        raise RuntimeError("v32 cleanup prefix missing")
    cleanup_match = re.search(r"(?s)\$cleanupSource = @'\r?\n(.*?)\r?\n'@", source)
    if not cleanup_match or any(
        old in cleanup_match.group(1)
        for old in (
            "/tmp/planora-muni-v30-canonical-tests-",
            "/tmp/planora-muni-v31-canonical-tests-",
        )
    ):
        raise RuntimeError("v32 cleanup can target a retained predecessor root")
    return source


def main() -> None:
    builder = Path(__file__)
    builder_size = builder.stat().st_size
    builder_hash = sha256(builder)
    tests_size = V32_TESTS.stat().st_size
    tests_hash = sha256(V32_TESTS)
    runner = render_runner(builder_size, builder_hash, tests_size, tests_hash)
    V32_RUNNER.write_text(runner, encoding="utf-8", newline="\n")

    powershell = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V32_RUNNER),
            "-EmitExpectedAuthorization",
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0 or result.stderr:
        raise RuntimeError(
            f"authorization emission failed: {result.returncode}: {result.stderr}"
        )
    authorization = json.loads(result.stdout)
    if (
        authorization["schema"] != "planora.itc2019.canonical-test-authorization.v12"
        or authorization["test_id"] != RUN_ID
        or authorization["runner"]["sha256"] != sha256(V32_RUNNER)
    ):
        raise RuntimeError("v32 authorization semantics rejected")
    V32_AUTH.write_text(
        json.dumps(authorization, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": "MUNI_V32_SUCCESSOR_GENERATED_STATIC_ONLY",
                "run_id": RUN_ID,
                "runner": str(V32_RUNNER.relative_to(REPO)).replace("\\", "/"),
                "runner_sha256": sha256(V32_RUNNER),
                "authorization": str(V32_AUTH.relative_to(REPO)).replace("\\", "/"),
                "authorization_sha256": sha256(V32_AUTH),
                "predecessor_pins": 61,
                "wsl_executed": False,
                "canonical_suite_executed": False,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
