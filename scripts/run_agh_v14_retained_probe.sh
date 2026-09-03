#!/usr/bin/env bash
set -euo pipefail

repo=/mnt/d/Stuff/Projects/Sites/Planora
chain="$repo/benchmarks/probe_diagnostics/agh_v14"
out="$repo/output/diagnostic-receipts"
probe_id=f95129553c8040529e356bef6802da98
prefix="$out/agh-fal17-v14-retained-probe-$probe_id"
authorization="$out/agh-fal17-v14-retained-probe-authorization-20260827T030610Z.receipt.json"

test ! -e "$prefix.stdout.json"
test ! -e "$prefix.stderr.log"
test ! -e "$prefix.exit-code.txt"
test ! -e "$prefix.invocations.json"

/usr/bin/python3.12 -I -S -B - "$repo" "$chain" "$authorization" <<'PY'
import hashlib
import json
import pathlib
import sys

repo = pathlib.Path(sys.argv[1])
chain = pathlib.Path(sys.argv[2])
authorization_path = pathlib.Path(sys.argv[3])
freeze_path = chain / "agent-aghfal17-native-v14-review-freeze.json"
invocations_path = chain / "agent-aghfal17-native-v14-invocations.json"


def read(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def verify(path: pathlib.Path, row: dict[str, object], label: str) -> None:
    payload = read(path)
    actual = hashlib.sha256(payload).hexdigest()
    if len(payload) != row["size_bytes"] or actual != row["sha256"]:
        raise SystemExit(f"PIN DRIFT: {label}: {path}")


authorization_raw = read(authorization_path)
if hashlib.sha256(authorization_raw).hexdigest() != "2e98c7a18870659a23c7103f2b7d26ee24e55b989b55ee92e9cf7d511ad31a86":
    raise SystemExit("authorization receipt drift")
authorization = json.loads(authorization_raw)
if (
    authorization["probe_id"] != "f95129553c8040529e356bef6802da98"
    or authorization["decision"] != "GO_FOR_EXACTLY_ONE_RETAINED_NO_SOLVER_PROBE"
    or authorization["official_launch_authorized"]
    or authorization["official_input_authorized"]
    or authorization["automatic_retry_authorized"]
):
    raise SystemExit("authorization boundary rejected")

freeze_raw = read(freeze_path)
freeze = json.loads(freeze_raw)
invocations_raw = read(invocations_path)
invocations = json.loads(invocations_raw)

if hashlib.sha256(invocations_raw).hexdigest() != "1a4c76f565563d40d191818931997fc8e5a6c4102ccd967677a9160f6d46d807":
    raise SystemExit("invocation evidence drift")
if hashlib.sha256(freeze_raw).hexdigest() != invocations["freeze_manifest"]["sha256"]:
    raise SystemExit("freeze-manifest pin drift")

for label, row in freeze["artifacts"].items():
    verify(chain / pathlib.PurePosixPath(row["path"]).name, row, f"artifact:{label}")
for relative, row in freeze["source_closure"].items():
    verify(repo / relative, row, f"source:{relative}")
for label, row in freeze["runtime_records"].items():
    verify(repo / row["path"], row, f"runtime-record:{label}")
for label in ("python", "bash"):
    row = freeze["runtime_pins"][label]
    verify(pathlib.Path(row["path"]), row, f"runtime-pin:{label}")

argv = invocations["probe"]["argv"]
if any(not isinstance(value, str) or "\0" in value for value in argv):
    raise SystemExit("canonical probe argv contains an invalid element")
digest = hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()
expected = "7fb4cb909e149a0fa2124c48b676ecd4dcc6d1f0242dfb37b24d318f4a946543"
if digest != expected or digest != invocations["probe"]["canonical_argv_sha256"]:
    raise SystemExit("canonical probe argv digest drift")
official_path = freeze["official_input"]["path"]
forbidden = {"--launch", "--allow-official-input", "--allow-solver", "--allow-publication"}
if argv[-1] != "--sealed-import-probe":
    raise SystemExit("probe terminal mode drift")
if forbidden.intersection(argv) or official_path in argv:
    raise SystemExit("official-launch or official-input argument detected")

print("AGH v14 preflight PASS")
print("freeze_sha256=" + hashlib.sha256(freeze_raw).hexdigest())
print("canonical_probe_argv_sha256=" + digest)
print("official_input_opened=false")
PY

for sample in 1 2; do
    available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    test "$available" -ge 1900000 || {
        echo "MemAvailable gate failed: $available KiB" >&2
        exit 1
    }
    if pgrep -af 'agent-.*(outer-controller|supervisor|runner)|--sealed-import-probe|--launch|itc2019.*solve' \
        | grep -v -E "($$|pgrep -af)" >/dev/null
    then
        echo "Competing heavy WSL process detected" >&2
        exit 1
    fi
    echo "MemAvailable sample $sample: $available KiB"
    test "$sample" -eq 2 || sleep 5
done

cp -- "$chain/agent-aghfal17-native-v14-invocations.json" "$prefix.invocations.json"

set +e
timeout --signal=TERM --kill-after=5s 250s \
    /usr/bin/bwrap \
    --unshare-all \
    --new-session \
    --die-with-parent \
    --uid 0 \
    --gid 0 \
    --cap-drop ALL \
    --ro-bind / / \
    --proc /proc \
    --dev /dev \
    --tmpfs /tmp \
    --ro-bind /dev/null \
      /mnt/d/Stuff/Projects/Sites/Planora/data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/agh-fal17.xml \
    --chdir /mnt/d/Stuff/Projects/Sites/Planora \
    --clearenv \
    --setenv PATH /usr/bin:/bin \
    --setenv LANG C.UTF-8 \
    --setenv LC_ALL C.UTF-8 \
    --setenv TZ UTC \
    -- /usr/bin/bash -s \
    >"$prefix.stdout.json" \
    2>"$prefix.stderr.log" <<'INNER'
set -euo pipefail

src=/mnt/d/Stuff/Projects/Sites/Planora/benchmarks/probe_diagnostics/agh_v14

stage() {
    /usr/bin/install -m 0400 -- "$src/$1" "/tmp/$1"
}

stage agent-aghfal17-native-v14-outer-controller.py
stage agent-aghfal17-native-v14-review-freeze.json
stage agent-aghfal17-native-v14-bootstrap.py
stage agent-aghfal17-native-v14-launcher.sh
stage agent-aghfal17-native-v14-supervisor.py
stage agent-aghfal17-native-v14-runner.py
stage agent-aghfal17-native-v14-minimal-tcb.sha256
stage agent-aghfal17-native-v14-stdlib.sha256

/usr/bin/python3.12 -I -S -B - "$src" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

src = pathlib.Path(sys.argv[1])
invocations = json.loads(
    (src / "agent-aghfal17-native-v14-invocations.json").read_bytes()
)
freeze_raw = pathlib.Path(
    "/tmp/agent-aghfal17-native-v14-review-freeze.json"
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

argv = invocations["probe"]["argv"]
digest = hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()
expected = "7fb4cb909e149a0fa2124c48b676ecd4dcc6d1f0242dfb37b24d318f4a946543"
if digest != expected or argv[-1] != "--sealed-import-probe":
    raise SystemExit("canonical probe argv rejected")
if "--launch" in argv or freeze["official_input"]["path"] in argv:
    raise SystemExit("official execution boundary rejected")

environment = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
}
os.execve(argv[0], argv, environment)
PY
INNER
probe_exit=$?
set -e

printf '%s\n' "$probe_exit" >"$prefix.exit-code.txt"
sha256sum \
    "$prefix.invocations.json" \
    "$prefix.stdout.json" \
    "$prefix.stderr.log" \
    "$prefix.exit-code.txt"

exit "$probe_exit"
