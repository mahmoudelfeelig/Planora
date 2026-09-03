param(
    [switch]$Force,
    [string]$IsolatedReplayRoot
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$parentBuilderPath = Join-Path $repositoryRoot "scripts\build_agh_v17_chain.ps1"
$parentRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v17"
$defaultTargetRoot = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v18"
$targetRoot = $defaultTargetRoot
if ($IsolatedReplayRoot) {
    $resolvedReplayRoot = [System.IO.Path]::GetFullPath($IsolatedReplayRoot)
    $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $replayLeaf = [System.IO.Path]::GetFileName($resolvedReplayRoot.TrimEnd('\'))
    if (
        -not $resolvedReplayRoot.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not $replayLeaf.StartsWith("planora-agh-v18-replay-", [StringComparison]::Ordinal)
    ) {
        throw "Isolated replay root must be a planora-agh-v18-replay-* directory under the system temp root"
    }
    $targetRoot = $resolvedReplayRoot
}
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$strictUtf8NoBom = [System.Text.UTF8Encoding]::new($false, $true)

if (-not ("PlanoraAghV18.PinnedFile" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;

namespace PlanoraAghV18
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeFileTime
    {
        internal uint Low;
        internal uint High;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeFileInformation
    {
        internal uint Attributes;
        internal NativeFileTime CreationTime;
        internal NativeFileTime LastAccessTime;
        internal NativeFileTime LastWriteTime;
        internal uint VolumeSerialNumber;
        internal uint FileSizeHigh;
        internal uint FileSizeLow;
        internal uint NumberOfLinks;
        internal uint FileIndexHigh;
        internal uint FileIndexLow;
    }

    public sealed class PinnedFile : IDisposable
    {
        private const uint GenericRead = 0x80000000;
        private const uint ShareRead = 0x00000001;
        private const uint OpenExisting = 3;
        private const uint FileAttributeNormal = 0x00000080;
        private const uint FileAttributeDirectory = 0x00000010;
        private const uint FileAttributeReparsePoint = 0x00000400;
        private const uint FileFlagOpenReparsePoint = 0x00200000;
        private const uint FileFlagSequentialScan = 0x08000000;

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
            SafeFileHandle handle,
            out NativeFileInformation information
        );

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CreateHardLinkW(
            string newFileName,
            string existingFileName,
            IntPtr securityAttributes
        );

        private readonly string _path;
        private readonly SafeFileHandle _handle;
        private readonly FileStream _stream;
        private readonly NativeFileInformation _admitted;
        private bool _disposed;

        public byte[] Bytes { get; private set; }
        public string Sha256 { get; private set; }
        public long Length { get { return Bytes.LongLength; } }
        public uint LinkCount { get { return _admitted.NumberOfLinks; } }
        public string Identity { get { return IdentityOf(_admitted); } }

        public PinnedFile(string path, long maximumBytes)
        {
            if (String.IsNullOrWhiteSpace(path))
                throw new ArgumentException("Pinned path is required", "path");
            _path = Path.GetFullPath(path);
            _handle = OpenNoFollow(_path);
            FileStream openedStream = null;
            try
            {
                _admitted = Information(_handle);
                ValidateRegularSingleLink(_admitted, maximumBytes, "admission");
                openedStream = new FileStream(_handle, FileAccess.Read, 4096, false);
                _stream = openedStream;
                Bytes = ReadExactly(_stream, CheckedLength(_admitted, maximumBytes));
                Sha256 = Digest(Bytes);
                byte[] replay = ReadExactly(_stream, Bytes.Length);
                if (!FixedTimeEquals(Bytes, replay) || !String.Equals(Sha256, Digest(replay), StringComparison.Ordinal))
                    throw new IOException("Pinned descriptor digest replay changed");
                NativeFileInformation after = Information(_handle);
                RequireSame(_admitted, after, "descriptor changed during capture");
                RequireNamedBinding(_path, _admitted, maximumBytes);
            }
            catch
            {
                if (openedStream != null)
                    openedStream.Dispose();
                else
                    _handle.Dispose();
                throw;
            }
        }

        public void AssertStillBound()
        {
            ThrowIfDisposed();
            NativeFileInformation before = Information(_handle);
            RequireSame(_admitted, before, "retained descriptor identity changed");
            byte[] replay = ReadExactly(_stream, Bytes.Length);
            if (!String.Equals(Sha256, Digest(replay), StringComparison.Ordinal))
                throw new IOException("Retained descriptor digest changed");
            NativeFileInformation after = Information(_handle);
            RequireSame(_admitted, after, "retained descriptor changed during replay");
            RequireNamedBinding(_path, _admitted, Bytes.LongLength);
        }

        public void Dispose()
        {
            if (_disposed)
                return;
            _disposed = true;
            _stream.Dispose();
        }

        private static SafeFileHandle OpenNoFollow(string path)
        {
            SafeFileHandle handle = CreateFileW(
                path,
                GenericRead,
                ShareRead,
                IntPtr.Zero,
                OpenExisting,
                FileAttributeNormal | FileFlagOpenReparsePoint | FileFlagSequentialScan,
                IntPtr.Zero
            );
            if (handle.IsInvalid)
                throw new Win32Exception(Marshal.GetLastWin32Error(), "No-follow predecessor open failed: " + path);
            return handle;
        }

        private static NativeFileInformation Information(SafeFileHandle handle)
        {
            NativeFileInformation information;
            if (!GetFileInformationByHandle(handle, out information))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Pinned file information failed");
            return information;
        }

        private static long CheckedLength(NativeFileInformation information, long maximumBytes)
        {
            long length = ((long)information.FileSizeHigh << 32) | information.FileSizeLow;
            if (length < 0 || length > maximumBytes || length > Int32.MaxValue)
                throw new IOException("Pinned predecessor length rejected");
            return length;
        }

        private static void ValidateRegularSingleLink(NativeFileInformation information, long maximumBytes, string phase)
        {
            if ((information.Attributes & FileAttributeDirectory) != 0 || (information.Attributes & FileAttributeReparsePoint) != 0)
                throw new IOException("Pinned predecessor is not a no-follow regular file at " + phase);
            if (information.NumberOfLinks != 1)
                throw new IOException("Pinned predecessor link count rejected at " + phase);
            CheckedLength(information, maximumBytes);
        }

        private static void RequireNamedBinding(string path, NativeFileInformation admitted, long maximumBytes)
        {
            using (SafeFileHandle named = OpenNoFollow(path))
            {
                NativeFileInformation current = Information(named);
                ValidateRegularSingleLink(current, maximumBytes, "named replay");
                RequireSame(admitted, current, "named predecessor path changed");
            }
        }

        private static void RequireSame(NativeFileInformation expected, NativeFileInformation actual, string label)
        {
            if (
                expected.VolumeSerialNumber != actual.VolumeSerialNumber ||
                expected.FileIndexHigh != actual.FileIndexHigh ||
                expected.FileIndexLow != actual.FileIndexLow ||
                expected.FileSizeHigh != actual.FileSizeHigh ||
                expected.FileSizeLow != actual.FileSizeLow ||
                expected.NumberOfLinks != actual.NumberOfLinks ||
                expected.Attributes != actual.Attributes ||
                expected.LastWriteTime.High != actual.LastWriteTime.High ||
                expected.LastWriteTime.Low != actual.LastWriteTime.Low
            )
                throw new IOException(label);
        }

        private static byte[] ReadExactly(FileStream stream, long expectedLength)
        {
            stream.Seek(0, SeekOrigin.Begin);
            byte[] bytes = new byte[(int)expectedLength];
            int offset = 0;
            while (offset < bytes.Length)
            {
                int read = stream.Read(bytes, offset, bytes.Length - offset);
                if (read <= 0)
                    throw new EndOfStreamException("Pinned predecessor ended early");
                offset += read;
            }
            if (stream.ReadByte() != -1)
                throw new IOException("Pinned predecessor exceeded admitted length");
            return bytes;
        }

        private static string Digest(byte[] bytes)
        {
            using (SHA256 hash = SHA256.Create())
            {
                return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
            }
        }

        private static bool FixedTimeEquals(byte[] left, byte[] right)
        {
            if (left.Length != right.Length)
                return false;
            int difference = 0;
            for (int index = 0; index < left.Length; index++)
                difference |= left[index] ^ right[index];
            return difference == 0;
        }

        private static string IdentityOf(NativeFileInformation value)
        {
            return String.Format(
                System.Globalization.CultureInfo.InvariantCulture,
                "{0:x8}:{1:x8}{2:x8}:{3}:{4}:{5:x8}",
                value.VolumeSerialNumber,
                value.FileIndexHigh,
                value.FileIndexLow,
                ((long)value.FileSizeHigh << 32) | value.FileSizeLow,
                value.NumberOfLinks,
                value.Attributes
            );
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException("PinnedFile");
        }
    }
}
'@
}

$script:pinnedInputsByPath = [ordered]@{}

function Capture-PinnedInput(
    [string]$Path,
    [long]$MaximumBytes = 16777216,
    [long]$ExpectedSize = -1,
    [string]$ExpectedSha256 = $null
) {
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if ($script:pinnedInputsByPath.Contains($resolved)) {
        $existing = $script:pinnedInputsByPath[$resolved]
        if ($ExpectedSize -ge 0 -and $existing.size_bytes -ne $ExpectedSize) {
            throw "Captured predecessor size disagrees with expected pin: $resolved"
        }
        if ($ExpectedSha256 -and $existing.sha256 -cne $ExpectedSha256) {
            throw "Captured predecessor digest disagrees with expected pin: $resolved"
        }
        return $existing
    }
    $pinned = [PlanoraAghV18.PinnedFile]::new($resolved, $MaximumBytes)
    try {
        if ($ExpectedSize -ge 0 -and $pinned.Length -ne $ExpectedSize) {
            throw "Pinned predecessor size rejected: $resolved"
        }
        if ($ExpectedSha256 -and $pinned.Sha256 -cne $ExpectedSha256) {
            throw "Pinned predecessor digest rejected: $resolved"
        }
        $capture = [ordered]@{
            path = $resolved
            size_bytes = [long]$pinned.Length
            sha256 = [string]$pinned.Sha256
            identity = [string]$pinned.Identity
            link_count = [long]$pinned.LinkCount
            bytes = [byte[]]$pinned.Bytes
            retained = $pinned
        }
        $script:pinnedInputsByPath[$resolved] = $capture
        return $capture
    }
    catch {
        $pinned.Dispose()
        throw
    }
}

function Get-CapturedText([object]$Capture) {
    return $strictUtf8NoBom.GetString([byte[]]$Capture.bytes)
}

function Assert-AllPinnedInputsStillBound() {
    foreach ($capture in $script:pinnedInputsByPath.Values) {
        $capture.retained.AssertStillBound()
    }
}

function Close-AllPinnedInputs() {
    foreach ($capture in $script:pinnedInputsByPath.Values) {
        $capture.retained.Dispose()
    }
}

$expectedParentBuilder = [ordered]@{ size = 40757; sha256 = "4a895136bf05d1eb621a4b5a659aac6485229a971791eb98e4e704bfa291f989" }
$expectedParentArtifacts = [ordered]@{
    "agent-aghfal17-native-v17-bootstrap.py" = [ordered]@{ size = 12889; sha256 = "d93d9f0c3d90b18b53112bf2281f1aeef2fd2a853a434b16474e66a9a9586b97" }
    "agent-aghfal17-native-v17-generic-validator.py" = [ordered]@{ size = 6053; sha256 = "2b8d4bbb3758b4aadf9c1f6d6e251e353da9ea064b94dce66a9075f0f86eaa0b" }
    "agent-aghfal17-native-v17-invocations.json" = [ordered]@{ size = 18685; sha256 = "5dcb99619c38707a110e85c948c618993068ead87a5345ab105147ac4645dc4b" }
    "agent-aghfal17-native-v17-launcher.sh" = [ordered]@{ size = 10942; sha256 = "73a0fca53b0b299f6d8fa0bd09858abdf6ad06fe22b5842f701fdd814413147d" }
    "agent-aghfal17-native-v17-minimal-tcb.sha256" = [ordered]@{ size = 5119; sha256 = "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea" }
    "agent-aghfal17-native-v17-outer-controller.py" = [ordered]@{ size = 49808; sha256 = "3fe5dba53e9c6293694779c5bec0100e46f9fbcaa19b9ef8f96531db96723a35" }
    "agent-aghfal17-native-v17-review-freeze.json" = [ordered]@{ size = 43048; sha256 = "1919dc785c6d1a6d3f06eb5f087faacde2d2194b890d8a0da70943ac829977c1" }
    "agent-aghfal17-native-v17-runner.py" = [ordered]@{ size = 71673; sha256 = "cd4275566130b19b51a719caee39c391f2e4d28e207c0b56b2da69cb1fbf017f" }
    "agent-aghfal17-native-v17-stdlib.sha256" = [ordered]@{ size = 67004; sha256 = "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327" }
    "agent-aghfal17-native-v17-supervisor.py" = [ordered]@{ size = 149387; sha256 = "56a78bc55e2b6e324397d9e7350346382d63e1676cdda06553b40dd280c0cc89" }
    "agent-aghfal17-native-v17-tests.py" = [ordered]@{ size = 49937; sha256 = "32062adb957740779b9bc99886507a9b58f46627f71ce2560a8ea1e352fc494d" }
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
    [System.IO.File]::WriteAllText($Path, $Text.Replace("`r`n", "`n"), $utf8NoBom)
}

function ConvertTo-CanonicalJsonValue([object]$Value) {
    if ($null -eq $Value) {
        return "null"
    }
    if ($Value -is [string] -or $Value -is [char]) {
        return '"' + [System.Text.Json.JsonEncodedText]::Encode([string]$Value).ToString() + '"'
    }
    if ($Value -is [bool]) {
        if ($Value) { return "true" }
        return "false"
    }
    if ($Value -is [System.Collections.IDictionary]) {
        [string[]]$keys = @($Value.Keys | ForEach-Object {
            if ($_ -isnot [string]) {
                throw "Canonical JSON object key is not a string"
            }
            [string]$_
        })
        [Array]::Sort($keys, [StringComparer]::Ordinal)
        $parts = foreach ($key in $keys) {
            ('"' + [System.Text.Json.JsonEncodedText]::Encode($key).ToString() + '":' + (ConvertTo-CanonicalJsonValue $Value[$key]))
        }
        return "{" + [string]::Join(",", [string[]]$parts) + "}"
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $properties = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $properties[[string]$property.Name] = $property.Value
        }
        return ConvertTo-CanonicalJsonValue $properties
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $parts = foreach ($item in $Value) {
            ConvertTo-CanonicalJsonValue $item
        }
        return "[" + [string]::Join(",", [string[]]$parts) + "]"
    }
    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    if ($Value -is [double]) {
        if ([double]::IsNaN($Value) -or [double]::IsInfinity($Value)) {
            throw "Canonical JSON rejects non-finite double"
        }
        return ([double]$Value).ToString("R", $culture)
    }
    if ($Value -is [single]) {
        if ([single]::IsNaN($Value) -or [single]::IsInfinity($Value)) {
            throw "Canonical JSON rejects non-finite single"
        }
        return ([single]$Value).ToString("R", $culture)
    }
    if ($Value -is [decimal]) {
        return ([decimal]$Value).ToString("G29", $culture)
    }
    if (
        $Value -is [byte] -or $Value -is [sbyte] -or
        $Value -is [int16] -or $Value -is [uint16] -or
        $Value -is [int32] -or $Value -is [uint32] -or
        $Value -is [int64] -or $Value -is [uint64]
    ) {
        return ([System.IFormattable]$Value).ToString($null, $culture)
    }
    throw "Canonical JSON value type is unsupported: $($Value.GetType().FullName)"
}

function ConvertTo-CanonicalJson([object]$Value) {
    return ConvertTo-CanonicalJsonValue $Value
}

function Invoke-CanonicalJsonSelfTest() {
    $left = [ordered]@{
        z = 1
        a = [ordered]@{ b = $true; a = $false }
        m = @(3, $null, "x")
    }
    $right = [ordered]@{
        m = @(3, $null, "x")
        a = [ordered]@{ a = $false; b = $true }
        z = 1
    }
    $expected = '{"a":{"a":false,"b":true},"m":[3,null,"x"],"z":1}'
    $leftJson = ConvertTo-CanonicalJson $left
    $rightJson = ConvertTo-CanonicalJson $right
    if ($leftJson -cne $expected -or $rightJson -cne $expected) {
        throw "Canonical JSON recursive ordinal sorting self-test failed"
    }
    return [ordered]@{
        recursive_ordinal_key_sorting = $true
        insertion_order_independent = $true
        compact_utf8_lf_encoding = $true
        ordered_dictionary_hashtable_coercion_used = $false
    }
}

function Write-Json([string]$Path, [object]$Value) {
    Write-Utf8 $Path ((ConvertTo-CanonicalJson $Value) + "`n")
}

function Replace-Required(
    [string]$Text,
    [string]$Old,
    [string]$New,
    [string]$Label
) {
    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    if ($count -ne 1) {
        throw "Expected exactly one token while generating ${Label}; observed ${count}: $Old"
    }
    return $Text.Replace($Old, $New)
}

function Replace-RequiredAfter(
    [string]$Text,
    [string]$Context,
    [string]$Old,
    [string]$New,
    [string]$Label
) {
    $contextCount = ([regex]::Matches($Text, [regex]::Escape($Context))).Count
    if ($contextCount -ne 1) {
        throw "Expected exactly one context while generating ${Label}; observed ${contextCount}: $Context"
    }
    $contextIndex = $Text.IndexOf($Context, [StringComparison]::Ordinal)
    $prefix = $Text.Substring(0, $contextIndex)
    $suffix = $Text.Substring($contextIndex)
    $oldCount = ([regex]::Matches($suffix, [regex]::Escape($Old))).Count
    if ($oldCount -ne 1) {
        throw "Expected exactly one contextual token while generating ${Label}; observed ${oldCount}: $Old"
    }
    return $prefix + $suffix.Replace($Old, $New)
}

function Replace-FirstRequiredAfter(
    [string]$Text,
    [string]$Context,
    [string]$Old,
    [string]$New,
    [string]$Label
) {
    $contextCount = ([regex]::Matches($Text, [regex]::Escape($Context))).Count
    if ($contextCount -ne 1) {
        throw "Expected exactly one context while generating ${Label}; observed ${contextCount}: $Context"
    }
    $contextIndex = $Text.IndexOf($Context, [StringComparison]::Ordinal)
    $oldIndex = $Text.IndexOf($Old, $contextIndex, [StringComparison]::Ordinal)
    if ($oldIndex -lt 0) {
        throw "Expected contextual token while generating ${Label}: $Old"
    }
    return $Text.Substring(0, $oldIndex) + $New + $Text.Substring($oldIndex + $Old.Length)
}

function Convert-Version([string]$Text) {
    $Text = $Text.Replace("`r`n", "`n")
    $Text = $Text.Replace("NativeV17", "NativeV18")
    $Text = $Text.Replace("NATIVE_V17", "NATIVE_V18")
    $Text = $Text.Replace("native_v17", "native_v18")
    $Text = $Text.Replace("native-v17", "native-v18")
    $Text = $Text.Replace("aghfal17-v17", "aghfal17-v18")
    $Text = $Text.Replace("AGH-FAL17 v17", "AGH-FAL17 v18")
    $Text = $Text.Replace("agh-v17", "agh-v18")
    $Text = $Text.Replace("agh_v17", "agh_v18")
    return $Text
}

function Write-Transformed(
    [string]$SourceName,
    [string]$DestinationName,
    [scriptblock]$Transform
) {
    $destination = Join-Path $targetRoot $DestinationName
    if (-not $script:parentCapturedByName.Contains($SourceName)) {
        throw "Captured v17 predecessor is unavailable: $SourceName"
    }
    $text = Convert-Version (Get-CapturedText $script:parentCapturedByName[$SourceName])
    $text = & $Transform $text
    Write-Utf8 $destination $text
    return $destination
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

function Capture-PreservedInputs() {
    $snapshot = [ordered]@{}
    $pathSet = [System.Collections.Generic.List[string]]::new()
    foreach ($version in 12..17) {
        $builder = Join-Path $repositoryRoot "scripts\build_agh_v${version}_chain.ps1"
        $chain = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v${version}"
        if (-not (Test-Path -LiteralPath $builder) -or -not (Test-Path -LiteralPath $chain)) {
            throw "Preserved AGH v${version} evidence is missing"
        }
        $builderCapture = Capture-PinnedInput $builder
        $pathSet.Add([System.IO.Path]::GetFullPath($builder))
        $snapshot["builder_v${version}"] = [ordered]@{
            size_bytes = $builderCapture.size_bytes
            sha256 = $builderCapture.sha256
            identity = $builderCapture.identity
            link_count = $builderCapture.link_count
        }
        $chainSnapshot = [ordered]@{}
        $entries = @(Get-ChildItem -LiteralPath $chain -Force | Sort-Object Name)
        $unexpectedDirectories = @(
            $entries | Where-Object { $_.PSIsContainer -and $_.Name -cne "__pycache__" }
        )
        if ($unexpectedDirectories.Count -ne 0) {
            throw "Preserved AGH v${version} chain contains a nested directory"
        }
        foreach ($entry in @($entries | Where-Object { -not $_.PSIsContainer })) {
            $capture = Capture-PinnedInput $entry.FullName
            $pathSet.Add([System.IO.Path]::GetFullPath($entry.FullName))
            $chainSnapshot[$entry.Name] = [ordered]@{
                size_bytes = $capture.size_bytes
                sha256 = $capture.sha256
                identity = $capture.identity
                link_count = $capture.link_count
            }
        }
        $snapshot["chain_v${version}"] = $chainSnapshot
    }
    [string[]]$orderedPaths = $pathSet.ToArray()
    [Array]::Sort($orderedPaths, [StringComparer]::OrdinalIgnoreCase)
    return [ordered]@{
        snapshot = $snapshot
        paths = $orderedPaths
    }
}

function Assert-PreservedPathSetUnchanged([string[]]$ExpectedPaths) {
    $actual = [System.Collections.Generic.List[string]]::new()
    foreach ($version in 12..17) {
        $builder = Join-Path $repositoryRoot "scripts\build_agh_v${version}_chain.ps1"
        $chain = Join-Path $repositoryRoot "benchmarks\probe_diagnostics\agh_v${version}"
        $actual.Add([System.IO.Path]::GetFullPath($builder))
        foreach ($entry in @(Get-ChildItem -LiteralPath $chain -Force)) {
            if ($entry.PSIsContainer) {
                if ($entry.Name -cne "__pycache__") {
                    throw "Preserved AGH v${version} chain gained a nested directory"
                }
                continue
            }
            $actual.Add([System.IO.Path]::GetFullPath($entry.FullName))
        }
    }
    [string[]]$actualPaths = $actual.ToArray()
    [Array]::Sort($actualPaths, [StringComparer]::OrdinalIgnoreCase)
    if ([string]::Join("`n", $ExpectedPaths) -cne [string]::Join("`n", $actualPaths)) {
        throw "AGH v12-v17 predecessor path set changed during build"
    }
}

function Invoke-CaptureAdversarialSelfTest() {
    $selfTestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("planora-agh-v18-capture-selftest-" + [Guid]::NewGuid().ToString("N"))
    $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolvedSelfTest = [System.IO.Path]::GetFullPath($selfTestRoot)
    if (-not $resolvedSelfTest.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Capture self-test root escaped system temp"
    }
    [System.IO.Directory]::CreateDirectory($resolvedSelfTest) | Out-Null
    $renameBlocked = $false
    $hardlinkRejected = $false
    $replacementDigestRejected = $false
    try {
        $source = Join-Path $resolvedSelfTest "source.bin"
        $moved = Join-Path $resolvedSelfTest "moved.bin"
        $hardlink = Join-Path $resolvedSelfTest "hardlink.bin"
        [byte[]]$original = $utf8NoBom.GetBytes("planora-agh-v18-pinned-original")
        [byte[]]$replacement = $utf8NoBom.GetBytes("planora-agh-v18-pinned-mutatedx")
        [System.IO.File]::WriteAllBytes($source, $original)
        $expectedDigest = Get-BytesSha256 $original
        $capture = [PlanoraAghV18.PinnedFile]::new($source, 4096)
        try {
            try {
                [System.IO.File]::Move($source, $moved)
            }
            catch [System.IO.IOException] {
                $renameBlocked = $true
            }
            if (-not $renameBlocked) {
                throw "Retained predecessor handle did not block path swap"
            }
            $capture.AssertStillBound()
        }
        finally {
            $capture.Dispose()
        }
        if (-not [PlanoraAghV18.PinnedFile]::CreateHardLinkW($hardlink, $source, [IntPtr]::Zero)) {
            throw [System.ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error(), "Capture self-test hardlink creation failed")
        }
        try {
            $bad = [PlanoraAghV18.PinnedFile]::new($source, 4096)
            $bad.Dispose()
        }
        catch [System.IO.IOException] {
            $hardlinkRejected = $true
        }
        if (-not $hardlinkRejected) {
            throw "Hardlinked predecessor was not rejected"
        }
        [System.IO.File]::Delete($hardlink)
        [System.IO.File]::WriteAllBytes($source, $replacement)
        $replacementCapture = [PlanoraAghV18.PinnedFile]::new($source, 4096)
        try {
            $replacementDigestRejected = $replacementCapture.Sha256 -cne $expectedDigest
        }
        finally {
            $replacementCapture.Dispose()
        }
        if (-not $replacementDigestRejected) {
            throw "Replacement predecessor digest was not rejected"
        }
        return [ordered]@{
            retained_handle_blocks_rename = $renameBlocked
            hardlink_rejected = $hardlinkRejected
            replacement_digest_rejected = $replacementDigestRejected
        }
    }
    finally {
        if ([System.IO.Directory]::Exists($resolvedSelfTest)) {
            [System.IO.Directory]::Delete($resolvedSelfTest, $true)
        }
    }
}

$canonicalJsonSelfTests = Invoke-CanonicalJsonSelfTest
$captureSelfTests = Invoke-CaptureAdversarialSelfTest
$builderCapture = Capture-PinnedInput $PSCommandPath 4194304
$parentBuilderCapture = Capture-PinnedInput `
    $parentBuilderPath `
    4194304 `
    ([long]$expectedParentBuilder.size) `
    ([string]$expectedParentBuilder.sha256)
$preservedCapture = Capture-PreservedInputs
$preservedBefore = $preservedCapture.snapshot
$preservedPaths = $preservedCapture.paths
$script:parentCapturedByName = [ordered]@{}
foreach ($entry in $expectedParentArtifacts.GetEnumerator()) {
    $path = Join-Path $parentRoot $entry.Key
    $capture = Capture-PinnedInput `
        $path `
        4194304 `
        ([long]$entry.Value.size) `
        ([string]$entry.Value.sha256)
    $script:parentCapturedByName[$entry.Key] = $capture
}
[string[]]$observedParentNames = @($preservedBefore.chain_v17.Keys)
[string[]]$expectedParentNames = @($expectedParentArtifacts.Keys)
[Array]::Sort($observedParentNames, [StringComparer]::Ordinal)
[Array]::Sort($expectedParentNames, [StringComparer]::Ordinal)
if ([string]::Join("`n", $observedParentNames) -cne [string]::Join("`n", $expectedParentNames)) {
    throw "AGH v17 predecessor file set drifted"
}
$preservedSnapshotText = ConvertTo-CanonicalJson $preservedBefore
$preservedSnapshotSha256 = Get-TextSha256 $preservedSnapshotText
$preservedFileCount = 0
foreach ($version in 12..17) {
    $preservedFileCount += 1
    $preservedFileCount += @($preservedBefore["chain_v${version}"].Keys).Count
}

if (-not (Test-Path -LiteralPath $targetRoot)) {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}
$existing = @(Get-ChildItem -LiteralPath $targetRoot -Force)
if ($existing.Count -gt 0 -and -not $Force) {
    throw "Refusing to overwrite the AGH v18 chain without -Force"
}
if ($Force) {
    foreach ($entry in $existing) {
        if ($entry.PSIsContainer) {
            $resolvedTarget = [System.IO.Path]::GetFullPath($targetRoot).TrimEnd('\') + '\'
            $resolvedEntry = [System.IO.Path]::GetFullPath($entry.FullName)
            if (
                $entry.Name -cne "__pycache__" -or
                -not $resolvedEntry.StartsWith($resolvedTarget, [StringComparison]::OrdinalIgnoreCase)
            ) {
                throw "Unexpected nested directory in AGH v18 target: $($entry.FullName)"
            }
            Remove-Item -LiteralPath $resolvedEntry -Recurse
            continue
        }
        Remove-Item -LiteralPath $entry.FullName
    }
}

$minimalName = "agent-aghfal17-native-v18-minimal-tcb.sha256"
$stdlibName = "agent-aghfal17-native-v18-stdlib.sha256"
$minimalPath = Join-Path $targetRoot $minimalName
$stdlibPath = Join-Path $targetRoot $stdlibName
[System.IO.File]::WriteAllBytes(
    $minimalPath,
    [byte[]]$script:parentCapturedByName["agent-aghfal17-native-v17-minimal-tcb.sha256"].bytes
)
[System.IO.File]::WriteAllBytes(
    $stdlibPath,
    [byte[]]$script:parentCapturedByName["agent-aghfal17-native-v17-stdlib.sha256"].bytes
)

$genericPath = Write-Transformed `
    "agent-aghfal17-native-v17-generic-validator.py" `
    "agent-aghfal17-native-v18-generic-validator.py" `
    { param($text) return $text }
$genericHash = Get-Sha256 $genericPath

$runnerPath = Write-Transformed `
    "agent-aghfal17-native-v17-runner.py" `
    "agent-aghfal17-native-v18-runner.py" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v17-generic-validator.py"].sha256 `
            $genericHash `
            "v18 runner generic-validator pin"
    }
$runnerHash = Get-Sha256 $runnerPath

$supervisorPath = Write-Transformed `
    "agent-aghfal17-native-v17-supervisor.py" `
    "agent-aghfal17-native-v18-supervisor.py" `
    {
        param($text)
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v17-runner.py"].sha256 `
            $runnerHash `
            "v18 supervisor runner pin"
        $text = Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v17-generic-validator.py"].sha256 `
            $genericHash `
            "v18 supervisor generic-validator pin"
        $text = Replace-Required $text `
            'return {"status": "NO_GO", "resource_gate": initial, "host_sample": baseline, "official_instance_opened": False, "solver_child_process_started": False, "solver_execution_started": False, "official_solution_xml_published": False}' `
            'return {"status": "NO_GO", "resource_gate": initial, "host_sample": baseline, "official_instance_opened": False, "solver_child_process_started": False, "solver_execution_started": False, "official_solution_xml_published": False, "checkpoint_or_certified_provenance_used": False}' `
            "v18 launch initial resource-gate producer"
        $text = Replace-Required $text `
            'return {"status": "NO_GO", "resource_gate": capture_gate, "host_sample": after_capture, "official_instance_opened": True, "solver_child_process_started": False, "solver_execution_started": False, "official_solution_xml_published": False}' `
            'return {"status": "NO_GO", "resource_gate": capture_gate, "host_sample": after_capture, "official_instance_opened": True, "solver_child_process_started": False, "solver_execution_started": False, "official_solution_xml_published": False, "checkpoint_or_certified_provenance_used": False}' `
            "v18 launch capture resource-gate producer"
        $text = Replace-FirstRequiredAfter $text `
            '"schema": "planora.agh-fal17.native-v18-supervisor.v1"' `
            '            "official_solution_xml_published": status == "COMPLETION_VALID",' `
            "            `"official_solution_xml_published`": status == `"COMPLETION_VALID`",`n            `"checkpoint_or_certified_provenance_used`": False," `
            "v18 launch completion producer"
        $text = Replace-FirstRequiredAfter $text `
            'if initial_gate is not None:' `
            '            "official_solution_xml_published": False,' `
            "            `"official_solution_xml_published`": False,`n            `"checkpoint_or_certified_provenance_used`": False," `
            "v18 probe initial resource-gate producer"
        $text = Replace-FirstRequiredAfter $text `
            "        if capture_gate is not None:`n            return {`n                `"status`": `"NO_GO`",`n                `"resource_gate`": capture_gate," `
            '                "official_solution_xml_published": False,' `
            "                `"official_solution_xml_published`": False,`n                `"checkpoint_or_certified_provenance_used`": False," `
            "v18 probe capture resource-gate producer"
        $text = Replace-FirstRequiredAfter $text `
            '"schema": "planora.agh-fal17.native-v18-sealed-import-supervisor.v1"' `
            '            "official_solution_xml_published": False,' `
            "            `"official_solution_xml_published`": False,`n            `"checkpoint_or_certified_provenance_used`": False," `
            "v18 inner authoritative checkpoint evidence"
        $text = Replace-FirstRequiredAfter $text `
            'def self_test() -> dict[str, Any]:' `
            '        "official_solution_xml_published": False,' `
            "        `"official_solution_xml_published`": False,`n        `"checkpoint_or_certified_provenance_used`": False," `
            "v18 self-test producer"
        return Replace-FirstRequiredAfter $text `
            'def dry_run() -> dict[str, Any]:' `
            '        "official_solution_xml_published": False,' `
            "        `"official_solution_xml_published`": False,`n        `"checkpoint_or_certified_provenance_used`": False," `
            "v18 dry-run producer"
    }
$supervisorHash = Get-Sha256 $supervisorPath

$launcherPath = Write-Transformed `
    "agent-aghfal17-native-v17-launcher.sh" `
    "agent-aghfal17-native-v18-launcher.sh" `
    {
        param($text)
        return Replace-Required $text `
            $expectedParentArtifacts["agent-aghfal17-native-v17-supervisor.py"].sha256 `
            $supervisorHash `
            "v18 launcher supervisor pin"
    }
$launcherHash = Get-Sha256 $launcherPath

$bootstrapPath = Write-Transformed `
    "agent-aghfal17-native-v17-bootstrap.py" `
    "agent-aghfal17-native-v18-bootstrap.py" `
    { param($text) return $text }
$bootstrapHash = Get-Sha256 $bootstrapPath

$outerPath = Write-Transformed `
    "agent-aghfal17-native-v17-outer-controller.py" `
    "agent-aghfal17-native-v18-outer-controller.py" `
    {
        param($text)
        $helpers = @'
def has_exact_checkpoint_provenance_false(payload: Mapping[str, Any]) -> bool:
    """Require explicit JSON false; equality with false is insufficient."""

    key = "checkpoint_or_certified_provenance_used"
    return (
        type(payload) is dict
        and key in payload
        and type(payload[key]) is bool
        and payload[key] is False
    )


def checkpoint_evidence_pair_is_exact(
    outer_payload: Mapping[str, Any], inner_payload: Mapping[str, Any]
) -> bool:
    """Bind the retained-probe outer and inner provenance assertions."""

    return has_exact_checkpoint_provenance_false(
        outer_payload
    ) and has_exact_checkpoint_provenance_false(inner_payload)


'@
        $text = Replace-Required $text `
            "def validate_inner_truth(mode: str, payload: Mapping[str, Any]) -> list[str]:" `
            ($helpers + "def validate_inner_truth(mode: str, payload: Mapping[str, Any]) -> list[str]:") `
            "v18 exact checkpoint helpers"
        $oldProbeContract = @'
            "solver_execution_started": False,
            "publication": False,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                errors.append(f"probe_truth:{key}")
'@
        $newProbeContract = @'
            "solver_execution_started": False,
            "publication": False,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                errors.append(f"probe_truth:{key}")
        if not has_exact_checkpoint_provenance_false(payload):
            errors.append("probe_truth:checkpoint_or_certified_provenance_used")
'@
        $text = Replace-Required $text $oldProbeContract $newProbeContract "v18 inner checkpoint consumer"
        $oldInitial = @'
            "official_instance_opened": False,
            "publication": False,
        }
'@
        $newInitial = @'
            "official_instance_opened": False,
            "publication": False,
            "checkpoint_or_certified_provenance_used": False,
        }
'@
        $text = Replace-Required $text $oldInitial $newInitial "v18 no-start outer checkpoint evidence"
        $oldFinal = @'
        "numeric_process_group_signal_sent": False,
    }
    report_raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
'@
        $newFinal = @'
        "numeric_process_group_signal_sent": False,
        "checkpoint_or_certified_provenance_used": False,
    }
    if mode == "probe" and not checkpoint_evidence_pair_is_exact(
        payload, inner_payload
    ):
        errors.append("checkpoint_provenance_pair_not_exact_false")
        payload["status"] = "FAILED"
    report_raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
'@
        return Replace-Required $text $oldFinal $newFinal "v18 outer authoritative checkpoint evidence"
    }
$outerHash = Get-Sha256 $outerPath

$runtimeHashMap = [ordered]@{
    $expectedParentArtifacts["agent-aghfal17-native-v17-outer-controller.py"].sha256 = $outerHash
    $expectedParentArtifacts["agent-aghfal17-native-v17-bootstrap.py"].sha256 = $bootstrapHash
    $expectedParentArtifacts["agent-aghfal17-native-v17-launcher.sh"].sha256 = $launcherHash
    $expectedParentArtifacts["agent-aghfal17-native-v17-supervisor.py"].sha256 = $supervisorHash
    $expectedParentArtifacts["agent-aghfal17-native-v17-runner.py"].sha256 = $runnerHash
    $expectedParentArtifacts["agent-aghfal17-native-v17-generic-validator.py"].sha256 = $genericHash
}

$testsPath = Write-Transformed `
    "agent-aghfal17-native-v17-tests.py" `
    "agent-aghfal17-native-v18-tests.py" `
    {
        param($text)
        foreach ($entry in $runtimeHashMap.GetEnumerator()) {
            $text = $text.Replace([string]$entry.Key, [string]$entry.Value)
        }
        $text = $text.Replace("class V17FreezeReadinessTests", "class V18FreezeReadinessTests")
        $text = $text.Replace(
            "def test_v17_is_review_ready_but_execution_unauthorized",
            "def test_v18_is_review_ready_but_execution_unauthorized"
        )
        $text = Replace-Required $text `
            '"READY_FOR_INDEPENDENT_STATIC_REVIEW_NO_GO_FOR_PROBE_OR_OFFICIAL_LAUNCH"' `
            '"READY_FOR_INDEPENDENT_STATIC_CHAIN_REVIEW_NO_GO_FOR_EXECUTION"' `
            "v18 frozen review status"
        $oldClosureTest = @'
    def test_current_planora_source_closure_replays(self) -> None:
        for relative, row in self.freeze["source_closure"].items():
            local = REPOSITORY_ROOT / relative
            self.assertEqual(local.stat().st_size, row["size_bytes"], relative)
            self.assertEqual(
                sha256(local.read_bytes()).hexdigest(), row["sha256"], relative
            )

'@
        $newClosureTest = @'
    def test_v17_planora_source_closure_is_inherited_without_repin(self) -> None:
        parent_path = (
            ARTIFACT_ROOT.parent
            / "agh_v17"
            / "agent-aghfal17-native-v17-review-freeze.json"
        )
        parent = json.loads(parent_path.read_text(encoding="utf-8"))
        self.assertEqual(self.freeze["source_closure"], parent["source_closure"])

'@
        $text = Replace-Required $text $oldClosureTest $newClosureTest "v18 frozen source closure inheritance"
        $oldValidProbe = @'
                    "solver_execution_started": False,
                    "publication": False,
                },
'@
        $newValidProbe = @'
                    "solver_execution_started": False,
                    "publication": False,
                    "checkpoint_or_certified_provenance_used": False,
                },
'@
        $text = Replace-Required $text $oldValidProbe $newValidProbe "v18 valid probe truth fixture"
        $text = Replace-Required $text `
            'self.assertEqual(preserved["versions"], [12, 13, 14, 15, 16])' `
            'self.assertEqual(preserved["versions"], [12, 13, 14, 15, 16, 17])' `
            "v18 preserved predecessor versions"
        $text = Replace-Required $text `
            'self.assertEqual(preserved["file_count"], 63)' `
            'self.assertEqual(preserved["file_count"], 72)' `
            "v18 preserved predecessor file count"
        $checkpointTests = @'
class V18CheckpointProvenanceRegressionTests(unittest.TestCase):
    def _valid_outer(self) -> dict[str, object]:
        return {"checkpoint_or_certified_provenance_used": False}

    def _valid_inner(self) -> dict[str, object]:
        return {
            "status": "PASS",
            "official_instance_opened": False,
            "solver_child_process_started": False,
            "solver_execution_started": False,
            "publication": False,
            "checkpoint_or_certified_provenance_used": False,
        }

    def test_exact_builtin_false_pair_is_accepted(self) -> None:
        self.assertTrue(
            outer.checkpoint_evidence_pair_is_exact(
                self._valid_outer(), self._valid_inner()
            )
        )
        self.assertEqual(outer.validate_inner_truth("probe", self._valid_inner()), [])

    def test_absent_null_zero_string_false_and_true_reject(self) -> None:
        key = "checkpoint_or_certified_provenance_used"
        invalid_payloads: tuple[dict[str, object], ...] = (
            {},
            {key: None},
            {key: 0},
            {key: "false"},
            {key: True},
        )
        for payload in invalid_payloads:
            self.assertFalse(outer.has_exact_checkpoint_provenance_false(payload))
            self.assertFalse(
                outer.checkpoint_evidence_pair_is_exact(
                    payload, self._valid_inner()
                )
            )
            inner = self._valid_inner()
            if key in payload:
                inner[key] = payload[key]
            else:
                del inner[key]
            self.assertFalse(
                outer.checkpoint_evidence_pair_is_exact(self._valid_outer(), inner)
            )
            self.assertIn(
                "probe_truth:checkpoint_or_certified_provenance_used",
                outer.validate_inner_truth("probe", inner),
            )

    def test_outer_inner_mismatch_rejects_in_both_directions(self) -> None:
        outer_payload = self._valid_outer()
        inner_payload = self._valid_inner()
        outer_payload["checkpoint_or_certified_provenance_used"] = True
        self.assertFalse(
            outer.checkpoint_evidence_pair_is_exact(outer_payload, inner_payload)
        )
        outer_payload["checkpoint_or_certified_provenance_used"] = False
        inner_payload["checkpoint_or_certified_provenance_used"] = True
        self.assertFalse(
            outer.checkpoint_evidence_pair_is_exact(outer_payload, inner_payload)
        )

    def test_authoritative_producers_emit_literal_false(self) -> None:
        supervisor_tree = ast.parse(
            SUPERVISOR_PATH.read_text(encoding="utf-8"),
            filename=str(SUPERVISOR_PATH),
        )
        status_producers: list[ast.Dict] = []
        for node in ast.walk(supervisor_tree):
            if not isinstance(node, ast.Dict):
                continue
            names = {
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if "status" in names:
                status_producers.append(node)
        self.assertEqual(len(status_producers), 8)
        for producer in status_producers:
            matches = [
                value
                for key, value in zip(producer.keys, producer.values, strict=True)
                if isinstance(key, ast.Constant)
                and key.value == "checkpoint_or_certified_provenance_used"
            ]
            self.assertEqual(len(matches), 1, ast.unparse(producer)[:160])
            value = matches[0]
            self.assertIsInstance(value, ast.Constant)
            self.assertIs(value.value, False)
            self.assertIs(type(value.value), bool)

        outer_tree = ast.parse(
            OUTER_PATH.read_text(encoding="utf-8"), filename=str(OUTER_PATH)
        )
        outer_literal_false = 0
        for node in ast.walk(outer_tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "checkpoint_or_certified_provenance_used"
                    and isinstance(value, ast.Constant)
                    and value.value is False
                    and type(value.value) is bool
                ):
                    outer_literal_false += 1
        self.assertGreaterEqual(outer_literal_false, 2)

    def test_generated_json_is_recursive_ordinal_canonical_utf8(self) -> None:
        class ObjectPairs(list[tuple[str, object]]):
            pass

        def visit(value: object, label: str) -> None:
            if isinstance(value, ObjectPairs):
                keys = [key for key, _ in value]
                ordinal = sorted(
                    keys, key=lambda key: key.encode("utf-16-be", "surrogatepass")
                )
                self.assertEqual(keys, ordinal, label)
                for key, child in value:
                    visit(child, f"{label}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{label}[{index}]")

        json_paths = (
            FREEZE_PATH,
            INVOCATIONS_PATH,
            ARTIFACT_ROOT / "agent-aghfal17-native-v18-derivation.json",
            ARTIFACT_ROOT / "agent-aghfal17-native-v18-review-certificate.json",
        )
        for path in json_paths:
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertTrue(raw.endswith(b"\n"), path.name)
            self.assertFalse(raw.endswith(b"\n\n"), path.name)
            body = raw[:-1].decode("utf-8")
            in_string = False
            escaped = False
            for character in body:
                if in_string:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == '"':
                        in_string = False
                elif character == '"':
                    in_string = True
                else:
                    self.assertNotIn(character, " \t\r\n", path.name)
            self.assertFalse(in_string, path.name)
            parsed = json.loads(body, object_pairs_hook=ObjectPairs)
            visit(parsed, path.name)

        builder = (REPOSITORY_ROOT / "scripts" / "build_agh_v18_chain.ps1").read_text(
            encoding="utf-8"
        )
        forbidden_coercion = "[hash" + "table]"
        self.assertNotIn(forbidden_coercion, builder.lower())
        self.assertIn("ConvertTo-CanonicalJsonValue", builder)
        self.assertIn("[StringComparer]::Ordinal", builder)

    def test_no_checkpoint_or_certified_incumbent_path_exists(self) -> None:
        forbidden = (
            "--checkpoint",
            "checkpoint_path",
            "load_checkpoint",
            "save_checkpoint",
            "certified_incumbent",
            "incumbent_certificate",
        )
        for path in (
            OUTER_PATH,
            SUPERVISOR_PATH,
            RUNNER_PATH,
            BOOTSTRAP_PATH,
            LAUNCHER_PATH,
        ):
            text = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name}: {token}")
        invocations = json.loads(INVOCATIONS_PATH.read_text(encoding="utf-8"))
        for mode in ("probe", "launch"):
            rendered = "\n".join(invocations[mode]["argv"]).lower()
            for token in forbidden:
                self.assertNotIn(token, rendered, f"{mode} argv: {token}")

    def test_v17_rejection_and_v18_review_boundaries_are_frozen(self) -> None:
        freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
        rejected = freeze["predecessor_v17_static_review_no_go"]
        self.assertEqual(rejected["verdict"], "NO_GO_DO_NOT_RUN_RETAINED_PROBE")
        self.assertFalse(freeze["verification"]["probe_run_authorized"])
        self.assertFalse(freeze["verification"]["official_launch_authorized"])
        contract = freeze["checkpoint_evidence_contract"]
        self.assertEqual(contract["required_type"], "builtins.bool")
        self.assertIs(contract["required_value"], False)


'@
        return Replace-Required $text `
            "@unittest.skipUnless(" `
            ($checkpointTests + "@unittest.skipUnless(") `
            "v18 checkpoint adversarial regressions"
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

$derivationPath = Join-Path $targetRoot "agent-aghfal17-native-v18-derivation.json"
$derivation = [ordered]@{
    schema = "planora.agh-fal17.native-v18-derivation.v1"
    status = "DERIVED_FROM_FROZEN_V17_NO_EXECUTION_AUTHORIZED"
    deterministic_metadata_date = "2026-08-27"
    builder = [ordered]@{
        path = "scripts/build_agh_v18_chain.ps1"
        size_bytes = $builderCapture.size_bytes
        sha256 = $builderCapture.sha256
    }
    rejected_predecessor = [ordered]@{
        version = 17
        verdict = "NO_GO_DO_NOT_RUN_RETAINED_PROBE"
        builder = $expectedParentBuilder
        freeze_manifest = $expectedParentArtifacts["agent-aghfal17-native-v17-review-freeze.json"]
        outer_controller = $expectedParentArtifacts["agent-aghfal17-native-v17-outer-controller.py"]
        supervisor = $expectedParentArtifacts["agent-aghfal17-native-v17-supervisor.py"]
        blockers = @(
            "outer payload omitted checkpoint_or_certified_provenance_used",
            "sealed-import supervisor payload omitted checkpoint_or_certified_provenance_used",
            "v17 retained-probe wrapper therefore failed closed before bwrap"
        )
    }
    derivation_rules = @(
        "capture every v12-v17 input through a retained no-follow single-link handle and transform only captured bytes",
        "bind identity and digest before and after capture, retain handles through output generation, and reject path swaps",
        "serialize every generated JSON artifact by recursive ordinal key sorting without hashtable coercion",
        "canonicalize generated text-file line endings to LF while preserving parsed semantics",
        "apply only version-token changes, transitive pin updates, exact checkpoint evidence, strict consumer checks, and tests",
        "preserve canonical probe and launch argv shape, one-worker deterministic settings, solver semantics, and official-input boundaries",
        "never authorize or execute a probe, solver, official input, launch, or publication"
    )
    checkpoint_delta = [ordered]@{
        required_key = "checkpoint_or_certified_provenance_used"
        required_type = "builtins.bool"
        required_value = $false
        authoritative_outer_schema = "planora.agh-fal17.native-v18-outer-controller.v1"
        authoritative_inner_schema = "planora.agh-fal17.native-v18-sealed-import-supervisor.v1"
        invalid_values = @("absent", "null", "integer_zero", "string_false", "true", "outer_inner_mismatch")
        checkpoint_path_present = $false
        certified_incumbent_path_present = $false
    }
    canonical_json = $canonicalJsonSelfTests
    predecessor_capture = [ordered]@{
        no_follow = $true
        single_link_required = $true
        retained_handle_through_generation = $true
        transform_from_captured_bytes_only = $true
        identity_and_digest_replayed_before_and_after = $true
        adversarial_self_tests = $captureSelfTests
    }
    generated_artifacts = [ordered]@{}
}
foreach ($entry in $artifactPaths.GetEnumerator()) {
    $item = Get-Item -LiteralPath ([string]$entry.Value)
    $derivation.generated_artifacts[$entry.Key] = [ordered]@{
        path = "benchmarks/probe_diagnostics/agh_v18/$($item.Name)"
        size_bytes = $item.Length
        sha256 = Get-Sha256 $item.FullName
    }
}
Write-Json $derivationPath $derivation
$derivationHash = Get-Sha256 $derivationPath

$certificatePath = Join-Path $targetRoot "agent-aghfal17-native-v18-review-certificate.json"
$certificate = [ordered]@{
    schema = "planora.agh-fal17.native-v18-review-certificate.v1"
    verdict = "GO_FOR_INDEPENDENT_STATIC_CHAIN_REVIEW_ONLY"
    execution_verdict = "NO_GO"
    deterministic_metadata_date = "2026-08-27"
    derivation = [ordered]@{
        path = "/tmp/agent-aghfal17-native-v18-derivation.json"
        size_bytes = (Get-Item -LiteralPath $derivationPath).Length
        sha256 = $derivationHash
    }
    reviewed_changes = @(
        "all eight actual supervisor status-producing returns and payloads, including both initial resource gates, emit their own literal built-in false",
        "outer retained-probe consumer requires exact built-in false from both outer and inner payloads",
        "absent null integer-zero string-false true and mismatched evidence are regression cases",
        "generated JSON uses recursive ordinal key sorting with compact UTF-8 LF bytes and no hashtable coercion",
        "predecessors are transformed only from retained no-follow single-link identity-and-digest-bound captures and path swaps are rejected",
        "no checkpoint or certified-incumbent path was introduced",
        "one-worker deterministic no-official-input retained-probe command contract remains frozen"
    )
    required_external_replay = @(
        "Windows PowerShell builder replay",
        "Windows Python unittest replay",
        "Python AST parse for every generated Python artifact",
        "Ruff lint check",
        "independent static chain review"
    )
    prohibited = @("WSL", "Bash execution", "probe", "solver", "Docker", "browser", "official input", "publication")
    probe_run_authorized = $false
    official_launch_authorized = $false
}
Write-Json $certificatePath $certificate
$certificateHash = Get-Sha256 $certificatePath

$artifactPaths.derivation_record = $derivationPath
$artifactPaths.review_certificate = $certificatePath
$oldToNewHashes = [ordered]@{}
foreach ($entry in $runtimeHashMap.GetEnumerator()) {
    $oldToNewHashes[$entry.Key] = $entry.Value
}
$oldToNewHashes[$expectedParentArtifacts["agent-aghfal17-native-v17-tests.py"].sha256] = $testsHash

$parentFreezeText = Get-CapturedText $script:parentCapturedByName["agent-aghfal17-native-v17-review-freeze.json"]
$parentFreeze = $parentFreezeText | ConvertFrom-Json -AsHashtable
$freezeText = Convert-Version $parentFreezeText
foreach ($entry in $oldToNewHashes.GetEnumerator()) {
    $freezeText = $freezeText.Replace([string]$entry.Key, [string]$entry.Value)
}
$freeze = $freezeText | ConvertFrom-Json -AsHashtable
$freeze.created_utc = "2026-08-27T00:00:00Z"
$freeze.status = "READY_FOR_INDEPENDENT_STATIC_CHAIN_REVIEW_NO_GO_FOR_EXECUTION"
$freeze.scope = "AGH-FAL17 v18 exact checkpoint provenance evidence derived from frozen v17; no runtime or official input used by this builder"
$freeze.verification.static_checks = "BUILDER_INVARIANTS_ONLY_EXTERNAL_WINDOWS_REPLAY_REQUIRED"
$freeze.verification.live_workspace_source_closure_replay = "NOT_USED_V17_FROZEN_CLOSURE_PRESERVED_WITHOUT_REPIN"
$freeze.verification.linux_adversarial_tests = "NOT_RUN"
$freeze.verification.sealed_import_probe = "NOT_RUN"
$freeze.verification.official_input_opened = $false
$freeze.verification.solver_started = $false
$freeze.verification.probe_run_authorized = $false
$freeze.verification.official_launch_authorized = $false
$freeze.verification.canonical_json_self_tests = $canonicalJsonSelfTests
$freeze.verification.predecessor_capture_self_tests = $captureSelfTests
$freeze.predecessor_v17_static_review_no_go = [ordered]@{
    verdict = "NO_GO_DO_NOT_RUN_RETAINED_PROBE"
    builder_sha256 = $expectedParentBuilder.sha256
    freeze_manifest_sha256 = $expectedParentArtifacts["agent-aghfal17-native-v17-review-freeze.json"].sha256
    outer_controller_sha256 = $expectedParentArtifacts["agent-aghfal17-native-v17-outer-controller.py"].sha256
    supervisor_sha256 = $expectedParentArtifacts["agent-aghfal17-native-v17-supervisor.py"].sha256
    blockers = @(
        "frozen outer payload omitted checkpoint_or_certified_provenance_used",
        "frozen sealed-import supervisor payload omitted checkpoint_or_certified_provenance_used"
    )
    v18_resolution = "all eight supervisor status producers emit their own literal false and the retained-probe consumer requires exact builtins.bool false from both authoritative payloads"
}
$freeze.preserved_predecessors = [ordered]@{
    versions = @(12, 13, 14, 15, 16, 17)
    file_count = $preservedFileCount
    snapshot_encoding = "recursive_ordinal_key_sorted_compact_utf8"
    snapshot_sha256 = $preservedSnapshotSha256
    no_follow = $true
    single_link_required = $true
    retained_handles_through_generation = $true
    transformed_from_captured_bytes_only = $true
    identity_and_digest_replayed_before_and_after = $true
}
$freeze.checkpoint_evidence_contract = [ordered]@{
    key = "checkpoint_or_certified_provenance_used"
    required_type = "builtins.bool"
    required_value = $false
    outer_schema = "planora.agh-fal17.native-v18-outer-controller.v1"
    inner_schema = "planora.agh-fal17.native-v18-sealed-import-supervisor.v1"
    exact_pair_required = $true
    missing_or_non_boolean_rejected = $true
    mismatch_rejected = $true
    checkpoint_path_present = $false
    certified_incumbent_path_present = $false
}
$freeze.artifacts["derivation_record"] = [ordered]@{}
$freeze.artifacts["review_certificate"] = [ordered]@{}
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

$freezePath = Join-Path $targetRoot "agent-aghfal17-native-v18-review-freeze.json"
$freezeRows = @(
    $freeze.sealed_storage_contract.probe.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
) + @(
    $freeze.sealed_storage_contract.launch.allocations |
        Where-Object { $_.allocation_id -eq "freeze-manifest-sealed" }
)
if ($freezeRows.Count -ne 2) {
    throw "AGH v18 freeze manifest allocation rows are incomplete"
}
$finalFreezeText = $null
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $candidate = (ConvertTo-CanonicalJson $freeze) + "`n"
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
    throw "AGH v18 freeze manifest sealed-size fixed point did not converge"
}
Write-Utf8 $freezePath $finalFreezeText
$freezeHash = Get-Sha256 $freezePath

$parentInvocationsText = Get-CapturedText $script:parentCapturedByName["agent-aghfal17-native-v17-invocations.json"]
$parentInvocations = $parentInvocationsText | ConvertFrom-Json -AsHashtable
$invocationsText = Convert-Version $parentInvocationsText
foreach ($entry in $oldToNewHashes.GetEnumerator()) {
    $invocationsText = $invocationsText.Replace([string]$entry.Key, [string]$entry.Value)
}
$invocationsText = $invocationsText.Replace(
    [string]$expectedParentArtifacts["agent-aghfal17-native-v17-review-freeze.json"].sha256,
    $freezeHash
)
$invocations = $invocationsText | ConvertFrom-Json -AsHashtable
$invocations.freeze_manifest.sha256 = $freezeHash
$invocations.sealed_entry_loader_sha256 = $freeze.sealed_entry_loader.source_sha256
foreach ($mode in @("probe", "launch")) {
    $invocations[$mode].canonical_argv_sha256 = Get-CanonicalArgvSha256 $invocations[$mode].argv
}
$invocations.authorization.probe_run = $false
$invocations.authorization.official_launch = $false
$invocations.authorization.official_input_opened_by_builder = $false
$invocationsPath = Join-Path $targetRoot "agent-aghfal17-native-v18-invocations.json"
Write-Json $invocationsPath $invocations

Assert-AllPinnedInputsStillBound
Assert-PreservedPathSetUnchanged $preservedPaths

$finalFreeze = Read-Utf8 $freezePath | ConvertFrom-Json -AsHashtable
$finalInvocations = Read-Utf8 $invocationsPath | ConvertFrom-Json -AsHashtable
if ($finalFreeze.verification.probe_run_authorized -or $finalFreeze.verification.official_launch_authorized) {
    throw "AGH v18 execution authorization unexpectedly enabled"
}
if ($finalInvocations.authorization.probe_run -or $finalInvocations.authorization.official_launch) {
    throw "AGH v18 invocation authorization unexpectedly enabled"
}
if ($finalFreeze.commands.probe.canonical_argv_sha256 -eq $finalFreeze.commands.launch.canonical_argv_sha256) {
    throw "AGH v18 probe and launch inner command digests unexpectedly match"
}
if ($finalInvocations.probe.canonical_argv_sha256 -eq $finalInvocations.launch.canonical_argv_sha256) {
    throw "AGH v18 probe and launch outer command digests unexpectedly match"
}
if ($finalInvocations.freeze_manifest.sha256 -ne $freezeHash) {
    throw "AGH v18 invocation freeze pin drifted"
}
foreach ($mode in @("probe", "launch")) {
    $parentMode = $parentInvocations[$mode]
    if (@($parentMode.argv).Count -ne @($finalInvocations[$mode].argv).Count) {
        throw "AGH v18 ${mode} invocation shape changed"
    }
}

$artifactRows = [ordered]@{}
Get-ChildItem -LiteralPath $targetRoot -File | Sort-Object Name | ForEach-Object {
    $artifactRows[$_.Name] = [ordered]@{
        size_bytes = $_.Length
        sha256 = Get-Sha256 $_.FullName
    }
}
$result = [ordered]@{
    target = $targetRoot
    status = $finalFreeze.status
    builder_sha256 = $builderCapture.sha256
    preserved_v12_through_v17_file_count = $preservedFileCount
    preserved_snapshot_sha256 = $preservedSnapshotSha256
    checkpoint_evidence = $finalFreeze.checkpoint_evidence_contract
    artifacts = $artifactRows
    probe_authorized = $false
    official_launch_authorized = $false
}
Close-AllPinnedInputs
$result | ConvertTo-Json -Depth 10
