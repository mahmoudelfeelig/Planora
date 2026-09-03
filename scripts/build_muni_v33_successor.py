from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
V32_RUN_ID = "4dc45edcd74446909290afadd5d3ecf0"
RUN_ID = "2339df35f57e441a8f92bd1f890fa68f"
STAMP = "20260828T141639Z"
CREATED_AT = "2026-08-28T14:16:39Z"
V32_RUNNER = REPO / "scripts/run_muni_v32_canonical_tests.ps1"
V33_RUNNER = REPO / "scripts/run_muni_v33_canonical_tests.ps1"
V33_TESTS = REPO / "tests/test_run_muni_v33_successor.py"
V33_AUTH = (
    REPO
    / "output/diagnostic-receipts"
    / f"muni-fspsx-v33-canonical-tests-authorization-{STAMP}.receipt.json"
)


PINS = json.loads(
    r"""[
{"path":"scripts/build_muni_v32_successor.py","size":67244,"sha256":"0f40634fd7521318b375225a60bc3d1a935bc0a952915f5a3a0857c7d827ba9a","file_id":"0000000000000000000300000017c009","last_write_utc_ticks":639235212275291720},
{"path":"scripts/run_muni_v32_canonical_tests.ps1","size":279918,"sha256":"9af9e31ec1820183cc216f5b67beaea9836e9f547116e43658505af2f5c6543c","file_id":"0000000000000000000600000017c00b","last_write_utc_ticks":639235213445549061},
{"path":"tests/test_run_muni_v32_successor.py","size":28634,"sha256":"2875be0c8c64d48ff2fe5557b3a7e1e7f43ebd14232a226ac078cb0e0a96e693","file_id":"0000000000000000000200000017c00d","last_write_utc_ticks":639235212434722970},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-tests-authorization-20260828T130114Z.receipt.json","size":32075,"sha256":"e60478a0f9bc8bad4a7c49123a5f9da353e608ed472191579232df2732b65d51","file_id":"0000000000000000000400000017c010","last_write_utc_ticks":639235213453536795},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-independent-review-20260828T135032Z.receipt.json","size":7206,"sha256":"75147c5ed140c55ea4395e852cce3a73371c632ea481c61efe7317c354f87e2d","file_id":"0000000000000000000200000017c4e2","last_write_utc_ticks":639235218865814146},
{"path":"scripts/run_muni_v32_terminal_gate_once.ps1","size":15717,"sha256":"d9a30e1d172206bb1223d579f4be4a8681a4661362175b178f2a6933f68c2060","file_id":"0000000000000000000200000017c4f3","last_write_utc_ticks":639235220267260660},
{"path":"tests/test_run_muni_v32_terminal_gate_once.py","size":6532,"sha256":"399b4f824cd1f221280a5ae4870d4dfe2fa55a1e5312ac313e6b48427a906cdf","file_id":"0000000000000000000200000017c4fa","last_write_utc_ticks":639235221383761574},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-terminal-gate-independent-review-20260828T140259Z.receipt.json","size":2137,"sha256":"584797bbf52dfc0d15b4f5855dc6723a0897b05fe93495be31761c4d7dd0c487","file_id":"0000000000000000000200000017c513","last_write_utc_ticks":639235226037389279},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.claim.json","size":541,"sha256":"bbfcd508eef6a619fdf78b009ce583d877dce1bd9d505b86855f501ba81ecbc2","file_id":"0000000000000000000800000017be80","last_write_utc_ticks":639235227947942144},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.heavy-lock-release.json","size":460,"sha256":"b7c6ef0cd8775976d1b42ad4c5a66b27712fe81b2fb70e2d17be94ad390d9635","file_id":"0000000000000000000700000017be88","last_write_utc_ticks":639235228659539618},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.heavy-lock.json","size":3176,"sha256":"f9be5767d685ec9c1b26a07e64180ac957555de032b452edff0413152db32b61","file_id":"0000000000000000000600000017be8b","last_write_utc_ticks":639235228048399187},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.mutation-watch.error.log","size":179,"sha256":"608ec8ead061d977f88c3aafe366cc8f51a2851e095590b9947dc3b1403c503d","file_id":"0000000000000000000600000017be8d","last_write_utc_ticks":639235228572742169},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.mutation-watch.jsonl","size":44633,"sha256":"bc2b7cfeb8c75fcfa32c19e08e2336e83ab522d592d93628f05cca838ad60962","file_id":"0000000000000000000600000017be8c","last_write_utc_ticks":639235228558027831},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.mutation-watch.stop","size":146,"sha256":"aadf0cf652c9675d20e8ea540d764032298c8464bf69079d6cd70026faf8bfac","file_id":"0000000000000000000200000017c554","last_write_utc_ticks":639235228572360073},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.mutation-watch.wrapper.stderr.log","size":218,"sha256":"7e860067f2756a2196e9396d05307695fd14197d1a22029e70cc3e55f3ce1d84","file_id":"0000000000000000000b00000017be7f","last_write_utc_ticks":639235228573184584},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.mutation-watch.wrapper.stdout.log","size":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","file_id":"000000000000000000150000001416d4","last_write_utc_ticks":639235228573154597},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.pre-inventory.json","size":847403,"sha256":"0fd29582a2159cd58595b458b7832e478d64735b0ea4a594a3e9cda6d1adf4a3","file_id":"0000000000000000000300000017c51a","last_write_utc_ticks":639235228563941029},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.predecessor-custody.json","size":9473907,"sha256":"7fad611c4afd891a435b81fc3ed58c0fe857703b9419552729a75209dfd67fba","file_id":"0000000000000000000700000017be86","last_write_utc_ticks":639235228033659376},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.rejection.json","size":1973307,"sha256":"850046811001360794940884b22cf301b8da80f15e76d39caf585c2ae3439b21","file_id":"0000000000000000000800000017be84","last_write_utc_ticks":639235228659281574},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.resource-exclusivity.error.log","size":246,"sha256":"ba94f358f8842477ba04715c80146e79f628edcc3ae6362367e1b4ff656a0026","file_id":"0000000000000000000300000017c51c","last_write_utc_ticks":639235228571583461},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.resource-exclusivity.jsonl","size":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","file_id":"0000000000000000000300000017c51b","last_write_utc_ticks":639235228571465296},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.resource-exclusivity.stop","size":38,"sha256":"87746647405a9432702dd37103d616dd4148ad671dba4212ae2e49fe952b2aa2","file_id":"0000000000000000000300000017c51d","last_write_utc_ticks":639235228572229749},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.resource-exclusivity.wrapper.stderr.log","size":285,"sha256":"6ec38aab2742def8497b204b4dfa50eece4f2041f31a664932003b8f6b5be830","file_id":"0000000000000000000200000017c553","last_write_utc_ticks":639235228572269721},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.resource-exclusivity.wrapper.stdout.log","size":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","file_id":"0000000000000000000200000017c552","last_write_utc_ticks":639235228572259721},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.retained-v30-snapshot-custody.json","size":1425,"sha256":"f126469dfde456029f5fd3dae0605301a600c17df48597993d54df0c648e6ab9","file_id":"0000000000000000000600000017be89","last_write_utc_ticks":639235228040638604},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.retained-v31-snapshot-custody.json","size":1425,"sha256":"9148371ac4f2f390ad52eb6c7ea1a3cbd1e5f192f8eca944abdbb99db39ce680","file_id":"0000000000000000000600000017be8a","last_write_utc_ticks":639235228047437684},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.staging-inventory.json","size":847403,"sha256":"0fd29582a2159cd58595b458b7832e478d64735b0ea4a594a3e9cda6d1adf4a3","file_id":"0000000000000000000300000017c519","last_write_utc_ticks":639235228534343690},
{"path":"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.static-adversarial.json","size":2916,"sha256":"68fda04bd92e08ea15eef041ef0e1660a9f68ffd50893660953ace965b881590","file_id":"0000000000000000000700000017be85","last_write_utc_ticks":639235228030561724}
]"""
)
PIN_BY_PATH = {row["path"]: row for row in PINS}

V32_SOURCE_PATHS = {
    "builder": "scripts/build_muni_v32_successor.py",
    "runner": "scripts/run_muni_v32_canonical_tests.ps1",
    "tests": "tests/test_run_muni_v32_successor.py",
    "authorization": "output/diagnostic-receipts/muni-fspsx-v32-canonical-tests-authorization-20260828T130114Z.receipt.json",
}
V32_PROVENANCE_PATHS = {
    "independent_review": "output/diagnostic-receipts/muni-fspsx-v32-independent-review-20260828T135032Z.receipt.json",
    "terminal_gate": "scripts/run_muni_v32_terminal_gate_once.ps1",
    "terminal_gate_tests": "tests/test_run_muni_v32_terminal_gate_once.py",
    "terminal_gate_review": "output/diagnostic-receipts/muni-fspsx-v32-terminal-gate-independent-review-20260828T140259Z.receipt.json",
}
V32_PREFIX = (
    f"output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-{V32_RUN_ID}"
)
V32_ARTIFACT_SUFFIXES = {
    "claim": "claim.json",
    "heavy_lock_release": "heavy-lock-release.json",
    "heavy_lock": "heavy-lock.json",
    "watch_error": "mutation-watch.error.log",
    "watch_log": "mutation-watch.jsonl",
    "watch_stop": "mutation-watch.stop",
    "watch_wrapper_stderr": "mutation-watch.wrapper.stderr.log",
    "watch_wrapper_stdout": "mutation-watch.wrapper.stdout.log",
    "pre_inventory": "pre-inventory.json",
    "predecessor_custody": "predecessor-custody.json",
    "rejection": "rejection.json",
    "resource_error": "resource-exclusivity.error.log",
    "resource_log": "resource-exclusivity.jsonl",
    "resource_stop": "resource-exclusivity.stop",
    "resource_wrapper_stderr": "resource-exclusivity.wrapper.stderr.log",
    "resource_wrapper_stdout": "resource-exclusivity.wrapper.stdout.log",
    "retained_v30_snapshot_custody": "retained-v30-snapshot-custody.json",
    "retained_v31_snapshot_custody": "retained-v31-snapshot-custody.json",
    "staging_inventory": "staging-inventory.json",
    "static_evidence": "static-adversarial.json",
}
V32_EXPECTED_ABSENT_SUFFIXES = [
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
    "retained-v30-snapshot-terminal-custody.json",
    "retained-v31-snapshot-terminal-custody.json",
]


def pinned(path: str) -> dict[str, Any]:
    return dict(PIN_BY_PATH[path])


V32_SOURCES = {name: pinned(path) for name, path in V32_SOURCE_PATHS.items()}
V32_PROVENANCE = {name: pinned(path) for name, path in V32_PROVENANCE_PATHS.items()}
V32_ARTIFACTS = {
    name: pinned(f"{V32_PREFIX}.{suffix}")
    for name, suffix in V32_ARTIFACT_SUFFIXES.items()
}

V32_FAILURE_CONTRACT = {
    "schema": "planora.muni-v33.v32-failure-custody-contract.v1",
    "run_id": V32_RUN_ID,
    "sources": V32_SOURCES,
    "launch_provenance": V32_PROVENANCE,
    "artifacts": V32_ARTIFACTS,
    "artifact_count": 20,
    "carried_predecessor_pin_count": 61,
    "direct_source_provenance_artifact_pin_count": 28,
    "initial_predecessor_evidence_sha256": "03af9aef297ba477d3aca0080c8e3e210af9e8736260a54ce0faa4815f58b7d3",
    "post_rejection_predecessor_evidence_sha256": "1ffb6b7e782cf044a4f9e7dd7c8afb0020f8fd0564d263fdad2c72b6398c452a",
    "initial_v31_failure_evidence_sha256": "ed30f958050f827ea0adcd57cfa969ebb8a6ebcd904c74f13e07bcdd8ebc77af",
    "post_rejection_v31_failure_evidence_sha256": "5ac1064000f9386de606bb8daa759c50064c67ff41f80312919b4dd136a2cc15",
    "failure": {
        "status": "REJECTED_AUTHORIZATION_CONSUMED",
        "message": "Resource monitor exited before READY; resource_monitor_stop=Resource monitor wrapper rejected: exit=1; watcher_stop=Watcher wrapper rejected: exit=1",
        "phase": "after_preinventory_during_resource_monitor_first_sample_before_ready_and_canonical_launch",
        "primary_root_cause": "unhandled_PermissionError_from_os_stat_proc_1_mount_namespace_magic_link",
        "resource_launch_attempted": True,
        "canonical_launch_attempted": False,
        "canonical_suite_executed": False,
        "automatic_retry_authorized": False,
    },
    "snapshot": {
        "root": f"/tmp/planora-muni-v32-canonical-tests-{V32_RUN_ID}",
        "inventory": V32_ARTIFACTS["staging_inventory"],
        "pre_inventory": V32_ARTIFACTS["pre_inventory"],
        "files": 3146,
        "directories": 368,
        "bytes": 190900047,
        "retained_for_forensics": True,
        "must_not_be_reused_or_deleted_by_v33": True,
    },
    "expected_absent_suffixes": V32_EXPECTED_ABSENT_SUFFIXES,
    "pass_receipt": f"{V32_PREFIX}.receipt.json",
    "pass_seal": f"{V32_PREFIX}.pass-publication-shutdown-seal.json",
    "predecessor_custody_status": "EXACT_V28_V29_V30_V31_CUSTODY_VALIDATED_BEFORE_V32_LOCK",
    "resource_error_sha256": V32_ARTIFACTS["resource_error"]["sha256"],
    "resource_wrapper_stderr_sha256": V32_ARTIFACTS["resource_wrapper_stderr"][
        "sha256"
    ],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"anchor count {count}, expected 1: {old[:160]!r}")
    return text.replace(old, new, 1)


def replace_count(text: str, old: str, new: str, expected: int) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"anchor count {count}, expected {expected}: {old[:160]!r}")
    return text.replace(old, new)


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
        raise RuntimeError(f"pinned v32 predecessor drift: {path}")
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
        raise RuntimeError(f"pinned v32 predecessor identity drift: {path}")


RESOURCE_MONITOR_BLOCK = r"""$resourceMonitorSource = @'
import errno,hashlib,json,os,re,stat,sys,time,traceback
c=json.loads(__import__('base64').b64decode(sys.argv[1]));stop=c['stop'];log_path=c['log'];error_path=c['error'];watcher_pid=int(c['watcher_pid']);timeout_argv=c['timeout_argv'];bwrap_argv=c['bwrap_argv'];test_argv=c['test_argv'];minimum=int(c['minimum_kib']);target_ns=int(c['target_interval_ms'])*1000000;max_gap_ns=int(c['maximum_gap_ms'])*1000000;subprocess_sites=int(c['subprocess_sites']);canonical_token_sha256=str(c['canonical_token_sha256']);readiness_self_test=bool(c.get('readiness_self_test',False))
if len(canonical_token_sha256)!=64 or any(ch not in '0123456789abcdef' for ch in canonical_token_sha256): raise RuntimeError('canonical token digest rejected')
def reserve(path):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
 try: os.fsync(fd);s=os.fstat(fd)
 finally: os.close(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise RuntimeError('reserved log identity rejected')
 return (s.st_dev,s.st_ino)
def append_bytes(path,identity,payload):
 deadline=time.monotonic()+2.0
 while True:
  try: fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC|os.O_NOFOLLOW)
  except OSError as exc:
   if exc.errno in (errno.EACCES,errno.EBUSY,errno.ETXTBSY,errno.EPERM) and time.monotonic()<deadline: time.sleep(0.01);continue
   raise
  try:
   before=os.fstat(fd);linked=os.lstat(path)
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or (before.st_dev,before.st_ino)!=identity or (linked.st_dev,linked.st_ino)!=identity: raise RuntimeError('append log identity rejected')
   offset=0
   while offset<len(payload):
    written=os.write(fd,payload[offset:])
    if written<=0: raise RuntimeError('append log short write')
    offset+=written
   os.fsync(fd);after=os.fstat(fd);linked_after=os.lstat(path)
   if not stat.S_ISREG(after.st_mode) or after.st_nlink!=1 or (after.st_dev,after.st_ino)!=identity or (linked_after.st_dev,linked_after.st_ino)!=identity: raise RuntimeError('append log identity drift')
   return
  finally: os.close(fd)
def publish_error(payload): append_bytes(error_path,error_identity,payload.encode())
log_identity=reserve(log_path);error_identity=reserve(error_path)
def emit(row): append_bytes(log_path,log_identity,(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode())
def nsid(path,stat_fn=os.stat):
 s=stat_fn(path);return [s.st_dev,s.st_ino]
def basic_rows():
 out={}
 for name in os.listdir('/proc'):
  if not name.isdigit(): continue
  pid=int(name);base='/proc/'+name
  try:
   raw=open(base+'/stat','rb').read();right=raw.rfind(b')');left=raw.find(b'(')
   if left<0 or right<=left: raise RuntimeError('proc stat shape rejected')
   rest=raw[right+2:].split();ppid=int(rest[1]);pgrp=int(rest[2]);session=int(rest[3]);starttime=int(rest[19]);comm=raw[left+1:right].decode('utf-8','backslashreplace')
   status=open(base+'/status','rt',encoding='utf-8').read().splitlines();uid_rows=[x for x in status if x.startswith('Uid:')]
   if len(uid_rows)!=1: raise RuntimeError('proc uid shape rejected')
   uid=int(uid_rows[0].split()[1]);cmd=open(base+'/cmdline','rb').read().split(b'\0');argv=[x.decode('utf-8','surrogateescape') for x in cmd if x]
   try:exe=nsid(base+'/exe')
   except (FileNotFoundError,PermissionError):exe=None
   out[pid]={'pid':pid,'ppid':ppid,'pgrp':pgrp,'session':session,'starttime':starttime,'uid':uid,'comm':comm,'argv':argv,'mnt_ns':None,'pid_ns':None,'namespace_state':'UNRESOLVED','exe':exe}
  except FileNotFoundError: continue
  except ProcessLookupError: continue
 return out
def monitor_ancestry(table,mine):
 allowed=set();cursor=mine
 while cursor:
  if cursor in allowed: raise RuntimeError('monitor ancestry cycle')
  allowed.add(cursor);row=table.get(cursor)
  if row is None: raise RuntimeError('monitor ancestry incomplete')
  cursor=row['ppid']
 return allowed
def minimal_infrastructure(row,table):
 if row['uid']!=0:return False
 argv=row['argv'];parent=table.get(row['ppid'])
 def exact_init(candidate):return candidate is not None and candidate['pid']==1 and candidate['ppid']==0 and candidate['pgrp']==0 and candidate['session']==0 and candidate['uid']==0 and candidate['comm']=='init(Ubuntu)' and candidate['argv']==['/init'] and candidate['exe'] is None
 if exact_init(row):return True
 if row['comm']=='init' and row['pgrp']==0 and row['session']==0 and row['exe'] is None and exact_init(parent) and len(argv)==10 and argv[0]=='plan9' and argv[1]=='--control-socket' and argv[2].isdigit() and argv[3]=='--log-level' and argv[4].isdigit() and argv[5]=='--server-fd' and argv[6].isdigit() and argv[7]=='--pipe-fd' and argv[8].isdigit() and argv[9]=='--log-truncate':return True
 if row['comm']=='SessionLeader' and row['pgrp']==row['pid'] and row['session']==row['pid'] and row['exe'] is None and argv==['/init'] and exact_init(parent):return True
 relay=re.fullmatch(r'Relay\(([0-9]+)\)',row['comm']);grand=table.get(parent['ppid']) if parent is not None else None;child=table.get(int(relay.group(1))) if relay is not None else None
 if relay is not None and parent is not None and row['pgrp']==parent['pid'] and row['session']==parent['pid'] and row['exe'] is None and argv==['/init'] and parent['uid']==0 and parent['comm']=='SessionLeader' and parent['argv']==['/init'] and parent['pgrp']==parent['pid'] and parent['session']==parent['pid'] and parent['exe'] is None and exact_init(grand) and child is not None and child['ppid']==row['pid']:return True
 return False
def infrastructure_ident(row,table):
 identity=[row[name] for name in ('pid','ppid','pgrp','session','starttime','uid','comm')]+[row['argv'],row['exe']]
 parent=table.get(row['ppid'])
 if parent is not None:identity.append([parent['pid'],parent['ppid'],parent['pgrp'],parent['session'],parent['starttime'],parent['uid'],parent['comm'],parent['argv'],parent['exe']])
 relay=re.fullmatch(r'Relay\(([0-9]+)\)',row['comm'])
 if relay is not None:
  child=table.get(int(relay.group(1)))
  if child is None:raise RuntimeError('relay child identity missing')
  identity.append([child['pid'],child['ppid'],child['pgrp'],child['session'],child['starttime'],child['uid'],child['comm'],child['argv'],child['exe']])
 return identity
def freeze_infrastructure(row,table,infra_freeze):
 identity=infrastructure_ident(row,table);prior=infra_freeze.get(row['pid'])
 if prior is not None and prior!=identity:raise RuntimeError('pre-admitted infrastructure PID identity drift: '+str(row['pid']))
 if prior is None:infra_freeze[row['pid']]=identity
def resolve_namespace_pair(row,stat_fn=os.stat):
 base='/proc/'+str(row['pid'])+'/ns/'
 try:mnt=nsid(base+'mnt',stat_fn);pidns=nsid(base+'pid',stat_fn)
 except (FileNotFoundError,ProcessLookupError):return 'VANISHED'
 except PermissionError:raise
 if len(mnt)!=2 or len(pidns)!=2:raise RuntimeError('namespace identity shape rejected')
 row['mnt_ns']=mnt;row['pid_ns']=pidns;row['namespace_state']='EXACT';return 'EXACT'
def mark_namespace_states(table,mine,stat_fn=os.stat,infra_freeze=None):
 if infra_freeze is None:infra_freeze={}
 ancestry=monitor_ancestry(table,mine);vanished=[]
 for row in table.values():
  if row['pid'] in infra_freeze:freeze_infrastructure(row,table,infra_freeze)
  if row['pid']==mine:row['namespace_state']='NOT_REQUIRED_MONITOR_ANCESTRY'
  elif row['pid']==watcher_pid:row['namespace_state']='NOT_REQUIRED_WATCHER_IDENTITY'
  else:
   try:state=resolve_namespace_pair(row,stat_fn)
   except PermissionError as exc:
    if minimal_infrastructure(row,table):
     freeze_infrastructure(row,table,infra_freeze)
     row['namespace_state']='NOT_REQUIRED_TRUSTED_INFRASTRUCTURE'
    else:raise RuntimeError('namespace identity permission denied for relevant process: pid='+str(row['pid'])+' comm='+row['comm']+' path='+str(exc.filename)) from exc
   else:
    if state=='VANISHED':vanished.append(row['pid'])
    elif minimal_infrastructure(row,table):freeze_infrastructure(row,table,infra_freeze)
 for pid in vanished:table.pop(pid,None)
 return table
def require_exact_namespace(row,context):
 if row['namespace_state']!='EXACT' or row['mnt_ns'] is None or row['pid_ns'] is None:raise RuntimeError(context+' exact namespace identity required')
 return [row['mnt_ns'],row['pid_ns']]
infrastructure_admitted={}
def rows():return mark_namespace_states(basic_rows(),os.getpid(),os.stat,infrastructure_admitted)
seen=False;sequence=0;anchor_ns=None;anchor_start=None;anchor_uid=None;admitted={};last_monotonic_ns=None;maximum_observed_gap_ns=0;max_canonical_processes=0
def ident(row):
 require_exact_namespace(row,'admitted identity');return [row['pid'],row['starttime'],row['mnt_ns'],row['pid_ns'],row['exe']]
def descends(pid,anchor,table):
 visited=set()
 while pid and pid not in visited:
  if pid==anchor:return True
  visited.add(pid);row=table.get(pid)
  if row is None:return False
  pid=row['ppid']
 return False
def sample():
 global seen,sequence,anchor_ns,anchor_start,anchor_uid,last_monotonic_ns,maximum_observed_gap_ns,max_canonical_processes
 now=time.monotonic_ns();gap=0 if last_monotonic_ns is None else now-last_monotonic_ns
 if last_monotonic_ns is not None and (gap<=0 or gap>max_gap_ns): raise RuntimeError('resource monitor cadence gap rejected: '+str(gap))
 last_monotonic_ns=now;maximum_observed_gap_ns=max(maximum_observed_gap_ns,gap)
 table=rows();mine=os.getpid()
 if mine not in table or watcher_pid not in table: raise RuntimeError('monitor or watcher process identity disappeared')
 allowed=monitor_ancestry(table,mine);allowed.add(watcher_pid)
 timeout_rows=[r for r in table.values() if r['argv']==timeout_argv];bwrap_rows=[r for r in table.values() if r['argv']==bwrap_argv];test_rows=[r for r in table.values() if r['argv']==test_argv]
 if len(timeout_rows)>1 or len(bwrap_rows)>1 or len(test_rows)>1: raise RuntimeError('duplicate canonical process chain rejected')
 for label,selected in (('timeout',timeout_rows),('bwrap',bwrap_rows),('test',test_rows)):
  if selected:require_exact_namespace(selected[0],'canonical '+label)
 if bwrap_rows and (not timeout_rows or bwrap_rows[0]['ppid']!=timeout_rows[0]['pid']): raise RuntimeError('canonical bwrap ancestry rejected')
 if timeout_rows: allowed.add(timeout_rows[0]['pid']);seen=True
 if test_rows:
  parents={timeout_rows[0]['pid']} if timeout_rows else set()
  if bwrap_rows: parents.add(bwrap_rows[0]['pid'])
  if not parents or test_rows[0]['ppid'] not in parents: raise RuntimeError('canonical test ancestry rejected')
  test=test_rows[0];launch_ns=require_exact_namespace(test,'canonical test')
  if anchor_ns is None:anchor_ns=launch_ns;anchor_start=test['starttime'];anchor_uid=test['uid']
  elif anchor_ns!=launch_ns or anchor_start!=test['starttime'] or anchor_uid!=test['uid']:raise RuntimeError('canonical launch identity drift')
  allowed.add(test['pid']);seen=True
 if bwrap_rows:allowed.add(bwrap_rows[0]['pid']);seen=True
 scoped=[]
 if anchor_ns is not None:
  for row in table.values():
   if row['namespace_state']=='EXACT' and [row['mnt_ns'],row['pid_ns']]==anchor_ns and row['uid']==anchor_uid and row['starttime']>=anchor_start:
    identity=ident(row);prior=admitted.get(row['pid'])
    if prior is not None and prior['identity']!=identity:raise RuntimeError('canonical descendant PID identity drift')
    test_pid=test_rows[0]['pid'] if test_rows else -1
    if prior is not None:binding='previously_frozen_descendant_identity'
    elif row['pid']==test_pid:binding='exact_test'
    elif test_pid>0 and descends(row['pid'],test_pid,table):binding='live_ancestry_plus_launch_identity'
    else:continue
    if prior is None:admitted[row['pid']]={'pid':row['pid'],'identity':identity,'first_ppid':row['ppid'],'first_sequence':sequence+1,'binding':binding}
    allowed.add(row['pid']);scoped.append(row)
 max_canonical_processes=max(max_canonical_processes,len(scoped))
 unknown=[]
 for row in table.values():
  if row['pid'] in allowed: continue
  if minimal_infrastructure(row,table): continue
  unknown.append({'pid':row['pid'],'ppid':row['ppid'],'uid':row['uid'],'comm':row['comm'],'argv':row['argv'],'namespace_state':row['namespace_state']})
 if unknown: raise RuntimeError('unknown concurrent WSL workload rejected: '+json.dumps(unknown,sort_keys=True,separators=(',',':')))
 mem_rows=[x for x in open('/proc/meminfo','rt',encoding='ascii').read().splitlines() if x.startswith('MemAvailable:')]
 if len(mem_rows)!=1: raise RuntimeError('MemAvailable shape rejected')
 parts=mem_rows[0].split();mem=int(parts[1])
 if len(parts)!=3 or parts[2]!='kB' or mem<minimum: raise RuntimeError('continuous MemAvailable floor rejected')
 states={name:sum(1 for row in table.values() if row['namespace_state']==name) for name in ('EXACT','NOT_REQUIRED_TRUSTED_INFRASTRUCTURE','NOT_REQUIRED_MONITOR_ANCESTRY','NOT_REQUIRED_WATCHER_IDENTITY')}
 if sum(states.values())!=len(table):raise RuntimeError('namespace state accounting rejected')
 infra_rows=[{'pid':pid,'identity':identity} for pid,identity in sorted(infrastructure_admitted.items())];infra_raw=json.dumps(infra_rows,sort_keys=True,separators=(',',':')).encode()
 sequence+=1;return {'kind':'SAMPLE','sequence':sequence,'monotonic_ns':now,'gap_ns':gap,'memavailable_kib':mem,'process_rows':len(table),'canonical_present':bool(timeout_rows or bwrap_rows or scoped),'canonical_processes':len(scoped),'admitted_descendant_identities':len(admitted),'launch_namespace_bound':anchor_ns is not None,'namespace_exact_rows':states['EXACT'],'namespace_not_required_infrastructure_rows':states['NOT_REQUIRED_TRUSTED_INFRASTRUCTURE'],'namespace_not_required_ancestry_rows':states['NOT_REQUIRED_MONITOR_ANCESTRY'],'namespace_not_required_watcher_rows':states['NOT_REQUIRED_WATCHER_IDENTITY'],'namespace_permission_denials':0,'admitted_infrastructure_identities':len(infra_rows),'admitted_infrastructure_sha256':hashlib.sha256(infra_raw).hexdigest()}
try:
 first=sample();emit({'kind':'READY','pid':os.getpid(),'watcher_pid':watcher_pid,'minimum_kib':minimum,'sequence':first['sequence'],'target_interval_ms':target_ns//1000000,'maximum_gap_ms':max_gap_ns//1000000,'cadence_claim':'bounded_maximum_gap_not_exact_interval','descendant_policy':'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace','pinned_subprocess_sites':subprocess_sites,'canonical_token_sha256':canonical_token_sha256,'readiness_self_test':readiness_self_test});emit(first)
 if readiness_self_test:
  infra_rows=[{'pid':pid,'identity':identity} for pid,identity in sorted(infrastructure_admitted.items())];infra_raw=json.dumps(infra_rows,sort_keys=True,separators=(',',':')).encode()
  emit({'kind':'SELFTEST_DONE','samples':sequence,'canonical_seen':False,'readiness_self_test':True,'canonical_token_sha256':canonical_token_sha256,'process_rows':first['process_rows'],'namespace_exact_rows':first['namespace_exact_rows'],'namespace_not_required_infrastructure_rows':first['namespace_not_required_infrastructure_rows'],'namespace_not_required_ancestry_rows':first['namespace_not_required_ancestry_rows'],'namespace_not_required_watcher_rows':first['namespace_not_required_watcher_rows'],'namespace_permission_denials':0,'admitted_infrastructure_identities':len(infra_rows),'admitted_infrastructure_json':infra_raw.decode(),'admitted_infrastructure_sha256':hashlib.sha256(infra_raw).hexdigest()})
 else:
  next_tick=time.monotonic_ns()+target_ns
  while not os.path.exists(stop):
   delay=next_tick-time.monotonic_ns()
   if delay>0:time.sleep(delay/1000000000)
   emit(sample());next_tick+=target_ns
  final=sample();emit(final)
  if not seen: raise RuntimeError('canonical process chain was never observed')
  admitted_rows=sorted(admitted.values(),key=lambda x:(x['pid'],x['identity'][1]));admitted_raw=json.dumps(admitted_rows,sort_keys=True,separators=(',',':')).encode()
  infra_rows=[{'pid':pid,'identity':identity} for pid,identity in sorted(infrastructure_admitted.items())];infra_raw=json.dumps(infra_rows,sort_keys=True,separators=(',',':')).encode()
  emit({'kind':'DONE','samples':sequence,'canonical_seen':seen,'minimum_kib':minimum,'target_interval_ms':target_ns//1000000,'maximum_gap_ms':max_gap_ns//1000000,'maximum_observed_gap_ns':maximum_observed_gap_ns,'admitted_descendant_identities':len(admitted),'admitted_identity_rows':admitted_rows,'admitted_identities_sha256':hashlib.sha256(admitted_raw).hexdigest(),'admitted_infrastructure_identities':len(infra_rows),'admitted_infrastructure_json':infra_raw.decode(),'admitted_infrastructure_sha256':hashlib.sha256(infra_raw).hexdigest(),'max_canonical_processes':max_canonical_processes,'launch_namespace_bound':anchor_ns is not None,'pinned_subprocess_sites':subprocess_sites,'canonical_token_sha256':canonical_token_sha256,'readiness_self_test':False})
except BaseException:
 publish_error(traceback.format_exc());raise
'@
"""


RESOURCE_SELFTEST_PEER_BLOCK = r"""$resourceSelfTestPeerSource = @'
import json,os,sys,time
c=json.loads(__import__('base64').b64decode(sys.argv[1]));ready=c['ready'];stop=c['stop'];fd=os.open(ready,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
try:
 payload=(json.dumps({'pid':os.getpid(),'kind':'READY'},sort_keys=True,separators=(',',':'))+'\n').encode();offset=0
 while offset<len(payload):offset+=os.write(fd,payload[offset:])
 os.fsync(fd)
finally:os.close(fd)
while not os.path.exists(stop):time.sleep(0.01)
'@
"""


RETAINED_V32_FUNCTIONS = r"""function Invoke-RetainedV32SnapshotVerifier([string]$Phase){
    $cfg=[ordered]@{root=$v32SnapshotRoot;expected=$v32StagingInventoryWsl;expected_size=847403;expected_sha256='0fd29582a2159cd58595b458b7832e478d64735b0ea4a594a3e9cda6d1adf4a3';phase=$Phase};$result=Invoke-BoundedSafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $cfg)) $retainedV30SnapshotVerifierSource "retained v32 snapshot $Phase" 180
    $lines=@($result.stdout.Trim()-split"`r?`n"|Where-Object{$_});if($lines.Count-ne1-or$result.stderr.Length-ne0){throw "Retained v32 snapshot verifier output rejected: $Phase"};$row=$lines[0]|ConvertFrom-Json
    if($row.schema-cne'planora.muni-v33.retained-snapshot-replay.v1'-or$row.status-cne'EXACT_RETAINED_SNAPSHOT_REPLAY'-or$row.phase-cne$Phase-or$row.root-cne$v32SnapshotRoot-or$row.files-ne3146-or$row.directories-ne368-or$row.bytes-ne190900047-or$row.inventory_sha256-cne'0fd29582a2159cd58595b458b7832e478d64735b0ea4a594a3e9cda6d1adf4a3'-or-not[bool]$row.all_nlink_one){throw "Retained v32 snapshot replay semantics rejected: $Phase"};return $row
}
function Get-NonThrowingRetainedV32SnapshotReplay([string]$Phase){try{return [ordered]@{phase=$Phase;status='REPLAYED';evidence=(Invoke-RetainedV32SnapshotVerifier $Phase);errors=@()}}catch{return [ordered]@{phase=$Phase;status='REPLAY_ERRORS_RECORDED';evidence=$null;errors=@($_.Exception.Message)}}}

"""


PASS_ABSENCE_FUNCTION = r"""function Assert-V28V29V30V31V32PassEvidenceAbsent([string]$Phase){
    $result=[ordered]@{phase=$Phase;v28_receipt_absent=(-not(Test-Path -LiteralPath $v28ReceiptPath));v28_seal_absent=(-not(Test-Path -LiteralPath $v28PassSealPath));v29_receipt_absent=(-not(Test-Path -LiteralPath $v29ReceiptPath));v29_seal_absent=(-not(Test-Path -LiteralPath $v29PassSealPath));v30_receipt_absent=(-not(Test-Path -LiteralPath $v30ReceiptPath));v30_seal_absent=(-not(Test-Path -LiteralPath $v30PassSealPath));v31_receipt_absent=(-not(Test-Path -LiteralPath $v31ReceiptPath));v31_seal_absent=(-not(Test-Path -LiteralPath $v31PassSealPath));v32_receipt_absent=(-not(Test-Path -LiteralPath $v32ReceiptPath));v32_seal_absent=(-not(Test-Path -LiteralPath $v32PassSealPath));observed_at_utc=[DateTime]::UtcNow.ToString('o')}
    if(-not$result.v28_receipt_absent-or-not$result.v28_seal_absent-or-not$result.v29_receipt_absent-or-not$result.v29_seal_absent-or-not$result.v30_receipt_absent-or-not$result.v30_seal_absent-or-not$result.v31_receipt_absent-or-not$result.v31_seal_absent-or-not$result.v32_receipt_absent-or-not$result.v32_seal_absent){throw "v28/v29/v30/v31/v32 PASS evidence unexpectedly exists: $Phase"};return $result
}
"""


V32_FAILURE_AND_COMPLETE_FUNCTIONS = r"""function Get-ValidatedV32FailureEvidence{
    $c=$v32FailureContractJson|ConvertFrom-Json;$pins=@()
    foreach($group in @($c.sources,$c.launch_provenance,$c.artifacts)){foreach($property in $group.PSObject.Properties){[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value}}
    if($pins.Count-ne28-or@($pins.path|Sort-Object -Unique).Count-ne28){throw 'v32 direct/provenance/artifact pin cardinality rejected'}
    $expected=@($c.artifacts.PSObject.Properties|ForEach-Object{[IO.Path]::GetFullPath((Join-Path $repo $_.Value.path.Replace('/','\')))}|Sort-Object);$leaf=(Split-Path -Leaf $v32Prefix)+'.';$entries=@(Get-ChildItem -LiteralPath (Split-Path -Parent $v32Prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if(@($entries|Where-Object{$_.PSIsContainer}).Count-ne0){throw 'v32 artifact directory rejected'};$observed=@($entries|ForEach-Object{$_.FullName}|Sort-Object);if($entries.Count-ne20-or(ConvertTo-JsonTokenStream ($observed|ConvertTo-Json -Compress))-cne(ConvertTo-JsonTokenStream ($expected|ConvertTo-Json -Compress))){throw 'v32 exact artifact inventory rejected'}
    foreach($suffix in $c.expected_absent_suffixes){if(Test-Path -LiteralPath ($v32Prefix+'.'+$suffix)){throw "Unexpected v32 artifact exists: $suffix"}}
    $claim=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.claim.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$release=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.heavy_lock_release.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$lock=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.heavy_lock.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$authorization=[IO.File]::ReadAllText((Join-Path $repo $c.sources.authorization.path.Replace('/','\')),$utf8)|ConvertFrom-Json
    $rejectionRaw=[IO.File]::ReadAllText($v32RejectionPath,$utf8);$rejection=$rejectionRaw|ConvertFrom-Json;$custodyRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.predecessor_custody.path.Replace('/','\')),$utf8);$custody=$custodyRaw|ConvertFrom-Json;$stageRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.staging_inventory.path.Replace('/','\')),$utf8);$preRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.pre_inventory.path.Replace('/','\')),$utf8);$stage=$stageRaw|ConvertFrom-Json
    if($claim.schema-cne'planora.muni-v32.atomic-run-claim.v2'-or$claim.run_id-cne$c.run_id-or$claim.authorization-cne$c.sources.authorization.path-or$claim.status-cne'CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS'-or-not[bool]$claim.irreversible-or-not[bool]$claim.failure_consumes_authorization-or$claim.default_outcome_on_any_unsealed_failure-cne'REJECTED_AUTHORIZATION_CONSUMED'){throw 'v32 claim semantics rejected'}
    if($rejection.schema-cne'planora.muni-v32.overall-rejection.v6'-or$rejection.run_id-cne$c.run_id-or$rejection.status-cne$c.failure.status-or$rejection.failure-cne$c.failure.message-or-not[bool]$rejection.claim_publication_complete-or$rejection.claim_publication_phase-cne'durably_published'-or$rejection.claim_sha256-cne$c.artifacts.claim.sha256-or$rejection.claim_size-ne$c.artifacts.claim.size-or[bool]$rejection.pass_receipt_present-or-not[bool]$rejection.pass_shutdown_seal_absent-or$rejection.acceptance_commitment_sha256-cne''-or-not[bool]$rejection.snapshot_retained_for_forensics-or$rejection.snapshot_root-cne$c.snapshot.root-or$rejection.predecessor_custody_sha256-cne$c.artifacts.predecessor_custody.sha256){throw 'v32 rejection semantics rejected'}
    if(-not[bool]$rejection.lifecycle.staging_exited-or-not[bool]$rejection.lifecycle.watcher_ready-or-not[bool]$rejection.lifecycle.preinventory_started-or-not[bool]$rejection.lifecycle.resource_launch_attempted-or[bool]$rejection.lifecycle.canonical_launch_attempted-or[bool]$rejection.lifecycle.canonical_started-or[bool]$rejection.lifecycle.canonical_exited-or-not[bool]$rejection.lifecycle.retained_v30_initial_custody_published-or-not[bool]$rejection.lifecycle.retained_v31_initial_custody_published-or[bool]$rejection.lifecycle.retained_v30_post_cleanup_custody_published-or[bool]$rejection.lifecycle.retained_v31_post_cleanup_custody_published){throw 'v32 failure lifecycle rejected'}
    if($release.run_id-cne$c.run_id-or$release.decision-cne'REJECTED'-or-not[bool]$release.same_handle_verified-or-not[bool]$release.delete_on_close-or-not[bool]$release.lock_path_absent-or$release.lock_sha256-cne$lock.lock_sha256-or$release.acceptance_commitment_sha256-cne''-or$release.cleanup_sha256-cne''){throw 'v32 lock release rejected'}
    if($custody.schema-cne'planora.muni-v32.predecessor-custody.v1'-or$custody.status-cne$c.predecessor_custody_status-or$custody.run_id-cne$c.run_id-or-not[bool]$custody.shared_lock_absent-or$custody.predecessor_evidence_sha256-cne$c.initial_predecessor_evidence_sha256-or$custody.v31_failure_evidence_sha256-cne$c.initial_v31_failure_evidence_sha256){throw 'v32 predecessor custody semantics rejected'}
    if($lock.lock.schema-cne'planora.shared-heavy-wsl-lock.v2'-or$lock.lock.run_id-cne$c.run_id-or$lock.lock.authorization_sha256-cne$c.sources.authorization.sha256-or$lock.lock.runner_sha256-cne$c.sources.runner.sha256-or$lock.lock.predecessor_custody_sha256-cne$c.artifacts.predecessor_custody.sha256-or-not[bool]$lock.held_open-or-not[bool]$lock.same_handle_verified-or-not[bool]$lock.delete_on_close-or$lock.predecessor_custody_sha256-cne$c.artifacts.predecessor_custody.sha256-or$lock.retained_v30_snapshot_custody_sha256-cne$c.artifacts.retained_v30_snapshot_custody.sha256-or$lock.retained_v31_snapshot_custody_sha256-cne$c.artifacts.retained_v31_snapshot_custody.sha256-or$lock.predecessor_evidence_sha256-cne$c.initial_predecessor_evidence_sha256){throw 'v32 heavy lock semantics rejected'}
    if($authorization.schema-cne'planora.itc2019.canonical-test-authorization.v12'-or$authorization.test_id-cne$c.run_id-or$authorization.candidate-cne'muni_v32'-or[bool]$authorization.automatic_retry_authorized-or$authorization.runner.sha256-cne$c.sources.runner.sha256-or$authorization.successor_admission.builder.sha256-cne$c.sources.builder.sha256-or$authorization.successor_admission.tests.sha256-cne$c.sources.tests.sha256){throw 'v32 authorization rejected'}
    $initialHash=Get-RawJsonObjectPropertyTokenHash $custodyRaw 'predecessor_evidence';$postHash=Get-RawJsonObjectPropertyTokenHash $rejectionRaw 'predecessor_evidence';$initialV31Hash=Get-RawJsonObjectPropertyTokenHash $custodyRaw 'v31_failure_evidence';$postV31Hash=Get-RawJsonObjectPropertyTokenHash $rejectionRaw 'v31_failure_evidence'
    if($initialHash-cne$c.initial_predecessor_evidence_sha256-or$postHash-cne$c.post_rejection_predecessor_evidence_sha256-or$initialV31Hash-cne$c.initial_v31_failure_evidence_sha256-or$postV31Hash-cne$c.post_rejection_v31_failure_evidence_sha256-or$rejection.predecessor_evidence_sha256-cne$c.post_rejection_predecessor_evidence_sha256-or$rejection.v31_failure_evidence_sha256-cne$c.post_rejection_v31_failure_evidence_sha256-or$rejection.predecessor_rejection_replay.status-cne'REPLAYED'-or$rejection.predecessor_rejection_replay.validated_pin_count-ne61-or@($rejection.predecessor_rejection_replay.errors).Count-ne0){throw 'v32 carried predecessor evidence rejected'}
    $priorPins=@($rejection.predecessor_evidence.runtime.validated_pins);$initialPins=@($custody.predecessor_evidence.runtime.validated_pins);if($priorPins.Count-ne61-or@($priorPins.path|Sort-Object -Unique).Count-ne61-or(ConvertTo-JsonTokenStream ($priorPins|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($initialPins|ConvertTo-Json -Depth 8 -Compress))){throw 'v32 carried pin cardinality or continuity rejected'}
    if($stage.schema-cne'planora.muni-v32.snapshot-inventory.v1'-or$stage.root-cne$c.snapshot.root-or$stage.file_count-ne$c.snapshot.files-or$stage.directory_count-ne$c.snapshot.directories-or$stage.total_bytes-ne$c.snapshot.bytes-or(ConvertTo-JsonTokenStream $stageRaw)-cne(ConvertTo-JsonTokenStream $preRaw)){throw 'v32 retained inventory semantics rejected'}
    $resourceError=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.resource_error.path.Replace('/','\')),$utf8);$resourceWrapper=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.resource_wrapper_stderr.path.Replace('/','\')),$utf8);if($resourceError-cnotmatch"PermissionError: \[Errno 13\] Permission denied: '/proc/1/ns/mnt'"-or$resourceWrapper-cnotmatch"PermissionError: \[Errno 13\] Permission denied: '/proc/1/ns/mnt'"-or(Get-Item -LiteralPath (Join-Path $repo $c.artifacts.resource_log.path.Replace('/','\'))).Length-ne0-or(Get-Item -LiteralPath (Join-Path $repo $c.artifacts.resource_wrapper_stdout.path.Replace('/','\'))).Length-ne0){throw 'v32 resource monitor failure evidence rejected'}
    $watchRaw=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_log.path.Replace('/','\')),$utf8);$watchRows=@($watchRaw.TrimEnd("`n").Split("`n")|ForEach-Object{$_|ConvertFrom-Json});if($watchRows.Count-ne203-or$watchRows[0].kind-cne'ARMED'-or$watchRows[-1].kind-cne'READY'-or@($watchRows|Where-Object{$_.kind-ceq'STAGING_EVENT'}).Count-ne201-or$watchRows[-1].root-cne$c.snapshot.root-or-not[bool]$watchRows[-1].watch_started_before_staging-or-not[bool]$watchRows[-1].parent_watch_active-or$watchRows[-1].file_count-ne$c.snapshot.files-or$watchRows[-1].inventory_sha256-cne$c.artifacts.staging_inventory.sha256-or$watchRows[-1].parent_watch_loss_events-ne0){throw 'v32 watcher failure-phase evidence rejected'}
    $watchError=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_error.path.Replace('/','\')),$utf8);$watchWrapper=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_wrapper_stderr.path.Replace('/','\')),$utf8);$watchStop=[IO.File]::ReadAllText((Join-Path $repo $c.artifacts.watch_stop.path.Replace('/','\')),$utf8)|ConvertFrom-Json;if($watchError-cnotmatch'watcher stopped before cleanup authorization'-or$watchWrapper-cnotmatch'watcher stopped before cleanup authorization'-or$watchStop.schema-cne'planora.muni-v32.watcher-abort-control.v1'-or$watchStop.run_id-cne$c.run_id){throw 'v32 watcher terminal evidence rejected'}
    foreach($name in @('retained_v30_snapshot_rejection_replay','retained_v31_snapshot_rejection_replay')){$replay=$rejection.$name;if($replay.status-cne'REPLAYED'-or@($replay.errors).Count-ne0-or$replay.evidence.status-cne'EXACT_RETAINED_SNAPSHOT_REPLAY'){throw "v32 rejection retained snapshot replay rejected: $name"}}
    $review=[IO.File]::ReadAllText((Join-Path $repo $c.launch_provenance.independent_review.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$gateReview=[IO.File]::ReadAllText((Join-Path $repo $c.launch_provenance.terminal_gate_review.path.Replace('/','\')),$utf8)|ConvertFrom-Json;if($review.status-cne'GO'-or$review.run_id-cne$c.run_id-or@($review.blockers).Count-ne0-or[bool]$review.review_scope.default_runner_execution_performed-or$gateReview.status-cne'GO'-or$gateReview.run_id-cne$c.run_id-or@($gateReview.blockers).Count-ne0){throw 'v32 independent review provenance rejected'}
    $gateSource=[IO.File]::ReadAllText((Join-Path $repo $c.launch_provenance.terminal_gate.path.Replace('/','\')),$utf8);if(([regex]::Matches($gateSource,'(?m)^    & \$runner$')).Count-ne1-or$gateSource-cnotmatch'defaultInvocationCount = 1'-or$gateSource-cmatch'(?i)automatic.retry'){throw 'v32 terminal gate provenance rejected'}
    $v32RunnerSource=[IO.File]::ReadAllText((Join-Path $repo $c.sources.runner.path.Replace('/','\')),$utf8);if($v32RunnerSource-cnotmatch"'mnt_ns':nsid\(base\+'/ns/mnt'\),'pid_ns':nsid\(base\+'/ns/pid'\)"-or$resourceError-cnotmatch'File "<stdin>", line 33, in nsid'){throw 'v32 namespace root-cause source witness rejected'}
    return [ordered]@{schema='planora.muni-v33.validated-v32-failure-evidence.v1';status='VALIDATED_EXACT_V32_FAILURE_AND_LAUNCH_PROVENANCE';contract=$c;runtime=[ordered]@{validated_pins=$pins;carried_predecessor_pins=$priorPins;artifact_count=$entries.Count;pass_absence=(Assert-V28V29V30V31V32PassEvidenceAbsent 'v32_failure_validation');shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));retained_snapshot_replay_required=$true};claim=$claim;rejection=[ordered]@{status=$rejection.status;failure=$rejection.failure;lifecycle=$rejection.lifecycle;predecessor_evidence_sha256=$rejection.predecessor_evidence_sha256};snapshot_inventory=$stage}
}
function New-ExpectedThroughV31PredecessorEvidence{
    $base=New-ExpectedCombinedPredecessorEvidence;$c=$v31FailureContractJson|ConvertFrom-Json;$base.status='EXPECTED_UNVALIDATED_V28_V29_V30_V31_PREDECESSOR_CUSTODY';$base['v31_failure_evidence']=[ordered]@{schema='planora.muni-v33.expected-v31-failure-evidence.v1';status='EXPECTED_UNVALIDATED_EXACT_V31_FAILURE_AND_LAUNCH_PROVENANCE';contract=$c;runtime=[ordered]@{expected_direct_and_provenance_pins=20;expected_carried_pins=41}};$base.runtime.expected_pin_count=61;return $base
}
function Get-ValidatedThroughV31PredecessorEvidence([bool]$RequireSharedLockAbsent){
    $base=Get-ValidatedCombinedPredecessorEvidence $RequireSharedLockAbsent;$v31=Get-ValidatedV31FailureEvidence;$basePins=@($base.runtime.validated_pins);$carried=@($v31.runtime.carried_predecessor_pins);if((ConvertTo-JsonTokenStream ($basePins|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($carried|ConvertTo-Json -Depth 8 -Compress))){throw 'v31 carried/base predecessor pins differ'};$all=@($basePins)+@($v31.runtime.validated_pins);if($all.Count-ne61-or@($all.path|Sort-Object -Unique).Count-ne61){throw 'through-v31 predecessor pin cardinality rejected'};$base.status='VALIDATED_EXACT_V28_V29_V30_V31_PREDECESSOR_CUSTODY';$base['v31_failure_evidence']=$v31;$base.runtime.validated_pins=$all;$base.runtime.pass_absence=Assert-V28V29V30V31V32PassEvidenceAbsent 'through_v31_predecessor_validation';return $base
}
function New-ExpectedCompletePredecessorEvidence{
    $base=New-ExpectedThroughV31PredecessorEvidence;$c=$v32FailureContractJson|ConvertFrom-Json;$base.status='EXPECTED_UNVALIDATED_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY';$base['v32_failure_evidence']=[ordered]@{schema='planora.muni-v33.expected-v32-failure-evidence.v1';status='EXPECTED_UNVALIDATED_EXACT_V32_FAILURE_AND_LAUNCH_PROVENANCE';contract=$c;runtime=[ordered]@{expected_direct_source_provenance_artifact_pins=28;expected_carried_pins=61}};$base.runtime.expected_pin_count=89;return $base
}
function Resolve-CompletePredecessorRejectionEvidence([object]$Current,[object]$Replay){
    $e=$Current;$phase=$(if($null-ne$Replay.phase){[string]$Replay.phase}else{'rejection_publication'});$priorStatus=$(if($null-ne$Current){[string]$Current.status}else{'MISSING'});$errors=@($Replay.errors);$r=$null
    if($Replay.status-ceq'REPLAYED'-and$null-ne$Replay.evidence){$candidate=$Replay.evidence;if($candidate.status-ceq'VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'-and@($candidate.runtime.validated_pins).Count-eq89){$e=$candidate;$r=[ordered]@{phase=$phase;status='REPLAYED';prior_evidence_status=$priorStatus;evidence_status=$candidate.status;validated_pin_count=89;errors=@()}}else{$errors+=,'Complete predecessor rejection replay promotion rejected'}}elseif($Replay.status-ceq'REPLAYED'){$errors+=,'Complete predecessor rejection replay evidence missing'}
    if($null-eq$r){if($errors.Count-eq0){$errors+=,"Complete predecessor rejection replay status rejected: $($Replay.status)"};$r=[ordered]@{phase=$phase;status='REPLAY_ERRORS_RECORDED';prior_evidence_status=$priorStatus;errors=$errors}}
    if($null-eq$e-or$null-eq$e.v31_failure_evidence-or$null-eq$e.v32_failure_evidence){$errors=@($r.errors)+@('Complete predecessor rejection fallback evidence missing');$e=New-ExpectedCompletePredecessorEvidence;$r=[ordered]@{phase=$phase;status='REPLAY_ERRORS_RECORDED';prior_evidence_status=$priorStatus;errors=$errors}}
    $v31Hash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e.v31_failure_evidence|ConvertTo-Json -Depth 70 -Compress));$v32Hash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e.v32_failure_evidence|ConvertTo-Json -Depth 70 -Compress));$e['rejection_replay']=$r;$eHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($e|ConvertTo-Json -Depth 70 -Compress));return [ordered]@{evidence=$e;replay=$r;v31_failure_evidence_sha256=$v31Hash;v32_failure_evidence_sha256=$v32Hash;predecessor_evidence_sha256=$eHash}
}
function Get-ValidatedCompletePredecessorEvidence([bool]$RequireSharedLockAbsent){
    $base=Get-ValidatedThroughV31PredecessorEvidence $RequireSharedLockAbsent;$v32=Get-ValidatedV32FailureEvidence;$basePins=@($base.runtime.validated_pins);$carried=@($v32.runtime.carried_predecessor_pins);if((ConvertTo-JsonTokenStream ($basePins|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($carried|ConvertTo-Json -Depth 8 -Compress))){throw 'v32 carried/through-v31 predecessor pins differ'};$all=@($basePins)+@($v32.runtime.validated_pins);if($all.Count-ne89-or@($all.path|Sort-Object -Unique).Count-ne89){throw 'complete v33 predecessor pin cardinality rejected'};$base.status='VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY';$base['v32_failure_evidence']=$v32;$base.runtime.validated_pins=$all;$base.runtime.pass_absence=Assert-V28V29V30V31V32PassEvidenceAbsent 'complete_predecessor_validation';return $base
}
function Get-CompletePredecessorPinArray([object]$Evidence){if($null-eq$Evidence-or$Evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'){throw 'Complete v33 predecessor evidence is not replay-ready'};return @($Evidence.runtime.validated_pins)}
function Get-NonThrowingCompletePredecessorReplay([object]$Evidence,[object]$ArchivePin){try{return [ordered]@{phase='rejection_publication';status='REPLAYED';evidence=(Get-ValidatedCompletePredecessorEvidence $false);prior_evidence_status=$Evidence.status;errors=@()}}catch{return [ordered]@{phase='rejection_publication';status='REPLAY_ERRORS_RECORDED';evidence=$null;prior_evidence_status=$Evidence.status;errors=@($_.Exception.Message)}}}

"""


RESOURCE_READINESS_SELFTEST = r"""function Clear-ResourceMonitorReadinessSelfTestDirectory([string]$Directory,[string[]]$KnownFiles){
    if(-not(Test-Path -LiteralPath $Directory)){return};$full=[IO.Path]::GetFullPath($Directory);$expectedPrefix=[IO.Path]::GetFullPath((Join-Path $repo 'tmp\muni-v33-resource-readiness-'))
    if(-not$full.StartsWith($expectedPrefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Resource readiness cleanup path rejected'}
    $known=@{};foreach($path in $KnownFiles){$known[[IO.Path]::GetFullPath($path)]=$true};$entries=@(Get-ChildItem -LiteralPath $Directory -Force);foreach($entry in $entries){if($entry.PSIsContainer-or-not$known.ContainsKey([IO.Path]::GetFullPath($entry.FullName))){throw "Unexpected resource readiness self-test entry retained: $($entry.FullName)"}}
    foreach($path in $KnownFiles){if(Test-Path -LiteralPath $path){Remove-Item -LiteralPath $path -Force}};if(@(Get-ChildItem -LiteralPath $Directory -Force).Count-ne0){throw 'Resource readiness self-test directory not empty'};[IO.Directory]::Delete($full,$false)
}
function Invoke-ResourceMonitorReadinessSelfTest{
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock present before resource readiness self-test'};$leaf=(Split-Path -Leaf $prefix)+'.';$before=@(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if($before.Count-ne0-or(Test-Path -LiteralPath $claimFile)){throw 'Fresh v33 evidence namespace rejected before resource readiness self-test'}
    $auth=Get-AuthorizationState;$name='muni-v33-resource-readiness-'+[Guid]::NewGuid().ToString('N');$tmpRoot=Join-Path $repo 'tmp';if(-not(Test-Path -LiteralPath $tmpRoot)){[void](New-Item -ItemType Directory -Path $tmpRoot)};$dir=Join-Path $tmpRoot $name;$dirWsl=$repoWsl+'/tmp/'+$name;[void](New-Item -ItemType Directory -Path $dir)
    $peerReady=Join-Path $dir 'peer.ready.json';$peerStop=Join-Path $dir 'peer.stop';$monitorLog=Join-Path $dir 'resource.jsonl';$monitorError=Join-Path $dir 'resource.error.log';$monitorStop=Join-Path $dir 'resource.stop';$known=@($peerReady,$peerStop,$monitorLog,$monitorError,$monitorStop);$peer=$null;$monitor=$null
    try{
        $peerCfg=[ordered]@{ready=$dirWsl+'/peer.ready.json';stop=$dirWsl+'/peer.stop'};$peer=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $peerCfg)) $resourceSelfTestPeerSource;$deadline=[DateTime]::UtcNow.AddSeconds(15);while(-not(Test-NonEmptyEvidenceFile $peerReady)-and[DateTime]::UtcNow-lt$deadline){if($peer.Process.HasExited){throw 'Resource readiness peer exited before READY'};Start-Sleep -Milliseconds 20};if(-not(Test-NonEmptyEvidenceFile $peerReady)){throw 'Resource readiness peer READY deadline'};$peerRow=[IO.File]::ReadAllText($peerReady,$utf8)|ConvertFrom-Json;if($peerRow.kind-cne'READY'-or$peerRow.pid-lt1){throw 'Resource readiness peer identity rejected'}
        $legacy=@(Get-LegacyRows);$canonical=@(Get-CanonicalArguments $legacy);$contract=New-CanonicalMonitorContract $canonical $legacy;$cfg=[ordered]@{stop=$dirWsl+'/resource.stop';log=$dirWsl+'/resource.jsonl';error=$dirWsl+'/resource.error.log';watcher_pid=[int]$peerRow.pid;timeout_argv=$contract.timeout_argv;bwrap_argv=$contract.bwrap_argv;test_argv=$contract.test_argv;minimum_kib=1900000;target_interval_ms=100;maximum_gap_ms=750;subprocess_sites=16;canonical_token_sha256=$contract.token_sha256;readiness_self_test=$true}
        $monitor=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $cfg)) $resourceMonitorSource;if(-not$monitor.Process.WaitForExit(15000)){try{$monitor.Process.Kill()}catch{};throw 'Resource readiness monitor deadline'};if(-not$monitor.OutTask.Wait(10000)-or-not$monitor.ErrTask.Wait(10000)){throw 'Resource readiness monitor stream drain deadline'};$out=$monitor.OutTask.GetAwaiter().GetResult();$err=$monitor.ErrTask.GetAwaiter().GetResult();$code=$monitor.Process.ExitCode;$monitor.Process.Dispose();$monitor=$null;if($code-ne0-or$out.Length-ne0-or$err.Length-ne0){throw "Resource readiness monitor wrapper rejected: exit=$code stderr=$err"}
        $raw=Read-StableUtf8Log $monitorLog 'Resource readiness self-test' $null;if((Get-Item -LiteralPath $monitorError).Length-ne0){throw 'Resource readiness monitor error evidence not empty'};$rows=@($raw.TrimEnd("`n").Split("`n")|ForEach-Object{$_|ConvertFrom-Json});if($rows.Count-ne3-or$rows[0].kind-cne'READY'-or-not[bool]$rows[0].readiness_self_test-or$rows[1].kind-cne'SAMPLE'-or$rows[1].sequence-ne1-or$rows[2].kind-cne'SELFTEST_DONE'-or-not[bool]$rows[2].readiness_self_test-or[bool]$rows[2].canonical_seen-or$rows[1].namespace_permission_denials-ne0-or$rows[2].namespace_permission_denials-ne0-or$rows[1].process_rows-ne($rows[1].namespace_exact_rows+$rows[1].namespace_not_required_infrastructure_rows+$rows[1].namespace_not_required_ancestry_rows+$rows[1].namespace_not_required_watcher_rows)-or$rows[1].namespace_not_required_infrastructure_rows-lt1){throw 'Resource readiness namespace/accounting evidence rejected'}
        $infraJson=[string]$rows[2].admitted_infrastructure_json;$infraParsed=ConvertFrom-Json -InputObject $infraJson;$infraRows=@();for($infraIndex=0;$infraIndex-lt$infraParsed.Count;$infraIndex++){$infraRows+=,$infraParsed[$infraIndex]};$infraHash=Get-Utf8StringSha256 $infraJson;if($rows[1].admitted_infrastructure_identities-lt1-or$rows[1].admitted_infrastructure_sha256-cnotmatch'^[0-9a-f]{64}$'-or$infraRows.Count-ne$rows[2].admitted_infrastructure_identities-or$rows[2].admitted_infrastructure_identities-ne$rows[1].admitted_infrastructure_identities-or$infraHash-cne$rows[2].admitted_infrastructure_sha256-or$rows[2].admitted_infrastructure_sha256-cne$rows[1].admitted_infrastructure_sha256){throw "Resource readiness infrastructure identity evidence rejected: sample_count=$($rows[1].admitted_infrastructure_identities) done_count=$($rows[2].admitted_infrastructure_identities) rows=$($infraRows.Count) sample_hash=$($rows[1].admitted_infrastructure_sha256) done_hash=$($rows[2].admitted_infrastructure_sha256) replay_hash=$infraHash"}
        Write-NewAscii $peerStop "stop`n";if(-not$peer.Process.WaitForExit(10000)){try{$peer.Process.Kill()}catch{};throw 'Resource readiness peer stop deadline'};if(-not$peer.OutTask.Wait(10000)-or-not$peer.ErrTask.Wait(10000)){throw 'Resource readiness peer stream drain deadline'};$peerOut=$peer.OutTask.GetAwaiter().GetResult();$peerErr=$peer.ErrTask.GetAwaiter().GetResult();$peerCode=$peer.Process.ExitCode;$peer.Process.Dispose();$peer=$null;if($peerCode-ne0-or$peerOut.Length-ne0-or$peerErr.Length-ne0){throw 'Resource readiness peer wrapper rejected'}
        $result=[ordered]@{schema='planora.muni-v33.resource-monitor-readiness-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;rows=$rows.Count;process_rows=$rows[1].process_rows;namespace_exact_rows=$rows[1].namespace_exact_rows;namespace_not_required_infrastructure_rows=$rows[1].namespace_not_required_infrastructure_rows;namespace_not_required_ancestry_rows=$rows[1].namespace_not_required_ancestry_rows;namespace_not_required_watcher_rows=$rows[1].namespace_not_required_watcher_rows;namespace_permission_denials=0;admitted_infrastructure_identities=$rows[2].admitted_infrastructure_identities;admitted_infrastructure_sha256=$rows[2].admitted_infrastructure_sha256;canonical_seen=$false;canonical_suite_executed=$false;shared_lock_used=$false;claim_created=$false;v33_artifacts_created=$false;wsl_executed=$true}
    }finally{
        if($null-ne$monitor){try{$monitor.Process.Kill()}catch{};try{$monitor.Process.Dispose()}catch{}};if($null-ne$peer){try{if(-not(Test-Path -LiteralPath $peerStop)){Write-NewAscii $peerStop "stop`n"}}catch{};try{if(-not$peer.Process.WaitForExit(3000)){$peer.Process.Kill()}}catch{};try{$peer.Process.Dispose()}catch{}};Clear-ResourceMonitorReadinessSelfTestDirectory $dir $known
    }
    $after=@(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if($after.Count-ne0-or(Test-Path -LiteralPath $claimFile)-or(Test-Path -LiteralPath $sharedLockPath)){throw 'Resource readiness self-test mutated protected state'};return $result
}

"""


TOP_LEVEL_JSON_HASH_HELPER = r"""function Get-RawTopLevelJsonObjectPropertyTokenHash([string]$Json,[string]$PropertyName){
    if([string]::IsNullOrWhiteSpace($Json)-or[string]::IsNullOrWhiteSpace($PropertyName)){throw 'Raw top-level JSON property input rejected'}
    $matches=New-Object 'Collections.Generic.List[int]';$topLevelNames=@{};$depth=0
    for($i=0;$i-lt$Json.Length;$i++){
        $ch=$Json[$i]
        if($ch-eq'"'){
            $nameStart=$i+1;$escaped=$false
            for($i=$i+1;$i-lt$Json.Length;$i++){
                $inner=$Json[$i]
                if($escaped){$escaped=$false;continue}
                if($inner-eq'\'){$escaped=$true;continue}
                if($inner-eq'"'){break}
            }
            if($i-ge$Json.Length){throw 'Raw top-level JSON string unterminated'}
            if($depth-eq1){
                $name=$Json.Substring($nameStart,$i-$nameStart);$cursor=$i+1
                while($cursor-lt$Json.Length-and[char]::IsWhiteSpace($Json[$cursor])){$cursor++}
                if($cursor-lt$Json.Length-and$Json[$cursor]-eq':'){
                    if($name.IndexOf('\',[StringComparison]::Ordinal)-ge0){throw "Raw top-level JSON escaped property name rejected: $name"}
                    if($topLevelNames.ContainsKey($name)){throw "Raw top-level JSON duplicate property name rejected: $name"}
                    $topLevelNames[$name]=$true
                    if($name-ceq$PropertyName){[void]$matches.Add($cursor)}
                }
            }
            continue
        }
        if($ch-eq'{'-or$ch-eq'['){$depth++}
        elseif($ch-eq'}'-or$ch-eq']'){$depth--;if($depth-lt0){throw 'Raw top-level JSON container depth rejected'}}
    }
    if($depth-ne0){throw 'Raw top-level JSON container unterminated'}
    if($matches.Count-ne1){throw "Raw top-level JSON property cardinality rejected: $PropertyName count=$($matches.Count)"}
    $i=[int]$matches[0]+1
    while($i-lt$Json.Length-and[char]::IsWhiteSpace($Json[$i])){$i++}
    if($i-ge$Json.Length-or$Json[$i]-ne'{'){throw "Raw top-level JSON object missing: $PropertyName"}
    $start=$i;$objectDepth=0;$inside=$false;$escaped=$false
    for(;$i-lt$Json.Length;$i++){
        $ch=$Json[$i]
        if($inside){if($escaped){$escaped=$false}elseif($ch-eq'\'){$escaped=$true}elseif($ch-eq'"'){$inside=$false};continue}
        if($ch-eq'"'){$inside=$true;continue}
        if($ch-eq'{'){$objectDepth++;continue}
        if($ch-eq'}'){$objectDepth--;if($objectDepth-eq0){$raw=$Json.Substring($start,$i-$start+1);return Get-Utf8StringSha256 (ConvertTo-JsonTokenStream $raw)};if($objectDepth-lt0){break}}
    }
    throw "Raw top-level JSON object unterminated: $PropertyName"
}
function Assert-ExactCanonicalJsonDocumentReplay([string]$Observed,[string]$Expected,[string]$Label){
    if([string]::IsNullOrWhiteSpace($Label)-or$null-eq$Observed-or$null-eq$Expected){throw 'Exact canonical JSON replay input rejected'}
    if(-not[string]::Equals($Observed,$Expected,[StringComparison]::Ordinal)){throw "$Label exact canonical JSON document replay rejected"}
    return $true
}
"""


STABLE_LOG_READER = r"""$stableLogReadStates=@{}
function Get-BytePrefixSha256([byte[]]$Bytes,[int]$Count){
    if($null-eq$Bytes-or$Count-lt0-or$Count-gt$Bytes.Length){throw [IO.InvalidDataException]::new('Byte prefix hash bounds rejected')};$sha=[Security.Cryptography.SHA256]::Create()
    try{return([BitConverter]::ToString($sha.ComputeHash($Bytes,0,$Count))-replace'-','').ToLowerInvariant()}finally{$sha.Dispose()}
}
function Read-StableUtf8Log([string]$Path,[string]$Label,[object]$WriterProcess){
    $deadline=[DateTime]::UtcNow.AddSeconds(3);$strictUtf8=New-Object Text.UTF8Encoding($false,$true);$writerSupplied=($null-ne$WriterProcess);$key=[IO.Path]::GetFullPath($Path);$prior=$null
    if($stableLogReadStates.ContainsKey($key)){$prior=$stableLogReadStates[$key]};$identityBound=($null-ne$prior);$attemptVolume=if($identityBound){[uint32]$prior.volume}else{[uint32]0};$attemptIndex=if($identityBound){[uint64]$prior.index}else{[uint64]0};$attemptLength=if($identityBound){[long]$prior.length}else{0L};$attemptPrefixSha=if($identityBound){[string]$prior.prefix_sha256}else{''}
    while($true){
        if(-not(Test-Path -LiteralPath $Path)){if($identityBound){throw [IO.InvalidDataException]::new("$Label log disappeared after identity binding")};if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};return ''}
        $share=[IO.FileShare]::Read;$stream=$null
        try{$stream=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share)}catch [IO.IOException]{if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}catch [UnauthorizedAccessException]{if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}
        try{
            $before=Get-HeldFileIdentity $stream $Label;if(-not$identityBound){$identityBound=$true;$attemptVolume=[uint32]$before.volume;$attemptIndex=[uint64]$before.index}elseif($before.volume-ne$attemptVolume-or$before.index-ne$attemptIndex){throw [IO.InvalidDataException]::new("$Label log identity changed from bound handle")}
            $length=[long]$stream.Length;if($length-gt[int]::MaxValue){throw [IO.InvalidDataException]::new("$Label log length rejected")};if($length-lt$attemptLength){throw [IO.InvalidDataException]::new("$Label log truncation below bound prefix")};$bytes=New-Object byte[] ([int]$length);$offset=0
            while($offset-lt$bytes.Length){$count=$stream.Read($bytes,$offset,$bytes.Length-$offset);if($count-le0){throw [IO.InvalidDataException]::new("$Label log short read or truncation")};$offset+=$count};$readHash=Get-BytePrefixSha256 $bytes $bytes.Length
            if($attemptLength-gt0-and(Get-BytePrefixSha256 $bytes ([int]$attemptLength))-cne$attemptPrefixSha){throw [IO.InvalidDataException]::new("$Label log prior prefix digest changed")}
            $after=Get-HeldFileIdentity $stream $Label;$currentLength=[long]$stream.Length;if($currentLength-lt$length-or$after.volume-ne$attemptVolume-or$after.index-ne$attemptIndex){throw [IO.InvalidDataException]::new("$Label log identity or truncation drift during append-prefix read")}
            $probe=$null
            while($null-eq$probe){try{$probe=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share)}catch [IO.IOException]{if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}catch [UnauthorizedAccessException]{if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}}
            try{$pathIdentity=Get-HeldFileIdentity $probe ($Label+' path replay');if($pathIdentity.volume-ne$attemptVolume-or$pathIdentity.index-ne$attemptIndex){throw [IO.InvalidDataException]::new("$Label log path identity drift")}}finally{$probe.Dispose()}
            [void]$stream.Seek(0,[IO.SeekOrigin]::Begin);$replayBytes=New-Object byte[] ([int]$length);$replayOffset=0
            while($replayOffset-lt$replayBytes.Length){$replayCount=$stream.Read($replayBytes,$replayOffset,$replayBytes.Length-$replayOffset);if($replayCount-le0){throw [IO.InvalidDataException]::new("$Label log held-handle prefix replay short read")};$replayOffset+=$replayCount}
            $replayHash=Get-BytePrefixSha256 $replayBytes $replayBytes.Length;if($replayHash-cne$readHash){throw [IO.InvalidDataException]::new("$Label log held-handle prefix replay changed")};$final=Get-HeldFileIdentity $stream $Label;$finalLength=[long]$stream.Length;if($finalLength-lt$length-or$final.volume-ne$attemptVolume-or$final.index-ne$attemptIndex){throw [IO.InvalidDataException]::new("$Label log identity or truncation drift after held-handle prefix replay")}
        }finally{$stream.Dispose()}
        try{$raw=$strictUtf8.GetString($bytes)}catch [Text.DecoderFallbackException]{throw [IO.InvalidDataException]::new("$Label log UTF-8 rejected",$_.Exception)}
        $fullHash=$readHash;if($raw.Contains("`r")){throw [IO.InvalidDataException]::new("$Label log CR framing rejected")};if($raw.Length-ne0-and-not$raw.EndsWith("`n",[StringComparison]::Ordinal)){if($writerSupplied-and[DateTime]::UtcNow-lt$deadline){$attemptLength=$length;$attemptPrefixSha=$fullHash;Start-Sleep -Milliseconds 10;continue};throw [IO.InvalidDataException]::new("$Label log incomplete framing")}
        $stableLogReadStates[$key]=[ordered]@{volume=$attemptVolume;index=$attemptIndex;length=$length;prefix_sha256=$fullHash};return $raw
    }
}
function Invoke-StableLogReaderStateRegression{
    $name='muni-v33-log-reader-state-'+[Guid]::NewGuid().ToString('N');$tmpRoot=Join-Path $repo 'tmp';if(-not(Test-Path -LiteralPath $tmpRoot)){[void](New-Item -ItemType Directory -Path $tmpRoot)};$dir=Join-Path $tmpRoot $name;[void](New-Item -ItemType Directory -Path $dir);$expectedPrefix=[IO.Path]::GetFullPath((Join-Path $repo 'tmp\muni-v33-log-reader-state-'))
    try{
        $appendPath=Join-Path $dir 'append.jsonl';$first="{`"kind`":`"A`"}`n";$second="{`"kind`":`"B`"}`n";[IO.File]::WriteAllText($appendPath,$first,$utf8);$appendBefore=Read-StableUtf8Log $appendPath 'Static append' $null;[IO.File]::AppendAllText($appendPath,$second,$utf8);$appendAfter=Read-StableUtf8Log $appendPath 'Static append' $null;if($appendBefore-cne$first-or$appendAfter-cne($first+$second)){throw 'Stable append-prefix positive regression rejected'}
        $replacementPath=Join-Path $dir 'replacement.jsonl';$replacementOld=Join-Path $dir 'replacement.old';[IO.File]::WriteAllText($replacementPath,$first,$utf8);[void](Read-StableUtf8Log $replacementPath 'Static replacement' $null);[IO.File]::Move($replacementPath,$replacementOld);[IO.File]::WriteAllText($replacementPath,$second,$utf8);$replacementRejected=$false;try{[void](Read-StableUtf8Log $replacementPath 'Static replacement' $null)}catch [IO.InvalidDataException]{$replacementRejected=$true}
        $truncationPath=Join-Path $dir 'truncation.jsonl';[IO.File]::WriteAllText($truncationPath,($first+$second),$utf8);[void](Read-StableUtf8Log $truncationPath 'Static truncation' $null);$truncationStream=New-Object IO.FileStream($truncationPath,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$truncationStream.SetLength($utf8.GetByteCount($first));$truncationStream.Flush($true)}finally{$truncationStream.Dispose()};$truncationRejected=$false;try{[void](Read-StableUtf8Log $truncationPath 'Static truncation' $null)}catch [IO.InvalidDataException]{$truncationRejected=$true}
        $rewritePath=Join-Path $dir 'rewrite.jsonl';[IO.File]::WriteAllText($rewritePath,$first,$utf8);[void](Read-StableUtf8Log $rewritePath 'Static rewrite' $null);[IO.File]::WriteAllText($rewritePath,$second,$utf8);$rewriteRejected=$false;try{[void](Read-StableUtf8Log $rewritePath 'Static rewrite' $null)}catch [IO.InvalidDataException]{$rewriteRejected=$true}
        $guardPath=Join-Path $dir 'guard.jsonl';[IO.File]::WriteAllText($guardPath,$first,$utf8);$guard=New-Object IO.FileStream($guardPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);$guardedWriter=$null;$guardedRewriteRejected=$false;try{try{$guardedWriter=New-Object IO.FileStream($guardPath,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)}catch [IO.IOException]{$guardedRewriteRejected=$true}catch [UnauthorizedAccessException]{$guardedRewriteRejected=$true}}finally{if($null-ne$guardedWriter){$guardedWriter.Dispose()};$guard.Dispose()}
        $framingPath=Join-Path $dir 'framing.jsonl';[IO.File]::WriteAllText($framingPath,'{}',$utf8);$framingRejected=$false;try{[void](Read-StableUtf8Log $framingPath 'Static framing' $null)}catch [IO.InvalidDataException]{$framingRejected=$true};$crPath=Join-Path $dir 'cr.jsonl';[IO.File]::WriteAllText($crPath,"{}`r`n",$utf8);$crRejected=$false;try{[void](Read-StableUtf8Log $crPath 'Static CR' $null)}catch [IO.InvalidDataException]{$crRejected=$true};$utf8Path=Join-Path $dir 'utf8.jsonl';[IO.File]::WriteAllBytes($utf8Path,[byte[]](0x7b,0xc3));$utf8Rejected=$false;try{[void](Read-StableUtf8Log $utf8Path 'Static UTF8' $null)}catch [IO.InvalidDataException]{$utf8Rejected=$true}
        if(-not$replacementRejected-or-not$truncationRejected-or-not$rewriteRejected-or-not$guardedRewriteRejected-or-not$framingRejected-or-not$crRejected-or-not$utf8Rejected){throw 'Stable log reader negative regression rejected'};return [ordered]@{append_prefix='PASS';replacement='REJECTED';truncation='REJECTED';same_identity_prefix_rewrite='REJECTED';concurrent_rewrite_while_guarded='REJECTED_BY_SHARE';missing_terminal_lf='REJECTED';cr='REJECTED';partial_utf8='REJECTED'}
    }finally{$full=[IO.Path]::GetFullPath($dir);if(-not$full.StartsWith($expectedPrefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Stable log reader cleanup path rejected'};if(Test-Path -LiteralPath $dir){Remove-Item -LiteralPath $dir -Recurse -Force}}
}
"""


def render_runner(
    builder_size: int, builder_hash: str, tests_size: int, tests_hash: str
) -> str:
    for expected in PINS:
        assert_pin(expected)

    source = V32_RUNNER.read_text(encoding="utf-8")
    source = source.replace(V32_RUN_ID, RUN_ID)
    source = source.replace("v32", "v33").replace("V32", "V33")
    source = source.replace("20260828T130114Z", STAMP)
    source = source.replace("2026-08-28T13:01:14Z", CREATED_AT)
    authorization_header = (
        "function Get-ExpectedAuthorizationJson([long]$RunnerSize,[string]$RunnerHash){"
    )
    if source.count(authorization_header) != 2:
        raise RuntimeError("v33 inherited authorization definition count rejected")
    source = source.replace(
        authorization_header,
        "function Get-ObsoleteV12AuthorizationJson([long]$RunnerSize,[string]$RunnerHash){",
        1,
    )
    source = replace_once(
        source,
        "[switch]$RejectionPromotionSelfTest)",
        "[switch]$RejectionPromotionSelfTest,[switch]$ResourceMonitorReadinessSelfTest)",
    )

    top_anchor = (
        "$v31StagingInventoryWsl = "
        "'/mnt/d/Stuff/Projects/Sites/Planora/output/diagnostic-receipts/"
        "muni-fspsx-v31-canonical-readonly-tests-5f2d84640f40404a82dd180d7043d9c5."
        "staging-inventory.json'"
    )
    top_addition = r"""
$v32Prefix = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0'
$v32ReceiptPath = $v32Prefix+'.receipt.json'
$v32PassSealPath = $v32Prefix+'.pass-publication-shutdown-seal.json'
$v32RejectionPath = $v32Prefix+'.rejection.json'
$v32SnapshotRoot = '/tmp/planora-muni-v32-canonical-tests-4dc45edcd74446909290afadd5d3ecf0'
$v32StagingInventoryWsl = '/mnt/d/Stuff/Projects/Sites/Planora/output/diagnostic-receipts/muni-fspsx-v32-canonical-readonly-tests-4dc45edcd74446909290afadd5d3ecf0.staging-inventory.json'
"""
    source = replace_once(source, top_anchor, top_anchor + top_addition)
    source = replace_once(
        source,
        '$retainedV31SnapshotTerminalCustodyFile = "$prefix.retained-v31-snapshot-terminal-custody.json"',
        '$retainedV31SnapshotTerminalCustodyFile = "$prefix.retained-v31-snapshot-terminal-custody.json"\n'
        '$retainedV32SnapshotCustodyFile = "$prefix.retained-v32-snapshot-custody.json"\n'
        '$retainedV32SnapshotTerminalCustodyFile = "$prefix.retained-v32-snapshot-terminal-custody.json"',
    )

    contract_json = json.dumps(V32_FAILURE_CONTRACT, separators=(",", ":"))
    source = replace_once(
        source,
        "'@\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
        "'@\n$v32FailureContractJson = @'\n"
        + contract_json
        + "\n'@\n$utf8 = New-Object System.Text.UTF8Encoding($false)",
    )

    source = replace_region(
        source,
        "$resourceMonitorSource = @'\n",
        "$legacyLogBridgeSource = @'",
        RESOURCE_MONITOR_BLOCK + "\n" + RESOURCE_SELFTEST_PEER_BLOCK + "\n",
    )
    source = replace_once(
        source,
        "function Stop-Watcher([object]$Watcher",
        RETAINED_V32_FUNCTIONS + "function Stop-Watcher([object]$Watcher",
    )
    source = replace_region(
        source,
        "function Assert-V28V29V30V31PassEvidenceAbsent([string]$Phase){",
        "function Assert-RetainedArchivePin",
        PASS_ABSENCE_FUNCTION,
    )
    source = source.replace(
        "Assert-V28V29V30V31PassEvidenceAbsent",
        "Assert-V28V29V30V31V32PassEvidenceAbsent",
    )
    source = replace_region(
        source,
        "function New-ExpectedCompletePredecessorEvidence{",
        "function Invoke-LockSelfReadRegressionModel{",
        V32_FAILURE_AND_COMPLETE_FUNCTIONS,
    )
    source = replace_once(
        source,
        "function Get-ValidatedCombinedPredecessorEvidence([bool]$RequireSharedLockAbsent){",
        TOP_LEVEL_JSON_HASH_HELPER
        + "\nfunction Get-ValidatedCombinedPredecessorEvidence([bool]$RequireSharedLockAbsent){",
    )
    source = replace_once(
        source,
        "if($CanonicalMonitorContractSelfTest){",
        RESOURCE_READINESS_SELFTEST
        + "if($ResourceMonitorReadinessSelfTest){\n"
        + "    $result=Invoke-ResourceMonitorReadinessSelfTest;[Console]::Out.WriteLine(($result|ConvertTo-Json -Depth 10 -Compress));return\n"
        + "}\n"
        + "if($CanonicalMonitorContractSelfTest){",
    )

    source = replace_once(
        source,
        "$closure=$snapshotContractJson|ConvertFrom-Json;$predecessor=$predecessorContractJson|ConvertFrom-Json;$v31Failure=$v31FailureContractJson|ConvertFrom-Json",
        "$closure=$snapshotContractJson|ConvertFrom-Json;$predecessor=$predecessorContractJson|ConvertFrom-Json;$v31Failure=$v31FailureContractJson|ConvertFrom-Json;$v32Failure=$v32FailureContractJson|ConvertFrom-Json",
    )
    source = replace_once(
        source,
        "schema='planora.itc2019.canonical-test-authorization.v12';created_at_utc='2026-08-28T14:16:39Z';instance='muni-fspsx-fal17';candidate='muni_v33'",
        "schema='planora.itc2019.canonical-test-authorization.v13';created_at_utc='2026-08-28T14:16:39Z';instance='muni-fspsx-fal17';candidate='muni_v33'",
    )
    source = replace_once(
        source,
        "GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_AUTHENTICATED_V31_ARGV_PIPELINE_FAILURE",
        "GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_AUTHENTICATED_V32_NAMESPACE_PERMISSION_FAILURE",
    )
    admission_pattern = re.compile(
        r"successor_admission=\[ordered\]@\{builder=\[ordered\]@\{path='scripts/build_muni_v33_successor\.py';size=\d+;sha256='[0-9a-f]{64}'\};tests=\[ordered\]@\{path='tests/test_run_muni_v33_successor\.py';size=\d+;sha256='[0-9a-f]{64}'\}\}"
    )
    admission = (
        "successor_admission=[ordered]@{builder=[ordered]@{path='scripts/build_muni_v33_successor.py';size="
        f"{builder_size};sha256='{builder_hash}'"
        "};tests=[ordered]@{path='tests/test_run_muni_v33_successor.py';size="
        f"{tests_size};sha256='{tests_hash}'"
        "}}"
    )
    source, admission_count = admission_pattern.subn(admission, source)
    if admission_count != 1:
        raise RuntimeError("v33 successor admission replacement failed")
    source = replace_once(
        source,
        "predecessor_custody_contract=$predecessor;v31_failure_custody_contract=$v31Failure",
        "predecessor_custody_contract=$predecessor;v31_failure_custody_contract=$v31Failure;v32_failure_custody_contract=$v32Failure",
    )
    source = replace_once(
        source,
        '$length=$stream.Length;if($length-ne$before.size-or$length-gt[ int ]::MaxValue){throw [IO.InvalidDataException]::new("$Label log length rejected")};$bytes=New-Object byte[] ([int]$length)',
        '$length=$stream.Length;if($length-gt[ int ]::MaxValue){throw [IO.InvalidDataException]::new("$Label log length rejected")};if($length-ne$before.size){throw [IO.IOException]::new("$Label log length drift during live read")};$bytes=New-Object byte[] ([int]$length)',
    )
    source = replace_once(
        source,
        '$after=Get-HeldFileIdentity $stream $Label;if($stream.Length-ne$length-or$after.volume-ne$before.volume-or$after.index-ne$before.index-or$after.size-ne$before.size){throw [IO.IOException]::new("$Label log identity or length drift during read")};$probe=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share);try{$pathIdentity=Get-HeldFileIdentity $probe ($Label+\' path replay\');if($pathIdentity.volume-ne$before.volume-or$pathIdentity.index-ne$before.index){throw [IO.IOException]::new("$Label log path identity drift")}}finally{$probe.Dispose()}',
        '$after=Get-HeldFileIdentity $stream $Label;$currentLength=$stream.Length;if($currentLength-lt$length-or$after.volume-ne$before.volume-or$after.index-ne$before.index-or$after.size-lt$before.size-or$after.size-lt[uint64]$length){throw [IO.IOException]::new("$Label log identity or truncation drift during append-prefix read")};$probe=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share);try{$pathIdentity=Get-HeldFileIdentity $probe ($Label+\' path replay\');if($pathIdentity.volume-ne$before.volume-or$pathIdentity.index-ne$before.index-or$pathIdentity.size-lt[uint64]$length){throw [IO.IOException]::new("$Label log path identity or truncation drift")}}finally{$probe.Dispose()}',
    )
    source = replace_once(
        source,
        "reader='bounded_explicit_FileStream_stable_identity_length_terminal_LF_UTF8_JSON'",
        "reader='bounded_explicit_FileStream_restrictive_read_guard_persistent_identity_monotonic_prefix_digest_terminal_LF_UTF8_JSON'",
    )
    stable_reader_pattern = re.compile(
        r"function Read-StableUtf8Log\(\[string\]\$Path,\[string\]\$Label,"
        r"\[object\]\$WriterProcess\)\{.*?(?=\r?\nfunction Get-WatcherLogState)",
        re.DOTALL,
    )
    source, stable_reader_count = stable_reader_pattern.subn(
        lambda _match: STABLE_LOG_READER, source
    )
    if stable_reader_count != 1:
        raise RuntimeError("v33 persistent stable log reader replacement failed")
    source = replace_once(
        source,
        "status='EXACT_V28_V29_V30_V31_CUSTODY_VALIDATED_BEFORE_V33_LOCK';run_id=$runId",
        "status='EXACT_V28_V29_V30_V31_V32_CUSTODY_VALIDATED_BEFORE_V33_LOCK';run_id=$runId",
    )
    source = replace_once(source, "throw'nlink'", "throw 'nlink'")
    custody_write = (
        ";Write-NewUtf8 $predecessorCustodyFile "
        "($custody|ConvertTo-Json -Depth 70);"
        "$predecessorCustodyHash=Get-Sha256 $predecessorCustodyFile"
    )
    custody_replay = (
        ";$custodyJson=$custody|ConvertTo-Json -Depth 70;"
        "Write-NewUtf8 $predecessorCustodyFile $custodyJson;"
        "$custodyExpectedBytes=$utf8.GetBytes($custodyJson);"
        "$predecessorCustodyGuard=New-Object IO.FileStream("
        "$predecessorCustodyFile,[IO.FileMode]::Open,[IO.FileAccess]::Read,"
        "[IO.FileShare]::Read);"
        "if($predecessorCustodyGuard.Length-ne$custodyExpectedBytes.Length"
        "-or$predecessorCustodyGuard.Length-gt[int]::MaxValue){"
        "throw 'Pre-lock predecessor custody byte length rejected'};"
        "$custodyObservedBytes=New-Object byte[] "
        "([int]$predecessorCustodyGuard.Length);$custodyOffset=0;"
        "while($custodyOffset-lt$custodyObservedBytes.Length){"
        "$custodyRead=$predecessorCustodyGuard.Read("
        "$custodyObservedBytes,$custodyOffset,"
        "$custodyObservedBytes.Length-$custodyOffset);"
        "if($custodyRead-le0){"
        "throw 'Pre-lock predecessor custody held-handle read rejected'};"
        "$custodyOffset+=$custodyRead};"
        "for($custodyIndex=0;$custodyIndex-lt$custodyExpectedBytes.Length;"
        "$custodyIndex++){if($custodyObservedBytes[$custodyIndex]-ne"
        "$custodyExpectedBytes[$custodyIndex]){"
        "throw 'Pre-lock predecessor custody exact byte replay rejected'}};"
        "$custodyRaw=$utf8.GetString($custodyObservedBytes);"
        "[void](Assert-ExactCanonicalJsonDocumentReplay $custodyRaw "
        "$custodyJson 'Pre-lock predecessor custody');"
        "$custodyReplay=$custodyRaw|ConvertFrom-Json;"
        "$custodyPins=@($custodyReplay.predecessor_evidence.runtime.validated_pins);"
        "$custodyPredecessorRawHash=Get-RawTopLevelJsonObjectPropertyTokenHash "
        "$custodyRaw 'predecessor_evidence';"
        "$custodyV31RawHash=Get-RawTopLevelJsonObjectPropertyTokenHash "
        "$custodyRaw 'v31_failure_evidence';"
        "$custodyV32RawHash=Get-RawTopLevelJsonObjectPropertyTokenHash "
        "$custodyRaw 'v32_failure_evidence';"
        "if($custodyReplay.schema-cne'planora.muni-v33.predecessor-custody.v1'"
        "-or$custodyReplay.status-cne"
        "'EXACT_V28_V29_V30_V31_V32_CUSTODY_VALIDATED_BEFORE_V33_LOCK'"
        "-or$custodyReplay.run_id-cne$runId"
        "-or-not[bool]$custodyReplay.shared_lock_absent"
        "-or$custodyReplay.predecessor_evidence.status-cne"
        "'VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'"
        "-or$custodyPins.Count-ne89"
        "-or@($custodyPins.path|Sort-Object -Unique).Count-ne89"
        "-or$custodyReplay.predecessor_evidence_sha256-cne$predecessorEvidenceHash"
        "-or$custodyReplay.v31_failure_evidence_sha256-cne$v31FailureEvidenceHash"
        "-or$custodyReplay.v32_failure_evidence_sha256-cne$v32FailureEvidenceHash"
        "-or$custodyPredecessorRawHash-cne$predecessorEvidenceHash"
        "-or$custodyV31RawHash-cne$v31FailureEvidenceHash"
        "-or$custodyV32RawHash-cne$v32FailureEvidenceHash){"
        "throw 'Pre-lock predecessor custody replay rejected'};"
        "$predecessorCustodyHash=Get-BytesSha256 $custodyObservedBytes"
    )
    source = replace_once(source, custody_write, custody_replay)
    source = replace_once(
        source,
        "$lockStream=$null;$lockHash='';$lockBody=$null;$predecessorCustodyHash='';",
        "$lockStream=$null;$lockHash='';$lockBody=$null;$predecessorCustodyHash='';$predecessorCustodyGuard=$null;",
    )
    source = replace_once(
        source,
        "if($null-ne$lockStream){try{Release-HeavyLock $lockStream $lockHash 'REJECTED' $acceptanceHash $cleanupHash; $lockStream=$null}catch{$failure+=\"; lock_release=$($_.Exception.Message)\"}}\n    throw $failure",
        "if($null-ne$lockStream){try{Release-HeavyLock $lockStream $lockHash 'REJECTED' $acceptanceHash $cleanupHash; $lockStream=$null}catch{$failure+=\"; lock_release=$($_.Exception.Message)\"}}\n    if($null-ne$predecessorCustodyGuard){try{$predecessorCustodyGuard.Dispose()}catch{};$predecessorCustodyGuard=$null}\n    throw $failure",
    )
    source = replace_once(
        source,
        "if($StaticSelfTest){\n    $auth=Get-AuthorizationState\n    $rows=@(Get-LegacyRows)",
        "if($StaticSelfTest){\n"
        "    $auth=Get-AuthorizationState\n"
        '    $topLevelFixture=\'{"predecessor_evidence":{"v31_failure_evidence":{"scope":"nested-v31"},"v32_failure_evidence":{"scope":"nested-v32"}},"v31_failure_evidence":{"scope":"outer-v31"},"v32_failure_evidence":{"scope":"outer-v32"}}\';'
        '$expectedTopV31=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream \'{"scope":"outer-v31"}\');'
        '$expectedTopV32=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream \'{"scope":"outer-v32"}\');'
        "$observedTopV31=Get-RawTopLevelJsonObjectPropertyTokenHash $topLevelFixture 'v31_failure_evidence';"
        "$observedTopV32=Get-RawTopLevelJsonObjectPropertyTokenHash $topLevelFixture 'v32_failure_evidence';"
        "$legacyNestedV31=Get-RawJsonObjectPropertyTokenHash $topLevelFixture 'v31_failure_evidence';"
        "$duplicateTopLevelRejected=$false;try{[void](Get-RawTopLevelJsonObjectPropertyTokenHash '{\"v31_failure_evidence\":{},\"v31_failure_evidence\":{}}' 'v31_failure_evidence')}catch{$duplicateTopLevelRejected=$true};"
        '$escapedAliasRejected=$false;try{[void](Get-RawTopLevelJsonObjectPropertyTokenHash \'{"v31_failure_evidence":{"scope":"literal"},"v31_failure_\\u0065vidence":{"scope":"escaped"}}\' \'v31_failure_evidence\')}catch{$escapedAliasRejected=$true};'
        "$caseAliasRejected=$false;try{[void](Get-RawTopLevelJsonObjectPropertyTokenHash '{\"v31_failure_evidence\":{},\"V31_FAILURE_EVIDENCE\":{}}' 'v31_failure_evidence')}catch{$caseAliasRejected=$true};"
        '$canonicalWholeDocument=\'{"predecessor_evidence":{"scope":"expected"}}\';'
        "$singleQuotedAlias='{\"predecessor_evidence\":{\"scope\":\"expected\"},''predecessor_evidence'':{''scope'':''malicious''}}';"
        '$unquotedAlias=\'{"predecessor_evidence":{"scope":"expected"},predecessor_evidence:{scope:"malicious"}}\';'
        '$commentedAlias=\'{"predecessor_evidence":{"scope":"expected"},/* { hidden } */"predecessor_evidence":{"scope":"malicious"}}\';'
        "if(-not(Assert-ExactCanonicalJsonDocumentReplay $canonicalWholeDocument $canonicalWholeDocument 'Static canonical JSON')){throw 'Canonical whole-document replay baseline rejected'};"
        "$singleParsed=$singleQuotedAlias|ConvertFrom-Json;$unquotedParsed=$unquotedAlias|ConvertFrom-Json;"
        "if($singleParsed.predecessor_evidence.scope-cne'malicious'-or$unquotedParsed.predecessor_evidence.scope-cne'malicious'){throw 'Permissive JSON parser attack baseline rejected'};"
        "if($PSVersionTable.PSVersion.Major-ge7){$commentedParsed=$commentedAlias|ConvertFrom-Json;if($commentedParsed.predecessor_evidence.scope-cne'malicious'){throw 'Commented JSON parser attack baseline rejected'}};"
        "$nonCanonicalWholeDocumentRejected=0;foreach($attack in @($singleQuotedAlias,$unquotedAlias,$commentedAlias)){try{[void](Assert-ExactCanonicalJsonDocumentReplay $attack $canonicalWholeDocument 'Static noncanonical JSON')}catch{$nonCanonicalWholeDocumentRejected++}};"
        "if($observedTopV31-cne$expectedTopV31-or$observedTopV32-cne$expectedTopV32-or$legacyNestedV31-ceq$expectedTopV31-or-not$duplicateTopLevelRejected-or-not$escapedAliasRejected-or-not$caseAliasRejected-or$nonCanonicalWholeDocumentRejected-ne3){throw 'Top-level and whole-document raw JSON shadow replay regression rejected'}\n"
        "    $rows=@(Get-LegacyRows)",
    )
    source = replace_once(
        source,
        "complete_predecessor_evidence_binding='PASS';cross_boundary_log_protocol=",
        "complete_predecessor_evidence_binding='PASS';top_level_raw_json_shadow_replay='PASS';whole_document_canonical_json_replay='PASS';cross_boundary_log_protocol=",
    )
    source = replace_once(
        source,
        "    $checks=Invoke-LocalStaticAdversarialChecks",
        "    $checks=Invoke-LocalStaticAdversarialChecks;$logReaderRegression=Invoke-StableLogReaderStateRegression",
    )
    source = replace_once(
        source,
        "cross_boundary_log_protocol='SHORT_LIVED_IDENTITY_CHECKED_APPEND_AND_STABLE_HOST_READ';authoritative_archived_lock_terminal_replay=",
        "cross_boundary_log_protocol='SHORT_LIVED_IDENTITY_CHECKED_APPEND_AND_PERSISTENT_PREFIX_CUSTODY';log_reader_state_regression=$logReaderRegression;authoritative_archived_lock_terminal_replay=",
    )
    source = replace_once(
        source,
        "return($o|ConvertTo-Json -Depth 60 -Compress)",
        "$o.heavy_gate['namespace_visibility_policy']='namespace_dereference_attempted_for_every_row_except_monitor_and_watcher_then_permission_denial_exempt_only_for_exact_wsl_control_shape';$o.heavy_gate['infrastructure_identity_policy']='exact_pid_parent_pgrp_session_starttime_uid_comm_argv_exe_and_relay_child_binding_frozen_on_first_sample_then_every_frozen_pid_rechecked_before_classification_with_append_only_set_growth';$o.heavy_gate['infrastructure_identity_telemetry']='canonical_json_sha256_each_sample_plus_final_hash_bound_identity_rows';$o.heavy_gate['nonconsuming_live_readiness_switch']='ResourceMonitorReadinessSelfTest';$o.heavy_gate['namespace_state_accounting_required']=$true;$o.evidence_contract['complete_v28_v29_v30_v31_v32_predecessor_pin_count']=89;$o.evidence_contract['v32_namespace_failure_exact_20_artifacts_and_13_absences_bound']=$true;$o.evidence_contract['retained_v32_snapshot_initial_terminal_rejection_and_final_replay_bound']=$true\n    return($o|ConvertTo-Json -Depth 60 -Compress)",
    )

    source = replace_once(
        source,
        "if($Rows.Count-lt2-or$Rows[0].kind-cne'READY'-or$Rows[0].target_interval_ms-ne100-or$Rows[0].maximum_gap_ms-ne750-or$Rows[0].pinned_subprocess_sites-ne16-or$Rows[0].cadence_claim-cne'bounded_maximum_gap_not_exact_interval'-or$Rows[0].descendant_policy-cne'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'-or$Rows[0].canonical_token_sha256-cnotmatch'^[0-9a-f]{64}$'){throw 'Resource monitor cadence contract rejected'}",
        "if($Rows.Count-lt2-or$Rows[0].kind-cne'READY'-or[bool]$Rows[0].readiness_self_test-or$Rows[0].target_interval_ms-ne100-or$Rows[0].maximum_gap_ms-ne750-or$Rows[0].pinned_subprocess_sites-ne16-or$Rows[0].cadence_claim-cne'bounded_maximum_gap_not_exact_interval'-or$Rows[0].descendant_policy-cne'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'-or$Rows[0].canonical_token_sha256-cnotmatch'^[0-9a-f]{64}$'){throw 'Resource monitor cadence contract rejected'}",
    )
    source = replace_once(
        source,
        "$row=$Rows[$i];if($row.kind-cne'SAMPLE'-or$row.sequence-ne$i-or$row.memavailable_kib-lt1900000-or$row.monotonic_ns-le0-or$row.gap_ns-lt0-or$row.gap_ns-gt750000000){throw 'Resource monitor sample/cadence grammar rejected'}",
        "$row=$Rows[$i];if($row.kind-cne'SAMPLE'-or$row.sequence-ne$i-or$row.memavailable_kib-lt1900000-or$row.monotonic_ns-le0-or$row.gap_ns-lt0-or$row.gap_ns-gt750000000-or$row.namespace_permission_denials-ne0-or$row.process_rows-ne($row.namespace_exact_rows+$row.namespace_not_required_infrastructure_rows+$row.namespace_not_required_ancestry_rows+$row.namespace_not_required_watcher_rows)-or$row.admitted_infrastructure_identities-lt1-or$row.admitted_infrastructure_sha256-cnotmatch'^[0-9a-f]{64}$'){throw 'Resource monitor sample/cadence/namespace grammar rejected'}",
    )
    source = replace_once(
        source,
        "if($done.kind-cne'DONE'-or-not$done.canonical_seen-or-not$done.launch_namespace_bound-or$done.samples-ne($Rows.Count-2)-or$done.target_interval_ms-ne100-or$done.maximum_gap_ms-ne750-or$done.pinned_subprocess_sites-ne16-or$done.maximum_observed_gap_ns-ne$maximum-or$done.canonical_token_sha256-cne$Rows[0].canonical_token_sha256-or$done.admitted_descendant_identities-lt1-or$identityRows.Count-ne$done.admitted_descendant_identities){throw 'Resource monitor final cadence/descendant evidence rejected'}",
        "if($done.kind-cne'DONE'-or[bool]$done.readiness_self_test-or-not$done.canonical_seen-or-not$done.launch_namespace_bound-or$done.samples-ne($Rows.Count-2)-or$done.target_interval_ms-ne100-or$done.maximum_gap_ms-ne750-or$done.pinned_subprocess_sites-ne16-or$done.maximum_observed_gap_ns-ne$maximum-or$done.canonical_token_sha256-cne$Rows[0].canonical_token_sha256-or$done.admitted_descendant_identities-lt1-or$identityRows.Count-ne$done.admitted_descendant_identities-or$done.admitted_infrastructure_identities-lt1){throw 'Resource monitor final cadence/descendant evidence rejected'}",
    )
    source = replace_once(
        source,
        "$identityJson=ConvertTo-Json -InputObject $identityRows -Depth 10 -Compress;if((Get-Utf8StringSha256 $identityJson)-cne$done.admitted_identities_sha256){throw 'Resource monitor admitted identity digest rejected'}",
        "$identityJson=ConvertTo-Json -InputObject $identityRows -Depth 10 -Compress;if((Get-Utf8StringSha256 $identityJson)-cne$done.admitted_identities_sha256){throw 'Resource monitor admitted identity digest rejected'};$infrastructureJson=[string]$done.admitted_infrastructure_json;$infrastructureParsed=ConvertFrom-Json -InputObject $infrastructureJson;$infrastructureRows=@();for($infrastructureIndex=0;$infrastructureIndex-lt$infrastructureParsed.Count;$infrastructureIndex++){$infrastructureRows+=,$infrastructureParsed[$infrastructureIndex]};if($infrastructureRows.Count-ne$done.admitted_infrastructure_identities){throw 'Resource monitor admitted infrastructure cardinality rejected'};$seenInfrastructure=@{};foreach($infrastructureRow in $infrastructureRows){$shape=@($infrastructureRow.identity).Count;if($infrastructureRow.pid-lt1-or$infrastructureRow.identity[0]-ne$infrastructureRow.pid-or$shape-lt9-or$shape-gt11-or$seenInfrastructure.ContainsKey([int]$infrastructureRow.pid)){throw 'Resource monitor admitted infrastructure identity evidence rejected'};$seenInfrastructure[[int]$infrastructureRow.pid]=$true};if((Get-Utf8StringSha256 $infrastructureJson)-cne$done.admitted_infrastructure_sha256){throw 'Resource monitor admitted infrastructure digest rejected'}",
    )
    source = replace_once(
        source,
        "admitted_descendant_identities=$rows[-1].admitted_descendant_identities;admitted_identities_sha256=$rows[-1].admitted_identities_sha256;max_canonical_processes",
        "admitted_descendant_identities=$rows[-1].admitted_descendant_identities;admitted_identities_sha256=$rows[-1].admitted_identities_sha256;admitted_infrastructure_identities=$rows[-1].admitted_infrastructure_identities;admitted_infrastructure_sha256=$rows[-1].admitted_infrastructure_sha256;max_canonical_processes",
    )
    source = replace_once(
        source,
        "maximum_gap_ms=750;subprocess_sites=16;canonical_token_sha256=$canonicalMonitorContract.token_sha256}",
        "maximum_gap_ms=750;subprocess_sites=16;canonical_token_sha256=$canonicalMonitorContract.token_sha256;readiness_self_test=$false}",
    )
    source = replace_once(
        source,
        "kind='READY';target_interval_ms=100",
        "kind='READY';readiness_self_test=$false;target_interval_ms=100",
    )
    sample_namespace_fields = (
        ";namespace_permission_denials=0;process_rows=2;namespace_exact_rows=1"
        ";namespace_not_required_infrastructure_rows=1"
        ";namespace_not_required_ancestry_rows=0"
        ";namespace_not_required_watcher_rows=0"
        ";admitted_infrastructure_identities=1"
        ";admitted_infrastructure_sha256=('b'*64)"
    )
    source = replace_count(
        source, "gap_ns=0}", "gap_ns=0" + sample_namespace_fields + "}", 2
    )
    source = replace_once(
        source,
        "gap_ns=100000000}",
        "gap_ns=100000000" + sample_namespace_fields + "}",
    )
    source = replace_once(
        source,
        "gap_ns=800000001}",
        "gap_ns=800000001" + sample_namespace_fields + "}",
    )

    retained_switch = r"""if($RetainedPredecessorSnapshotsSelfTest){
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock present before retained predecessor snapshot self-test'};$leaf=(Split-Path -Leaf $prefix)+'.';$existing=@(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if($existing.Count-ne0){throw 'Fresh v33 artifact namespace is not empty before retained predecessor snapshot self-test'};$auth=Get-AuthorizationState;$v30=Invoke-RetainedV30SnapshotVerifier 'isolated_nonconsuming_v30_preflight';$v31=Invoke-RetainedV31SnapshotVerifier 'isolated_nonconsuming_v31_preflight';$v32=Invoke-RetainedV32SnapshotVerifier 'isolated_nonconsuming_v32_preflight';$existingAfter=@(Get-ChildItem -LiteralPath (Split-Path -Parent $prefix) -Force|Where-Object{$_.Name.IndexOf($leaf,[StringComparison]::Ordinal)-eq0});if($existingAfter.Count-ne0-or(Test-Path -LiteralPath $claimFile)){throw 'Retained predecessor snapshot self-test created v33 evidence'};if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock appeared during retained predecessor snapshot self-test'}
    [Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v33.retained-predecessor-snapshots-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;v30=$v30;v31=$v31;v32=$v32;canonical_suite_executed=$false;shared_lock_used=$false;claim_created=$false;v33_artifacts_created=$false}|ConvertTo-Json -Depth 10 -Compress));return
}
"""
    source = replace_region(
        source,
        "if($RetainedPredecessorSnapshotsSelfTest){",
        "if($LogBridgeSelfTest){",
        retained_switch,
    )
    source = replace_once(
        source,
        "if($failure.evidence.status-cne'EXPECTED_UNVALIDATED_V28_V29_V30_V31_PREDECESSOR_CUSTODY'-or$failure.replay.status-cne'REPLAY_ERRORS_RECORDED'-or$failure.replay.Contains('evidence')-or$failure.v31_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$failure.predecessor_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$success.evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_V31_PREDECESSOR_CUSTODY'-or@($success.evidence.runtime.validated_pins).Count-ne61-or$success.replay.status-cne'REPLAYED'-or$success.replay.Contains('evidence')-or$success.replay.validated_pin_count-ne61-or$success.v31_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$success.predecessor_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$failureJson.Length-eq0-or$successJson.Length-eq0){throw 'Complete predecessor rejection promotion self-test rejected'}",
        "if($failure.evidence.status-cne'EXPECTED_UNVALIDATED_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'-or$failure.replay.status-cne'REPLAY_ERRORS_RECORDED'-or$failure.replay.Contains('evidence')-or$failure.v31_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$failure.v32_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$failure.predecessor_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$success.evidence.status-cne'VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY'-or@($success.evidence.runtime.validated_pins).Count-ne89-or$success.replay.status-cne'REPLAYED'-or$success.replay.Contains('evidence')-or$success.replay.validated_pin_count-ne89-or$success.v31_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$success.v32_failure_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$success.predecessor_evidence_sha256-cnotmatch'^[0-9a-f]{64}$'-or$failureJson.Length-eq0-or$successJson.Length-eq0){throw 'Complete predecessor rejection promotion self-test rejected'}",
    )
    source = replace_once(
        source,
        "early_failure=[ordered]@{evidence_status=$failure.evidence.status;replay_status=$failure.replay.status;v31_failure_evidence_sha256=$failure.v31_failure_evidence_sha256;predecessor_evidence_sha256=$failure.predecessor_evidence_sha256;json_serialized=$true};successful_replay=[ordered]@{evidence_status=$success.evidence.status;replay_status=$success.replay.status;validated_pin_count=$success.replay.validated_pin_count;v31_failure_evidence_sha256=$success.v31_failure_evidence_sha256;predecessor_evidence_sha256=$success.predecessor_evidence_sha256;json_serialized=$true}",
        "early_failure=[ordered]@{evidence_status=$failure.evidence.status;replay_status=$failure.replay.status;v31_failure_evidence_sha256=$failure.v31_failure_evidence_sha256;v32_failure_evidence_sha256=$failure.v32_failure_evidence_sha256;predecessor_evidence_sha256=$failure.predecessor_evidence_sha256;json_serialized=$true};successful_replay=[ordered]@{evidence_status=$success.evidence.status;replay_status=$success.replay.status;validated_pin_count=$success.replay.validated_pin_count;v31_failure_evidence_sha256=$success.v31_failure_evidence_sha256;v32_failure_evidence_sha256=$success.v32_failure_evidence_sha256;predecessor_evidence_sha256=$success.predecessor_evidence_sha256;json_serialized=$true}",
    )
    source = replace_once(
        source,
        "if(@($predecessorModel.runtime.validated_pins).Count-ne61-or@($predecessorModel.contract.v30.sources.PSObject.Properties).Count-ne4",
        "if(@($predecessorModel.runtime.validated_pins).Count-ne89-or@($predecessorModel.v32_failure_evidence.runtime.validated_pins).Count-ne28-or@($predecessorModel.contract.v30.sources.PSObject.Properties).Count-ne4",
    )
    source = replace_once(
        source,
        "predecessor_evidence_model='61_EXACT_IDENTITY_PINS_V28_V29_V30_V31_PLUS_QUADRUPLE_PASS_ABSENCE_VALIDATED'",
        "predecessor_evidence_model='89_EXACT_IDENTITY_PINS_V28_V29_V30_V31_V32_PLUS_QUINTUPLE_PASS_ABSENCE_VALIDATED'",
    )
    source = replace_count(
        source,
        "'planora.muni-v33.complete-v28-v29-v30-v31-predecessor-evidence.v1'",
        "'planora.muni-v33.complete-v28-v29-v30-v31-v32-predecessor-evidence.v1'",
        2,
    )
    source = replace_once(
        source,
        "'complete-v28-v29-v30-v31-predecessor-evidence.v1'",
        "'complete-v28-v29-v30-v31-v32-predecessor-evidence.v1'",
    )
    source = replace_once(
        source,
        "'Write-FinalPassSeal'",
        "'Write-FinalPassSeal','ResourceMonitorReadinessSelfTest','namespace_not_required_infrastructure_rows','namespace identity permission denied for relevant process','Get-ValidatedV32FailureEvidence','Invoke-RetainedV32SnapshotVerifier'",
    )

    source = replace_once(
        source,
        "$retainedV31FinalReplay=$null;$retainedV31RejectionReplay=$null;$v31FailureEvidenceHash='';",
        "$retainedV31FinalReplay=$null;$retainedV31RejectionReplay=$null;$retainedV32SnapshotCustodyHash='';$retainedV32SnapshotTerminalCustodyHash='';$retainedV32SnapshotCustodyPin=$null;$retainedV32SnapshotTerminalCustodyPin=$null;$retainedV32FinalReplay=$null;$retainedV32RejectionReplay=$null;$v31FailureEvidenceHash='';$v32FailureEvidenceHash='';",
    )
    source = replace_once(
        source,
        "$v31FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v31_failure_evidence|ConvertTo-Json -Depth 40 -Compress));$predecessorPins=@();",
        "$v31FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v31_failure_evidence|ConvertTo-Json -Depth 40 -Compress));$v32FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v32_failure_evidence|ConvertTo-Json -Depth 40 -Compress));$predecessorPins=@();",
    )
    source = replace_once(
        source,
        "$reserved=@($retainedV30SnapshotCustodyFile,$retainedV30SnapshotTerminalCustodyFile,$retainedV31SnapshotCustodyFile,$retainedV31SnapshotTerminalCustodyFile,",
        "$reserved=@($retainedV30SnapshotCustodyFile,$retainedV30SnapshotTerminalCustodyFile,$retainedV31SnapshotCustodyFile,$retainedV31SnapshotTerminalCustodyFile,$retainedV32SnapshotCustodyFile,$retainedV32SnapshotTerminalCustodyFile,",
    )
    source = replace_once(
        source,
        "$predecessorPins=@(Get-CompletePredecessorPinArray $predecessorEvidence);if($predecessorPins.Count-ne61){throw 'Combined predecessor pin cardinality rejected'}",
        "$predecessorPins=@(Get-CompletePredecessorPinArray $predecessorEvidence);if($predecessorPins.Count-ne89){throw 'Complete predecessor pin cardinality rejected'}",
    )
    source = replace_once(
        source,
        "$predecessorEvidence=Get-ValidatedCompletePredecessorEvidence $true;$staleArchivePin=$predecessorEvidence.contract.v28.archive;$predecessorPins=@(Get-CompletePredecessorPinArray $predecessorEvidence);if($predecessorPins.Count-ne89){throw 'Complete predecessor pin cardinality rejected'}\n    $predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 40 -Compress));$v31FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v31_failure_evidence|ConvertTo-Json -Depth 40 -Compress))",
        "$predecessorEvidence=Get-ValidatedCompletePredecessorEvidence $true;$staleArchivePin=$predecessorEvidence.contract.v28.archive;$predecessorPins=@(Get-CompletePredecessorPinArray $predecessorEvidence);if($predecessorPins.Count-ne89){throw 'Complete predecessor pin cardinality rejected'}\n    $predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 40 -Compress));$v31FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v31_failure_evidence|ConvertTo-Json -Depth 40 -Compress));$v32FailureEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence.v32_failure_evidence|ConvertTo-Json -Depth 40 -Compress))",
    )
    source = replace_once(
        source,
        "v31_failure_evidence=$predecessorEvidence.v31_failure_evidence;v31_failure_evidence_sha256=$v31FailureEvidenceHash;archive_identity_replay=",
        "v31_failure_evidence=$predecessorEvidence.v31_failure_evidence;v31_failure_evidence_sha256=$v31FailureEvidenceHash;v32_failure_evidence=$predecessorEvidence.v32_failure_evidence;v32_failure_evidence_sha256=$v32FailureEvidenceHash;archive_identity_replay=",
    )
    source = replace_once(
        source,
        "$retainedV31SnapshotCustodyHash=Get-Sha256 $retainedV31SnapshotCustodyFile;$retainedV31SnapshotCustodyPin=Get-LocalEvidencePin $retainedV31SnapshotCustodyFile\n    Write-NewUtf8 $lockEvidenceFile",
        "$retainedV31SnapshotCustodyHash=Get-Sha256 $retainedV31SnapshotCustodyFile;$retainedV31SnapshotCustodyPin=Get-LocalEvidencePin $retainedV31SnapshotCustodyFile\n    $retainedV32Initial=Invoke-RetainedV32SnapshotVerifier 'initial_after_v33_lock';$retainedV32SnapshotCustody=[ordered]@{schema='planora.muni-v33.retained-v32-snapshot-custody.v1';status='EXACT_RETAINED_V32_SNAPSHOT_VALIDATED_WHILE_V33_LOCK_HELD';run_id=$runId;replay=$retainedV32Initial;source_inventory_pin=$predecessorEvidence.v32_failure_evidence.contract.snapshot.inventory;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $retainedV32SnapshotCustodyFile ($retainedV32SnapshotCustody|ConvertTo-Json -Depth 12);$retainedV32SnapshotCustodyHash=Get-Sha256 $retainedV32SnapshotCustodyFile;$retainedV32SnapshotCustodyPin=Get-LocalEvidencePin $retainedV32SnapshotCustodyFile\n    Write-NewUtf8 $lockEvidenceFile",
    )
    source = replace_once(
        source,
        "retained_v31_snapshot_custody_sha256=$retainedV31SnapshotCustodyHash;retained_v31_snapshot_custody_pin=$retainedV31SnapshotCustodyPin;stale_archive_pin=",
        "retained_v31_snapshot_custody_sha256=$retainedV31SnapshotCustodyHash;retained_v31_snapshot_custody_pin=$retainedV31SnapshotCustodyPin;retained_v32_snapshot_custody_sha256=$retainedV32SnapshotCustodyHash;retained_v32_snapshot_custody_pin=$retainedV32SnapshotCustodyPin;stale_archive_pin=",
    )
    source = replace_once(
        source,
        "$plan['v31_failure_evidence_sha256']=$v31FailureEvidenceHash;",
        "$plan['v31_failure_evidence_sha256']=$v31FailureEvidenceHash;$plan['v32_failure_evidence']=$predecessorEvidence.v32_failure_evidence;$plan['v32_failure_evidence_sha256']=$v32FailureEvidenceHash;",
    )
    source = replace_once(
        source,
        "$plan['retained_v31_snapshot_custody']=[ordered]@{sha256=$retainedV31SnapshotCustodyHash;pin=$retainedV31SnapshotCustodyPin};$plan['new_lock_verification']",
        "$plan['retained_v31_snapshot_custody']=[ordered]@{sha256=$retainedV31SnapshotCustodyHash;pin=$retainedV31SnapshotCustodyPin};$plan['retained_v32_snapshot_custody']=[ordered]@{sha256=$retainedV32SnapshotCustodyHash;pin=$retainedV32SnapshotCustodyPin};$plan['new_lock_verification']",
    )
    source = replace_once(
        source,
        "@($runnerPath,$retainedV30SnapshotCustodyFile,$retainedV31SnapshotCustodyFile,$authorizationPath,",
        "@($runnerPath,$retainedV30SnapshotCustodyFile,$retainedV31SnapshotCustodyFile,$retainedV32SnapshotCustodyFile,$authorizationPath,",
    )
    source = replace_once(
        source,
        "$retainedV31SnapshotTerminalCustodyHash=Get-Sha256 $retainedV31SnapshotTerminalCustodyFile;$retainedV31SnapshotTerminalCustodyPin=Get-LocalEvidencePin $retainedV31SnapshotTerminalCustodyFile\n    $protectedPins=",
        "$retainedV31SnapshotTerminalCustodyHash=Get-Sha256 $retainedV31SnapshotTerminalCustodyFile;$retainedV31SnapshotTerminalCustodyPin=Get-LocalEvidencePin $retainedV31SnapshotTerminalCustodyFile\n    $retainedV32Terminal=Invoke-RetainedV32SnapshotVerifier 'post_cleanup_while_v33_lock_held_before_final_census';$retainedV32SnapshotTerminalCustody=[ordered]@{schema='planora.muni-v33.retained-v32-snapshot-terminal-custody.v1';status='EXACT_RETAINED_V32_SNAPSHOT_REPLAYED_AFTER_V33_CLEANUP_WHILE_LOCK_HELD';run_id=$runId;initial_custody_sha256=$retainedV32SnapshotCustodyHash;replay=$retainedV32Terminal;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $retainedV32SnapshotTerminalCustodyFile ($retainedV32SnapshotTerminalCustody|ConvertTo-Json -Depth 12);$retainedV32SnapshotTerminalCustodyHash=Get-Sha256 $retainedV32SnapshotTerminalCustodyFile;$retainedV32SnapshotTerminalCustodyPin=Get-LocalEvidencePin $retainedV32SnapshotTerminalCustodyFile\n    $protectedPins=",
    )
    source = replace_once(
        source,
        "$retainedV30SnapshotTerminalCustodyPin,$retainedV31SnapshotTerminalCustodyPin)",
        "$retainedV30SnapshotTerminalCustodyPin,$retainedV31SnapshotTerminalCustodyPin,$retainedV32SnapshotTerminalCustodyPin)",
    )
    source = replace_once(
        source,
        "$receipt['v31_failure_evidence_sha256']=$v31FailureEvidenceHash;",
        "$receipt['v31_failure_evidence_sha256']=$v31FailureEvidenceHash;$receipt['v32_failure_evidence']=$predecessorEvidence.v32_failure_evidence;$receipt['v32_failure_evidence_sha256']=$v32FailureEvidenceHash;",
    )
    source = replace_once(
        source,
        "$receipt['retained_v31_snapshot_terminal_custody_pin']=$retainedV31SnapshotTerminalCustodyPin;$receipt['new_lock_verification']",
        "$receipt['retained_v31_snapshot_terminal_custody_pin']=$retainedV31SnapshotTerminalCustodyPin;$receipt['retained_v32_snapshot_custody_sha256']=$retainedV32SnapshotCustodyHash;$receipt['retained_v32_snapshot_custody_pin']=$retainedV32SnapshotCustodyPin;$receipt['retained_v32_snapshot_terminal_custody_sha256']=$retainedV32SnapshotTerminalCustodyHash;$receipt['retained_v32_snapshot_terminal_custody_pin']=$retainedV32SnapshotTerminalCustodyPin;$receipt['new_lock_verification']",
    )
    source = replace_once(
        source,
        "$retainedV30FinalReplay=Invoke-RetainedV30SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$retainedV31FinalReplay=Invoke-RetainedV31SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$terminalArchiveGuard=",
        "$retainedV30FinalReplay=Invoke-RetainedV30SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$retainedV31FinalReplay=Invoke-RetainedV31SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$retainedV32FinalReplay=Invoke-RetainedV32SnapshotVerifier 'terminal_immediately_before_archive_guard_and_final_seal';$terminalArchiveGuard=",
    )
    source = replace_once(
        source,
        "retained_v31_snapshot_terminal_custody_sha256=$retainedV31SnapshotTerminalCustodyHash;retained_v31_snapshot_final_replay=$retainedV31FinalReplay;stale_lock_archive_pin=",
        "retained_v31_snapshot_terminal_custody_sha256=$retainedV31SnapshotTerminalCustodyHash;retained_v31_snapshot_final_replay=$retainedV31FinalReplay;retained_v32_snapshot_custody_sha256=$retainedV32SnapshotCustodyHash;retained_v32_snapshot_terminal_custody_sha256=$retainedV32SnapshotTerminalCustodyHash;retained_v32_snapshot_final_replay=$retainedV32FinalReplay;stale_lock_archive_pin=",
    )
    source = replace_once(
        source,
        "$retainedV30RejectionReplay=Get-NonThrowingRetainedV30SnapshotReplay 'rejection_before_optional_v33_lock_release';$retainedV31RejectionReplay=Get-NonThrowingRetainedV31SnapshotReplay 'rejection_before_optional_v33_lock_release';$predecessorRejectionReplay=",
        "$retainedV30RejectionReplay=Get-NonThrowingRetainedV30SnapshotReplay 'rejection_before_optional_v33_lock_release';$retainedV31RejectionReplay=Get-NonThrowingRetainedV31SnapshotReplay 'rejection_before_optional_v33_lock_release';$retainedV32RejectionReplay=Get-NonThrowingRetainedV32SnapshotReplay 'rejection_before_optional_v33_lock_release';$predecessorRejectionReplay=",
    )
    source = replace_once(
        source,
        "$v31FailureEvidenceHash=$resolvedPredecessorRejection.v31_failure_evidence_sha256;$predecessorEvidenceHash=",
        "$v31FailureEvidenceHash=$resolvedPredecessorRejection.v31_failure_evidence_sha256;$v32FailureEvidenceHash=$resolvedPredecessorRejection.v32_failure_evidence_sha256;$predecessorEvidenceHash=",
    )
    source = replace_count(
        source,
        "retained_v31_final_replay_completed=($null-ne$retainedV31FinalReplay)",
        "retained_v31_final_replay_completed=($null-ne$retainedV31FinalReplay);retained_v32_initial_custody_published=($null-ne$retainedV32SnapshotCustodyPin);retained_v32_post_cleanup_custody_published=($null-ne$retainedV32SnapshotTerminalCustodyPin);retained_v32_final_replay_completed=($null-ne$retainedV32FinalReplay)",
        2,
    )
    source = replace_count(
        source,
        "v31_failure_evidence=$predecessorEvidence.v31_failure_evidence;v31_failure_evidence_sha256=$v31FailureEvidenceHash;predecessor_custody_sha256=$predecessorCustodyHash;retained_v30_snapshot_custody_sha256=",
        "v31_failure_evidence=$predecessorEvidence.v31_failure_evidence;v31_failure_evidence_sha256=$v31FailureEvidenceHash;v32_failure_evidence=$predecessorEvidence.v32_failure_evidence;v32_failure_evidence_sha256=$v32FailureEvidenceHash;predecessor_custody_sha256=$predecessorCustodyHash;retained_v30_snapshot_custody_sha256=",
        3,
    )
    source = replace_count(
        source,
        "retained_v31_snapshot_rejection_replay=$retainedV31RejectionReplay;stale_lock_archive_pin=",
        "retained_v31_snapshot_rejection_replay=$retainedV31RejectionReplay;retained_v32_snapshot_custody_sha256=$retainedV32SnapshotCustodyHash;retained_v32_snapshot_custody_pin=$retainedV32SnapshotCustodyPin;retained_v32_snapshot_terminal_custody_sha256=$retainedV32SnapshotTerminalCustodyHash;retained_v32_snapshot_terminal_custody_pin=$retainedV32SnapshotTerminalCustodyPin;retained_v32_snapshot_final_replay=$retainedV32FinalReplay;retained_v32_snapshot_rejection_replay=$retainedV32RejectionReplay;stale_lock_archive_pin=",
        2,
    )

    source = replace_once(
        source,
        "retained_predecessor_snapshots_contract=[ordered]@{v30_root=$predecessor.v30.snapshot.root;v31_root=$v31Failure.snapshot.root;v30_inventory=$predecessor.v30.snapshot.inventory;v31_inventory=$v31Failure.snapshot.inventory;isolated_switch='RetainedPredecessorSnapshotsSelfTest';read_only_identity_replay=$true;initial_post_cleanup_rejection_and_final_replay_required=$true;v33_cleanup_must_not_target_v30_or_v31=$true}",
        "retained_predecessor_snapshots_contract=[ordered]@{v30_root=$predecessor.v30.snapshot.root;v31_root=$v31Failure.snapshot.root;v32_root=$v32Failure.snapshot.root;v30_inventory=$predecessor.v30.snapshot.inventory;v31_inventory=$v31Failure.snapshot.inventory;v32_inventory=$v32Failure.snapshot.inventory;isolated_switch='RetainedPredecessorSnapshotsSelfTest';read_only_identity_replay=$true;initial_post_cleanup_rejection_and_final_replay_required=$true;v33_cleanup_must_not_target_v30_v31_or_v32=$true}",
    )
    source = (
        source.replace(
            "complete_v28_v29_v30_v31_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true",
            "complete_v28_v29_v30_v31_v32_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true",
        )
        .replace(
            "all_61_predecessor_file_ids_and_timestamps_authorized=$true",
            "all_89_predecessor_file_ids_and_timestamps_authorized=$true",
        )
        .replace(
            "v28_v29_v30_v31_pass_absence_replayed_through_final_pass_seal_publication=$true",
            "v28_v29_v30_v31_v32_pass_absence_replayed_through_final_pass_seal_publication=$true",
        )
    )
    source = source.replace(
        "v31_failure_hash_nonempty_on_early_rejection=$true",
        "v31_and_v32_failure_hashes_nonempty_on_early_rejection=$true",
    )

    if (
        source.count(
            "$canonicalLaunchAttempted=$true;$executionHandle=Start-SafeLoggedProcess"
        )
        != 1
    ):
        raise RuntimeError("v33 canonical launch site cardinality rejected")
    production_readiness_mode = (
        "canonical_token_sha256=$canonicalMonitorContract.token_sha256;"
        "readiness_self_test=$false}"
    )
    if source.count(production_readiness_mode) != 1:
        raise RuntimeError(
            "v33 production resource readiness mode cardinality rejected"
        )
    if source.count("readiness_self_test=$true") != 1:
        raise RuntimeError("v33 self-test resource readiness mode cardinality rejected")
    if source.count("Get-ValidatedV32FailureEvidence") < 2:
        raise RuntimeError("v33 v32 failure custody integration missing")
    if source.count("Invoke-RetainedV32SnapshotVerifier") < 6:
        raise RuntimeError("v33 retained v32 replay integration missing")
    if "VALIDATED_EXACT_V28_V29_V30_V31_V32_PREDECESSOR_CUSTODY" not in source:
        raise RuntimeError("v33 complete predecessor status missing")
    if "complete_v28_v29_v30_v31_v32_predecessor_pin_count']=89" not in source:
        raise RuntimeError("v33 authorization predecessor count missing")
    if "prefix='/tmp/planora-muni-v33-canonical-tests-'" not in source:
        raise RuntimeError("v33 cleanup prefix rejected")
    cleanup_match = re.search(r"(?s)\$cleanupSource = @'\r?\n(.*?)\r?\n'@", source)
    if not cleanup_match:
        raise RuntimeError("v33 cleanup source missing")
    cleanup_region = cleanup_match.group(1)
    for retained in (
        "/tmp/planora-muni-v30-canonical-tests-",
        "/tmp/planora-muni-v31-canonical-tests-",
        "/tmp/planora-muni-v32-canonical-tests-",
    ):
        if retained in cleanup_region:
            raise RuntimeError(f"v33 cleanup can target retained root: {retained}")
    required = (
        "namespace identity permission denied for relevant process",
        "NOT_REQUIRED_TRUSTED_INFRASTRUCTURE",
        "namespace_state_accounting_required",
        "ResourceMonitorReadinessSelfTest",
        "v32_namespace_failure_exact_20_artifacts_and_13_absences_bound",
        "retained_v32_snapshot_initial_terminal_rejection_and_final_replay_bound",
        "predecessorPins.Count-ne89",
        "readiness_self_test=$false",
        "readiness_self_test=$true",
        "log prior prefix digest changed",
        "log held-handle prefix replay changed",
        "Invoke-StableLogReaderStateRegression",
        "restrictive_read_guard_persistent_identity_monotonic_prefix_digest",
    )
    for marker in required:
        if marker not in source:
            raise RuntimeError(f"v33 required marker missing: {marker}")
    return source


def main() -> None:
    builder = Path(__file__)
    builder_size = builder.stat().st_size
    builder_hash = sha256(builder)
    tests_size = V33_TESTS.stat().st_size
    tests_hash = sha256(V33_TESTS)
    runner = render_runner(builder_size, builder_hash, tests_size, tests_hash)
    V33_RUNNER.write_text(runner, encoding="utf-8", newline="\n")

    powershell = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(V33_RUNNER),
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
        authorization["schema"] != "planora.itc2019.canonical-test-authorization.v13"
        or authorization["test_id"] != RUN_ID
        or authorization["runner"]["sha256"] != sha256(V33_RUNNER)
        or authorization["evidence_contract"][
            "complete_v28_v29_v30_v31_v32_predecessor_pin_count"
        ]
        != 89
        or authorization["heavy_gate"]["nonconsuming_live_readiness_switch"]
        != "ResourceMonitorReadinessSelfTest"
    ):
        raise RuntimeError("v33 authorization semantics rejected")
    V33_AUTH.write_text(
        json.dumps(authorization, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": "MUNI_V33_SUCCESSOR_GENERATED_STATIC_ONLY",
                "run_id": RUN_ID,
                "runner": str(V33_RUNNER.relative_to(REPO)).replace("\\", "/"),
                "runner_sha256": sha256(V33_RUNNER),
                "authorization": str(V33_AUTH.relative_to(REPO)).replace("\\", "/"),
                "authorization_sha256": sha256(V33_AUTH),
                "predecessor_pins": 89,
                "wsl_executed": False,
                "canonical_suite_executed": False,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
