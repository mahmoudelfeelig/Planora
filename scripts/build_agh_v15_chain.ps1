param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$parentBuilderPath = Join-Path $repositoryRoot "scripts\build_agh_v14_chain.ps1"
$parentRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v14"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v15"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$expectedParentBuilderSha256 = "485061c0fbb741fc214a335dc48afd4a10ecc4e71c4dd1e17716414e18ca868e"
$expectedParentFreezeSha256 = "6522a072ac957abc95e56951dbc7e677809ae13ab4e835ba6372d072f45ea855"
$expectedParentArtifacts = [ordered]@{
    "agent-aghfal17-native-v14-bootstrap.py" = @{ size = 12889; sha256 = "5e16d8c983f3b19411f022de3e92c971ca593836d83b3c18d5e3d5cc4b8ea6b5" }
    "agent-aghfal17-native-v14-generic-validator.py" = @{ size = 6053; sha256 = "8e40cc0ba7d858347947940bf22d01f265c26cd23834df104f39aafb2ac8ffc2" }
    "agent-aghfal17-native-v14-invocations.json" = @{ size = 18685; sha256 = "1a4c76f565563d40d191818931997fc8e5a6c4102ccd967677a9160f6d46d807" }
    "agent-aghfal17-native-v14-launcher.sh" = @{ size = 10942; sha256 = "67f38351e3a8fd99b8dd22ddc66d0f6c943cb3102de70cfba16e8397a97f8486" }
    "agent-aghfal17-native-v14-minimal-tcb.sha256" = @{ size = 5119; sha256 = "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea" }
    "agent-aghfal17-native-v14-outer-controller.py" = @{ size = 45357; sha256 = "b4de5f184d905afff98bbd97f7485ced82949b1ae80d05cf6a8fe1c3eacb545c" }
    "agent-aghfal17-native-v14-review-freeze.json" = @{ size = 40015; sha256 = $expectedParentFreezeSha256 }
    "agent-aghfal17-native-v14-runner.py" = @{ size = 71673; sha256 = "92ed0f5152a74f724c5b08127be53e3f8c86f1cb75d774a5e1ab7bc8d0f61609" }
    "agent-aghfal17-native-v14-stdlib.sha256" = @{ size = 67004; sha256 = "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327" }
    "agent-aghfal17-native-v14-supervisor.py" = @{ size = 149387; sha256 = "9adf911138ea22726581973c2c305d73bc3c7a80ac45ac324915eb828514ad07" }
    "agent-aghfal17-native-v14-tests.py" = @{ size = 32214; sha256 = "23224f51a01a70253db907176550f15232ea5914b3badf9f74424aa253e5b9cd" }
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

function Convert-Version([string]$Text) {
    $Text = $Text.Replace("NativeV14", "NativeV15")
    $Text = $Text.Replace("NATIVE_V14", "NATIVE_V15")
    $Text = $Text.Replace("native_v14", "native_v15")
    $Text = $Text.Replace("native-v14", "native-v15")
    $Text = $Text.Replace("aghfal17-v14", "aghfal17-v15")
    $Text = $Text.Replace("AGH-FAL17 v14", "AGH-FAL17 v15")
    $Text = $Text.Replace("agh-v14", "agh-v15")
    $Text = $Text.Replace("agh_v14", "agh_v15")
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
        throw "$Label changed while building AGH v15"
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
    throw "AGH v14 builder evidence is missing"
}
if ((Get-Sha256 $parentBuilderPath) -ne $expectedParentBuilderSha256) {
    throw "AGH v14 builder evidence drifted"
}
if (-not (Test-Path -LiteralPath $parentRoot)) {
    throw "AGH v14 preserved chain is missing"
}
foreach ($entry in $expectedParentArtifacts.GetEnumerator()) {
    $path = Join-Path $parentRoot $entry.Key
    if (
        -not (Test-Path -LiteralPath $path) -or
        (Get-Item -LiteralPath $path).Length -ne [long]$entry.Value.size -or
        (Get-Sha256 $path) -ne [string]$entry.Value.sha256
    ) {
        throw "AGH v14 preserved artifact drifted: $($entry.Key)"
    }
}

$parentBuilderBefore = Get-Sha256 $parentBuilderPath
$parentSnapshotBefore = Get-DirectorySnapshot $parentRoot

if (-not (Test-Path -LiteralPath $targetRoot)) {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}
$existing = @(Get-ChildItem -LiteralPath $targetRoot -File -Force)
if ($existing.Count -gt 0 -and -not $Force) {
    throw "Refusing to overwrite the AGH v15 chain without -Force"
}
if ($Force) {
    foreach ($file in $existing) {
        Remove-Item -LiteralPath $file.FullName
    }
}

$minimalName = "agent-aghfal17-native-v15-minimal-tcb.sha256"
$stdlibName = "agent-aghfal17-native-v15-stdlib.sha256"
$minimalPath = Join-Path $targetRoot $minimalName
$stdlibPath = Join-Path $targetRoot $stdlibName
[System.IO.File]::WriteAllBytes(
    $minimalPath,
    [System.IO.File]::ReadAllBytes((Join-Path $parentRoot "agent-aghfal17-native-v14-minimal-tcb.sha256"))
)
[System.IO.File]::WriteAllBytes(
    $stdlibPath,
    [System.IO.File]::ReadAllBytes((Join-Path $parentRoot "agent-aghfal17-native-v14-stdlib.sha256"))
)

$genericPath = Write-Transformed `
    "agent-aghfal17-native-v14-generic-validator.py" `
    "agent-aghfal17-native-v15-generic-validator.py" `
    { param($text) return $text }
$genericHash = Get-Sha256 $genericPath

$runnerPath = Write-Transformed `
    "agent-aghfal17-native-v14-runner.py" `
    "agent-aghfal17-native-v15-runner.py" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v14-generic-validator.py"].sha256 `
            $genericHash `
            "runner generic-validator pin"
    }
$runnerHash = Get-Sha256 $runnerPath

$supervisorPath = Write-Transformed `
    "agent-aghfal17-native-v14-supervisor.py" `
    "agent-aghfal17-native-v15-supervisor.py" `
    {
        param($text)
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v14-runner.py"].sha256 `
            $runnerHash `
            "supervisor runner pin"
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v14-generic-validator.py"].sha256 `
            $genericHash `
            "supervisor generic-validator pin"
        return $text
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherPath = Write-Transformed `
    "agent-aghfal17-native-v14-launcher.sh" `
    "agent-aghfal17-native-v15-launcher.sh" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v14-supervisor.py"].sha256 `
            $supervisorHash `
            "launcher supervisor pin"
    }
$launcherHash = Get-Sha256 $launcherPath

$bootstrapPath = Write-Transformed `
    "agent-aghfal17-native-v14-bootstrap.py" `
    "agent-aghfal17-native-v15-bootstrap.py" `
    { param($text) return $text }
$bootstrapHash = Get-Sha256 $bootstrapPath

$outerPath = Write-Transformed `
    "agent-aghfal17-native-v14-outer-controller.py" `
    "agent-aghfal17-native-v15-outer-controller.py" `
    {
        param($text)
        $text = Replace-Required $text "import re`nimport signal" "import re`nimport select`nimport signal" "outer pidfd poll import"
        $old = @'
def identity_bound_status(
    pid: int, expected: ProcessIdentity
) -> dict[str, Any] | None:
    before = proc_record(pid)
    if before is None:
        return None
    if before.identity != expected:
        raise RuntimeError(f"identity replay failed before status read: {pid}")
    try:
        status = _status_values(pid)
    except OSError as exc:
        if isinstance(exc, (FileNotFoundError, ProcessLookupError)) or exc.errno in (
            errno.ENOENT,
            errno.ESRCH,
        ):
            return None
        raise ProcInspectionError(
            f"proc status read failed: {pid}:{int(exc.errno or errno.EIO)}"
        ) from exc
    after = proc_record(pid)
    if after is None:
        return None
    if after.identity != expected:
        raise RuntimeError(f"identity replay failed after status read: {pid}")
    if "VmRSS" not in status:
        raise RuntimeError(f"VmRSS unavailable for admitted identity: {pid}")
    return {
        "pid": pid,
        "identity": [pid, expected.starttime],
        "topology": [
            after.topology.ppid,
            after.topology.process_group,
            after.topology.session,
        ],
        "vmrss_kib": int(status["VmRSS"]),
        "vmswap_kib": int(status.get("VmSwap", 0)),
    }
'@
        $new = @'
def pidfd_exit_confirmed(pidfd: int) -> bool:
    """Return true only when the pinned process generation has terminated."""

    poll_factory = getattr(select, "poll", None)
    if poll_factory is None:
        raise ProcInspectionError("pidfd polling unavailable")
    poll_in = int(getattr(select, "POLLIN", 0x001))
    poll_invalid = int(getattr(select, "POLLNVAL", 0x020))
    try:
        poller = poll_factory()
        poller.register(pidfd, poll_in)
        events = tuple(poller.poll(0))
    except (OSError, ValueError) as exc:
        raise ProcInspectionError(
            f"pidfd exit observation failed: {pidfd}:{type(exc).__name__}:{exc}"
        ) from exc
    for observed_fd, event_mask in events:
        if int(observed_fd) != pidfd or int(event_mask) & poll_invalid:
            raise ProcInspectionError(f"pidfd exit observation invalid: {pidfd}")
        if int(event_mask) & poll_in:
            return True
    return False


def _confirmed_exit_or_raise(pid: int, pidfd: int | None, reason: str) -> None:
    if pidfd is not None and pidfd_exit_confirmed(pidfd):
        return None
    raise ProcInspectionError(f"{reason}: {pid}")


def identity_bound_status(
    pid: int, expected: ProcessIdentity, pidfd: int | None = None
) -> dict[str, Any] | None:
    before = proc_record(pid)
    if before is None:
        return _confirmed_exit_or_raise(
            pid, pidfd, "proc stat absent without confirmed generation exit"
        )
    if before.identity != expected:
        return _confirmed_exit_or_raise(
            pid, pidfd, "identity replay failed before status read"
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
        if pidfd is not None and pidfd_exit_confirmed(pidfd):
            return None
        raise ProcInspectionError(
            f"proc status read failed: {pid}:{int(exc.errno or errno.EIO)}"
        ) from exc
    after = proc_record(pid)
    if after is None:
        return _confirmed_exit_or_raise(
            pid, pidfd, "proc stat vanished without confirmed generation exit"
        )
    if after.identity != expected:
        return _confirmed_exit_or_raise(
            pid, pidfd, "identity replay failed after status read"
        )
    if "VmRSS" not in status:
        return _confirmed_exit_or_raise(
            pid, pidfd, "VmRSS unavailable without confirmed generation exit"
        )
    return {
        "pid": pid,
        "identity": [pid, expected.starttime],
        "topology": [
            after.topology.ppid,
            after.topology.process_group,
            after.topology.session,
        ],
        "vmrss_kib": int(status["VmRSS"]),
        "vmswap_kib": int(status.get("VmSwap", 0)),
    }
'@
        $text = Replace-Required $text $old $new "outer confirmed-disappearance state machine"
        $text = Replace-Required $text `
            'requested: list[tuple[str, int, ProcessIdentity]] = [' `
            'requested: list[tuple[str, int, ProcessIdentity, int | None]] = [' `
            "outer accounting request type"
        $text = Replace-Required $text `
            '("outer_controller", wrapper_pid, wrapper_identity)' `
            '("outer_controller", wrapper_pid, wrapper_identity, None)' `
            "outer accounting wrapper request"
        $text = Replace-Required $text `
            '("launch_generation", pid, member.identity)' `
            '("launch_generation", pid, member.identity, member.pidfd)' `
            "outer accounting member request"
        $text = Replace-Required $text `
            'for role, pid, identity in requested:' `
            'for role, pid, identity, pidfd in requested:' `
            "outer accounting request unpack"
        $text = Replace-Required $text `
            'row = identity_bound_status(pid, identity)' `
            'row = identity_bound_status(pid, identity, pidfd)' `
            "outer accounting pidfd binding"
        $text = Replace-Required $text `
            'vanished.append({"role": role, "pid": pid})' `
            'vanished.append({"role": role, "pid": pid, "basis": "pidfd_exit_confirmed"})' `
            "outer confirmed-disappearance evidence"
        return $text
    }
$outerHash = Get-Sha256 $outerPath

$testsPath = Write-Transformed `
    "agent-aghfal17-native-v14-tests.py" `
    "agent-aghfal17-native-v15-tests.py" `
    {
        param($text)
        $text = Replace-Required $text `
            'status.assert_called_once_with(10, identity)' `
            'status.assert_called_once_with(10, identity, None)' `
            "v15 accounting call contract"
        $marker = "@unittest.skipUnless(`n    os.name == `"posix`""
        if (-not $text.Contains($marker)) {
            throw "AGH v15 adversarial-test insertion marker is absent"
        }
        $additional = @'
class ConfirmedDisappearanceRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = outer.ProcessIdentity(200)
        self.record = outer.ProcessRecord(
            self.identity, outer.ProcessTopology(10, 20, 20)
        )
        self.member = outer.AdmittedMember(
            identity=self.identity,
            pidfd=77,
            topology=self.record.topology,
        )

    def test_pidfd_readability_is_required_for_exit_confirmation(self) -> None:
        poller = mock.Mock()
        poller.poll.return_value = [(77, 0x001)]
        with mock.patch.object(outer.select, "poll", return_value=poller, create=True):
            self.assertTrue(outer.pidfd_exit_confirmed(77))
        poller.register.assert_called_once_with(77, 0x001)

    def test_pidfd_poll_failure_is_observation_failure(self) -> None:
        with mock.patch.object(
            outer.select, "poll", side_effect=OSError(5, "io"), create=True
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "pidfd exit observation failed"
            ):
                outer.pidfd_exit_confirmed(77)

    def test_zombie_without_vmrss_is_vanished_only_after_pidfd_exit(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", side_effect=[self.record, self.record]),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(outer, "pidfd_exit_confirmed", return_value=True),
        ):
            self.assertIsNone(
                outer.identity_bound_status(20, self.identity, self.member.pidfd)
            )

    def test_zombie_without_vmrss_fails_closed_while_pidfd_is_live(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", side_effect=[self.record, self.record]),
            mock.patch.object(outer, "_status_values", return_value={}),
            mock.patch.object(outer, "pidfd_exit_confirmed", return_value=False),
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "VmRSS unavailable without confirmed generation exit",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)

    def test_missing_proc_row_fails_closed_without_pidfd_confirmation(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", return_value=None),
            mock.patch.object(outer, "pidfd_exit_confirmed", return_value=False),
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "proc stat absent without confirmed generation exit",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)

    def test_permission_failure_fails_closed_for_live_generation(self) -> None:
        with (
            mock.patch.object(outer, "proc_record", return_value=self.record),
            mock.patch.object(
                outer, "_status_values", side_effect=PermissionError(13, "denied")
            ),
            mock.patch.object(outer, "pidfd_exit_confirmed", return_value=False),
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError, "proc status read failed"
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)

    def test_pid_reuse_is_not_accepted_without_old_generation_exit(self) -> None:
        reused = outer.ProcessRecord(
            outer.ProcessIdentity(900), outer.ProcessTopology(1, 20, 20)
        )
        with (
            mock.patch.object(outer, "proc_record", return_value=reused),
            mock.patch.object(outer, "pidfd_exit_confirmed", return_value=False),
        ):
            with self.assertRaisesRegex(
                outer.ProcInspectionError,
                "identity replay failed before status read",
            ):
                outer.identity_bound_status(20, self.identity, self.member.pidfd)

    def test_reported_v14_race_becomes_confirmed_zero_contribution(self) -> None:
        wrapper = {
            "pid": 10,
            "identity": [10, 100],
            "topology": [1, 10, 10],
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
        self.assertIsNone(
            outer.resource_breach(
                elapsed_seconds=27.666,
                process_rss_kib=sample["process_vmrss_kib"],
                process_swap_kib=sample["process_vmswap_kib"],
                process_group_charges_kib=sample["process_group_charges_kib"],
                sealed_bytes=0,
                report_bytes=0,
                mem_available_kib=2_000_000,
                wall_seconds=240,
                accounting_errors=sample["unavailable"],
            )
        )


'@
        return $text.Replace($marker, $additional + $marker)
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
    $expectedParentArtifacts["agent-aghfal17-native-v14-outer-controller.py"].sha256 = $outerHash
    $expectedParentArtifacts["agent-aghfal17-native-v14-bootstrap.py"].sha256 = $bootstrapHash
    $expectedParentArtifacts["agent-aghfal17-native-v14-launcher.sh"].sha256 = $launcherHash
    $expectedParentArtifacts["agent-aghfal17-native-v14-supervisor.py"].sha256 = $supervisorHash
    $expectedParentArtifacts["agent-aghfal17-native-v14-runner.py"].sha256 = $runnerHash
    $expectedParentArtifacts["agent-aghfal17-native-v14-generic-validator.py"].sha256 = $genericHash
    $expectedParentArtifacts["agent-aghfal17-native-v14-tests.py"].sha256 = $testsHash
}

$parentFreezePath = Join-Path $parentRoot "agent-aghfal17-native-v14-review-freeze.json"
$freezeText = Convert-Version (Read-Utf8 $parentFreezePath)
foreach ($entry in $oldToNewHashes.GetEnumerator()) {
    $freezeText = $freezeText.Replace([string]$entry.Key, [string]$entry.Value)
}
$freeze = $freezeText | ConvertFrom-Json -AsHashtable
$freeze.created_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$freeze.status = "READY_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
$freeze.scope = "AGH-FAL17 v15 confirmed-disappearance accounting fix derived from preserved v14; official input never opened by this builder"
$freeze.verification.static_checks = "NOT_RUN_BY_BUILDER_REQUIRES_FRESH_WINDOWS_SAFE_REPLAY"
$freeze.verification.linux_adversarial_tests = "NOT_RUN"
$freeze.verification.sealed_import_probe = "NOT_RUN"
$freeze.verification.official_input_opened = $false
$freeze.verification.solver_started = $false
$freeze.verification.probe_run_authorized = $false
$freeze.verification.official_launch_authorized = $false
$freeze.predecessor_v14_retained_probe_failure = [ordered]@{
    probe_id = "f95129553c8040529e356bef6802da98"
    disposition = "FAILED_CLOSED_NO_RETRY_INHERITED"
    elapsed_seconds = 27.666
    breach = "exact_generation_accounting_unavailable"
    contained_root_exit_code = -15
    inner_stdout_empty = $true
    peak_accounting_unavailable_rows = 0
    cleanup_empty = $true
    cleanup_stable_zero_snapshots = 2
    probe_child_started = $true
    solver_started = $false
    official_input_opened = $false
    publication = $false
    root_cause = "outer accounting sampled the admitted supervisor generation after exit while its zombie status lacked VmRSS, before root.poll reaped it; v14 treated that legitimate transition as unavailable instead of consulting the already-bound pidfd"
    v15_resolution = "only a readable pinned pidfd can convert disappearance, status loss, PID reuse, or missing VmRSS into a zero contribution; all unconfirmed observation failures remain fail-closed"
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

$freezePath = Join-Path $targetRoot "agent-aghfal17-native-v15-review-freeze.json"
$freezeRows = @(
    $freeze.sealed_storage_contract.probe.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
) + @(
    $freeze.sealed_storage_contract.launch.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
)
if ($freezeRows.Count -ne 2) {
    throw "AGH v15 freeze manifest allocation rows are incomplete"
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
    throw "AGH v15 freeze manifest sealed-size fixed point did not converge"
}
Write-Utf8 $freezePath $finalFreezeText
$freezeHash = Get-Sha256 $freezePath

$parentInvocationsPath = Join-Path $parentRoot "agent-aghfal17-native-v14-invocations.json"
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
$invocationsPath = Join-Path $targetRoot "agent-aghfal17-native-v15-invocations.json"
Write-Utf8 $invocationsPath (($invocations | ConvertTo-Json -Depth 30) + "`n")

if ((Get-Sha256 $parentBuilderPath) -ne $parentBuilderBefore) {
    throw "AGH v14 builder changed while building AGH v15"
}
Assert-SnapshotsEqual $parentSnapshotBefore (Get-DirectorySnapshot $parentRoot) "AGH v14 chain"

$finalFreeze = Read-Utf8 $freezePath | ConvertFrom-Json -AsHashtable
$finalInvocations = Read-Utf8 $invocationsPath | ConvertFrom-Json -AsHashtable
if ($finalFreeze.verification.probe_run_authorized -or $finalFreeze.verification.official_launch_authorized) {
    throw "AGH v15 execution authorization unexpectedly enabled"
}
if ($finalInvocations.authorization.probe_run -or $finalInvocations.authorization.official_launch) {
    throw "AGH v15 invocation authorization unexpectedly enabled"
}
if ($finalFreeze.commands.probe.canonical_argv_sha256 -eq $finalFreeze.commands.launch.canonical_argv_sha256) {
    throw "AGH v15 probe and launch inner command digests unexpectedly match"
}
if ($finalInvocations.probe.canonical_argv_sha256 -eq $finalInvocations.launch.canonical_argv_sha256) {
    throw "AGH v15 probe and launch outer command digests unexpectedly match"
}
if ($finalInvocations.freeze_manifest.sha256 -ne $freezeHash) {
    throw "AGH v15 invocation freeze pin drifted"
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
    v14_immutable = $true
    root_cause = $finalFreeze.predecessor_v14_retained_probe_failure.root_cause
    artifacts = $artifactRows
    probe_authorized = $false
    official_launch_authorized = $false
} | ConvertTo-Json -Depth 8
