#!/bin/bash
# Build the macOS DMG: the app, an Applications link to drop it on, a
# background with first-launch instructions, and a note about Gatekeeper.
#   packaging/make-dmg.sh dist/RKDevelopTool-GUI.app dist/RKDevelopTool-GUI-arm64.dmg
set -euo pipefail
APP="$1"; DMG="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
NOTE="$HERE/dmg/如果打不开 - If it won't open.txt"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

python "$HERE/dmg/render_background.py" "$WORK"
# One TIFF with both resolutions: Finder picks the sharp one on Retina.
tiffutil -cathidpicheck "$WORK/background.png" "$WORK/background@2x.png" -out "$WORK/background.tiff"

rm -f "$DMG"
if create-dmg \
    --volname "RKDevelopTool-GUI" \
    --background "$WORK/background.tiff" \
    --window-size 660 500 \
    --icon-size 104 \
    --icon "$(basename "$APP")" 165 170 \
    --app-drop-link 495 170 \
    --add-file "$(basename "$NOTE")" "$NOTE" 330 430 \
    --hide-extension "$(basename "$APP")" \
    --no-internet-enable \
    "$DMG" "$APP"; then
  exit 0
fi

# create-dmg lays the window out through Finder, which can fail on a
# headless runner. Without the layout, still give people somewhere to drop
# the app and the instructions.
echo "create-dmg failed; building a plain DMG with the Applications link" >&2
STAGE="$WORK/stage"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/$(basename "$APP")"
ln -s /Applications "$STAGE/Applications"
cp "$NOTE" "$STAGE/"
rm -f "$DMG"
hdiutil create -volname "RKDevelopTool-GUI" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
