param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$parentBuilderPath = Join-Path $repositoryRoot "scripts\build_agh_v16_chain.ps1"
$parentRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v16"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v17"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$expectedParentBuilderSha256 = "c2c90624d066f23fb811d9009a5c44d075febe34bd04155756405bb03162eb08"
$expectedParentFreezeSha256 = "f1dd6fc04b195c0b679ee466620448119f315b9658bfb0484c4c8d1ad1378c3e"
$expectedParentArtifacts = [ordered]@{
    "agent-aghfal17-native-v16-bootstrap.py" = @{ size = 12889; sha256 = "efb5ca798bfbc999b654b157d8aad9136c6f7145b33ddb0b4a2c57974b2cc3e3" }
    "agent-aghfal17-native-v16-generic-validator.py" = @{ size = 6053; sha256 = "aaaf84d8d68ca869ad13c8522e417fecc379c4436f958f7b7f047a450f63d3fd" }
    "agent-aghfal17-native-v16-invocations.json" = @{ size = 18685; sha256 = "c809486e73e26aa6a52cfe4703fddc2f216a17947a2882f24649ab430aabe8df" }
    "agent-aghfal17-native-v16-launcher.sh" = @{ size = 10942; sha256 = "e4362d9c6666570dd56507cea918a1349464d75281c8e69d8ac1b51557278ee2" }
    "agent-aghfal17-native-v16-minimal-tcb.sha256" = @{ size = 5119; sha256 = "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea" }
    "agent-aghfal17-native-v16-outer-controller.py" = @{ size = 48193; sha256 = "0178d2c04e2e0d1e82bb11defa965d947ea5527e7270d838e32a9ef6d385a558" }
    "agent-aghfal17-native-v16-review-freeze.json" = @{ size = 41824; sha256 = $expectedParentFreezeSha256 }
    "agent-aghfal17-native-v16-runner.py" = @{ size = 71673; sha256 = "eba2e08b04a05a6a36b61c9402df8b73fe75ca5b3e9f9d4a372e15f69d4b813e" }
    "agent-aghfal17-native-v16-stdlib.sha256" = @{ size = 67004; sha256 = "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327" }
    "agent-aghfal17-native-v16-supervisor.py" = @{ size = 149387; sha256 = "3c7cc1cbbdb6ccc2b24535d28d1db18c599bab5b5cea87e11412986a1ec961db" }
    "agent-aghfal17-native-v16-tests.py" = @{ size = 41658; sha256 = "6b931292d4b65e00461202c57157be0bf8805403cb6de90f613ce79d730fea9f" }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-BytesSha256([byte[]]$Raw) {
    $digest = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([Convert]::ToHexString($digest.ComputeHash($Raw))).ToLowerInvariant()
    }
    finally {
        $digest.Dispose()
    }
}

function Get-TextSha256([string]$Text) {
    return Get-BytesSha256 $utf8NoBom.GetBytes($Text)
}

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, $utf8NoBom)
}

function Write-Utf8([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Replace-Required(
    [string]$Text,
    [string]$Old,
    [string]$New,
    [string]$Label
) {
    if (-not $Text.Contains($Old)) {
        throw "Expected token was absent while generating ${Label}: $Old"
    }
    return $Text.Replace($Old, $New)
}

function Replace-Section(
    [string]$Text,
    [string]$StartMarker,
    [string]$EndMarker,
    [string]$Replacement,
    [string]$Label
) {
    $start = $Text.IndexOf($StartMarker, [StringComparison]::Ordinal)
    if ($start -lt 0) {
        throw "Start marker was absent while generating ${Label}: $StartMarker"
    }
    $end = $Text.IndexOf($EndMarker, $start, [StringComparison]::Ordinal)
    if ($end -lt 0) {
        throw "End marker was absent while generating ${Label}: $EndMarker"
    }
    return $Text.Substring(0, $start) + $Replacement + $Text.Substring($end)
}

function Convert-Version([string]$Text) {
    $Text = $Text.Replace("NativeV16", "NativeV17")
    $Text = $Text.Replace("NATIVE_V16", "NATIVE_V17")
    $Text = $Text.Replace("native_v16", "native_v17")
    $Text = $Text.Replace("native-v16", "native-v17")
    $Text = $Text.Replace("aghfal17-v16", "aghfal17-v17")
    $Text = $Text.Replace("AGH-FAL17 v16", "AGH-FAL17 v17")
    $Text = $Text.Replace("agh-v16", "agh-v17")
    $Text = $Text.Replace("agh_v16", "agh_v17")
    return $Text
}

function Get-CanonicalArgvSha256([object[]]$Argv) {
    $values = @($Argv | ForEach-Object { [string]$_ })
    foreach ($value in $values) {
        if ($value.Contains([char]0)) {
            throw "Canonical argv contains NUL"
        }
    }
    return Get-BytesSha256 $utf8NoBom.GetBytes([string]::Join([char]0, $values))
}

function Get-DirectorySnapshot([string]$Root) {
    $snapshot = [ordered]@{}
    Get-ChildItem -LiteralPath $Root -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            $relative = [System.IO.Path]::GetRelativePath($Root, $_.FullName).Replace("\", "/")
            $snapshot[$relative] = [ordered]@{
                size_bytes = $_.Length
                sha256 = Get-Sha256 $_.FullName
            }
        }
    return $snapshot
}

function Get-PreservedSnapshot() {
    $snapshot = [ordered]@{}
    foreach ($version in 12..16) {
        $builder = Join-Path $repositoryRoot "scripts\build_agh_v${version}_chain.ps1"
        $chain = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v${version}"
        if (-not (Test-Path -LiteralPath $builder) -or -not (Test-Path -LiteralPath $chain)) {
            throw "Preserved AGH v${version} evidence is missing"
        }
        $builderItem = Get-Item -LiteralPath $builder
        $snapshot["builder_v${version}"] = [ordered]@{
            size_bytes = $builderItem.Length
            sha256 = Get-Sha256 $builder
        }
        $snapshot["chain_v${version}"] = Get-DirectorySnapshot $chain
    }
    return $snapshot
}

function Assert-SnapshotsEqual([hashtable]$Before, [hashtable]$After, [string]$Label) {
    if (
        ($Before | ConvertTo-Json -Depth 12 -Compress) -cne
        ($After | ConvertTo-Json -Depth 12 -Compress)
    ) {
        throw "$Label changed while building AGH v17"
    }
}

function Write-Transformed(
    [string]$SourceName,
    [string]$DestinationName,
    [scriptblock]$Transform
) {
    $source = Join-Path $parentRoot $SourceName
    $destination = Join-Path $targetRoot $DestinationName
    $text = Convert-Version (Read-Utf8 $source)
    $text = & $Transform $text
    Write-Utf8 $destination $text
    return $destination
}

if (-not (Test-Path -LiteralPath $parentBuilderPath)) {
    throw "AGH v16 builder evidence is missing"
}
if ((Get-Sha256 $parentBuilderPath) -ne $expectedParentBuilderSha256) {
    throw "AGH v16 builder evidence drifted"
}
if (-not (Test-Path -LiteralPath $parentRoot)) {
    throw "AGH v16 preserved chain is missing"
}
foreach ($entry in $expectedParentArtifacts.GetEnumerator()) {
    $path = Join-Path $parentRoot $entry.Key
    if (
        -not (Test-Path -LiteralPath $path) -or
        (Get-Item -LiteralPath $path).Length -ne [long]$entry.Value.size -or
        (Get-Sha256 $path) -ne [string]$entry.Value.sha256
    ) {
        throw "AGH v16 preserved artifact drifted: $($entry.Key)"
    }
}

$preservedBefore = Get-PreservedSnapshot
$preservedSnapshotText = $preservedBefore | ConvertTo-Json -Depth 12 -Compress
$preservedSnapshotSha256 = Get-TextSha256 $preservedSnapshotText
$preservedFileCount = 0
foreach ($version in 12..16) {
    $preservedFileCount += 1
    $preservedFileCount += @($preservedBefore["chain_v${version}"].Keys).Count
}

if (-not (Test-Path -LiteralPath $targetRoot)) {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}
$existing = @(Get-ChildItem -LiteralPath $targetRoot -File -Force)
if ($existing.Count -gt 0 -and -not $Force) {
    throw "Refusing to overwrite the AGH v17 chain without -Force"
}
if ($Force) {
    foreach ($file in $existing) {
        Remove-Item -LiteralPath $file.FullName
    }
}

$minimalName = "agent-aghfal17-native-v17-minimal-tcb.sha256"
$stdlibName = "agent-aghfal17-native-v17-stdlib.sha256"
$minimalPath = Join-Path $targetRoot $minimalName
$stdlibPath = Join-Path $targetRoot $stdlibName
[System.IO.File]::WriteAllBytes(
    $minimalPath,
    [System.IO.File]::ReadAllBytes((Join-Path $parentRoot "agent-aghfal17-native-v16-minimal-tcb.sha256"))
)
[System.IO.File]::WriteAllBytes(
    $stdlibPath,
    [System.IO.File]::ReadAllBytes((Join-Path $parentRoot "agent-aghfal17-native-v16-stdlib.sha256"))
)

$genericPath = Write-Transformed `
    "agent-aghfal17-native-v16-generic-validator.py" `
    "agent-aghfal17-native-v17-generic-validator.py" `
    { param($text) return $text }
$genericHash = Get-Sha256 $genericPath

$runnerPath = Write-Transformed `
    "agent-aghfal17-native-v16-runner.py" `
    "agent-aghfal17-native-v17-runner.py" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v16-generic-validator.py"].sha256 `
            $genericHash `
            "runner generic-validator pin"
    }
$runnerHash = Get-Sha256 $runnerPath

$supervisorPath = Write-Transformed `
    "agent-aghfal17-native-v16-supervisor.py" `
    "agent-aghfal17-native-v17-supervisor.py" `
    {
        param($text)
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v16-runner.py"].sha256 `
            $runnerHash `
            "supervisor runner pin"
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v16-generic-validator.py"].sha256 `
            $genericHash `
            "supervisor generic-validator pin"
        return $text
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherPath = Write-Transformed `
    "agent-aghfal17-native-v16-launcher.sh" `
    "agent-aghfal17-native-v17-launcher.sh" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v16-supervisor.py"].sha256 `
            $supervisorHash `
            "launcher supervisor pin"
    }
$launcherHash = Get-Sha256 $launcherPath

$bootstrapPath = Write-Transformed `
    "agent-aghfal17-native-v16-bootstrap.py" `
    "agent-aghfal17-native-v17-bootstrap.py" `
    { param($text) return $text }
$bootstrapHash = Get-Sha256 $bootstrapPath

$outerPath = Write-Transformed `
    "agent-aghfal17-native-v16-outer-controller.py" `
    "agent-aghfal17-native-v17-outer-controller.py" `
    {
        param($text)
        $statusValues = @'
def _status_values(pid: int) -> dict[str, int]:
    values: dict[str, int] = {}
    raw = (Path("/proc") / str(pid) / "status").read_text(encoding="ascii")
    tracked = frozenset(("VmRSS", "VmSwap"))
    for line in raw.splitlines():
        match = re.match(r"^\s*(VmRSS|VmSwap)(?=\s|:|$)", line)
        if match is None:
            continue
        tracked_key = match.group(1)
        key, separator, value = line.partition(":")
        if not separator or key != tracked_key:
            raise ProcInspectionError(
                f"proc status {tracked_key} key syntax malformed: {pid}"
            )
        if tracked_key not in tracked:
            raise ProcInspectionError(f"proc status tracked key rejected: {pid}")
        if tracked_key in values:
            raise ProcInspectionError(
                f"proc status duplicate {tracked_key}: {pid}"
            )
        tokens = value.strip().split()
        if len(tokens) != 2 or tokens[1] != "kB":
            raise ProcInspectionError(
                f"proc status {tracked_key} malformed: {pid}"
            )
        try:
            parsed = int(tokens[0])
        except ValueError as exc:
            raise ProcInspectionError(
                f"proc status {tracked_key} malformed: {pid}"
            ) from exc
        if parsed < 0:
            raise ProcInspectionError(
                f"proc status {tracked_key} negative: {pid}"
            )
        values[tracked_key] = parsed
    return values


'@
        $text = Replace-Section $text `
            "def _status_values(" `
            "def pidfd_exit_confirmed(" `
            ($statusValues + "`n") `
            "v17 canonical tracked status syntax"

        $ambiguityHelpers = @'
def _confirmed_exit_or_raise(pid: int, pidfd: int | None, reason: str) -> None:
    if pidfd is not None and pidfd_exit_confirmed(pidfd):
        return None
    raise ProcInspectionError(f"{reason}: {pid}")


def _generation_ambiguity_error(
    context: str,
    pid: int,
    expected: ProcessIdentity,
    observed: ProcessIdentity,
) -> ProcInspectionError:
    return ProcInspectionError(
        "admitted PID generation ambiguity:"
        f"{context}:{pid}:expected={expected.starttime}:observed={observed.starttime}"
    )


'@
        $text = Replace-Section $text `
            "def _confirmed_exit_or_raise(" `
            "def identity_bound_status(" `
            ($ambiguityHelpers + "`n") `
            "v17 ambiguity evidence helper"

        $identityBoundStatus = @'
def identity_bound_status(
    pid: int, expected: ProcessIdentity, pidfd: int | None = None
) -> dict[str, Any] | None:
    before = proc_record(pid)
    if before is None:
        return _confirmed_exit_or_raise(
            pid, pidfd, "proc stat absent without confirmed generation exit"
        )
    if before.identity != expected:
        raise _generation_ambiguity_error(
            "identity replay failed before status read",
            pid,
            expected,
            before.identity,
        )
    try:
        status = _status_values(pid)
    except OSError as exc:
        if isinstance(exc, (FileNotFoundError, ProcessLookupError)) or exc.errno in (
            errno.ENOENT,
            errno.ESRCH,
        ):
            return _confirmed_exit_or_raise(
                pid, pidfd, "proc status absent without confirmed generation exit"
            )
        raise ProcInspectionError(
            f"proc status read failed: {pid}:{int(exc.errno or errno.EIO)}"
        ) from exc
    after = proc_record(pid)
    if after is None:
        return _confirmed_exit_or_raise(
            pid, pidfd, "proc stat vanished without confirmed generation exit"
        )
    if after.identity != expected:
        raise _generation_ambiguity_error(
            "identity replay failed after status read",
            pid,
            expected,
            after.identity,
        )
    if "VmRSS" not in status:
        if after.state != "Z":
            raise ProcInspectionError(
                f"VmRSS unavailable for non-zombie admitted identity: {pid}:{after.state}"
            )
        if pidfd is None or not pidfd_exit_confirmed(pidfd):
            raise ProcInspectionError(
                f"zombie VmRSS unavailable without confirmed generation exit: {pid}"
            )
        return None
    return {
        "pid": pid,
        "identity": [pid, expected.starttime],
        "topology": [
            after.topology.ppid,
            after.topology.process_group,
            after.topology.session,
        ],
        "process_state": after.state,
        "vmrss_kib": int(status["VmRSS"]),
        "vmswap_kib": int(status.get("VmSwap", 0)),
    }


'@
        $text = Replace-Section $text `
            "def identity_bound_status(" `
            "def _open_pidfd(" `
            ($identityBoundStatus + "`n") `
            "v17 fail-closed identity accounting"

        $refresh = @'
def refresh_descendant_registry(
    *,
    wrapper_pid: int,
    root_pid: int,
    admitted: dict[int, AdmittedMember],
    baseline_direct_children: Mapping[int, ProcessIdentity],
    snapshot: Mapping[int, ProcessRecord] | None = None,
) -> dict[str, Any]:
    observed = dict(proc_snapshot() if snapshot is None else snapshot)
    added: list[int] = []
    changed = True
    while changed:
        changed = False
        live_parents: set[int] = set()
        for pid, member in admitted.items():
            record = observed.get(pid)
            if record is None:
                continue
            if record.identity != member.identity:
                raise _generation_ambiguity_error(
                    "descendant_refresh", pid, member.identity, record.identity
                )
            member.topology = record.topology
            live_parents.add(pid)
        for pid, record in sorted(observed.items()):
            if pid in admitted or pid == wrapper_pid:
                continue
            direct_root = pid == root_pid and record.topology.ppid == wrapper_pid
            descendant = record.topology.ppid in live_parents
            reparented_orphan = (
                record.topology.ppid == wrapper_pid
                and baseline_direct_children.get(pid) != record.identity
            )
            if not (direct_root or descendant or reparented_orphan):
                continue
            admit_member(admitted, pid, record)
            added.append(pid)
            changed = True
    return {
        "added_pids": added,
        "live_admitted_pids": sorted(
            pid for pid in admitted if observed.get(pid) is not None
        ),
        "generation_ambiguities": [],
    }


'@
        $text = Replace-Section $text `
            "def refresh_descendant_registry(" `
            "def accounting_sample(" `
            ($refresh + "`n") `
            "v17 descendant ambiguity propagation"

        $live = @'
def live_admitted(admitted: Mapping[int, AdmittedMember]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pid, member in sorted(admitted.items()):
        record = proc_record(pid)
        if record is None:
            continue
        if record.identity != member.identity:
            raise _generation_ambiguity_error(
                "live_admitted", pid, member.identity, record.identity
            )
        member.topology = record.topology
        rows.append(
            {
                "pid": pid,
                "identity": [pid, member.identity.starttime],
                "topology": [
                    record.topology.ppid,
                    record.topology.process_group,
                    record.topology.session,
                ],
            }
        )
    return rows


'@
        $text = Replace-Section $text `
            "def live_admitted(" `
            "def signal_admitted(" `
            ($live + "`n") `
            "v17 live-generation ambiguity propagation"

        $signal = @'
def signal_admitted(
    admitted: Mapping[int, AdmittedMember], signum: int
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "signal": int(signum),
        "signaled_pids": [],
        "vanished_pids": [],
        "identity_mismatch_pids": [],
        "proc_unknown_pids": [],
        "errors": [],
        "numeric_process_group_signal_sent": False,
    }
    if not hasattr(signal, "pidfd_send_signal"):
        result["errors"].append("pidfd_send_signal_unavailable")
        return result
    for pid, member in sorted(admitted.items(), reverse=True):
        try:
            current = proc_record(pid)
        except ProcInspectionError as exc:
            current = None
            result["proc_unknown_pids"].append(pid)
            result["errors"].append(f"proc_inspection:{pid}:{exc}")
        else:
            if current is None:
                result["vanished_pids"].append(pid)
                continue
            if current.identity != member.identity:
                result["identity_mismatch_pids"].append(pid)
                result["errors"].append(
                    str(
                        _generation_ambiguity_error(
                            "signal_admitted",
                            pid,
                            member.identity,
                            current.identity,
                        )
                    )
                )
                continue
            member.topology = current.topology
        if current is None and pid not in result["proc_unknown_pids"]:
            result["vanished_pids"].append(pid)
            continue
        try:
            signal.pidfd_send_signal(member.pidfd, signum, None, 0)
            result["signaled_pids"].append(pid)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                result["vanished_pids"].append(pid)
            else:
                result["errors"].append(
                    f"pidfd_send:{pid}:{int(exc.errno or errno.EIO)}"
                )
    return result


'@
        $text = Replace-Section $text `
            "def signal_admitted(" `
            "def _reap_known_children(" `
            ($signal + "`n") `
            "v17 no-wrong-generation signaling evidence"

        $reap = @'
def _reap_known_children(
    wrapper_pid: int,
    root: subprocess.Popen[bytes] | None,
    admitted: Mapping[int, AdmittedMember],
) -> list[dict[str, int]]:
    reaped: list[dict[str, int]] = []
    if root is not None:
        root.poll()
    for pid, member in sorted(admitted.items()):
        if root is not None and pid == root.pid:
            continue
        record = proc_record(pid)
        if record is None:
            continue
        if record.identity != member.identity:
            raise _generation_ambiguity_error(
                "reap_known_children", pid, member.identity, record.identity
            )
        if record.topology.ppid != wrapper_pid:
            continue
        member.topology = record.topology
        try:
            observed, status = os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, ProcessLookupError):
            continue
        except OSError as exc:
            if exc.errno in (errno.ECHILD, errno.ENOENT, errno.ESRCH):
                continue
            raise ProcInspectionError(
                f"waitpid failed: {pid}:{int(exc.errno or errno.EIO)}"
            ) from exc
        if observed:
            reaped.append({"pid": observed, "wait_status": status})
    return reaped


'@
        return Replace-Section $text `
            "def _reap_known_children(" `
            "def _append_cleanup_error(" `
            ($reap + "`n") `
            "v17 cleanup-generation ambiguity propagation"
    }
$outerHash = Get-Sha256 $outerPath

$testsPath = Write-Transformed `
    "agent-aghfal17-native-v16-tests.py" `
    "agent-aghfal17-native-v17-tests.py" `
    {
        param($text)
        $text = Replace-Required $text `
            "class V16FreezeReadinessTests" `
            "class V17FreezeReadinessTests" `
            "v17 readiness class identity"
        $text = Replace-Required $text `
            "def test_v16_is_review_ready_but_execution_unauthorized" `
            "def test_v17_is_review_ready_but_execution_unauthorized" `
            "v17 readiness test identity"
        $text = Replace-Required $text `
            "def test_no_v15_protocol_tokens_in_active_v16_runtime_artifacts" `
            "def test_no_v15_protocol_tokens_in_active_v17_runtime_artifacts" `
            "v17 inherited stale-token test identity"

        $staleMarker = @'


class V17FreezeReadinessTests(unittest.TestCase):
'@
        $staleTest = @'

    def test_no_v16_protocol_tokens_in_active_v17_runtime_artifacts(self) -> None:
        for path in (
            OUTER_PATH,
            BOOTSTRAP_PATH,
            SUPERVISOR_PATH,
            RUNNER_PATH,
            LAUNCHER_PATH,
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("native-v16", source, path.name)
            self.assertNotIn("NATIVE_V16", source, path.name)


class V17FreezeReadinessTests(unittest.TestCase):
'@
        $text = Replace-Required $text $staleMarker $staleTest "v17 stale runtime token regression"

        $predecessorMarker = @'
    def test_final_shared_core_and_focused_regression_are_frozen(self) -> None:
'@
        $predecessorTest = @'
    def test_v16_no_go_context_and_predecessor_snapshot_are_retained(self) -> None:
        context = self.freeze["predecessor_v16_static_review_no_go"]
        self.assertEqual(context["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(
            context["outer_controller_sha256"],
            "0178d2c04e2e0d1e82bb11defa965d947ea5527e7270d838e32a9ef6d385a558",
        )
        self.assertEqual(
            context["tests_sha256"],
            "6b931292d4b65e00461202c57157be0bf8805403cb6de90f613ce79d730fea9f",
        )
        preserved = self.freeze["preserved_predecessors"]
        self.assertEqual(preserved["versions"], [12, 13, 14, 15, 16])
        self.assertEqual(preserved["file_count"], 63)
        self.assertEqual(len(preserved["snapshot_sha256"]), 64)

    def test_final_shared_core_and_focused_regression_are_frozen(self) -> None:
'@
        $text = Replace-Required $text `
            $predecessorMarker `
            $predecessorTest `
            "v16 no-go and predecessor snapshot regression"

        $reviewerRegressions = @'
class V17IndependentReviewerRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = outer.ProcessIdentity(200)
        self.running = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "S"
        )
        self.zombie = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "Z"
        )
        self.reused = outer.ProcessRecord(
            outer.ProcessIdentity(900), outer.ProcessTopology(10, 20, 20), "S"
        )
        self.member = outer.AdmittedMember(
            identity=self.identity,
            pidfd=77,
            topology=self.running.topology,
        )

    def test_noncanonical_tracked_status_keys_are_explicitly_rejected(self) -> None:
        malformed = (
            " VmRSS: invalid kB\n",
            "VmRSS : invalid kB\n",
            "\tVmRSS:\t12 kB\n",
            "VmRSS\t:\t12 kB\n",
            " VmSwap: invalid kB\n",
            "VmSwap : invalid kB\n",
            "\tVmSwap:\t0 kB\n",
            "VmSwap\t:\t0 kB\n",
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                with mock.patch.object(outer.Path, "read_text", return_value=raw):
                    with self.assertRaisesRegex(
                        outer.ProcInspectionError, "key syntax malformed"
                    ):
                        outer._status_values(20)

    def test_malformed_whitespace_vmrss_cannot_be_forgiven_as_zombie_absence(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.zombie]
            ),
            mock.patch.object(
                outer.Path,
                "read_text",
                return_value=" VmRSS: invalid kB\nVmSwap: 0 kB\n",
            ),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "VmRSS key syntax malformed"
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_truly_absent_vmrss_still_requires_zombie_and_positive_pidfd(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.zombie]
            ),
            mock.patch.object(
                outer.Path, "read_text", return_value="VmSwap: 0 kB\n"
            ),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            self.assertIsNone(
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
            )
        confirmed.assert_called_once_with(self.member.pidfd)

    def test_descendant_refresh_rejects_admitted_pid_reuse(self) -> None:
        with self.assertRaisesRegex(
            outer.ProcInspectionError,
            "admitted PID generation ambiguity:descendant_refresh",
        ):
            outer.refresh_descendant_registry(
                wrapper_pid=10,
                root_pid=20,
                admitted={20: self.member},
                baseline_direct_children={},
                snapshot={20: self.reused},
            )

    def test_live_admitted_rejects_pid_reuse_instead_of_returning_empty(self) -> None:
        with mock.patch.object(outer, "proc_record", return_value=self.reused):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "admitted PID generation ambiguity:live_admitted",
            ):
                outer.live_admitted({20: self.member})

    def test_memory_snapshot_records_pid_reuse_as_unavailable(self) -> None:
        wrapper = {
            "pid": 10,
            "identity": [10, 100],
            "topology": [1, 10, 10],
            "process_state": "R",
            "vmrss_kib": 40,
            "vmswap_kib": 0,
        }

        def status(pid, _identity, _pidfd):
            if pid == 20:
                raise outer._generation_ambiguity_error(
                    "memory_snapshot",
                    pid,
                    self.identity,
                    self.reused.identity,
                )
            return wrapper

        with mock.patch.object(outer, "identity_bound_status", side_effect=status):
            sample = outer.accounting_sample(
                wrapper_pid=10,
                wrapper_identity=outer.ProcessIdentity(100),
                admitted={20: self.member},
            )
        self.assertEqual(len(sample["unavailable"]), 1)
        self.assertIn(
            "admitted PID generation ambiguity:memory_snapshot",
            sample["unavailable"][0]["error"],
        )

    def test_reap_known_children_rejects_observed_pid_reuse(self) -> None:
        with mock.patch.object(outer, "proc_record", return_value=self.reused):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "admitted PID generation ambiguity:reap_known_children",
            ):
                outer._reap_known_children(10, None, {20: self.member})

    def test_cleanup_fixed_point_cannot_certify_zero_after_pid_reuse(self) -> None:
        with (
            mock.patch.object(outer, "_reap_known_children", return_value=[]),
            mock.patch.object(
                outer,
                "refresh_descendant_registry",
                return_value={
                    "added_pids": [],
                    "live_admitted_pids": [],
                    "generation_ambiguities": [],
                },
            ),
            mock.patch.object(outer, "proc_record", return_value=self.reused),
            mock.patch.object(outer, "TERMINATION_GRACE_SECONDS", 0.0),
        ):
            result = outer.final_zero_fixed_point(
                wrapper_pid=10,
                root=None,
                root_pid=20,
                admitted={20: self.member},
                baseline_direct_children={},
            )
        self.assertFalse(result["empty"])
        self.assertEqual(result["stable_zero_snapshots"], 0)
        self.assertEqual(result["final_discovery_snapshots"][0]["status"], "UNKNOWN")
        self.assertTrue(
            any("admitted PID generation ambiguity" in row for row in result["errors"])
        )

    def test_pid_reuse_is_recorded_but_wrong_generation_is_never_signaled(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", return_value=self.reused),
            mock.patch.object(
                outer.signal, "pidfd_send_signal", create=True
            ) as send_signal,
        ):
            result = outer.signal_admitted({20: self.member}, outer.SIGKILL)
        send_signal.assert_not_called()
        self.assertEqual(result["identity_mismatch_pids"], [20])
        self.assertTrue(
            any("admitted PID generation ambiguity" in row for row in result["errors"])
        )


'@
        return Replace-Required $text `
            "@unittest.skipUnless(" `
            ($reviewerRegressions + "@unittest.skipUnless(") `
            "v17 independent reviewer regressions"
    }
$testsHash = Get-Sha256 $testsPath

$artifactPaths = [ordered]@{
    outer_controller = $outerPath
    bootstrap = $bootstrapPath
    launcher = $launcherPath
    supervisor = $supervisorPath
    runner = $runnerPath
    generic_validator = $genericPath
    minimal_tcb_manifest = $minimalPath
    stdlib_manifest = $stdlibPath
    tests = $testsPath
}
$oldToNewHashes = [ordered]@{
    $expectedParentArtifacts["agent-aghfal17-native-v16-outer-controller.py"].sha256 = $outerHash
    $expectedParentArtifacts["agent-aghfal17-native-v16-bootstrap.py"].sha256 = $bootstrapHash
    $expectedParentArtifacts["agent-aghfal17-native-v16-launcher.sh"].sha256 = $launcherHash
    $expectedParentArtifacts["agent-aghfal17-native-v16-supervisor.py"].sha256 = $supervisorHash
    $expectedParentArtifacts["agent-aghfal17-native-v16-runner.py"].sha256 = $runnerHash
    $expectedParentArtifacts["agent-aghfal17-native-v16-generic-validator.py"].sha256 = $genericHash
    $expectedParentArtifacts["agent-aghfal17-native-v16-tests.py"].sha256 = $testsHash
}

$parentFreezePath = Join-Path $parentRoot "agent-aghfal17-native-v16-review-freeze.json"
$parentFreeze = Read-Utf8 $parentFreezePath | ConvertFrom-Json -AsHashtable
$freezeText = Convert-Version (Read-Utf8 $parentFreezePath)
foreach ($entry in $oldToNewHashes.GetEnumerator()) {
    $freezeText = $freezeText.Replace([string]$entry.Key, [string]$entry.Value)
}
$freeze = $freezeText | ConvertFrom-Json -AsHashtable
$freeze.created_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$freeze.status = "READY_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
$freeze.scope = "AGH-FAL17 v17 strict proc-status syntax and admitted-generation ambiguity fix derived from preserved v16; official input never opened by this builder"
$freeze.verification.static_checks = "NOT_RUN_BY_BUILDER_REQUIRES_FRESH_WINDOWS_SAFE_REPLAY"
$freeze.verification.linux_adversarial_tests = "NOT_RUN"
$freeze.verification.sealed_import_probe = "NOT_RUN"
$freeze.verification.official_input_opened = $false
$freeze.verification.solver_started = $false
$freeze.verification.probe_run_authorized = $false
$freeze.verification.official_launch_authorized = $false
$freeze.predecessor_v14_retained_probe_failure = $parentFreeze.predecessor_v14_retained_probe_failure
$freeze.predecessor_v15_static_review_no_go = $parentFreeze.predecessor_v15_static_review_no_go
$freeze.predecessor_v16_static_review_no_go = [ordered]@{
    verdict = "NO_GO_DO_NOT_RUN_RETAINED_PROBE"
    outer_controller_sha256 = $expectedParentArtifacts["agent-aghfal17-native-v16-outer-controller.py"].sha256
    tests_sha256 = $expectedParentArtifacts["agent-aghfal17-native-v16-tests.py"].sha256
    status_key_reproduction = "leading or separator whitespace around VmRSS and VmSwap returned an empty mapping instead of an explicit malformed-key error"
    generation_reuse_reproduction = "an admitted numeric PID observed with a different starttime was omitted from live_admitted_pids and could be treated as an empty generation"
    v17_resolution = "tracked status-key syntax is canonical and fail-closed; every observed admitted-PID starttime mismatch propagates as explicit ambiguity through discovery, liveness, accounting, reaping, signaling evidence, and zero certification"
}
$freeze.preserved_predecessors = [ordered]@{
    versions = @(12, 13, 14, 15, 16)
    file_count = $preservedFileCount
    snapshot_encoding = "powershell_ordered_json_depth12_compressed_utf8"
    snapshot_sha256 = $preservedSnapshotSha256
}

foreach ($entry in $artifactPaths.GetEnumerator()) {
    $path = [string]$entry.Value
    $freeze.artifacts[$entry.Key].path = "/tmp/$([System.IO.Path]::GetFileName($path))"
    $freeze.artifacts[$entry.Key].size_bytes = (Get-Item -LiteralPath $path).Length
    $freeze.artifacts[$entry.Key].sha256 = Get-Sha256 $path
}
$freeze.sealed_entry_loader.source_sha256 = Get-TextSha256 ([string]$freeze.sealed_entry_loader.source)
foreach ($mode in @("probe", "launch")) {
    $freeze.commands[$mode].canonical_argv_sha256 = Get-CanonicalArgvSha256 $freeze.commands[$mode].argv
    foreach ($allocation in $freeze.sealed_storage_contract[$mode].allocations) {
        $sourceName = [System.IO.Path]::GetFileName([string]$allocation.source)
        foreach ($path in $artifactPaths.Values) {
            if ([System.IO.Path]::GetFileName([string]$path) -eq $sourceName) {
                $allocation.size_bytes = (Get-Item -LiteralPath ([string]$path)).Length
            }
        }
    }
}

$freezePath = Join-Path $targetRoot "agent-aghfal17-native-v17-review-freeze.json"
$freezeRows = @(
    $freeze.sealed_storage_contract.probe.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
) + @(
    $freeze.sealed_storage_contract.launch.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
)
if ($freezeRows.Count -ne 2) {
    throw "AGH v17 freeze manifest allocation rows are incomplete"
}
$finalFreezeText = $null
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $candidate = ($freeze | ConvertTo-Json -Depth 30) + "`n"
    $candidateSize = $utf8NoBom.GetByteCount($candidate)
    $sizes = @($freezeRows | ForEach-Object { [long]$_.size_bytes } | Select-Object -Unique)
    if ($sizes.Count -eq 1 -and $sizes[0] -eq $candidateSize) {
        $finalFreezeText = $candidate
        break
    }
    foreach ($row in $freezeRows) {
        $row.size_bytes = $candidateSize
    }
}
if ($null -eq $finalFreezeText) {
    throw "AGH v17 freeze manifest sealed-size fixed point did not converge"
}
Write-Utf8 $freezePath $finalFreezeText
$freezeHash = Get-Sha256 $freezePath

$parentInvocationsPath = Join-Path $parentRoot "agent-aghfal17-native-v16-invocations.json"
$invocationsText = Convert-Version (Read-Utf8 $parentInvocationsPath)
foreach ($entry in $oldToNewHashes.GetEnumerator()) {
    $invocationsText = $invocationsText.Replace([string]$entry.Key, [string]$entry.Value)
}
$invocationsText = $invocationsText.Replace($expectedParentFreezeSha256, $freezeHash)
$invocations = $invocationsText | ConvertFrom-Json -AsHashtable
$invocations.freeze_manifest.sha256 = $freezeHash
$invocations.sealed_entry_loader_sha256 = $freeze.sealed_entry_loader.source_sha256
foreach ($mode in @("probe", "launch")) {
    $invocations[$mode].canonical_argv_sha256 = Get-CanonicalArgvSha256 $invocations[$mode].argv
}
$invocations.authorization.probe_run = $false
$invocations.authorization.official_launch = $false
$invocations.authorization.official_input_opened_by_builder = $false
$invocationsPath = Join-Path $targetRoot "agent-aghfal17-native-v17-invocations.json"
Write-Utf8 $invocationsPath (($invocations | ConvertTo-Json -Depth 30) + "`n")

$preservedAfter = Get-PreservedSnapshot
Assert-SnapshotsEqual $preservedBefore $preservedAfter "AGH v12-v16 preserved evidence"

$finalFreeze = Read-Utf8 $freezePath | ConvertFrom-Json -AsHashtable
$finalInvocations = Read-Utf8 $invocationsPath | ConvertFrom-Json -AsHashtable
if ($finalFreeze.verification.probe_run_authorized -or $finalFreeze.verification.official_launch_authorized) {
    throw "AGH v17 execution authorization unexpectedly enabled"
}
if ($finalInvocations.authorization.probe_run -or $finalInvocations.authorization.official_launch) {
    throw "AGH v17 invocation authorization unexpectedly enabled"
}
if ($finalFreeze.commands.probe.canonical_argv_sha256 -eq $finalFreeze.commands.launch.canonical_argv_sha256) {
    throw "AGH v17 probe and launch inner command digests unexpectedly match"
}
if ($finalInvocations.probe.canonical_argv_sha256 -eq $finalInvocations.launch.canonical_argv_sha256) {
    throw "AGH v17 probe and launch outer command digests unexpectedly match"
}
if ($finalInvocations.freeze_manifest.sha256 -ne $freezeHash) {
    throw "AGH v17 invocation freeze pin drifted"
}

$artifactRows = [ordered]@{}
Get-ChildItem -LiteralPath $targetRoot -File | Sort-Object Name | ForEach-Object {
    $artifactRows[$_.Name] = [ordered]@{
        size_bytes = $_.Length
        sha256 = Get-Sha256 $_.FullName
    }
}
[ordered]@{
    target = $targetRoot
    status = $finalFreeze.status
    preserved_v12_through_v16_file_count = $preservedFileCount
    preserved_snapshot_sha256 = $preservedSnapshotSha256
    root_causes = @(
        $finalFreeze.predecessor_v16_static_review_no_go.status_key_reproduction,
        $finalFreeze.predecessor_v16_static_review_no_go.generation_reuse_reproduction
    )
    artifacts = $artifactRows
    probe_authorized = $false
    official_launch_authorized = $false
} | ConvertTo-Json -Depth 8
