#!/bin/bash
#
# package-macos.sh -- Build a macOS .dmg for fleetctl.
#
# Usage: ./scripts/package-macos.sh [VERSION]
#
# Requires: PyInstaller binary already built at dist/fleetctl
# Produces: dist/fleetctl-<VERSION>.dmg

set -euo pipefail

VERSION="${1:-0.0.0}"
APP_NAME="fleetctl"
BINARY="dist/${APP_NAME}"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
STAGE_DIR="build/dmg-stage"

if [ ! -f "$BINARY" ]; then
    echo "[!] Binary not found: $BINARY"
    echo "    Run 'make binary' first."
    exit 1
fi

echo "[*] Staging macOS bundle..."
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# Copy binary
cp "$BINARY" "$STAGE_DIR/${APP_NAME}"
chmod +x "$STAGE_DIR/${APP_NAME}"

# Add supporting files
cp README.md "$STAGE_DIR/" 2>/dev/null || true
cp docs/user-guide.md "$STAGE_DIR/" 2>/dev/null || true
cp docs/compliance.md "$STAGE_DIR/" 2>/dev/null || true

# Create a simple install script
cat > "$STAGE_DIR/install.sh" <<'EOF'
#!/bin/bash
# Install fleetctl to /usr/local/bin
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -m 0755 "$DIR/fleetctl" /usr/local/bin/fleetctl
echo "Installed: /usr/local/bin/fleetctl"
echo "Run: fleetctl --help"
EOF
chmod +x "$STAGE_DIR/install.sh"

echo "[*] Creating disk image: $DMG_NAME"
hdiutil create -volname "$APP_NAME $VERSION" \
    -srcfolder "$STAGE_DIR" \
    -ov -format UDZO \
    "dist/$DMG_NAME"

# Optional: codesigning (requires Developer ID + notarization)
if [ -n "${FLEETCTL_SIGN_IDENTITY:-}" ]; then
    echo "[*] Signing with identity: $FLEETCTL_SIGN_IDENTITY"
    codesign --force --sign "$FLEETCTL_SIGN_IDENTITY" --timestamp "$BINARY"
    if [ -n "${FLEETCTL_NOTARY_PROFILE:-}" ]; then
        echo "[*] Notarizing..."
        xcrun notarytool submit "dist/$DMG_NAME" \
            --keychain-profile "$FLEETCTL_NOTARY_PROFILE" --wait
    fi
else
    echo "[i] Skipping codesign (set FLEETCTL_SIGN_IDENTITY to enable)"
fi

echo "[+] DMG created: dist/$DMG_NAME"
