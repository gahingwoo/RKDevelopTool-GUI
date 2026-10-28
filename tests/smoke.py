#!/usr/bin/env python3
"""Headless start-up smoke test, run by .github/workflows/ci.yml on every PR.

Imports the *installed* package (so missing package data shows up), then
builds the main window in every language under Qt's offscreen platform with a
stub rkdeveloptool that reports no device, runs the event loop for a few
seconds so the device worker and timers get to fire, and closes it again.

Fails on: an import error, an exception raised anywhere (including inside a
slot or a worker thread), a translation key present in one language but not
another, missing icon assets, or a compressed image that is misdetected
or does not decompress byte-for-byte, or an update check that gives the
wrong answer.

    pip install . && python tests/smoke.py
"""
import os
import stat
import sys
import tempfile
import threading
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Stub rkdeveloptool: answers every command with "no device" and exit code 0.
# Must be set before rkdeveloptool_gui.utils is imported, which resolves the
# tool path once at import time.
_tmp = tempfile.mkdtemp(prefix="rkgui-smoke-")
_stub = os.path.join(_tmp, "rkdeveloptool")
with open(_stub, "w") as f:
    f.write('#!/bin/sh\necho "not found any devices!"\nexit 0\n')
os.chmod(_stub, os.stat(_stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
os.environ["RKDEVELOPTOOL_BIN"] = _stub
# Keep the run from reading or writing the developer's real QSettings.
os.environ["XDG_CONFIG_HOME"] = _tmp
os.environ["HOME"] = _tmp
# No network in CI: the startup update check reads this (missing) file and
# fails quietly; check_updates() points it at real JSON.
os.environ["RKDEVELOPTOOL_GUI_UPDATE_URL"] = "file://" + os.path.join(_tmp, "none.json")

errors = []


def _record(exc_type, exc, tb):
    errors.append("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _record
threading.excepthook = lambda a: _record(a.exc_type, a.exc_value, a.exc_traceback)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rkdeveloptool_gui import settings as app_settings  # noqa: E402
from rkdeveloptool_gui.i18n import TRANSLATIONS  # noqa: E402
from rkdeveloptool_gui.rkdevtoolgui import (  # noqa: E402
    RKDevToolGUI, TranslationManager, load_app_icon,
)
from rkdeveloptool_gui.settings import AppSettings  # noqa: E402
from rkdeveloptool_gui.utils import RKTOOL, ToolValidator  # noqa: E402


def check_translations():
    langs = list(TRANSLATIONS)
    all_keys = set().union(*(TRANSLATIONS[l] for l in langs))
    for lang in langs:
        missing = sorted(all_keys - set(TRANSLATIONS[lang]))
        if missing:
            errors.append(f"language {lang!r} is missing keys: {missing}")


def check_updates(app):
    """Version comparison, per-platform asset choice, and the status-bar
    button, against a canned GitHub release JSON."""
    import json
    from importlib.metadata import version as dist_version

    from rkdeveloptool_gui import __version__, updater

    if dist_version("rkdeveloptool-gui") != __version__:
        errors.append(f"package metadata says {dist_version('rkdeveloptool-gui')}, "
                      f"__version__ says {__version__}")
    for newer, older in (("5.10.0", "5.9.9"), ("v6", "5.99"), ("5.4.1", "5.4")):
        if not updater.is_newer(newer, older) or updater.is_newer(older, newer):
            errors.append(f"version compare wrong for {newer} vs {older}")
    if updater.is_newer("5.4.0", "5.4") or updater.is_newer("junk", "1.0"):
        errors.append("equal or unparsable versions treated as newer")

    names = ["rkdeveloptool-gui-9.0.0-1.aarch64.rpm", "rkdeveloptool-gui-9.0.0-1.x86_64.rpm",
             "RKDevelopTool-GUI-9.0.0-aarch64.AppImage", "RKDevelopTool-GUI-9.0.0-aarch64.AppImage.zsync",
             "RKDevelopTool-GUI-9.0.0-x86_64.AppImage", "RKDevelopTool-GUI-arm64.dmg",
             "RKDevelopTool-GUI-x86_64.dmg", "rkdeveloptool-gui_9.0.0_amd64.deb",
             "rkdeveloptool-gui_9.0.0_arm64.deb"]
    assets = [{"name": n, "browser_download_url": "https://x/" + n} for n in names]
    for kind, machine, want in (("dmg", "arm64", "RKDevelopTool-GUI-arm64.dmg"),
                                ("dmg", "x86_64", "RKDevelopTool-GUI-x86_64.dmg"),
                                ("appimage", "aarch64", "RKDevelopTool-GUI-9.0.0-aarch64.AppImage"),
                                ("appimage", "x86_64", "RKDevelopTool-GUI-9.0.0-x86_64.AppImage"),
                                ("deb", "x86_64", "rkdeveloptool-gui_9.0.0_amd64.deb"),
                                ("rpm", "aarch64", "rkdeveloptool-gui-9.0.0-1.aarch64.rpm"),
                                ("pip", "x86_64", None)):
        got = updater.pick_asset(assets, kind, machine)
        if got != (want and "https://x/" + want):
            errors.append(f"pick_asset({kind}, {machine}) = {got}, want {want}")

    feed = os.path.join(_tmp, "release.json")
    old_env = os.environ["RKDEVELOPTOOL_GUI_UPDATE_URL"]
    os.environ["RKDEVELOPTOOL_GUI_UPDATE_URL"] = "file://" + feed
    try:
        for tag, expect in (("9.0.0", "available"), (__version__, "up_to_date")):
            with open(feed, "w") as f:
                json.dump({"tag_name": tag, "html_url": "https://x/page",
                           "body": "notes", "assets": assets}, f)
            got = {}
            worker = updater.UpdateCheckWorker()
            worker.available.connect(lambda r: got.update(available=r))
            worker.up_to_date.connect(lambda v: got.update(up_to_date=v))
            worker.failed.connect(lambda e: got.update(failed=e))
            worker.run()
            if list(got) != [expect]:
                errors.append(f"update check for release {tag}: {got}, want {expect}")

        window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                              settings=AppSettings())
        try:
            if window.update_button.text() != f"v{__version__}":
                errors.append(f"status bar shows {window.update_button.text()!r}")
            window._on_update_available(
                {"version": "9.0.0", "page": "https://x/page", "download": None,
                 "notes": ""}, manual=False)
            if "9.0.0" not in window.update_button.text():
                errors.append(f"update not shown in status bar: {window.update_button.text()!r}")
        finally:
            window.cleanup()
            window.deleteLater()
            app.processEvents()
    finally:
        os.environ["RKDEVELOPTOOL_GUI_UPDATE_URL"] = old_env
def check_decompression():
    """Compressed images are recognised and unpack byte-for-byte; a truncated
    one fails cleanly instead of leaving a partial image to be flashed."""
    import bz2
    import gzip
    import lzma
    import zipfile

    from rkdeveloptool_gui.utils import decompressed_name, detect_compression
    from rkdeveloptool_gui.workers import DecompressWorker

    work = tempfile.mkdtemp(dir=_tmp)
    # Protective-MBR-like start plus incompressible data, ~3 MiB so the
    # worker runs more than one read.
    image = b"\0" * 446 + b"\x00\xee" + b"\0" * 62 + b"\x55\xaa" + os.urandom(3 << 20)
    raw = os.path.join(work, "board.img")
    with open(raw, "wb") as f:
        f.write(image)
    if detect_compression(raw) is not None:
        errors.append("a raw image was detected as compressed")

    for kind, ext, compress in (("xz", ".xz", lzma.compress),
                                ("gzip", ".gz", gzip.compress),
                                ("bzip2", ".bz2", bz2.compress)):
        src = raw + ext
        with open(src, "wb") as f:
            f.write(compress(image))
        if detect_compression(src) != kind:
            errors.append(f"{src} detected as {detect_compression(src)!r}, not {kind!r}")
        if decompressed_name(src) != "board.img":
            errors.append(f"decompressed_name({src!r}) = {decompressed_name(src)!r}")

        dest = os.path.join(work, f"out-{kind}.img")
        result = {}
        worker = DecompressWorker(src, kind, dest)
        worker.finished.connect(lambda p: result.update(ok=p))
        worker.failed.connect(lambda k, m: result.update(failed=(k, m)))
        worker.run()  # synchronously, on this thread
        if result.get("ok") != dest:
            errors.append(f"{kind}: decompression did not finish: {result}")
            continue
        with open(dest, "rb") as f:
            if f.read() != image:
                errors.append(f"{kind}: decompressed bytes differ from the original")

        truncated = src + ".part"
        with open(src, "rb") as f, open(truncated, "wb") as out:
            out.write(f.read()[: os.path.getsize(src) // 2])
        bad_dest = dest + ".bad"
        result = {}
        worker = DecompressWorker(truncated, kind, bad_dest)
        worker.finished.connect(lambda p: result.update(ok=p))
        worker.failed.connect(lambda k, m: result.update(failed=(k, m)))
        worker.run()
        if result.get("failed", ("",))[0] != "corrupt":
            errors.append(f"{kind}: truncated input gave {result}, not a 'corrupt' failure")
        if os.path.exists(bad_dest):
            errors.append(f"{kind}: a partial image was left behind after failure")

    zst = os.path.join(work, "board.img.zst")
    with open(zst, "wb") as f:
        f.write(b"\x28\xb5\x2f\xfd" + b"\0" * 16)
    zp = os.path.join(work, "board.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("board.img", b"x")
    for path, kind in ((zst, "zstd"), (zp, "zip")):
        if detect_compression(path) != kind:
            errors.append(f"{path} detected as {detect_compression(path)!r}, not {kind!r}")


def check_burn_flow(app):
    """Drive one-click burn with an .img.xz: the command must name the
    decompressed copy, and the copy must be gone once the command ends. A
    .zst must be refused, never written raw."""
    import lzma

    from rkdeveloptool_gui import operations

    work = tempfile.mkdtemp(dir=_tmp)
    image = b"\0" * 510 + b"\x55\xaa" + os.urandom(1 << 20)
    src = os.path.join(work, "board.img.xz")
    with open(src, "wb") as f:
        f.write(lzma.compress(image))
    zst = os.path.join(work, "board.img.zst")
    with open(zst, "wb") as f:
        f.write(b"\x28\xb5\x2f\xfd" + b"\0" * 16)

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    seen = {}
    real_confirm, real_message = operations._burn_with_confirm, operations._show_rkfw_message

    def fake_confirm(gui, path, address, on_confirm, on_cancel=None):
        with open(path, "rb") as f:
            seen["content_ok"] = f.read() == image
        on_confirm()

    def fake_run(cmd, key, callback=None):
        seen["cmd"] = cmd
        seen["tmp_dir"] = os.path.dirname(cmd[-1])
        if callback:
            callback(True, "")
        app.quit()

    operations._burn_with_confirm = fake_confirm
    operations._show_rkfw_message = lambda gui, title, text, icon="Critical": seen.update(refused=text)
    window.run_command = fake_run
    try:
        window.firmware_path.setText(src)
        operations.onekey_burn(window)
        QTimer.singleShot(15000, app.quit)  # don't hang CI if it never finishes
        app.exec()

        cmd = seen.get("cmd")
        if not cmd or cmd[1:3] != ["wl", "0x0"] or not cmd[3].endswith("board.img"):
            errors.append(f"one-click burn of an .img.xz ran {cmd!r}")
        if not seen.get("content_ok"):
            errors.append("the image handed to the burn was not the decompressed original")
        if seen.get("tmp_dir") and os.path.exists(seen["tmp_dir"]):
            errors.append("the decompressed copy was not deleted after the burn")

        seen.pop("cmd", None)
        window.firmware_path.setText(zst)
        operations.onekey_burn(window)
        if "cmd" in seen or "refused" not in seen:
            errors.append("a .zst image was not refused")
    finally:
        operations._burn_with_confirm, operations._show_rkfw_message = real_confirm, real_message
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def run_window(app, lang):
    settings = AppSettings()
    manager = TranslationManager(lang=lang, settings=settings)
    window = RKDevToolGUI(manager, settings=settings)
    window.show()
    QTimer.singleShot(3000, window.close)
    QTimer.singleShot(3500, app.quit)
    app.exec()
    window.cleanup()
    window.deleteLater()
    app.processEvents()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName(app_settings.ORGANIZATION)
    app.setApplicationName(app_settings.APPLICATION)

    if RKTOOL != _stub:
        errors.append(f"rkdeveloptool resolved to {RKTOOL!r}, not the stub")
    if not ToolValidator.validate():
        errors.append("ToolValidator rejected the stub rkdeveloptool")
    if load_app_icon().isNull():
        errors.append("app icon is empty: assets/icons missing from the installed package")

    check_translations()
    check_updates(app)
    check_decompression()
    check_burn_flow(app)
    for lang in TRANSLATIONS:
        print(f"--- starting main window, language={lang}", flush=True)
        run_window(app, lang)

    if errors:
        print(f"\nSMOKE TEST FAILED ({len(errors)} problem(s)):")
        for e in errors:
            print(" *", e)
        return 1
    print("\nsmoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
