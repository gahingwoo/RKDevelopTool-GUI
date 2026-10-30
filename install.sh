#!/bin/sh
# Install the latest RKDevelopTool GUI:
#   curl -fsSL https://raw.githubusercontent.com/gahingwoo/RKDevelopTool-GUI/main/install.sh | sh
#
# It picks the package for the system:
# - macOS: the .app goes to /Applications (~/Applications if that isn't
#   writable). Files curl downloads aren't quarantined, so the first launch
#   isn't blocked by Gatekeeper the way a DMG opened from a browser is.
# - Debian/Ubuntu (apt) and Fedora/openSUSE (dnf/zypper): the .deb or .rpm,
#   installed with sudo; it brings the udev rule, so the board shows up
#   without sudo afterwards.
# - Any other Linux, or without sudo: the AppImage, in ~/.local/bin with a
#   launcher menu entry.
#
# The download is checked against the SHA-256 digest GitHub publishes for
# the release asset. PACKAGE=appimage|deb|rpm overrides the choice on Linux;
# INSTALL_DIR overrides where the .app or AppImage goes.
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
case "$arch" in
  x86_64|amd64) arch=x86_64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) die "no package for $os $arch; see https://github.com/$REPO/releases" ;;
esac

# Root commands: directly as root, through sudo otherwise.
if [ "$(id -u)" = 0 ]; then as_root=""; elif command -v sudo >/dev/null; then as_root="sudo"; else as_root="none"; fi

kind=${PACKAGE:-}
if [ "$os" = Darwin ]; then
  kind=dmg
elif [ "$os" = Linux ] && [ -z "$kind" ]; then
  if [ "$as_root" != none ] && command -v apt-get >/dev/null; then kind=deb
  elif [ "$as_root" != none ] && { command -v dnf >/dev/null || command -v zypper >/dev/null; }; then kind=rpm
  else kind=appimage; fi
elif [ "$os" != Linux ]; then
  die "no package for $os; see https://github.com/$REPO/releases"
fi
case "$kind/$arch" in
  dmg/arm64)         pattern='-arm64\.dmg$' ;;
  dmg/x86_64)        pattern='-x86_64\.dmg$' ;;
  appimage/x86_64)   pattern='-x86_64\.AppImage$' ;;
  appimage/arm64)    pattern='-aarch64\.AppImage$' ;;
  deb/x86_64)        pattern='_amd64\.deb$' ;;
  deb/arm64)         pattern='_arm64\.deb$' ;;
  rpm/x86_64)        pattern='\.x86_64\.rpm$' ;;
  rpm/arm64)         pattern='\.aarch64\.rpm$' ;;
  *) die "unknown PACKAGE=$kind (use appimage, deb or rpm)" ;;
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
elif [ "$kind" = deb ] || [ "$kind" = rpm ]; then
  [ "$as_root" != none ] || die "installing a .$kind needs root or sudo (PACKAGE=appimage needs neither)"
  say "Installing with the package manager (it may ask for your password)..."
  if [ "$kind" = deb ]; then
    $as_root apt-get install -y "$tmp/$name"
  elif command -v dnf >/dev/null; then
    $as_root dnf install -y "$tmp/$name"
  else
    $as_root zypper --non-interactive install --allow-unsigned-rpm "$tmp/$name"
  fi
  say "Installed. Start it from your applications menu or run: rkdeveloptool-gui"
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
