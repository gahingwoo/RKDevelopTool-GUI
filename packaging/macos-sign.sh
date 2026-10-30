#!/bin/bash
# Sign the macOS app or DMG.
#   packaging/macos-sign.sh app dist/RKDevelopTool-GUI.app
#   packaging/macos-sign.sh dmg dist/RKDevelopTool-GUI-arm64.dmg
#
# With a Developer ID certificate in the environment (repository secrets,
# see below) the app is signed with the hardened runtime and the DMG is
# notarized by Apple and stapled: macOS then opens it without the
# "can't be opened" prompt. Without them the app gets an ad-hoc signature,
# which only keeps the bundle's seal valid.
#
#   MACOS_CERTIFICATE_P12   base64 of the Developer ID Application .p12
#   MACOS_CERTIFICATE_PASSWORD
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD  (app-specific password,
#                                                  for notarytool)
set -euo pipefail
what="$1"; target="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"

have_identity() { [ -n "${MACOS_CERTIFICATE_P12:-}" ] && [ -n "${MACOS_CERTIFICATE_PASSWORD:-}" ]; }

import_identity() {
  # A throwaway keychain holding the certificate; returns its identity.
  local keychain="$RUNNER_TEMP/signing.keychain-db" pass
  pass="$(openssl rand -base64 24)"
  if [ ! -f "$keychain" ]; then
    echo "$MACOS_CERTIFICATE_P12" | base64 --decode > "$RUNNER_TEMP/cert.p12"
    security create-keychain -p "$pass" "$keychain"
    security set-keychain-settings -lut 3600 "$keychain"
    security unlock-keychain -p "$pass" "$keychain"
    security import "$RUNNER_TEMP/cert.p12" -k "$keychain" -P "$MACOS_CERTIFICATE_PASSWORD" \
      -T /usr/bin/codesign
    security set-key-partition-list -S apple-tool:,apple: -s -k "$pass" "$keychain" >/dev/null
    security list-keychains -d user -s "$keychain" $(security list-keychains -d user | tr -d '"')
    rm -f "$RUNNER_TEMP/cert.p12"
  fi
  security find-identity -v -p codesigning "$keychain" \
    | sed -n 's/.*"\(Developer ID Application:[^"]*\)".*/\1/p' | head -1
}

case "$what" in
  app)
    if have_identity; then
      identity="$(import_identity)"
      [ -n "$identity" ] || { echo "no Developer ID Application identity in the certificate" >&2; exit 1; }
      codesign --force --deep --timestamp --options runtime \
        --entitlements "$HERE/macos-entitlements.plist" --sign "$identity" "$target"
    else
      echo "No signing certificate configured: ad-hoc signature only" >&2
      codesign --force --deep --sign - "$target"
    fi
    codesign --verify --deep --strict "$target"
    ;;
  dmg)
    have_identity || { echo "No signing certificate configured: DMG not notarized" >&2; exit 0; }
    identity="$(import_identity)"
    codesign --force --timestamp --sign "$identity" "$target"
    xcrun notarytool submit "$target" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
      --password "$APPLE_APP_PASSWORD" --wait
    xcrun stapler staple "$target"
    spctl --assess --type open --context context:primary-signature -v "$target"
    ;;
  *) echo "usage: $0 app|dmg PATH" >&2; exit 2 ;;
esac
