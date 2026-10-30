#!/bin/sh
# Install the latest RKDevelopTool GUI:
#   curl -fsSL https://raw.githubusercontent.com/gahingwoo/RKDevelopTool-GUI/main/install.sh | sh
#
# macOS: the .app goes to /Applications (~/Applications if that isn't
# writable). Files curl downloads aren't quarantined, so the first launch
# isn't blocked by Gatekeeper the way a DMG opened from a browser is.
# Linux: the AppImage goes to ~/.local/bin, with a launcher menu entry.
#
# The download is checked against the SHA-256 digest GitHub publishes for
# the release asset. INSTALL_DIR overrides where it goes.
set -eu

REPO="gahingwoo/RKDevelopTool-GUI"
API="https://api.github.com/repos/$REPO/releases/latest"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || die "curl is needed"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

os=$(uname -s)
arch=$(uname -m)
case "$os/$arch" in
  Darwin/arm64)          pattern='-arm64\.dmg$' ;;
  Darwin/x86_64)         pattern='-x86_64\.dmg$' ;;
  Linux/x86_64)          pattern='-x86_64\.AppImage$' ;;
  Linux/aarch64|Linux/arm64) pattern='-aarch64\.AppImage$' ;;
  *) die "no package for $os $arch; see https://github.com/$REPO/releases" ;;
esac

say "Looking up the latest release..."
curl -fsSL -H "Accept: application/vnd.github+json" "$API" -o "$tmp/release.json" \
  || die "couldn't reach GitHub"

# One field per line, then pick the asset whose name matches; its digest and
# download URL follow its name in GitHub's JSON.
tr ',{}' '\n\n\n' < "$tmp/release.json" | sed 's/^ *//' > "$tmp/fields"
tag=$(sed -n 's/^"tag_name": *"\([^"]*\)".*/\1/p' "$tmp/fields" | head -1)
name=$(sed -n 's/^"name": *"\([^"]*\)".*/\1/p' "$tmp/fields" | grep -E -e "$pattern" | head -1)
[ -n "$name" ] || die "release $tag has no package for $os $arch"
digest=$(awk -v n="\"name\": \"$name\"" '$0 == n {hit=1} hit && /^"digest":/ {print; exit}' "$tmp/fields" \
  | sed 's/.*"sha256:\([0-9a-f]*\)".*/\1/')
url=$(awk -v n="\"name\": \"$name\"" '$0 == n {hit=1} hit && /^"browser_download_url":/ {print; exit}' "$tmp/fields" \
  | sed 's/^"browser_download_url": *"\([^"]*\)".*/\1/')
[ -n "$url" ] || die "couldn't find the download link for $name"
[ "${#digest}" -eq 64 ] || die "release $tag publishes no checksum for $name"

say "Downloading $name ($tag)..."
curl -fL --progress-bar "$url" -o "$tmp/$name" || die "download failed"
if command -v sha256sum >/dev/null; then
  got=$(sha256sum "$tmp/$name" | cut -d' ' -f1)
else
  got=$(shasum -a 256 "$tmp/$name" | cut -d' ' -f1)
fi
[ "$got" = "$digest" ] || die "checksum mismatch: the download isn't the published file"
say "Checksum OK."

if [ "$os" = Darwin ]; then
  dest=${INSTALL_DIR:-/Applications}
  if [ ! -w "$dest" ]; then
    dest="$HOME/Applications"
    mkdir -p "$dest"
  fi
  mnt="$tmp/mnt"
  mkdir "$mnt"
  hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$mnt" "$tmp/$name" >/dev/null
  app=$(cd "$mnt" && ls -d *.app | head -1)
  rm -rf "$dest/$app"
  ditto "$mnt/$app" "$dest/$app"
  hdiutil detach -quiet "$mnt"
  xattr -dr com.apple.quarantine "$dest/$app" 2>/dev/null || true
  say "Installed $dest/$app"
  [ -n "${NO_LAUNCH:-}" ] || open "$dest/$app"
else
  dest=${INSTALL_DIR:-$HOME/.local/bin}
  mkdir -p "$dest"
  install -m 755 "$tmp/$name" "$dest/rkdeveloptool-gui.AppImage"
  apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$apps"
  cat > "$apps/rkdeveloptool-gui.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=RKDevelopTool GUI
Comment=Flash Rockchip boards with rkdeveloptool
Exec=$dest/rkdeveloptool-gui.AppImage
Categories=Development;Utility;
Terminal=false
DESKTOP
  say "Installed $dest/rkdeveloptool-gui.AppImage (also in your applications menu)."
  say "If the board isn't found without sudo, the app shows the one-line udev command to fix it."
  command -v fusermount >/dev/null 2>&1 || say "Note: AppImages need FUSE 2 (e.g. sudo apt install libfuse2)."
fi
