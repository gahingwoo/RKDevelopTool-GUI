#!/usr/bin/env bash
#
# Assemble an AppDir from the Nuitka onefile build + bundled rkdeveloptool and
# package it as an AppImage. Expects:
#   dist/rkdevtoolgui     (Nuitka onefile app)
#   dist/rkdeveloptool    (bundled tool, from build-rkdeveloptool.sh)
#
set -euo pipefail

VERSION="${VERSION:-${GITHUB_REF_NAME#v}}"
[ -n "${VERSION:-}" ] || VERSION="0.0.0"

# AppImage arch string (x86_64 or aarch64); must match the host architecture.
APPIMAGE_ARCH="${APPIMAGE_ARCH:-x86_64}"

APPDIR="$PWD/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"

cp dist/rkdevtoolgui  "$APPDIR/usr/bin/rkdevtoolgui"
cp dist/rkdeveloptool "$APPDIR/usr/bin/rkdeveloptool"
chmod +x "$APPDIR/usr/bin/rkdevtoolgui" "$APPDIR/usr/bin/rkdeveloptool"

# Bundle the system libraries Qt's platform plugin needs.
#
# Nuitka's onefile payload carries PySide6's own Qt libraries and plugins, but
# not the system libraries those link against. On a bare system - such as the
# container the AppImage catalog tests submissions in - libxkbcommon-x11.so.0
# is absent, so libqxcb.so fails to load, Qt finds no usable platform plugin,
# and the app dies before showing a window:
#
#   Cannot load library .../platforms/libqxcb.so:
#     libxkbcommon-x11.so.0: cannot open shared object file
#
# Copy every dependency of the Qt libraries/plugins that AppImage's excludelist
# does not reserve for the host into usr/lib. Bundling an excludelisted library
# (libX11, libGL, libstdc++, the C library, ...) is what breaks AppImages on
# other distributions, so those are deliberately left out.
bundle_qt_libs() {
  local pyside_dir
  pyside_dir="$(python3 -c 'import PySide6, os; print(os.path.dirname(PySide6.__file__))' 2>/dev/null)" || {
    echo "==> PySide6 not importable; skipping Qt library bundling" >&2
    return 0
  }
  [ -d "$pyside_dir" ] || return 0

  local excludelist="$PWD/packaging/appimage-excludelist"
  [ -f "$excludelist" ] || { echo "==> missing $excludelist" >&2; return 1; }

  mkdir -p "$APPDIR/usr/lib"

  # Qt resolves the platform plugin plus its input-context and GL companions at
  # startup; scanning those together with the Qt libraries covers everything
  # needed to get a window on screen.
  local scan_dirs=()
  local d
  for d in "$pyside_dir/Qt/plugins/platforms" \
           "$pyside_dir/Qt/plugins/platforminputcontexts" \
           "$pyside_dir/Qt/plugins/xcbglintegrations" \
           "$pyside_dir/Qt/plugins/iconengines" \
           "$pyside_dir/Qt/plugins/imageformats" \
           "$pyside_dir/Qt/lib"; do
    [ -d "$d" ] && scan_dirs+=("$d")
  done
  if [ "${#scan_dirs[@]}" -eq 0 ]; then
    echo "==> no Qt plugin/lib directories found under $pyside_dir" >&2
    return 1
  fi

  # ldd prints "<soname> => <path> (0x...)"; keep the resolved paths that live
  # outside the PySide6 tree (its own libraries already travel in the onefile
  # payload) and that the host is not expected to provide.
  local copied=0 soname path
  while read -r soname path; do
    grep -qxF "$soname" <(awk '/^[a-zA-Z]/ {print $1}' "$excludelist") && continue
    [ -e "$APPDIR/usr/lib/$soname" ] && continue
    cp -L "$path" "$APPDIR/usr/lib/$soname"
    copied=$((copied + 1))
    echo "    + $soname"
  done < <(
    find "${scan_dirs[@]}" -name '*.so*' -type f -print0 \
      | xargs -0 -r ldd 2>/dev/null \
      | awk '$2 == "=>" && $3 ~ /^\// {print $1, $3}' \
      | grep -vF "$pyside_dir" \
      | sort -u
  )

  echo "==> Bundled $copied library/libraries into usr/lib"
  # The whole point of this step is that libqxcb.so can load, so fail loudly
  # rather than shipping an AppImage that cannot open a window.
  if [ -d "$pyside_dir/Qt/plugins/platforms" ] \
     && ! [ -e "$APPDIR/usr/lib/libxkbcommon-x11.so.0" ]; then
    echo "ERROR: libxkbcommon-x11.so.0 was not bundled; libqxcb.so will fail" >&2
    echo "       to load at runtime. Is libxkbcommon-x11-0 installed?" >&2
    return 1
  fi
}
bundle_qt_libs

cp packaging/rkdeveloptool-gui.desktop "$APPDIR/rkdeveloptool-gui.desktop"
if [ -f packaging/rkdeveloptool-gui.png ]; then
  cp packaging/rkdeveloptool-gui.png "$APPDIR/rkdeveloptool-gui.png"
else
  # appimagetool requires an icon; generate a plain placeholder if none exists.
  convert -size 256x256 xc:'#2b6cb0' "$APPDIR/rkdeveloptool-gui.png"
fi

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export APPDIR="$HERE"
# Qt's platform plugins live inside the onefile payload but link against
# libraries bundled in usr/lib (see bundle_qt_libs in make-appimage.sh); the
# loader has to be told where to find them. Keep any inherited path after ours
# so a host copy still wins for libraries we deliberately did not bundle.
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$HERE/usr/bin/rkdevtoolgui" "$@"
EOF
chmod +x "$APPDIR/AppRun"

curl -fsSL -o /tmp/appimagetool \
  "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${APPIMAGE_ARCH}.AppImage"
chmod +x /tmp/appimagetool

mkdir -p dist
# Extract-and-run avoids needing FUSE on CI runners.
export APPIMAGE_EXTRACT_AND_RUN=1
ARCH="$APPIMAGE_ARCH" /tmp/appimagetool "$APPDIR" \
  "dist/RKDevelopTool-GUI-${VERSION}-${APPIMAGE_ARCH}.AppImage"

echo "==> Built dist/RKDevelopTool-GUI-${VERSION}-${APPIMAGE_ARCH}.AppImage"
