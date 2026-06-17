# Third-Party Components

The distributed packages (DMG / AppImage / deb / rpm) bundle the following
third-party software. Their licenses apply to the bundled copies.

## rkdeveloptool

- Source: https://github.com/rockchip-linux/rkdeveloptool
- License: GPL-2.0
- Bundled as a compiled binary so users do not need to install it separately.
  The corresponding source is available at the URL above; per GPL-2.0 we make
  the same version we ship obtainable on request / via that repository.

## libusb

- Source: https://github.com/libusb/libusb
- License: LGPL-2.1
- Statically linked into the bundled `rkdeveloptool` binary.

## PySide6 / Qt

- Source: https://www.qt.io / https://pypi.org/project/PySide6/
- License: LGPL-3.0 (Qt) — bundled via the Python application build.
