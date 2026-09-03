param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v11"
$targetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v12"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$bashSha256 = "bc5945feb8bd26203ebfafea5ce1878bb2e32cb8fb50ab7ae395cfb1e1aaaef1"
$bashSizeBytes = 1446024
$pythonSha256 = "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273"
$pythonSizeBytes = 8020928
$officialInputSha256 = "bae3363ed68e895280cd33bc20686bf396932f532c2b197f7b863f4167437528"
$officialInputSizeBytes = 44961985
$runtimeBundleBytes = 191956270
$barrierFd = 198
$barrierLoader = "import os,sys;fd=int(sys.argv[1]);token=os.read(fd,1);os.close(fd);token==b'G' or (_ for _ in ()).throw(RuntimeError('outer barrier rejected'));marker=sys.argv.index('--');argv=sys.argv[marker+1:];argv or (_ for _ in ()).throw(RuntimeError('inner argv missing'));os.execve(argv[0],argv,dict(os.environ))"
$outerControllerFd = 196
$freezeManifestFd = 197
$outerFdLoader = @'
import errno,fcntl,hashlib,os,stat,sys
required=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
identity=lambda row:(int(row.st_dev),int(row.st_ino),int(row.st_size),stat.S_IFMT(row.st_mode),stat.S_IMODE(row.st_mode),int(row.st_uid),int(row.st_nlink))
def capture(path,expected,target,label):
 if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected): raise RuntimeError(label+' expected hash rejected')
 try: os.fstat(target)
 except OSError as exc:
  if exc.errno!=errno.EBADF: raise
 else: raise RuntimeError(label+' fixed descriptor occupied')
 parent=os.path.dirname(path);name=os.path.basename(path);parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0));parent_row=os.fstat(parent_fd);source_fd=os.open(name,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0),dir_fd=parent_fd);before=os.fstat(source_fd)
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>(4<<20): raise RuntimeError(label+' source contract rejected')
 raw=os.pread(source_fd,before.st_size,0);after=os.fstat(source_fd);named=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
 os.close(source_fd);os.close(parent_fd)
 if len(raw)!=before.st_size or identity(before)!=identity(after) or identity(after)!=identity(named) or hashlib.sha256(raw).hexdigest()!=expected: raise RuntimeError(label+' source drift')
 descriptor=os.memfd_create('aghfal17-v12-'+label,getattr(os,'MFD_ALLOW_SEALING',0x0002));view=memoryview(raw)
 while view:
  written=os.write(descriptor,view)
  if written<=0: raise RuntimeError(label+' sealed write failed')
  view=view[written:]
 os.fchmod(descriptor,0o400);fcntl.fcntl(descriptor,fcntl.F_ADD_SEALS,required)
 if int(fcntl.fcntl(descriptor,fcntl.F_GET_SEALS))&required!=required: raise RuntimeError(label+' sealing failed')
 os.dup2(descriptor,target,inheritable=True);os.close(descriptor);return len(raw)
outer_path,outer_hash,freeze_path,freeze_hash=sys.argv[1:5];forwarded=sys.argv[5:]
capture(outer_path,outer_hash,196,'outer-controller');capture(freeze_path,freeze_hash,197,'freeze-manifest')
environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TZ':'UTC'}
argv=['/proc/self/exe','-I','-S','-B','/proc/self/fd/196',*forwarded]
os.execve('/proc/self/exe',argv,environment)
'@.Trim()

if (-not (Test-Path -LiteralPath $sourceRoot)) {
    throw "AGH v11 source chain is missing: $sourceRoot"
}
if (-not (Test-Path -LiteralPath $targetRoot)) {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}

$outerName = "agent-aghfal17-native-v12-outer-controller.py"
$testsName = "agent-aghfal17-native-v12-tests.py"
$ownedGeneratedNames = @(
    "agent-aghfal17-native-v12-bootstrap.py",
    "agent-aghfal17-native-v12-generic-validator.py",
    "agent-aghfal17-native-v12-launcher.sh",
    "agent-aghfal17-native-v12-minimal-tcb.sha256",
    "agent-aghfal17-native-v12-invocations.json",
    "agent-aghfal17-native-v12-review-freeze.json",
    "agent-aghfal17-native-v12-runner.py",
    "agent-aghfal17-native-v12-stdlib.sha256",
    "agent-aghfal17-native-v12-supervisor.py"
)
$existingGenerated = @(
    $ownedGeneratedNames |
        Where-Object { Test-Path -LiteralPath (Join-Path $targetRoot $_) }
)
if ($existingGenerated.Count -gt 0 -and -not $Force) {
    throw "Refusing to overwrite generated AGH v12 artifacts without -Force: $($existingGenerated -join ', ')"
}
if ($Force) {
    foreach ($name in $ownedGeneratedNames) {
        $path = Join-Path $targetRoot $name
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path
        }
    }
}

$outerPath = Join-Path $targetRoot $outerName
$testsPath = Join-Path $targetRoot $testsName
foreach ($required in @($outerPath, $testsPath)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Hand-authored AGH v12 source is missing: $required"
    }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
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
    $Text = $Text.Replace("aghfal17-v11", "aghfal17-v12")
    $Text = $Text.Replace("native-v11", "native-v12")
    $Text = $Text.Replace("NATIVE_V11", "NATIVE_V12")
    $Text = $Text.Replace("native_v11", "native_v12")
    $Text = $Text.Replace("NativeV11", "NativeV12")
    $Text = $Text.Replace("AGH-FAL17 v11", "AGH-FAL17 v12")
    $Text = $Text.Replace("agh-v11", "agh-v12")
    return $Text
}

function Write-Generated(
    [string]$SourceName,
    [string]$DestinationName,
    [scriptblock]$Transform
) {
    $source = Join-Path $sourceRoot $SourceName
    $destination = Join-Path $targetRoot $DestinationName
    $text = Convert-Version (Read-Utf8 $source)
    $text = & $Transform $text
    Write-Utf8 $destination $text
    return $destination
}

function Get-CanonicalArgvSha256([string[]]$Argv) {
    foreach ($value in $Argv) {
        if ($value.Contains([char]0)) {
            throw "Canonical argv contains NUL"
        }
    }
    $raw = $utf8NoBom.GetBytes([string]::Join([char]0, $Argv))
    $digest = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([Convert]::ToHexString($digest.ComputeHash($raw))).ToLowerInvariant()
    }
    finally {
        $digest.Dispose()
    }
}

function New-Allocation([string]$Id, [long]$Size, [string]$Source) {
    if ($Size -lt 0) {
        throw "Negative sealed allocation size: $Id"
    }
    return [ordered]@{
        allocation_id = $Id
        size_bytes = $Size
        source = $Source
    }
}

$moduleFiles = [ordered]@{
    planora_benchmarks_init = "benchmarks\__init__.py"
    planora_benchmarks_corpus = "benchmarks\corpus.py"
    planora_itc2019 = "benchmarks\itc2019.py"
    planora_itc2019_compact_joint = "benchmarks\itc2019_compact_joint.py"
    planora_itc2019_decomposed = "benchmarks\itc2019_decomposed.py"
    planora_itc2019_decomposed_quality = "benchmarks\itc2019_decomposed_quality.py"
    planora_itc2019_factorized = "benchmarks\itc2019_factorized.py"
    planora_itc2019_generalized_occurrences = "benchmarks\itc2019_generalized_occurrences.py"
    planora_itc2019_global_components = "benchmarks\itc2019_global_components.py"
    planora_itc2019_global_quality = "benchmarks\itc2019_global_quality.py"
    planora_itc2019_grouped_calendar = "benchmarks\itc2019_grouped_calendar.py"
    planora_itc2019_resource_seed = "benchmarks\itc2019_resource_seed.py"
    planora_itc2019_sparse_joint = "benchmarks\itc2019_sparse_joint.py"
    planora_itc2019_structural = "benchmarks\itc2019_structural.py"
    planora_itc2019_violation_lns = "benchmarks\itc2019_violation_lns.py"
}
$moduleHashes = [ordered]@{}
$moduleSizes = [ordered]@{}
foreach ($entry in $moduleFiles.GetEnumerator()) {
    $path = Join-Path $repositoryRoot $entry.Value
    $moduleHashes[$entry.Key] = Get-Sha256 $path
    $moduleSizes[$entry.Key] = (Get-Item -LiteralPath $path).Length
}

$genericName = "agent-aghfal17-native-v12-generic-validator.py"
$genericPath = Write-Generated `
    "agent-aghfal17-native-v11-generic-validator.py" `
    $genericName `
    { param($text) return $text }
$genericHash = Get-Sha256 $genericPath

$runnerName = "agent-aghfal17-native-v12-runner.py"
$runnerPath = Write-Generated `
    "agent-aghfal17-native-v11-runner.py" `
    $runnerName `
    {
        param($text)
        $text = Replace-Required $text "5a64e57fb81d088e97dd6f471657b9a5599d31e9fbf014dce2b31f3fd0bf09b6" $genericHash "runner generic validator pin"
        $text = Replace-Required $text "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63" $moduleHashes.planora_itc2019_decomposed "runner decomposed pin"
        $text = Replace-Required $text "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe" $moduleHashes.planora_itc2019_sparse_joint "runner sparse pin"
        $text = Replace-Required $text "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b" $moduleHashes.planora_itc2019_violation_lns "runner violation pin"
        return $text
    }
$runnerHash = Get-Sha256 $runnerPath

$supervisorName = "agent-aghfal17-native-v12-supervisor.py"
$supervisorPath = Write-Generated `
    "agent-aghfal17-native-v11-supervisor.py" `
    $supervisorName `
    {
        param($text)
        $text = Replace-Required $text "785cf5b950653894d82e9f118f4373faf1f68ef605c3a19bab67c996ffad4cb1" $runnerHash "supervisor runner pin"
        $text = Replace-Required $text "19ca8fbe7c699ee454b90352577d0e6995a592059cd241aeb8ea6d8484f5437f" $genericHash "supervisor generic pin"
        $text = Replace-Required $text "a96e5fcd98b30ce69ff0a51e6fb1b65243d84d502f5873854423780de68b4b63" $moduleHashes.planora_itc2019_decomposed "supervisor decomposed pin"
        $text = Replace-Required $text "393f13042ef84e3040b17caefa407c63be32a50913f7edc456cbad836af9ccfe" $moduleHashes.planora_itc2019_sparse_joint "supervisor sparse pin"
        $text = Replace-Required $text "af902e522b980cd511f4633c39d7f76ccddcd417f94b8cdc8785f389a831317b" $moduleHashes.planora_itc2019_violation_lns "supervisor violation pin"
        $text = Replace-Required $text "SUPERVISOR_HARD_WALL_SECONDS = 1_800.0" "SUPERVISOR_HARD_WALL_SECONDS = 1_780.0" "inner cleanup wall reservation"
        $text = $text.Replace(
            '"whole_launch_monitoring_without_double_count": True,',
            ('"inner_monitoring_without_double_count": True,' + [Environment]::NewLine + '        "outer_controller_authoritative": True,')
        )
        return $text
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherName = "agent-aghfal17-native-v12-launcher.sh"
$launcherPath = Write-Generated `
    "agent-aghfal17-native-v11-launcher.sh" `
    $launcherName `
    {
        param($text)
        $text = Replace-Required $text "0ff6364de655f1972cedf94072e707b3caad0bfa345b4ee856b1c40e8eeb80eb" $supervisorHash "launcher supervisor pin"
        return $text
    }
$launcherHash = Get-Sha256 $launcherPath

$bootstrapName = "agent-aghfal17-native-v12-bootstrap.py"
$bootstrapPath = Write-Generated `
    "agent-aghfal17-native-v11-bootstrap.py" `
    $bootstrapName `
    {
        param($text)
        $text = [regex]::Replace(
            $text,
            '(?ms)^PROBE_HARNESS = Path\("/tmp/agent-aghfal17-native-v12-probe-harness\.py"\)\r?\nEXPECTED_PROBE_HARNESS_SHA256 = \(\r?\n    "[0-9a-f]{64}"\r?\n\)\r?\n',
            ''
        )
        $text = [regex]::Replace(
            $text,
            '(?ms)^    harness_fd, _harness = capture_sealed_source\(\r?\n        PROBE_HARNESS,\r?\n        EXPECTED_PROBE_HARNESS_SHA256,\r?\n        "probe-harness",\r?\n        executable=False,\r?\n    \)\r?\n',
            ''
        )
        $text = Replace-Required $text "for descriptor in (bootstrap_fd, launcher_fd, bash_fd, harness_fd):" "for descriptor in (bootstrap_fd, launcher_fd, bash_fd):" "bootstrap inherited descriptors"
        $text = [regex]::Replace(
            $text,
            '(?ms)^    if forwarded == \["--sealed-import-probe"\]:\r?\n.*?^        raise AssertionError\("sealed probe harness exec unexpectedly returned"\)\r?\n',
            ''
        )
        if ($text.Contains("PROBE_HARNESS") -or $text.Contains("harness_fd")) {
            throw "Probe-only harness routing survived bootstrap generation"
        }
        return $text
    }
$bootstrapHash = Get-Sha256 $bootstrapPath

$minimalName = "agent-aghfal17-native-v12-minimal-tcb.sha256"
$minimalPath = Join-Path $targetRoot $minimalName
[System.IO.File]::Copy(
    (Join-Path $sourceRoot "agent-aghfal17-native-v11-minimal-tcb.sha256"),
    $minimalPath,
    $true
)
$stdlibName = "agent-aghfal17-native-v12-stdlib.sha256"
$stdlibPath = Join-Path $targetRoot $stdlibName
[System.IO.File]::Copy(
    (Join-Path $sourceRoot "agent-aghfal17-native-v11-stdlib.sha256"),
    $stdlibPath,
    $true
)

$bootstrapText = Read-Utf8 $bootstrapPath
$loaderMatch = [regex]::Match(
    $bootstrapText,
    "(?s)BOOTSTRAP_FD_LOADER = r'''(.*?)'''\.strip\(\)"
)
if (-not $loaderMatch.Success) {
    throw "Generated bootstrap loader source could not be extracted"
}
$bootstrapLoader = $loaderMatch.Groups[1].Value.Trim()
$outerText = Read-Utf8 $outerPath
if (-not $outerText.Contains("BARRIER_LOADER = (") -or -not $outerText.Contains("BARRIER_FD = $barrierFd")) {
    throw "Outer controller barrier contract drifted"
}
foreach ($token in @(
    "WHOLE_LAUNCH_MEMORY_LIMIT_KIB = 614_400",
    "PROCESS_GENERATION_MEMORY_LIMIT_KIB = 368_640",
    "INITIAL_MEMAVAILABLE_FLOOR_KIB = 1_900_000",
    "RUNTIME_MEMAVAILABLE_FLOOR_KIB = 900_000",
    "PROBE_OUTER_WALL_SECONDS = 240.0",
    "LAUNCH_OUTER_WALL_SECONDS = 1_800.0"
)) {
    if (-not $outerText.Contains($token)) {
        throw "Outer controller resource contract drifted: $token"
    }
}
foreach ($token in @(
    "class ProcessIdentity:",
    "class ProcessTopology:",
    "class ProcInspectionError(RuntimeError):",
    "FINAL_ZERO_SNAPSHOTS_REQUIRED = 2",
    "def final_zero_fixed_point("
)) {
    if (-not $outerText.Contains($token)) {
        throw "Outer controller containment contract drifted: $token"
    }
}

$bootstrapBase = @(
    "/usr/bin/python3.12", "-I", "-S", "-B", "-c", $bootstrapLoader,
    "/tmp/$bootstrapName", $bootstrapHash, $pythonSha256,
    "--expected-bootstrap-sha256", $bootstrapHash,
    "--launcher", "/tmp/$launcherName",
    "--expected-launcher-sha256", $launcherHash,
    "--bash", "/usr/bin/bash",
    "--expected-bash-sha256", $bashSha256,
    "--"
)
$probeInner = @($bootstrapBase + "--sealed-import-probe")
$launchInner = @($bootstrapBase + "--launch")
$probeArgv = @(
    "/usr/bin/python3.12", "-I", "-S", "-B", "-c", $barrierLoader,
    [string]$barrierFd, "--"
) + $probeInner
$launchArgv = @(
    "/usr/bin/python3.12", "-I", "-S", "-B", "-c", $barrierLoader,
    [string]$barrierFd, "--"
) + $launchInner
$probeCommandHash = Get-CanonicalArgvSha256 $probeArgv
$launchCommandHash = Get-CanonicalArgvSha256 $launchArgv
if ($probeCommandHash -eq $launchCommandHash) {
    throw "Probe and launch canonical command digests unexpectedly match"
}

$runtimeRecords = [ordered]@{
    runtime_ortools_record = ".venv\lib\python3.12\site-packages\ortools-9.15.6755.dist-info\RECORD"
    runtime_numpy_record = ".venv\lib\python3.12\site-packages\numpy-2.4.2.dist-info\RECORD"
    runtime_pandas_record = ".venv\lib\python3.12\site-packages\pandas-3.0.1.dist-info\RECORD"
    runtime_dateutil_record = ".venv\lib\python3.12\site-packages\python_dateutil-2.9.0.post0.dist-info\RECORD"
    runtime_six_record = ".venv\lib\python3.12\site-packages\six-1.17.0.dist-info\RECORD"
    runtime_lxml_record = ".venv\lib\python3.12\site-packages\lxml-6.1.0.dist-info\RECORD"
    runtime_absl_record = ".venv\lib\python3.12\site-packages\absl_py-2.4.0.dist-info\RECORD"
    runtime_immutabledict_record = ".venv\lib\python3.12\site-packages\immutabledict-4.3.1.dist-info\RECORD"
    runtime_protobuf_record = ".venv\lib\python3.12\site-packages\protobuf-6.33.5.dist-info\RECORD"
    runtime_typing_extensions_record = ".venv\lib\python3.12\site-packages\typing_extensions-4.15.0.dist-info\RECORD"
}
$runtimeRows = [ordered]@{}
foreach ($entry in $runtimeRecords.GetEnumerator()) {
    $path = Join-Path $repositoryRoot $entry.Value
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Pinned runtime RECORD is missing: $path"
    }
    $runtimeRows[$entry.Key] = [ordered]@{
        path = ($entry.Value -replace '\\', '/')
        size_bytes = (Get-Item -LiteralPath $path).Length
        sha256 = Get-Sha256 $path
    }
}

$freezeName = "agent-aghfal17-native-v12-review-freeze.json"
$freezePath = Join-Path $targetRoot $freezeName
$freezeAllocation = New-Allocation "freeze-manifest-sealed" 0 "/tmp/$freezeName"
$commonAllocations = @(
    (New-Allocation "outer-controller-sealed" (Get-Item $outerPath).Length "/tmp/$outerName"),
    $freezeAllocation,
    (New-Allocation "minimal-tcb-loader-sealed" (Get-Item $minimalPath).Length "/tmp/$minimalName"),
    (New-Allocation "bootstrap-source-sealed" (Get-Item $bootstrapPath).Length "/tmp/$bootstrapName"),
    (New-Allocation "launcher-source-sealed" (Get-Item $launcherPath).Length "/tmp/$launcherName"),
    (New-Allocation "bash-binary-sealed" $bashSizeBytes "/usr/bin/bash"),
    (New-Allocation "runner-capture-sealed" (Get-Item $runnerPath).Length "/tmp/$runnerName"),
    (New-Allocation "python-binary-capture-sealed" $pythonSizeBytes "/usr/bin/python3.12"),
    (New-Allocation "stdlib-manifest-capture-sealed" (Get-Item $stdlibPath).Length "/tmp/$stdlibName")
)
foreach ($entry in $runtimeRows.GetEnumerator()) {
    $commonAllocations += New-Allocation "$($entry.Key)-capture-sealed" $entry.Value.size_bytes $entry.Value.path
}
$commonAllocations += New-Allocation "runtime-bundle-sealed-files" $runtimeBundleBytes "frozen-runtime-record-closure"
$probeAllocations = @($commonAllocations)
$launchAllocations = @($commonAllocations)
$launchAllocations += New-Allocation "generic-validator-capture-sealed" (Get-Item $genericPath).Length "/tmp/$genericName"
$launchAllocations += New-Allocation "minimal-tcb-supervisor-capture-sealed" (Get-Item $minimalPath).Length "/tmp/$minimalName"
$launchAllocations += New-Allocation "official-input-capture-sealed" $officialInputSizeBytes "data/input/ITC-2019/agh-fal17.xml"
foreach ($entry in $moduleFiles.GetEnumerator()) {
    $launchAllocations += New-Allocation "$($entry.Key)-capture-sealed" $moduleSizes[$entry.Key] ($entry.Value -replace '\\', '/')
}

$artifacts = [ordered]@{
    outer_controller = [ordered]@{ path = "/tmp/$outerName"; size_bytes = (Get-Item $outerPath).Length; sha256 = Get-Sha256 $outerPath }
    bootstrap = [ordered]@{ path = "/tmp/$bootstrapName"; size_bytes = (Get-Item $bootstrapPath).Length; sha256 = $bootstrapHash }
    launcher = [ordered]@{ path = "/tmp/$launcherName"; size_bytes = (Get-Item $launcherPath).Length; sha256 = $launcherHash }
    supervisor = [ordered]@{ path = "/tmp/$supervisorName"; size_bytes = (Get-Item $supervisorPath).Length; sha256 = $supervisorHash }
    runner = [ordered]@{ path = "/tmp/$runnerName"; size_bytes = (Get-Item $runnerPath).Length; sha256 = $runnerHash }
    generic_validator = [ordered]@{ path = "/tmp/$genericName"; size_bytes = (Get-Item $genericPath).Length; sha256 = $genericHash }
    minimal_tcb_manifest = [ordered]@{ path = "/tmp/$minimalName"; size_bytes = (Get-Item $minimalPath).Length; sha256 = Get-Sha256 $minimalPath }
    stdlib_manifest = [ordered]@{ path = "/tmp/$stdlibName"; size_bytes = (Get-Item $stdlibPath).Length; sha256 = Get-Sha256 $stdlibPath }
    tests = [ordered]@{ path = "/tmp/$testsName"; size_bytes = (Get-Item $testsPath).Length; sha256 = Get-Sha256 $testsPath }
}

$sourceClosure = [ordered]@{}
foreach ($entry in $moduleFiles.GetEnumerator()) {
    $sourceClosure[($entry.Value -replace '\\', '/')] = [ordered]@{
        size_bytes = $moduleSizes[$entry.Key]
        sha256 = $moduleHashes[$entry.Key]
    }
}

$freeze = [ordered]@{
    schema = "planora.agh-fal17.native-v12-freeze.v1"
    created_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    status = "GO_FOR_LIGHTWEIGHT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"
    scope = "AGH-FAL17 v12 authoritative outer control plane; official input never opened by this builder"
    artifacts = $artifacts
    source_closure = $sourceClosure
    runtime_records = $runtimeRows
    runtime_pins = [ordered]@{
        bash = [ordered]@{ path = "/usr/bin/bash"; size_bytes = $bashSizeBytes; sha256 = $bashSha256 }
        python = [ordered]@{ path = "/usr/bin/python3.12"; size_bytes = $pythonSizeBytes; sha256 = $pythonSha256 }
        runtime_bundle_file_count = 3077
        runtime_bundle_bytes = $runtimeBundleBytes
    }
    sealed_entry_loader = [ordered]@{
        protocol = "planora.aghfal17.native-v12-sealed-entry-loader.v1"
        source = $outerFdLoader
        source_sha256 = ([System.BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::HashData($utf8NoBom.GetBytes($outerFdLoader))
        ).Replace("-", "").ToLowerInvariant())
        controller_fd = $outerControllerFd
        freeze_manifest_fd = $freezeManifestFd
        controller_and_freeze_captured_to_sealed_memfds_before_execution = $true
    }
    official_input = [ordered]@{
        path = "/mnt/d/Stuff/Projects/Sites/Planora/data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/agh-fal17.xml"
        size_bytes = $officialInputSizeBytes
        sha256 = $officialInputSha256
        expected_classes = 5081
        opened_by_builder = $false
    }
    commands = [ordered]@{
        probe = [ordered]@{
            mode = "--sealed-import-probe"
            canonical_encoding = "utf8_nul_joined"
            canonical_argv_sha256 = $probeCommandHash
            argv = $probeArgv
        }
        launch = [ordered]@{
            mode = "--launch"
            canonical_encoding = "utf8_nul_joined"
            canonical_argv_sha256 = $launchCommandHash
            argv = $launchArgv
        }
    }
    sealed_storage_contract = [ordered]@{
        probe = [ordered]@{ allocations = $probeAllocations; report_bytes = "measured from unique outer-created memfd inode identities" }
        launch = [ordered]@{ allocations = $launchAllocations; report_bytes = "measured from unique outer-created memfd inode identities" }
    }
    resource_contract = [ordered]@{
        authoritative_component = "outer_controller"
        process_generation_vmrss_plus_vmswap_limit_kib = 368640
        whole_launch_process_plus_sealed_plus_report_limit_kib = 614400
        initial_memavailable_floor_kib = 1900000
        initial_sample_count = 2
        initial_sample_interval_seconds = 5.0
        runtime_memavailable_floor_kib = 900000
        probe_outer_wall_seconds = 240.0
        probe_inner_wall_seconds = 180.0
        launch_outer_wall_seconds = 1800.0
        launch_inner_wall_seconds = 1780.0
        child_cooperative_deadline_seconds = 1680.0
        barrier_fd = $barrierFd
        exact_identity = "pid_plus_starttime_plus_pidfd"
        mutable_topology = "ppid_pgid_sid_refreshed_without_generation_invalidation"
        proc_observation = "only_enoent_esrch_mean_vanished_all_other_failures_fail_closed"
        descendant_boundary = "fresh_fixed_point_parent_chain_plus_subreaper_orphans_across_sessions"
        cleanup = "pidfd_term_kill_then_reap_refresh_and_two_successive_zero_snapshots"
        final_zero_snapshots_required = 2
        numeric_process_group_signalling = $false
    }
    truth_contract = [ordered]@{
        probe_official_input_opened = $false
        probe_solver_child_started = $false
        probe_solver_execution_started = $false
        probe_publication = $false
        outer_status_overrides_inner_status = $true
        outer_post_exit_empty_required = $true
    }
    verification = [ordered]@{
        builder_platform = "windows_powershell"
        adversarial_tests_present = $true
        static_checks = "NOT_RUN"
        linux_adversarial_tests = "NOT_RUN"
        sealed_import_probe = "NOT_RUN"
        official_input_opened = $false
        solver_started = $false
        official_launch_authorized = $false
    }
}
$freezeText = $null
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    $candidate = ($freeze | ConvertTo-Json -Depth 12) + "`n"
    $candidateSize = $utf8NoBom.GetByteCount($candidate)
    if ($freezeAllocation.size_bytes -eq $candidateSize) {
        $freezeText = $candidate
        break
    }
    $freezeAllocation.size_bytes = $candidateSize
}
if ($null -eq $freezeText) {
    throw "Freeze manifest sealed-size fixed point did not converge"
}
Write-Utf8 $freezePath $freezeText
if ((Get-Item -LiteralPath $freezePath).Length -ne $freezeAllocation.size_bytes) {
    throw "Freeze manifest sealed-size contract drifted after write"
}
$freezeHash = Get-Sha256 $freezePath

$outerHash = Get-Sha256 $outerPath
$probeForwarded = @(
    "--mode", "probe",
    "--freeze", "/proc/self/fd/$freezeManifestFd",
    "--expected-freeze-sha256", $freezeHash,
    "--expected-controller-sha256", $outerHash,
    "--"
) + $probeInner
$launchForwarded = @(
    "--mode", "launch",
    "--freeze", "/proc/self/fd/$freezeManifestFd",
    "--expected-freeze-sha256", $freezeHash,
    "--expected-controller-sha256", $outerHash,
    "--"
) + $launchInner
$probeInvocation = @(
    "/usr/bin/python3.12", "-I", "-S", "-B", "-c", $outerFdLoader,
    "/tmp/$outerName", $outerHash,
    "/tmp/$freezeName", $freezeHash
) + $probeForwarded
$launchInvocation = @(
    "/usr/bin/python3.12", "-I", "-S", "-B", "-c", $outerFdLoader,
    "/tmp/$outerName", $outerHash,
    "/tmp/$freezeName", $freezeHash
) + $launchForwarded
$invocationsName = "agent-aghfal17-native-v12-invocations.json"
$invocationsPath = Join-Path $targetRoot $invocationsName
$invocations = [ordered]@{
    schema = "planora.agh-fal17.native-v12-invocations.v1"
    freeze_manifest = [ordered]@{
        path = "/tmp/$freezeName"
        sha256 = $freezeHash
    }
    sealed_entry_loader_sha256 = $freeze.sealed_entry_loader.source_sha256
    canonical_encoding = "utf8_nul_joined"
    probe = [ordered]@{
        argv = $probeInvocation
        canonical_argv_sha256 = Get-CanonicalArgvSha256 $probeInvocation
    }
    launch = [ordered]@{
        argv = $launchInvocation
        canonical_argv_sha256 = Get-CanonicalArgvSha256 $launchInvocation
    }
    authorization = [ordered]@{
        probe_run = $false
        official_launch = $false
        official_input_opened_by_builder = $false
    }
}
Write-Utf8 $invocationsPath (($invocations | ConvertTo-Json -Depth 8) + "`n")

[ordered]@{
    target = $targetRoot
    artifacts = $artifacts
    freeze = [ordered]@{
        path = $freezePath
        size_bytes = (Get-Item $freezePath).Length
        sha256 = $freezeHash
    }
    invocations = [ordered]@{
        path = $invocationsPath
        size_bytes = (Get-Item $invocationsPath).Length
        sha256 = Get-Sha256 $invocationsPath
    }
    commands = [ordered]@{
        probe_canonical_argv_sha256 = $probeCommandHash
        launch_canonical_argv_sha256 = $launchCommandHash
    }
    source_closure = $sourceClosure
} | ConvertTo-Json -Depth 10
