#!/usr/bin/env bash
set -euo pipefail

umask 077

repo=/mnt/d/Stuff/Projects/Sites/Planora
chain="$repo/benchmarks/probe_diagnostics/agh_v17"
out="$repo/output/diagnostic-receipts"
runner="$repo/scripts/run_agh_v17_retained_probe.sh"
probe_id=9769625f105940118da502781078a4f5
prefix="$out/agh-fal17-v17-retained-probe-$probe_id"
authorization="$out/agh-fal17-v17-retained-probe-authorization-20260827T042509Z.receipt.json"
claim_dir="$prefix.claim"
claim_owner="$claim_dir/owner.json"
inner_script="$prefix.inner.sh"
preflight="$prefix.preflight.json"
checksums="$prefix.checksums.json"
result_receipt="$prefix.result-receipt.json"
heavy_lock_dir="$out/.planora-wsl-heavy-task.lock"
heavy_lock_claim="$prefix.heavy-lock-claim.json"
heavy_lock_evidence="$prefix.heavy-lock.json"

# This is the irreversible authorization-consumption boundary. The directory is
# never removed by this wrapper, including on preflight or execution failure.
if ! /usr/bin/mkdir -- "$claim_dir"; then
    echo "AGH v17 probe ID already consumed; retry prohibited: $probe_id" >&2
    exit 73
fi

claimed_at_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
claim_host="$(uname -n)"
/usr/bin/python3.12 -I -S -B - \
    "$claim_owner" "$probe_id" "$claim_dir" "$runner" \
    "$claimed_at_utc" "$claim_host" "$$" "$PPID" <<'PY'
import json
import os
import pathlib
import sys

(
    owner_path_raw,
    probe_id,
    claim_path,
    runner_path,
    claimed_at_utc,
    hostname,
    shell_pid_raw,
    shell_ppid_raw,
) = sys.argv[1:]
shell_pid = int(shell_pid_raw)
shell_ppid = int(shell_ppid_raw)
stat_fields = pathlib.Path(f"/proc/{shell_pid}/stat").read_text(encoding="ascii").split()
if len(stat_fields) < 22:
    raise SystemExit("claim owner process identity unavailable")
payload = {
    "schema": "planora.itc2019.retained-probe-claim.v1",
    "probe_id": probe_id,
    "claim_marker_path": claim_path,
    "claimed_at_utc": claimed_at_utc,
    "hostname": hostname,
    "shell_pid": shell_pid,
    "shell_ppid": shell_ppid,
    "shell_starttime_ticks": int(stat_fields[21]),
    "runner_path": runner_path,
    "atomic_primitive": "mkdir",
    "claim_retained_on_failure": True,
    "retry_allowed": False,
}
raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
owner_path = pathlib.Path(owner_path_raw)
with owner_path.open("xb") as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
PY
chmod 0400 -- "$claim_owner"
chmod 0500 -- "$claim_dir"

for retained in \
    "$prefix.authorization.json" \
    "$prefix.invocations.json" \
    "$inner_script" \
    "$preflight" \
    "$prefix.stdout.json" \
    "$prefix.stderr.log" \
    "$prefix.exit-code.txt" \
    "$heavy_lock_claim" \
    "$heavy_lock_evidence" \
    "$checksums" \
    "$result_receipt"
do
    if test -e "$retained"; then
        echo "Retained evidence already exists after claim consumption: $retained" >&2
        exit 74
    fi
done

# This shared directory is an atomic cooperative mutex for every Planora WSL
# heavy task. It is distinct from the irreversible probe claim above. The lock
# is released on shell exit, while its owner/census evidence remains retained.
if ! /usr/bin/mkdir -- "$heavy_lock_dir"; then
    /usr/bin/python3.12 -I -S -B - \
        "$heavy_lock_claim" "$heavy_lock_dir" "$claim_owner" "$probe_id" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

evidence_raw, lock_raw, claim_owner_raw, probe_id = sys.argv[1:]
evidence_path = pathlib.Path(evidence_raw)
lock_path = pathlib.Path(lock_raw)
claim_raw = pathlib.Path(claim_owner_raw).read_bytes()
try:
    row = os.lstat(lock_path)
    observed = {
        "exists": True,
        "device": int(row.st_dev),
        "inode": int(row.st_ino),
        "mode": stat.S_IMODE(row.st_mode),
        "file_type": stat.S_IFMT(row.st_mode),
        "uid": int(row.st_uid),
    }
except FileNotFoundError:
    observed = {"exists": False}
payload = {
    "schema": "planora.wsl-heavy-task-lock-claim.v1",
    "status": "NO_GO",
    "reason": "shared_lock_unavailable",
    "probe_id": probe_id,
    "lock_path": str(lock_path),
    "atomic_primitive": "exclusive_mkdir",
    "probe_claim_owner_sha256": hashlib.sha256(claim_raw).hexdigest(),
    "observed_lock_path": observed,
    "v17_execution_authorized": False,
}
raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
with evidence_path.open("xb") as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
PY
    echo "Shared WSL heavy-task lock is held; probe execution prohibited" >&2
    exit 75
fi
release_heavy_lock() {
    /usr/bin/rmdir -- "$heavy_lock_dir" || {
        echo "Shared WSL heavy-task lock release failed: $heavy_lock_dir" >&2
        return 1
    }
}
trap release_heavy_lock EXIT

/usr/bin/python3.12 -I -S -B - \
    "$heavy_lock_dir" "$heavy_lock_claim" "$claim_owner" "$probe_id" \
    "$$" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

lock_raw, evidence_raw, claim_owner_raw, probe_id, shell_pid_raw = sys.argv[1:]
lock_path = pathlib.Path(lock_raw)
evidence_path = pathlib.Path(evidence_raw)
claim_owner_path = pathlib.Path(claim_owner_raw)
lock_row = lock_path.stat(follow_symlinks=False)
if (
    not stat.S_ISDIR(lock_row.st_mode)
    or stat.S_IMODE(lock_row.st_mode) != 0o700
    or lock_row.st_uid != os.getuid()
):
    raise SystemExit("shared heavy-task lock claim rejected")
claim_raw = claim_owner_path.read_bytes()
payload = {
    "schema": "planora.wsl-heavy-task-lock-claim.v1",
    "probe_id": probe_id,
    "lock_path": str(lock_path),
    "atomic_primitive": "exclusive_mkdir",
    "device": int(lock_row.st_dev),
    "inode": int(lock_row.st_ino),
    "mode": stat.S_IMODE(lock_row.st_mode),
    "uid": int(lock_row.st_uid),
    "owner_shell_pid": int(shell_pid_raw),
    "probe_claim_owner_sha256": hashlib.sha256(claim_raw).hexdigest(),
    "held_until_runner_exit": True,
    "v17_execution_authorized": False,
}
raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
with evidence_path.open("xb") as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
PY

set -o noclobber
{
cat <<'INNER'
set -euo pipefail

src=/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/agh_v17

stage() {
    /usr/bin/install -m 0400 -- "$src/$1" "/tmp/$1"
}

stage agent-aghfal17-native-v17-outer-controller.py
stage agent-aghfal17-native-v17-review-freeze.json
stage agent-aghfal17-native-v17-bootstrap.py
stage agent-aghfal17-native-v17-launcher.sh
stage agent-aghfal17-native-v17-supervisor.py
stage agent-aghfal17-native-v17-runner.py
stage agent-aghfal17-native-v17-minimal-tcb.sha256
stage agent-aghfal17-native-v17-stdlib.sha256

/usr/bin/python3.12 -I -S -B - "$src" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

src = pathlib.Path(sys.argv[1])
invocations = json.loads(
    (src / "agent-aghfal17-native-v17-invocations.json").read_bytes()
)
freeze_raw = pathlib.Path(
    "/tmp/agent-aghfal17-native-v17-review-freeze.json"
).read_bytes()
freeze = json.loads(freeze_raw)

if hashlib.sha256(freeze_raw).hexdigest() != invocations["freeze_manifest"]["sha256"]:
    raise SystemExit("staged freeze drift")

required = {
    "outer_controller",
    "bootstrap",
    "launcher",
    "supervisor",
    "runner",
    "minimal_tcb_manifest",
    "stdlib_manifest",
}
for label in required:
    row = freeze["artifacts"][label]
    path = pathlib.Path(row["path"])
    payload = path.read_bytes()
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o400
        or len(payload) != row["size_bytes"]
        or hashlib.sha256(payload).hexdigest() != row["sha256"]
    ):
        raise SystemExit(f"staged artifact contract rejected: {label}")

root_ro = False
for line in pathlib.Path("/proc/self/mountinfo").read_text().splitlines():
    fields = line.split(" - ", 1)[0].split()
    if len(fields) >= 6 and fields[4] == "/" and "ro" in fields[5].split(","):
        root_ro = True
if not root_ro:
    raise SystemExit("sandbox root is not read-only")

for path in ("/", "/usr", "/usr/bin", "/usr/lib", "/usr/lib/python3.12"):
    info = os.stat(path, follow_symlinks=False)
    if info.st_uid != 65534 or info.st_gid != 65534:
        raise SystemExit(f"system ownership mapping rejected: {path}")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise SystemExit(f"writable system ancestor rejected: {path}")

outer_argv = invocations["probe"]["argv"]
outer_digest = hashlib.sha256("\0".join(outer_argv).encode("utf-8")).hexdigest()
expected_outer = "bcab8bc73f21c72be120fb89e66bd9d614ff4e58d1ed7b1b158bf65f6e4af0cb"
inner_argv = freeze["commands"]["probe"]["argv"]
inner_digest = hashlib.sha256("\0".join(inner_argv).encode("utf-8")).hexdigest()
expected_inner = "a94419760f9cd5ac58a26cffaebc0ee7dc3ba87e78681620632586665c988fe3"
if outer_digest != expected_outer or outer_digest != invocations["probe"]["canonical_argv_sha256"]:
    raise SystemExit("outer canonical probe argv rejected")
if inner_digest != expected_inner or inner_digest != freeze["commands"]["probe"]["canonical_argv_sha256"]:
    raise SystemExit("inner canonical probe argv rejected")
if outer_argv[-1] != "--sealed-import-probe" or inner_argv[-1] != "--sealed-import-probe":
    raise SystemExit("probe terminal mode rejected")
forbidden = {"--launch", "--allow-official-input", "--allow-solver", "--allow-publication"}
if forbidden.intersection(outer_argv) or forbidden.intersection(inner_argv):
    raise SystemExit("forbidden execution capability detected")
if freeze["official_input"]["path"] in outer_argv or freeze["official_input"]["path"] in inner_argv:
    raise SystemExit("official input detected in frozen probe argv")

environment = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
}
os.execve(outer_argv[0], outer_argv, environment)
PY
INNER
} >"$inner_script"
set +o noclobber
chmod 0400 -- "$inner_script"

execution_argv=(
    /usr/bin/timeout
    --signal=TERM
    --kill-after=5s
    250s
    /usr/bin/bwrap
    --unshare-all
    --new-session
    --die-with-parent
    --uid
    0
    --gid
    0
    --cap-drop
    ALL
    --ro-bind
    /
    /
    --proc
    /proc
    --dev
    /dev
    --tmpfs
    /tmp
    --ro-bind
    /dev/null
    /mnt/d/Stuff/Projects/Sites/Planora/data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/agh-fal17.xml
    --chdir
    /mnt/d/Stuff/Projects/Sites/Planora
    --clearenv
    --setenv
    PATH
    /usr/bin:/bin
    --setenv
    LANG
    C.UTF-8
    --setenv
    LC_ALL
    C.UTF-8
    --setenv
    TZ
    UTC
    --
    /usr/bin/bash
    -s
)

/usr/bin/python3.12 -I -S -B - \
    "$repo" "$chain" "$authorization" "$runner" "$claim_owner" \
    "$inner_script" "$preflight" "$heavy_lock_dir" "$heavy_lock_claim" \
    "$heavy_lock_evidence" \
    "$prefix.authorization.json" \
    "$prefix.invocations.json" "$probe_id" -- "${execution_argv[@]}" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys
import time

separator = sys.argv.index("--")
(
    repo_raw,
    chain_raw,
    authorization_raw_path,
    runner_raw,
    claim_owner_raw,
    inner_script_raw,
    preflight_raw,
    heavy_lock_raw,
    heavy_lock_claim_raw,
    heavy_lock_evidence_raw,
    authorization_snapshot_raw,
    invocations_snapshot_raw,
    probe_id,
) = sys.argv[1:separator]
execution_argv = sys.argv[separator + 1 :]
repo = pathlib.Path(repo_raw)
chain = pathlib.Path(chain_raw)
authorization_path = pathlib.Path(authorization_raw_path)
runner_path = pathlib.Path(runner_raw)
claim_owner_path = pathlib.Path(claim_owner_raw)
inner_script_path = pathlib.Path(inner_script_raw)
preflight_path = pathlib.Path(preflight_raw)
heavy_lock_path = pathlib.Path(heavy_lock_raw)
heavy_lock_claim_path = pathlib.Path(heavy_lock_claim_raw)
heavy_lock_evidence_path = pathlib.Path(heavy_lock_evidence_raw)
authorization_snapshot = pathlib.Path(authorization_snapshot_raw)
invocations_snapshot = pathlib.Path(invocations_snapshot_raw)
freeze_path = chain / "agent-aghfal17-native-v17-review-freeze.json"
invocations_path = chain / "agent-aghfal17-native-v17-invocations.json"


def read(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def exact_keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise SystemExit(f"{label} keys rejected")


def verify(path: pathlib.Path, row: dict[str, object], label: str) -> None:
    payload = read(path)
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or len(payload) != row["size_bytes"]
        or digest(payload) != row["sha256"]
    ):
        raise SystemExit(f"PIN DRIFT: {label}: {path}")


authorization_raw = read(authorization_path)
authorization = json.loads(authorization_raw)
exact_keys(
    authorization,
    {
        "schema",
        "created_at_utc",
        "instance",
        "candidate",
        "probe_id",
        "decision",
        "retained_probe_authorized",
        "successor_chain_required",
        "official_launch_authorized",
        "official_input_authorized",
        "solver_authorized",
        "checkpoint_authorized",
        "publication_authorized",
        "automatic_retry_authorized",
        "execution_wrapper",
        "authorization_consumption",
        "producer_checkpoint_evidence",
        "heavy_task_gate",
        "independent_review",
        "coordinator_replay",
        "frozen_probe",
        "frozen_limits",
        "mandatory_execution_conditions",
    },
    "authorization",
)
expected_identity = {
    "schema": "planora.itc2019.retained-probe-authorization.v3",
    "created_at_utc": "2026-08-27T04:25:09Z",
    "instance": "agh-fal17",
    "candidate": "native-v17",
    "probe_id": "9769625f105940118da502781078a4f5",
    "decision": "NO_GO_REQUIRES_SUCCESSOR_CHAIN_CHECKPOINT_EVIDENCE",
    "retained_probe_authorized": False,
    "successor_chain_required": True,
    "official_launch_authorized": False,
    "official_input_authorized": False,
    "solver_authorized": False,
    "checkpoint_authorized": False,
    "publication_authorized": False,
    "automatic_retry_authorized": False,
}
for key, value in expected_identity.items():
    if authorization.get(key) != value:
        raise SystemExit(f"authorization identity rejected: {key}")
if probe_id != expected_identity["probe_id"]:
    raise SystemExit("runner probe ID drift")

expected_review = {
    "verdict": "NO_GO",
    "scope": "static review only; retained probe execution prohibited",
    "canonical_tests_run": 65,
    "canonical_tests_passed": 64,
    "canonical_tests_skipped_linux_only": 1,
    "adversarial_checks_passed": 48,
    "reviewed_artifacts": 9,
    "reviewed_source_closure_rows": 16,
    "reviewed_runtime_record_rows": 10,
    "preserved_v12_v16_files": 63,
    "material_blockers": [
        "frozen outer payload omits checkpoint_or_certified_provenance_used",
        "frozen inner supervisor payload omits checkpoint_or_certified_provenance_used",
        "successor chain must emit exact built-in false values before a new authorization",
    ],
}
expected_replay = {
    "builder_size": 40757,
    "builder_sha256": "4a895136bf05d1eb621a4b5a659aac6485229a971791eb98e4e704bfa291f989",
    "freeze_manifest_size": 43048,
    "freeze_manifest_sha256": "1919dc785c6d1a6d3f06eb5f087faacde2d2194b890d8a0da70943ac829977c1",
    "invocations_size": 18685,
    "invocations_sha256": "5dcb99619c38707a110e85c948c618993068ead87a5345ab105147ac4645dc4b",
    "shared_core_sha256": "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
    "focused_regression_sha256": "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d",
}
expected_probe = {
    "invocation_path": "benchmarks/probe_diagnostics/agh_v17/agent-aghfal17-native-v17-invocations.json",
    "outer_canonical_argv_sha256": "bcab8bc73f21c72be120fb89e66bd9d614ff4e58d1ed7b1b158bf65f6e4af0cb",
    "inner_canonical_argv_sha256": "a94419760f9cd5ac58a26cffaebc0ee7dc3ba87e78681620632586665c988fe3",
    "terminal_mode": "--sealed-import-probe",
}
expected_limits = {
    "process_generation_vmrss_plus_vmswap_limit_kib": 368640,
    "whole_launch_process_plus_sealed_plus_report_limit_kib": 614400,
    "initial_memavailable_floor_kib": 1900000,
    "initial_sample_count": 2,
    "initial_sample_interval_seconds": 5,
    "runtime_memavailable_floor_kib": 900000,
    "probe_outer_wall_seconds": 240,
    "probe_inner_wall_seconds": 180,
    "final_zero_snapshots_required": 2,
}
expected_consumption = {
    "claim_marker_path": "output/diagnostic-receipts/agh-fal17-v17-retained-probe-9769625f105940118da502781078a4f5.claim",
    "atomic_primitive": "mkdir",
    "consume_before_preflight": True,
    "claim_retained_on_failure": True,
    "retry_prohibited": True,
}
expected_checkpoint_evidence = {
    "required_key": "checkpoint_or_certified_provenance_used",
    "required_value_type": "builtins.bool",
    "required_value": False,
    "outer_payload_schema": "planora.agh-fal17.native-v17-outer-controller.v1",
    "outer_source_path": "benchmarks/probe_diagnostics/agh_v17/agent-aghfal17-native-v17-outer-controller.py",
    "outer_source_sha256": "3fe5dba53e9c6293694779c5bec0100e46f9fbcaa19b9ef8f96531db96723a35",
    "outer_required_key_emitted": False,
    "inner_payload_schema": "planora.agh-fal17.native-v17-sealed-import-supervisor.v1",
    "inner_source_path": "benchmarks/probe_diagnostics/agh_v17/agent-aghfal17-native-v17-supervisor.py",
    "inner_source_sha256": "56a78bc55e2b6e324397d9e7350346382d63e1676cdda06553b40dd280c0cc89",
    "inner_required_key_emitted": False,
    "evidence_sufficient_for_execution": False,
}
expected_heavy_gate = {
    "shared_lock_path": "output/diagnostic-receipts/.planora-wsl-heavy-task.lock",
    "atomic_primitive": "exclusive_mkdir",
    "lock_must_be_held_through_any_authorized_execution": True,
    "lock_evidence_retained": True,
    "census_policy": "reject_every_non_ancestry_non_minimal_infrastructure_process",
    "known_workloads_explicitly_classified": [
        "stress-ng", "pytest", "python", "java", "solver", "build", "docker-client"
    ],
    "unknown_user_commands_rejected": True,
    "inspection_uncertainty_rejected": True,
}
expected_conditions = [
    "Do not execute the retained v17 probe; the authorization decision is NO-GO and a successor chain is required.",
    "Atomically and irreversibly consume the probe ID with the exclusive claim marker before preflight; retain it on every failure and prohibit retry.",
    "Require checkpoint_or_certified_provenance_used to be present in both outer and inner payloads with type exactly builtins.bool and value false; absence or any other JSON value rejects.",
    "Acquire the atomic shared WSL heavy-task lock and reject every concurrent process except exact current-runner ancestry and minimal allowlisted WSL infrastructure.",
    "Keep every current artifact, source, runtime RECORD, Python, Bash, freeze-manifest, invocation, authorization, and execution-wrapper pin fail-closed; no v17 execution may occur.",
    "Recompute both canonical probe argv digests and require exact equality.",
    "Any successor authorization must use a read-only-root bwrap namespace with a fresh private writable /tmp and only its frozen probe artifacts staged at exact paths.",
    "Any successor authorization must obtain two MemAvailable samples of at least 1900000 KiB at least five seconds apart and pass the authoritative shared-lock process census.",
    "Any successor authorization must execute exactly once, serialized against every other WSL-heavy task, with no automatic retry.",
    "Any successor result must reject unless the outer status is PASS, breach is absent, child exit is zero, cleanup is error-free with two stable zero snapshots, and every official-input, solver, checkpoint, and publication flag is exact false.",
    "Any successor result must retain claim ownership, lock and census evidence, exact command and environment, complete preflight, stdout, stderr, exit status, post-run checksums, accounting peak, and post-exit cleanup evidence.",
]
for actual, expected, label in (
    (authorization["independent_review"], expected_review, "review"),
    (authorization["coordinator_replay"], expected_replay, "coordinator replay"),
    (authorization["frozen_probe"], expected_probe, "frozen probe"),
    (authorization["frozen_limits"], expected_limits, "frozen limits"),
    (authorization["authorization_consumption"], expected_consumption, "authorization consumption"),
    (authorization["producer_checkpoint_evidence"], expected_checkpoint_evidence, "producer checkpoint evidence"),
    (authorization["heavy_task_gate"], expected_heavy_gate, "heavy task gate"),
    (authorization["mandatory_execution_conditions"], expected_conditions, "mandatory conditions"),
):
    if actual != expected:
        raise SystemExit(f"authorization {label} rejected")

runner_raw = read(runner_path)
wrapper_row = authorization["execution_wrapper"]
expected_runner_relative = "scripts/run_agh_v17_retained_probe.sh"
expected_runner_wsl = "/mnt/d/Stuff/Projects/Sites/Planora/scripts/run_agh_v17_retained_probe.sh"
exact_keys(wrapper_row, {"path", "wsl_path", "size_bytes", "sha256"}, "execution wrapper")
if (
    wrapper_row["path"] != expected_runner_relative
    or wrapper_row["wsl_path"] != expected_runner_wsl
    or runner_path.resolve() != pathlib.Path(expected_runner_wsl)
    or len(runner_raw) != wrapper_row["size_bytes"]
    or digest(runner_raw) != wrapper_row["sha256"]
):
    raise SystemExit("execution wrapper pin rejected")

freeze_raw = read(freeze_path)
freeze = json.loads(freeze_raw)
invocations_raw = read(invocations_path)
invocations = json.loads(invocations_raw)
if len(freeze_raw) != expected_replay["freeze_manifest_size"] or digest(freeze_raw) != expected_replay["freeze_manifest_sha256"]:
    raise SystemExit("freeze-manifest authorization pin drift")
if len(invocations_raw) != expected_replay["invocations_size"] or digest(invocations_raw) != expected_replay["invocations_sha256"]:
    raise SystemExit("invocation authorization pin drift")
if digest(freeze_raw) != invocations["freeze_manifest"]["sha256"]:
    raise SystemExit("freeze-manifest invocation pin drift")

for label, row in freeze["artifacts"].items():
    verify(chain / pathlib.PurePosixPath(row["path"]).name, row, f"artifact:{label}")
for relative, row in freeze["source_closure"].items():
    verify(repo / relative, row, f"source:{relative}")
for label, row in freeze["runtime_records"].items():
    verify(repo / row["path"], row, f"runtime-record:{label}")
for label in ("python", "bash"):
    row = freeze["runtime_pins"][label]
    verify(pathlib.Path(row["path"]), row, f"runtime-pin:{label}")

outer_argv = invocations["probe"]["argv"]
inner_argv = freeze["commands"]["probe"]["argv"]
if any(not isinstance(value, str) or "\0" in value for value in outer_argv + inner_argv):
    raise SystemExit("canonical probe argv contains invalid elements")
outer_digest = digest("\0".join(outer_argv).encode("utf-8"))
inner_digest = digest("\0".join(inner_argv).encode("utf-8"))
if outer_digest != expected_probe["outer_canonical_argv_sha256"] or outer_digest != invocations["probe"]["canonical_argv_sha256"]:
    raise SystemExit("outer canonical probe argv digest drift")
if inner_digest != expected_probe["inner_canonical_argv_sha256"] or inner_digest != freeze["commands"]["probe"]["canonical_argv_sha256"]:
    raise SystemExit("inner canonical probe argv digest drift")
if outer_argv[-1] != expected_probe["terminal_mode"] or inner_argv[-1] != expected_probe["terminal_mode"]:
    raise SystemExit("canonical probe terminal mode drift")
forbidden = {"--launch", "--allow-official-input", "--allow-solver", "--allow-publication"}
official_path = freeze["official_input"]["path"]
if forbidden.intersection(outer_argv) or forbidden.intersection(inner_argv) or official_path in outer_argv or official_path in inner_argv:
    raise SystemExit("official-input, solver, or publication capability detected")

expected_execution_argv = [
    "/usr/bin/timeout", "--signal=TERM", "--kill-after=5s", "250s",
    "/usr/bin/bwrap", "--unshare-all", "--new-session", "--die-with-parent",
    "--uid", "0", "--gid", "0", "--cap-drop", "ALL",
    "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev",
    "--tmpfs", "/tmp", "--ro-bind", "/dev/null", official_path,
    "--chdir", "/mnt/d/Stuff/Projects/Sites/Planora", "--clearenv",
    "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
    "--setenv", "LC_ALL", "C.UTF-8", "--setenv", "TZ", "UTC",
    "--", "/usr/bin/bash", "-s",
]
if execution_argv != expected_execution_argv:
    raise SystemExit("host execution argv rejected")

claim_owner_raw = read(claim_owner_path)
claim_owner = json.loads(claim_owner_raw)
expected_claim_keys = {
    "schema", "probe_id", "claim_marker_path", "claimed_at_utc", "hostname",
    "shell_pid", "shell_ppid", "shell_starttime_ticks", "runner_path",
    "atomic_primitive", "claim_retained_on_failure", "retry_allowed",
}
exact_keys(claim_owner, expected_claim_keys, "claim owner")
if (
    claim_owner["schema"] != "planora.itc2019.retained-probe-claim.v1"
    or claim_owner["probe_id"] != probe_id
    or pathlib.Path(claim_owner["claim_marker_path"]) != claim_owner_path.parent
    or claim_owner["runner_path"] != expected_runner_wsl
    or claim_owner["atomic_primitive"] != "mkdir"
    or claim_owner["claim_retained_on_failure"] is not True
    or claim_owner["retry_allowed"] is not False
    or not claim_owner_path.parent.is_dir()
):
    raise SystemExit("claim ownership rejected")


def mem_available_kib() -> int:
    for line in pathlib.Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB":
                return int(fields[1])
    raise SystemExit("MemAvailable unavailable")


KNOWN_WORKLOAD_MARKERS = (
    b"stress-ng",
    b"pytest",
    b"python",
    b"java",
    b"solver",
    b"ortools",
    b"gradle",
    b"mvn",
    b"cargo",
    b"rustc",
    b"gcc",
    b"g++",
    b"clang",
    b"cmake",
    b"ninja",
    b"make",
    b"docker",
    b"podman",
    b"build",
    b"node",
    b"npm",
)
INFRASTRUCTURE_EXECUTABLES = {
    "/init",
    "/usr/lib/systemd/systemd",
    "/usr/lib/systemd/systemd-journald",
    "/usr/lib/systemd/systemd-udevd",
    "/usr/lib/systemd/systemd-resolved",
    "/usr/lib/systemd/systemd-networkd",
    "/usr/bin/dbus-daemon",
    "/usr/libexec/wsl-pro-service",
    "/usr/bin/wsl-pro-service",
}


def process_stat(pid: int) -> dict[str, object]:
    raw = (pathlib.Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    closing = raw.rfind(")")
    opening = raw.find("(")
    if opening <= 0 or closing <= opening + 1:
        raise RuntimeError("malformed stat envelope")
    tail = raw[closing + 2 :].split()
    if len(tail) < 20:
        raise RuntimeError("short stat record")
    return {
        "pid": int(raw[:opening].strip()),
        "comm": raw[opening + 1 : closing],
        "state": tail[0],
        "ppid": int(tail[1]),
        "starttime_ticks": int(tail[19]),
    }


def process_identity(pid: int) -> tuple[int, int]:
    row = process_stat(pid)
    if row["pid"] != pid:
        raise RuntimeError("stat pid mismatch")
    return pid, int(row["starttime_ticks"])


def runner_ancestry() -> dict[int, tuple[int, int]]:
    ancestry: dict[int, tuple[int, int]] = {}
    cursor = os.getpid()
    seen: set[int] = set()
    while cursor > 0:
        if cursor in seen:
            raise RuntimeError("ancestry cycle")
        seen.add(cursor)
        row = process_stat(cursor)
        ancestry[cursor] = (cursor, int(row["starttime_ticks"]))
        parent = int(row["ppid"])
        if parent == cursor:
            raise RuntimeError("self-parent ancestry")
        cursor = parent
    return ancestry


def status_uid_gid(pid: int) -> tuple[int, int]:
    uid_values: list[int] | None = None
    gid_values: list[int] | None = None
    raw = (pathlib.Path("/proc") / str(pid) / "status").read_text(encoding="ascii")
    for line in raw.splitlines():
        if line.startswith("Uid:"):
            fields = line.split()[1:]
            if len(fields) != 4 or any(not value.isdigit() for value in fields):
                raise RuntimeError("malformed Uid status")
            uid_values = [int(value) for value in fields]
        elif line.startswith("Gid:"):
            fields = line.split()[1:]
            if len(fields) != 4 or any(not value.isdigit() for value in fields):
                raise RuntimeError("malformed Gid status")
            gid_values = [int(value) for value in fields]
    if uid_values is None or gid_values is None:
        raise RuntimeError("missing Uid or Gid status")
    if len(set(uid_values)) != 1 or len(set(gid_values)) != 1:
        raise RuntimeError("credential transition observed")
    return uid_values[0], gid_values[0]


def inspect_process(pid: int) -> dict[str, object]:
    before = process_stat(pid)
    uid, gid = status_uid_gid(pid)
    proc = pathlib.Path("/proc") / str(pid)
    executable = os.readlink(proc / "exe")
    cmdline = (proc / "cmdline").read_bytes()
    after = process_stat(pid)
    if (
        (before["pid"], before["starttime_ticks"])
        != (after["pid"], after["starttime_ticks"])
    ):
        raise RuntimeError("process identity changed during census")
    return {
        "pid": pid,
        "ppid": int(after["ppid"]),
        "starttime_ticks": int(after["starttime_ticks"]),
        "state": str(after["state"]),
        "comm": str(after["comm"]),
        "uid": uid,
        "gid": gid,
        "executable": executable,
        "cmdline_sha256": digest(cmdline),
        "cmdline": cmdline,
    }


def minimal_infrastructure(row: dict[str, object]) -> bool:
    executable = str(row["executable"])
    if (
        executable not in INFRASTRUCTURE_EXECUTABLES
        or row["uid"] != 0
        or row["gid"] != 0
    ):
        return False
    argv = [value for value in bytes(row["cmdline"]).split(b"\0") if value]
    if not argv:
        return False
    if executable == "/init":
        return argv[0] == b"/init"
    if executable == "/usr/lib/systemd/systemd":
        return argv[0] in {b"/sbin/init", b"/usr/lib/systemd/systemd"} and all(
            value in {b"--system", b"--user", b"--deserialize", b"--switched-root"}
            or value.isdigit()
            for value in argv[1:]
        )
    if executable == "/usr/bin/dbus-daemon":
        return argv[0] == b"/usr/bin/dbus-daemon" and b"--system" in argv[1:]
    return argv[0].decode("utf-8", "strict") == executable


def workload_classification(row: dict[str, object]) -> str:
    searchable = (
        str(row["executable"]).encode("utf-8", "surrogateescape")
        + b" "
        + bytes(row["cmdline"])
    ).lower()
    if any(marker in searchable for marker in KNOWN_WORKLOAD_MARKERS):
        return "KNOWN_USER_WORKLOAD"
    return "UNKNOWN_USER_WORKLOAD"


def census_policy_self_check() -> dict[str, object]:
    def synthetic(executable: str, cmdline: bytes, uid: int = 1000) -> dict[str, object]:
        return {
            "executable": executable,
            "cmdline": cmdline,
            "uid": uid,
            "gid": uid,
        }

    known = (
        synthetic("/usr/bin/stress-ng", b"stress-ng\x00--cpu\x001\x00"),
        synthetic("/usr/bin/pytest", b"pytest\x00-q\x00"),
        synthetic("/usr/bin/python3", b"python3\x00-m\x00pytest\x00"),
        synthetic("/usr/bin/java", b"java\x00-jar\x00solver.jar\x00"),
        synthetic("/opt/solver", b"solver\x00"),
        synthetic("/usr/bin/ninja", b"ninja\x00build\x00"),
        synthetic("/usr/bin/docker", b"docker\x00run\x00"),
    )
    unknown = synthetic("/opt/custom-task", b"custom-task\x00")
    infrastructure = synthetic(
        "/usr/lib/systemd/systemd-journald",
        b"/usr/lib/systemd/systemd-journald\x00",
        uid=0,
    )
    impersonated_infrastructure = synthetic(
        "/usr/lib/systemd/systemd-journald",
        b"/usr/lib/systemd/systemd-journald\x00",
        uid=1000,
    )
    passed = (
        all(workload_classification(row) == "KNOWN_USER_WORKLOAD" for row in known)
        and workload_classification(unknown) == "UNKNOWN_USER_WORKLOAD"
        and minimal_infrastructure(infrastructure)
        and not minimal_infrastructure(impersonated_infrastructure)
    )
    if not passed:
        raise RuntimeError("conservative process-census policy self-check failed")
    return {
        "known_workload_cases_rejected": len(known),
        "unknown_workload_case_rejected": True,
        "root_minimal_infrastructure_allowed": True,
        "nonroot_infrastructure_impersonation_rejected": True,
        "status": "PASS",
    }


def process_census(index: int) -> dict[str, object]:
    ancestry = runner_ancestry()
    initial_pids = sorted(
        int(entry.name)
        for entry in pathlib.Path("/proc").iterdir()
        if entry.name.isdigit()
    )
    accepted_ancestry: list[dict[str, object]] = []
    accepted_infrastructure: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for pid in initial_pids:
        try:
            row = inspect_process(pid)
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, RuntimeError, UnicodeError) as exc:
            rejected.append(
                {
                    "pid": pid,
                    "classification": "INSPECTION_UNCERTAIN",
                    "error": type(exc).__name__,
                }
            )
            continue
        identity = (pid, int(row["starttime_ticks"]))
        public_row = {key: value for key, value in row.items() if key != "cmdline"}
        if ancestry.get(pid) == identity:
            public_row["classification"] = "CURRENT_RUNNER_ANCESTRY"
            accepted_ancestry.append(public_row)
        elif minimal_infrastructure(row):
            public_row["classification"] = "MINIMAL_WSL_INFRASTRUCTURE"
            accepted_infrastructure.append(public_row)
        else:
            public_row["classification"] = workload_classification(row)
            rejected.append(public_row)
    final_pids = {
        int(entry.name)
        for entry in pathlib.Path("/proc").iterdir()
        if entry.name.isdigit()
    }
    for pid in sorted(final_pids.difference(initial_pids)):
        rejected.append(
            {
                "pid": pid,
                "classification": "APPEARED_DURING_CENSUS",
            }
        )
    return {
        "index": index,
        "policy": "reject_every_non_ancestry_non_minimal_infrastructure_process",
        "accepted_runner_ancestry": accepted_ancestry,
        "accepted_minimal_wsl_infrastructure": accepted_infrastructure,
        "rejected": rejected,
        "rejected_count": len(rejected),
        "status": "PASS" if not rejected else "NO_GO",
    }


lock_before = heavy_lock_path.stat(follow_symlinks=False)
policy_self_check = census_policy_self_check()
heavy_lock_claim_bytes = read(heavy_lock_claim_path)
heavy_lock_claim_payload = json.loads(heavy_lock_claim_bytes)
if (
    not stat.S_ISDIR(lock_before.st_mode)
    or stat.S_IMODE(lock_before.st_mode) != 0o700
    or lock_before.st_uid != os.getuid()
    or heavy_lock_claim_payload.get("schema")
    != "planora.wsl-heavy-task-lock-claim.v1"
    or heavy_lock_claim_payload.get("probe_id") != probe_id
    or heavy_lock_claim_payload.get("device") != int(lock_before.st_dev)
    or heavy_lock_claim_payload.get("inode") != int(lock_before.st_ino)
    or heavy_lock_claim_payload.get("v17_execution_authorized") is not False
):
    raise SystemExit("shared heavy-task lock contract rejected")
sample_one_at = time.monotonic()
sample_one = mem_available_kib()
census_one = process_census(1)
time.sleep(expected_limits["initial_sample_interval_seconds"])
sample_two_at = time.monotonic()
sample_two = mem_available_kib()
census_two = process_census(2)
lock_after = heavy_lock_path.stat(follow_symlinks=False)
interval = sample_two_at - sample_one_at
lock_identity_stable = (
    (lock_before.st_dev, lock_before.st_ino)
    == (lock_after.st_dev, lock_after.st_ino)
)
heavy_gate_pass = (
    lock_identity_stable
    and sample_one >= expected_limits["initial_memavailable_floor_kib"]
    and sample_two >= expected_limits["initial_memavailable_floor_kib"]
    and interval >= expected_limits["initial_sample_interval_seconds"]
    and census_one["status"] == "PASS"
    and census_two["status"] == "PASS"
)
heavy_gate_payload = {
    "schema": "planora.wsl-heavy-task-gate.v1",
    "status": "PASS" if heavy_gate_pass else "NO_GO",
    "probe_id": probe_id,
    "claim_owner_sha256": digest(claim_owner_raw),
    "heavy_lock_claim": {
        "path": str(heavy_lock_claim_path),
        "size_bytes": len(heavy_lock_claim_bytes),
        "sha256": digest(heavy_lock_claim_bytes),
    },
    "lock": {
        "path": str(heavy_lock_path),
        "atomic_primitive": "exclusive_mkdir",
        "device": int(lock_before.st_dev),
        "inode": int(lock_before.st_ino),
        "mode": stat.S_IMODE(lock_before.st_mode),
        "uid": int(lock_before.st_uid),
        "identity_stable": lock_identity_stable,
        "held_until_runner_exit": True,
        "v17_execution_occurred": False,
    },
    "samples": [
        {"index": 1, "mem_available_kib": sample_one, "census": census_one},
        {"index": 2, "mem_available_kib": sample_two, "census": census_two},
    ],
    "observed_interval_seconds": interval,
    "non_allowlisted_process_count": int(census_one["rejected_count"])
    + int(census_two["rejected_count"]),
    "policy_self_check": policy_self_check,
}
heavy_gate_bytes = (
    json.dumps(heavy_gate_payload, indent=2, sort_keys=True) + "\n"
).encode("utf-8")
with heavy_lock_evidence_path.open("xb") as stream:
    stream.write(heavy_gate_bytes)
    stream.flush()
    os.fsync(stream.fileno())
if not heavy_gate_pass:
    raise SystemExit("authoritative shared-lock/process-census gate rejected")

inner_script_raw_bytes = read(inner_script_path)
host_environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}
boundary = {
    "official_input": False,
    "solver": False,
    "checkpoint": None,
    "publication": False,
}
preflight_payload = {
    "schema": "planora.agh-fal17.native-v17-retained-probe-preflight.v1",
    "status": "NO_GO",
    "reason": "frozen_producers_omit_required_checkpoint_evidence",
    "probe_id": probe_id,
    "claim": claim_owner,
    "claim_owner_sha256": digest(claim_owner_raw),
    "authorization": {"path": str(authorization_path), "size_bytes": len(authorization_raw), "sha256": digest(authorization_raw)},
    "execution_wrapper": {"path": str(runner_path), "size_bytes": len(runner_raw), "sha256": digest(runner_raw)},
    "freeze_manifest": {"path": str(freeze_path), "size_bytes": len(freeze_raw), "sha256": digest(freeze_raw)},
    "invocations": {"path": str(invocations_path), "size_bytes": len(invocations_raw), "sha256": digest(invocations_raw)},
    "canonical_probe_commands": {
        "encoding": "utf8_nul_joined",
        "outer_argv": outer_argv,
        "outer_argv_count": len(outer_argv),
        "outer_argv_sha256": outer_digest,
        "inner_argv": inner_argv,
        "inner_argv_count": len(inner_argv),
        "inner_argv_sha256": inner_digest,
        "terminal_mode": "--sealed-import-probe",
    },
    "host_execution": {
        "environment": host_environment,
        "argv": execution_argv,
        "argv_sha256": digest("\0".join(execution_argv).encode("utf-8")),
        "stdin_path": str(inner_script_path),
        "stdin_size_bytes": len(inner_script_raw_bytes),
        "stdin_sha256": digest(inner_script_raw_bytes),
        "textual_bwrap_execution_paths": 1,
        "automatic_retry": False,
    },
    "sandbox_execution_environment": host_environment,
    "official_input_mask": {"source": "/dev/null", "destination": official_path, "read_only": True},
    "execution_boundaries": boundary,
    "producer_checkpoint_evidence": expected_checkpoint_evidence,
    "successor_chain_required": True,
    "resource_limits": expected_limits,
    "memory_gate": {
        "samples": [
            {"index": 1, "mem_available_kib": sample_one},
            {"index": 2, "mem_available_kib": sample_two},
        ],
        "observed_interval_seconds": interval,
        "authoritative_heavy_task_gate_path": str(heavy_lock_evidence_path),
        "authoritative_heavy_task_gate_sha256": digest(heavy_gate_bytes),
        "non_allowlisted_process_count": heavy_gate_payload[
            "non_allowlisted_process_count"
        ],
    },
    "heavy_task_gate": heavy_gate_payload,
    "pin_replay": {
        "artifacts": len(freeze["artifacts"]),
        "source_closure": len(freeze["source_closure"]),
        "runtime_records": len(freeze["runtime_records"]),
        "runtime_pins": 2,
        "all_exact": True,
    },
    "authorization_snapshot_path": str(authorization_snapshot),
    "invocations_snapshot_path": str(invocations_snapshot),
}
for path, payload in (
    (authorization_snapshot, authorization_raw),
    (invocations_snapshot, invocations_raw),
    (preflight_path, (json.dumps(preflight_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")),
):
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
raise SystemExit(
    "AGH v17 retained probe NO-GO: successor chain must emit exact checkpoint evidence"
)
PY

set +e
/usr/bin/env -i \
    PATH=/usr/bin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    "${execution_argv[@]}" \
    >"$prefix.stdout.json" \
    2>"$prefix.stderr.log" \
    <"$inner_script"
probe_exit=$?
set -e

printf '%s\n' "$probe_exit" >"$prefix.exit-code.txt"

set +e
/usr/bin/python3.12 -I -S -B - \
    "$authorization" "$runner" \
    "$chain/agent-aghfal17-native-v17-review-freeze.json" \
    "$chain/agent-aghfal17-native-v17-invocations.json" \
    "$claim_owner" "$inner_script" "$preflight" "$heavy_lock_claim" \
    "$heavy_lock_evidence" \
    "$prefix.authorization.json" "$prefix.invocations.json" \
    "$prefix.stdout.json" "$prefix.stderr.log" "$prefix.exit-code.txt" \
    "$checksums" "$result_receipt" "$probe_id" <<'PY'
import hashlib
import json
import os
import pathlib
import sys
from typing import Any

(
    authorization_raw,
    runner_raw,
    freeze_raw,
    invocations_raw,
    claim_owner_raw,
    inner_script_raw,
    preflight_raw,
    heavy_lock_claim_raw,
    heavy_lock_evidence_raw,
    authorization_snapshot_raw,
    invocations_snapshot_raw,
    stdout_raw,
    stderr_raw,
    exit_code_raw,
    checksums_raw,
    result_receipt_raw,
    probe_id,
) = sys.argv[1:]
authorization = pathlib.Path(authorization_raw)
runner = pathlib.Path(runner_raw)
freeze = pathlib.Path(freeze_raw)
invocations = pathlib.Path(invocations_raw)
claim_owner = pathlib.Path(claim_owner_raw)
inner_script = pathlib.Path(inner_script_raw)
preflight = pathlib.Path(preflight_raw)
heavy_lock_claim = pathlib.Path(heavy_lock_claim_raw)
heavy_lock_evidence = pathlib.Path(heavy_lock_evidence_raw)
authorization_snapshot = pathlib.Path(authorization_snapshot_raw)
invocations_snapshot = pathlib.Path(invocations_snapshot_raw)
stdout_path = pathlib.Path(stdout_raw)
stderr_path = pathlib.Path(stderr_raw)
exit_code_path = pathlib.Path(exit_code_raw)
checksums_path = pathlib.Path(checksums_raw)
result_receipt_path = pathlib.Path(result_receipt_raw)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def row(path: pathlib.Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {"path": str(path), "size_bytes": len(raw), "sha256": digest(raw)}


evidence_paths = {
    "authorization": authorization,
    "execution_wrapper": runner,
    "freeze_manifest": freeze,
    "invocations": invocations,
    "claim_owner": claim_owner,
    "inner_script": inner_script,
    "preflight": preflight,
    "heavy_lock_claim": heavy_lock_claim,
    "heavy_lock_evidence": heavy_lock_evidence,
    "authorization_snapshot": authorization_snapshot,
    "invocations_snapshot": invocations_snapshot,
    "stdout": stdout_path,
    "stderr": stderr_path,
    "exit_code": exit_code_path,
}
checksum_payload = {
    "schema": "planora.agh-fal17.native-v17-retained-probe-checksums.v1",
    "probe_id": probe_id,
    "rows": {label: row(path) for label, path in evidence_paths.items()},
}
checksum_bytes = (json.dumps(checksum_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
with checksums_path.open("xb") as stream:
    stream.write(checksum_bytes)
    stream.flush()
    os.fsync(stream.fileno())

errors: list[str] = []
predicates: dict[str, bool] = {}


def exact_json_object(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        payload, end = json.JSONDecoder().raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"{label}_json:{type(exc).__name__}")
        return {}
    if text[end:].strip() or not isinstance(payload, dict):
        errors.append(f"{label}_json:not_exact_object")
        return {}
    return payload


preflight_payload = exact_json_object(preflight, "preflight")
outer = exact_json_object(stdout_path, "stdout")
inner = outer.get("inner_payload") if isinstance(outer.get("inner_payload"), dict) else {}
cleanup = outer.get("cleanup") if isinstance(outer.get("cleanup"), dict) else {}
try:
    probe_exit = int(exit_code_path.read_text(encoding="ascii").strip())
except (ValueError, OSError) as exc:
    errors.append(f"exit_code:{type(exc).__name__}")
    probe_exit = -1

preflight_hashes_stable = all(
    checksum_payload["rows"][label]["sha256"]
    == preflight_payload.get(preflight_key, {}).get("sha256")
    for label, preflight_key in (
        ("authorization", "authorization"),
        ("execution_wrapper", "execution_wrapper"),
        ("freeze_manifest", "freeze_manifest"),
        ("invocations", "invocations"),
    )
)
snapshots_exact = (
    authorization.read_bytes() == authorization_snapshot.read_bytes()
    and invocations.read_bytes() == invocations_snapshot.read_bytes()
)
claim_owner_hash_stable = (
    checksum_payload["rows"]["claim_owner"]["sha256"]
    == preflight_payload.get("claim_owner_sha256")
)
inner_script_hash_stable = (
    checksum_payload["rows"]["inner_script"]["sha256"]
    == preflight_payload.get("host_execution", {}).get("stdin_sha256")
)
final_snapshots = cleanup.get("final_discovery_snapshots")
zero_snapshots = (
    isinstance(final_snapshots, list)
    and len(final_snapshots) >= 2
    and all(isinstance(item, dict) and item.get("status") == "ZERO" for item in final_snapshots[-2:])
)
outer_commands = preflight_payload.get("canonical_probe_commands", {})
outer_argv = outer_commands.get("outer_argv", [])
inner_argv = outer_commands.get("inner_argv", [])
memory_gate = preflight_payload.get("memory_gate", {})
memory_samples = memory_gate.get("samples", [])
heavy_task_gate = preflight_payload.get("heavy_task_gate", {})
heavy_samples = heavy_task_gate.get("samples", [])
memory_gate_exact = (
    isinstance(memory_samples, list)
    and len(memory_samples) == 2
    and all(
        isinstance(sample, dict)
        and sample.get("index") == index
        and isinstance(sample.get("mem_available_kib"), int)
        and sample["mem_available_kib"] >= 1_900_000
        for index, sample in enumerate(memory_samples, 1)
    )
    and isinstance(memory_gate.get("observed_interval_seconds"), (int, float))
    and memory_gate["observed_interval_seconds"] >= 5
    and type(heavy_task_gate) is dict
    and heavy_task_gate.get("schema") == "planora.wsl-heavy-task-gate.v1"
    and heavy_task_gate.get("status") == "PASS"
    and heavy_task_gate.get("non_allowlisted_process_count") == 0
    and isinstance(heavy_samples, list)
    and len(heavy_samples) == 2
    and all(
        isinstance(sample, dict)
        and sample.get("census", {}).get("status") == "PASS"
        and sample.get("census", {}).get("rejected_count") == 0
        for sample in heavy_samples
    )
    and heavy_task_gate.get("lock", {}).get("atomic_primitive")
    == "exclusive_mkdir"
    and heavy_task_gate.get("lock", {}).get("identity_stable") is True
)
official_mask_exact = preflight_payload.get("official_input_mask") == {
    "source": "/dev/null",
    "destination": "/mnt/d/Stuff/Projects/Sites/Planora/data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/agh-fal17.xml",
    "read_only": True,
}
forbidden_checkpoint_tokens = {"--checkpoint", "--resume-checkpoint", "--load-checkpoint"}


def exact_builtin_false(payload: object, key: str) -> bool:
    return (
        type(payload) is dict
        and key in payload
        and type(payload[key]) is bool
        and payload[key] is False
    )


checkpoint_key = "checkpoint_or_certified_provenance_used"
checkpoint_adversarial_values = (
    {},
    {checkpoint_key: None},
    {checkpoint_key: 0},
    {checkpoint_key: "false"},
    {checkpoint_key: True},
    {checkpoint_key: False},
)
checkpoint_adversarial_expected = (False, False, False, False, False, True)
checkpoint_adversarial_actual = tuple(
    exact_builtin_false(payload, checkpoint_key)
    for payload in checkpoint_adversarial_values
)
if checkpoint_adversarial_actual != checkpoint_adversarial_expected:
    raise RuntimeError("exact checkpoint boolean self-check failed")
checkpoint_false = (
    not forbidden_checkpoint_tokens.intersection(outer_argv)
    and not forbidden_checkpoint_tokens.intersection(inner_argv)
    and exact_builtin_false(outer, checkpoint_key)
    and exact_builtin_false(inner, checkpoint_key)
)
predicates.update(
    {
        "probe_exit_zero": probe_exit == 0,
        "preflight_pass": preflight_payload.get("schema") == "planora.agh-fal17.native-v17-retained-probe-preflight.v1" and preflight_payload.get("status") == "PASS" and preflight_payload.get("probe_id") == probe_id,
        "claim_owned_and_retry_false": claim_owner.parent.is_dir() and preflight_payload.get("claim", {}).get("retry_allowed") is False,
        "claim_owner_hash_stable": claim_owner_hash_stable,
        "preflight_hashes_stable": preflight_hashes_stable,
        "inner_script_hash_stable": inner_script_hash_stable,
        "snapshots_exact": snapshots_exact,
        "memory_gate_exact": memory_gate_exact,
        "official_input_mask_exact": official_mask_exact,
        "frozen_outer_argv_exact": outer_commands.get("outer_argv_count") == 40 and outer_commands.get("outer_argv_sha256") == "bcab8bc73f21c72be120fb89e66bd9d614ff4e58d1ed7b1b158bf65f6e4af0cb",
        "frozen_inner_argv_exact": outer_commands.get("inner_argv_count") == 29 and outer_commands.get("inner_argv_sha256") == "a94419760f9cd5ac58a26cffaebc0ee7dc3ba87e78681620632586665c988fe3",
        "outer_schema_exact": outer.get("schema") == "planora.agh-fal17.native-v17-outer-controller.v1",
        "outer_status_pass": outer.get("status") == "PASS",
        "outer_mode_probe": outer.get("mode") == "probe",
        "outer_authoritative": outer.get("outer_authoritative") is True,
        "outer_errors_empty": outer.get("errors") == [],
        "breach_absent": outer.get("breach") is None,
        "contained_root_exit_zero": outer.get("contained_root_exit_code") == 0,
        "cleanup_empty": cleanup.get("empty") is True and outer.get("post_exit_empty") is True,
        "cleanup_error_free": cleanup.get("errors") == [],
        "cleanup_two_stable_zero_snapshots": cleanup.get("stable_zero_snapshots") == 2 and cleanup.get("stable_zero_snapshots_required") == 2 and zero_snapshots,
        "inner_status_pass": inner.get("schema") == "planora.agh-fal17.native-v17-sealed-import-supervisor.v1" and inner.get("status") == "PASS",
        "official_input_false": outer.get("official_instance_opened") is False and inner.get("official_instance_opened") is False,
        "solver_false": outer.get("solver_child_process_started") is False and inner.get("solver_child_process_started") is False and inner.get("solver_execution_started") is False,
        "checkpoint_false": checkpoint_false,
        "publication_false": outer.get("publication") is False and inner.get("publication") is False and inner.get("official_solution_xml_published") is False,
        "process_group_signal_false": outer.get("numeric_process_group_signal_sent") is False and cleanup.get("numeric_process_group_signal_sent") is False,
        "inner_argv_digest_exact": outer.get("canonical_argv_sha256") == "a94419760f9cd5ac58a26cffaebc0ee7dc3ba87e78681620632586665c988fe3",
        "accounting_peak_retained": isinstance(outer.get("peak_accounting"), dict),
    }
)
for name, passed in predicates.items():
    if not passed:
        errors.append(f"acceptance:{name}")

result = {
    "schema": "planora.agh-fal17.native-v17-retained-probe-result.v1",
    "probe_id": probe_id,
    "status": "PASS" if not errors else "NO_GO",
    "automatic_retry_authorized": False,
    "claim_marker_retained": claim_owner.parent.is_dir(),
    "acceptance_predicates": predicates,
    "errors": errors,
    "execution_boundaries": {
        "official_input": False if predicates.get("official_input_false") else None,
        "solver": False if predicates.get("solver_false") else None,
        "checkpoint": False if predicates.get("checkpoint_false") else None,
        "publication": False if predicates.get("publication_false") else None,
    },
    "probe_exit_code": probe_exit,
    "outer_status": outer.get("status"),
    "breach": outer.get("breach"),
    "contained_root_exit_code": outer.get("contained_root_exit_code"),
    "peak_accounting": outer.get("peak_accounting"),
    "cleanup": cleanup,
    "checksums": {
        "path": str(checksums_path),
        "size_bytes": len(checksum_bytes),
        "sha256": digest(checksum_bytes),
    },
}
result_bytes = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
with result_receipt_path.open("xb") as stream:
    stream.write(result_bytes)
    stream.flush()
    os.fsync(stream.fileno())
raise SystemExit(0 if not errors else 2)
PY
acceptance_exit=$?
set -e

if test "$acceptance_exit" -ne 0; then
    exit "$acceptance_exit"
fi
exit 0
