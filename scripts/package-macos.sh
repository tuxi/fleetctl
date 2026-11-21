#!/bin/bash
#
# package-macos.sh -- Build, sign and notarize a macOS .dmg for fleetctl.
#
# Usage: ./scripts/package-macos.sh [VERSION]
#
# Requires: PyInstaller binary already built at dist/fleetctl
# Produces: dist/fleetctl-<VERSION>.dmg
#
# Signing is env-gated so local builds keep working without a certificate:
#   FLEETCTL_SIGN_IDENTITY="Developer ID Application: ..."  -> codesign (hardened runtime)
#   Notarization (one of):
#     FLEETCTL_NOTARY_PROFILE                              -> notarytool keychain profile
#     APPLE_ID + APPLE_TEAM_ID + APPLE_APP_PASSWORD        -> App Store Connect password
# With no identity the DMG is left unsigned and unnotarized.

set -euo pipefail

VERSION="${1:-0.0.0}"
APP_NAME="fleetctl"
BINARY="dist/${APP_NAME}"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
DMG_PATH="dist/${DMG_NAME}"
STAGE_DIR="build/dmg-stage"
IDENTITY="${FLEETCTL_SIGN_IDENTITY:-}"
ENTITLEMENTS="scripts/macos-entitlements.plist"

if [ ! -f "$BINARY" ]; then
    echo "[!] Binary not found: $BINARY"
    echo "    Run 'make binary' first."
    exit 1
fi

# --- Sign the binary BEFORE it goes into the image ------------------- #
if [ -n "$IDENTITY" ]; then
    if ! security find-identity -v -p codesigning | grep -qF "$IDENTITY"; then
        echo "[!] Signing identity not found in keychain: $IDENTITY"
        exit 1
    fi
    echo "[*] Signing binary (hardened runtime): $IDENTITY"
    codesign --force --options runtime --timestamp \
        --entitlements "$ENTITLEMENTS" \
        --sign "$IDENTITY" "$BINARY"
    codesign --verify --strict --verbose=2 "$BINARY"
else
    echo "[i] No FLEETCTL_SIGN_IDENTITY set; building an unsigned DMG"
fi

echo "[*] Staging macOS bundle..."
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

cp "$BINARY" "$STAGE_DIR/${APP_NAME}"
chmod +x "$STAGE_DIR/${APP_NAME}"

cp README.md "$STAGE_DIR/" 2>/dev/null || true
cp docs/user-guide.md "$STAGE_DIR/" 2>/dev/null || true
cp docs/compliance.md "$STAGE_DIR/" 2>/dev/null || true

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
    "$DMG_PATH"

# --- Sign the image itself ------------------------------------------ #
if [ -n "$IDENTITY" ]; then
    echo "[*] Signing disk image"
    codesign --force --timestamp --sign "$IDENTITY" "$DMG_PATH"
    codesign --verify --strict --verbose=2 "$DMG_PATH"
fi

# --- Notarize + staple ---------------------------------------------- #
notarize() {
    local creds=()
    if [ -n "${FLEETCTL_NOTARY_PROFILE:-}" ]; then
        creds=(--keychain-profile "$FLEETCTL_NOTARY_PROFILE")
    elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && \
         [ -n "${APPLE_APP_PASSWORD:-}" ]; then
        creds=(--apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
               --password "$APPLE_APP_PASSWORD")
    else
        echo "[i] No notarization credentials; skipping notarization"
        echo "    Set FLEETCTL_NOTARY_PROFILE or APPLE_ID/APPLE_TEAM_ID/APPLE_APP_PASSWORD"
        return 0
    fi

    if [ -z "$IDENTITY" ]; then
        echo "[!] Notarization requires a signed DMG; set FLEETCTL_SIGN_IDENTITY"
        return 1
    fi

    echo "[*] Submitting to Apple notary service (this can take a few minutes)..."
    local out
    if ! out=$(xcrun notarytool submit "$DMG_PATH" "${creds[@]}" \
            --wait --output-format json); then
        echo "[!] notarytool submit failed"
        return 1
    fi

    local status
    status=$(printf '%s' "$out" | /usr/bin/python3 -c \
        'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)

    if [ "$status" != "Accepted" ]; then
        echo "$out"
        echo "[!] Notarization status: ${status:-unknown}"
        return 1
    fi

    echo "[*] Stapling notarization ticket"
    xcrun stapler staple "$DMG_PATH"
    xcrun stapler validate "$DMG_PATH"
    spctl --assess --type open --context context:primary-signature -v "$DMG_PATH"
}

notarize

echo "[+] DMG created: $DMG_PATH"
if [ -n "$IDENTITY" ]; then
    echo "[+] Signed with: $IDENTITY"
fi
