#!/usr/bin/env python3
"""Regenerate every icon asset from rkdeveloptool-gui.svg.

The outputs are committed, so builds never need an SVG renderer; run this
again after editing the SVG:

    python3 packaging/icon/render.py

Produces:
  packaging/icon/hicolor/<N>x<N>/apps/rkdeveloptool-gui.png   Linux (deb/rpm/AppImage)
  packaging/rkdeveloptool-gui.png                            AppImage top-level icon (256)
  rkdeveloptool-gui/assets/icons/rkdeveloptool-gui-<N>.png   window icon, bundled with the app
  packaging/icon/rkdeveloptool-gui.icns                      macOS .app icon (needs iconutil)
"""
import os
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SVG = os.path.join(HERE, "rkdeveloptool-gui.svg")
NAME = "rkdeveloptool-gui"

HICOLOR_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
WINDOW_SIZES = (16, 32, 48, 64, 128, 256)
# iconutil wants exactly these names in an .iconset.
ICONSET = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}


def render(renderer, size, path):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not img.save(path, "PNG"):
        sys.exit(f"failed to write {path}")


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 - QPainter needs one
    renderer = QSvgRenderer(SVG)
    if not renderer.isValid():
        sys.exit(f"cannot parse {SVG}")

    for size in HICOLOR_SIZES:
        render(renderer, size,
               os.path.join(HERE, "hicolor", f"{size}x{size}", "apps", f"{NAME}.png"))

    render(renderer, 256, os.path.join(ROOT, "packaging", f"{NAME}.png"))

    for size in WINDOW_SIZES:
        render(renderer, size,
               os.path.join(ROOT, "rkdeveloptool-gui", "assets", "icons", f"{NAME}-{size}.png"))

    icns = os.path.join(HERE, f"{NAME}.icns")
    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = os.path.join(tmp, f"{NAME}.iconset")
            os.makedirs(iconset)
            for fname, size in ICONSET.items():
                render(renderer, size, os.path.join(iconset, fname))
            subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    else:
        print("iconutil not found (macOS only); left the existing .icns untouched")

    print("icons regenerated")


if __name__ == "__main__":
    main()
