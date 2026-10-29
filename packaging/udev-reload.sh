#!/bin/sh
# Run after installing or removing the package: apply the udev rule to
# Rockchip devices that are already plugged in.
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger --subsystem-match=usb --attr-match=idVendor=2207 2>/dev/null || true
fi
exit 0
