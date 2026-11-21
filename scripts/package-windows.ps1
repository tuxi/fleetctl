# package-windows.ps1 -- Build and sign a Windows .msi for fleetctl.
#
# Usage: powershell -File scripts/package-windows.ps1 -Version 0.4.0
#
# Requires: PyInstaller binary at dist\fleetctl.exe, WiX Toolset (candle/light) OR
#           fallback to a simple zip if WiX is not available.
#
# Authenticode signing is env-gated:
#   WINDOWS_CERT_PFX_BASE64   base64 of the .pfx code-signing certificate
#   WINDOWS_CERT_PASSWORD     password for the .pfx (optional)
# With neither set the artifacts are left unsigned (local development only).

param(
    [string]$Version = "0.0.0"
)

$ErrorActionPreference = "Stop"
$AppName = "fleetctl"
$Binary = "dist\$AppName.exe"
$MsiName = "$AppName-$Version.msi"

if (-not (Test-Path $Binary)) {
    Write-Host "[!] Binary not found: $Binary"
    Write-Host "    Run 'make binary' first."
    exit 1
}

# ---------------------------------------------------------------- #
# Signing helpers                                                   #
# ---------------------------------------------------------------- #

function Resolve-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kits) {
        $found = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                 Where-Object { $_.FullName -match '\\x64\\' } |
                 Sort-Object FullName -Descending |
                 Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

$script:SignTool = Resolve-SignTool
$script:PfxPath = $null

function Get-SigningPfx {
    if ($script:PfxPath) { return $script:PfxPath }
    if (-not $env:WINDOWS_CERT_PFX_BASE64) { return $null }
    $path = Join-Path (Get-Location) "build\codesign.pfx"
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    [IO.File]::WriteAllBytes($path, [Convert]::FromBase64String($env:WINDOWS_CERT_PFX_BASE64))
    $script:PfxPath = $path
    return $path
}

function Sign-Artifact([string]$Path) {
    $pfx = Get-SigningPfx
    if (-not $pfx) {
        Write-Host "[i] WINDOWS_CERT_PFX_BASE64 not set; leaving $Path unsigned"
        return
    }
    if (-not $script:SignTool) {
        throw "signtool.exe not found; install the Windows SDK"
    }
    $signArgs = @("sign", "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256", "/f", $pfx)
    if ($env:WINDOWS_CERT_PASSWORD) { $signArgs += @("/p", $env:WINDOWS_CERT_PASSWORD) }
    $signArgs += $Path
    & $script:SignTool @signArgs
    if ($LASTEXITCODE -ne 0) { throw "signtool sign failed for $Path" }

    & $script:SignTool verify /pa $Path
    if ($LASTEXITCODE -ne 0) { throw "signtool verify failed for $Path" }
    Write-Host "[+] Signed: $Path"
}

# ---------------------------------------------------------------- #
# Build                                                             #
# ---------------------------------------------------------------- #

Write-Host "[*] Staging Windows bundle..."
$Stage = "build\msi-stage"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Path $Stage | Out-Null

Copy-Item $Binary "$Stage\$AppName.exe"
if (Test-Path "README.md") { Copy-Item "README.md" $Stage }
if (Test-Path "docs\user-guide.md") { Copy-Item "docs\user-guide.md" $Stage }

# Sign the executable first so the MSI embeds a signed binary.
Sign-Artifact "$Stage\$AppName.exe"

# Generate WiX source if WiX is available
$wxsPath = "build\fleetctl.wxs"
@"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="fleetctl" Language="1033" Version="$Version"
           Manufacturer="fleetctl" UpgradeCode="B2F4A6E0-1C3D-4E5F-9A7B-8C0D1E2F3A4B">
    <Package InstallerVersion="200" Compressed="yes" InstallScope="perMachine" />
    <MajorUpgrade DowngradeErrorMessage="A newer version is already installed." />
    <MediaTemplate EmbedCab="yes" />
    <Feature Id="Main">
      <ComponentGroupRef Id="ProductComponents" />
      <ComponentRef Id="PathComponent" />
    </Feature>
  </Product>
  <Fragment>
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="INSTALLFOLDER" Name="fleetctl" />
      </Directory>
    </Directory>
  </Fragment>
  <Fragment>
    <ComponentGroup Id="ProductComponents" Directory="INSTALLFOLDER">
      <Component Id="FleetctlExe">
        <File Id="FleetctlExe" Source="$Stage\$AppName.exe" KeyPath="yes" />
      </Component>
    </ComponentGroup>
  </Fragment>
  <Fragment>
    <Component Id="PathComponent" Directory="INSTALLFOLDER" Guid="*">
      <Environment Id="PATH" Name="PATH" Value="[INSTALLFOLDER]" Permanent="no"
                   Part="last" Action="set" System="yes" />
    </Component>
  </Fragment>
</Wix>
"@ | Out-File -Encoding UTF8 $wxsPath

if (Get-Command candle.exe -ErrorAction SilentlyContinue) {
    if (-not (Test-Path "dist")) { New-Item -ItemType Directory -Path "dist" | Out-Null }
    Write-Host "[*] Building MSI with WiX..."
    candle.exe -nologo -out "build\fleetctl.wixobj" $wxsPath
    light.exe -nologo -out "dist\$MsiName" "build\fleetctl.wixobj"
    Sign-Artifact "dist\$MsiName"
    Write-Host "[+] MSI created: dist\$MsiName"
} else {
    Write-Host "[!] WiX Toolset not found (candle.exe)."
    Write-Host "    Falling back to ZIP archive..."
    $Zip = "dist\$AppName-$Version-win64.zip"
    if (-not (Test-Path "dist")) { New-Item -ItemType Directory -Path "dist" | Out-Null }
    Compress-Archive -Path "$Stage\*" -DestinationPath $Zip -Force
    Write-Host "[+] ZIP created: $Zip (not Authenticode-signed; install WiX for a real .msi)"
}

if ($script:PfxPath) {
    Remove-Item $script:PfxPath -Force -ErrorAction SilentlyContinue
}
