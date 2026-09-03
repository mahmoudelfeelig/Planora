Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$wsl = 'C:\Windows\System32\wsl.exe'
$repo = 'C:\mnt\d\stuff\projects\sites\planora'
$repoWsl = '/mnt/d/Stuff/Projects/Sites/Planora'
$runId = '3913458278a647e9b3a635c7452ae2d6'
$root = "/tmp/planora-muni-v26-readonly-tests-$runId"
$prefix = Join-Path $repo "output\diagnostic-receipts\muni-fspsx-v26-canonical-readonly-tests-$runId"
$authorization = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v26-canonical-tests-authorization-20260827T034050Z.receipt.json'

$testFile = Join-Path $repo 'benchmarks\probe_diagnostics\muni_v26\planora-muni-fspsx-frontier-v26-tests.py'
$certificateFile = Join-Path $repo 'benchmarks\probe_diagnostics\muni_v26\planora-muni-fspsx-frontier-v26-certificate.json'
$manifestFile = Join-Path $repo 'benchmarks\probe_diagnostics\muni_v26\planora-muni-fspsx-frontier-v26-freeze-manifest.json'
$builderFile = Join-Path $repo 'scripts\build_muni_v26_chain.ps1'

function Assert-LocalPin {
    param([string]$Path, [long]$Size, [string]$Hash)
    $item = Get-Item -LiteralPath $Path
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($item.Length -ne $Size -or $actual -ne $Hash) {
        throw "Local pin drift: $Path"
    }
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Value)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Value, $encoding)
}

Assert-LocalPin $authorization 2476 '5f710235a29c3230533e6cb2e04f21592f62df323452ff25ba955db41fc1f9a4'
Assert-LocalPin $builderFile 62157 'faec7c322543427e440de08a0644e1715a15c9500e767abaab08bb2ef6f498c0'
Assert-LocalPin $testFile 175454 '33888b6ecaa74c20bb59ba3416eb96edb011feb84bcb0e55283b8bf4bcc24341'
Assert-LocalPin $certificateFile 30311 'ed9226597e871f9254f9aa7099617144a93a216fab2153f238694e9e336be15d'
Assert-LocalPin $manifestFile 35987 '8220439619602cee750edcf0b950474f85899c727953a7d024936599b8e0c29d'

$source = Get-Content -Raw -LiteralPath $testFile
$matches = [regex]::Matches(
    $source,
    '(?m)^\s*"(?<path>/tmp/planora[^"]+)":\s*"(?<hash>[0-9a-f]{64})",?$'
)
$rows = @(
    foreach ($match in $matches) {
        $path = $match.Groups['path'].Value
        $leaf = $path.Substring('/tmp/'.Length)
        [pscustomobject]@{
            Source = $path
            Leaf = $leaf
            Hash = $match.Groups['hash'].Value
            Target = "$root/$leaf"
        }
    }
)

if ($rows.Count -ne 48 -or @($rows.Leaf | Sort-Object -Unique).Count -ne 48) {
    throw "Legacy allowlist rejected: rows=$($rows.Count)"
}
foreach ($version in 12,13,14,15) {
    if (@($rows | Where-Object Leaf -Match "v$version").Count -ne 12) {
        throw "Expected exactly 12 v$version artifacts"
    }
}
if ($rows.Leaf -match '(?i)official|input|progress|checkpoint|solution|derivation-audit') {
    throw 'Forbidden artifact detected in canonical-suite allowlist'
}

foreach ($row in $rows) {
    & $wsl -d Ubuntu -- test -f $row.Source
    if ($LASTEXITCODE -ne 0) { throw "Missing source: $($row.Source)" }
    & $wsl -d Ubuntu -- test ! -L $row.Source
    if ($LASTEXITCODE -ne 0) { throw "Symlink source rejected: $($row.Source)" }
    $actual = (& $wsl -d Ubuntu -- sha256sum -- $row.Source).Split()[0]
    if ($LASTEXITCODE -ne 0 -or $actual -ne $row.Hash) {
        throw "Legacy source pin drift: $($row.Source)"
    }
}

$pythonHash = (& $wsl -d Ubuntu -- sha256sum -- /usr/bin/python3.12).Split()[0]
if ($LASTEXITCODE -ne 0 -or $pythonHash -ne 'c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273') {
    throw 'Python 3.12 pin drift'
}

& $wsl -d Ubuntu -- test ! -e $root
if ($LASTEXITCODE -ne 0) { throw "Root already exists: $root" }
& $wsl -d Ubuntu -- install -d -m 0700 -- $root
if ($LASTEXITCODE -ne 0) { throw 'Private-root creation failed' }
foreach ($row in $rows) {
    & $wsl -d Ubuntu -- install -m 0400 -- $row.Source $row.Target
    if ($LASTEXITCODE -ne 0) { throw "Staging failed: $($row.Source)" }
}

$rootStat = & $wsl -d Ubuntu -- stat -c '%a %U:%G' $root
if ($LASTEXITCODE -ne 0 -or -not $rootStat.StartsWith('700 ')) {
    throw "Private-root contract rejected: $rootStat"
}
$actualPaths = @(& $wsl -d Ubuntu -- find $root -mindepth 1 -maxdepth 1 -type f -print)
$actualNames = @($actualPaths | ForEach-Object { [System.IO.Path]::GetFileName($_) })
$nonFiles = @(& $wsl -d Ubuntu -- find $root -mindepth 1 -maxdepth 1 ! -type f -print)
if ($nonFiles.Count -ne 0 -or $actualNames.Count -ne 48) {
    throw 'Staging root is not exactly 48 regular files'
}
if (Compare-Object ($rows.Leaf | Sort-Object) ($actualNames | Sort-Object)) {
    throw 'Staging-root filename set differs from the allowlist'
}
foreach ($row in $rows) {
    $actual = (& $wsl -d Ubuntu -- sha256sum -- $row.Target).Split()[0]
    if ($LASTEXITCODE -ne 0 -or $actual -ne $row.Hash) {
        throw "Staged pin drift: $($row.Target)"
    }
}

function Get-MemAvailable {
    $line = & $wsl -d Ubuntu -- grep '^MemAvailable:' /proc/meminfo
    if ($LASTEXITCODE -ne 0 -or $line -notmatch '^MemAvailable:\s+(\d+)\s+kB$') {
        throw 'Could not read MemAvailable'
    }
    return [long]$Matches[1]
}

function Get-HeavyProcesses {
    $processes = & $wsl -d Ubuntu -- ps -eo pid=,ppid=,stat=,rss=,args=
    return @(
        $processes |
            Select-String -CaseSensitive:$false -Pattern 'planora-muni.*(tests|probe|launch)|agent-agh|planora-puproj|--sealed-import-probe|--launch|itc2019.*solve'
    )
}

$mem1 = Get-MemAvailable
$heavy1 = @(Get-HeavyProcesses)
if ($mem1 -lt 1900000 -or $heavy1.Count -ne 0) { throw 'First admission sample failed' }
Start-Sleep -Milliseconds 5200
$mem2 = Get-MemAvailable
$heavy2 = @(Get-HeavyProcesses)
if ($mem2 -lt 1900000 -or $heavy2.Count -ne 0) { throw 'Second admission sample failed' }

$stdout = "$prefix.stdout.log"
$stderr = "$prefix.stderr.log"
$exitFile = "$prefix.exit-code.txt"
$planFile = "$prefix.plan.json"
$receiptFile = "$prefix.receipt.json"
foreach ($path in $stdout,$stderr,$exitFile,$planFile,$receiptFile) {
    if (Test-Path -LiteralPath $path) { throw "Evidence path already exists: $path" }
}

$argv = @(
    '-d','Ubuntu','--',
    '/usr/bin/timeout','600s',
    '/usr/bin/bwrap','--die-with-parent','--new-session','--unshare-all',
    '--ro-bind','/','/',
    '--bind',$root,'/tmp',
    '--dev','/dev','--proc','/proc','--clearenv',
    '--setenv','PATH','/usr/bin:/bin',
    '--setenv','LANG','C.UTF-8',
    '--setenv','LC_ALL','C.UTF-8',
    '--setenv','TZ','UTC',
    '--setenv','PLANORA_MUNI_V26_SKIP_HEAVY','1',
    '--cap-drop','ALL',
    '--chdir',$repoWsl,
    '/usr/bin/python3.12','-I','-S','-B',
    "$repoWsl/benchmarks/probe_diagnostics/muni_v26/planora-muni-fspsx-frontier-v26-tests.py"
)

$planJson = [ordered]@{
    schema = 'planora.muni-v26.canonical-readonly-plan.v1'
    run_id = $runId
    authorization_sha256 = '5f710235a29c3230533e6cb2e04f21592f62df323452ff25ba955db41fc1f9a4'
    private_tmp_root = $root
    private_tmp_mode = '0700'
    staged_artifacts = $rows
    memavailable_samples_kib = @($mem1,$mem2)
    competing_heavy_processes = @()
    argv = @('wsl.exe') + $argv
    official_input_opened = $false
    progress_or_checkpoint_staged = $false
    probe_or_solver_authorized = $false
} | ConvertTo-Json -Depth 8
Write-Utf8NoBom -Path $planFile -Value $planJson

$process = Start-Process `
    -FilePath $wsl `
    -ArgumentList $argv `
    -WindowStyle Hidden `
    -Wait `
    -PassThru `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr
$process.ExitCode | Set-Content -Encoding ascii -LiteralPath $exitFile

$stderrText = Get-Content -Raw -LiteralPath $stderr
$stdoutSize = (Get-Item -LiteralPath $stdout).Length
$postPaths = @(& $wsl -d Ubuntu -- find $root -mindepth 1 -maxdepth 1 -type f -print)
$postNames = @($postPaths | ForEach-Object { [System.IO.Path]::GetFileName($_) })
$postNonFiles = @(& $wsl -d Ubuntu -- find $root -mindepth 1 -maxdepth 1 ! -type f -print)
$postHeavy = @(Get-HeavyProcesses)
$postMem = Get-MemAvailable
$accepted = (
    $process.ExitCode -eq 0 -and
    $stdoutSize -eq 0 -and
    $stderrText -match '(?m)^Ran 119 tests in [0-9.]+s\r?$' -and
    $stderrText -match '(?m)^OK \(skipped=2\)\r?$' -and
    ([regex]::Matches($stderrText,[regex]::Escape("skipped 'heavy sealed-runtime import probe disabled by test contract'")).Count -eq 1) -and
    ([regex]::Matches($stderrText,[regex]::Escape("skipped 'real sealed chain admission disabled by test contract'")).Count -eq 1) -and
    $stderrText -notmatch '(?m)^FAILED|^ERROR:' -and
    $postNonFiles.Count -eq 0 -and
    $postNames.Count -eq 48 -and
    -not (Compare-Object ($rows.Leaf | Sort-Object) ($postNames | Sort-Object)) -and
    $postHeavy.Count -eq 0
)

$receiptJson = [ordered]@{
    schema = 'planora.itc2019.canonical-test-receipt.v1'
    instance = 'muni-fspsx-fal17'
    diagnostic_chain = 'muni_v26'
    test_id = $runId
    decision = if ($accepted) { 'PASS_FOR_ONE_RETAINED_NO_SOLVER_PROBE_ONLY' } else { 'REJECTED' }
    official_launch_authorized = $false
    retained_probe_authorized = $accepted
    process_exit_code = $process.ExitCode
    expected = @{ tests_run=119; passed=117; skipped=2; failures=0; errors=0 }
    pretest_memavailable_samples_kib = @($mem1,$mem2)
    post_exit_memavailable_kib = $postMem
    residual_heavy_processes = @($postHeavy | ForEach-Object Line)
    root_unchanged_at_48_exact_files = ($postNonFiles.Count -eq 0 -and $postNames.Count -eq 48 -and -not (Compare-Object ($rows.Leaf | Sort-Object) ($postNames | Sort-Object)))
    official_input_opened = $false
    progress_or_checkpoint_staged = $false
    solver_run = $false
    logs = @{
        stdout = @{ path=$stdout; size=(Get-Item $stdout).Length; sha256=(Get-FileHash -Algorithm SHA256 $stdout).Hash.ToLowerInvariant() }
        stderr = @{ path=$stderr; size=(Get-Item $stderr).Length; sha256=(Get-FileHash -Algorithm SHA256 $stderr).Hash.ToLowerInvariant() }
    }
    plan_sha256 = (Get-FileHash -Algorithm SHA256 $planFile).Hash.ToLowerInvariant()
    exit_file_sha256 = (Get-FileHash -Algorithm SHA256 $exitFile).Hash.ToLowerInvariant()
} | ConvertTo-Json -Depth 8
Write-Utf8NoBom -Path $receiptFile -Value $receiptJson

if (-not $accepted) { throw "MUNI v26 canonical suite rejected; inspect $receiptFile" }
Write-Output "PASS: $receiptFile"
