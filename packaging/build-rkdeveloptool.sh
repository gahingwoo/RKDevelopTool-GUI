#!/usr/bin/env bash
#
# Build a self-contained rkdeveloptool binary (libusb linked statically) so it
# can be bundled into the macOS .app / Linux packages and the user never has to
# install it. Works on macOS and Linux; builds for the host architecture.
#
# Usage: build-rkdeveloptool.sh [output-binary-path]
#
set -euo pipefail

OUT="${1:-$PWD/dist/rkdeveloptool}"
LIBUSB_VERSION="1.0.27"
RKDEV_REPO="https://github.com/rockchip-linux/rkdeveloptool.git"

WORK="$(mktemp -d)"
PREFIX="$WORK/prefix"
mkdir -p "$PREFIX"
OS="$(uname -s)"
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"

echo "==> Building libusb ${LIBUSB_VERSION} (static) on ${OS}"
cd "$WORK"
curl -fsSL -o libusb.tar.bz2 \
  "https://github.com/libusb/libusb/releases/download/v${LIBUSB_VERSION}/libusb-${LIBUSB_VERSION}.tar.bz2"
tar xf libusb.tar.bz2
cd "libusb-${LIBUSB_VERSION}"
if [ "$OS" = "Linux" ]; then
  # --disable-udev keeps the static binary free of a libudev dependency.
  ./configure --prefix="$PREFIX" --enable-static --disable-shared --disable-udev
else
  ./configure --prefix="$PREFIX" --enable-static --disable-shared
fi
make -j"$JOBS"
make install

echo "==> Building rkdeveloptool"
cd "$WORK"
git clone --depth 1 "$RKDEV_REPO" rkdeveloptool
cd rkdeveloptool
autoreconf -i
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
if [ "$OS" = "Darwin" ]; then
  # A statically linked libusb needs these macOS frameworks at link time.
  export LIBS="-framework IOKit -framework CoreFoundation -framework Security -lobjc"
fi
./configure
make -j"$JOBS"

mkdir -p "$(dirname "$OUT")"
cp rkdeveloptool "$OUT"
strip "$OUT" 2>/dev/null || true
chmod +x "$OUT"

echo "==> Built: $OUT"
file "$OUT" || true
"$OUT" --version || true
