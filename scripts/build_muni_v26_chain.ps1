param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$muniRepositoryRoot = Split-Path -Parent $PSScriptRoot
$muniV25Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v25"
$muniV24Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v24"
$muniV26Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v26"
$muniRepositoryWsl = "/mnt/d/Stuff/Projects/Sites/Planora"
$muniV25Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v25"
$muniV24Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v24"
$muniV26Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v26"
$muniUtf8NoBom = [System.Text.UTF8Encoding]::new($false)

$muniFinalSharedCoreHash = "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf"
$muniFinalFocusedTestHash = "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d"
$muniSupersededSharedCoreHash = "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d"
$muniParentBuilderHash = "d6b379e7307e803023d9f6726f36a4cf7d69411f1a6c9f228cc9edd51ea3c028"
$muniParentManifestHash = "574f549bcacb773097ebf2f1ff242068f8113609127f96c26ab2e94b9a6c6df8"
$muniParentCertificateHash = "ca2324b21c89f2fea30c4ee5376796e47667b75ed4875aac34e8aae40f8083aa"
$muniStaleV24BuilderHash = "4bb5b603020886758a69fb91df6cb9d3aea1dd87f19e314bb43eff09f1f883da"
$muniStaleV24ManifestHash = "66a8560e20919cc5825c6c3dc7817b639687fe26ca1088bda21bc6d7eabf0469"
$muniStaleV24CertificateHash = "a95f01282e326f9a8f05bd0176b046d4cc85805bb7ac11c67fc231cd6fa1ba1b"
$muniSharedCoreReceiptHash = "fa12c7ac258331407f2882cd69f4ff1e5d779dc955a77971c732c45699d1ed55"
$muniSharedCoreStdoutHash = "c68d64995601c3af1954a5b6ac0ae56db15d2dd10245f3263418b87cfd551e41"
$muniEmptySha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

$muniParentBuilderPath = Join-Path $muniRepositoryRoot "scripts\build_muni_v25_chain.ps1"
$muniParentManifestPath = Join-Path $muniV25Root "planora-muni-fspsx-frontier-v25-freeze-manifest.json"
$muniParentCertificatePath = Join-Path $muniV25Root "planora-muni-fspsx-frontier-v25-certificate.json"
$muniStaleV24BuilderPath = Join-Path $muniRepositoryRoot "scripts\build_muni_v24_chain.ps1"
$muniStaleV24ManifestPath = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-freeze-manifest.json"
$muniStaleV24CertificatePath = Join-Path $muniV24Root "planora-muni-fspsx-frontier-v24-certificate.json"
$muniFinalFocusedTestPath = Join-Path $muniRepositoryRoot "tests\test_itc2019_decomposed_extended_budget.py"
$muniSharedCoreReceiptPath = Join-Path $muniRepositoryRoot "output\diagnostic-receipts\shared-core-0b6f07a6-windows-itc2019-tests-20260827T024036Z.receipt.json"
$muniSharedCoreStdoutPath = Join-Path $muniRepositoryRoot "output\diagnostic-receipts\shared-core-0b6f07a6-windows-itc2019-tests-20260827T024036Z.stdout.log"
$muniSharedCoreStderrPath = Join-Path $muniRepositoryRoot "output\diagnostic-receipts\shared-core-0b6f07a6-windows-itc2019-tests-20260827T024036Z.stderr.log"
$muniBuilderPath = $PSCommandPath

function Get-MuniSha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-MuniUtf8([string]$Path, [string]$Value) {
    [System.IO.File]::WriteAllText($Path, $Value, $muniUtf8NoBom)
}

function Assert-MuniPinnedFile([string]$Path, [string]$ExpectedHash, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Pinned $Label is absent: $Path"
    }
    $observed = Get-MuniSha256 $Path
    if ($observed -ne $ExpectedHash) {
        throw "Pinned $Label drift: expected $ExpectedHash observed $observed"
    }
}

function Copy-MuniArtifact([string]$SourceName, [string]$DestinationName) {
    [System.IO.File]::Copy(
        (Join-Path $muniV25Root $SourceName),
        (Join-Path $muniV26Root $DestinationName)
    )
}

function Convert-MuniV25Text(
    [string]$SourceName,
    [string]$DestinationName,
    [hashtable]$HashReplacements,
    [scriptblock]$AdditionalTransform = $null
) {
    $sourcePath = Join-Path $muniV25Root $SourceName
    $destinationPath = Join-Path $muniV26Root $DestinationName
    $text = [System.IO.File]::ReadAllText($sourcePath, $muniUtf8NoBom)

    if (-not (
        $text.Contains("muni_v25") -or
        $text.Contains("frontier-v25") -or
        $text.Contains("MUNI-FSPSX v25")
    )) {
        throw "Expected v25 identity token absent from $SourceName"
    }
    $text = $text.Replace("muni_v25", "muni_v26")
    $text = $text.Replace("frontier-v25", "frontier-v26")
    $text = $text.Replace("MUNI-FSPSX v25", "MUNI-FSPSX v26")
    $text = $text.Replace("MUNI v25", "MUNI v26")
    $text = $text.Replace("MUNI_V25", "MUNI_V26")
    $text = $text.Replace("V25", "V26")
    $text = $text.Replace("v25", "v26")

    foreach ($entry in $HashReplacements.GetEnumerator()) {
        if ($text.Contains([string]$entry.Key)) {
            $text = $text.Replace([string]$entry.Key, [string]$entry.Value)
        }
    }
    if ($null -ne $AdditionalTransform) {
        $text = & $AdditionalTransform $text
    }
    if ($text.Contains("muni_v25") -or $text.Contains("frontier-v25")) {
        throw "Stale v25 current-chain identifier remains in $DestinationName"
    }
    Write-MuniUtf8 $destinationPath $text
}

function New-MuniBwrapArgv(
    [string]$HostOutputRoot,
    [string]$InlinePayload,
    [string]$BootstrapHash,
    [string]$InlineHash,
    [string]$Mode,
    [string]$LauncherHash,
    [string]$SupervisorHash,
    [string]$ManifestHash
) {
    $argv = @(
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--ro-bind", "/", "/",
        "--bind", $HostOutputRoot, "/tmp",
        "--dev", "/dev",
        "--proc", "/proc",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "LC_ALL", "C.UTF-8",
        "--setenv", "TZ", "UTC",
        "--cap-drop", "ALL",
        "--chdir", $muniRepositoryWsl,
        "/usr/bin/python3.12", "-I", "-S", "-B", "-c", $InlinePayload,
        "--inline-trust-v1",
        "$muniV26Wsl/planora-muni-fspsx-frontier-v26-bootstrap.py",
        $BootstrapHash,
        $InlineHash,
        $Mode,
        "--expected-launcher-sha256", $LauncherHash,
        "--expected-supervisor-sha256", $SupervisorHash,
        "--expected-manifest-sha256", $ManifestHash
    )
    if ($argv.Count -ne 48) {
        throw "Contained bwrap contract must contain exactly 48 elements; observed $($argv.Count)"
    }
    return ,$argv
}

function Get-MuniNulArgvSha256([object[]]$Argv) {
    $payload = [System.Text.Encoding]::UTF8.GetBytes(
        (($Argv | ForEach-Object { [string]$_ }) -join [char]0) + [char]0
    )
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($hasher.ComputeHash($payload))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
}

$muniBuilderHashAtStart = Get-MuniSha256 $muniBuilderPath

if (-not (Test-Path -LiteralPath $muniV25Root -PathType Container)) {
    throw "MUNI v25 parent chain is absent: $muniV25Root"
}
if (-not (Test-Path -LiteralPath $muniV24Root -PathType Container)) {
    throw "MUNI v24 stale audit chain is absent: $muniV24Root"
}
if (Test-Path -LiteralPath $muniV26Root) {
    throw "Refusing to overwrite an existing MUNI v26 chain: $muniV26Root"
}

Assert-MuniPinnedFile $muniParentBuilderPath $muniParentBuilderHash "MUNI v25 builder"
Assert-MuniPinnedFile $muniParentManifestPath $muniParentManifestHash "MUNI v25 freeze manifest"
Assert-MuniPinnedFile $muniParentCertificatePath $muniParentCertificateHash "MUNI v25 certificate"
Assert-MuniPinnedFile $muniStaleV24BuilderPath $muniStaleV24BuilderHash "stale MUNI v24 builder"
Assert-MuniPinnedFile $muniStaleV24ManifestPath $muniStaleV24ManifestHash "stale MUNI v24 freeze manifest"
Assert-MuniPinnedFile $muniStaleV24CertificatePath $muniStaleV24CertificateHash "stale MUNI v24 certificate"
Assert-MuniPinnedFile $muniFinalFocusedTestPath $muniFinalFocusedTestHash "final shared-core focused test"
Assert-MuniPinnedFile $muniSharedCoreReceiptPath $muniSharedCoreReceiptHash "final shared-core 457-pass receipt"
Assert-MuniPinnedFile $muniSharedCoreStdoutPath $muniSharedCoreStdoutHash "final shared-core 457-pass stdout"
Assert-MuniPinnedFile $muniSharedCoreStderrPath $muniEmptySha256 "final shared-core 457-pass stderr"

$muniParentCertificate = Get-Content -LiteralPath $muniParentCertificatePath -Raw | ConvertFrom-Json
if ($muniParentCertificate.current_source_hashes.itc2019_decomposed -ne $muniFinalSharedCoreHash) {
    throw "MUNI v25 parent does not bind the final shared core"
}
if ($muniParentCertificate.authorization.retained_probe_authorized -ne $false -or
    $muniParentCertificate.authorization.official_launch_authorized -ne $false) {
    throw "MUNI v25 parent unexpectedly authorizes execution"
}

$muniSharedCoreReceipt = Get-Content -LiteralPath $muniSharedCoreReceiptPath -Raw | ConvertFrom-Json
if ($muniSharedCoreReceipt.decision -ne "PASS") {
    throw "Final shared-core receipt is not PASS"
}
if ($muniSharedCoreReceipt.shared_core.sha256 -ne $muniFinalSharedCoreHash -or $muniSharedCoreReceipt.shared_core.size -ne 135880) {
    throw "Final shared-core receipt core identity drift"
}
if ($muniSharedCoreReceipt.focused_test_source.sha256 -ne $muniFinalFocusedTestHash -or $muniSharedCoreReceipt.focused_test_source.size -ne 7138) {
    throw "Final shared-core receipt focused-test identity drift"
}
if (
    $muniSharedCoreReceipt.scope.tests_run -ne 459 -or
    $muniSharedCoreReceipt.scope.passed -ne 457 -or
    $muniSharedCoreReceipt.scope.skipped -ne 2 -or
    $muniSharedCoreReceipt.scope.failures -ne 0 -or
    $muniSharedCoreReceipt.scope.errors -ne 0
) {
    throw "Final shared-core receipt test-count contract drift"
}
if ($muniSharedCoreReceipt.logs.stdout.sha256 -ne $muniSharedCoreStdoutHash -or $muniSharedCoreReceipt.logs.stderr.sha256 -ne $muniEmptySha256) {
    throw "Final shared-core receipt log binding drift"
}

$muniV25Snapshot = [ordered]@{}
foreach ($file in Get-ChildItem -LiteralPath $muniV25Root -File | Sort-Object Name) {
    $muniV25Snapshot[$file.Name] = [ordered]@{
        size_bytes = $file.Length
        sha256 = Get-MuniSha256 $file.FullName
    }
}

$muniV24Snapshot = [ordered]@{}
foreach ($file in Get-ChildItem -LiteralPath $muniV24Root -File | Sort-Object Name) {
    $muniV24Snapshot[$file.Name] = [ordered]@{
        size_bytes = $file.Length
        sha256 = Get-MuniSha256 $file.FullName
    }
}

$muniSharedCoreEvidence = [ordered]@{
    schema = "planora.itc2019.shared-core-external-evidence.v1"
    decision = "PASS"
    receipt_path = "output/diagnostic-receipts/shared-core-0b6f07a6-windows-itc2019-tests-20260827T024036Z.receipt.json"
    receipt_sha256 = $muniSharedCoreReceiptHash
    stdout_path = "output/diagnostic-receipts/shared-core-0b6f07a6-windows-itc2019-tests-20260827T024036Z.stdout.log"
    stdout_sha256 = $muniSharedCoreStdoutHash
    stderr_path = "output/diagnostic-receipts/shared-core-0b6f07a6-windows-itc2019-tests-20260827T024036Z.stderr.log"
    stderr_sha256 = $muniEmptySha256
    shared_core_path = "benchmarks/itc2019_decomposed.py"
    shared_core_size_bytes = 135880
    shared_core_sha256 = $muniFinalSharedCoreHash
    focused_test_path = "tests/test_itc2019_decomposed_extended_budget.py"
    focused_test_size_bytes = 7138
    focused_test_sha256 = $muniFinalFocusedTestHash
    tests_run = 459
    passed = 457
    skipped = 2
    failures = 0
    errors = 0
    expected_skips = @(
        "SIGKILL is not available on this platform",
        "source-derived pinned v35 artifacts are unavailable"
    )
    empty_forbidden_table_protobuf_equivalence = "PASS"
}

$muniStaleV24Evidence = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v26.stale-v24-evidence.v1"
    version = "v24"
    status = "STALE_UNAUTHORIZED_NOT_USED_AS_RUNTIME_PARENT"
    root = $muniV24Wsl
    builder_path = "scripts/build_muni_v24_chain.ps1"
    builder_sha256 = $muniStaleV24BuilderHash
    freeze_manifest_path = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-freeze-manifest.json"
    freeze_manifest_sha256 = $muniStaleV24ManifestHash
    implementation_certificate_path = "$muniV24Wsl/planora-muni-fspsx-frontier-v24-certificate.json"
    implementation_certificate_sha256 = $muniStaleV24CertificateHash
    superseded_shared_core_sha256 = $muniSupersededSharedCoreHash
    final_shared_core_sha256 = $muniFinalSharedCoreHash
    stale_reason = "v24 pins the superseded shared core before the empty-forbidden-table protobuf-equivalence fix"
    post_generation_windows_safe_tests_run = $false
    canonical_read_only_tests_run = $false
    retained_probe_run = $false
    official_launch_run = $false
    retained_probe_authorized = $false
    official_launch_authorized = $false
    artifact_snapshot = $muniV24Snapshot
}

$muniParentManifest = Get-Content -LiteralPath $muniParentManifestPath -Raw | ConvertFrom-Json
$muniSourcePaths = [ordered]@{}
$muniSourceHashes = [ordered]@{}
$muniHashReplacements = @{}
foreach ($row in $muniParentManifest.files) {
    $path = [string]$row.path
    $isRepositorySource = (
        ($path.StartsWith("$muniRepositoryWsl/benchmarks/") -or $path.StartsWith("$muniRepositoryWsl/tests/")) -and
        (-not $path.StartsWith("$muniV25Wsl/")) -and
        $path.EndsWith(".py")
    )
    if (-not $isRepositorySource) {
        continue
    }
    $label = [string]$row.label
    $relativePath = $path.Substring($muniRepositoryWsl.Length + 1).Replace("/", "\")
    $windowsPath = Join-Path $muniRepositoryRoot $relativePath
    if (-not (Test-Path -LiteralPath $windowsPath -PathType Leaf)) {
        throw "MUNI v26 source-closure path is absent: $windowsPath"
    }
    $currentHash = Get-MuniSha256 $windowsPath
    $muniSourcePaths[$label] = $windowsPath
    $muniSourceHashes[$label] = $currentHash
    $muniHashReplacements[[string]$row.sha256] = $currentHash
}
if ($muniSourceHashes.itc2019_decomposed -ne $muniFinalSharedCoreHash) {
    throw "Final shared core drift: expected $muniFinalSharedCoreHash observed $($muniSourceHashes.itc2019_decomposed)"
}

New-Item -ItemType Directory -Path $muniV26Root | Out-Null

Copy-MuniArtifact "planora_muni_v25_benchmarks_stub.py" "planora_muni_v26_benchmarks_stub.py"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v25-generic-validator.py" "planora-muni-fspsx-frontier-v26-generic-validator.py"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v25-minimal-tcb.sha256" "planora-muni-fspsx-frontier-v26-minimal-tcb.sha256"
Copy-MuniArtifact "planora-muni-fspsx-frontier-v25-stdlib.sha256" "planora-muni-fspsx-frontier-v26-stdlib.sha256"
Copy-MuniArtifact "planora-muni-fspsx-v35-derivation-audit-v1.json" "planora-muni-fspsx-v35-derivation-audit-v1.json"

Convert-MuniV25Text `
    "planora-muni-fspsx-frontier-v25-runner.py" `
    "planora-muni-fspsx-frontier-v26-runner.py" `
    $muniHashReplacements
$muniSupervisorTransform = {
    param([string]$Text)

    $replacements = @(
        @(
@'
        and cleanup is not None
        and not cleanup.get("errors")
        and child_report is not None
'@,
@'
        and cleanup is not None
        and not cleanup.get("errors")
        and not cleanup.get("observation_errors")
        and cleanup.get("original_pgid_asserted_empty") is True
        and child_report is not None
'@
        ),
        @(
@'
def proc_stat_identity(pid: int) -> tuple[int, int, int] | None:
    try:
        value = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    closing = value.rfind(")")
    if closing < 0:
        return None
    fields = value[closing + 2 :].split()
    if len(fields) < 20:
        return None
    try:
        return int(fields[2]), int(fields[3]), int(fields[19])
    except ValueError:
        return None


def process_group_snapshot(
    pgid: int,
) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    """Capture member PID identities in the same scan that admits the PGID."""
    result: list[tuple[int, tuple[int, int, int]]] = []
    try:
        entries = tuple(os.scandir("/proc"))
    except OSError:
        return ()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        identity = proc_stat_identity(int(entry.name))
        if identity is not None and identity[0] == pgid:
            result.append((int(entry.name), identity))
    return tuple(sorted(result))
'@,
@'
class ProcObservationError(RuntimeError):
    """A /proc observation failed without proving process disappearance."""


def _confirmed_proc_disappearance(exc: OSError) -> bool:
    return exc.errno in {errno.ENOENT, errno.ESRCH}


def proc_stat_identity(pid: int) -> tuple[int, int, int] | None:
    """Return None only when /proc confirms ENOENT/ESRCH disappearance."""

    path = Path("/proc") / str(pid) / "stat"
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        if _confirmed_proc_disappearance(exc):
            return None
        raise ProcObservationError(
            f"proc stat observation failed for PID {pid}: "
            f"{type(exc).__name__}:errno={exc.errno}"
        ) from exc
    closing = value.rfind(")")
    if closing < 0:
        raise ProcObservationError(
            f"proc stat malformed for PID {pid}: missing command terminator"
        )
    fields = value[closing + 2 :].split()
    if len(fields) < 20:
        raise ProcObservationError(
            f"proc stat malformed for PID {pid}: expected at least 20 tail fields"
        )
    try:
        return int(fields[2]), int(fields[3]), int(fields[19])
    except ValueError as exc:
        raise ProcObservationError(
            f"proc stat malformed for PID {pid}: non-integer identity field"
        ) from exc


def process_group_snapshot(
    pgid: int,
) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    """Capture identities; observation failure is never an empty-group proof."""

    result: list[tuple[int, tuple[int, int, int]]] = []
    try:
        entries = tuple(os.scandir("/proc"))
    except OSError as exc:
        raise ProcObservationError(
            f"proc enumeration failed for PGID {pgid}: "
            f"{type(exc).__name__}:errno={exc.errno}"
        ) from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            identity = proc_stat_identity(pid)
        except ProcObservationError as exc:
            raise ProcObservationError(
                f"proc identity scan failed for PID {pid} in PGID {pgid}"
            ) from exc
        if identity is not None and identity[0] == pgid:
            result.append((pid, identity))
    return tuple(sorted(result))
'@
        ),
        @(
@'
    before = proc_stat_identity(generation.leader_pid)
    if before != generation.leader_identity:
        generation.seal("leader_generation_absent_before_snapshot")
        return ()
    candidate = process_group_snapshot(generation.pgid)
    after = proc_stat_identity(generation.leader_pid)
    if after != generation.leader_identity:
        generation.seal("leader_generation_absent_after_snapshot")
        return ()
'@,
@'
    try:
        before = proc_stat_identity(generation.leader_pid)
    except ProcObservationError:
        generation.seal("leader_generation_observation_failed_before_snapshot")
        raise
    if before != generation.leader_identity:
        generation.seal("leader_generation_absent_before_snapshot")
        return ()
    try:
        candidate = process_group_snapshot(generation.pgid)
    except ProcObservationError:
        generation.seal("process_group_observation_failed_during_snapshot")
        raise
    try:
        after = proc_stat_identity(generation.leader_pid)
    except ProcObservationError:
        generation.seal("leader_generation_observation_failed_after_snapshot")
        raise
    if after != generation.leader_identity:
        generation.seal("leader_generation_absent_after_snapshot")
        return ()
'@
        ),
        @(
@'
            "identity_mismatch_pids": (),
            "pidfd_open_failures": (),
'@,
@'
            "identity_mismatch_pids": (),
            "identity_observation_failures": (),
            "pidfd_open_failures": (),
'@
        ),
        @(
@'
    identity_mismatches: list[int] = []
    pidfd_open_failures: list[dict[str, int]] = []
'@,
@'
    identity_mismatches: list[int] = []
    identity_observation_failures: list[dict[str, object]] = []
    pidfd_open_failures: list[dict[str, int]] = []
'@
        ),
        @(
@'
            replayed_identity = proc_stat_identity(pid)
            if replayed_identity is None:
'@,
@'
            try:
                replayed_identity = proc_stat_identity(pid)
            except ProcObservationError as exc:
                identity_observation_failures.append({
                    "pid": pid,
                    "error": f"{type(exc).__name__}:{exc}",
                })
                continue
            if replayed_identity is None:
'@
        ),
        @(
@'
        "identity_mismatch_pids": tuple(identity_mismatches),
        "pidfd_open_failures": tuple(pidfd_open_failures),
'@,
@'
        "identity_mismatch_pids": tuple(identity_mismatches),
        "identity_observation_failures": tuple(identity_observation_failures),
        "pidfd_open_failures": tuple(pidfd_open_failures),
'@
        )
    )
    foreach ($pair in $replacements) {
        $old = [string]$pair[0]
        $new = [string]$pair[1]
        if (-not $Text.Contains($old)) {
            throw "Required v26 supervisor transform seam is absent"
        }
        $Text = $Text.Replace($old, $new)
    }

    $stopStart = $Text.IndexOf("def stop_process_group(")
    $stopEnd = $Text.IndexOf("$([char]10)$([char]10)def admit_spawned_process_group(", $stopStart)
    if ($stopStart -lt 0 -or $stopEnd -lt 0) {
        throw "Required v26 stop_process_group replacement seam is absent"
    }
    $stopReplacement = @'
def stop_process_group(
    process: subprocess.Popen[bytes],
    generation: ProcessGroupGeneration,
    pidfd: int | None,
) -> dict[str, object]:
    """Drain admitted identities while never converting uncertainty to absence."""

    pgid = generation.pgid
    if process.pid != generation.leader_pid:
        raise RuntimeError("Popen leader does not match admitted generation")
    observation_errors: list[str] = []

    def record_observation(stage: str, exc: BaseException) -> None:
        value = f"{stage}:{type(exc).__name__}:{exc}"
        if value not in observation_errors:
            observation_errors.append(value)

    try:
        observed = proc_stat_identity(process.pid)
    except ProcObservationError as exc:
        record_observation("leader_before_stop", exc)
        observed = None
        identity_changed = False
        generation.seal("leader_generation_observation_failed_before_stop")
    else:
        identity_changed = observed not in (None, generation.leader_identity)
        if identity_changed:
            generation.seal("leader_generation_identity_changed_before_stop")

    def observe_wait(timeout: float, stage: str) -> tuple[int | None, bool]:
        try:
            return process.wait(timeout=timeout), True
        except subprocess.TimeoutExpired:
            return None, False
        except (OSError, ValueError) as exc:
            record_observation(stage, exc)
            return None, False

    def safe_refresh(stage: str) -> None:
        try:
            refresh_process_group_generation(generation)
        except ProcObservationError as exc:
            record_observation(stage, exc)
            generation.seal(f"{stage}_observation_failed")

    def cleanup_snapshot(stage: str) -> tuple[tuple[int, tuple[int, int, int]], ...]:
        snapshot: list[tuple[int, tuple[int, int, int]]] = []
        for admitted_pid, admitted_identity in sorted(generation.members.items()):
            try:
                current = proc_stat_identity(admitted_pid)
            except ProcObservationError as exc:
                record_observation(f"{stage}:pid={admitted_pid}", exc)
                snapshot.append((admitted_pid, admitted_identity))
                continue
            if current is None:
                continue
            if current != admitted_identity:
                generation.seal("admitted_member_identity_changed_during_cleanup")
                continue
            snapshot.append((admitted_pid, admitted_identity))
        return tuple(snapshot)

    def record_signal_observation(stage: str, result: Mapping[str, object]) -> None:
        for row in result.get("identity_observation_failures", ()):
            record_observation(
                f"{stage}:pid={row.get('pid')}",
                RuntimeError(str(row.get("error"))),
            )

    safe_refresh("final_admission_refresh")
    _initial_returncode, known_leader_reaped = observe_wait(0, "initial_wait")
    snapshot_before = cleanup_snapshot("before_term_snapshot")
    members_before = tuple(pid for pid, _identity in snapshot_before)
    leader_exited_before_cleanup = process.returncode is not None
    if known_leader_reaped and process.pid in members_before:
        raise RuntimeError("reaped process-group leader PID was reused")
    term_signal = signal_process_group_snapshot(pgid, snapshot_before, signal.SIGTERM)
    record_signal_observation("term_signal", term_signal)
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    group_observed_empty = False
    while time.monotonic() < deadline:
        safe_refresh("grace_refresh")
        if process.returncode is None:
            observe_wait(0, "grace_wait")
        current_snapshot = cleanup_snapshot("grace_snapshot")
        if not current_snapshot and not observation_errors:
            group_observed_empty = True
            break
        time.sleep(0.05)
    survivor_snapshot = () if group_observed_empty else cleanup_snapshot("pre_kill_snapshot")
    survivors = tuple(pid for pid, _identity in survivor_snapshot)
    kill_signal = signal_process_group_snapshot(pgid, survivor_snapshot, signal.SIGKILL)
    record_signal_observation("kill_signal", kill_signal)
    observed_returncode, _final_wait_completed = observe_wait(
        TERMINATION_GRACE_SECONDS, "final_wait"
    )
    returncode = observed_returncode if observed_returncode is not None else process.returncode
    final_snapshot = cleanup_snapshot("final_admitted_snapshot")
    final_admitted_survivors = tuple(pid for pid, _identity in final_snapshot)
    try:
        current_group = process_group_snapshot(pgid)
    except ProcObservationError as exc:
        record_observation("final_process_group_snapshot", exc)
        current_group = None
        unregistered_current_members: tuple[int, ...] = ()
    else:
        unregistered_current_members = tuple(
            current_pid
            for current_pid, identity in current_group
            if generation.members.get(current_pid) != identity
        )
    original_pgid_asserted_empty = bool(
        current_group is not None
        and not observation_errors
        and not final_admitted_survivors
        and not unregistered_current_members
    )
    cleanup_errors = list(observation_errors)
    if final_admitted_survivors or unregistered_current_members:
        cleanup_errors.append(
            "process-group cleanup left admitted or unregistered survivors: "
            + ",".join(
                str(item)
                for item in (*final_admitted_survivors, *unregistered_current_members)
            )
        )
    if not original_pgid_asserted_empty:
        cleanup_errors.append(
            "process-group empty assertion rejected due to survivors or observation uncertainty"
        )
    return {
        "returncode": returncode,
        "members_before": members_before,
        "term_survivors": survivors,
        "final_survivors": final_admitted_survivors,
        "unregistered_current_members": unregistered_current_members,
        "leader_identity_changed": identity_changed,
        "leader_identity_available": observed is not None,
        "pidfd_evidence_available": pidfd is not None,
        "known_leader_reaped_before_group_interpretation": known_leader_reaped,
        "pid_reuse_guard_passed": bool(
            current_group is not None
            and not observation_errors
            and not unregistered_current_members
        ),
        "leader_exited_before_cleanup": leader_exited_before_cleanup,
        "original_pgid_asserted_empty": original_pgid_asserted_empty,
        "group_observed_empty_before_any_later_signal": bool(
            group_observed_empty and not observation_errors
        ),
        "term_signal": term_signal,
        "kill_signal": kill_signal,
        "numeric_pgid_signal_sent": False,
        "generation_registry_size": len(generation.members),
        "generation_registry_sealed": generation.sealed,
        "generation_registry_seal_reason": generation.seal_reason,
        "generation_refresh_count": generation.refresh_count,
        "observation_errors": tuple(observation_errors),
        "errors": tuple(cleanup_errors),
    }
'@
    $Text = $Text.Substring(0, $stopStart) + $stopReplacement + $Text.Substring($stopEnd)
    return $Text
}
Convert-MuniV25Text `
    "planora-muni-fspsx-frontier-v25-supervisor.py" `
    "planora-muni-fspsx-frontier-v26-supervisor.py" `
    $muniHashReplacements `
    $muniSupervisorTransform
Convert-MuniV25Text `
    "planora-muni-fspsx-frontier-v25-bootstrap.py" `
    "planora-muni-fspsx-frontier-v26-bootstrap.py" `
    $muniHashReplacements
Convert-MuniV25Text `
    "planora-muni-fspsx-frontier-v25-inline-trust-root.txt" `
    "planora-muni-fspsx-frontier-v26-inline-trust-root.txt" `
    $muniHashReplacements
Convert-MuniV25Text `
    "planora-muni-fspsx-frontier-v25-launcher.sh" `
    "planora-muni-fspsx-frontier-v26-launcher.sh" `
    $muniHashReplacements

$muniTestTransform = {
    param([string]$Text)

    $Text = $Text.Replace(
        "import base64$([char]10)",
        "import ast$([char]10)import base64$([char]10)"
    )
    $loaderNeedle = @'
runner = load(RUNNER, "planora_muni_v26_runner_tests")
supervisor = load(SUPERVISOR, "planora_muni_v26_supervisor_tests")
bootstrap = load(BOOTSTRAP, "planora_muni_v26_bootstrap_tests")
'@
    $loaderReplacement = @'
def load_windows_safe_supervisor_subset(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = {
        "ProcObservationError",
        "ProcessStatusMemoryUnavailable",
        "ProcessGroupGeneration",
        "_confirmed_proc_disappearance",
        "proc_stat_identity",
        "process_group_snapshot",
        "refresh_process_group_generation",
        "admitted_generation_snapshot",
        "read_process_memory_status_once",
        "identity_pinned_process_memory",
        "identity_pinned_process_memory_snapshot",
        "signal_process_group_snapshot",
        "stop_process_group",
        "sealed_import_probe_accepted",
    }
    body = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
        )
        or (
            isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and node.name in wanted
        )
    ]
    selected = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    module = types.ModuleType("planora_muni_v26_supervisor_windows_static_tests")
    signal_compat = types.SimpleNamespace(
        **{name: getattr(signal, name) for name in dir(signal) if not name.startswith("__")}
    )
    if not hasattr(signal_compat, "SIGKILL"):
        signal_compat.SIGKILL = 9
    module.__dict__.update({
        "errno": errno,
        "os": os,
        "Path": Path,
        "signal": signal_compat,
        "subprocess": subprocess,
        "time": time,
        "TERMINATION_GRACE_SECONDS": 5.0,
        "SEALED_IMPORT_PROBE_WALL_SECONDS": 180.0,
        "WHOLE_LAUNCH_MEMORY_CAP_KIB": 700_000,
    })
    exec(compile(selected, str(path), "exec"), module.__dict__)
    return module


if os.name == "nt":
    runner = types.SimpleNamespace()
    supervisor = load_windows_safe_supervisor_subset(SUPERVISOR)
    bootstrap = types.SimpleNamespace()
else:
    runner = load(RUNNER, "planora_muni_v26_runner_tests")
    supervisor = load(SUPERVISOR, "planora_muni_v26_supervisor_tests")
    bootstrap = load(BOOTSTRAP, "planora_muni_v26_bootstrap_tests")
'@
    if (-not $Text.Contains($loaderNeedle)) {
        throw "Windows-safe v26 test loader seam is absent"
    }
    $Text = $Text.Replace($loaderNeedle, $loaderReplacement)

    $Text = $Text.Replace(
        "test_direct_v23_parent_and_exact_bwrap_contract",
        "test_direct_v25_parent_and_exact_bwrap_contract"
    )
    $Text = $Text.Replace(
        'self.assertEqual(parent["version"], "v23")',
        'self.assertEqual(parent["version"], "v25")'
    )
    $Text = $Text.Replace(
        "c52265500d9dd112f0ed73e3e89c45e965c122eb54bc530624f9c6c7e7151d87",
        $muniParentManifestHash
    )
    $Text = $Text.Replace(
        "114dcaf09b3eca05add37cdc7bb26aa35320118d17610f009a09690c2154679f",
        $muniParentCertificateHash
    )

    $classNeedle = "class StaticContractTests(unittest.TestCase):`n"
    $contractTests = @'
class V26ProcObservationRegressionTests(unittest.TestCase):
    @staticmethod
    def stat_text(pid: int, pgid: int, sid: int, start: int) -> str:
        return f"{pid} (cmd) S 1 {pgid} {sid} " + ("0 " * 15) + f"{start}\n"

    def test_proc_stat_identity_returns_none_only_for_confirmed_disappearance(self) -> None:
        for failure in (
            FileNotFoundError(errno.ENOENT, "gone"),
            ProcessLookupError(errno.ESRCH, "gone"),
        ):
            with self.subTest(errno=failure.errno), mock.patch.object(
                supervisor.Path, "read_text", side_effect=failure
            ):
                self.assertIsNone(supervisor.proc_stat_identity(41))

    def test_proc_stat_identity_rejects_permission_and_io_failures(self) -> None:
        for failure in (
            PermissionError(errno.EACCES, "denied"),
            OSError(errno.EIO, "io"),
        ):
            with self.subTest(errno=failure.errno), mock.patch.object(
                supervisor.Path, "read_text", side_effect=failure
            ):
                with self.assertRaises(supervisor.ProcObservationError):
                    supervisor.proc_stat_identity(42)

    def test_proc_stat_identity_rejects_every_malformed_identity_shape(self) -> None:
        malformed = (
            "42 malformed",
            "42 (cmd) S 1 42",
            "42 (cmd) S 1 bad 42 " + ("0 " * 15) + "100\n",
        )
        for value in malformed:
            with self.subTest(value=value), mock.patch.object(
                supervisor.Path, "read_text", return_value=value
            ):
                with self.assertRaises(supervisor.ProcObservationError):
                    supervisor.proc_stat_identity(42)

    def test_process_group_enumeration_failure_is_not_empty(self) -> None:
        with mock.patch.object(
            supervisor.os,
            "scandir",
            side_effect=OSError(errno.EIO, "enumeration failed"),
        ):
            with self.assertRaises(supervisor.ProcObservationError):
                supervisor.process_group_snapshot(51)

    def test_process_group_identity_read_failure_is_not_empty(self) -> None:
        entry = types.SimpleNamespace(name="51")
        with (
            mock.patch.object(supervisor.os, "scandir", return_value=(entry,)),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=supervisor.ProcObservationError("identity failed"),
            ),
        ):
            with self.assertRaises(supervisor.ProcObservationError):
                supervisor.process_group_snapshot(51)

    def test_memory_accounting_rejects_observation_uncertainty(self) -> None:
        identity = (61, 61, 100)
        generation = supervisor.ProcessGroupGeneration(61, 61, identity)
        with mock.patch.object(
            supervisor,
            "proc_stat_identity",
            side_effect=supervisor.ProcObservationError("memory identity uncertain"),
        ):
            with self.assertRaises(supervisor.ProcObservationError):
                supervisor.identity_pinned_process_memory_snapshot(
                    generation,
                    supervisor_pid=99,
                    supervisor_identity=(99, 99, 200),
                )

    def test_signal_continues_after_one_identity_observation_failure(self) -> None:
        first = (71, (70, 70, 100))
        second = (72, (70, 70, 200))
        with (
            mock.patch.object(
                supervisor.os, "pidfd_open", side_effect=(81, 82), create=True
            ),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=(
                    supervisor.ProcObservationError("first uncertain"),
                    second[1],
                ),
            ),
            mock.patch.object(supervisor.os, "close"),
            mock.patch.object(
                supervisor.signal, "pidfd_send_signal", create=True
            ) as send,
        ):
            result = supervisor.signal_process_group_snapshot(
                70, (first, second), signal.SIGTERM
            )
        self.assertEqual(
            tuple(row["pid"] for row in result["identity_observation_failures"]),
            (71,),
        )
        self.assertEqual(result["signaled_pids"], (72,))
        send.assert_called_once_with(82, signal.SIGTERM, None, 0)

    def test_cleanup_retains_admitted_members_and_rejects_false_empty(self) -> None:
        leader = (80, 80, 100)
        member = (80, 80, 200)
        generation = supervisor.ProcessGroupGeneration(80, 80, leader)
        generation.members[81] = member
        process = mock.Mock(pid=80, returncode=None)
        process.wait.side_effect = subprocess.TimeoutExpired(("child",), 0)
        signal_results = []

        def capture_signal(_pgid, snapshot, signum):
            signal_results.append((signum, snapshot))
            return {
                "identity_observation_failures": (),
                "numeric_pgid_signal_sent": False,
            }

        identities = {80: leader, 81: member}
        with (
            mock.patch.object(
                supervisor,
                "refresh_process_group_generation",
                side_effect=supervisor.ProcObservationError("enumeration uncertain"),
            ),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=lambda pid: identities[pid],
            ),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                side_effect=supervisor.ProcObservationError("final scan uncertain"),
            ),
            mock.patch.object(
                supervisor, "signal_process_group_snapshot", side_effect=capture_signal
            ),
            mock.patch.object(supervisor, "TERMINATION_GRACE_SECONDS", 0.0),
        ):
            cleanup = supervisor.stop_process_group(process, generation, None)
        self.assertEqual(signal_results[0][1], ((80, leader), (81, member)))
        self.assertEqual(signal_results[1][1], ((80, leader), (81, member)))
        self.assertTrue(cleanup["observation_errors"])
        self.assertFalse(cleanup["original_pgid_asserted_empty"])
        self.assertFalse(cleanup["pid_reuse_guard_passed"])
        self.assertTrue(cleanup["errors"])

    def test_probe_acceptance_rejects_observation_uncertainty(self) -> None:
        accepted = supervisor.sealed_import_probe_accepted(
            errors=(),
            stop_reason="normal_exit",
            child_exit=0,
            cleanup={
                "errors": (),
                "observation_errors": ("proc uncertain",),
                "original_pgid_asserted_empty": True,
            },
            child_report={"status": "PASS"},
            final_elapsed_seconds=1.0,
            peak_whole_memory_kib=1,
        )
        self.assertFalse(accepted)


class StaticContractTests(unittest.TestCase):
    def test_v26_final_core_parent_and_authorization_state(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json").read_bytes()
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json").read_bytes()
        )
        self.assertEqual(
            certificate["current_source_hashes"]["itc2019_decomposed"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )
        self.assertEqual(manifest["parent_chain"]["version"], "v25")
        self.assertEqual(
            manifest["parent_chain"]["builder_sha256"],
            "d6b379e7307e803023d9f6726f36a4cf7d69411f1a6c9f228cc9edd51ea3c028",
        )
        finding = certificate["parent_v25_review_finding"]
        self.assertEqual(finding["status"], "FIXED_IN_V26_PENDING_STATIC_VERIFICATION")
        self.assertIn("observation uncertainty", finding["summary"])
        self.assertFalse(finding["v25_modified"])
        stale = certificate["stale_v24_evidence"]
        self.assertEqual(stale["status"], "STALE_UNAUTHORIZED_NOT_USED_AS_RUNTIME_PARENT")
        self.assertEqual(
            stale["superseded_shared_core_sha256"],
            "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
        )
        self.assertEqual(
            stale["freeze_manifest_sha256"],
            "66a8560e20919cc5825c6c3dc7817b639687fe26ca1088bda21bc6d7eabf0469",
        )
        self.assertFalse(stale["retained_probe_authorized"])
        self.assertFalse(stale["official_launch_authorized"])
        shared = certificate["shared_core_verification_evidence"]
        self.assertEqual(shared["decision"], "PASS")
        self.assertEqual(shared["passed"], 457)
        self.assertEqual(shared["skipped"], 2)
        self.assertEqual(
            shared["receipt_sha256"],
            "fa12c7ac258331407f2882cd69f4ff1e5d779dc955a77971c732c45699d1ed55",
        )
        self.assertEqual(
            shared["focused_test_sha256"],
            "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d",
        )
        self.assertEqual(certificate["status"], "NO_GO_PENDING_INDEPENDENT_REVIEW")
        self.assertFalse(certificate["authorization"]["retained_probe_authorized"])
        self.assertFalse(certificate["authorization"]["official_launch_authorized"])

    def test_v26_preserves_v25_caps_and_mode_separation(self) -> None:
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json").read_bytes()
        )
        resource = certificate["resource_contract"]
        self.assertEqual(resource["launch_memavailable_floor_kib"], 1_900_000)
        self.assertEqual(resource["runtime_memavailable_floor_kib"], 650_000)
        self.assertEqual(resource["process_group_memory_cap_kib"], 700_000)
        self.assertEqual(resource["whole_launch_memory_cap_kib"], 700_000)
        self.assertEqual(resource["runner_seconds"], 600.0)
        self.assertEqual(resource["supervisor_wall_seconds"], 630.0)
        self.assertEqual(resource["sealed_import_probe_wall_seconds"], 180.0)
        self.assertEqual(resource["probe_outer_timeout_seconds"], 210)
        self.assertEqual(resource["official_outer_timeout_seconds"], 660)
        probe = certificate["contained_bwrap_contract"]["sealed_import_probe"]
        launch = certificate["contained_bwrap_contract"]["official_launch"]
        self.assertEqual(len(probe["argv"]), 48)
        self.assertEqual(len(launch["argv"]), 48)
        self.assertNotEqual(probe["argv_nul_sha256"], launch["argv_nul_sha256"])
        self.assertIn("--sealed-import-probe", probe["argv"])
        self.assertNotIn("--launch", probe["argv"])
        self.assertIn("--launch", launch["argv"])
        self.assertNotIn("--sealed-import-probe", launch["argv"])
        probe_text = "\0".join(probe["argv"])
        for forbidden in ("muni-fspsx-fal17.xml", "progress.json", "checkpoint", "--resume"):
            self.assertNotIn(forbidden, probe_text)

'@
    if (-not $Text.Contains($classNeedle)) {
        throw "Static contract class seam absent from transformed v26 tests"
    }
    $Text = $Text.Replace($classNeedle, $contractTests)
    $mainNeedle = @'
    else:
        unittest.main(verbosity=2)
'@
    $mainReplacement = @'
    elif os.name == "nt":
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromTestCase(V26ProcObservationRegressionTests))
        suite.addTest(StaticContractTests("test_v26_final_core_parent_and_authorization_state"))
        suite.addTest(StaticContractTests("test_v26_preserves_v25_caps_and_mode_separation"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    else:
        unittest.main(verbosity=2)
'@
    if (-not $Text.Contains($mainNeedle)) {
        throw "Windows-safe v26 test main seam is absent"
    }
    return $Text.Replace($mainNeedle, $mainReplacement)
}
Convert-MuniV25Text `
    "planora-muni-fspsx-frontier-v25-tests.py" `
    "planora-muni-fspsx-frontier-v26-tests.py" `
    $muniHashReplacements `
    $muniTestTransform

$muniPaths = [ordered]@{
    bootstrap = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-bootstrap.py"
    inline_trust_payload = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-inline-trust-root.txt"
    launcher = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-launcher.sh"
    supervisor = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-supervisor.py"
    runner = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-runner.py"
    v26_adversarial_tests = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-tests.py"
    generic_validator = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-generic-validator.py"
    stdlib_manifest = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-stdlib.sha256"
    minimal_tcb_manifest = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-minimal-tcb.sha256"
    benchmarks = Join-Path $muniV26Root "planora_muni_v26_benchmarks_stub.py"
    staged_audit_copy = Join-Path $muniV26Root "planora-muni-fspsx-v35-derivation-audit-v1.json"
}
$muniArtifactHashes = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $muniArtifactHashes[$entry.Key] = Get-MuniSha256 $entry.Value
}

$muniManifestText = [System.IO.File]::ReadAllText($muniParentManifestPath, $muniUtf8NoBom)
$muniManifestText = $muniManifestText.Replace("muni_v25", "muni_v26")
$muniManifestText = $muniManifestText.Replace("frontier-v25", "frontier-v26")
$muniManifestText = $muniManifestText.Replace("V25", "V26")
$muniManifestText = $muniManifestText.Replace("v25", "v26")
foreach ($entry in $muniHashReplacements.GetEnumerator()) {
    $muniManifestText = $muniManifestText.Replace([string]$entry.Key, [string]$entry.Value)
}
$muniManifest = $muniManifestText | ConvertFrom-Json

$muniManifest.code_review_certificate_path = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-certificate.json"
$muniManifest.created_for = "v26-final-shared-core-freeze-pending-independent-review"
$muniManifest.PSObject.Properties.Remove("parent_chain")
$muniManifest.PSObject.Properties.Remove("outer_bwrap_contract")
$muniManifest.PSObject.Properties.Remove("stale_v24_evidence")
$muniManifest.PSObject.Properties.Remove("shared_core_verification_evidence")

$muniFilePathByLabel = @{
    bootstrap = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-bootstrap.py"
    inline_trust_payload = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-inline-trust-root.txt"
    launcher = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-launcher.sh"
    supervisor = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-supervisor.py"
    runner = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-runner.py"
    v26_adversarial_tests = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-tests.py"
    generic_validator = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-generic-validator.py"
    stdlib_manifest = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-stdlib.sha256"
    minimal_tcb_manifest = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-minimal-tcb.sha256"
    benchmarks = "$muniV26Wsl/planora_muni_v26_benchmarks_stub.py"
}
foreach ($row in $muniManifest.files) {
    $label = [string]$row.label
    if ($muniFilePathByLabel.ContainsKey($label)) {
        $row.path = $muniFilePathByLabel[$label]
        $row.sha256 = $muniArtifactHashes[$label]
    }
    if ($muniSourceHashes.Contains($label)) {
        $row.sha256 = $muniSourceHashes[$label]
    }
}

$muniManifest.inline_trust_root.bootstrap_sha256 = $muniArtifactHashes.bootstrap
$muniManifest.inline_trust_root.inline_payload_sha256 = $muniArtifactHashes.inline_trust_payload
$muniManifest.stdlib_trust_boundary.minimal_tcb_manifest_path = $muniFilePathByLabel.minimal_tcb_manifest
$muniManifest.verification = [ordered]@{
    build_manifest_rows_replayed = $true
    powershell_parse = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    bash_syntax = "PENDING_CANONICAL_READ_ONLY_ENVIRONMENT"
    python_ast = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    windows_safe_tests = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    canonical_read_only_tests = "NOT_RUN"
    sealed_import_probe = "NOT_RUN"
    official_input_opened = $false
    progress_or_checkpoint_opened = $false
    solver_run = $false
}
$muniManifest | Add-Member -NotePropertyName parent_chain -NotePropertyValue ([ordered]@{
    version = "v25"
    root = $muniV25Wsl
    builder_sha256 = $muniParentBuilderHash
    freeze_manifest_sha256 = $muniParentManifestHash
    implementation_certificate_sha256 = $muniParentCertificateHash
    inherited_historical_claims_reconstructed = $false
})
$muniParentReviewFinding = [ordered]@{
    status = "FIXED_IN_V26_PENDING_STATIC_VERIFICATION"
    summary = "v25 could convert /proc observation uncertainty into process absence or an empty group"
    v25_modified = $false
    affected_boundaries = @(
        "process_group_snapshot enumeration"
        "proc_stat_identity permission malformed and IO failures"
        "memory accounting disappearance classification"
        "cleanup continuation and empty-group assertion"
        "sealed import probe acceptance"
    )
    v26_contract = @(
        "None means only confirmed ENOENT or ESRCH disappearance"
        "all other observation failures raise ProcObservationError"
        "cleanup retains and retries every previously admitted identity-pinned member"
        "observation uncertainty rejects empty-group proof and probe acceptance"
    )
}
$muniManifest | Add-Member -NotePropertyName parent_v25_review_finding -NotePropertyValue $muniParentReviewFinding
$muniManifest | Add-Member -NotePropertyName inherited_parent_v23_rejection_evidence -NotePropertyValue $muniParentCertificate.parent_v23_rejection_evidence
$muniManifest | Add-Member -NotePropertyName stale_v24_evidence -NotePropertyValue $muniStaleV24Evidence
$muniManifest | Add-Member -NotePropertyName shared_core_verification_evidence -NotePropertyValue $muniSharedCoreEvidence

$muniSymbolicArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" "{INLINE_TRUST_PAYLOAD}" "{BOOTSTRAP_SHA256}" `
    "{INLINE_TRUST_SHA256}" "{EXECUTION_MODE}" "{LAUNCHER_SHA256}" `
    "{SUPERVISOR_SHA256}" "{FREEZE_MANIFEST_SHA256}"
$muniManifest | Add-Member -NotePropertyName outer_bwrap_contract -NotePropertyValue ([ordered]@{
    schema = "planora.muni-fspsx.frontier-v26.bwrap-argv.v1"
    contained_argv_count = 48
    argv_shape = $muniSymbolicArgv
    probe_outer_timeout_seconds = 210
    official_outer_timeout_seconds = 660
    host_output_root_is_fresh_private_and_bound_as_tmp = $true
})

$muniManifestPath = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-freeze-manifest.json"
Write-MuniUtf8 $muniManifestPath (($muniManifest | ConvertTo-Json -Depth 20) + "`n")
$muniManifestHash = Get-MuniSha256 $muniManifestPath

$muniInlinePayload = [System.IO.File]::ReadAllText($muniPaths.inline_trust_payload, $muniUtf8NoBom)
$muniProbeArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" $muniInlinePayload $muniArtifactHashes.bootstrap `
    $muniArtifactHashes.inline_trust_payload "--sealed-import-probe" `
    $muniArtifactHashes.launcher $muniArtifactHashes.supervisor $muniManifestHash
$muniOfficialArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" $muniInlinePayload $muniArtifactHashes.bootstrap `
    $muniArtifactHashes.inline_trust_payload "--launch" `
    $muniArtifactHashes.launcher $muniArtifactHashes.supervisor $muniManifestHash

$muniCertificateFiles = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $name = Split-Path -Leaf $entry.Value
    $muniCertificateFiles["$muniV26Wsl/$name"] = $muniArtifactHashes[$entry.Key]
}
$muniCertificateFiles["$muniV26Wsl/planora-muni-fspsx-frontier-v26-freeze-manifest.json"] = $muniManifestHash

$muniCertificate = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v26.implementation-certificate.v1"
    status = "NO_GO_PENDING_INDEPENDENT_REVIEW"
    diagnostic_launch_status = "NO_GO_PENDING_INDEPENDENT_REVIEW"
    official_launch_status = "NO_GO_PENDING_RETAINED_PROBE_AND_INDEPENDENT_AUTHORIZATION"
    authorization = [ordered]@{
        retained_probe_authorized = $false
        official_launch_authorized = $false
        authorization_requires_new_external_review = $true
        inherited_v25_authorization = $false
    }
    canonical_certificate_path = "$muniV26Wsl/planora-muni-fspsx-frontier-v26-certificate.json"
    builder_source = [ordered]@{
        path = "scripts/build_muni_v26_chain.ps1"
        sha256 = $muniBuilderHashAtStart
    }
    scope = "fresh v26 chain over final current Planora source closure; v25 is the runtime parent and v24 is preserved as stale audit evidence; no WSL, official input, progress, checkpoint, canonical read-only suite, retained probe, or solver was opened or run by the builder"
    parent_chain = [ordered]@{
        version = "v25"
        builder_sha256 = $muniParentBuilderHash
        freeze_manifest_sha256 = $muniParentManifestHash
        implementation_certificate_sha256 = $muniParentCertificateHash
        inherited_historical_claims_reconstructed = $false
    }
    parent_v25_review_finding = $muniParentReviewFinding
    parent_v23_rejection_evidence = $muniParentCertificate.parent_v23_rejection_evidence
    stale_v24_evidence = $muniStaleV24Evidence
    shared_core_verification_evidence = $muniSharedCoreEvidence
    files = $muniCertificateFiles
    current_source_hashes = $muniSourceHashes
    resource_contract = [ordered]@{
        launch_memavailable_floor_kib = 1900000
        runtime_memavailable_floor_kib = 650000
        process_group_memory_cap_kib = 700000
        whole_launch_memory_cap_kib = 700000
        runner_seconds = 600.0
        supervisor_wall_seconds = 630.0
        sealed_import_probe_wall_seconds = 180.0
        probe_outer_timeout_seconds = 210
        official_outer_timeout_seconds = 660
        host_swap_counters_kill_enabled = $false
    }
    contained_bwrap_contract = [ordered]@{
        schema = "planora.muni-fspsx.frontier-v26.bwrap-argv.v1"
        host_output_root_token = "{HOST_OUTPUT_ROOT}"
        sealed_import_probe = [ordered]@{
            argv_count = $muniProbeArgv.Count
            argv_nul_sha256 = Get-MuniNulArgvSha256 $muniProbeArgv
            argv = $muniProbeArgv
        }
        official_launch = [ordered]@{
            argv_count = $muniOfficialArgv.Count
            argv_nul_sha256 = Get-MuniNulArgvSha256 $muniOfficialArgv
            argv = $muniOfficialArgv
        }
    }
    implementation_verification = [ordered]@{
        builder_source_hash_stability = "PASS"
        parent_v25_builder_manifest_certificate = "PASS"
        parent_v25_review_blockers_addressed = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        stale_v24_builder_manifest_certificate = "PASS_STALE_NOT_INHERITED"
        final_shared_core_457_pass_receipt = "PASS_PINNED"
        v25_files_modified = $false
        v24_files_modified = $false
        manifest_file_rows_replayed_by_builder = "PASS"
        full_repository_source_closure_replayed_by_builder = "PASS"
        exact_bwrap_argv_count = "PASS_48_PROBE_48_OFFICIAL"
        probe_and_official_argv_distinct = "PASS"
        powershell_parse = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        python_ast = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        v26_windows_safe_tests = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        canonical_read_only_tests = "NOT_RUN"
        retained_probe = "NOT_RUN"
        heavy_work_skipped = $true
        official_input_opened = $false
        solver_run = $false
    }
}
$muniCertificatePath = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-certificate.json"
Write-MuniUtf8 $muniCertificatePath (($muniCertificate | ConvertTo-Json -Depth 25) + "`n")

$muniManifestRows = @{}
foreach ($row in $muniManifest.files) {
    $muniManifestRows[[string]$row.label] = $row
}
foreach ($entry in $muniFilePathByLabel.GetEnumerator()) {
    $label = [string]$entry.Key
    if (-not $muniManifestRows.ContainsKey($label)) {
        throw "Generated manifest is missing chain row: $label"
    }
    if ($muniManifestRows[$label].sha256 -ne $muniArtifactHashes[$label]) {
        throw "Generated manifest hash replay failed: $label"
    }
}
foreach ($entry in $muniSourceHashes.GetEnumerator()) {
    if (-not $muniManifestRows.ContainsKey($entry.Key)) {
        throw "Generated manifest is missing source row: $($entry.Key)"
    }
    if ($muniManifestRows[$entry.Key].sha256 -ne $entry.Value) {
        throw "Generated manifest source hash replay failed: $($entry.Key)"
    }
    if ((Get-MuniSha256 $muniSourcePaths[$entry.Key]) -ne $entry.Value) {
        throw "Source changed during MUNI v26 construction: $($entry.Key)"
    }
}

foreach ($file in Get-ChildItem -LiteralPath $muniV25Root -File | Sort-Object Name) {
    if (-not $muniV25Snapshot.Contains($file.Name)) {
        throw "MUNI v25 file set changed during v26 construction"
    }
    $snapshot = $muniV25Snapshot[$file.Name]
    if ($file.Length -ne $snapshot.size_bytes -or (Get-MuniSha256 $file.FullName) -ne $snapshot.sha256) {
        throw "MUNI v25 artifact changed during v26 construction: $($file.Name)"
    }
}
if ((Get-ChildItem -LiteralPath $muniV25Root -File).Count -ne $muniV25Snapshot.Count) {
    throw "MUNI v25 file set changed during v26 construction"
}

foreach ($file in Get-ChildItem -LiteralPath $muniV24Root -File | Sort-Object Name) {
    if (-not $muniV24Snapshot.Contains($file.Name)) {
        throw "MUNI v24 file set changed during v26 construction"
    }
    $snapshot = $muniV24Snapshot[$file.Name]
    if ($file.Length -ne $snapshot.size_bytes -or (Get-MuniSha256 $file.FullName) -ne $snapshot.sha256) {
        throw "MUNI v24 artifact changed during v26 construction: $($file.Name)"
    }
}
if ((Get-ChildItem -LiteralPath $muniV24Root -File).Count -ne $muniV24Snapshot.Count) {
    throw "MUNI v24 file set changed during v26 construction"
}
Assert-MuniPinnedFile $muniParentBuilderPath $muniParentBuilderHash "MUNI v25 builder after construction"
Assert-MuniPinnedFile $muniParentManifestPath $muniParentManifestHash "MUNI v25 manifest after construction"
Assert-MuniPinnedFile $muniParentCertificatePath $muniParentCertificateHash "MUNI v25 certificate after construction"
Assert-MuniPinnedFile $muniStaleV24BuilderPath $muniStaleV24BuilderHash "stale MUNI v24 builder after construction"
Assert-MuniPinnedFile $muniStaleV24ManifestPath $muniStaleV24ManifestHash "stale MUNI v24 manifest after construction"
Assert-MuniPinnedFile $muniStaleV24CertificatePath $muniStaleV24CertificateHash "stale MUNI v24 certificate after construction"
Assert-MuniPinnedFile $muniFinalFocusedTestPath $muniFinalFocusedTestHash "final shared-core focused test after construction"
Assert-MuniPinnedFile $muniSharedCoreReceiptPath $muniSharedCoreReceiptHash "final shared-core receipt after construction"
Assert-MuniPinnedFile $muniSharedCoreStdoutPath $muniSharedCoreStdoutHash "final shared-core stdout after construction"
Assert-MuniPinnedFile $muniSharedCoreStderrPath $muniEmptySha256 "final shared-core stderr after construction"
if ((Get-MuniSha256 $muniBuilderPath) -ne $muniBuilderHashAtStart) {
    throw "MUNI v26 builder source changed during construction"
}

[ordered]@{
    target = $muniV26Root
    builder_sha256 = $muniBuilderHashAtStart
    manifest_sha256 = $muniManifestHash
    certificate_sha256 = Get-MuniSha256 $muniCertificatePath
    contained_probe_argv_count = $muniProbeArgv.Count
    contained_probe_argv_nul_sha256 = Get-MuniNulArgvSha256 $muniProbeArgv
    contained_official_argv_count = $muniOfficialArgv.Count
    contained_official_argv_nul_sha256 = Get-MuniNulArgvSha256 $muniOfficialArgv
    current_source_hashes = $muniSourceHashes
    parent_v25_manifest_sha256 = $muniParentManifestHash
    parent_v25_certificate_sha256 = $muniParentCertificateHash
    stale_v24_manifest_sha256 = $muniStaleV24ManifestHash
    final_shared_core_receipt_sha256 = $muniSharedCoreReceiptHash
    final_shared_core_sha256 = $muniFinalSharedCoreHash
    final_focused_test_sha256 = $muniFinalFocusedTestHash
    retained_probe_authorized = $false
    official_launch_authorized = $false
    official_input_opened = $false
    solver_run = $false
} | ConvertTo-Json -Depth 8
