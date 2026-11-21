# Builds the Windows installer. Run on Windows — the sidecar must be a
# Windows executable and the NSIS/WebView2 toolchain is Windows-only.
#
# Prerequisites:
#   - Python 3.11+ on PATH
#   - Rust (stable) with the MSVC toolchain
#   - Node 20+
#   - Apple Mobile Device Support (ships with iTunes) so pymobiledevice3 can
#     reach a connected iPhone through the Apple Mobile Device service
$ErrorActionPreference = "Stop"

Write-Host "[*] Installing Python dependencies"
python -m pip install --upgrade pip
pip install pymobiledevice3 pyinstaller
pip install -e .

Write-Host "[*] Freezing the device bridge"
pyinstaller --clean --noconfirm --name fleetctl-bridge --onefile --console `
    --collect-all pymobiledevice3 --collect-all fleetctl `
    --add-data "prototype/models.json;." `
    --hidden-import pymobiledevice3.services.mobile_config `
    --hidden-import pymobiledevice3.services.diagnostics `
    --hidden-import pymobiledevice3.services.installation_proxy `
    prototype/server.py

if (-not (Test-Path "dist/fleetctl-bridge.exe")) {
    throw "PyInstaller did not produce dist/fleetctl-bridge.exe"
}

Write-Host "[*] Staging the sidecar for Tauri"
New-Item -ItemType Directory -Force -Path "src-tauri/binaries" | Out-Null
Copy-Item "dist/fleetctl-bridge.exe" "src-tauri/binaries/fleetctl-bridge-x86_64-pc-windows-msvc.exe" -Force

Write-Host "[*] Building the desktop app"
npx --yes @tauri-apps/cli@2 build --bundles nsis

Write-Host "[+] Installer: src-tauri/target/release/bundle/nsis/"
