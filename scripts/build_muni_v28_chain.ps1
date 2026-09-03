param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$muniRepositoryRoot = Split-Path -Parent $PSScriptRoot
$muniV27Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v27"
$muniV28Root = Join-Path $muniRepositoryRoot "benchmarks\probe_diagnostics\muni_v28"
$muniRepositoryWsl = "/mnt/d/Stuff/Projects/Sites/Planora"
$muniV27Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v27"
$muniV28Wsl = "$muniRepositoryWsl/benchmarks/probe_diagnostics/muni_v28"
$muniUtf8NoBom = [System.Text.UTF8Encoding]::new($false)
$muniBuilderPath = $PSCommandPath

$muniParentBuilderHash = "d332174875e7bf458876e050c936cd00ccc28ef6f3ee54f0940d54b1c69002d9"
$muniParentManifestHash = "1777d903c8105c0d76397503ad3667a5b9a21defa2fff16d17388c3ca22c32ee"
$muniParentCertificateHash = "05b6ba7852706d3328bf8ab1622986828c412f9b6549cda07d526e2eea2d3639"
$muniParentTestsHash = "6699f5d59b9218613fd7261fb6d68cda808e10b9967d05ebe24d505cc0d68aa5"
$muniCanonicalRunnerHash = "cbd78d3286a5f763e0af041b923e721d55fd3d9c2dd8e5bc2f0857c7d2a4a19e"
$muniCanonicalRunId = "656c1c3fd68f4866bc61714de29e35fd"
$muniCanonicalPrefix = "muni-fspsx-v27-canonical-readonly-tests-$muniCanonicalRunId"
$muniCanonicalAuthorizationName = "muni-fspsx-v27-canonical-tests-authorization-20260827T041746Z.receipt.json"
$muniCanonicalEvidencePins = [ordered]@{
    $muniCanonicalAuthorizationName = "bd01fe863cec792ba7660b2d2fdd2694b531fda593f196a998c8f0a788b54d2f"
    "$muniCanonicalPrefix.cleanup.json" = "32a70344cdad59148e08a4f90b3aa2c7c2fe2488a045ae4107a221043658d554"
    "$muniCanonicalPrefix.exit-code.txt" = "13bf7b3039c63bf5a50491fa3cfd8eb4e699d1ba1436315aef9cbe5711530354"
    "$muniCanonicalPrefix.plan.json" = "335296412e2d8ce9a328acf9b4943af5bf94f7feca7a7e2212aba6feeca24c00"
    "$muniCanonicalPrefix.receipt.json" = "a9ec00f3bffafb81f51ad3806d178d936ad246ec2b759c55bf745f1a67cd433c"
    "$muniCanonicalPrefix.stderr.log" = "6cb0a42eff44bbbed0fe89ed6ed07bf6ff77249318adb96c5bc25c01c0bb0998"
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
    "27" = "3ae4be16e8735ec64971aea78020077df1f1706d08eaad6a83ec9b084e0e5e58"
}
$muniHistoricalBuilderPins = [ordered]@{
    "23" = "c52265500d9dd112f0ed73e3e89c45e965c122eb54bc530624f9c6c7e7151d87"
    "24" = "4bb5b603020886758a69fb91df6cb9d3aea1dd87f19e314bb43eff09f1f883da"
    "25" = "d6b379e7307e803023d9f6726f36a4cf7d69411f1a6c9f228cc9edd51ea3c028"
    "26" = "faec7c322543427e440de08a0644e1715a15c9500e767abaab08bb2ef6f498c0"
    "27" = $muniParentBuilderHash
}
$muniExpectedSkips = @(
    "heavy sealed-runtime import probe disabled by test contract",
    "real sealed chain admission disabled by test contract"
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

function Convert-MuniV27Identity([string]$Text) {
    $result = $Text
    foreach ($pair in @(
        @("muni_v27", "muni_v28"),
        @("frontier-v27", "frontier-v28"),
        @("MUNI-FSPSX v27", "MUNI-FSPSX v28"),
        @("MUNI v27", "MUNI v28"),
        @("MUNI_V27", "MUNI_V28"),
        @("V27", "V28"),
        @("v27", "v28")
    )) {
        $result = $result.Replace([string]$pair[0], [string]$pair[1])
    }
    return $result
}

function Convert-MuniV28IdentityToV27([string]$Text) {
    $result = $Text
    foreach ($pair in @(
        @("muni_v28", "muni_v27"),
        @("frontier-v28", "frontier-v27"),
        @("MUNI-FSPSX v28", "MUNI-FSPSX v27"),
        @("MUNI v28", "MUNI v27"),
        @("MUNI_V28", "MUNI_V27"),
        @("V28", "V27"),
        @("v28", "v27")
    )) {
        $result = $result.Replace([string]$pair[0], [string]$pair[1])
    }
    return $result
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

function Convert-MuniArtifact(
    [string]$SourceName,
    [string]$DestinationName,
    [scriptblock]$AdditionalTransform = $null
) {
    $source = Join-Path $muniV27Root $SourceName
    $destination = Join-Path $muniV28Root $DestinationName
    $text = [System.IO.File]::ReadAllText($source, $muniUtf8NoBom)
    $text = Convert-MuniV27Identity $text
    if ($null -ne $AdditionalTransform) {
        $text = & $AdditionalTransform $text
    }
    Write-MuniUtf8 $destination $text
}

function Get-MuniLegacyRows([string]$Text) {
    $pattern = '(?m)^\s*"(?<path>/tmp/planora[^"]+)":\s*"(?<hash>[0-9a-f]{64})",?$'
    $rows = @(
        foreach ($match in [regex]::Matches($Text, $pattern)) {
            [string]$match.Groups["path"].Value + "=" + [string]$match.Groups["hash"].Value
        }
    )
    [System.Array]::Sort($rows, [System.StringComparer]::Ordinal)
    return ,$rows
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
        "$muniV28Wsl/planora-muni-fspsx-frontier-v28-bootstrap.py",
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
$muniParentBuilderPath = Join-Path $muniRepositoryRoot "scripts\build_muni_v27_chain.ps1"
$muniParentManifestPath = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-freeze-manifest.json"
$muniParentCertificatePath = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-certificate.json"
$muniParentTestsPath = Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-tests.py"
$muniCanonicalRunnerPath = Join-Path $muniRepositoryRoot "scripts\run_muni_v27_canonical_tests.ps1"
$muniEvidenceRoot = Join-Path $muniRepositoryRoot "output\diagnostic-receipts"

if (Test-Path -LiteralPath $muniV28Root) {
    throw "Refusing to overwrite an existing MUNI v28 chain: $muniV28Root"
}
Assert-MuniHistoricalLineage
Assert-MuniPinnedFile $muniParentBuilderPath $muniParentBuilderHash "MUNI v27 builder"
Assert-MuniPinnedFile $muniParentManifestPath $muniParentManifestHash "MUNI v27 freeze manifest"
Assert-MuniPinnedFile $muniParentCertificatePath $muniParentCertificateHash "MUNI v27 certificate"
Assert-MuniPinnedFile $muniParentTestsPath $muniParentTestsHash "MUNI v27 canonical tests"
Assert-MuniPinnedFile $muniCanonicalRunnerPath $muniCanonicalRunnerHash "MUNI v27 canonical runner"
foreach ($entry in $muniCanonicalEvidencePins.GetEnumerator()) {
    Assert-MuniPinnedFile (Join-Path $muniEvidenceRoot $entry.Key) $entry.Value "v27 canonical evidence $($entry.Key)"
}

$muniParentManifest = Get-Content -LiteralPath $muniParentManifestPath -Raw | ConvertFrom-Json
$muniParentCertificate = Get-Content -LiteralPath $muniParentCertificatePath -Raw | ConvertFrom-Json
if ($muniParentCertificate.authorization.retained_probe_authorized -ne $false -or
    $muniParentCertificate.authorization.official_launch_authorized -ne $false -or
    $muniParentCertificate.authorization.official_input_authorized -ne $false) {
    throw "MUNI v27 parent unexpectedly authorizes execution"
}
foreach ($entry in $muniParentCertificate.files.PSObject.Properties) {
    $path = [string]$entry.Name
    if ($path.StartsWith("$muniV27Wsl/")) {
        $local = Join-Path $muniV27Root (Split-Path -Leaf $path)
        Assert-MuniPinnedFile $local ([string]$entry.Value) "MUNI v27 certificate file $(Split-Path -Leaf $path)"
    }
}

$muniSourcePaths = [ordered]@{}
$muniSourceHashes = [ordered]@{}
foreach ($row in $muniParentManifest.files) {
    $path = [string]$row.path
    $isRepositorySource = (
        ($path.StartsWith("$muniRepositoryWsl/benchmarks/") -or $path.StartsWith("$muniRepositoryWsl/tests/")) -and
        (-not $path.StartsWith("$muniV27Wsl/")) -and
        $path.EndsWith(".py")
    )
    if (-not $isRepositorySource) {
        continue
    }
    $label = [string]$row.label
    $relative = $path.Substring($muniRepositoryWsl.Length + 1).Replace("/", "\")
    $local = Join-Path $muniRepositoryRoot $relative
    Assert-MuniPinnedFile $local ([string]$row.sha256) "MUNI v27 source closure $label"
    $muniSourcePaths[$label] = $local
    $muniSourceHashes[$label] = [string]$row.sha256
}
if ($muniSourceHashes.Count -ne 21) {
    throw "Expected 21 MUNI v27 source-closure rows; observed $($muniSourceHashes.Count)"
}

$muniReceiptPath = Join-Path $muniEvidenceRoot "$muniCanonicalPrefix.receipt.json"
$muniPlanPath = Join-Path $muniEvidenceRoot "$muniCanonicalPrefix.plan.json"
$muniCleanupPath = Join-Path $muniEvidenceRoot "$muniCanonicalPrefix.cleanup.json"
$muniStderrPath = Join-Path $muniEvidenceRoot "$muniCanonicalPrefix.stderr.log"
$muniStdoutPath = Join-Path $muniEvidenceRoot "$muniCanonicalPrefix.stdout.log"
$muniReceipt = Get-Content -LiteralPath $muniReceiptPath -Raw | ConvertFrom-Json
$muniPlan = Get-Content -LiteralPath $muniPlanPath -Raw | ConvertFrom-Json
$muniCleanup = Get-Content -LiteralPath $muniCleanupPath -Raw | ConvertFrom-Json
$muniStderr = [System.IO.File]::ReadAllText($muniStderrPath, $muniUtf8NoBom)
if ($muniReceipt.process_exit_code -ne 0 -or $muniReceipt.expected.tests_run -ne 119 -or
    $muniReceipt.expected.passed -ne 117 -or $muniReceipt.expected.skipped -ne 2 -or
    $muniReceipt.expected.failures -ne 0 -or $muniReceipt.expected.errors -ne 0) {
    throw "Pinned v27 passing canonical receipt summary drift"
}
if ((Get-Item -LiteralPath $muniStdoutPath).Length -ne 0 -or
    -not $muniStderr.Contains("Ran 119 tests") -or
    -not $muniStderr.Contains("OK (skipped=2)")) {
    throw "Pinned v27 passing canonical logs drift"
}
foreach ($skip in $muniExpectedSkips) {
    if (([regex]::Matches($muniStderr, [regex]::Escape("skipped '$skip'"))).Count -ne 1) {
        throw "Pinned v27 canonical skip drift: $skip"
    }
}
$muniPlanArgvText = (($muniPlan.argv | ForEach-Object { [string]$_ }) -join [char]0)
$muniReadWriteMount = "--bind" + [char]0 + [string]$muniPlan.private_tmp_root + [char]0 + "/tmp"
$muniReadOnlyMount = "--ro-bind" + [char]0 + [string]$muniPlan.private_tmp_root + [char]0 + "/tmp"
if (-not $muniPlanArgvText.Contains($muniReadWriteMount) -or $muniPlanArgvText.Contains($muniReadOnlyMount)) {
    throw "Pinned v27 plan no longer proves the reviewed read-write /tmp bind"
}
if ($muniReceipt.root_unchanged_at_48_exact_files -ne $true -or
    $muniCleanup.canonical_receipt_sha256 -ne $muniCanonicalEvidencePins["$muniCanonicalPrefix.receipt.json"] -or
    $muniCleanup.postcondition -ne "TARGET_ABSENT") {
    throw "Pinned v27 receipt or cleanup semantics drift"
}

New-Item -ItemType Directory -Path $muniV28Root | Out-Null

$muniNoGoEvidence = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v28.v27-canonical-evidence-no-go.v1"
    reviewed_run_id = $muniCanonicalRunId
    verdict = "NO_GO_FOR_RETAINED_NO_SOLVER_PROBE"
    official_input_and_launch_verdict = "NO_GO"
    severity = "P1"
    confidence = "HIGH"
    independent_finding = "v27 reported root_unchanged_at_48_exact_files but mounted the staged root read-write at /tmp and checked only final names and regular-file types; neither final content identity nor transient immutability was proven"
    observed_v27_contract = [ordered]@{
        staged_file_count = 48
        sandbox_mount = "BWRAP_READ_WRITE_BIND_TO_TMP"
        post_exit_checks = @("exact_final_name_set", "regular_file_type")
        post_exit_content_rehash_count = 0
        transient_mutation_watch = "ABSENT"
        receipt_claim = "root_unchanged_at_48_exact_files=true"
        retained_probe_authorization_from_receipt_accepted_by_independent_review = $false
    }
    passing_canonical_result = [ordered]@{
        tests_run = 119
        passed = 117
        skipped = 2
        failures = 0
        errors = 0
        exact_skip_reasons = $muniExpectedSkips
    }
    pinned_v27_evidence = [ordered]@{
        canonical_runner = [ordered]@{
            path = "scripts/run_muni_v27_canonical_tests.ps1"
            sha256 = $muniCanonicalRunnerHash
        }
        authorization = [ordered]@{
            path = "output/diagnostic-receipts/$muniCanonicalAuthorizationName"
            sha256 = $muniCanonicalEvidencePins[$muniCanonicalAuthorizationName]
        }
        plan = [ordered]@{
            path = "output/diagnostic-receipts/$muniCanonicalPrefix.plan.json"
            sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.plan.json"]
        }
        receipt = [ordered]@{
            path = "output/diagnostic-receipts/$muniCanonicalPrefix.receipt.json"
            sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.receipt.json"]
        }
        stderr = [ordered]@{
            path = "output/diagnostic-receipts/$muniCanonicalPrefix.stderr.log"
            sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.stderr.log"]
        }
        stdout = [ordered]@{
            path = "output/diagnostic-receipts/$muniCanonicalPrefix.stdout.log"
            sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.stdout.log"]
        }
        exit_code = [ordered]@{
            path = "output/diagnostic-receipts/$muniCanonicalPrefix.exit-code.txt"
            sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.exit-code.txt"]
        }
        cleanup = [ordered]@{
            path = "output/diagnostic-receipts/$muniCanonicalPrefix.cleanup.json"
            sha256 = $muniCanonicalEvidencePins["$muniCanonicalPrefix.cleanup.json"]
        }
    }
    mandatory_next_external_canonical_runner = [ordered]@{
        staged_allowlist = "extract exactly 48 unique v12-v15 paths and SHA-256 values from the pinned v28 tests"
        immutable_mount = "bind the staged 48-file root read-only at /tmp using --ro-bind or use an equivalently immutable content-addressed snapshot with no write-capable alias"
        post_exit_rehash = "rehash all 48 regular files after process exit and compare path hash and count against the extracted allowlist"
        transient_mutation_rejection = "retain kernel-enforced immutable-mount proof plus mutation-watch or immutable-snapshot evidence covering pre-launch through post-exit rehash; any mutation event or observation uncertainty rejects"
        final_mutation_rejection = "any missing extra non-regular renamed or hash-mismatched entry rejects"
        runner_self_pin = "authorization plan and receipt must carry one identical SHA-256 for the external canonical runner; the file must replay before launch and after evidence finalization"
        cleanup = "retain post-exit cleanup evidence bound to the canonical receipt hash and proving the exact staged target absent"
        acceptance = "119 unique tests with 117 passes exactly two pinned heavy skips zero failures zero errors and no solver official input progress checkpoint or publication"
    }
    authorization = [ordered]@{
        canonical_test_authorized = $false
        retained_probe_authorized = $false
        official_input_authorized = $false
        official_launch_authorized = $false
        automatic_retry_authorized = $false
    }
}
$muniNoGoPath = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-v27-canonical-evidence-no-go.json"
Write-MuniUtf8 $muniNoGoPath (($muniNoGoEvidence | ConvertTo-Json -Depth 20) + "`n")
$muniNoGoHash = Get-MuniSha256 $muniNoGoPath

foreach ($copy in @(
    @("planora_muni_v27_benchmarks_stub.py", "planora_muni_v28_benchmarks_stub.py"),
    @("planora-muni-fspsx-frontier-v27-generic-validator.py", "planora-muni-fspsx-frontier-v28-generic-validator.py"),
    @("planora-muni-fspsx-frontier-v27-minimal-tcb.sha256", "planora-muni-fspsx-frontier-v28-minimal-tcb.sha256"),
    @("planora-muni-fspsx-frontier-v27-stdlib.sha256", "planora-muni-fspsx-frontier-v28-stdlib.sha256"),
    @("planora-muni-fspsx-v35-derivation-audit-v1.json", "planora-muni-fspsx-v35-derivation-audit-v1.json")
)) {
    [System.IO.File]::Copy(
        (Join-Path $muniV27Root ([string]$copy[0])),
        (Join-Path $muniV28Root ([string]$copy[1]))
    )
}

foreach ($artifact in @("runner.py", "supervisor.py", "bootstrap.py", "inline-trust-root.txt", "launcher.sh")) {
    Convert-MuniArtifact `
        "planora-muni-fspsx-frontier-v27-$artifact" `
        "planora-muni-fspsx-frontier-v28-$artifact"
}

$muniTestTransform = {
    param([string]$Text)

    $finalCoreMethod = @'
    def test_v28_final_core_parent_and_authorization_state(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v28-freeze-manifest.json").read_bytes()
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v28-certificate.json").read_bytes()
        )
        self.assertEqual(manifest["parent_chain"]["version"], "v27")
        self.assertEqual(
            manifest["parent_chain"]["builder_sha256"],
            "d332174875e7bf458876e050c936cd00ccc28ef6f3ee54f0940d54b1c69002d9",
        )
        self.assertEqual(
            manifest["parent_chain"]["freeze_manifest_sha256"],
            "1777d903c8105c0d76397503ad3667a5b9a21defa2fff16d17388c3ca22c32ee",
        )
        self.assertEqual(
            manifest["parent_chain"]["implementation_certificate_sha256"],
            "05b6ba7852706d3328bf8ab1622986828c412f9b6549cda07d526e2eea2d3639",
        )
        finding = certificate["parent_v27_canonical_evidence_no_go"]
        self.assertEqual(finding["verdict"], "NO_GO_FOR_RETAINED_NO_SOLVER_PROBE")
        self.assertEqual(finding["passing_canonical_result"], {
            "tests_run": 119, "passed": 117, "skipped": 2, "failures": 0,
            "errors": 0, "exact_skip_reasons": [
                "heavy sealed-runtime import probe disabled by test contract",
                "real sealed chain admission disabled by test contract",
            ],
        })
        requirements = finding["mandatory_next_external_canonical_runner"]
        for key in (
            "staged_allowlist", "immutable_mount", "post_exit_rehash",
            "transient_mutation_rejection", "final_mutation_rejection",
            "runner_self_pin", "cleanup", "acceptance",
        ):
            self.assertTrue(requirements[key], key)
        self.assertIn("--ro-bind", requirements["immutable_mount"])
        self.assertIn("all 48", requirements["post_exit_rehash"])
        self.assertIn("authorization plan and receipt", requirements["runner_self_pin"])
        self.assertEqual(certificate["status"], "NO_GO_PENDING_INDEPENDENT_CANONICAL_REVIEW")
        for key in (
            "canonical_test_authorized", "retained_probe_authorized",
            "official_launch_authorized", "official_input_authorized",
        ):
            self.assertFalse(certificate["authorization"][key], key)

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
            27: "3ae4be16e8735ec64971aea78020077df1f1706d08eaad6a83ec9b084e0e5e58",
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
    $Text = Replace-MuniPythonMethod $Text "test_v28_final_core_parent_and_authorization_state" $finalCoreMethod

    $directParentMethod = @'
    def test_direct_v27_parent_and_exact_bwrap_contract(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v28-freeze-manifest.json").read_bytes()
        )
        parent = manifest["parent_chain"]
        self.assertEqual(parent["version"], "v27")
        self.assertEqual(
            parent["builder_sha256"],
            "d332174875e7bf458876e050c936cd00ccc28ef6f3ee54f0940d54b1c69002d9",
        )
        self.assertEqual(
            parent["freeze_manifest_sha256"],
            "1777d903c8105c0d76397503ad3667a5b9a21defa2fff16d17388c3ca22c32ee",
        )
        self.assertEqual(
            parent["implementation_certificate_sha256"],
            "05b6ba7852706d3328bf8ab1622986828c412f9b6549cda07d526e2eea2d3639",
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v28-certificate.json").read_bytes()
        )
        for label in ("sealed_import_probe", "official_launch"):
            contract = certificate["contained_bwrap_contract"][label]
            argv = contract["argv"]
            self.assertEqual(len(argv), 48)
            encoded = ("\0".join(argv) + "\0").encode("utf-8")
            self.assertEqual(sha256(encoded).hexdigest(), contract["argv_nul_sha256"])
        self.assertNotEqual(
            certificate["contained_bwrap_contract"]["sealed_import_probe"]["argv_nul_sha256"],
            certificate["contained_bwrap_contract"]["official_launch"]["argv_nul_sha256"],
        )
'@
    $Text = Replace-MuniPythonMethod $Text "test_direct_v26_parent_and_exact_bwrap_contract" $directParentMethod

    $canonicalEvidenceMethod = @'
    def test_v28_v27_canonical_evidence_no_go_and_authorization_state(self) -> None:
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v28-certificate.json").read_bytes()
        )
        evidence_path = (
            CHAIN_ROOT / "planora-muni-fspsx-frontier-v28-v27-canonical-evidence-no-go.json"
        )
        evidence = json.loads(evidence_path.read_bytes())
        evidence_rows = [
            value for path, value in certificate["files"].items()
            if path.endswith("/planora-muni-fspsx-frontier-v28-v27-canonical-evidence-no-go.json")
        ]
        self.assertEqual(len(evidence_rows), 1)
        self.assertEqual(sha256(evidence_path.read_bytes()).hexdigest(), evidence_rows[0])
        self.assertEqual(evidence, certificate["parent_v27_canonical_evidence_no_go"])
        self.assertEqual(evidence["reviewed_run_id"], "656c1c3fd68f4866bc61714de29e35fd")
        self.assertEqual(evidence["verdict"], "NO_GO_FOR_RETAINED_NO_SOLVER_PROBE")
        observed = evidence["observed_v27_contract"]
        self.assertEqual(observed["sandbox_mount"], "BWRAP_READ_WRITE_BIND_TO_TMP")
        self.assertEqual(observed["post_exit_content_rehash_count"], 0)
        self.assertEqual(observed["transient_mutation_watch"], "ABSENT")
        self.assertFalse(observed["retained_probe_authorization_from_receipt_accepted_by_independent_review"])
        expected_hashes = {
            "canonical_runner": "cbd78d3286a5f763e0af041b923e721d55fd3d9c2dd8e5bc2f0857c7d2a4a19e",
            "authorization": "bd01fe863cec792ba7660b2d2fdd2694b531fda593f196a998c8f0a788b54d2f",
            "plan": "335296412e2d8ce9a328acf9b4943af5bf94f7feca7a7e2212aba6feeca24c00",
            "receipt": "a9ec00f3bffafb81f51ad3806d178d936ad246ec2b759c55bf745f1a67cd433c",
            "stderr": "6cb0a42eff44bbbed0fe89ed6ed07bf6ff77249318adb96c5bc25c01c0bb0998",
            "stdout": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "exit_code": "13bf7b3039c63bf5a50491fa3cfd8eb4e699d1ba1436315aef9cbe5711530354",
            "cleanup": "32a70344cdad59148e08a4f90b3aa2c7c2fe2488a045ae4107a221043658d554",
        }
        self.assertEqual(
            {key: value["sha256"] for key, value in evidence["pinned_v27_evidence"].items()},
            expected_hashes,
        )
        for key, value in evidence["authorization"].items():
            self.assertFalse(value, key)
        for key in (
            "canonical_test_authorized", "retained_probe_authorized",
            "official_launch_authorized", "official_input_authorized",
        ):
            self.assertFalse(certificate["authorization"][key], key)
'@
    $Text = Replace-MuniPythonMethod $Text "test_v28_canonical_rejection_evidence_and_authorization_state" $canonicalEvidenceMethod
    $Text = $Text.Replace(
        'StaticContractTests("test_direct_v26_parent_and_exact_bwrap_contract")',
        'StaticContractTests("test_direct_v27_parent_and_exact_bwrap_contract")'
    )
    $Text = $Text.Replace(
        'StaticContractTests("test_v28_canonical_rejection_evidence_and_authorization_state")',
        'StaticContractTests("test_v28_v27_canonical_evidence_no_go_and_authorization_state")'
    )
    return $Text
}
Convert-MuniArtifact `
    "planora-muni-fspsx-frontier-v27-tests.py" `
    "planora-muni-fspsx-frontier-v28-tests.py" `
    $muniTestTransform

$muniParentLegacyRows = Get-MuniLegacyRows ([System.IO.File]::ReadAllText($muniParentTestsPath, $muniUtf8NoBom))
$muniV28TestsPath = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-tests.py"
$muniV28LegacyRows = Get-MuniLegacyRows ([System.IO.File]::ReadAllText($muniV28TestsPath, $muniUtf8NoBom))
if ($muniParentLegacyRows.Count -ne 48 -or $muniV28LegacyRows.Count -ne 48 -or
    (Compare-Object $muniParentLegacyRows $muniV28LegacyRows)) {
    throw "MUNI v12-v15 canonical 48-row hash map was not preserved exactly"
}

$muniRuntimeIdentityPairs = @(
    @("runner.py", "runner.py"),
    @("supervisor.py", "supervisor.py"),
    @("bootstrap.py", "bootstrap.py"),
    @("inline-trust-root.txt", "inline-trust-root.txt"),
    @("launcher.sh", "launcher.sh")
)
foreach ($pair in $muniRuntimeIdentityPairs) {
    $parent = [System.IO.File]::ReadAllText(
        (Join-Path $muniV27Root "planora-muni-fspsx-frontier-v27-$($pair[0])"),
        $muniUtf8NoBom
    )
    $child = [System.IO.File]::ReadAllText(
        (Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-$($pair[1])"),
        $muniUtf8NoBom
    )
    if ((Convert-MuniV28IdentityToV27 $child) -cne $parent) {
        throw "Runtime semantics drift beyond identity conversion: $($pair[0])"
    }
}

$muniPaths = [ordered]@{
    bootstrap = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-bootstrap.py"
    inline_trust_payload = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-inline-trust-root.txt"
    launcher = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-launcher.sh"
    supervisor = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-supervisor.py"
    runner = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-runner.py"
    v28_adversarial_tests = $muniV28TestsPath
    generic_validator = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-generic-validator.py"
    stdlib_manifest = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-stdlib.sha256"
    minimal_tcb_manifest = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-minimal-tcb.sha256"
    benchmarks = Join-Path $muniV28Root "planora_muni_v28_benchmarks_stub.py"
    staged_audit_copy = Join-Path $muniV28Root "planora-muni-fspsx-v35-derivation-audit-v1.json"
    v27_canonical_evidence_no_go = $muniNoGoPath
}
$muniArtifactHashes = [ordered]@{}
foreach ($entry in $muniPaths.GetEnumerator()) {
    $muniArtifactHashes[$entry.Key] = Get-MuniSha256 $entry.Value
}

$muniManifestText = [System.IO.File]::ReadAllText($muniParentManifestPath, $muniUtf8NoBom)
$muniManifest = (Convert-MuniV27Identity $muniManifestText) | ConvertFrom-Json
$muniManifest.code_review_certificate_path = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-certificate.json"
$muniManifest.created_for = "v28-v27-canonical-evidence-no-go-pending-independent-canonical-review"
foreach ($property in @(
    "parent_chain", "outer_bwrap_contract", "parent_v23_rejection_evidence",
    "parent_v26_canonical_rejection_evidence", "v26_canonical_rejection_fixes",
    "historical_lineage_integrity"
)) {
    $muniManifest.PSObject.Properties.Remove($property)
}
$muniFilePathByLabel = [ordered]@{
    bootstrap = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-bootstrap.py"
    inline_trust_payload = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-inline-trust-root.txt"
    launcher = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-launcher.sh"
    supervisor = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-supervisor.py"
    runner = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-runner.py"
    v28_adversarial_tests = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-tests.py"
    generic_validator = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-generic-validator.py"
    stdlib_manifest = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-stdlib.sha256"
    minimal_tcb_manifest = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-minimal-tcb.sha256"
    benchmarks = "$muniV28Wsl/planora_muni_v28_benchmarks_stub.py"
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
$muniManifest.files = @($muniManifest.files) + @([pscustomobject][ordered]@{
    label = "v27_canonical_evidence_no_go"
    path = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-v27-canonical-evidence-no-go.json"
    sha256 = $muniNoGoHash
})
$muniManifest.inline_trust_root.bootstrap_sha256 = $muniArtifactHashes.bootstrap
$muniManifest.inline_trust_root.inline_payload_sha256 = $muniArtifactHashes.inline_trust_payload
$muniManifest.stdlib_trust_boundary.minimal_tcb_manifest_path = $muniFilePathByLabel.minimal_tcb_manifest
$muniManifest.verification = [ordered]@{
    parent_v27_manifest_and_certificate_replayed = $true
    v27_passing_canonical_evidence_replayed = $true
    independent_v27_evidence_no_go_preserved = $true
    historical_v16_v27_tree_pins_replayed = $true
    historical_v12_v15_canonical_48_hash_rows_preserved = $true
    runtime_semantics_v27_equivalent_by_inverse_identity_replay = $true
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
    version = "v27"
    root = $muniV27Wsl
    builder_sha256 = $muniParentBuilderHash
    freeze_manifest_sha256 = $muniParentManifestHash
    implementation_certificate_sha256 = $muniParentCertificateHash
    canonical_tests_sha256 = $muniParentTestsHash
    inherited_authorization = $false
})
$muniManifest | Add-Member -NotePropertyName parent_v27_canonical_evidence_no_go -NotePropertyValue $muniNoGoEvidence
$muniManifest | Add-Member -NotePropertyName historical_lineage_integrity -NotePropertyValue ([ordered]@{
    v12_v15_external_canonical_hash_rows = "48_PRESERVED_EXACTLY_IN_PINNED_V27_AND_V28_TEST_ARTIFACTS"
    v16_v27_tree_sha256 = $muniHistoricalTreePins
    v23_v27_builder_sha256 = $muniHistoricalBuilderPins
    v27_files_modified = $false
})
$muniSymbolicArgv = New-MuniBwrapArgv `
    "{HOST_OUTPUT_ROOT}" "{INLINE_TRUST_PAYLOAD}" "{BOOTSTRAP_SHA256}" `
    "{INLINE_TRUST_SHA256}" "{EXECUTION_MODE}" "{LAUNCHER_SHA256}" `
    "{SUPERVISOR_SHA256}" "{FREEZE_MANIFEST_SHA256}"
$muniManifest | Add-Member -NotePropertyName outer_bwrap_contract -NotePropertyValue ([ordered]@{
    schema = "planora.muni-fspsx.frontier-v28.bwrap-argv.v1"
    contained_argv_count = 48
    argv_shape = $muniSymbolicArgv
    probe_outer_timeout_seconds = 210
    official_outer_timeout_seconds = 660
    host_output_root_is_fresh_private_and_bound_as_tmp = $true
})

$muniManifestPath = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-freeze-manifest.json"
Write-MuniUtf8 $muniManifestPath (($muniManifest | ConvertTo-Json -Depth 30) + "`n")
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
    $muniCertificateFiles["$muniV28Wsl/$name"] = $muniArtifactHashes[$entry.Key]
}
$muniCertificateFiles["$muniV28Wsl/planora-muni-fspsx-frontier-v28-freeze-manifest.json"] = $muniManifestHash
$muniCertificate = [ordered]@{
    schema = "planora.muni-fspsx.frontier-v28.implementation-certificate.v1"
    status = "NO_GO_PENDING_INDEPENDENT_CANONICAL_REVIEW"
    diagnostic_launch_status = "NO_GO_PENDING_INDEPENDENT_CANONICAL_REVIEW"
    official_launch_status = "NO_GO_PENDING_CANONICAL_REVIEW_RETAINED_PROBE_AND_INDEPENDENT_AUTHORIZATION"
    authorization = [ordered]@{
        canonical_test_authorized = $false
        retained_probe_authorized = $false
        official_launch_authorized = $false
        official_input_authorized = $false
        automatic_retry_authorized = $false
        authorization_requires_new_external_review = $true
        inherited_v27_authorization = $false
    }
    canonical_certificate_path = "$muniV28Wsl/planora-muni-fspsx-frontier-v28-certificate.json"
    builder_source = [ordered]@{
        path = "scripts/build_muni_v28_chain.ps1"
        sha256 = $muniBuilderHashAtStart
    }
    scope = "preserved v28 successor after the v27 canonical-evidence NO-GO; no WSL Docker browser official input retained probe solver or publication was opened or run"
    parent_chain = $muniManifest.parent_chain
    parent_v27_canonical_evidence_no_go = $muniNoGoEvidence
    mandatory_next_external_canonical_runner = $muniNoGoEvidence.mandatory_next_external_canonical_runner
    historical_lineage_integrity = $muniManifest.historical_lineage_integrity
    files = $muniCertificateFiles
    current_source_hashes = $muniSourceHashes
    source_closure_parent_manifest_sha256 = $muniParentManifestHash
    runtime_closure_parent_manifest_sha256 = $muniParentManifestHash
    resource_contract = $muniParentCertificate.resource_contract
    proc_observation_contract = [ordered]@{
        inherited_v27_runtime_semantics_byte_equivalent_after_identity_normalization = $true
        only_confirmed_enoent_or_esrch_means_absence = $true
        permission_eio_malformed_identity_status_and_other_uncertainty_reject = $true
    }
    canonical_test_contract = [ordered]@{
        unique_tests = 119
        expected_passes = 117
        expected_skips = 2
        expected_failures = 0
        expected_errors = 0
        exact_skip_reasons = $muniExpectedSkips
        staged_legacy_hash_rows = 48
    }
    contained_bwrap_contract = [ordered]@{
        schema = "planora.muni-fspsx.frontier-v28.bwrap-argv.v1"
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
        parent_v27_builder_manifest_certificate_tests = "PASS"
        v27_passing_canonical_logs_receipt_plan_exit_cleanup_authorization = "PASS_PINNED_EXACT"
        independent_v27_canonical_evidence_no_go = "PASS_PRESERVED"
        v12_v15_canonical_hash_rows = "PASS_48_EXACT"
        v16_v27_tree_pins = "PASS"
        v27_files_modified = $false
        runtime_semantics_v27_equivalent = "PASS_INVERSE_IDENTITY_REPLAY"
        exact_bwrap_argv_count = "PASS_48_PROBE_48_OFFICIAL"
        probe_and_official_argv_distinct = "PASS"
        powershell_parse = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        python_ast = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        v28_windows_safe_tests = "PENDING_EXTERNAL_WINDOWS_SAFE_VERIFICATION"
        canonical_read_only_tests = "NOT_RUN"
        retained_probe = "NOT_RUN"
        heavy_work_skipped = $true
        official_input_opened = $false
        solver_run = $false
    }
}
$muniCertificatePath = Join-Path $muniV28Root "planora-muni-fspsx-frontier-v28-certificate.json"
Write-MuniUtf8 $muniCertificatePath (($muniCertificate | ConvertTo-Json -Depth 35) + "`n")

$muniManifestRows = @{}
foreach ($row in $muniManifest.files) {
    $muniManifestRows[[string]$row.label] = $row
}
foreach ($entry in $muniFilePathByLabel.GetEnumerator()) {
    if (-not $muniManifestRows.ContainsKey($entry.Key) -or
        $muniManifestRows[$entry.Key].sha256 -ne $muniArtifactHashes[$entry.Key]) {
        throw "Generated manifest replay failed: $($entry.Key)"
    }
}
if ($muniManifestRows["v27_canonical_evidence_no_go"].sha256 -ne $muniNoGoHash) {
    throw "Generated manifest no-go evidence replay failed"
}
foreach ($entry in $muniSourceHashes.GetEnumerator()) {
    if (-not $muniManifestRows.ContainsKey($entry.Key) -or
        $muniManifestRows[$entry.Key].sha256 -ne $entry.Value -or
        (Get-MuniSha256 $muniSourcePaths[$entry.Key]) -ne $entry.Value) {
        throw "Generated source closure replay failed: $($entry.Key)"
    }
}
Assert-MuniHistoricalLineage
foreach ($entry in $muniCanonicalEvidencePins.GetEnumerator()) {
    Assert-MuniPinnedFile (Join-Path $muniEvidenceRoot $entry.Key) $entry.Value "v27 canonical evidence after construction $($entry.Key)"
}
if ((Get-MuniSha256 $muniBuilderPath) -ne $muniBuilderHashAtStart) {
    throw "MUNI v28 builder source changed during construction"
}

[ordered]@{
    target = $muniV28Root
    builder_sha256 = $muniBuilderHashAtStart
    manifest_sha256 = $muniManifestHash
    certificate_sha256 = Get-MuniSha256 $muniCertificatePath
    no_go_evidence_sha256 = $muniNoGoHash
    artifact_sha256 = $muniArtifactHashes
    parent_v27_builder_sha256 = $muniParentBuilderHash
    parent_v27_manifest_sha256 = $muniParentManifestHash
    parent_v27_certificate_sha256 = $muniParentCertificateHash
    parent_v27_tests_sha256 = $muniParentTestsHash
    preserved_v27_evidence_rows = $muniCanonicalEvidencePins.Count + 1
    preserved_v12_v15_hash_rows = $muniV28LegacyRows.Count
    preserved_v16_v27_tree_rows = $muniHistoricalTreePins.Count
    canonical_test_authorized = $false
    retained_probe_authorized = $false
    official_launch_authorized = $false
    official_input_authorized = $false
    official_input_opened = $false
    solver_run = $false
} | ConvertTo-Json -Depth 15
