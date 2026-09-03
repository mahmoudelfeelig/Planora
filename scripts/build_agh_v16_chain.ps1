param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$parentBuilderPath = Join-Path $repositoryRoot "scripts\build_agh_v15_chain.ps1"
$parentRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v15"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v16"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$expectedParentBuilderSha256 = "4a7510149fe4d71b3ec384ffaa6f166f5cbabf2c99829cd56b3740ee133db8f0"
$expectedParentFreezeSha256 = "732bb0c4de0415a367c263628d4dbc27cdf98a580fae6208eb4c636da6aa8710"
$expectedParentArtifacts = [ordered]@{
    "agent-aghfal17-native-v15-bootstrap.py" = @{ size = 12889; sha256 = "e053946f8885d644531f2ea14b9cad87160b2a155eed6e162a49d20df3a2e7d2" }
    "agent-aghfal17-native-v15-generic-validator.py" = @{ size = 6053; sha256 = "a6c24c63d55bd9e329c487376a667c8d2dd1f35f571130a23676174272e7c0ca" }
    "agent-aghfal17-native-v15-invocations.json" = @{ size = 18685; sha256 = "7cb50be60b8002c6cc7cdcbb55b582351527b90e29251803b8edf9719c233d9d" }
    "agent-aghfal17-native-v15-launcher.sh" = @{ size = 10942; sha256 = "3f15066a9d9546c5d152b0a8c93af06a19f7ea205340dae8cc1c47c00048a2d4" }
    "agent-aghfal17-native-v15-minimal-tcb.sha256" = @{ size = 5119; sha256 = "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea" }
    "agent-aghfal17-native-v15-outer-controller.py" = @{ size = 47188; sha256 = "1326027d0447c76be37f112d2e6ede2bdf7b8e2eb95c6afcb6ef8597369c325b" }
    "agent-aghfal17-native-v15-review-freeze.json" = @{ size = 41020; sha256 = $expectedParentFreezeSha256 }
    "agent-aghfal17-native-v15-runner.py" = @{ size = 71673; sha256 = "85ab5878974018687fc3c8684712792ebcb6e4abf67412be78ff4ec1a839426f" }
    "agent-aghfal17-native-v15-stdlib.sha256" = @{ size = 67004; sha256 = "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327" }
    "agent-aghfal17-native-v15-supervisor.py" = @{ size = 149387; sha256 = "e74ab1ce5b5d6d1094fb515b7821ef51f8d2e367b2aa473263abc87e2d3e1629" }
    "agent-aghfal17-native-v15-tests.py" = @{ size = 37693; sha256 = "8067172a13d3719260a842f1e138efdcc654e3950c04487c95212ade78841422" }
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
    $Text = $Text.Replace("NativeV15", "NativeV16")
    $Text = $Text.Replace("NATIVE_V15", "NATIVE_V16")
    $Text = $Text.Replace("native_v15", "native_v16")
    $Text = $Text.Replace("native-v15", "native-v16")
    $Text = $Text.Replace("aghfal17-v15", "aghfal17-v16")
    $Text = $Text.Replace("AGH-FAL17 v15", "AGH-FAL17 v16")
    $Text = $Text.Replace("agh-v15", "agh-v16")
    $Text = $Text.Replace("agh_v15", "agh_v16")
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

function Assert-SnapshotsEqual([hashtable]$Before, [hashtable]$After, [string]$Label) {
    if (
        ($Before | ConvertTo-Json -Depth 8 -Compress) -cne
        ($After | ConvertTo-Json -Depth 8 -Compress)
    ) {
        throw "$Label changed while building AGH v16"
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
    throw "AGH v15 builder evidence is missing"
}
if ((Get-Sha256 $parentBuilderPath) -ne $expectedParentBuilderSha256) {
    throw "AGH v15 builder evidence drifted"
}
if (-not (Test-Path -LiteralPath $parentRoot)) {
    throw "AGH v15 preserved chain is missing"
}
foreach ($entry in $expectedParentArtifacts.GetEnumerator()) {
    $path = Join-Path $parentRoot $entry.Key
    if (
        -not (Test-Path -LiteralPath $path) -or
        (Get-Item -LiteralPath $path).Length -ne [long]$entry.Value.size -or
        (Get-Sha256 $path) -ne [string]$entry.Value.sha256
    ) {
        throw "AGH v15 preserved artifact drifted: $($entry.Key)"
    }
}

$parentBuilderBefore = Get-Sha256 $parentBuilderPath
$parentSnapshotBefore = Get-DirectorySnapshot $parentRoot

if (-not (Test-Path -LiteralPath $targetRoot)) {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}
$existing = @(Get-ChildItem -LiteralPath $targetRoot -File -Force)
if ($existing.Count -gt 0 -and -not $Force) {
    throw "Refusing to overwrite the AGH v16 chain without -Force"
}
if ($Force) {
    foreach ($file in $existing) {
        Remove-Item -LiteralPath $file.FullName
    }
}

$minimalName = "agent-aghfal17-native-v16-minimal-tcb.sha256"
$stdlibName = "agent-aghfal17-native-v16-stdlib.sha256"
$minimalPath = Join-Path $targetRoot $minimalName
$stdlibPath = Join-Path $targetRoot $stdlibName
[System.IO.File]::WriteAllBytes(
    $minimalPath,
    [System.IO.File]::ReadAllBytes((Join-Path $parentRoot "agent-aghfal17-native-v15-minimal-tcb.sha256"))
)
[System.IO.File]::WriteAllBytes(
    $stdlibPath,
    [System.IO.File]::ReadAllBytes((Join-Path $parentRoot "agent-aghfal17-native-v15-stdlib.sha256"))
)

$genericPath = Write-Transformed `
    "agent-aghfal17-native-v15-generic-validator.py" `
    "agent-aghfal17-native-v16-generic-validator.py" `
    { param($text) return $text }
$genericHash = Get-Sha256 $genericPath

$runnerPath = Write-Transformed `
    "agent-aghfal17-native-v15-runner.py" `
    "agent-aghfal17-native-v16-runner.py" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v15-generic-validator.py"].sha256 `
            $genericHash `
            "runner generic-validator pin"
    }
$runnerHash = Get-Sha256 $runnerPath

$supervisorPath = Write-Transformed `
    "agent-aghfal17-native-v15-supervisor.py" `
    "agent-aghfal17-native-v16-supervisor.py" `
    {
        param($text)
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v15-runner.py"].sha256 `
            $runnerHash `
            "supervisor runner pin"
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v15-generic-validator.py"].sha256 `
            $genericHash `
            "supervisor generic-validator pin"
        return $text
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherPath = Write-Transformed `
    "agent-aghfal17-native-v15-launcher.sh" `
    "agent-aghfal17-native-v16-launcher.sh" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v15-supervisor.py"].sha256 `
            $supervisorHash `
            "launcher supervisor pin"
    }
$launcherHash = Get-Sha256 $launcherPath

$bootstrapPath = Write-Transformed `
    "agent-aghfal17-native-v15-bootstrap.py" `
    "agent-aghfal17-native-v16-bootstrap.py" `
    { param($text) return $text }
$bootstrapHash = Get-Sha256 $bootstrapPath

$outerPath = Write-Transformed `
    "agent-aghfal17-native-v15-outer-controller.py" `
    "agent-aghfal17-native-v16-outer-controller.py" `
    {
        param($text)
        $text = Replace-Required $text @'
@dataclass(frozen=True)
class ProcessRecord:
    identity: ProcessIdentity
    topology: ProcessTopology
'@ @'
@dataclass(frozen=True)
class ProcessRecord:
    identity: ProcessIdentity
    topology: ProcessTopology
    state: str = "S"
'@ "outer process-state retention"

        $procRecord = @'
def proc_record(pid: int) -> ProcessRecord | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    except OSError as exc:
        if isinstance(exc, (FileNotFoundError, ProcessLookupError)) or exc.errno in (
            errno.ENOENT,
            errno.ESRCH,
        ):
            return None
        raise ProcInspectionError(
            f"proc stat read failed: {pid}:{int(exc.errno or errno.EIO)}"
        ) from exc
    close = raw.rfind(")")
    fields = raw[close + 2 :].split() if close >= 0 else []
    if len(fields) < 20:
        raise ProcInspectionError(f"proc stat malformed: {pid}")
    state = fields[0]
    if len(state) != 1 or not state.isascii() or not state.isalpha():
        raise ProcInspectionError(f"proc stat state malformed: {pid}")
    try:
        return ProcessRecord(
            identity=ProcessIdentity(starttime=int(fields[19])),
            topology=ProcessTopology(
                ppid=int(fields[1]),
                process_group=int(fields[2]),
                session=int(fields[3]),
            ),
            state=state,
        )
    except ValueError as exc:
        raise ProcInspectionError(f"proc stat parse failed: {pid}") from exc


'@
        $text = Replace-Section $text "def proc_record(" "def proc_identity(" ($procRecord + "`n") "outer strict proc stat parser"

        $statusValues = @'
def _status_values(pid: int) -> dict[str, int]:
    values: dict[str, int] = {}
    raw = (Path("/proc") / str(pid) / "status").read_text(encoding="ascii")
    tracked = frozenset(("VmRSS", "VmSwap"))
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            if line.lstrip().startswith(("VmRSS", "VmSwap")):
                raise ProcInspectionError(f"proc status field malformed: {pid}")
            continue
        if key not in tracked:
            continue
        if key in values:
            raise ProcInspectionError(f"proc status duplicate {key}: {pid}")
        tokens = value.strip().split()
        if len(tokens) != 2 or tokens[1] != "kB":
            raise ProcInspectionError(f"proc status {key} malformed: {pid}")
        try:
            parsed = int(tokens[0])
        except ValueError as exc:
            raise ProcInspectionError(f"proc status {key} malformed: {pid}") from exc
        if parsed < 0:
            raise ProcInspectionError(f"proc status {key} negative: {pid}")
        values[key] = parsed
    return values


'@
        $text = Replace-Section $text "def _status_values(" "def pidfd_exit_confirmed(" ($statusValues + "`n") "outer strict proc status parser"

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
        raise ProcInspectionError(f"identity replay failed before status read: {pid}")
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
        raise ProcInspectionError(f"identity replay failed after status read: {pid}")
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
        return Replace-Section $text "def identity_bound_status(" "def _open_pidfd(" ($identityBoundStatus + "`n") "outer fail-closed identity accounting"
    }
$outerHash = Get-Sha256 $outerPath

$testsPath = Write-Transformed `
    "agent-aghfal17-native-v15-tests.py" `
    "agent-aghfal17-native-v16-tests.py" `
    {
        param($text)
        $text = Replace-Required $text `
            "class V14FreezeReadinessTests" `
            "class V16FreezeReadinessTests" `
            "v16 readiness class identity"
        $text = Replace-Required $text `
            "def test_v14_is_review_ready_but_execution_unauthorized" `
            "def test_v16_is_review_ready_but_execution_unauthorized" `
            "v16 readiness test identity"
        $staleTokenMarker = @'


class V16FreezeReadinessTests(unittest.TestCase):
'@
        $staleTokenTest = @'

    def test_no_v15_protocol_tokens_in_active_v16_runtime_artifacts(self) -> None:
        for path in (
            OUTER_PATH,
            BOOTSTRAP_PATH,
            SUPERVISOR_PATH,
            RUNNER_PATH,
            LAUNCHER_PATH,
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("native-v15", source, path.name)
            self.assertNotIn("NATIVE_V15", source, path.name)


class V16FreezeReadinessTests(unittest.TestCase):
'@
        $text = Replace-Required $text `
            $staleTokenMarker `
            $staleTokenTest `
            "v16 stale runtime token regression"
        $predecessorMarker = @'
    def test_final_shared_core_and_focused_regression_are_frozen(self) -> None:
'@
        $predecessorTest = @'
    def test_v15_no_go_context_is_retained(self) -> None:
        context = self.freeze["predecessor_v15_static_review_no_go"]
        self.assertEqual(context["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertEqual(
            context["outer_controller_sha256"],
            "1326027d0447c76be37f112d2e6ede2bdf7b8e2eb95c6afcb6ef8597369c325b",
        )
        self.assertEqual(
            context["tests_sha256"],
            "8067172a13d3719260a842f1e138efdcc654e3950c04487c95212ade78841422",
        )

    def test_final_shared_core_and_focused_regression_are_frozen(self) -> None:
'@
        $text = Replace-Required $text `
            $predecessorMarker `
            $predecessorTest `
            "v15 no-go context regression"
        $regressions = @'
class StrictTerminationObservationRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = outer.ProcessIdentity(200)
        self.running = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "S"
        )
        self.zombie = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20), "Z"
        )
        self.member = outer.AdmittedMember(
            identity=self.identity,
            pidfd=77,
            topology=self.running.topology,
        )

    def test_proc_record_parses_and_retains_zombie_state(self) -> None:
        fields = ["Z", "10", "20", "20", *(["0"] * 15), "200"]
        raw = "20 (worker name) " + " ".join(fields)
        with mock.patch.object(outer.Path, "read_text", return_value=raw):
            record = outer.proc_record(20)
        self.assertEqual(record, self.zombie)

    def test_malformed_proc_state_fails_closed(self) -> None:
        fields = ["ZZ", "10", "20", "20", *(["0"] * 15), "200"]
        raw = "20 (worker) " + " ".join(fields)
        with mock.patch.object(outer.Path, "read_text", return_value=raw):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "proc stat state malformed"
            ):
                outer.proc_record(20)

    def test_permission_and_eio_remain_fail_closed_after_pidfd_termination(self) -> None:
        failures = (PermissionError(13, "denied"), OSError(5, "io"))
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                with (
                    mock.patch.object(outer, "proc_record", return_value=self.running),
                    mock.patch.object(outer, "_status_values", side_effect=failure),
                    mock.patch.object(
                        outer, "pidfd_exit_confirmed", return_value=True
                    ) as confirmed,
                ):
                    with self.assertRaisesRegex(
                        outer.ProcInspectionError, "proc status read failed"
                    ):
                        outer.identity_bound_status(
                            20, self.identity, self.member.pidfd
                        )
                confirmed.assert_not_called()

    def test_malformed_vmrss_is_distinct_from_missing_vmrss(self) -> None:
        malformed = (
            "VmRSS: nope kB\n",
            "VmRSS: 12 MB\n",
            "VmRSS:\n",
            "VmRSS 12 kB\n",
            "VmRSS: 12 kB\nVmRSS: 13 kB\n",
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                with mock.patch.object(outer.Path, "read_text", return_value=raw):
                    with self.assertRaises(outer.ProcInspectionError):
                        outer._status_values(20)

    def test_malformed_vmswap_fails_closed(self) -> None:
        raw = "VmRSS: 12 kB\nVmSwap: bad kB\n"
        with mock.patch.object(outer.Path, "read_text", return_value=raw):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "proc status VmSwap malformed"
            ):
                outer._status_values(20)

    def test_non_zombie_missing_vmrss_fails_even_after_pidfd_termination(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.running]
            ),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "VmRSS unavailable for non-zombie admitted identity",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_genuine_zombie_without_vmrss_is_zero_only_after_pidfd_exit(self) -> None:
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, self.zombie]
            ),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            self.assertIsNone(
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
            )
        confirmed.assert_called_once_with(self.member.pidfd)

    def test_zombie_without_vmrss_fails_when_pidfd_is_not_ready(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", return_value=self.zombie),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(outer, "pidfd_exit_confirmed", return_value=False),
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "zombie VmRSS unavailable without confirmed generation exit",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)

    def test_pid_reuse_before_status_is_ambiguous_even_after_pidfd_exit(self) -> None:
        reused = outer.ProcessRecord(
            outer.ProcessIdentity(900), outer.ProcessTopology(1, 20, 20), "S"
        )
        with (
            mock.patch.object(outer, "proc_record", return_value=reused),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "identity replay failed before status read",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_pid_reuse_after_status_is_ambiguous_even_after_pidfd_exit(self) -> None:
        reused = outer.ProcessRecord(
            outer.ProcessIdentity(900), outer.ProcessTopology(1, 20, 20), "Z"
        )
        with (
            mock.patch.object(
                outer, "proc_record", side_effect=[self.running, reused]
            ),
            mock.patch.object(outer, "_status_values", return_value={"VmRSS": 1}),
            mock.patch.object(
                outer, "pidfd_exit_confirmed", return_value=True
            ) as confirmed,
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "identity replay failed after status read",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
        confirmed.assert_not_called()

    def test_pidfd_poll_failure_is_observation_failure(self) -> None:
        with mock.patch.object(
            outer.select, "poll", side_effect=OSError(5, "io"), create=True
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "pidfd exit observation failed"
            ):
                outer.pidfd_exit_confirmed(77)

    def test_pidfd_invalid_event_is_observation_failure(self) -> None:
        poller = mock.Mock()
        poller.poll.return_value = [(77, getattr(outer.select, "POLLNVAL", 0x020))]
        with mock.patch.object(outer.select, "poll", return_value=poller, create=True):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "pidfd exit observation invalid"
            ):
                outer.pidfd_exit_confirmed(77)

    def test_confirmed_zombie_is_reported_as_vanished_without_accounting_error(self) -> None:
        wrapper = {
            "pid": 10,
            "identity": [10, 100],
            "topology": [1, 10, 10],
            "process_state": "R",
            "vmrss_kib": 40,
            "vmswap_kib": 0,
        }
        with mock.patch.object(
            outer, "identity_bound_status", side_effect=[wrapper, None]
        ):
            sample = outer.accounting_sample(
                wrapper_pid=10,
                wrapper_identity=outer.ProcessIdentity(100),
                admitted={20: self.member},
            )
        self.assertEqual(sample["unavailable"], [])
        self.assertEqual(
            sample["vanished"],
            [
                {
                    "role": "launch_generation",
                    "pid": 20,
                    "basis": "pidfd_exit_confirmed",
                }
            ],
        )
        self.assertEqual(sample["process_vmrss_kib"], 40)


'@
        return Replace-Section $text `
            "class ConfirmedDisappearanceRegressionTests" `
            "@unittest.skipUnless(" `
            $regressions `
            "v16 strict observation regressions"
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
    $expectedParentArtifacts["agent-aghfal17-native-v15-outer-controller.py"].sha256 = $outerHash
    $expectedParentArtifacts["agent-aghfal17-native-v15-bootstrap.py"].sha256 = $bootstrapHash
    $expectedParentArtifacts["agent-aghfal17-native-v15-launcher.sh"].sha256 = $launcherHash
    $expectedParentArtifacts["agent-aghfal17-native-v15-supervisor.py"].sha256 = $supervisorHash
    $expectedParentArtifacts["agent-aghfal17-native-v15-runner.py"].sha256 = $runnerHash
    $expectedParentArtifacts["agent-aghfal17-native-v15-generic-validator.py"].sha256 = $genericHash
    $expectedParentArtifacts["agent-aghfal17-native-v15-tests.py"].sha256 = $testsHash
}

$parentFreezePath = Join-Path $parentRoot "agent-aghfal17-native-v15-review-freeze.json"
$parentFreeze = Read-Utf8 $parentFreezePath | ConvertFrom-Json -AsHashtable
$freezeText = Convert-Version (Read-Utf8 $parentFreezePath)
foreach ($entry in $oldToNewHashes.GetEnumerator()) {
    $freezeText = $freezeText.Replace([string]$entry.Key, [string]$entry.Value)
}
$freeze = $freezeText | ConvertFrom-Json -AsHashtable
$freeze.created_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$freeze.status = "READY_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
$freeze.scope = "AGH-FAL17 v16 strict generation-observation fix derived from preserved v15; official input never opened by this builder"
$freeze.verification.static_checks = "NOT_RUN_BY_BUILDER_REQUIRES_FRESH_WINDOWS_SAFE_REPLAY"
$freeze.verification.linux_adversarial_tests = "NOT_RUN"
$freeze.verification.sealed_import_probe = "NOT_RUN"
$freeze.verification.official_input_opened = $false
$freeze.verification.solver_started = $false
$freeze.verification.probe_run_authorized = $false
$freeze.verification.official_launch_authorized = $false
$freeze.predecessor_v14_retained_probe_failure = $parentFreeze.predecessor_v14_retained_probe_failure
$freeze.predecessor_v15_static_review_no_go = [ordered]@{
    verdict = "NO_GO_DO_NOT_RUN_RETAINED_PROBE"
    outer_controller_sha256 = $expectedParentArtifacts["agent-aghfal17-native-v15-outer-controller.py"].sha256
    tests_sha256 = $expectedParentArtifacts["agent-aghfal17-native-v15-tests.py"].sha256
    root_cause = "v15 allowed a terminated pidfd to erase permission and I/O observation failures, treated malformed VmRSS as missing, and did not retain process state, so a non-zombie or malformed status could be misclassified as a confirmed zero contribution"
    v16_resolution = "permission, EIO, malformed stat or status, identity ambiguity, and pidfd uncertainty always fail closed; missing VmRSS is accepted only for the same admitted identity with state Z and a positively terminated identity-bound pidfd"
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

$freezePath = Join-Path $targetRoot "agent-aghfal17-native-v16-review-freeze.json"
$freezeRows = @(
    $freeze.sealed_storage_contract.probe.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
) + @(
    $freeze.sealed_storage_contract.launch.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
)
if ($freezeRows.Count -ne 2) {
    throw "AGH v16 freeze manifest allocation rows are incomplete"
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
    throw "AGH v16 freeze manifest sealed-size fixed point did not converge"
}
Write-Utf8 $freezePath $finalFreezeText
$freezeHash = Get-Sha256 $freezePath

$parentInvocationsPath = Join-Path $parentRoot "agent-aghfal17-native-v15-invocations.json"
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
$invocationsPath = Join-Path $targetRoot "agent-aghfal17-native-v16-invocations.json"
Write-Utf8 $invocationsPath (($invocations | ConvertTo-Json -Depth 30) + "`n")

if ((Get-Sha256 $parentBuilderPath) -ne $parentBuilderBefore) {
    throw "AGH v15 builder changed while building AGH v16"
}
Assert-SnapshotsEqual $parentSnapshotBefore (Get-DirectorySnapshot $parentRoot) "AGH v15 chain"

$finalFreeze = Read-Utf8 $freezePath | ConvertFrom-Json -AsHashtable
$finalInvocations = Read-Utf8 $invocationsPath | ConvertFrom-Json -AsHashtable
if ($finalFreeze.verification.probe_run_authorized -or $finalFreeze.verification.official_launch_authorized) {
    throw "AGH v16 execution authorization unexpectedly enabled"
}
if ($finalInvocations.authorization.probe_run -or $finalInvocations.authorization.official_launch) {
    throw "AGH v16 invocation authorization unexpectedly enabled"
}
if ($finalFreeze.commands.probe.canonical_argv_sha256 -eq $finalFreeze.commands.launch.canonical_argv_sha256) {
    throw "AGH v16 probe and launch inner command digests unexpectedly match"
}
if ($finalInvocations.probe.canonical_argv_sha256 -eq $finalInvocations.launch.canonical_argv_sha256) {
    throw "AGH v16 probe and launch outer command digests unexpectedly match"
}
if ($finalInvocations.freeze_manifest.sha256 -ne $freezeHash) {
    throw "AGH v16 invocation freeze pin drifted"
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
    v15_immutable = $true
    root_cause = $finalFreeze.predecessor_v15_static_review_no_go.root_cause
    artifacts = $artifactRows
    probe_authorized = $false
    official_launch_authorized = $false
} | ConvertTo-Json -Depth 8
