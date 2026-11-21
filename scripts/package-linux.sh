#!/bin/bash
#
# package-linux.sh -- Build and sign a Linux .AppImage for fleetctl.
#
# Usage: ./scripts/package-linux.sh [VERSION]
#
# Requires: PyInstaller binary at dist/fleetctl
# Produces: dist/fleetctl-<VERSION>-x86_64.AppImage
#
# GPG signing is env-gated:
#   LINUX_GPG_PRIVATE_KEY   base64 of an ASCII-armored private key
#   LINUX_GPG_KEY_ID        key id / fingerprint to sign with (required with a key)
#   LINUX_GPG_PASSPHRASE    key passphrase (optional)
# Produces dist/<AppImage>.asc; with no key the AppImage is left unsigned.

set -euo pipefail

VERSION="${1:-0.0.0}"
APP_NAME="fleetctl"
BINARY="dist/${APP_NAME}"
APPIMAGE="${APP_NAME}-${VERSION}-x86_64.AppImage"
APPDIR="build/${APP_NAME}.AppDir"

if [ ! -f "$BINARY" ]; then
    echo "[!] Binary not found: $BINARY"
    echo "    Run 'make binary' first."
    exit 1
fi

echo "[*] Building AppDir..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/doc/${APP_NAME}"

cp "$BINARY" "$APPDIR/usr/bin/${APP_NAME}"
chmod +x "$APPDIR/usr/bin/${APP_NAME}"
cp README.md "$APPDIR/usr/share/doc/${APP_NAME}/" 2>/dev/null || true
cp docs/user-guide.md "$APPDIR/usr/share/doc/${APP_NAME}/" 2>/dev/null || true

cat > "$APPDIR/${APP_NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=fleetctl
Comment=Cross-platform compliant device management toolkit
Exec=${APP_NAME}
Icon=${APP_NAME}
Terminal=true
Categories=Utility;System;
EOF

# Minimal icon (SVG placeholder)
cat > "$APPDIR/${APP_NAME}.svg" <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#007AFF"/>
  <text x="64" y="82" font-family="Helvetica,Arial" font-size="56" font-weight="bold"
        fill="white" text-anchor="middle">fc</text>
</svg>
EOF

cat > "$APPDIR/AppRun" <<EOF
#!/bin/bash
HERE="\$(dirname "\$(readlink -f "\${0}")")"
exec "\${HERE}/usr/bin/${APP_NAME}" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

# Download appimagetool if not present
TOOL="build/appimagetool-x86_64.AppImage"
if [ ! -f "$TOOL" ]; then
    echo "[*] Downloading appimagetool..."
    mkdir -p build
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL"
fi

echo "[*] Creating AppImage: $APPIMAGE"
ARCH=x86_64 "$TOOL" "$APPDIR" "dist/$APPIMAGE"

echo "[+] AppImage created: dist/$APPIMAGE"

# --- Optional detached GPG signature -------------------------------- #
if [ -n "${LINUX_GPG_PRIVATE_KEY:-}" ]; then
    if [ -z "${LINUX_GPG_KEY_ID:-}" ]; then
        echo "[!] LINUX_GPG_KEY_ID is required when LINUX_GPG_PRIVATE_KEY is set"
        exit 1
    fi

    export GNUPGHOME
    GNUPGHOME="$(mktemp -d)"
    trap 'rm -rf "$GNUPGHOME"' EXIT

    echo "[*] Importing GPG key..."
    printf '%s' "$LINUX_GPG_PRIVATE_KEY" | base64 -d | gpg --batch --import

    echo "[*] Signing AppImage..."
    _gpg_args=(--batch --yes --armor --detach-sign --local-user "$LINUX_GPG_KEY_ID")
    if [ -n "${LINUX_GPG_PASSPHRASE:-}" ]; then
        _gpg_args+=(--pinentry-mode loopback --passphrase "$LINUX_GPG_PASSPHRASE")
    fi
    gpg "${_gpg_args[@]}" "dist/$APPIMAGE"
    gpg --verify "dist/$APPIMAGE.asc" "dist/$APPIMAGE"

    echo "[+] Signature: dist/$APPIMAGE.asc"
else
    echo "[i] No LINUX_GPG_PRIVATE_KEY set; leaving AppImage unsigned"
fi
