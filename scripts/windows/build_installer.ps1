param(
    [string]$PythonExe = "",
    [string]$IsccPath = "",
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$isWindowsHost = $false
try {
    $isWindowsHost = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows
    )
}
catch {
    $isWindowsHost = ($env:OS -eq "Windows_NT")
}

if (-not $isWindowsHost) {
    throw "This script must be run on Windows."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

function Resolve-Python {
    param(
        [string]$RequestedPython
    )

    if ($RequestedPython) {
        if (Test-Path $RequestedPython) {
            return @{
                Command = (Resolve-Path $RequestedPython).Path
                PrefixArgs = @()
            }
        }
        $cmd = Get-Command $RequestedPython -ErrorAction SilentlyContinue
        if ($cmd) {
            return @{
                Command = $cmd.Source
                PrefixArgs = @()
            }
        }
        throw "Requested Python '$RequestedPython' was not found."
    }

    $pythonCmd = Get-Command "python" -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @{
            Command = $pythonCmd.Source
            PrefixArgs = @()
        }
    }

    $pyCmd = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @{
            Command = $pyCmd.Source
            PrefixArgs = @("-3")
        }
    }

    throw "No Python interpreter found. Install Python 3.12+ or create .venv first."
}

function Invoke-Python {
    param(
        [string]$CommandPath,
        [string[]]$PrefixArgs,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )
    & $CommandPath @PrefixArgs @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $CommandPath $($PrefixArgs + $Args -join ' ')"
    }
}

function Resolve-Iscc {
    param(
        [string]$RequestedIscc
    )

    if ($RequestedIscc) {
        if (Test-Path $RequestedIscc) {
            return (Resolve-Path $RequestedIscc).Path
        }
        throw "Provided -IsccPath was not found: $RequestedIscc"
    }

    $isccCmd = Get-Command "iscc" -ErrorAction SilentlyContinue
    if ($isccCmd) {
        return $isccCmd.Source
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 5\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $regKeys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1"
    )
    foreach ($key in $regKeys) {
        if (-not (Test-Path $key)) {
            continue
        }
        try {
            $props = Get-ItemProperty -Path $key -ErrorAction Stop
            foreach ($propName in @("InstallLocation", "Inno Setup: App Path")) {
                $dir = $props.$propName
                if (-not $dir) {
                    continue
                }
                $exe = Join-Path $dir "ISCC.exe"
                if (Test-Path $exe) {
                    return $exe
                }
            }
            $uninstall = $props.UninstallString
            if ($uninstall) {
                $match = [regex]::Match([string]$uninstall, '"([^"]*\\unins\d+\.exe)"')
                if ($match.Success) {
                    $dir = Split-Path $match.Groups[1].Value -Parent
                    $exe = Join-Path $dir "ISCC.exe"
                    if (Test-Path $exe) {
                        return $exe
                    }
                }
            }
        }
        catch {
        }
    }

    return $null
}

function Resolve-AppIconData {
    $candidates = @("app_icon.png", "Logo.ico")
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return "$candidate;."
        }
    }
    throw "No application icon asset found. Expected one of: $($candidates -join ', ')"
}

$pythonCmd = ""
$pythonPrefixArgs = @()

if ($PythonExe) {
    $pythonInfo = Resolve-Python -RequestedPython $PythonExe
    $pythonCmd = $pythonInfo.Command
    $pythonPrefixArgs = @($pythonInfo.PrefixArgs)
}
else {
    $repoVenvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $repoVenvPython) {
        $pythonCmd = (Resolve-Path $repoVenvPython).Path
        $pythonPrefixArgs = @()
    }
    else {
        $bootstrap = Resolve-Python -RequestedPython ""
        $buildVenvDir = Join-Path $repoRoot ".packaging-venv"
        $buildVenvPython = Join-Path $buildVenvDir "Scripts\python.exe"
        if (-not (Test-Path $buildVenvPython)) {
            Write-Host "No .venv found. Creating isolated build env at $buildVenvDir ..."
            Invoke-Python -CommandPath $bootstrap.Command -PrefixArgs @($bootstrap.PrefixArgs) -Args @("-m", "venv", $buildVenvDir)
        }
        $pythonCmd = (Resolve-Path $buildVenvPython).Path
        $pythonPrefixArgs = @()
    }
}

Write-Host "[1/4] Installing build dependencies..."
Write-Host "Using Python: $pythonCmd $($pythonPrefixArgs -join ' ')"
Invoke-Python -CommandPath $pythonCmd -PrefixArgs @($pythonPrefixArgs) -Args @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python -CommandPath $pythonCmd -PrefixArgs @($pythonPrefixArgs) -Args @("-m", "pip", "install", "-r", "requirements-dev.txt", "pyinstaller")

if (-not $SkipTests) {
    Write-Host "[2/4] Running smoke tests..."
    Invoke-Python -CommandPath $pythonCmd -PrefixArgs @($pythonPrefixArgs) -Args @("-m", "pytest", "-q", "tests/test_ui_smoke.py", "tests/test_ui_admin_features.py")
}
else {
    Write-Host "[2/4] Skipping tests (--SkipTests)."
}

Write-Host "[3/4] Building desktop executable (PyInstaller)..."
if (Test-Path "build") {
    Remove-Item "build" -Recurse -Force
}
if (Test-Path "dist\Scheduler") {
    Remove-Item "dist\Scheduler" -Recurse -Force
}

$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--noupx",
    "--windowed",
    "--onedir",
    "--name", "Scheduler",
    "--add-data", (Resolve-AppIconData),
    "--add-data", "README.md;.",
    "--add-data", "LICENSE;.",
    "--collect-binaries", "ortools",
    "--collect-data", "ortools",
    "--hidden-import", "ortools.sat.python.cp_model_helper",
    "--hidden-import", "ortools.util.python.sorted_interval_list"
)

# Avoid pulling large unrelated packages from global environments.
$excludeModules = @(
    "pytest",
    "torch",
    "torchvision",
    "onnx",
    "onnxruntime",
    "tensorflow",
    "matplotlib",
    "IPython"
)
foreach ($mod in $excludeModules) {
    $pyinstallerArgs += @("--exclude-module", $mod)
}
$pyinstallerArgs += "ui/app.py"

Invoke-Python -CommandPath $pythonCmd -PrefixArgs @($pythonPrefixArgs) -Args $pyinstallerArgs

Write-Host "[3/4] Building dedicated solver worker executable..."
$enginePyinstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--noupx",
    "--console",
    "--onefile",
    "--name", "SchedulerEngine",
    "--collect-binaries", "ortools",
    "--collect-data", "ortools",
    "--hidden-import", "ortools.sat.python.cp_model_helper",
    "--hidden-import", "ortools.util.python.sorted_interval_list"
)
foreach ($mod in $excludeModules) {
    $enginePyinstallerArgs += @("--exclude-module", $mod)
}
$enginePyinstallerArgs += "core/engine_cli.py"
Invoke-Python -CommandPath $pythonCmd -PrefixArgs @($pythonPrefixArgs) -Args $enginePyinstallerArgs

$engineExe = Join-Path $repoRoot "dist\SchedulerEngine.exe"
$uiDistDir = Join-Path $repoRoot "dist\Scheduler"
if (Test-Path $engineExe) {
    Copy-Item -Path $engineExe -Destination (Join-Path $uiDistDir "SchedulerEngine.exe") -Force
}
else {
    throw "Expected worker executable was not produced: $engineExe"
}

if ($SkipInstaller) {
    Write-Host "[4/4] Skipping installer generation (--SkipInstaller)."
    Write-Host "Portable app folder: $repoRoot\dist\Scheduler"
    exit 0
}

Write-Host "[4/4] Building installer (.exe) with Inno Setup..."
$iscc = Resolve-Iscc -RequestedIscc $IsccPath

if (-not $iscc) {
    throw "Inno Setup compiler not found. Install Inno Setup (https://jrsoftware.org/isinfo.php), or pass -IsccPath 'C:\Path\To\ISCC.exe'."
}

& $iscc "packaging/windows/scheduler_installer.iss"

Write-Host "Installer built at: $repoRoot\dist\installer"
