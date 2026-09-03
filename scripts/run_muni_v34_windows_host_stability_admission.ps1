param(
    [switch]$StaticSelfTest,
    [switch]$InspectPreconditions,
    [switch]$Observe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$admissionId = 'a5329b8ce4d7458ea26cb4351bb551fe'
$runId = '3c3ed012febd407da5202423b2a67d32'
$repo = 'D:\Stuff\Projects\Sites\Planora'
$receiptDirectory = Join-Path $repo 'output\diagnostic-receipts'
$scriptRelative = 'scripts/run_muni_v34_windows_host_stability_admission.ps1'
$testRelative = 'tests/test_run_muni_v34_windows_host_stability_admission.py'
$forensicReviewRelative = 'output/diagnostic-receipts/muni-fspsx-v33-terminal-gate-rejection-independent-review-20260830T002100Z.receipt.json'
$independentReviewRelative = "output/diagnostic-receipts/muni-fspsx-v34-windows-host-stability-$admissionId.independent-review.receipt.json"
$authorizationRelative = "output/diagnostic-receipts/muni-fspsx-v34-windows-host-stability-$admissionId.authorization.receipt.json"
$scriptPath = Join-Path $repo $scriptRelative.Replace('/', '\')
$testPath = Join-Path $repo $testRelative.Replace('/', '\')
$forensicReviewPath = Join-Path $repo $forensicReviewRelative.Replace('/', '\')
$independentReviewPath = Join-Path $repo $independentReviewRelative.Replace('/', '\')
$authorizationPath = Join-Path $repo $authorizationRelative.Replace('/', '\')
$forensicReviewSha256 = '131a4273ad86e98608e6e2f0335fca8363a7abe8232264ec6e05dc27430bec83'
$receiptPrefix = Join-Path $receiptDirectory "muni-fspsx-v34-windows-host-stability-$admissionId"
$authorityIntentPath = $receiptPrefix + '.authority-intent.json'
$intentPath = $receiptPrefix + '.intent.json'
$capturePath = $receiptPrefix + '.capture.json'
$receiptPendingPath = $receiptPrefix + '.receipt.pending.json'
$receiptPath = $receiptPrefix + '.receipt.json'
$rejectionPendingPath = $receiptPrefix + '.rejection.pending.json'
$rejectionPath = $receiptPrefix + '.rejection.json'
$lockEvidencePath = $receiptPrefix + '.serialization-lock.evidence.json'
$sharedLockPath = Join-Path $receiptDirectory 'planora-shared-heavy-wsl.lock'
$dockerVhdxPath = 'D:\Docker\wsl\disk\docker_data.vhdx'
$ubuntuVhdxPath = 'D:\WSL\Ubuntu\ext4.vhdx'
$finalRunnerPath = Join-Path $repo 'scripts\run_muni_v34_canonical_tests.ps1'
$finalGatePath = Join-Path $repo 'scripts\run_muni_v34_terminal_gate_once.ps1'
$canonicalRunPrefix = "muni-fspsx-v34-canonical-readonly-tests-$runId"
$canonicalAuthorizationPrefix = 'muni-fspsx-v34-canonical-tests-authorization-'
$sampleCount = 3
$sampleIntervalSeconds = 450
$minimumQuietWindowSeconds = 900
$continuousGuardPollMilliseconds = 2000
$maximumContinuousGuardGapMilliseconds = 15000
$terminalProcessStartDrainGraceMilliseconds = 5000
$minimumFreeSpaceBytes = [long](64GB)
$maximumFreeSpaceLossBytes = [long](1GB)
$requiredServiceNames = @('WslService', 'vmcompute', 'hns', 'HvHost')
$mutexName = 'Global\Planora.MuniV34.WindowsHostStability'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)

if ($null -eq ('PlanoraMuniV34AtomicFile' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class PlanoraMuniV34AtomicFile
{
    public sealed class Identity
    {
        public long Size;
        public string Sha256;
        public string FileId;
        public long LastWriteUtcTicks;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeFileTime
    {
        public uint Low;
        public uint High;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeFileInformation
    {
        public uint Attributes;
        public NativeFileTime CreationTime;
        public NativeFileTime LastAccessTime;
        public NativeFileTime LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoStatusBlock
    {
        public IntPtr Status;
        public UIntPtr Information;
    }

    private const uint GenericRead = 0x80000000;
    private const uint GenericWrite = 0x40000000;
    private const uint DeleteAccess = 0x00010000;
    private const uint ShareRead = 0x00000001;
    private const uint ShareWrite = 0x00000002;
    private const uint ShareDelete = 0x00000004;
    private const uint CreateNew = 1;
    private const uint OpenExisting = 3;
    private const uint FileTraverse = 0x00000020;
    private const uint FileReadAttributes = 0x00000080;
    private const uint FileAttributeDirectory = 0x00000010;
    private const uint FileAttributeNormal = 0x00000080;
    private const uint FileAttributeReparsePoint = 0x00000400;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileFlagWriteThrough = 0x80000000;
    private const int NativeFileRenameInformation = 10;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle file,
        out NativeFileInformation information
    );

    [DllImport("ntdll.dll")]
    private static extern int NtSetInformationFile(
        SafeFileHandle file,
        out IoStatusBlock ioStatusBlock,
        IntPtr information,
        uint bufferSize,
        int informationClass
    );

    [DllImport("ntdll.dll")]
    private static extern uint RtlNtStatusToDosError(int status);

    public static SafeFileHandle CreateExclusive(string path)
    {
        SafeFileHandle handle = CreateFileW(
            Path.GetFullPath(path),
            GenericRead | GenericWrite | DeleteAccess,
            ShareRead,
            IntPtr.Zero,
            CreateNew,
            FileAttributeNormal | FileFlagWriteThrough,
            IntPtr.Zero
        );
        if (handle.IsInvalid)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Exclusive atomic file creation failed: " + path);
        return handle;
    }

    public static FileStream OpenNonOwningReadWriteStream(SafeFileHandle handle)
    {
        if (handle == null || handle.IsInvalid || handle.IsClosed)
            throw new ObjectDisposedException("handle");
        SafeFileHandle borrowed = new SafeFileHandle(handle.DangerousGetHandle(), false);
        return new FileStream(borrowed, FileAccess.ReadWrite, 4096, false);
    }

    public static SafeFileHandle OpenDirectoryBinding(string path)
    {
        string fullPath = Path.GetFullPath(path);
        SafeFileHandle handle = CreateFileW(
            fullPath,
            FileTraverse | FileReadAttributes,
            ShareRead | ShareWrite,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero
        );
        if (handle.IsInvalid)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Directory binding open failed: " + fullPath);
        NativeFileInformation information;
        if (!GetFileInformationByHandle(handle, out information))
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "Directory binding identity query failed: " + fullPath);
        }
        if ((information.Attributes & FileAttributeDirectory) == 0 ||
            (information.Attributes & FileAttributeReparsePoint) != 0)
        {
            handle.Dispose();
            throw new InvalidOperationException("Directory binding rejected a non-directory or reparse point: " + fullPath);
        }
        return handle;
    }

    public static void RenameOpenHandle(SafeFileHandle handle, SafeFileHandle directory, string fileName)
    {
        if (handle == null || handle.IsInvalid || handle.IsClosed)
            throw new ObjectDisposedException("handle");
        if (directory == null || directory.IsInvalid || directory.IsClosed)
            throw new ObjectDisposedException("directory");
        if (String.IsNullOrWhiteSpace(fileName) || Path.IsPathRooted(fileName) ||
            !String.Equals(Path.GetFileName(fileName), fileName, StringComparison.Ordinal) ||
            fileName == "." || fileName == "..")
            throw new ArgumentException("Rename destination must be one leaf name", "fileName");
        byte[] fileNameBytes = Encoding.Unicode.GetBytes(fileName);
        int rootOffset = IntPtr.Size == 8 ? 8 : 4;
        int lengthOffset = IntPtr.Size == 8 ? 16 : 8;
        int nameOffset = IntPtr.Size == 8 ? 20 : 12;
        int structureSize = IntPtr.Size == 8 ? 24 : 16;
        int bufferLength = checked(structureSize + fileNameBytes.Length);
        IntPtr buffer = Marshal.AllocHGlobal(bufferLength);
        try
        {
            for (int index = 0; index < bufferLength; index++)
                Marshal.WriteByte(buffer, index, 0);
            Marshal.WriteByte(buffer, 0, 0);
            Marshal.WriteIntPtr(buffer, rootOffset, directory.DangerousGetHandle());
            Marshal.WriteInt32(buffer, lengthOffset, fileNameBytes.Length);
            Marshal.Copy(fileNameBytes, 0, IntPtr.Add(buffer, nameOffset), fileNameBytes.Length);
            IoStatusBlock ioStatusBlock;
            int status = NtSetInformationFile(
                handle,
                out ioStatusBlock,
                buffer,
                (uint)bufferLength,
                NativeFileRenameInformation
            );
            if (status < 0)
                throw new Win32Exception((int)RtlNtStatusToDosError(status), "Open-handle atomic relative rename failed: " + fileName);
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    public static Identity InspectOpenHandle(SafeFileHandle handle)
    {
        if (handle == null || handle.IsInvalid || handle.IsClosed)
            throw new ObjectDisposedException("handle");
        NativeFileInformation information;
        if (!GetFileInformationByHandle(handle, out information))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Open-handle identity query failed");
        string digest;
        SafeFileHandle borrowed = new SafeFileHandle(handle.DangerousGetHandle(), false);
        using (FileStream stream = new FileStream(borrowed, FileAccess.Read, 4096, false))
        using (SHA256 sha = SHA256.Create())
        {
            stream.Position = 0;
            digest = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
        long size = ((long)information.FileSizeHigh << 32) | information.FileSizeLow;
        long fileTime = ((long)information.LastWriteTime.High << 32) | information.LastWriteTime.Low;
        return new Identity {
            Size = size,
            Sha256 = digest,
            FileId = (information.FileIndexHigh.ToString("x8") + information.FileIndexLow.ToString("x8")).PadLeft(32, '0'),
            LastWriteUtcTicks = DateTime.FromFileTimeUtc(fileTime).Ticks
        };
    }

    public static Identity InspectNamedSharedDelete(string path)
    {
        SafeFileHandle handle = CreateFileW(
            Path.GetFullPath(path),
            GenericRead,
            ShareRead | ShareWrite | ShareDelete,
            IntPtr.Zero,
            OpenExisting,
            FileAttributeNormal,
            IntPtr.Zero
        );
        if (handle.IsInvalid)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Shared-delete identity open failed: " + path);
        using (handle)
        {
            NativeFileInformation information;
            if (!GetFileInformationByHandle(handle, out information))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Shared-delete identity query failed: " + path);
            string digest;
            using (FileStream stream = new FileStream(handle, FileAccess.Read, 4096, false))
            using (SHA256 sha = SHA256.Create())
                digest = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            long size = ((long)information.FileSizeHigh << 32) | information.FileSizeLow;
            long fileTime = ((long)information.LastWriteTime.High << 32) | information.LastWriteTime.Low;
            return new Identity {
                Size = size,
                Sha256 = digest,
                FileId = (information.FileIndexHigh.ToString("x8") + information.FileIndexLow.ToString("x8")).PadLeft(32, '0'),
                LastWriteUtcTicks = DateTime.FromFileTimeUtc(fileTime).Ticks
            };
        }
    }
}
'@
}

$selectedModeCount = 0
foreach ($selectedMode in @($StaticSelfTest, $InspectPreconditions, $Observe)) {
    if ([bool]$selectedMode) {
        $selectedModeCount++
    }
}
if ($selectedModeCount -ne 1) {
    throw 'Exactly one explicit host-stability mode is required'
}

function Get-BytesSha256([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Bytes)) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-Sha256([string]$Path) {
    $stream = New-Object IO.FileStream(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Get-StringSha256([string]$Value) {
    return Get-BytesSha256 $utf8.GetBytes($Value)
}

function ConvertTo-CanonicalJson([object]$Value, [int]$Depth = 40) {
    return ConvertTo-Json -InputObject $Value -Depth $Depth -Compress
}

function Assert-NoCaseAliasJsonKeys([object]$Value, [string]$Path = '$') {
    if ($null -eq $Value -or $Value -is [string] -or $Value -is [ValueType]) {
        return
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $seen = @{}
        foreach ($keyObject in $Value.Keys) {
            $key = [string]$keyObject
            $folded = $key.ToUpperInvariant()
            if ($seen.ContainsKey($folded)) {
                throw "Case-alias JSON key rejected at $Path"
            }
            $seen[$folded] = $true
            Assert-NoCaseAliasJsonKeys $Value[$keyObject] "$Path.$key"
        }
        return
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $index = 0
        foreach ($entry in $Value) {
            Assert-NoCaseAliasJsonKeys $entry "$Path[$index]"
            $index++
        }
        return
    }
    $seenProperties = @{}
    foreach ($property in $Value.PSObject.Properties) {
        $folded = $property.Name.ToUpperInvariant()
        if ($seenProperties.ContainsKey($folded)) {
            throw "Case-alias JSON property rejected at $Path"
        }
        $seenProperties[$folded] = $true
        Assert-NoCaseAliasJsonKeys $property.Value "$Path.$($property.Name)"
    }
}

function ConvertFrom-CanonicalJsonText([string]$Raw, [string]$Label) {
    if ([string]::IsNullOrEmpty($Raw)) {
        throw "$Label canonical JSON is empty"
    }
    try {
        $value = ConvertFrom-Json -InputObject $Raw
    }
    catch {
        throw "$Label strict JSON parse rejected: $($_.Exception.Message)"
    }
    Assert-NoCaseAliasJsonKeys $value
    $replayed = ConvertTo-CanonicalJson $value 60
    if ($replayed -cne $Raw) {
        throw "$Label canonical JSON replay rejected"
    }
    return $value
}

function Assert-JsonBooleanProperty([object]$Object, [string]$Name, [string]$Label) {
    $properties = @($Object.PSObject.Properties | Where-Object { $_.Name -ceq $Name })
    if ($properties.Count -ne 1 -or -not ($properties[0].Value -is [bool])) {
        throw "$Label JSON Boolean type rejected: $Name"
    }
}

function Assert-JsonArrayProperty([object]$Object, [string]$Name, [string]$Label) {
    $properties = @($Object.PSObject.Properties | Where-Object { $_.Name -ceq $Name })
    if ($properties.Count -ne 1 -or -not ($properties[0].Value -is [System.Array])) {
        throw "$Label JSON array type rejected: $Name"
    }
}

function Write-CreateOnlyUtf8Durable([string]$Path, [string]$Text) {
    $bytes = $utf8.GetBytes($Text)
    $stream = New-Object IO.FileStream(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read,
        4096,
        [IO.FileOptions]::WriteThrough
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Publish-CanonicalTerminal([string]$PendingPath, [string]$FinalPath, [string]$Json, [string]$Label) {
    $bytes = $utf8.GetBytes($Json)
    $pendingParent = [IO.Path]::GetFullPath((Split-Path -Parent $PendingPath))
    $finalParent = [IO.Path]::GetFullPath((Split-Path -Parent $FinalPath))
    if (-not [string]::Equals($pendingParent, $finalParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label pending and final directories differ"
    }
    $finalLeaf = [IO.Path]::GetFileName($FinalPath)
    if ([string]::IsNullOrWhiteSpace($finalLeaf)) { throw "$Label final leaf name is missing" }
    $directoryHandle = $null
    $nativeHandle = $null
    $stream = $null
    try {
        $directoryHandle = [PlanoraMuniV34AtomicFile]::OpenDirectoryBinding($finalParent)
        $nativeHandle = [PlanoraMuniV34AtomicFile]::CreateExclusive($PendingPath)
        $stream = [PlanoraMuniV34AtomicFile]::OpenNonOwningReadWriteStream($nativeHandle)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        Assert-HeldCanonicalReplay $stream $Json "$Label pending"
        $pendingIdentity = Get-HeldPhysicalEvidenceIdentity $nativeHandle
        $namedPendingIdentity = Get-PhysicalEvidenceIdentitySharedDelete $PendingPath
        Assert-SamePhysicalPin $pendingIdentity $namedPendingIdentity "$Label pending path binding"
        $publication = [ordered]@{
            status = 'ATOMIC_CREATE_WRITE_FLUSH_REPLAY_NO_REPLACE_RENAME_COMMIT'
            committed_identity = $pendingIdentity; destination_directory_bound = $true
            destination_reparse_point_rejected = $true
        }
        $stream.Dispose()
        $stream = $null
        [PlanoraMuniV34AtomicFile]::RenameOpenHandle($nativeHandle, $directoryHandle, $finalLeaf)
        return $publication
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $nativeHandle) { $nativeHandle.Dispose() }
        if ($null -ne $directoryHandle) { $directoryHandle.Dispose() }
    }
}

function Get-FileId([string]$Path) {
    $rows = @(& 'C:\Windows\System32\fsutil.exe' file queryfileid $Path 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "File ID query failed: $Path"
    }
    $match = [regex]::Match(($rows -join "`n"), 'File ID is 0x([0-9a-fA-F]{32})')
    if (-not $match.Success) {
        throw "File ID parse failed: $Path"
    }
    return $match.Groups[1].Value.ToLowerInvariant()
}

function Get-LocalEvidencePin([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    $repoPrefix = $repo.TrimEnd('\') + '\'
    if (-not $item.FullName.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Evidence path is outside the frozen repository root: $Path"
    }
    return [ordered]@{
        path                 = $item.FullName.Substring($repoPrefix.Length).Replace('\', '/')
        size                 = [long]$item.Length
        sha256               = Get-Sha256 $item.FullName
        file_id              = Get-FileId $item.FullName
        last_write_utc_ticks = [long]$item.LastWriteTimeUtc.Ticks
    }
}

function Get-LocalEvidencePinSharedDelete([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    $repoPrefix = $repo.TrimEnd('\') + '\'
    if (-not $item.FullName.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Evidence path is outside the frozen repository root: $Path"
    }
    $identity = [PlanoraMuniV34AtomicFile]::InspectNamedSharedDelete($item.FullName)
    return [ordered]@{
        path = $item.FullName.Substring($repoPrefix.Length).Replace('\', '/')
        size = [long]$identity.Size; sha256 = [string]$identity.Sha256
        file_id = [string]$identity.FileId; last_write_utc_ticks = [long]$identity.LastWriteUtcTicks
    }
}

function Get-PhysicalEvidenceIdentity([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    return [ordered]@{
        size                 = [long]$item.Length
        sha256               = Get-Sha256 $item.FullName
        file_id              = Get-FileId $item.FullName
        last_write_utc_ticks = [long]$item.LastWriteTimeUtc.Ticks
    }
}

function Get-PhysicalEvidenceIdentitySharedDelete([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    $identity = [PlanoraMuniV34AtomicFile]::InspectNamedSharedDelete($item.FullName)
    return [ordered]@{
        size = [long]$identity.Size; sha256 = [string]$identity.Sha256
        file_id = [string]$identity.FileId; last_write_utc_ticks = [long]$identity.LastWriteUtcTicks
    }
}

function Get-HeldPhysicalEvidenceIdentity([Microsoft.Win32.SafeHandles.SafeFileHandle]$Handle) {
    $identity = [PlanoraMuniV34AtomicFile]::InspectOpenHandle($Handle)
    return [ordered]@{
        size = [long]$identity.Size; sha256 = [string]$identity.Sha256
        file_id = [string]$identity.FileId; last_write_utc_ticks = [long]$identity.LastWriteUtcTicks
    }
}

function Assert-ExactPin([object]$Expected, [object]$Actual, [string]$Label) {
    foreach ($field in @('path', 'size', 'sha256', 'file_id', 'last_write_utc_ticks')) {
        if ($Expected.$field -cne $Actual.$field) {
            throw "$Label exact pin mismatch: $field"
        }
    }
}

function Assert-SamePhysicalPin([object]$Expected, [object]$Actual, [string]$Label) {
    foreach ($field in @('size', 'sha256', 'file_id', 'last_write_utc_ticks')) {
        if ($Expected.$field -cne $Actual.$field) {
            throw "$Label physical pin mismatch: $field"
        }
    }
}

function Open-ReadEvidenceGuard([string]$Path) {
    return New-Object IO.FileStream(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
}

function Read-HeldUtf8([IO.FileStream]$Stream, [string]$Label) {
    if ($Stream.Length -gt [int]::MaxValue) {
        throw "$Label exceeds the held-handle read bound"
    }
    $bytes = New-Object byte[] ([int]$Stream.Length)
    $Stream.Position = 0
    $offset = 0
    while ($offset -lt $bytes.Length) {
        $read = $Stream.Read($bytes, $offset, $bytes.Length - $offset)
        if ($read -le 0) {
            throw "$Label held-handle read ended early"
        }
        $offset += $read
    }
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        throw "$Label UTF-8 BOM rejected"
    }
    try {
        return $strictUtf8.GetString($bytes)
    }
    catch {
        throw "$Label strict UTF-8 decode rejected"
    }
}

function Assert-HeldCanonicalReplay([IO.FileStream]$Stream, [string]$ExpectedRaw, [string]$Label) {
    $heldRaw = Read-HeldUtf8 $Stream $Label
    if ($heldRaw -cne $ExpectedRaw) {
        throw "$Label held-handle replay mismatch"
    }
    [void](ConvertFrom-CanonicalJsonText $heldRaw $Label)
}

function Close-EvidenceGuards([object[]]$Streams) {
    foreach ($stream in @($Streams)) {
        if ($null -ne $stream) {
            try {
                $stream.Dispose()
            }
            catch {
            }
        }
    }
}

function Get-GuardedAuthorizationState([string]$Mode) {
    $paths = @($scriptPath, $testPath, $forensicReviewPath, $independentReviewPath, $authorizationPath)
    $streams = @()
    try {
        foreach ($path in $paths) {
            $streams += , (Open-ReadEvidenceGuard $path)
        }
        $pins = [ordered]@{
            script             = Get-LocalEvidencePin $scriptPath
            tests              = Get-LocalEvidencePin $testPath
            forensic_review    = Get-LocalEvidencePin $forensicReviewPath
            independent_review = Get-LocalEvidencePin $independentReviewPath
            authorization      = Get-LocalEvidencePin $authorizationPath
        }
        if ($pins.forensic_review.sha256 -cne $forensicReviewSha256) {
            throw 'Frozen v33 host-forensic review hash mismatch'
        }
        $invokedIdentity = Get-PhysicalEvidenceIdentity $PSCommandPath
        foreach ($field in @('size', 'sha256', 'file_id', 'last_write_utc_ticks')) {
            if ($invokedIdentity.$field -cne $pins.script.$field) {
                throw "Invoked host-stability script identity mismatch: $field"
            }
        }
        $reviewRaw = Read-HeldUtf8 $streams[3] 'Independent review'
        $authorizationRaw = Read-HeldUtf8 $streams[4] 'Observation authorization'
        $review = ConvertFrom-CanonicalJsonText $reviewRaw 'Independent review'
        $authorization = ConvertFrom-CanonicalJsonText $authorizationRaw 'Observation authorization'
        Assert-JsonArrayProperty $review 'blockers' 'Independent review'
        foreach ($name in @('live_mode_executed', 'wsl_executed', 'docker_or_service_action_performed',
                'artifact_publication_performed')) {
            Assert-JsonBooleanProperty $review.review_scope $name 'Independent review scope'
        }
        Assert-JsonArrayProperty $authorization 'authorized_modes' 'Observation authorization'
        foreach ($name in @('one_shot_authority', 'automatic_retry_authorized', 'wsl_authorized',
                'docker_or_service_action_authorized', 'vhdx_attribute_change_authorized',
                'canonical_execution_authorized')) {
            Assert-JsonBooleanProperty $authorization $name 'Observation authorization'
        }
        if (
            $review.schema -cne 'planora.muni-v34.windows-host-stability-independent-review.v1' -or
            $review.status -cne 'GO_FOR_EXACT_WINDOWS_HOST_STABILITY_OBSERVATION' -or
            $review.admission_id -cne $admissionId -or
            @($review.blockers).Count -ne 0 -or
            [bool]$review.review_scope.live_mode_executed -or
            [bool]$review.review_scope.wsl_executed -or
            [bool]$review.review_scope.docker_or_service_action_performed -or
            [bool]$review.review_scope.artifact_publication_performed
        ) {
            throw 'Independent host-stability review semantics rejected'
        }
        Assert-ExactPin $review.sources.script $pins.script 'Independent review script'
        Assert-ExactPin $review.sources.tests $pins.tests 'Independent review tests'
        Assert-ExactPin $authorization.sources.script $pins.script 'Authorization script'
        Assert-ExactPin $authorization.sources.tests $pins.tests 'Authorization tests'
        Assert-ExactPin $authorization.sources.forensic_review $pins.forensic_review 'Authorization forensic review'
        Assert-ExactPin $authorization.sources.independent_review $pins.independent_review 'Authorization independent review'
        $authorizedModes = @($authorization.authorized_modes)
        if (
            $authorization.schema -cne 'planora.muni-v34.windows-host-stability-authorization.v1' -or
            $authorization.status -cne 'GO_FOR_EXACTLY_ONE_WINDOWS_HOST_STABILITY_AUTHORITY' -or
            $authorization.admission_id -cne $admissionId -or
            $authorizedModes.Count -ne 1 -or
            $authorizedModes[0] -cne $Mode -or
            -not [bool]$authorization.one_shot_authority -or
            [bool]$authorization.automatic_retry_authorized -or
            [bool]$authorization.wsl_authorized -or
            [bool]$authorization.docker_or_service_action_authorized -or
            [bool]$authorization.vhdx_attribute_change_authorized -or
            [bool]$authorization.canonical_execution_authorized
        ) {
            throw 'Host-stability authorization semantics rejected'
        }
        return [pscustomobject]@{ streams = $streams; pins = $pins; review = $review; authorization = $authorization }
    }
    catch {
        Close-EvidenceGuards $streams
        throw
    }
}

function Get-PathObservation([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    return [ordered]@{
        path = $Path; size = [long]$item.Length; file_id = Get-FileId $Path
        creation_utc_ticks = [long]$item.CreationTimeUtc.Ticks; last_write_utc_ticks = [long]$item.LastWriteTimeUtc.Ticks
        attributes = [string]$item.Attributes; compressed = [bool]($item.Attributes -band [IO.FileAttributes]::Compressed)
        encrypted = [bool]($item.Attributes -band [IO.FileAttributes]::Encrypted)
        sparse = [bool]($item.Attributes -band [IO.FileAttributes]::SparseFile)
    }
}

function Get-DirectoryObservation([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    return [ordered]@{
        path = $Path; file_id = Get-FileId $Path; creation_utc_ticks = [long]$item.CreationTimeUtc.Ticks
        last_write_utc_ticks = [long]$item.LastWriteTimeUtc.Ticks; attributes = [string]$item.Attributes
        compressed = [bool]($item.Attributes -band [IO.FileAttributes]::Compressed)
        encrypted = [bool]($item.Attributes -band [IO.FileAttributes]::Encrypted)
        reparse_point = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    }
}

function Get-RepositoryNamespaceObservation {
    return [ordered]@{
        repository = Get-DirectoryObservation $repo
        receipt_directory = Get-DirectoryObservation $receiptDirectory
    }
}

function Assert-RepositoryNamespaceIdentity([object]$Expected) {
    $current = Get-RepositoryNamespaceObservation
    foreach ($name in @('repository', 'receipt_directory')) {
        foreach ($field in @('path', 'file_id', 'creation_utc_ticks', 'attributes', 'compressed', 'encrypted', 'reparse_point')) {
            if ($current.$name.$field -cne $Expected.$name.$field) {
                throw "Repository namespace identity drift: $name.$field"
            }
        }
    }
    Assert-RepositoryNamespaceObservationAdmissible $current
    return $current
}

function Assert-RepositoryNamespaceObservationAdmissible([object]$Namespace) {
    foreach ($name in @('repository', 'receipt_directory')) {
        if ([bool]$Namespace.$name.reparse_point) {
            throw "Repository namespace reparse point rejected: $name"
        }
    }
}

function Get-VolumeObservation {
    $volume = Get-Volume -DriveLetter D -ErrorAction Stop
    $partition = Get-Partition -DriveLetter D -ErrorAction Stop
    return [ordered]@{
        drive_letter = 'D'; file_system = [string]$volume.FileSystem; health_status = [string]$volume.HealthStatus
        operational_status = (@($volume.OperationalStatus | ForEach-Object { [string]$_ }) -join ',')
        size_bytes = [long]$volume.Size; size_remaining_bytes = [long]$volume.SizeRemaining
        partition_number = [int]$partition.PartitionNumber; partition_guid = [string]$partition.Guid
        is_offline = [bool]$partition.IsOffline; is_read_only = [bool]$partition.IsReadOnly
    }
}

function Get-ServiceObservation {
    $rows = @()
    foreach ($name in $requiredServiceNames) {
        $service = Get-CimInstance Win32_Service -Filter "Name='$name'" -ErrorAction Stop
        if ($null -eq $service) {
            $rows += , [ordered]@{ name = $name; present = $false; state = 'MISSING'; start_mode = 'MISSING'; process_id = 0 }
        }
        else {
            $rows += , [ordered]@{
                name = $name; present = $true; state = [string]$service.State
                start_mode = [string]$service.StartMode; process_id = [int]$service.ProcessId
            }
        }
    }
    return $rows
}

function Get-DockerProcessObservation {
    $rows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $byPid = @{}
    foreach ($row in $rows) { $byPid[[int]$row.ProcessId] = $row }
    $dockerRoots = @($rows | Where-Object {
        ([string]$_.Name) -match '(?i)docker|com\.docker|dockerd' -or
        ([string]$_.ExecutablePath) -match '(?i)docker|com\.docker' -or
        ([string]$_.CommandLine) -match '(?i)docker-desktop|docker_data\.vhdx|com\.docker'
    })
    $rootIds = @($dockerRoots | ForEach-Object { [int]$_.ProcessId })
    $matches = @()
    foreach ($row in $rows) {
        $pidValue = [int]$row.ProcessId
        $cursor = $pidValue
        $belongs = $rootIds -ccontains $pidValue
        for ($depth = 0; $depth -lt 64 -and -not $belongs; $depth++) {
            if (-not $byPid.ContainsKey($cursor)) { break }
            $parent = [int]$byPid[$cursor].ParentProcessId
            if ($rootIds -ccontains $parent) { $belongs = $true; break }
            if ($parent -le 0 -or $parent -eq $cursor) { break }
            $cursor = $parent
        }
        if ($belongs) {
            $command = [string]$row.CommandLine
            $matches += , [ordered]@{
                pid = $pidValue; parent_pid = [int]$row.ParentProcessId; name = [string]$row.Name
                executable = [string]$row.ExecutablePath; command_line_sha256 = Get-StringSha256 $command
            }
        }
    }
    $wslWorkloads = @($rows | Where-Object {
        ([string]$_.Name) -match '(?i)^(wsl|wslhost|wslrelay|vmmem|vmmemwsl)(?:\.exe)?$'
    } | ForEach-Object {
        $command = [string]$_.CommandLine
        [ordered]@{
            pid = [int]$_.ProcessId; parent_pid = [int]$_.ParentProcessId; name = [string]$_.Name
            executable = [string]$_.ExecutablePath; command_line_sha256 = Get-StringSha256 $command
        }
    })
    $dockerService = Get-CimInstance Win32_Service -Filter "Name='com.docker.service'" -ErrorAction Stop
    return [ordered]@{
        matching_processes = $matches; matching_process_count = $matches.Count
        wsl_workload_processes = $wslWorkloads; wsl_workload_process_count = $wslWorkloads.Count
        docker_service_present = $null -ne $dockerService
        docker_service_state = if ($null -eq $dockerService) { 'MISSING' } else { [string]$dockerService.State }
        docker_service_process_id = if ($null -eq $dockerService) { 0 } else { [int]$dockerService.ProcessId }
    }
}

function Start-ProcessStartMonitor {
    $sourceIdentifier = "Planora.MuniV34.WindowsOnlyProcessStart.$admissionId.$PID"
    $subscription = Register-CimIndicationEvent -Namespace 'root/cimv2' -Query (
        'SELECT * FROM Win32_ProcessStartTrace'
    ) -SourceIdentifier $sourceIdentifier
    return [pscustomobject]@{
        source_identifier = $sourceIdentifier
        subscription      = $subscription
    }
}

function Read-ProcessStartMonitor([object]$Monitor) {
    $subscribers = @(Get-EventSubscriber -SourceIdentifier $Monitor.source_identifier -ErrorAction SilentlyContinue)
    $jobState = if ($null -eq $Monitor.subscription) { 'MISSING' } else { [string]$Monitor.subscription.State }
    $events = @(Get-Event -SourceIdentifier $Monitor.source_identifier -ErrorAction SilentlyContinue)
    $rows = @()
    foreach ($event in $events) {
        $newEvent = $event.SourceEventArgs.NewEvent
        $name = [string]$newEvent.ProcessName
        $rows += , [ordered]@{
            process_name = $name
            process_id   = [int]$newEvent.ProcessID
            suspicious   = $name -match '(?i)docker|dockerd|com\.docker|wsl|wslhost|vmmem'
        }
        Remove-Event -EventIdentifier $event.EventIdentifier -ErrorAction SilentlyContinue
    }
    return [ordered]@{
        subscriber_count = $subscribers.Count
        subscription_job_state = $jobState
        event_count      = $rows.Count
        suspicious_count = @($rows | Where-Object { [bool]$_.suspicious }).Count
        events           = $rows
    }
}

function Assert-ProcessStartMonitorHealthy([object]$Observation) {
    if ([int]$Observation.subscriber_count -ne 1 -or
        @('NotStarted', 'Running') -cnotcontains [string]$Observation.subscription_job_state) {
        throw 'Process-start monitor subscription or job liveness rejected'
    }
}

function Stop-ProcessStartMonitor([object]$Monitor) {
    if ($null -eq $Monitor) {
        return
    }
    Unregister-Event -SourceIdentifier $Monitor.source_identifier -ErrorAction SilentlyContinue
    Get-Event -SourceIdentifier $Monitor.source_identifier -ErrorAction SilentlyContinue |
        Remove-Event -ErrorAction SilentlyContinue
    if ($null -ne $Monitor.subscription) {
        Remove-Job -Job $Monitor.subscription -Force -ErrorAction SilentlyContinue
    }
}

function Get-LatestEventObservation([string]$LogName, [string]$ProviderName, [int]$Id) {
    try {
        $event = Get-WinEvent -FilterHashtable @{ LogName = $LogName; ProviderName = $ProviderName; Id = $Id } -MaxEvents 1 -ErrorAction Stop
    }
    catch {
        if ($_.FullyQualifiedErrorId -match 'NoMatchingEventsFound') {
            return [ordered]@{
                present = $false; log_name = $LogName; record_id = 0; time_created_utc = $null
                provider = $ProviderName; event_id = $Id
            }
        }
        throw
    }
    return [ordered]@{
        present = $true; log_name = $LogName; record_id = [long]$event.RecordId
        time_created_utc = $event.TimeCreated.ToUniversalTime().ToString('o')
        provider = [string]$event.ProviderName; event_id = [int]$event.Id
    }
}

function Get-NewStorageWarnings([DateTime]$StartUtc) {
    try {
        $events = @(Get-WinEvent -FilterHashtable @{
            LogName = 'System'; Level = @(1, 2, 3); StartTime = $StartUtc.ToLocalTime()
        } -ErrorAction Stop | Where-Object {
            $_.ProviderName -match '(?i)disk|ntfs|storahci|stornvme|volmgr|volsnap'
        })
    }
    catch {
        if ($_.FullyQualifiedErrorId -match 'NoMatchingEventsFound') { $events = @() } else { throw }
    }
    return @($events | ForEach-Object {
        [ordered]@{
            record_id = [long]$_.RecordId; event_id = [int]$_.Id; provider = [string]$_.ProviderName
            time_created_utc = $_.TimeCreated.ToUniversalTime().ToString('o')
        }
    })
}

function Get-CanonicalArtifactObservation {
    $runArtifacts = @(Get-ChildItem -LiteralPath $receiptDirectory -File -Filter "$canonicalRunPrefix*" -ErrorAction Stop |
        Sort-Object Name | ForEach-Object { $_.Name })
    $authorizationArtifacts = @(Get-ChildItem -LiteralPath $receiptDirectory -File -Filter "$canonicalAuthorizationPrefix*" -ErrorAction Stop |
        Sort-Object Name | ForEach-Object { $_.Name })
    return [ordered]@{
        run_artifacts = $runArtifacts; run_artifact_count = $runArtifacts.Count
        authorization_artifacts = $authorizationArtifacts; authorization_artifact_count = $authorizationArtifacts.Count
        final_runner_present = Test-Path -LiteralPath $finalRunnerPath
        final_gate_present = Test-Path -LiteralPath $finalGatePath
    }
}

function Get-SharedLockObservation([object]$OwnedLock) {
    if ($null -eq $OwnedLock) {
        return [ordered]@{ present = Test-Path -LiteralPath $sharedLockPath; owned = $false; pin = $null }
    }
    $livePin = Get-LocalEvidencePinSharedDelete $sharedLockPath
    Assert-ExactPin $OwnedLock.pin $livePin 'Admission-owned shared lock'
    return [ordered]@{ present = $true; owned = $true; pin = $livePin }
}

function Get-LiveSample([int]$Index, [long]$ElapsedMilliseconds, [DateTime]$StartUtc, [object]$OwnedLock,
    [object]$ExpectedNamespace) {
    return [ordered]@{
        index = $Index; observed_at_utc = [DateTime]::UtcNow.ToString('o'); elapsed_milliseconds = $ElapsedMilliseconds
        repository_namespace = Assert-RepositoryNamespaceIdentity $ExpectedNamespace
        shared_lock = Get-SharedLockObservation $OwnedLock; canonical_artifacts = Get-CanonicalArtifactObservation
        docker = Get-DockerProcessObservation; services = Get-ServiceObservation
        docker_vhdx = Get-PathObservation $dockerVhdxPath
        docker_vhdx_parent = Get-DirectoryObservation (Split-Path -Parent $dockerVhdxPath)
        ubuntu_vhdx = Get-PathObservation $ubuntuVhdxPath
        ubuntu_vhdx_parent = Get-DirectoryObservation (Split-Path -Parent $ubuntuVhdxPath)
        volume = Get-VolumeObservation; ntfs_141 = Get-LatestEventObservation 'System' 'Ntfs' 141
        application_popup_26 = Get-LatestEventObservation 'System' 'Application Popup' 26
        new_storage_warnings = Get-NewStorageWarnings $StartUtc
    }
}

function Assert-DockerInactive([object]$Docker) {
    if ([int]$Docker.matching_process_count -ne 0) { throw 'Docker-owned process present' }
    if ([int]$Docker.wsl_workload_process_count -ne 0) { throw 'Pre-existing WSL workload process present' }
    if ([bool]$Docker.docker_service_present -and $Docker.docker_service_state -cne 'Stopped') { throw 'Docker service is active' }
}

function Assert-RequiredServicesRunning([object[]]$Services) {
    if ($Services.Count -ne $requiredServiceNames.Count) { throw 'Required WSL service cardinality rejected' }
    foreach ($name in $requiredServiceNames) {
        $matches = @($Services | Where-Object { $_.name -ceq $name })
        if ($matches.Count -ne 1 -or -not [bool]$matches[0].present -or $matches[0].state -cne 'Running' -or [int]$matches[0].process_id -le 0) {
            throw "Required WSL service is not running with a process identity: $name"
        }
    }
}

function Assert-CanonicalNamespaceEmpty([object]$Artifacts) {
    if ([int]$Artifacts.run_artifact_count -ne 0 -or [int]$Artifacts.authorization_artifact_count -ne 0 -or
        [bool]$Artifacts.final_runner_present -or [bool]$Artifacts.final_gate_present) {
        throw 'Final v34 canonical namespace is not empty'
    }
}

function Assert-VolumeAdmissible([object]$Volume) {
    if ($Volume.file_system -cne 'NTFS' -or $Volume.health_status -cne 'Healthy' -or $Volume.operational_status -cne 'OK' -or
        [bool]$Volume.is_offline -or [bool]$Volume.is_read_only -or [long]$Volume.size_remaining_bytes -lt $minimumFreeSpaceBytes) {
        throw 'D volume health, status, write state, or free-space floor rejected'
    }
}

function Assert-SingleSampleAdmissible([object]$Sample, [object]$Baseline, [bool]$RequireOwnedLock) {
    if ($RequireOwnedLock) {
        if (-not [bool]$Sample.shared_lock.present -or -not [bool]$Sample.shared_lock.owned) {
            throw 'Admission-owned shared serialization lock is missing'
        }
    }
    elseif ([bool]$Sample.shared_lock.present) { throw 'Competing shared heavy WSL lock is present' }
    Assert-RepositoryNamespaceObservationAdmissible $Sample.repository_namespace
    Assert-CanonicalNamespaceEmpty $Sample.canonical_artifacts
    Assert-DockerInactive $Sample.docker
    Assert-RequiredServicesRunning @($Sample.services)
    Assert-VolumeAdmissible $Sample.volume
    if ([long]$Sample.ntfs_141.record_id -ne [long]$Baseline.ntfs_141.record_id -or
        [long]$Sample.application_popup_26.record_id -ne [long]$Baseline.application_popup_26.record_id -or
        @($Sample.new_storage_warnings).Count -ne 0) { throw 'New storage warning event observed' }
    foreach ($vhdx in @($Sample.docker_vhdx, $Sample.ubuntu_vhdx)) {
        if ([bool]$vhdx.encrypted -or [bool]$vhdx.sparse) { throw 'Encrypted or sparse VHDX attribute rejected' }
    }
}

function Assert-HostStabilitySamples([object[]]$Samples, [object]$Baseline, [bool]$RequireOwnedLock) {
    if ($Samples.Count -ne $sampleCount) { throw 'Windows host sample cardinality rejected' }
    for ($index = 0; $index -lt $sampleCount; $index++) {
        if ([int]$Samples[$index].index -ne ($index + 1)) { throw 'Windows host sample sequence rejected' }
    }
    $firstElapsed = [long]$Samples[0].elapsed_milliseconds
    $secondElapsed = [long]$Samples[1].elapsed_milliseconds
    $thirdElapsed = [long]$Samples[2].elapsed_milliseconds
    if ($firstElapsed -gt 5000 -or ($secondElapsed - $firstElapsed) -lt ($sampleIntervalSeconds * 1000) -or
        ($thirdElapsed - $secondElapsed) -lt ($sampleIntervalSeconds * 1000) -or
        ($thirdElapsed - $firstElapsed) -lt ($minimumQuietWindowSeconds * 1000)) {
        throw 'Windows host quiet-window timing rejected'
    }
    foreach ($sample in $Samples) { Assert-SingleSampleAdmissible $sample $Baseline $RequireOwnedLock }
    foreach ($property in @('repository_namespace', 'docker', 'services', 'docker_vhdx', 'docker_vhdx_parent',
            'ubuntu_vhdx', 'ubuntu_vhdx_parent')) {
        $expected = ConvertTo-CanonicalJson $Samples[0].$property
        if ((ConvertTo-CanonicalJson $Samples[1].$property) -cne $expected -or
            (ConvertTo-CanonicalJson $Samples[2].$property) -cne $expected) {
            throw "Windows host identity drift: $property"
        }
    }
    $volumeIdentity = @('drive_letter', 'file_system', 'health_status', 'operational_status', 'size_bytes',
        'partition_number', 'partition_guid', 'is_offline', 'is_read_only')
    foreach ($property in $volumeIdentity) {
        if ($Samples[1].volume.$property -cne $Samples[0].volume.$property -or
            $Samples[2].volume.$property -cne $Samples[0].volume.$property) {
            throw "D volume identity drift: $property"
        }
    }
    $maximumObservedFreeSpaceLoss = [long]0
    foreach ($sample in @($Samples | Select-Object -Skip 1)) {
        $freeSpaceLoss = [long]$Samples[0].volume.size_remaining_bytes - [long]$sample.volume.size_remaining_bytes
        $maximumObservedFreeSpaceLoss = [Math]::Max($maximumObservedFreeSpaceLoss, $freeSpaceLoss)
        if ($freeSpaceLoss -gt $maximumFreeSpaceLossBytes) { throw 'D volume material free-space loss rejected' }
    }
    return [ordered]@{
        status = 'PASS_WINDOWS_QUIET_WINDOW_ONLY_NOT_FULL_HOST_READINESS'; samples = $sampleCount
        minimum_separation_seconds = $sampleIntervalSeconds; quiet_window_seconds = $minimumQuietWindowSeconds
        no_new_ntfs_141 = $true; no_new_application_popup_26 = $true; no_new_storage_warnings = $true
        docker_owned_processes_absent = $true; docker_service_inactive = $true
        required_services_running_stable = $true; vhdx_identity_and_attributes_stable = $true
        volume_stable_healthy_online_writable = $true; admission_owned_serialization_lock = $RequireOwnedLock
        maximum_observed_free_space_loss_bytes = $maximumObservedFreeSpaceLoss
        compressed_vhdx_blocker_cleared = $false; ubuntu_readiness_authorized = $false
    }
}

function New-SharedAdmissionLock([object]$AuthorizationPins, [ref]$PartialState) {
    $PartialState.Value = [ordered]@{
        acquisition_attempted = $true; native_owner_acquired = $false
        acquisition_completed = $false; owned_partial_retained = $false
        owned_handle_identity = $null; source_matches_owned_handle = $false
        source_pin = $null; source_observation_error = $null
        archive_conflict_present = $false; archive_conflict_pin = $null
        archive_conflict_observation_error = $null
    }
    if (Test-Path -LiteralPath $sharedLockPath) { throw 'Shared heavy WSL lock already exists' }
    $lock = [ordered]@{
        schema = 'planora.muni-v34.windows-host-stability-serialization-lock.v1'
        status = 'HELD_FOR_WINDOWS_ONLY_QUIET_WINDOW'; admission_id = $admissionId; pid = $PID
        authorization = $AuthorizationPins.authorization; wsl_authorized = $false
        docker_action_authorized = $false; canonical_execution_authorized = $false
        automatic_retry_authorized = $false; created_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    $json = ConvertTo-CanonicalJson $lock 12
    $bytes = $utf8.GetBytes($json)
    $directoryHandle = $null
    $nativeHandle = $null
    $stream = $null
    try {
        $directoryHandle = [PlanoraMuniV34AtomicFile]::OpenDirectoryBinding($receiptDirectory)
        $nativeHandle = [PlanoraMuniV34AtomicFile]::CreateExclusive($sharedLockPath)
        $PartialState.Value.native_owner_acquired = $true
        $stream = New-Object IO.FileStream($nativeHandle, [IO.FileAccess]::ReadWrite, 4096, $false)
        $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true); $stream.Position = 0
        $replay = New-Object byte[] $bytes.Length
        $offset = 0
        while ($offset -lt $replay.Length) {
            $read = $stream.Read($replay, $offset, $replay.Length - $offset)
            if ($read -le 0) { throw 'Shared lock same-handle replay ended early' }
            $offset += $read
        }
        if ((Get-BytesSha256 $replay) -cne (Get-BytesSha256 $bytes)) { throw 'Shared lock same-handle replay hash mismatch' }
        $heldIdentity = Get-HeldPhysicalEvidenceIdentity $nativeHandle
        $pin = Get-LocalEvidencePinSharedDelete $sharedLockPath
        Assert-SamePhysicalPin $heldIdentity $pin 'Shared lock source path binding'
        if ($pin.size -ne $bytes.Length -or $pin.sha256 -cne (Get-BytesSha256 $bytes)) {
            throw 'Shared lock path identity rejected after same-handle replay'
        }
        $PartialState.Value.acquisition_completed = $true
        $PartialState.Value.owned_handle_identity = $heldIdentity
        $PartialState.Value.source_matches_owned_handle = $true
        $PartialState.Value.source_pin = $pin
        return [pscustomobject]@{
            stream = $stream; native_handle = $nativeHandle; directory_handle = $directoryHandle
            pin = $pin; record = $lock; archived = $false
        }
    }
    catch {
        $failure = $_.Exception.Message
        if ($null -ne $nativeHandle -and -not $nativeHandle.IsInvalid -and -not $nativeHandle.IsClosed) {
            $PartialState.Value.owned_partial_retained = $true
            try {
                $PartialState.Value.owned_handle_identity = Get-HeldPhysicalEvidenceIdentity $nativeHandle
            }
            catch {
                $PartialState.Value.source_observation_error = 'owned_handle_identity=' + $_.Exception.Message
            }
            try {
                $PartialState.Value.source_pin = Get-LocalEvidencePinSharedDelete $sharedLockPath
                if ($null -ne $PartialState.Value.owned_handle_identity) {
                    Assert-SamePhysicalPin $PartialState.Value.owned_handle_identity $PartialState.Value.source_pin 'Partial shared lock source binding'
                    $PartialState.Value.source_matches_owned_handle = $true
                }
            }
            catch {
                $sourceFailure = $_.Exception.Message
                if ($null -ne $PartialState.Value.source_observation_error) {
                    $sourceFailure = $PartialState.Value.source_observation_error + '; source_path=' + $sourceFailure
                }
                $PartialState.Value.source_observation_error = $sourceFailure
            }
            $PartialState.Value.archive_conflict_present = Test-Path -LiteralPath $lockEvidencePath
            if ($PartialState.Value.archive_conflict_present) {
                try {
                    $PartialState.Value.archive_conflict_pin = Get-LocalEvidencePinSharedDelete $lockEvidencePath
                }
                catch {
                    $PartialState.Value.archive_conflict_observation_error = $_.Exception.Message
                }
            }
            $failure += '; owned_partial_shared_lock_retained_for_authenticated_reconciliation'
        }
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $nativeHandle) { $nativeHandle.Dispose() }
        if ($null -ne $directoryHandle) { $directoryHandle.Dispose() }
        throw $failure
    }
}

function Release-SharedAdmissionLock([object]$OwnedLock) {
    if ($null -eq $OwnedLock) {
        return [ordered]@{ owned = $false; released = $false; absent = -not (Test-Path -LiteralPath $sharedLockPath) }
    }
    if ([bool]$OwnedLock.archived) {
        $archivePin = Get-LocalEvidencePinSharedDelete $lockEvidencePath
        Assert-SamePhysicalPin $OwnedLock.pin $archivePin 'Previously archived shared lock evidence'
        if ($null -ne $OwnedLock.stream) { $OwnedLock.stream.Dispose() }
        if ($null -ne $OwnedLock.native_handle) { $OwnedLock.native_handle.Dispose() }
        if ($null -ne $OwnedLock.directory_handle) { $OwnedLock.directory_handle.Dispose() }
        return [ordered]@{
            owned = $true; released = $true; archived = $true; already_archived = $true
            released_pin = $OwnedLock.pin; archive_pin = $archivePin
        }
    }
    $livePin = Get-LocalEvidencePinSharedDelete $sharedLockPath
    Assert-ExactPin $OwnedLock.pin $livePin 'Shared lock release'
    $archiveLeaf = [IO.Path]::GetFileName($lockEvidencePath)
    [PlanoraMuniV34AtomicFile]::RenameOpenHandle($OwnedLock.native_handle, $OwnedLock.directory_handle, $archiveLeaf)
    $OwnedLock.archived = $true
    $archivePin = Get-LocalEvidencePinSharedDelete $lockEvidencePath
    Assert-SamePhysicalPin $livePin $archivePin 'Archived shared lock evidence'
    $OwnedLock.stream.Dispose()
    $OwnedLock.native_handle.Dispose()
    $OwnedLock.directory_handle.Dispose()
    return [ordered]@{
        owned = $true; released = $true; archived = $true; released_pin = $livePin; archive_pin = $archivePin
        released_at_utc = [DateTime]::UtcNow.ToString('o')
    }
}

function Get-ContinuousGuardObservation([Diagnostics.Stopwatch]$Stopwatch, [object]$OwnedLock, [object]$ProcessMonitor,
    [object]$ExpectedNamespace, [int]$ProcessStartDrainGraceMilliseconds = 0) {
    $completedElapsedMilliseconds = $Stopwatch.ElapsedMilliseconds
    $completedAtUtc = [DateTime]::UtcNow.ToString('o')
    if ($ProcessStartDrainGraceMilliseconds -lt 0 -or $ProcessStartDrainGraceMilliseconds -gt 10000) {
        throw 'Process-start drain grace interval rejected'
    }
    if ($ProcessStartDrainGraceMilliseconds -gt 0) {
        Start-Sleep -Milliseconds $ProcessStartDrainGraceMilliseconds
    }
    $processStarts = Read-ProcessStartMonitor $ProcessMonitor
    $docker = Get-DockerProcessObservation
    $artifacts = Get-CanonicalArtifactObservation
    $lock = Get-SharedLockObservation $OwnedLock
    $volume = Get-VolumeObservation
    $repositoryNamespace = Assert-RepositoryNamespaceIdentity $ExpectedNamespace
    return [ordered]@{
        observed_at_utc = $completedAtUtc; elapsed_milliseconds = $completedElapsedMilliseconds
        repository_namespace = $repositoryNamespace
        shared_lock_owned = [bool]$lock.owned; docker_matching_processes = [int]$docker.matching_process_count
        wsl_workload_processes = [int]$docker.wsl_workload_process_count
        docker_service_present = [bool]$docker.docker_service_present; docker_service_state = $docker.docker_service_state
        process_start_events = $processStarts
        volume = $volume
        canonical_run_artifacts = [int]$artifacts.run_artifact_count
        canonical_authorizations = [int]$artifacts.authorization_artifact_count
        final_runner_present = [bool]$artifacts.final_runner_present; final_gate_present = [bool]$artifacts.final_gate_present
    }
}

function Assert-ContinuousGuardObservation([object]$Observation) {
    if (-not [bool]$Observation.shared_lock_owned) { throw 'Continuous guard lost the admission-owned serialization lock' }
    Assert-ProcessStartMonitorHealthy $Observation.process_start_events
    Assert-VolumeAdmissible $Observation.volume
    if ([int]$Observation.docker_matching_processes -ne 0 -or
        [int]$Observation.wsl_workload_processes -ne 0 -or
        ([bool]$Observation.docker_service_present -and $Observation.docker_service_state -cne 'Stopped') -or
        [int]$Observation.process_start_events.suspicious_count -ne 0) {
        throw 'Continuous guard observed Docker or WSL activity'
    }
    if ([int]$Observation.canonical_run_artifacts -ne 0 -or [int]$Observation.canonical_authorizations -ne 0 -or
        [bool]$Observation.final_runner_present -or [bool]$Observation.final_gate_present) {
        throw 'Continuous guard observed final v34 canonical state'
    }
}

function Add-ContinuousGuardObservation([Collections.Generic.List[object]]$Rows, [object]$Observation) {
    Assert-ContinuousGuardObservation $Observation
    $elapsed = [long]$Observation.elapsed_milliseconds
    if ($Rows.Count -eq 0) {
        if ($elapsed -lt 0 -or $elapsed -gt $maximumContinuousGuardGapMilliseconds) {
            throw 'Continuous guard first-observation timing rejected'
        }
    }
    else {
        $previous = [long]$Rows[$Rows.Count - 1].elapsed_milliseconds
        if ($elapsed -lt $previous -or ($elapsed - $previous) -gt $maximumContinuousGuardGapMilliseconds) {
            throw 'Continuous guard poll gap rejected'
        }
    }
    $Rows.Add($Observation)
}

function Assert-ContinuousGuardTelemetry([object[]]$Rows, [long]$EndElapsedMilliseconds) {
    if ($Rows.Count -lt 2) { throw 'Continuous guard telemetry cardinality rejected' }
    $maximumGap = [long]0
    $maximumObservedFreeSpaceLoss = [long]0
    $previous = [long]0
    $initialRemaining = [long]$Rows[0].volume.size_remaining_bytes
    $volumeIdentity = @('drive_letter', 'file_system', 'health_status', 'operational_status', 'size_bytes',
        'partition_number', 'partition_guid', 'is_offline', 'is_read_only')
    foreach ($row in $Rows) {
        $elapsed = [long]$row.elapsed_milliseconds
        $gap = $elapsed - $previous
        if ($gap -lt 0 -or $gap -gt $maximumContinuousGuardGapMilliseconds) {
            throw 'Continuous guard telemetry gap rejected'
        }
        $maximumGap = [Math]::Max($maximumGap, $gap)
        foreach ($property in $volumeIdentity) {
            if ($row.volume.$property -cne $Rows[0].volume.$property) {
                throw "Continuous guard D volume identity drift: $property"
            }
        }
        $freeSpaceLoss = $initialRemaining - [long]$row.volume.size_remaining_bytes
        $maximumObservedFreeSpaceLoss = [Math]::Max($maximumObservedFreeSpaceLoss, $freeSpaceLoss)
        if ($freeSpaceLoss -gt $maximumFreeSpaceLossBytes) {
            throw 'Continuous guard D volume material free-space loss rejected'
        }
        $previous = $elapsed
    }
    $terminalGap = $EndElapsedMilliseconds - $previous
    if ($terminalGap -lt 0 -or $terminalGap -gt $maximumContinuousGuardGapMilliseconds) {
        throw 'Continuous guard terminal gap rejected'
    }
    $maximumGap = [Math]::Max($maximumGap, $terminalGap)
    return [ordered]@{
        status = 'PASS_CONTINUOUS_GUARD_TIMING'; observation_count = $Rows.Count
        maximum_gap_milliseconds = $maximumGap; terminal_elapsed_milliseconds = $EndElapsedMilliseconds
        maximum_observed_free_space_loss_bytes = $maximumObservedFreeSpaceLoss
        volume_identity_healthy_online_writable_at_every_poll = $true
    }
}

function Wait-GuardedUntil([long]$TargetElapsedMilliseconds, [Diagnostics.Stopwatch]$Stopwatch,
    [object]$OwnedLock, [object]$ProcessMonitor, [object]$ExpectedNamespace,
    [Collections.Generic.List[object]]$GuardRows) {
    while ($Stopwatch.ElapsedMilliseconds -lt $TargetElapsedMilliseconds) {
        $observation = Get-ContinuousGuardObservation $Stopwatch $OwnedLock $ProcessMonitor $ExpectedNamespace
        Add-ContinuousGuardObservation $GuardRows $observation
        $remaining = $TargetElapsedMilliseconds - $Stopwatch.ElapsedMilliseconds
        if ($remaining -gt 0) {
            Start-Sleep -Milliseconds ([int][Math]::Min($continuousGuardPollMilliseconds, $remaining))
        }
    }
}

function Assert-AdmissionNamespaceFresh {
    $existing = @($authorityIntentPath, $intentPath, $capturePath, $receiptPendingPath, $receiptPath,
        $rejectionPendingPath, $rejectionPath, $lockEvidencePath) |
        Where-Object { Test-Path -LiteralPath $_ }
    if ($existing.Count -ne 0) { throw 'Windows host-stability authority namespace is already consumed' }
}

function New-StaticFixtureSamples {
    $serviceRows = @(
        [ordered]@{ name = 'WslService'; present = $true; state = 'Running'; start_mode = 'Auto'; process_id = 10 },
        [ordered]@{ name = 'vmcompute'; present = $true; state = 'Running'; start_mode = 'Manual'; process_id = 11 },
        [ordered]@{ name = 'hns'; present = $true; state = 'Running'; start_mode = 'Manual'; process_id = 12 },
        [ordered]@{ name = 'HvHost'; present = $true; state = 'Running'; start_mode = 'Manual'; process_id = 13 }
    )
    $vhdx = [ordered]@{
        path = 'D:\fixture.vhdx'; size = 10; file_id = '0' * 32; creation_utc_ticks = 1
        last_write_utc_ticks = 2; attributes = 'Archive, Compressed'; compressed = $true
        encrypted = $false; sparse = $false
    }
    $parent = [ordered]@{
        path = 'D:\fixture'; file_id = '1' * 32; creation_utc_ticks = 1; last_write_utc_ticks = 2
        attributes = 'Directory, Compressed'; compressed = $true; encrypted = $false
    }
    $volume = [ordered]@{
        drive_letter = 'D'; file_system = 'NTFS'; health_status = 'Healthy'; operational_status = 'OK'
        size_bytes = [long](1TB); size_remaining_bytes = [long](512GB); partition_number = 1
        partition_guid = 'fixture'; is_offline = $false; is_read_only = $false
    }
    $docker = [ordered]@{
        matching_processes = @(); matching_process_count = 0; docker_service_present = $false
        wsl_workload_processes = @(); wsl_workload_process_count = 0
        docker_service_state = 'MISSING'; docker_service_process_id = 0
    }
    $namespace = [ordered]@{
        repository = [ordered]@{
            path = 'D:\Stuff\Projects\Sites\Planora'; file_id = '3' * 32; creation_utc_ticks = 1
            last_write_utc_ticks = 2; attributes = 'Directory'; compressed = $false; encrypted = $false
            reparse_point = $false
        }
        receipt_directory = [ordered]@{
            path = 'D:\Stuff\Projects\Sites\Planora\output\diagnostic-receipts'; file_id = '4' * 32
            creation_utc_ticks = 1; last_write_utc_ticks = 2; attributes = 'Directory'
            compressed = $false; encrypted = $false; reparse_point = $false
        }
    }
    $event141 = [ordered]@{
        present = $true; log_name = 'System'; record_id = 223072
        time_created_utc = '2026-08-30T00:20:37Z'; provider = 'Ntfs'; event_id = 141
    }
    $event26 = [ordered]@{
        present = $true; log_name = 'System'; record_id = 223073
        time_created_utc = '2026-08-30T00:20:38Z'; provider = 'Application Popup'; event_id = 26
    }
    $baseline = [ordered]@{ ntfs_141 = $event141; application_popup_26 = $event26 }
    $samples = @()
    foreach ($pair in @(@(1, 0), @(2, 450000), @(3, 900000))) {
        $sample = [ordered]@{
            index = $pair[0]; observed_at_utc = '2026-08-30T00:00:00Z'; elapsed_milliseconds = $pair[1]
            repository_namespace = $namespace
            shared_lock = [ordered]@{ present = $true; owned = $true; pin = [ordered]@{ sha256 = '2' * 64 } }
            canonical_artifacts = [ordered]@{
                run_artifacts = @(); run_artifact_count = 0; authorization_artifacts = @()
                authorization_artifact_count = 0; final_runner_present = $false; final_gate_present = $false
            }
            docker = $docker; services = $serviceRows; docker_vhdx = $vhdx; docker_vhdx_parent = $parent
            ubuntu_vhdx = $vhdx; ubuntu_vhdx_parent = $parent; volume = $volume
            ntfs_141 = $event141; application_popup_26 = $event26; new_storage_warnings = @()
        }
        $samples += , (ConvertFrom-Json -InputObject (ConvertTo-CanonicalJson $sample 20))
    }
    return [pscustomobject]@{ baseline = $baseline; samples = $samples }
}

if ($StaticSelfTest) {
    $fixture = New-StaticFixtureSamples
    $good = Assert-HostStabilitySamples @($fixture.samples) $fixture.baseline $true
    $negativeResults = [ordered]@{}
    $mutations = @(
        [pscustomobject]@{ name = 'timing_under_900_seconds'; apply = { param($rows) $rows[2].elapsed_milliseconds = 899999 } },
        [pscustomobject]@{ name = 'new_ntfs_141'; apply = { param($rows) $rows[1].ntfs_141.record_id = 223074 } },
        [pscustomobject]@{ name = 'new_application_popup_26'; apply = { param($rows) $rows[1].application_popup_26.record_id = 223074 } },
        [pscustomobject]@{ name = 'storage_warning'; apply = { param($rows) $rows[1].new_storage_warnings = @([pscustomobject]@{ event_id = 1 }) } },
        [pscustomobject]@{ name = 'docker_process'; apply = { param($rows) $rows[1].docker.matching_process_count = 1 } },
        [pscustomobject]@{ name = 'preexisting_wsl_workload'; apply = { param($rows) $rows[1].docker.wsl_workload_process_count = 1 } },
        [pscustomobject]@{ name = 'stopped_wsl_service'; apply = { param($rows) $rows[1].services[0].state = 'Stopped'; $rows[1].services[0].process_id = 0 } },
        [pscustomobject]@{ name = 'repository_namespace_drift'; apply = { param($rows) $rows[1].repository_namespace.receipt_directory.file_id = 'e' * 32 } },
        [pscustomobject]@{ name = 'repository_namespace_reparse'; apply = { param($rows) $rows[1].repository_namespace.receipt_directory.reparse_point = $true } },
        [pscustomobject]@{ name = 'vhdx_identity_drift'; apply = { param($rows) $rows[1].ubuntu_vhdx.file_id = 'f' * 32 } },
        [pscustomobject]@{ name = 'degraded_volume'; apply = { param($rows) $rows[1].volume.operational_status = 'OK,Degraded' } },
        [pscustomobject]@{ name = 'intermediate_free_space_loss'; apply = { param($rows) $rows[1].volume.size_remaining_bytes = [long](510GB) } },
        [pscustomobject]@{ name = 'canonical_artifact'; apply = { param($rows) $rows[1].canonical_artifacts.run_artifact_count = 1 } },
        [pscustomobject]@{ name = 'serialization_lock_lost'; apply = { param($rows) $rows[1].shared_lock.owned = $false } }
    )
    foreach ($mutation in $mutations) {
        $parsedRows = ConvertFrom-Json -InputObject (ConvertTo-CanonicalJson $fixture.samples 30)
        $rows = @()
        for ($rowIndex = 0; $rowIndex -lt $parsedRows.Count; $rowIndex++) {
            $rows += , $parsedRows[$rowIndex]
        }
        & $mutation.apply $rows
        $rejected = $false
        try { [void](Assert-HostStabilitySamples $rows $fixture.baseline $true) } catch { $rejected = $true }
        if (-not $rejected) { throw "Negative host-stability fixture was accepted: $($mutation.name)" }
        $negativeResults[$mutation.name] = 'REJECTED'
    }
    $monitorRejected = $false
    try {
        Assert-ProcessStartMonitorHealthy ([ordered]@{ subscriber_count = 0; subscription_job_state = 'Stopped' })
    }
    catch { $monitorRejected = $true }
    if (-not $monitorRejected) { throw 'Dead process-start monitor fixture was accepted' }
    $negativeResults.process_start_monitor_dead = 'REJECTED'
    $guardVolume = $fixture.samples[0].volume
    $validGuardRows = @(
        [ordered]@{ elapsed_milliseconds = 0; volume = $guardVolume },
        [ordered]@{ elapsed_milliseconds = 2000; volume = $guardVolume },
        [ordered]@{ elapsed_milliseconds = 4000; volume = $guardVolume }
    )
    [void](Assert-ContinuousGuardTelemetry $validGuardRows 6000)
    $gapGuardRows = @(
        [ordered]@{ elapsed_milliseconds = 0; volume = $guardVolume },
        [ordered]@{ elapsed_milliseconds = 20000; volume = $guardVolume },
        [ordered]@{ elapsed_milliseconds = 22000; volume = $guardVolume }
    )
    $gapRejected = $false
    try { [void](Assert-ContinuousGuardTelemetry $gapGuardRows 24000) } catch { $gapRejected = $true }
    if (-not $gapRejected) { throw 'Continuous guard gap fixture was accepted' }
    $negativeResults.guard_poll_gap = 'REJECTED'
    $freeSpaceGuardRows = ConvertFrom-Json -InputObject (ConvertTo-CanonicalJson $validGuardRows 20)
    $freeSpaceGuardRows[1].volume.size_remaining_bytes = [long](510GB)
    $guardFreeSpaceRejected = $false
    try { [void](Assert-ContinuousGuardTelemetry @($freeSpaceGuardRows) 6000) } catch { $guardFreeSpaceRejected = $true }
    if (-not $guardFreeSpaceRejected) { throw 'Continuous guard free-space fixture was accepted' }
    $negativeResults.guard_intermediate_free_space_loss = 'REJECTED'
    Assert-JsonBooleanProperty ([pscustomobject]@{ flag = $false }) 'flag' 'Boolean fixture'
    Assert-JsonArrayProperty ([pscustomobject]@{ values = @('Observe') }) 'values' 'Array fixture'
    $booleanTypeRejected = $false
    try {
        Assert-JsonBooleanProperty ([pscustomobject]@{ flag = 'false' }) 'flag' 'Malformed authorization fixture'
    }
    catch { $booleanTypeRejected = $true }
    if (-not $booleanTypeRejected) { throw 'Malformed authorization Boolean fixture was accepted' }
    $negativeResults.authorization_boolean_type = 'REJECTED'
    $arrayTypeRejected = $false
    try {
        Assert-JsonArrayProperty ([pscustomobject]@{ values = 'Observe' }) 'values' 'Malformed authorization fixture'
    }
    catch { $arrayTypeRejected = $true }
    if (-not $arrayTypeRejected) { throw 'Malformed authorization array fixture was accepted' }
    $negativeResults.authorization_array_type = 'REJECTED'
    $parsedFixture = ConvertFrom-CanonicalJsonText '{"schema":"fixture","nested":{"value":1}}' 'Static fixture'
    $aliasRejected = $false
    try { [void](ConvertFrom-CanonicalJsonText '{"schema":"fixture","SCHEMA":"alias"}' 'Alias fixture') } catch { $aliasRejected = $true }
    $duplicateRejected = $false
    try { [void](ConvertFrom-CanonicalJsonText '{"schema":"fixture","schema":"duplicate"}' 'Duplicate fixture') } catch { $duplicateRejected = $true }
    if ($parsedFixture.schema -cne 'fixture' -or -not $aliasRejected -or -not $duplicateRejected) {
        throw 'Canonical authorization JSON static regression rejected'
    }
    $selfTestJson = ConvertTo-CanonicalJson ([ordered]@{
        schema = 'planora.muni-v34.windows-host-stability-self-test.v2'; status = 'PASS'; positive = $good
        negative_results = $negativeResults; canonical_json_alias = 'REJECTED'; canonical_json_duplicate = 'REJECTED'
        wsl_executed = $false; host_state_queried = $false; artifacts_written = $false; live_authorization_read = $false
    }) 20
    [Console]::Out.WriteLine($selfTestJson)
    return
}

$modeName = if ($InspectPreconditions) { 'InspectPreconditions' } else { 'Observe' }
$authorizationState = $null
$mutex = $null
$mutexOwned = $false
$processMonitor = $null
$ownedLock = $null
$authorityIntentGuard = $null
$authorityIntentJson = $null
$authorityIntentWriteStarted = $false
$authorityIntentPublished = $false
$authorityIntentPin = $null
$authorityIntentTerminalReplay = $false
$intentGuard = $null
$intentJson = $null
$intentPublished = $false
$passPublished = $false
$authorityEntered = $false
$lockAcquisitionStarted = $false
$partialLockState = $null
$intentTerminalReplay = $false
$intentPin = $null
$captureGuard = $null
$captureJson = $null
$capturePublished = $false
$capturePin = $null
$captureTerminalReplay = $false
$namespaceIdentity = $null
$samples = @()
$guardRows = New-Object 'Collections.Generic.List[object]'
$guardTelemetry = $null
$lockRelease = $null
$receiptPublication = $null
$receiptJson = $null

try {
    $authorizationState = Get-GuardedAuthorizationState $modeName
    $mutex = New-Object Threading.Mutex($false, $mutexName)
    $mutexOwned = $mutex.WaitOne(0)
    if (-not $mutexOwned) { throw 'Another Windows host-stability admission owns the named mutex' }
    Assert-AdmissionNamespaceFresh
    $namespaceIdentity = Get-RepositoryNamespaceObservation
    Assert-RepositoryNamespaceObservationAdmissible $namespaceIdentity
    $authorityIntent = [ordered]@{
        schema = 'planora.muni-v34.windows-host-stability-authority-intent.v1'
        status = 'ONE_SHOT_AUTHORITY_DURABLY_ENTERED'; admission_id = $admissionId; mode = $modeName
        sources = $authorizationState.pins; repository_namespace = $namespaceIdentity
        automatic_retry_authorized = $false; wsl_authorized = $false
        docker_or_service_action_authorized = $false; canonical_execution_authorized = $false
        created_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    $authorityIntentJson = ConvertTo-CanonicalJson $authorityIntent 30
    $authorityIntentWriteStarted = $true
    Write-CreateOnlyUtf8Durable $authorityIntentPath $authorityIntentJson
    $authorityIntentPublished = $true
    $authorityIntentGuard = Open-ReadEvidenceGuard $authorityIntentPath
    $authorityIntentPin = Get-LocalEvidencePin $authorityIntentPath
    Assert-HeldCanonicalReplay $authorityIntentGuard $authorityIntentJson 'Host-stability authority intent'
    $authorityEntered = $true
    $processMonitor = Start-ProcessStartMonitor
    if (Test-Path -LiteralPath $sharedLockPath) { throw 'Shared heavy WSL lock present before host-stability admission' }
    $preflightStartUtc = [DateTime]::UtcNow
    $preflightBaseline = [ordered]@{
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        ntfs_141 = Get-LatestEventObservation 'System' 'Ntfs' 141
        application_popup_26 = Get-LatestEventObservation 'System' 'Application Popup' 26
    }
    $preflight = Get-LiveSample 0 0 $preflightStartUtc $null $namespaceIdentity
    Assert-SingleSampleAdmissible $preflight $preflightBaseline $false
    $preflightProcessStarts = Read-ProcessStartMonitor $processMonitor
    Assert-ProcessStartMonitorHealthy $preflightProcessStarts
    if ([int]$preflightProcessStarts.suspicious_count -ne 0) {
        throw 'Preflight observed Docker or WSL process activation'
    }
    if ($InspectPreconditions) {
        $preflightJson = ConvertTo-CanonicalJson ([ordered]@{
            schema = 'planora.muni-v34.windows-host-stability-preconditions.v2'; status = 'INSPECTED_NOT_ADMITTED'
            admission_id = $admissionId; authorization = $authorizationState.pins.authorization
            authority_intent_pin = $authorityIntentPin
            repository_namespace = $namespaceIdentity; baseline = $preflightBaseline
            sample = $preflight; process_start_events = $preflightProcessStarts
            wsl_executed = $false; artifacts_written = $true
            next_action = 'STOP_AND_CREATE_A_NEW_REVIEWED_ADMISSION_ID_BEFORE_OBSERVE_MODE'
        }) 40
        $receiptJson = $preflightJson
        Assert-HeldCanonicalReplay $authorityIntentGuard $authorityIntentJson 'Host-stability authority intent'
        $authorityIntentTerminalReplay = $true
        $receiptPublication = Publish-CanonicalTerminal $receiptPendingPath $receiptPath $receiptJson 'Preconditions receipt'
        $passPublished = $true
        [Console]::Out.WriteLine($preflightJson)
        return
    }
    $lockAcquisitionStarted = $true
    $ownedLock = New-SharedAdmissionLock $authorizationState.pins ([ref]$partialLockState)
    $intent = [ordered]@{
        schema = 'planora.muni-v34.windows-host-stability-intent.v2'
        status = 'INTENT_DURABLY_PUBLISHED_BEFORE_QUIET_WINDOW'; admission_id = $admissionId
        sources = $authorizationState.pins; repository_namespace = $namespaceIdentity; preflight = $preflight
        preflight_process_start_events = $preflightProcessStarts; serialization_lock = $ownedLock.pin
        sample_count = $sampleCount; sample_interval_seconds = $sampleIntervalSeconds
        minimum_quiet_window_seconds = $minimumQuietWindowSeconds
        continuous_guard_poll_ms = $continuousGuardPollMilliseconds
        maximum_continuous_guard_gap_ms = $maximumContinuousGuardGapMilliseconds
        minimum_free_space_bytes = $minimumFreeSpaceBytes; maximum_free_space_loss_bytes = $maximumFreeSpaceLossBytes
        wsl_authorized = $false; docker_action_authorized = $false; vhdx_attribute_change_authorized = $false
        canonical_execution_authorized = $false; automatic_retry_authorized = $false
        created_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    $intentJson = ConvertTo-CanonicalJson $intent 50
    Write-CreateOnlyUtf8Durable $intentPath $intentJson
    $intentPublished = $true
    $intentGuard = Open-ReadEvidenceGuard $intentPath
    $intentPin = Get-LocalEvidencePin $intentPath
    Assert-HeldCanonicalReplay $intentGuard $intentJson 'Host-stability intent'
    $baseline = [ordered]@{
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        ntfs_141 = Get-LatestEventObservation 'System' 'Ntfs' 141
        application_popup_26 = Get-LatestEventObservation 'System' 'Application Popup' 26
    }
    $startUtc = [DateTime]::UtcNow
    $watch = [Diagnostics.Stopwatch]::StartNew()
    for ($index = 1; $index -le $sampleCount; $index++) {
        $target = [long](($index - 1) * $sampleIntervalSeconds * 1000)
        if ($index -gt 1) {
            Wait-GuardedUntil $target $watch $ownedLock $processMonitor $namespaceIdentity $guardRows
        }
        $guard = Get-ContinuousGuardObservation $watch $ownedLock $processMonitor $namespaceIdentity
        Add-ContinuousGuardObservation $guardRows $guard
        $samples += , (Get-LiveSample $index $watch.ElapsedMilliseconds $startUtc $ownedLock $namespaceIdentity)
    }
    $decision = Assert-HostStabilitySamples $samples $baseline $true
    $preCaptureGuard = Get-ContinuousGuardObservation $watch $ownedLock $processMonitor $namespaceIdentity
    Add-ContinuousGuardObservation $guardRows $preCaptureGuard
    Assert-HeldCanonicalReplay $authorityIntentGuard $authorityIntentJson 'Host-stability authority intent'
    Assert-HeldCanonicalReplay $intentGuard $intentJson 'Host-stability intent'
    $capture = [ordered]@{
        schema = 'planora.muni-v34.windows-host-stability-capture.v1'
        status = 'CAPTURED_NOT_PASS_UNTIL_TERMINAL_RECEIPT'; admission_id = $admissionId
        sources = $authorizationState.pins; authority_intent_pin = $authorityIntentPin; intent_pin = $intentPin
        repository_namespace = $namespaceIdentity; baseline = $baseline; samples = $samples
        continuous_guard = [ordered]@{
            poll_interval_milliseconds = $continuousGuardPollMilliseconds
            maximum_gap_milliseconds = $maximumContinuousGuardGapMilliseconds
            observation_count = $guardRows.Count; observations = $guardRows
        }
        decision = $decision; vhdx_attributes_audited_not_changed = $true
        compressed_vhdx_blocker_cleared = $false; wsl_executed = $false
        canonical_execution_performed = $false; captured_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    $captureJson = ConvertTo-CanonicalJson $capture 70
    Write-CreateOnlyUtf8Durable $capturePath $captureJson
    $capturePublished = $true
    $captureGuard = Open-ReadEvidenceGuard $capturePath
    $capturePin = Get-LocalEvidencePin $capturePath
    Assert-HeldCanonicalReplay $captureGuard $captureJson 'Host-stability capture'
    $terminalGuard = Get-ContinuousGuardObservation $watch $ownedLock $processMonitor $namespaceIdentity `
        $terminalProcessStartDrainGraceMilliseconds
    Add-ContinuousGuardObservation $guardRows $terminalGuard
    $guardTelemetry = Assert-ContinuousGuardTelemetry @($guardRows.ToArray()) $terminalGuard.elapsed_milliseconds
    Assert-HeldCanonicalReplay $authorityIntentGuard $authorityIntentJson 'Host-stability authority intent'
    Assert-HeldCanonicalReplay $intentGuard $intentJson 'Host-stability intent'
    Assert-HeldCanonicalReplay $captureGuard $captureJson 'Host-stability capture'
    $watch.Stop()
    $lockRelease = Release-SharedAdmissionLock $ownedLock
    $ownedLock = $null
    [void](Assert-RepositoryNamespaceIdentity $namespaceIdentity)
    Assert-HeldCanonicalReplay $authorityIntentGuard $authorityIntentJson 'Host-stability authority intent'
    Assert-HeldCanonicalReplay $intentGuard $intentJson 'Host-stability intent'
    Assert-HeldCanonicalReplay $captureGuard $captureJson 'Host-stability capture'
    $intentTerminalReplay = $true
    $captureTerminalReplay = $true
    $authorityIntentTerminalReplay = $true
    $receipt = [ordered]@{
        schema = 'planora.muni-v34.windows-host-stability-admission.v3'
        status = 'PASS_WINDOWS_QUIET_WINDOW_ONLY_NOT_FULL_HOST_READINESS'; admission_id = $admissionId
        sources = $authorizationState.pins; authority_intent_pin = $authorityIntentPin; intent_pin = $intentPin
        capture_pin = $capturePin; serialization_lock_release = $lockRelease
        continuous_guard = [ordered]@{
            poll_interval_milliseconds = $continuousGuardPollMilliseconds
            maximum_gap_milliseconds = $maximumContinuousGuardGapMilliseconds; telemetry = $guardTelemetry
            capture_observation_count = $guardRows.Count - 1; total_observation_count = $guardRows.Count
            terminal_observation = $terminalGuard
        }
        authority_intent_terminal_replay = $authorityIntentTerminalReplay
        intent_terminal_replay = $intentTerminalReplay; capture_terminal_replay = $captureTerminalReplay
        repository_namespace_terminal_replay = $true; vhdx_attributes_audited_not_changed = $true
        compressed_vhdx_blocker_cleared = $false; wsl_executed = $false; ubuntu_activated = $false
        docker_or_service_action_performed = $false; canonical_execution_performed = $false
        default_runner_authority_consumed = $false; automatic_retry_authorized = $false
        next_authority = 'INDEPENDENTLY_REVIEW_THIS_WINDOWS_RECEIPT_THEN_BUILD_SEPARATE_BOUNDED_UBUNTU_COLD_START_ADMISSION'
        recorded_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    $receiptJson = ConvertTo-CanonicalJson $receipt 70
    $receiptPublication = Publish-CanonicalTerminal $receiptPendingPath $receiptPath $receiptJson 'Host-stability PASS receipt'
    $passPublished = $true
}
catch {
    $failure = $_.Exception.Message
    if ($null -ne $ownedLock) {
        try { $lockRelease = Release-SharedAdmissionLock $ownedLock; $ownedLock = $null }
        catch { $failure += '; shared_lock_release=' + $_.Exception.Message }
    }
    if ($intentPublished -and -not $passPublished) {
        try {
            if ($null -eq $intentGuard) { $intentGuard = Open-ReadEvidenceGuard $intentPath }
            Assert-HeldCanonicalReplay $intentGuard $intentJson 'Host-stability intent'
            $intentTerminalReplay = $true
        }
        catch { $failure += '; intent_terminal_replay=' + $_.Exception.Message }
    }
    if ($capturePublished -and -not $passPublished) {
        try {
            if ($null -eq $captureGuard) { $captureGuard = Open-ReadEvidenceGuard $capturePath }
            Assert-HeldCanonicalReplay $captureGuard $captureJson 'Host-stability capture'
            $captureTerminalReplay = $true
        }
        catch { $failure += '; capture_terminal_replay=' + $_.Exception.Message }
    }
    if ($authorityIntentPublished -and -not $passPublished) {
        try {
            if ($null -eq $authorityIntentGuard) { $authorityIntentGuard = Open-ReadEvidenceGuard $authorityIntentPath }
            Assert-HeldCanonicalReplay $authorityIntentGuard $authorityIntentJson 'Host-stability authority intent'
            $authorityIntentTerminalReplay = $true
        }
        catch { $failure += '; authority_intent_terminal_replay=' + $_.Exception.Message }
    }
    if ($authorityIntentWriteStarted -and -not $passPublished) {
        if (-not (Test-Path -LiteralPath $rejectionPath) -and -not (Test-Path -LiteralPath $rejectionPendingPath)) {
            $lockEvidencePin = $null
            $lockEvidenceObservationError = $null
            $sharedLockSourcePin = $null
            $sharedLockSourceObservationError = $null
            $passReceiptPin = $null
            $passReceiptObservationError = $null
            $pendingReceiptPin = $null
            $pendingReceiptObservationError = $null
            if (Test-Path -LiteralPath $lockEvidencePath) {
                try { $lockEvidencePin = Get-LocalEvidencePinSharedDelete $lockEvidencePath }
                catch { $lockEvidenceObservationError = $_.Exception.Message }
            }
            if (Test-Path -LiteralPath $sharedLockPath) {
                try { $sharedLockSourcePin = Get-LocalEvidencePinSharedDelete $sharedLockPath }
                catch { $sharedLockSourceObservationError = $_.Exception.Message }
            }
            if (Test-Path -LiteralPath $receiptPath) {
                try { $passReceiptPin = Get-LocalEvidencePin $receiptPath }
                catch { $passReceiptObservationError = $_.Exception.Message }
            }
            if (Test-Path -LiteralPath $receiptPendingPath) {
                try { $pendingReceiptPin = Get-LocalEvidencePin $receiptPendingPath }
                catch { $pendingReceiptObservationError = $_.Exception.Message }
            }
            $rejection = [ordered]@{
                schema = 'planora.muni-v34.windows-host-stability-rejection.v3'
                status = 'REJECTED_WINDOWS_HOST_STABILITY_AUTHORITY_CONSUMED'; admission_id = $admissionId
                sources = $authorizationState.pins; repository_namespace = $namespaceIdentity
                authority_intent_write_started = $authorityIntentWriteStarted
                authority_intent_present = $authorityIntentPublished; authority_intent_pin = $authorityIntentPin
                authority_intent_terminal_replay = $authorityIntentTerminalReplay
                authority_entered = $authorityEntered; intent_present = $intentPublished
                intent_pin = $intentPin; intent_terminal_replay = $intentTerminalReplay
                capture_present = $capturePublished; capture_pin = $capturePin
                capture_terminal_replay = $captureTerminalReplay
                lock_acquisition_started = $lockAcquisitionStarted; partial_lock_state = $partialLockState
                serialization_lock_source_pin = $sharedLockSourcePin
                serialization_lock_source_observation_error = $sharedLockSourceObservationError
                serialization_lock_evidence_pin = $lockEvidencePin
                serialization_lock_evidence_observation_error = $lockEvidenceObservationError
                failure = $failure
                samples = $samples; continuous_guard_observations = $guardRows
                serialization_lock_release = $lockRelease
                pass_receipt_present = $null -ne $passReceiptPin; pass_receipt_validated = $false
                pass_receipt_pin = $passReceiptPin; pass_receipt_observation_error = $passReceiptObservationError
                pending_pass_receipt_pin = $pendingReceiptPin
                pending_pass_receipt_observation_error = $pendingReceiptObservationError
                wsl_executed = $false; ubuntu_activated = $false; canonical_execution_performed = $false
                automatic_retry_authorized = $false; new_admission_id_required = $true
                recorded_at_utc = [DateTime]::UtcNow.ToString('o')
            }
            try {
                $rejectionJson = ConvertTo-CanonicalJson $rejection 70
                [void](Publish-CanonicalTerminal $rejectionPendingPath $rejectionPath $rejectionJson 'Host-stability rejection')
            }
            catch { $failure += '; rejection_publication=' + $_.Exception.Message }
        }
    }
    throw $failure
}
finally {
    if ($null -ne $ownedLock) {
        try { [void](Release-SharedAdmissionLock $ownedLock) } catch {}
    }
    Stop-ProcessStartMonitor $processMonitor
    if ($null -ne $captureGuard) { $captureGuard.Dispose() }
    if ($null -ne $intentGuard) { $intentGuard.Dispose() }
    if ($null -ne $authorityIntentGuard) { $authorityIntentGuard.Dispose() }
    if ($mutexOwned) { try { $mutex.ReleaseMutex() } catch {} }
    if ($null -ne $mutex) { $mutex.Dispose() }
    if ($null -ne $authorizationState) { Close-EvidenceGuards $authorizationState.streams }
}

if ($passPublished) {
    [Console]::Out.WriteLine($receiptJson)
    return
}

throw 'Windows host-stability authority reached no terminal state'
