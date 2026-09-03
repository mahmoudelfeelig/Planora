param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$muniRepositoryRoot = Split-Path -Parent $PSScriptRoot
$muniV26Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v26"
$muniV27Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v27"
$muniRepositoryWsl = "/mnt/d/Stuff/Projects/Sites/Planora"
$muniV26Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v26"
$muniV27Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v27"
$muniUtf8NoBom = [System.Text.UTF8Encoding]::new($false)
$muniBuilderPath = $PSCommandPath

$muniParentBuilderHash = "faec7c322543427e440de08a0644e1715a15c9500e767abaab08bb2ef6f498c0"
$muniParentManifestHash = "8220439619602cee750edcf0b950474f85899c727953a7d024936599b8e0c29d"
$muniParentCertificateHash = "ed9226597e871f9254f9aa7099617144a93a216fab2153f238694e9e336be15d"
$muniCanonicalRunId = "3913458278a647e9b3a635c7452ae2d6"
$muniCanonicalPrefix = "muni-fspsx-v26-canonical-readonly-tests-$muniCanonicalRunId"
$muniCanonicalEvidencePins = [ordered]@{
    "$muniCanonicalPrefix.exit-code.txt" = "f1b2f662800122bed0ff255693df89c4487fbdcf453d3524a42d4ec20c3d9c04"
    "$muniCanonicalPrefix.plan.json" = "b8776382708c372e7c7597f00a9c9b6298d021372e5ef5dab56852223f50ccb0"
    "$muniCanonicalPrefix.receipt.json" = "cc2c00f55d5682ae5c9aca11e2d5d9449a62a9c41073c47179ef06c51f2316d0"
    "$muniCanonicalPrefix.stderr.log" = "a8fa2770f9e4715fdfbad7f873689c4a17edc64b9f7f63e73eb463a62297b04c"
    "$muniCanonicalPrefix.stdout.log" = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
$muniHistoricalTreePins = [ordered]@{
    "16" = "f5f663575cbff160bc291d0de618abc6052b863d91bdc686c18a1858b0674202"
    "17" = "4898668e9c19d0a8cb3724f96c7083716b9e8b18c3ff747f53e6fb4b56fd26a4"
    "18" = "2ee23445d8a0691c1a3dc05b035d0265c94a9b6dc641c4bbceb76c381d53335b"
    "19" = "c69d9feb3633db7e625f839ebad77edd4b9874e73950f27802e7d6b14585642a"
    "20" = "4c850d0efef25e016c9e5bf92bdeb2a2f4e7df0d23e84251077bf52ac42f5ee3"
    "21" = "5e8cbdc955568c29434c36875fe593223cd0c520819d2db4a50b2976d0e2fecd"
    "22" = "ed1b901170089e08db59d1ae376897d4aca514fe85092eb314bb09cbc3b820eb"
    "23" = "e1e109484eb584843e9a40cb5dd25a8351b233be63f139390119f5a2f2e7e7c5"
    "24" = "54b208e878bd88906b96d1e4b1121060257aeb7b5c8b10599d2e6b9c19a93922"
    "25" = "f731bbbedc064d217f27a5e49439788f3105a18292f6ba50fb264574e91dc227"
    "26" = "916a42957f81524a8014a1a5997ef6a54d1a4a3a1560ea589a47dfe2413fa86e"
}
$muniHistoricalBuilderPins = [ordered]@{
    "23" = "c52265500d9dd112f0ed73e3e89c45e965c122eb54bc530624f9c6c7e7151d87"
    "24" = "4bb5b603020886758a69fb91df6cb9d3aea1dd87f19e314bb43eff09f1f883da"
    "25" = "d6b379e7307e803023d9f6726f36a4cf7d69411f1a6c9f228cc9edd51ea3c028"
    "26" = $muniParentBuilderHash
}
$muniExpectedFailures = @(
    "test_post_popen_admission_fault_always_drains_provisional_pgid"
    "test_final_acceptance_requires_elapsed_and_peak_within_limits"
    "test_direct_v25_parent_and_exact_bwrap_contract"
    "test_v26_final_core_rejection_evidence_and_authorization_state"
)

function Get-MuniSha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-MuniBytesSha256([byte[]]$Bytes) {
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($hasher.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
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

function Get-MuniTreeDigest([string]$Directory) {
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
        throw "Pinned historical directory is absent: $Directory"
    }
    $rows = [System.Collections.Generic.List[string]]::new()
    [string[]]$names = @(Get-ChildItem -LiteralPath $Directory -File | ForEach-Object Name)
    [System.Array]::Sort($names, [System.StringComparer]::Ordinal)
    foreach ($name in $names) {
        $file = Get-Item -LiteralPath (Join-Path $Directory $name)
        $rows.Add(
            $file.Name + [char]0 + (Get-MuniSha256 $file.FullName) +
            [char]0 + [string]$file.Length + "`n"
        )
    }
    return Get-MuniBytesSha256 ([System.Text.Encoding]::UTF8.GetBytes(($rows -join "")))
}

function Assert-MuniHistoricalLineage() {
    foreach ($entry in $muniHistoricalTreePins.GetEnumerator()) {
        $directory = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v$($entry.Key)"
        $observed = Get-MuniTreeDigest $directory
        if ($observed -ne $entry.Value) {
            throw "MUNI v$($entry.Key) tree drift: expected $($entry.Value) observed $observed"
        }
    }
    foreach ($entry in $muniHistoricalBuilderPins.GetEnumerator()) {
        $path = Join-Path $muniRepositoryRoot "scripts\build_muni_v$($entry.Key)_chain.ps1"
        Assert-MuniPinnedFile $path $entry.Value "MUNI v$($entry.Key) builder"
    }
}

function Convert-MuniV26Identity([string]$Text) {
    $result = $Text
    foreach ($pair in @(
        @("muni_v26", "muni_v27"),
        @("frontier-v26", "frontier-v27"),
        @("MUNI-FSPSX v26", "MUNI-FSPSX v27"),
        @("MUNI v26", "MUNI v27"),
        @("MUNI_V26", "MUNI_V27"),
        @("V26", "V27"),
        @("v26", "v27")
    )) {
        $result = $result.Replace([string]$pair[0], [string]$pair[1])
    }
    return $result
}

function Convert-MuniArtifact(
    [string]$SourceName,
    [string]$DestinationName,
    [scriptblock]$AdditionalTransform = $null
) {
    $source = Join-Path $muniV26Root $SourceName
    $destination = Join-Path $muniV27Root $DestinationName
    $text = [System.IO.File]::ReadAllText($source, $muniUtf8NoBom)
    if (-not ($text.Contains("muni_v26") -or $text.Contains("frontier-v26") -or $text.Contains("v26"))) {
        throw "Expected v26 identity token absent from $SourceName"
    }
    $text = Convert-MuniV26Identity $text
    if ($null -ne $AdditionalTransform) {
        $text = & $AdditionalTransform $text
    }
    if ($text.Contains("muni_v26") -or $text.Contains("frontier-v26")) {
        throw "Stale current-chain v26 identity remains in $DestinationName"
    }
    Write-MuniUtf8 $destination $text
}

function Replace-MuniExact([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    $first = $Text.IndexOf($Old, [System.StringComparison]::Ordinal)
    if ($first -lt 0) {
        throw "Required $Label seam is absent"
    }
    if ($Text.IndexOf($Old, $first + $Old.Length, [System.StringComparison]::Ordinal) -ge 0) {
        throw "Required $Label seam is ambiguous"
    }
    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

function Replace-MuniPythonMethod(
    [string]$Text,
    [string]$MethodName,
    [string]$Replacement
) {
    $pattern = "(?ms)^    def " + [regex]::Escape($MethodName) + "\(.*?(?=^    def |^class |\z)"
    $matches = [regex]::Matches($Text, $pattern)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one Python method $MethodName; observed $($matches.Count)"
    }
    return [regex]::Replace($Text, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{
        param($match)
        return $Replacement.TrimEnd() + "`n`n"
    }, 1)
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
        "$muniV27Wsl/planora-muni-fspsx-frontier-v27-bootstrap.py",
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
    return Get-MuniBytesSha256 $payload
}

$muniBuilderHashAtStart = Get-MuniSha256 $muniBuilderPath
$muniParentBuilderPath = Join-Path $muniRepositoryRoot "scripts\build_muni_v26_chain.ps1"
$muniParentManifestPath = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-freeze-manifest.json"
$muniParentCertificatePath = Join-Path $muniV26Root "planora-muni-fspsx-frontier-v26-certificate.json"

if (Test-Path -LiteralPath $muniV27Root) {
    throw "Refusing to overwrite an existing MUNI v27 chain: $muniV27Root"
}
Assert-MuniHistoricalLineage
Assert-MuniPinnedFile $muniParentBuilderPath $muniParentBuilderHash "MUNI v26 builder"
Assert-MuniPinnedFile $muniParentManifestPath $muniParentManifestHash "MUNI v26 freeze manifest"
Assert-MuniPinnedFile $muniParentCertificatePath $muniParentCertificateHash "MUNI v26 certificate"

$muniEvidenceRoot = Join-Path $muniRepositoryRoot "output\diagnostic-receipts"
foreach ($entry in $muniCanonicalEvidencePins.GetEnumerator()) {
    Assert-MuniPinnedFile (Join-Path $muniEvidenceRoot $entry.Key) $entry.Value "v26 canonical rejection $($entry.Key)"
}
$muniReceiptPath = Join-Path $muniEvidenceRoot "$muniCanonicalPrefix.receipt.json"
$muniStderrPath = Join-Path $muniEvidenceRoot "$muniCanonicalPrefix.stderr.log"
$muniReceipt = Get-Content -LiteralPath $muniReceiptPath -Raw | ConvertFrom-Json
$muniStderr = [System.IO.File]::ReadAllText($muniStderrPath, $muniUtf8NoBom)
if ($muniReceipt.decision -ne "REJECTED" -or $muniReceipt.process_exit_code -ne 1) {
    throw "Pinned v26 canonical receipt no longer records the rejection"
}
if (-not $muniStderr.Contains("Ran 119 tests") -or -not $muniStderr.Contains("FAILED (failures=4, skipped=2)")) {
    throw "Pinned v26 canonical stderr summary drift"
}
foreach ($failure in $muniExpectedFailures) {
    $needle = "FAIL: $failure "
    if (([regex]::Matches($muniStderr, [regex]::Escape($needle))).Count -ne 1) {
        throw "Pinned v26 canonical failure set drift for $failure"
    }
}

$muniParentManifest = Get-Content -LiteralPath $muniParentManifestPath -Raw | ConvertFrom-Json
$muniParentCertificate = Get-Content -LiteralPath $muniParentCertificatePath -Raw | ConvertFrom-Json
if ($muniParentCertificate.authorization.retained_probe_authorized -ne $false -or
    $muniParentCertificate.authorization.official_launch_authorized -ne $false) {
    throw "MUNI v26 parent unexpectedly authorizes execution"
}

# Replay every locally available frozen v26 artifact and every repository source row.
foreach ($entry in $muniParentCertificate.files.PSObject.Properties) {
    $path = [string]$entry.Name
    if ($path.StartsWith("$muniV26Wsl/")) {
        $local = Join-Path $muniV26Root (Split-Path -Leaf $path)
        Assert-MuniPinnedFile $local ([string]$entry.Value) "MUNI v26 certificate file $(Split-Path -Leaf $path)"
    }
}
$muniSourcePaths = [ordered]@{}
$muniSourceHashes = [ordered]@{}
foreach ($row in $muniParentManifest.files) {
    $path = [string]$row.path
    $isRepositorySource = (
        ($path.StartsWith("$muniRepositoryWsl/benchmarks/") -or $path.StartsWith("$muniRepositoryWsl/tests/")) -and
        (-not $path.StartsWith("$muniV26Wsl/")) -and
        $path.EndsWith(".py")
    )
    if (-not $isRepositorySource) {
        continue
    }
    $label = [string]$row.label
    $relative = $path.Substring($muniRepositoryWsl.Length + 1).Replace("/", "\")
    $local = Join-Path $muniRepositoryRoot $relative
    Assert-MuniPinnedFile $local ([string]$row.sha256) "MUNI v26 source closure $label"
    $muniSourcePaths[$label] = $local
    $muniSourceHashes[$label] = [string]$row.sha256
}
if ($muniSourceHashes.Count -eq 0) {
    throw "MUNI v26 source closure is empty"
}

New-Item -ItemType Directory -Path $muniV27Root | Out-Null
foreach ($copy in @(
    @("planora_muni_v26_benchmarks_stub.py", "planora_muni_v27_benchmarks_stub.py"),
    @("planora-muni-fspsx-frontier-v26-generic-validator.py", "planora-muni-fspsx-frontier-v27-generic-validator.py"),
    @("planora-muni-fspsx-frontier-v26-minimal-tcb.sha256", "planora-muni-fspsx-frontier-v27-minimal-tcb.sha256"),
    @("planora-muni-fspsx-frontier-v26-stdlib.sha256", "planora-muni-fspsx-frontier-v27-stdlib.sha256"),
    @("planora-muni-fspsx-v35-derivation-audit-v1.json", "planora-muni-fspsx-v35-derivation-audit-v1.json")
)) {
    [System.IO.File]::Copy(
        (Join-Path $muniV26Root ([string]$copy[0])),
        (Join-Path $muniV27Root ([string]$copy[1]))
    )
}

Convert-MuniArtifact `
    "planora-muni-fspsx-frontier-v26-runner.py" `
    "planora-muni-fspsx-frontier-v27-runner.py"

$muniSupervisorTransform = {
    param([string]$Text)

    $oldAcceptance = @'
        and cleanup is not None
        and not cleanup.get("errors")
        and not cleanup.get("observation_errors")
        and cleanup.get("original_pgid_asserted_empty") is True
        and child_report is not None
'@
    $newAcceptance = @'
        and cleanup is not None
        and cleanup.get("errors") == ()
        and cleanup.get("observation_errors") == ()
        and cleanup.get("original_pgid_asserted_empty") is True
        and cleanup.get("leader_observation_state")
        in {"same_identity", "confirmed_disappeared"}
        and child_report is not None
'@
    $Text = Replace-MuniExact $Text $oldAcceptance $newAcceptance "v27 complete cleanup acceptance"

    $oldLeaderObservation = @'
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
'@
    $newLeaderObservation = @'
    try:
        observed = proc_stat_identity(process.pid)
    except ProcObservationError as exc:
        record_observation("leader_before_stop", exc)
        observed = None
        identity_changed = False
        leader_observation_state = "uncertain"
        generation.seal("leader_generation_observation_failed_before_stop")
    else:
        identity_changed = observed not in (None, generation.leader_identity)
        if observed is None:
            leader_observation_state = "confirmed_disappeared"
        elif identity_changed:
            leader_observation_state = "identity_changed"
            generation.seal("leader_generation_identity_changed_before_stop")
        else:
            leader_observation_state = "same_identity"
'@
    $Text = Replace-MuniExact $Text $oldLeaderObservation $newLeaderObservation "v27 leader observation classification"

    $oldReturn = @'
        "leader_identity_changed": identity_changed,
        "leader_identity_available": observed is not None,
        "pidfd_evidence_available": pidfd is not None,
'@
    $newReturn = @'
        "leader_identity_changed": identity_changed,
        "leader_identity_available": observed is not None,
        "leader_observation_state": leader_observation_state,
        "pidfd_evidence_available": pidfd is not None,
'@
    return Replace-MuniExact $Text $oldReturn $newReturn "v27 cleanup observation evidence"
}
Convert-MuniArtifact `
    "planora-muni-fspsx-frontier-v26-supervisor.py" `
    "planora-muni-fspsx-frontier-v27-supervisor.py" `
    $muniSupervisorTransform
Convert-MuniArtifact `
    "planora-muni-fspsx-frontier-v26-bootstrap.py" `
    "planora-muni-fspsx-frontier-v27-bootstrap.py"
Convert-MuniArtifact `
    "planora-muni-fspsx-frontier-v26-inline-trust-root.txt" `
    "planora-muni-fspsx-frontier-v27-inline-trust-root.txt"
Convert-MuniArtifact `
    "planora-muni-fspsx-frontier-v26-launcher.sh" `
    "planora-muni-fspsx-frontier-v27-launcher.sh"

$muniTestTransform = {
    param([string]$Text)

    $postPopenEvidence = @'
self.assertFalse(cleanup["leader_identity_available"])
        self.assertEqual(cleanup["leader_observation_state"], "confirmed_disappeared")
'@
    $Text = $Text.Replace(
        'self.assertTrue(cleanup["leader_identity_available"])',
        $postPopenEvidence
    )
    $oldUncertainCleanup = @'
self.assertTrue(cleanup["observation_errors"])
        self.assertFalse(cleanup["original_pgid_asserted_empty"])
'@
    $newUncertainCleanup = @'
self.assertTrue(cleanup["observation_errors"])
        self.assertEqual(cleanup["leader_observation_state"], "same_identity")
        self.assertFalse(cleanup["original_pgid_asserted_empty"])
'@
    $Text = $Text.Replace($oldUncertainCleanup, $newUncertainCleanup)

    $acceptanceMethod = @'
    def test_final_acceptance_requires_elapsed_and_peak_within_limits(self) -> None:
        complete_cleanup = {
            "errors": (),
            "observation_errors": (),
            "original_pgid_asserted_empty": True,
            "leader_observation_state": "confirmed_disappeared",
        }
        common = {
            "errors": (), "stop_reason": "normal_exit", "child_exit": 0,
            "cleanup": complete_cleanup, "child_report": {"status": "PASS"},
        }
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=180.001, peak_whole_memory_kib=1
        ))
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=1.0, peak_whole_memory_kib=700_001
        ))
        self.assertTrue(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=180.0, peak_whole_memory_kib=700_000
        ))
        for missing in (
            "errors", "observation_errors", "original_pgid_asserted_empty",
            "leader_observation_state",
        ):
            incomplete = dict(complete_cleanup)
            incomplete.pop(missing)
            self.assertFalse(supervisor.sealed_import_probe_accepted(
                **{**common, "cleanup": incomplete},
                final_elapsed_seconds=1.0,
                peak_whole_memory_kib=1,
            ), missing)
        for uncertain in ("uncertain", "identity_changed"):
            rejected = dict(complete_cleanup, leader_observation_state=uncertain)
            self.assertFalse(supervisor.sealed_import_probe_accepted(
                **{**common, "cleanup": rejected},
                final_elapsed_seconds=1.0,
                peak_whole_memory_kib=1,
            ), uncertain)
'@
    $Text = Replace-MuniPythonMethod $Text "test_final_acceptance_requires_elapsed_and_peak_within_limits" $acceptanceMethod

    $directParentMethod = @'
    def test_direct_v26_parent_and_exact_bwrap_contract(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v27-freeze-manifest.json").read_bytes()
        )
        parent = manifest["parent_chain"]
        self.assertEqual(parent["version"], "v26")
        self.assertEqual(
            parent["builder_sha256"],
            "faec7c322543427e440de08a0644e1715a15c9500e767abaab08bb2ef6f498c0",
        )
        self.assertEqual(
            parent["freeze_manifest_sha256"],
            "8220439619602cee750edcf0b950474f85899c727953a7d024936599b8e0c29d",
        )
        self.assertEqual(
            parent["implementation_certificate_sha256"],
            "ed9226597e871f9254f9aa7099617144a93a216fab2153f238694e9e336be15d",
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v27-certificate.json").read_bytes()
        )
        for label in ("sealed_import_probe", "official_launch"):
            contract = certificate["contained_bwrap_contract"][label]
            argv = contract["argv"]
            self.assertEqual(len(argv), 48)
            encoded = ("\0".join(argv) + "\0").encode("utf-8")
            self.assertEqual(sha256(encoded).hexdigest(), contract["argv_nul_sha256"])
'@
    $Text = Replace-MuniPythonMethod $Text "test_direct_v25_parent_and_exact_bwrap_contract" $directParentMethod

    $rejectionMethod = @'
    def test_v27_canonical_rejection_evidence_and_authorization_state(self) -> None:
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v27-certificate.json").read_bytes()
        )
        rejection = certificate["parent_v26_canonical_rejection_evidence"]
        self.assertEqual(rejection["decision"], "REJECTED")
        self.assertEqual(rejection["run_id"], "3913458278a647e9b3a635c7452ae2d6")
        self.assertEqual(rejection["tests_run"], 119)
        self.assertEqual(rejection["failures"], 4)
        self.assertEqual(rejection["skipped"], 2)
        self.assertEqual(rejection["errors"], 0)
        self.assertEqual(rejection["passed"], 113)
        self.assertEqual(set(rejection["failure_names"]), {
            "test_post_popen_admission_fault_always_drains_provisional_pgid",
            "test_final_acceptance_requires_elapsed_and_peak_within_limits",
            "test_direct_v25_parent_and_exact_bwrap_contract",
            "test_v26_final_core_rejection_evidence_and_authorization_state",
        })
        self.assertEqual(
            rejection["receipt_sha256"],
            "cc2c00f55d5682ae5c9aca11e2d5d9449a62a9c41073c47179ef06c51f2316d0",
        )
        self.assertFalse(certificate["authorization"]["retained_probe_authorized"])
        self.assertFalse(certificate["authorization"]["official_launch_authorized"])
        self.assertFalse(certificate["authorization"]["official_input_authorized"])
'@
    $Text = Replace-MuniPythonMethod $Text "test_v27_final_core_rejection_evidence_and_authorization_state" $rejectionMethod

    $parentMethod = @'
    def test_v27_final_core_parent_and_authorization_state(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v27-freeze-manifest.json").read_bytes()
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v27-certificate.json").read_bytes()
        )
        self.assertEqual(manifest["parent_chain"]["version"], "v26")
        self.assertEqual(
            manifest["parent_chain"]["builder_sha256"],
            "faec7c322543427e440de08a0644e1715a15c9500e767abaab08bb2ef6f498c0",
        )
        self.assertEqual(
            certificate["current_source_hashes"]["itc2019_decomposed"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )
        finding = certificate["v26_canonical_rejection_fixes"]
        self.assertEqual(finding["status"], "FIXED_IN_V27_PENDING_INDEPENDENT_CANONICAL_REVIEW")
        self.assertEqual(len(finding["root_causes"]), 4)
        self.assertEqual(certificate["status"], "NO_GO_PENDING_INDEPENDENT_CANONICAL_REVIEW")
        self.assertFalse(certificate["authorization"]["retained_probe_authorized"])
        self.assertFalse(certificate["authorization"]["official_launch_authorized"])
        self.assertFalse(certificate["authorization"]["official_input_authorized"])

        expected_trees = {
            16: "f5f663575cbff160bc291d0de618abc6052b863d91bdc686c18a1858b0674202",
            17: "4898668e9c19d0a8cb3724f96c7083716b9e8b18c3ff747f53e6fb4b56fd26a4",
            18: "2ee23445d8a0691c1a3dc05b035d0265c94a9b6dc641c4bbceb76c381d53335b",
            19: "c69d9feb3633db7e625f839ebad77edd4b9874e73950f27802e7d6b14585642a",
            20: "4c850d0efef25e016c9e5bf92bdeb2a2f4e7df0d23e84251077bf52ac42f5ee3",
            21: "5e8cbdc955568c29434c36875fe593223cd0c520819d2db4a50b2976d0e2fecd",
            22: "ed1b901170089e08db59d1ae376897d4aca514fe85092eb314bb09cbc3b820eb",
            23: "e1e109484eb584843e9a40cb5dd25a8351b233be63f139390119f5a2f2e7e7c5",
            24: "54b208e878bd88906b96d1e4b1121060257aeb7b5c8b10599d2e6b9c19a93922",
            25: "f731bbbedc064d217f27a5e49439788f3105a18292f6ba50fb264574e91dc227",
            26: "916a42957f81524a8014a1a5997ef6a54d1a4a3a1560ea589a47dfe2413fa86e",
        }
        for version, expected in expected_trees.items():
            root = CHAIN_ROOT.parent / f"muni_v{version}"
            rows = []
            for path in sorted(root.iterdir(), key=lambda item: item.name):
                if path.is_file():
                    rows.append(
                        path.name.encode() + b"\0" + sha256(path.read_bytes()).hexdigest().encode()
                        + b"\0" + str(path.stat().st_size).encode() + b"\n"
                    )
            self.assertEqual(sha256(b"".join(rows)).hexdigest(), expected, version)
'@
    $Text = Replace-MuniPythonMethod $Text "test_v27_final_core_parent_and_authorization_state" $parentMethod
    $Text = $Text.Replace(
        "test_v27_preserves_v25_caps_and_mode_separation",
        "test_v27_preserves_v26_caps_and_mode_separation"
    )

    $oldWindowsStatic = @'
        suite.addTest(StaticContractTests("test_v27_final_core_parent_and_authorization_state"))
        suite.addTest(StaticContractTests("test_v27_preserves_v26_caps_and_mode_separation"))
'@
    $newWindowsStatic = @'
        suite.addTest(StaticContractTests("test_v27_final_core_parent_and_authorization_state"))
        suite.addTest(StaticContractTests("test_v27_preserves_v26_caps_and_mode_separation"))
        suite.addTest(StaticContractTests("test_direct_v26_parent_and_exact_bwrap_contract"))
        suite.addTest(StaticContractTests("test_v27_canonical_rejection_evidence_and_authorization_state"))
'@
    return Replace-MuniExact $Text $oldWindowsStatic $newWindowsStatic "v27 Windows-safe static suite"
}
Convert-MuniArtifact `
    "planora-muni-fspsx-frontier-v26-tests.py" `
    "planora-muni-fspsx-frontier-v27-tests.py" `
    $muniTestTransform

$muniPaths = [ordered]@{
    bootstrap = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-bootstrap.py"
    inline_trust_payload = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-inline-trust-root.txt"
    launcher = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-launcher.sh"
    supervisor = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-supervisor.py"
    runner = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-runner.py"
    v27_adversarial_tests = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-tests.py"
    generic_validator = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-generic-validator.py"
    stdlib_manifest = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-stdlib.sha256"
    minimal_tcb_manifest = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-minimal-tcb.sha256"
    benchmarks = Join-Path $muniV27Root "planora_muni_v27_benchmarks_stub.py"
    staged_audit_copy = Join-Path $muniV27Root "planora-muni-fspsx-v35-derivation-audit-v1.json"
}
$muniArtifactHashes = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $muniArtifactHashes[$entry.Key] = Get-MuniSha256 $entry.Value
}

$muniManifestText = [System.IO.File]::ReadAllText($muniParentManifestPath, $muniUtf8NoBom)
$muniManifest = (Convert-MuniV26Identity $muniManifestText) | ConvertFrom-Json
$muniManifest.code_review_certificate_path = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-certificate.json"
$muniManifest.created_for = "v27-v26-canonical-rejection-fixes-pending-independent-canonical-review"
foreach ($property in @(
    "parent_chain", "outer_bwrap_contract", "stale_v24_evidence",
    "shared_core_verification_evidence", "parent_v25_review_finding",
    "inherited_parent_v23_rejection_evidence", "parent_v26_canonical_rejection_evidence",
    "v26_canonical_rejection_fixes", "historical_lineage_integrity"
)) {
    $muniManifest.PSObject.Properties.Remove($property)
}
$muniFilePathByLabel = [ordered]@{
    bootstrap = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-bootstrap.py"
    inline_trust_payload = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-inline-trust-root.txt"
    launcher = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-launcher.sh"
    supervisor = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-supervisor.py"
    runner = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-runner.py"
    v27_adversarial_tests = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-tests.py"
    generic_validator = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-generic-validator.py"
    stdlib_manifest = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-stdlib.sha256"
    minimal_tcb_manifest = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-minimal-tcb.sha256"
    benchmarks = "$muniV27Wsl/planora_muni_v27_benchmarks_stub.py"
}
foreach ($row in $muniManifest.files) {
    $label = [string]$row.label
    if ($muniFilePathByLabel.Contains($label)) {
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
    historical_v16_v26_tree_pins_replayed = $true
    historical_v12_v15_canonical_hash_maps_preserved_in_parent_test_artifact = $true
    powershell_parse = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    python_ast = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    windows_safe_tests = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
    canonical_read_only_tests = "NOT_RUN"
    sealed_import_probe = "NOT_RUN"
    official_input_opened = $false
    progress_or_checkpoint_opened = $false
    solver_run = $false
}
$muniManifest | Add-Member -NotePropertyName parent_chain -NotePropertyValue ([ordered]@{
    version = "v26"
    root = $muniV26Wsl
    builder_sha256 = $muniParentBuilderHash
    freeze_manifest_sha256 = $muniParentManifestHash
    implementation_certificate_sha256 = $muniParentCertificateHash
    inherited_authorization = $false
})
$muniCanonicalRejectionEvidence = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v26.canonical-rejection-evidence.v1"
    run_id = $muniCanonicalRunId
    decision = "REJECTED"
    process_exit_code = 1
    tests_run = 119
    passed = 113
    failures = 4
    skipped = 2
    errors = 0
    failure_names = $muniExpectedFailures
    receipt_path = "output/diagnostic-receipts/$muniCanonicalPrefix.receipt.json"
    receipt_sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.receipt.json"]
    stderr_path = "output/diagnostic-receipts/$muniCanonicalPrefix.stderr.log"
    stderr_sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.stderr.log"]
    plan_sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.plan.json"]
    official_input_opened = $false
    solver_run = $false
    retained_probe_authorized = $false
    official_launch_authorized = $false
}
$muniV26CanonicalFixes = [ordered]@{
    status = "FIXED_IN_V27_PENDING_INDEPENDENT_CANONICAL_REVIEW"
    v26_modified = $false
    root_causes = @(
        [ordered]@{
            failed_test = $muniExpectedFailures[0]
            classification = "TEST_ORACLE_AND_DIAGNOSTIC_AMBIGUITY"
            diagnosis = "a confirmed ENOENT/ESRCH leader disappearance was correctly unavailable but the inherited test still required availability; v27 records a distinct leader_observation_state and tests confirmed disappearance"
        },
        [ordered]@{
            failed_test = $muniExpectedFailures[1]
            classification = "INCOMPLETE_ACCEPTANCE_FIXTURE"
            diagnosis = "the inherited positive boundary fixture omitted mandatory cleanup and observation evidence; v27 requires a complete cleanup schema and adversarially rejects every missing or uncertain field"
        },
        [ordered]@{
            failed_test = $muniExpectedFailures[2]
            classification = "STALE_DIRECT_PARENT_HASH_ASSERTION"
            diagnosis = "the renamed v25 test retained the v23 manifest hash; v27 binds all three direct v26 parent pins and independently replays bwrap argv digests"
        },
        [ordered]@{
            failed_test = $muniExpectedFailures[3]
            classification = "STALE_DUPLICATE_LINEAGE_ASSERTION"
            diagnosis = "an inherited current-chain rejection test still asserted v23 lineage while a separate v26 parent test asserted v25; v27 replaces it with pinned evidence for the exactly-once v26 canonical rejection"
        }
    )
    proc_absence_contract = "only confirmed ENOENT or ESRCH means absence"
    proc_uncertainty_contract = "permission EIO malformed identity or status and every other uncertainty reject"
}
$muniManifest | Add-Member -NotePropertyName parent_v26_canonical_rejection_evidence -NotePropertyValue $muniCanonicalRejectionEvidence
$muniManifest | Add-Member -NotePropertyName v26_canonical_rejection_fixes -NotePropertyValue $muniV26CanonicalFixes
$muniManifest | Add-Member -NotePropertyName historical_lineage_integrity -NotePropertyValue ([ordered]@{
    v12_v15_hash_maps = "PRESERVED_IN_PINNED_V26_TEST_ARTIFACT_AND_REPLAYED_BY_CANONICAL_SUITE"
    v16_v26_tree_sha256 = $muniHistoricalTreePins
    v23_v26_builder_sha256 = $muniHistoricalBuilderPins
})

$muniSymbolicArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" "{INLINE_TRUST_PAYLOAD}" "{BOOTSTRAP_SHA256}" `
    "{INLINE_TRUST_SHA256}" "{EXECUTION_MODE}" "{LAUNCHER_SHA256}" `
    "{SUPERVISOR_SHA256}" "{FREEZE_MANIFEST_SHA256}"
$muniManifest | Add-Member -NotePropertyName outer_bwrap_contract -NotePropertyValue ([ordered]@{
    schema = "planora.muni-fspsx.frontier-v27.bwrap-argv.v1"
    contained_argv_count = 48
    argv_shape = $muniSymbolicArgv
    probe_outer_timeout_seconds = 210
    official_outer_timeout_seconds = 660
    host_output_root_is_fresh_private_and_bound_as_tmp = $true
})

$muniManifestPath = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-freeze-manifest.json"
Write-MuniUtf8 $muniManifestPath (($muniManifest | ConvertTo-Json -Depth 25) + "`n")
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
if ((Get-MuniNulArgvSha256 $muniProbeArgv) -eq (Get-MuniNulArgvSha256 $muniOfficialArgv)) {
    throw "Probe and official bwrap commands are not distinct"
}

$muniCertificateFiles = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $name = Split-Path -Leaf $entry.Value
    $muniCertificateFiles["$muniV27Wsl/$name"] = $muniArtifactHashes[$entry.Key]
}
$muniCertificateFiles["$muniV27Wsl/planora-muni-fspsx-frontier-v27-freeze-manifest.json"] = $muniManifestHash
$muniCertificate = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v27.implementation-certificate.v1"
    status = "NO_GO_PENDING_INDEPENDENT_CANONICAL_REVIEW"
    diagnostic_launch_status = "NO_GO_PENDING_INDEPENDENT_CANONICAL_REVIEW"
    official_launch_status = "NO_GO_PENDING_CANONICAL_REVIEW_RETAINED_PROBE_AND_INDEPENDENT_AUTHORIZATION"
    authorization = [ordered]@{
        retained_probe_authorized = $false
        official_launch_authorized = $false
        official_input_authorized = $false
        canonical_test_authorized = $false
        authorization_requires_new_external_review = $true
        inherited_v26_authorization = $false
    }
    canonical_certificate_path = "$muniV27Wsl/planora-muni-fspsx-frontier-v27-certificate.json"
    builder_source = [ordered]@{
        path = "scripts/build_muni_v27_chain.ps1"
        sha256 = $muniBuilderHashAtStart
    }
    scope = "preserved v27 successor addressing only the exactly-once v26 canonical rejection; no WSL Docker browser official input retained probe solver or publication was opened or run"
    parent_chain = $muniManifest.parent_chain
    parent_v26_canonical_rejection_evidence = $muniCanonicalRejectionEvidence
    v26_canonical_rejection_fixes = $muniV26CanonicalFixes
    historical_lineage_integrity = $muniManifest.historical_lineage_integrity
    files = $muniCertificateFiles
    current_source_hashes = $muniSourceHashes
    source_closure_parent_manifest_sha256 = $muniParentManifestHash
    runtime_closure_parent_manifest_sha256 = $muniParentManifestHash
    resource_contract = $muniParentCertificate.resource_contract
    contained_bwrap_contract = [ordered]@{
        schema = "planora.muni-fspsx.frontier-v27.bwrap-argv.v1"
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
        parent_v26_builder_manifest_certificate = "PASS"
        v26_canonical_rejection_evidence = "PASS_PINNED_EXACTLY_ONCE"
        four_root_causes_addressed = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        v12_v15_hash_maps_preserved = "PASS_PINNED_PARENT_TEST_ARTIFACT"
        v16_v26_tree_pins_replayed = "PASS"
        v26_files_modified = $false
        manifest_file_rows_replayed_by_builder = "PASS"
        source_closure_replayed_by_builder = "PASS"
        runtime_closure_inherited_byte_exact_from_v26 = "PASS_PINNED"
        exact_bwrap_argv_count = "PASS_48_PROBE_48_OFFICIAL"
        probe_and_official_argv_distinct = "PASS"
        powershell_parse = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        python_ast = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        v27_windows_safe_tests = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        canonical_read_only_tests = "NOT_RUN"
        retained_probe = "NOT_RUN"
        heavy_work_skipped = $true
        official_input_opened = $false
        solver_run = $false
    }
}
$muniCertificatePath = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-certificate.json"
Write-MuniUtf8 $muniCertificatePath (($muniCertificate | ConvertTo-Json -Depth 30) + "`n")

# Recheck every generated manifest row that is locally replayable.
$muniManifestRows = @{}
foreach ($row in $muniManifest.files) {
    $muniManifestRows[[string]$row.label] = $row
}
foreach ($entry in $muniFilePathByLabel.GetEnumerator()) {
    if (-not $muniManifestRows.ContainsKey($entry.Key)) {
        throw "Generated manifest is missing chain row: $($entry.Key)"
    }
    if ($muniManifestRows[$entry.Key].sha256 -ne $muniArtifactHashes[$entry.Key]) {
        throw "Generated manifest hash replay failed: $($entry.Key)"
    }
}
foreach ($entry in $muniSourceHashes.GetEnumerator()) {
    if (-not $muniManifestRows.ContainsKey($entry.Key)) {
        throw "Generated manifest is missing source row: $($entry.Key)"
    }
    if ($muniManifestRows[$entry.Key].sha256 -ne $entry.Value -or
        (Get-MuniSha256 $muniSourcePaths[$entry.Key]) -ne $entry.Value) {
        throw "Generated source closure replay failed: $($entry.Key)"
    }
}
Assert-MuniHistoricalLineage
foreach ($entry in $muniCanonicalEvidencePins.GetEnumerator()) {
    Assert-MuniPinnedFile (Join-Path $muniEvidenceRoot $entry.Key) $entry.Value "v26 canonical rejection after construction $($entry.Key)"
}
if ((Get-MuniSha256 $muniBuilderPath) -ne $muniBuilderHashAtStart) {
    throw "MUNI v27 builder source changed during construction"
}

[ordered]@{
    target = $muniV27Root
    builder_sha256 = $muniBuilderHashAtStart
    manifest_sha256 = $muniManifestHash
    certificate_sha256 = Get-MuniSha256 $muniCertificatePath
    artifact_sha256 = $muniArtifactHashes
    parent_v26_builder_sha256 = $muniParentBuilderHash
    parent_v26_manifest_sha256 = $muniParentManifestHash
    parent_v26_certificate_sha256 = $muniParentCertificateHash
    v26_canonical_receipt_sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.receipt.json"]
    v26_canonical_failure_count = 4
    retained_probe_authorized = $false
    official_launch_authorized = $false
    official_input_authorized = $false
    official_input_opened = $false
    solver_run = $false
} | ConvertTo-Json -Depth 12
