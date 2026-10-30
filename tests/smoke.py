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
wrong answer, or settings / manual commands that don't take effect.

    pip install . && python tests/smoke.py
"""
import os
import stat
import sys
import tempfile
import threading
import time
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
# Keep the run from reading or writing the developer's real settings. $HOME
# alone isn't enough: macOS's native store ignores it.
os.environ["RKDEVELOPTOOL_GUI_SETTINGS"] = os.path.join(_tmp, "settings.ini")
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

    # Errors map to a reason the dialog can explain.
    import ssl
    import urllib.error
    cert = urllib.error.URLError(ssl.SSLCertVerificationError(1, "unable to get local issuer"))
    for err, want in ((cert, "cert"),
                      (urllib.error.HTTPError("u", 403, "rate", {}, None), "rate_limit"),
                      (urllib.error.URLError("nodename nor servname"), "offline"),
                      (ValueError("bad tag"), "other")):
        if updater.describe_error(err) != want:
            errors.append(f"describe_error({err!r}) = {updater.describe_error(err)}, want {want}")

    # A certificate failure with the default trust store (python.org's macOS
    # Python before "Install Certificates") retries with a CA bundle.
    import urllib.request
    real_urlopen, calls = urllib.request.urlopen, []

    def fake_urlopen(request, timeout=None, context=None):
        calls.append(context)
        if context is None:
            raise cert
        return "opened"

    urllib.request.urlopen = fake_urlopen
    try:
        got = updater._open(urllib.request.Request("https://example.invalid"))
    finally:
        urllib.request.urlopen = real_urlopen
    if got != "opened" or calls[0] is not None or calls[-1] is None:
        errors.append(f"no CA-bundle retry after a certificate error: {got!r}, {calls}")

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
            worker.failed.connect(lambda k, e: got.update(failed=(k, e)))
            worker.run()
            if list(got) != [expect]:
                errors.append(f"update check for release {tag}: {got}, want {expect}")

        window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                              settings=AppSettings())
        try:
            if not window.update_button.text().startswith(f"v{__version__} · "):
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

    def fake_confirm(gui, path, address, on_confirm, on_cancel=None, **kwargs):
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
    operations._show_rkfw_message = lambda gui, title, text, icon="Critical", **_: seen.update(refused=text)
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


def check_linux_usb_access(app):
    """Detecting a Rockchip device the user can't open, and the udev rule."""
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import utils

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "packaging", "70-rkdeveloptool-gui.rules")) as f:
        rules = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if rules != [utils.UDEV_RULE]:
        errors.append(f"packaged udev rule {rules} differs from utils.UDEV_RULE")
    if utils.UDEV_RULE not in utils.udev_fix_command():
        errors.append("udev_fix_command doesn't install UDEV_RULE")

    sysfs = tempfile.mkdtemp(dir=_tmp)
    devfs = tempfile.mkdtemp(dir=_tmp)
    for name, vendor, dev in (("1-1", "2207", 5), ("1-2", "05ac", 6)):
        os.makedirs(os.path.join(sysfs, name))
        for key, value in (("idVendor", vendor), ("busnum", "1"), ("devnum", str(dev))):
            with open(os.path.join(sysfs, name, key), "w") as f:
                f.write(value + "\n")
        os.makedirs(os.path.join(devfs, "001"), exist_ok=True)
        node = os.path.join(devfs, "001", f"{dev:03d}")
        open(node, "w").close()
        os.chmod(node, 0)
    rockchip = os.path.join(devfs, "001", "005")
    check = lambda **k: utils.inaccessible_rockchip_usb(sysfs, devfs, **k)
    if os.geteuid() != 0:  # root can open anything
        if check(linux=True) != [rockchip]:
            errors.append(f"blocked Rockchip node not reported (other vendors ignored): {check(linux=True)}")
    if check(linux=False):
        errors.append("USB access reported as a problem off Linux")
    os.chmod(rockchip, 0o600)
    if check(linux=True):
        errors.append("an accessible Rockchip node was reported")

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    shown = []
    real = (utils.inaccessible_rockchip_usb, QMessageBox.exec)
    utils.inaccessible_rockchip_usb = lambda: ["/dev/bus/usb/001/005"]
    QMessageBox.exec = lambda self: shown.append(self.text()) or 0
    try:
        window.on_device_lost()
        window.on_device_lost()
    finally:
        utils.inaccessible_rockchip_usb, QMessageBox.exec = real
        window.cleanup()
        window.deleteLater()
        app.processEvents()
    if len(shown) != 1 or "/dev/bus/usb/001/005" not in shown[0]:
        errors.append(f"USB permission hint shown {len(shown)} times (want once, naming the node)")
def check_settings_and_command_line(app):
    """Settings dialog wiring and the manual command line."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QMessageBox

    from rkdeveloptool_gui import operations, utils, workers
    from rkdeveloptool_gui import settings as app_settings

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    ran = []
    window.run_command = lambda cmd, key, callback=None: ran.append(cmd)
    real_warning = QMessageBox.warning
    answers = []
    QMessageBox.warning = staticmethod(lambda *a, **k: answers.pop(0))
    try:
        window.open_settings()
        if window.tab_widget.currentWidget() is not window.settings_page:
            errors.append("open_settings() didn't switch to the Settings tab")
        dialog = window.settings_page

        # Appearance pickers mirror the status-bar ones, both ways.
        theme = dialog.findChildren(type(window.theme_combo))
        target = next(c for c in theme if c.count() == window.theme_combo.count()
                      and c.itemData(0) == window.theme_combo.itemData(0))
        new_index = (window.theme_combo.currentIndex() + 1) % window.theme_combo.count()
        target.setCurrentIndex(new_index)
        if window.theme_combo.currentIndex() != new_index:
            errors.append("settings theme picker didn't change the status-bar one")
        back = (new_index + 1) % window.theme_combo.count()
        window.theme_combo.setCurrentIndex(back)
        if target.currentIndex() != back:
            errors.append("status-bar theme picker didn't update the Settings tab")

        # rkdeveloptool path: invalid is refused, a valid one switches every module.
        before = utils.RKTOOL
        dialog.tool_path.setText(os.path.join(_tmp, "does-not-exist"))
        dialog._apply_tool_path()
        if utils.RKTOOL != before:
            errors.append("an invalid rkdeveloptool path was applied")
        other = os.path.join(_tmp, "rkdeveloptool-other")
        with open(other, "w") as f:
            f.write('#!/bin/sh\necho "rkdeveloptool ver 9.9"\n')
        os.chmod(other, 0o755)
        dialog.tool_path.setText(other)
        dialog._apply_tool_path()
        if not (utils.RKTOOL == operations.RKTOOL == workers.RKTOOL == other):
            errors.append(f"rkdeveloptool not switched everywhere: {utils.RKTOOL}, "
                          f"{operations.RKTOOL}, {workers.RKTOOL}")
        if "9.9" not in dialog.tool_status.text():
            errors.append(f"tool status doesn't show the version: {dialog.tool_status.text()!r}")
        dialog._reset_tool()
        if utils.RKTOOL != _stub:
            errors.append(f"auto-detect didn't restore the stub: {utils.RKTOOL}")

        # Unpack location.
        image = os.path.join(tempfile.mkdtemp(dir=_tmp), "board.img.xz")
        custom = tempfile.mkdtemp(dir=_tmp)
        for mode, want_parent in (("beside", os.path.dirname(image)),
                                  ("temp", tempfile.gettempdir()), ("custom", custom)):
            window.settings.set(app_settings.KEY_UNPACK_MODE, mode)
            window.settings.set(app_settings.KEY_UNPACK_DIR, custom)
            got = operations._make_unpack_dir(window, image)
            if os.path.realpath(os.path.dirname(got)) != os.path.realpath(want_parent):
                errors.append(f"unpack mode {mode}: {got}, want under {want_parent}")
        window.settings.set(app_settings.KEY_UNPACK_MODE, "beside")

        # Font sizes apply at once to every kind of text, and are kept.
        dialog.ui_font.setValue(15)
        dialog.log_font.setValue(13)
        app.processEvents()
        sizes = {
            "app": QApplication.font().pointSize(),
            "label": window.device_status_label.font().pointSize(),
            "table": window.partition_table.font().pointSize(),
            "log": window.log_output.font().pointSize(),
            "command": window.equiv_command_field.font().pointSize(),
        }
        if sizes != {"app": 15, "label": 15, "table": 15, "log": 13, "command": 13}:
            errors.append(f"font sizes not applied everywhere: {sizes}")
        reopened = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                                settings=AppSettings())
        if (QApplication.font().pointSize(), reopened.log_output.font().pointSize()) != (15, 13):
            errors.append("font sizes not restored in a new window")
        reopened.cleanup()
        reopened.deleteLater()
        # Slider and number box stay in step; a drag only shows the number
        # until the slider is released.
        control = dialog.ui_font
        control.slider.sliderMoved.emit(19)
        if control.spin.value() != 19 or QApplication.font().pointSize() != 15:
            errors.append("dragging the slider should show 19 without applying it yet")
        control.slider.setValue(19)  # release
        app.processEvents()
        if QApplication.font().pointSize() != 19:
            errors.append("releasing the slider didn't apply the size")
        control.spin.setValue(12)  # typed
        app.processEvents()
        if control.slider.value() != 12 or QApplication.font().pointSize() != 12:
            errors.append("typing a size didn't move the slider and apply it")

        dialog._reset_fonts()
        app.processEvents()
        if (QApplication.font().pointSize(), window.log_output.font().pointSize()) != \
                (app_settings.DEFAULT_UI_FONT_SIZE, app_settings.DEFAULT_LOG_FONT_SIZE):
            errors.append("Reset text sizes didn't restore the defaults")

        # A language switch rebuilds the tab in the new language; the old
        # page's mirror connections must go with it.
        old_page = window.settings_page
        window.lang_combo.setCurrentIndex(window.lang_combo.findData("zh"))
        app.processEvents()
        app.processEvents()
        if window.settings_page is old_page:
            errors.append("Settings tab not rebuilt after a language switch")
        window.theme_combo.setCurrentIndex(0)
        window.enable_debug_log.setChecked(not window.enable_debug_log.isChecked())
        window.loader_path.setText("/tmp/x.bin")
        app.processEvents()
        window.lang_combo.setCurrentIndex(window.lang_combo.findData("en"))
        app.processEvents()

        # Command line.
        parse = window.parse_manual_command
        for text, want in (("ld", ["ld"]), ("rkdeveloptool rci", ["rci"]),
                           (f"{_stub} wl 0x0 'my image.img'", ["wl", "0x0", "my image.img"]),
                           ("ld; rm -rf /", ["ld;", "rm", "-rf", "/"]),
                           ('rl 0 "unterminated', None), ("rkdeveloptool", None), ("", None)):
            if parse(text) != want:
                errors.append(f"parse_manual_command({text!r}) = {parse(text)}, want {want}")

        field = window.equiv_command_field
        field.setText("rci")
        window.run_manual_command()
        answers.append(QMessageBox.StandardButton.No)
        field.setText("ef")
        window.run_manual_command()
        answers.append(QMessageBox.StandardButton.Yes)
        field.setText("rkdeveloptool ef")
        window.run_manual_command()
        if ran != [[utils.RKTOOL, "rci"], [utils.RKTOOL, "ef"]]:
            errors.append(f"manual commands ran {ran}; 'ef' must need a Yes first")

        field.clear()
        for _ in range(2):
            app.sendEvent(field, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up,
                                           Qt.KeyboardModifier.NoModifier))
        if field.text() != "rci":
            errors.append(f"Up twice in the command line gave {field.text()!r}, not 'rci'")
    finally:
        QMessageBox.warning = real_warning
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_native_macos_style(app):
    """Under the macOS style the app uses the style's palette and passes the
    theme on as a color scheme (a custom palette clashes with AppKit-drawn
    widgets). Only runs where that style exists."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QStyleFactory

    if "macOS" not in QStyleFactory.keys():
        return
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    try:
        from rkdeveloptool_gui.themes import create_dark_palette
        custom = create_dark_palette().color(QPalette.ColorRole.Window)
        window.theme_manager.apply_theme(theme="dark", style="macOS")
        if app.palette().color(QPalette.ColorRole.Window) == custom:
            errors.append("macOS style still uses the custom dark palette")
        # Only a real Cocoa session reports the scheme back (offscreen doesn't).
        hints = app.styleHints()
        if app.platformName() == "cocoa" and hasattr(hints, "colorScheme") \
                and hints.colorScheme() != Qt.ColorScheme.Dark:
            errors.append(f"dark theme under macOS style gave color scheme {hints.colorScheme()}")
        window.theme_manager.apply_theme(theme="light", style="Fusion")
        if app.palette().color(app.palette().ColorRole.Window).lightness() < 200:
            errors.append("Fusion light theme lost its custom light palette")
    finally:
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def _window_rect(window, widget):
    from PySide6.QtCore import QRect
    return QRect(widget.mapTo(window, widget.rect().topLeft()), widget.size())


def check_layout(app):
    """The tab area is sized by the current tab (QTabWidget asks for the
    tallest one by default, which pushed the log down and squeezed its
    progress row onto it), and the progress row never overlaps the log."""
    from PySide6.QtWidgets import QScrollArea

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    try:
        window.resize(1300, 720)
        window.show()
        tabs = window.tab_widget
        right_area = next(area for area in window.findChildren(QScrollArea)
                          if area.isAncestorOf(window.log_output))
        if right_area.isAncestorOf(window.progress_bar):
            errors.append("the progress row scrolls with the panel")
        tallest = max(tabs.widget(i).sizeHint().height() for i in range(tabs.count()))
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            for _ in range(10):
                app.processEvents()
            page = tabs.currentWidget()
            if page.sizeHint().height() < tallest - 50 and \
                    tabs.sizeHint().height() >= tallest:
                errors.append(f"tab {tabs.tabText(i)!r} asks for the tallest tab's height")
            area = _window_rect(window, right_area)
            bar = _window_rect(window, window.progress_bar)
            if bar.top() <= area.bottom():
                errors.append(f"tab {tabs.tabText(i)!r}: progress row overlaps the log")
        # A window too short for the tab plus the log scrolls the right panel,
        # but the progress row sits outside the scroll area and stays in view.
        window.resize(1300, 420)
        for _ in range(10):
            app.processEvents()
        bar = _window_rect(window, window.progress_bar)
        if not window.progress_bar.isVisible() or bar.bottom() > window.height() \
                or bar.height() <= 0:
            errors.append(f"progress row out of view in a short window: {bar}")
    finally:
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_drag_and_drop(app):
    """Files dropped on the window go where they belong, with format checks."""
    import lzma
    import shlex

    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QLineEdit, QMessageBox, QScrollArea

    from rkdeveloptool_gui import operations, utils
    from rkdeveloptool_gui import settings as app_settings

    work = tempfile.mkdtemp(dir=_tmp)

    def make(name, data):
        path = os.path.join(work, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    mbr = b"\0" * 510 + b"\x55\xaa" + b"\0" * 512
    files = {
        "loader": make("rk3588_spl_loader_v1.16.bin", b"BOOT" + b"\0" * 600),
        "loader_ldr": make("idbloader_ldr.bin", b"LDR " + b"\0" * 600),
        "rkfw": make("update.img", b"RKFW" + b"\0" * 600),
        "compressed": make("Armbian.img.xz", lzma.compress(mbr)),
        "disk": make("disk.img", mbr),
        "gpt": make("gpt.img", b"\0" * 512 + b"EFI PART" + b"\0" * 504),
        "other": make("boot.img", b"ANDROID!" + b"\0" * 600),
    }
    want_kind = {"loader": "loader", "loader_ldr": "loader", "rkfw": "rkfw",
                 "compressed": "compressed", "disk": "disk", "gpt": "disk", "other": "other"}
    for key, path in files.items():
        if utils.classify_image_file(path) != want_kind[key]:
            errors.append(f"classify_image_file({key}) = {utils.classify_image_file(path)}")

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.resize(1300, 800)
    window.show()

    def at(widget):
        """Window coordinates of a widget's centre, with its tab showing."""
        page = widget
        while page is not None and window.tab_widget.indexOf(page) < 0:
            page = page.parentWidget()
        if page is not None:
            window.tab_widget.setCurrentWidget(page)
        for _ in range(5):
            app.processEvents()
        # Scroll it into view, as a user would before dropping on it.
        area = widget.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is not None:
            area.ensureWidgetVisible(widget)
            for _ in range(5):
                app.processEvents()
        pos = widget.mapTo(window, widget.rect().center())
        if window.childAt(pos) is not widget and not widget.isAncestorOf(window.childAt(pos)):
            errors.append(f"test setup: {widget.objectName() or type(widget).__name__} "
                          f"isn't under its own centre")
        return QPointF(pos)

    def drop(widget, *paths):
        """Drag enter, then drop if accepted - the order Qt delivers a real
        drag in (a Drop sent on its own is discarded). Returns whether the
        drag was accepted."""
        pos = at(widget)
        # Keep the QMimeData referenced: the events only hold a pointer to it.
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(p) for p in paths])
        enter = QDragEnterEvent(pos.toPoint(), Qt.DropAction.CopyAction, data,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        window.dragEnterEvent(enter)
        if not enter.isAccepted():
            return False
        window.dropEvent(QDropEvent(pos, Qt.DropAction.CopyAction, data,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        app.processEvents()
        return True

    def reset():
        for field in (window.loader_path, window.firmware_path, window.image_path):
            field.clear()
        window.log_widget.clear_log()

    def warned():
        return "[WARNING]" in window.log_output.toPlainText()

    blank = window.home_cards_label
    try:
        # Dropped anywhere else: routed by contents.
        for key in ("loader", "loader_ldr"):
            reset()
            drop(blank, files[key])
            if window.loader_path.text() != files[key]:
                errors.append(f"{key} dropped on the window didn't fill the Loader field")
        for key in ("rkfw", "compressed", "disk", "gpt"):
            reset()
            drop(blank, files[key])
            if window.firmware_path.text() != files[key] or \
                    window.tab_widget.currentWidget() is not window.download_tab:
                errors.append(f"{key} dropped on the window didn't fill one-click burn")
        reset()
        drop(blank, files["other"])
        if window.firmware_path.text() or window.loader_path.text() or not warned():
            errors.append("a partition image dropped on the window was routed somewhere")

        # On a field: that field, with format checks.
        reset()
        drop(window.firmware_path, files["loader"])
        if window.loader_path.text() != files["loader"] or window.firmware_path.text():
            errors.append("a loader dropped on the firmware field wasn't moved to Loader")
        reset()
        drop(window.firmware_path, files["other"])
        if window.firmware_path.text() != files["other"] or not warned():
            errors.append("a partition image on the firmware field: not filled, or no warning")
        reset()
        drop(window.mass_firmware_path, files["rkfw"])
        if window.mass_firmware_path.text() != files["rkfw"] or warned():
            errors.append("update.img on the mass-production field: not filled, or warned")
        reset()
        drop(window.loader_path, files["disk"])
        if window.loader_path.text() != files["disk"] or not warned():
            errors.append("a non-loader on the Loader field: not filled, or no warning")
        reset()
        drop(window.image_path, files["other"])
        if window.image_path.text() != files["other"] or warned():
            errors.append("a file on the custom image field: not filled, or warned")
        # (The partition file field is only shown with a device connected.)
        for field in (window.unpack_input_path, window.gpt_path,
                      window.tagspl_spl_path, window.verify_file_path):
            drop(field, files["other"])
            if field.text() != files["other"]:
                errors.append(f"a file dropped on {field.objectName() or field} wasn't taken")

        # Several files, and folders outside the unpack folder, are refused.
        reset()
        if drop(blank, files["rkfw"], files["disk"]) or window.firmware_path.text():
            errors.append("dropping two files at once was accepted")
        if drop(blank, work):
            errors.append("a folder dropped on the window was accepted")

        # Settings: unpack folder, rkdeveloptool.
        drop(window.settings_page.unpack_dir, work)
        if window.settings_page.unpack_dir.text() != work or \
                window.settings.get_str(app_settings.KEY_UNPACK_MODE, "") != "custom":
            errors.append("a folder dropped on the unpack folder field wasn't selected")
        window.settings.set(app_settings.KEY_UNPACK_MODE, "beside")
        tool = make("rkdeveloptool", b'#!/bin/sh\necho "rkdeveloptool ver 2.0"\n')
        os.chmod(tool, 0o755)
        drop(window.settings_page.tool_path, tool)
        if utils.RKTOOL != tool:
            errors.append("rkdeveloptool dropped on its Settings field wasn't applied")
        window.settings_page._reset_tool()
        drop(window.settings_page.loader_path, files["loader"])
        if window.loader_path.text() != files["loader"]:
            errors.append("a loader dropped on the Settings Loader field wasn't taken")

        # Command line: the quoted path, at the cursor.
        spaced = make("my image.img", mbr)
        window.equiv_command_field.setText("wl 0x0 ")
        drop(window.equiv_command_field, spaced)
        if window.equiv_command_field.text() != "wl 0x0 " + shlex.quote(spaced):
            errors.append(f"command line after a drop: {window.equiv_command_field.text()!r}")

        # No line edit inserts "file://" text itself.
        if any(e.acceptDrops() for e in window.findChildren(QLineEdit)):
            errors.append("a line edit still takes drops itself (would insert file:// text)")

        # The GPT and unpack fields are what those actions use now.
        asked = []
        real = (app_settings.get_open_file, app_settings.get_directory, QMessageBox.exec)
        app_settings.get_open_file = lambda *a, **k: asked.append("file") or ""
        app_settings.get_directory = lambda *a, **k: ""
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.No
        try:
            operations.import_gpt_table(window)
            operations.unpack_firmware(window)
        finally:
            app_settings.get_open_file, app_settings.get_directory, QMessageBox.exec = real
        if asked:
            errors.append("Import GPT / Unpack asked for a file despite one in their field")
    finally:
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_failure_guidance(app):
    """rkdeveloptool's failure messages map to a cause and what to try."""
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import failures

    # Messages as rkdeveloptool prints them (main.cpp / RKComm.cpp).
    samples = {
        "Found too many rockusb devices, please plug devices out!": "too_many_devices",
        "Did not find any rockusb device, please plug device in!": "no_device",
        "not found any devices!": "no_device",
        "Parameter of [UL] command is invalid, please check help!": "bad_arguments",
        "command is invalid!": "bad_arguments",
        "Upgrading loader failed!": "loader_upgrade",
        "Downloading bootloader failed!": "loader_download",
        "Write LBA failed, err=-1, can't open file: /x.img": "file_open",
        "Creating Comm Object failed!": "cannot_open",
        "Write LBA quit, creating comm object failed!": "cannot_open",
        "Write LBA from file (37%)\nWrite LBA failed!": "write_failed",
        "Write LBA failed!": "rejected",
        "Read LBA failed!": "rejected",
        "Writing master gpt failed!": "write_failed",
        "Read LBA to file (12%)\nRead LBA failed!": "read_failed",
        "Not found any partition table!": "no_partition_table",
        "Parse parameter failed!": "bad_parameter_file",
        "Change Storage failed!": "storage_switch",
        "Reading Flash Info failed!": "needs_loader",
    }
    for output, kind in samples.items():
        got = failures.classify_failure("Downloading bootloader...\n" * (kind != "loader_download") + output)
        if got != kind:
            errors.append(f"{output!r} classified as {got}, want {kind}")
    if failures.classify_failure("something nobody has seen\n") is not None:
        errors.append("unrecognised output was classified")
    for lang, table in TRANSLATIONS.items():
        for kind in failures.KINDS:
            for part in ("title", "causes", "actions"):
                if f"err_{kind}_{part}" not in table:
                    errors.append(f"{lang}: missing err_{kind}_{part}")

    tr = TranslationManager(lang="en").tr
    with_rule = failures.explain(tr, "Creating Comm Object failed!", "sudo tee RULE")
    write = failures.explain(tr, "Write LBA from file (5%)\nWrite LBA failed!", "sudo tee RULE")
    if not with_rule or "sudo tee RULE" not in with_rule[1]:
        errors.append("the Linux udev command isn't offered for a device that can't be opened")
    if not write or "sudo tee RULE" in write[1]:
        errors.append("the Linux udev command was offered for a write failure")

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()

    class FakeWorker:
        description_key = "burning"

        def __init__(self, output):
            self.output = output

    shown = []
    real_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: shown.append(self.text()) or 0
    try:
        def finish(output, mode="Loader", loaded=True, rkfw=False):
            shown.clear()
            window.device_mode, window.loader_loaded = mode, loaded
            window.maskrom_device_shown_hint = False
            window._rkfw_flashing = rkfw
            window.command_worker = FakeWorker(output)
            window.on_command_finished(False, "failed")
            return list(shown)

        if finish("Write LBA from file (40%)\nWrite LBA failed!") != ["Writing failed"]:
            errors.append(f"write failure dialog: {shown}")
        if finish("Write LBA from file (40%)\nWrite LBA failed!", rkfw=True):
            errors.append("a failure during an RKFW flash popped its own dialog")
        hint = finish("Reading Flash Info failed!", mode="Maskrom", loaded=False)
        if len(hint) != 1 or "Reading device information failed" in hint[0]:
            errors.append(f"Maskrom without loader should show only the loader hint: {hint}")
        if finish("something nobody has seen"):
            errors.append("an unrecognised failure popped a dialog")
        if "Writing failed" not in window.log_output.toPlainText():
            errors.append("the guidance wasn't logged")
    finally:
        QMessageBox.exec = real_exec
        window._rkfw_flashing = False
        window.command_worker = None
        window.cleanup()
        window.deleteLater()
        app.processEvents()
def check_preflight(app):
    """The checks shown before a write, and that a failed one blocks it."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops

    work = tempfile.mkdtemp(dir=_tmp)

    def make(name, data):
        path = os.path.join(work, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    disk = make("disk.img", b"\0" * 510 + b"\x55\xaa" + b"\0" * 1536)  # 2 KiB
    loader = make("loader.bin", b"BOOT" + b"\0" * 2044)
    part = make("boot.img", b"ANDROID!" + b"\0" * 2040)

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())

    def statuses(path, address, capacity, device="dev", mode="Loader", loaded=False):
        window.current_device, window.device_mode, window.loader_loaded = device, mode, loaded
        return [status for status, _ in ops.preflight_checks(window, path, address, capacity)]

    def with_loader_field(fn):
        window.loader_path.setText(loader)
        try:
            return fn()
        finally:
            window.loader_path.setText("")

    def with_chip(fn):
        window.chip_info = "RK3576"
        try:
            return fn()
        finally:
            window.chip_info = "unknown_chip"

    P, W, F, U = ops.PASS, ops.WARN, ops.FAIL, ops.UNKNOWN
    cases = {
        "no device": (statuses(disk, "0x0", 1 << 20, device=None), [F, P, P]),
        "maskrom, no loader": (statuses(disk, "0x0", None, mode="Maskrom"), [P, F, P, U]),
        "maskrom, Loader in the field": (with_loader_field(
            lambda: statuses(disk, "0x0", None, mode="Maskrom")), [P, W, P, U]),
        "maskrom, chip known": (with_chip(
            lambda: statuses(disk, "0x0", None, mode="Maskrom")), [P, W, P, U]),
        "maskrom, loader loaded": (statuses(disk, "0x0", 1 << 20, mode="Maskrom", loaded=True),
                                   [P, P, P, P]),
        "loader at 0x0": (statuses(loader, "0x0", 1 << 20), [P, P, F, P]),
        "partition image at 0x0": (statuses(part, "0x0", 1 << 20), [P, P, W, P]),
        "partition image elsewhere": (statuses(part, "0x8000", 1 << 30), [P, P, P]),
        "too big": (statuses(disk, "0x0", 1024), [P, P, P, F]),
        "too big from its offset": (statuses(disk, "0x2", 2048), [P, P, F]),
        "capacity unknown": (statuses(disk, "0x0", None), [P, P, P, U]),
        "named partition": (statuses(part, "boot", 1 << 30), [P, P, U]),
    }
    for name, (got, want) in cases.items():
        if got != want:
            errors.append(f"pre-flight '{name}': {got}, want {want}")

    # A failed check: the dialog still appears, and no answer starts a write.
    shown = []
    real_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: shown.append(self.standardButtons()) or QMessageBox.StandardButton.Yes
    try:
        accepted = ops._show_burn_confirm(window, "x", 1, "1 B", "md5", "0x0", "eMMC", {},
                                          [(F, "Capacity: too big")])
        accepted_ok = ops._show_burn_confirm(window, "x", 1, "1 B", "md5", "0x0", "eMMC", {},
                                             [(P, "fine"), (W, "careful")])
    finally:
        QMessageBox.exec = real_exec
    if accepted or len(shown) != 2 or shown[0] != QMessageBox.StandardButton.Close:
        errors.append(f"a failed pre-flight check didn't block (accepted={accepted}, shown={shown})")
    if not accepted_ok:
        errors.append("warnings alone blocked the write")

    # End to end: the capacity read on a worker reaches the checks; no rfi
    # call in Maskrom without a loader.
    # (The stub rkdeveloptool reports no device; keep the poller from
    # resetting the device state while the capacity query runs.)
    window.stop_device_detection()
    seen, queried, results = [], [], {}
    real = (ops.get_flash_capacity_bytes, ops._show_burn_confirm)
    ops.get_flash_capacity_bytes = lambda gui: queried.append(1) or (1 << 20, "test")
    # (gui, name, size, size_str, md5, address, storage, info, checks, verify)
    ops._show_burn_confirm = lambda *a: seen.append(a[8]) or False
    try:
        for mode, loaded in (("Loader", False), ("Maskrom", False)):
            window.current_device, window.device_mode, window.loader_loaded = "dev", mode, loaded
            seen.clear()
            ops._burn_with_confirm(window, disk, "0x0", lambda: None)
            for _ in range(200):
                app.processEvents()
                if seen:
                    break
                time.sleep(0.01)
            results[mode] = [status for status, _ in seen[0]] if seen else None
    finally:
        ops.get_flash_capacity_bytes, ops._show_burn_confirm = real
        window.current_device = None
        window.cleanup()
        window.deleteLater()
        app.processEvents()
    if queried != [1]:
        errors.append(f"capacity queried {len(queried)} times (want once: not in Maskrom without loader)")
    # Loader mode: the queried 1 MiB reaches the capacity check (a pass for
    # a 2 KiB image). Maskrom without a loader: blocked, capacity unknown.
    if results.get("Loader") != [P, P, P, P] or results.get("Maskrom") != [P, F, P, U]:
        errors.append(f"pre-flight end to end: {results}")


def check_disconnect_during_write(app):
    """While the device is in use the poller only enumerates; losing the
    device during a write stops it and explains how to recover."""
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import workers

    # A stub rkdeveloptool that lists a Maskrom device and records its calls.
    calls = os.path.join(_tmp, "calls.log")
    tool = os.path.join(_tmp, "rkdeveloptool-logging")
    with open(tool, "w") as f:
        f.write('#!/bin/sh\necho "$1" >> ' + calls + '\n'
                'echo "DevNo=1\tVid=0x2207,Pid=0x350b,LocationID=101\tMaskrom"\n')
    os.chmod(tool, 0o755)
    real_tool = workers.RKTOOL
    workers.RKTOOL = tool
    try:
        for light in (True, False):
            open(calls, "w").close()
            got = []
            worker = workers.DeviceWorker(TranslationManager(lang="en"))
            worker.light = light
            worker.presence.connect(lambda p: got.append(("presence", p)))
            worker.device_found.connect(lambda *a: got.append(("found",)))
            worker.start()
            for _ in range(300):
                app.processEvents()
                if got:
                    break
                time.sleep(0.01)
            worker.stop()
            worker.wait(5000)
            app.processEvents()
            with open(calls) as f:
                commands = set(f.read().split())
            if light and (got[:1] != [("presence", True)] or "rci" in commands):
                errors.append(f"light polling: signals {got}, commands {commands} (must not run rci)")
            if not light and (got[:1] != [("found",)] or "rci" not in commands):
                errors.append(f"normal polling: signals {got}, commands {commands}")
    finally:
        workers.RKTOOL = real_tool

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()

    class FakeWorker:
        def __init__(self, key):
            self.description_key, self.output, self.killed = key, "Write LBA failed!", 0

        def terminate_process(self):
            self.killed += 1

    shown = []
    real_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: shown.append(self.text()) or 0
    try:
        def start(key):
            window.command_worker = FakeWorker(key)
            window._command_active, window._lost_during_write, window._absent_polls = True, False, 0
            window.device_mode, window.loader_loaded = "Loader", True
            return window.command_worker

        w = start("burning")
        window.on_device_presence(False)
        if window._lost_during_write or w.killed:
            errors.append("one missed poll during a write counted as a disconnect")
        window.on_device_presence(True)
        window.on_device_presence(False)
        if window._lost_during_write:
            errors.append("a poll that found the device didn't reset the count")
        window.on_device_presence(False)
        if not window._lost_during_write or w.killed != 1:
            errors.append(f"two missed polls during a write: lost={window._lost_during_write}, killed={w.killed}")
        shown.clear()
        window.on_command_finished(False, "failed")
        if shown != ["The device disconnected while being written"]:
            errors.append(f"after a disconnect mid-write the dialogs were {shown}")

        w = start("reading_flash")
        for _ in range(3):
            window.on_device_presence(False)
        if window._lost_during_write or w.killed:
            errors.append("a disconnect during a read was treated as a broken write")

        window._command_active = False
        window._rkfw_flashing = True
        window.device_worker = workers.DeviceWorker(TranslationManager(lang="en"))
        window._update_poll_mode()
        if not window.device_worker.light:
            errors.append("polling isn't light during a full RKFW flash")
        window._rkfw_flashing = False
        window._update_poll_mode()
        if window.device_worker.light:
            errors.append("polling stayed light after the flash")
    finally:
        QMessageBox.exec = real_exec
        window._rkfw_flashing = False
        window._command_active = False
        window.command_worker = None
        window.device_worker = None
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_cancel(app):
    """Cancel: shown only while something runs, confirms before abandoning a
    write, and reports a cancelled write as possibly partial."""
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui import rkfw
    from rkdeveloptool_gui.workers import RKFWPrepWorker

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    window.show()

    class FakeWorker:
        def __init__(self, key):
            self.description_key, self.output, self.killed = key, "", 0

        def terminate_process(self):
            self.killed += 1

    asked, shown = [], []
    answer = [QMessageBox.StandardButton.Yes]
    real = (QMessageBox.warning, QMessageBox.exec, ops._show_rkfw_message)
    QMessageBox.warning = staticmethod(lambda *a, **k: asked.append(a[1]) or answer[0])
    QMessageBox.exec = lambda self: shown.append(self.text()) or 0
    ops._show_rkfw_message = lambda gui, title, text, icon="Critical", **_: shown.append(title)
    try:
        def start(key):
            window.command_worker = FakeWorker(key)
            window._command_active = True
            window._cancel_requested = False
            window._update_poll_mode()
            app.processEvents()
            return window.command_worker

        window._command_active = False
        window._update_poll_mode()
        if window.cancel_btn.isVisible():
            errors.append("Cancel is visible with nothing running")

        # A read: stopped without asking, nothing to report afterwards.
        w = start("reading_flash")
        if not window.cancel_btn.isVisible():
            errors.append("Cancel isn't shown while a command runs")
        asked.clear(); shown.clear()
        window.cancel_current()
        window.on_command_finished(False, "killed")
        if asked or w.killed != 1 or shown:
            errors.append(f"cancelling a read: asked={asked}, killed={w.killed}, dialogs={shown}")

        # A write, declined: nothing happens.
        w = start("burning")
        answer[0] = QMessageBox.StandardButton.No
        asked.clear()
        window.cancel_current()
        if len(asked) != 1 or w.killed:
            errors.append(f"declining to cancel a write still stopped it (asked={asked}, killed={w.killed})")

        # A write, confirmed: stopped, reported as possibly partial, and not
        # explained as a failure.
        answer[0] = QMessageBox.StandardButton.Yes
        asked.clear(); shown.clear()
        window.cancel_current()
        w.output = "Write LBA failed!"
        window.on_command_finished(False, "killed")
        if w.killed != 1 or asked != ["Cancel flashing?", "Flashing cancelled"] or shown:
            errors.append(f"cancelling a write: killed={w.killed}, asked={asked}, dialogs={shown}")
        if window.cancel_btn.isVisible():
            errors.append("Cancel stayed visible after the command ended")

        # Between two RKFW steps: the next step never starts.
        window._command_active = False
        ran = []
        real_run = window.run_command
        window.run_command = lambda *a, **k: ran.append(a)
        window._cancel_requested = True
        tmp = tempfile.mkdtemp(dir=_tmp)
        shown.clear()
        ops._run_rkfw_steps(window, [(["x"], "importing_gpt", "gpt")], 0, tmp)
        window.run_command = real_run
        if ran or shown != ["cancelled_partial_title"] or os.path.exists(tmp):
            errors.append(f"cancel between RKFW steps: ran={ran}, dialogs={shown}")
    finally:
        QMessageBox.warning, QMessageBox.exec, ops._show_rkfw_message = real
        window._command_active = False
        window.command_worker = None
        window.cleanup()
        window.deleteLater()
        app.processEvents()

    # The RKFW verify/unpack pass stops when asked, and says it was cancelled.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rkfw_layouts
    image = os.path.join(tempfile.mkdtemp(dir=_tmp), "update.img")
    rkfw_layouts.build(image, [("parameter", "parameter.txt", b"CMDLINE: x\n"),
                               ("boot", "Image/boot.img", os.urandom(1 << 20))])
    info = rkfw.parse_rkfw_header(image)
    rkaf = rkfw.parse_rkaf_header(image, info.fw_offset, info.fw_size)
    outcome = []
    prep = RKFWPrepWorker(image, info, rkaf, tempfile.mkdtemp(dir=_tmp),
                          TranslationManager(lang="en"))
    prep.failed.connect(lambda kind, msg: outcome.append(kind))
    prep.finished.connect(lambda paths: outcome.append("finished"))
    prep.stop()
    prep.run()
    if outcome != ["cancelled"]:
        errors.append(f"stopping the RKFW prep worker gave {outcome}, not cancelled")


def check_progress(app):
    """Overall progress weighted by bytes, recent speed, an honest ETA."""
    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui.progress import ProgressTracker, format_eta

    now = [0.0]
    t = ProgressTracker(1000, clock=lambda: now[0])
    now[0] = 1.0
    t.update(100)
    if t.eta() is not None:
        errors.append("an ETA was offered after 1 s")
    now[0] = 4.0
    t.update(400)
    if t.speed() != 100 or round(t.eta()) != 6:
        errors.append(f"steady 100 B/s: speed={t.speed()}, eta={t.eta()}")
    # Slows to 4 B/s: within a 10 s window the estimate follows.
    for step, done in ((20.0, 500), (25.0, 520)):
        now[0] = step
        t.update(done)
    if not (t.speed() < 10 and t.eta() > 50):
        errors.append(f"after slowing down: speed={t.speed()}, eta={t.eta()} (stale average?)")
    tr = TranslationManager(lang="en").tr
    if format_eta(tr, 130) != "about 2 min 10 s left" or format_eta(tr, 0.2) != "about 1 s left":
        errors.append(f"format_eta: {format_eta(tr, 130)!r}, {format_eta(tr, 0.2)!r}")

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    try:
        window.begin_job(1000)
        window.job_stage("[2/3] rootfs", 400, 600)
        if window.progress_bar.value() != 40:
            errors.append(f"a step starting at 400 of 1000 B shows {window.progress_bar.value()}%")
        window._on_command_progress(50)
        label = window.progress_label.text()
        if window.progress_bar.value() != 70 or not label.startswith("[2/3] rootfs 70%"):
            errors.append(f"50% of that step: bar {window.progress_bar.value()}, label {label!r}")
        window.log_message("Write LBA from file (15%)")
        if window.progress_bar.value() != 70:
            errors.append("a step's own NN% log line overwrote the overall progress")
        window.end_job()
        window.log_message("Write LBA from file (15%)")
        if window.progress_bar.value() != 15:
            errors.append("log-line progress didn't come back after the job")

        # A full RKFW flash: step 2 starts with step 1's bytes counted.
        work = tempfile.mkdtemp(dir=_tmp)
        files = []
        for name, size in (("loader.bin", 100), ("parameter.txt", 300), ("rootfs.img", 600)):
            path = os.path.join(work, name)
            with open(path, "wb") as f:
                f.write(b"\0" * size)
            files.append(path)
        steps = [([ops.RKTOOL, "db", files[0]], "loading_loader", "Loader"),
                 ([ops.RKTOOL, "gpt", files[1]], "importing_gpt", "GPT"),
                 ([ops.RKTOOL, "wlx", "rootfs", files[2]], "burning", "rootfs")]
        window._rkfw_step_bytes = [100, 300, 600]
        window.begin_job(1000)
        real_run = window.run_command
        window.run_command = lambda *a, **k: None
        try:
            ops._run_rkfw_steps(window, steps, 1, work)
        finally:
            window.run_command = real_run
        if window.progress_bar.value() != 10 or not window.progress_label.text().startswith("[2/3] GPT"):
            errors.append(f"RKFW step 2: bar {window.progress_bar.value()}, label {window.progress_label.text()!r}")
        window.end_job()
    finally:
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_verify_after_write(app):
    """Optional readback after a write: offered, remembered, compared."""
    import hashlib

    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui import settings as app_settings
    from rkdeveloptool_gui.workers import FileHashWorker

    work = tempfile.mkdtemp(dir=_tmp)
    image = os.path.join(work, "board.img")
    data = b"\0" * 510 + b"\x55\xaa" + os.urandom(3000)  # not a whole number of sectors
    with open(image, "wb") as f:
        f.write(data)
    expected = hashlib.md5(data).hexdigest()

    got = []
    hasher = FileHashWorker(image, length=1000)
    hasher.finished.connect(got.append)
    hasher.run()
    if got != [hashlib.md5(data[:1000]).hexdigest()]:
        errors.append("FileHashWorker(length=) didn't hash just the prefix")

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()

    # The checkbox: offered with its remembered state, choice remembered.
    boxes = []
    real_exec = QMessageBox.exec

    def fake_exec(self):
        box = self.checkBox()
        boxes.append(box.isChecked() if box else None)
        if box:
            box.setChecked(True)
        return QMessageBox.StandardButton.Yes

    QMessageBox.exec = fake_exec
    try:
        ops._show_burn_confirm(window, "x", 1, "1 B", "md5", "0x0", "eMMC", {}, [], False)
        ops._show_burn_confirm(window, "x", 1, "1 B", "md5", "0x0", "eMMC", {}, [], None)
        ops._show_burn_confirm(window, "x", 1, "1 B", "md5", "0x0", "eMMC", {},
                               [(ops.FAIL, "no")], True)
    finally:
        QMessageBox.exec = real_exec
    if boxes != [False, None, None] or \
            window.settings.get_str(app_settings.KEY_VERIFY_AFTER_WRITE, "") != "1":
        errors.append(f"verify checkbox offered {boxes} (want unchecked, absent, absent "
                      "when blocked), choice remembered: "
                      f"{window.settings.get_str(app_settings.KEY_VERIFY_AFTER_WRITE, '')}")

    def run_burn(verify, corrupt=False, address="0x0", filler_from=None):
        commands, reports, cleaned, offered = [], [], [], []

        def fake_confirm(gui, path, addr, on_confirm, on_cancel=None, offer_verify=False):
            offered.append(offer_verify)
            gui._verify_after_write = verify
            gui._last_burn_md5 = expected
            on_confirm()

        def fake_run(cmd, key, callback=None):
            commands.append(cmd[1:3])
            if cmd[1] == "rl":
                sectors = int(cmd[3], 16)
                back = bytearray(data + b"\xff" * (sectors * 512 - len(data)))
                if corrupt:
                    back[100] ^= 0xFF
                if filler_from is not None:
                    back[filler_from:] = b"\xcc" * (len(back) - filler_from)
                with open(cmd[4], "wb") as f:
                    f.write(back)
            if callback:
                callback(True, "")

        real = (ops._burn_with_confirm, ops._show_rkfw_message, window.run_command)
        ops._burn_with_confirm = fake_confirm
        ops._show_rkfw_message = lambda gui, title, text, icon="Critical", **_: reports.append(title)
        window.run_command = fake_run
        try:
            ops._burn_file(window, image, address,
                           lambda p: [ops.RKTOOL, "wl", address, p])
            for _ in range(300):
                app.processEvents()
                if reports or (not verify and commands):
                    break
                time.sleep(0.01)
        finally:
            ops._burn_with_confirm, ops._show_rkfw_message, window.run_command = real
        leftovers = [n for n in os.listdir(work) if n.startswith(".rkdevtool_verify_")]
        return commands, reports, offered, leftovers

    commands, reports, offered, leftovers = run_burn(verify=True)
    sectors = hex(-(-len(data) // 512))
    if commands != [["wl", "0x0"], ["rl", "0x0"]] or reports != ["verify_ok_title"] or leftovers:
        errors.append(f"verify after write: commands {commands}, reports {reports}, "
                      f"temp left {leftovers}")
    commands, reports, _, _ = run_burn(verify=True, corrupt=True)
    if reports != ["verify_mismatch_title"]:
        errors.append(f"a corrupted readback was reported as {reports}")
    commands, reports, _, leftovers = run_burn(verify=True, filler_from=1024)
    if reports != ["verify_unreliable_title"] or leftovers:
        errors.append(f"a readback that turns to 0xCC filler was reported as {reports} "
                      f"(temp left {leftovers})")
    commands, reports, _, _ = run_burn(verify=False)
    if commands != [["wl", "0x0"]] or reports != ["write_done_title"]:
        errors.append(f"verify off: commands {commands}, reports {reports}")
    _, _, offered, _ = run_burn(verify=False, address="boot")
    if offered != [False]:
        errors.append("verify was offered for a write without a numeric address")

    window.cleanup()
    window.deleteLater()
    app.processEvents()


def check_chip_and_device_lock(app):
    """Chip info decoding, and that the poller never opens the device while
    a partition-table read (or capacity query) holds DEVICE_LOCK."""
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui import utils, workers

    for text, want in (("Chip Info:  36 37 35 33 0 0 0 0 0 0 0 0 0 0 0 0", "RK3576"),  # a real RK3576
                       ("Chip Info: 38 38 35 33 0 0 0 0 0 0 0 0 0 0 0 0", "RK3588"),
                       # "330A" and "330C" are RK3368's and RK3399's numbers.
                       ("Chip Info: 41 30 33 33 0 0 0 0 0 0 0 0 0 0 0 0", "RK3368"),
                       ("Chip Info: 43 30 33 33 0 0 0 0 0 0 0 0 0 0 0 0", "RK3399"),
                       ("0x330A", "RK3368"),
                       ("36 37 35 33 0 0", "RK3576"),
                       ("RK3399", "RK3399"),
                       ("", "Unknown Chip")):
        if utils.parse_chip_info(text) != want:
            errors.append(f"parse_chip_info({text!r}) = {utils.parse_chip_info(text)!r}, want {want}")

    calls = os.path.join(_tmp, "lock-calls.log")
    tool = os.path.join(_tmp, "rkdeveloptool-lock")
    with open(tool, "w") as f:
        f.write('#!/bin/sh\necho "$1" >> ' + calls + '\n'
                'case "$1" in\n'
                '  ld) echo "DevNo=1\tVid=0x2207,Pid=0x350e,LocationID=101\tMaskrom" ;;\n'
                '  rci) echo "Chip Info:  36 37 35 33 0 0 0 0 0 0 0 0 0 0 0 0" ;;\n'
                '  ppt) echo "Not found any partition table!"; exit 1 ;;\n'
                'esac\n')
    os.chmod(tool, 0o755)
    real_tool = workers.RKTOOL
    workers.RKTOOL = tool

    def poll_once(hold_lock):
        open(calls, "w").close()
        got = []
        worker = workers.DeviceWorker(TranslationManager(lang="en"))
        worker.presence.connect(lambda p: got.append(("presence", p)))
        worker.device_found.connect(lambda d, m, c: got.append(("found", c)))
        if hold_lock:
            utils.DEVICE_LOCK.acquire()
        try:
            worker.start()
            for _ in range(300):
                app.processEvents()
                if got:
                    break
                time.sleep(0.01)
        finally:
            worker.stop()
            if hold_lock:
                utils.DEVICE_LOCK.release()
            worker.wait(5000)
            app.processEvents()
        with open(calls) as f:
            return got[:1], set(f.read().split())

    try:
        got, commands = poll_once(hold_lock=True)
        if got != [("presence", True)] or "rci" in commands:
            errors.append(f"poll while the device lock is held: {got}, ran {commands}")
        got, commands = poll_once(hold_lock=False)
        if got != [("found", "RK3576")] or "rci" not in commands:
            errors.append(f"poll with the lock free: {got}, ran {commands}")

        # The partition read waits for the lock.
        done = []
        ppt = workers.PartitionPPTWorker()
        ppt.finished.connect(lambda out, code: done.append((out, code)))
        utils.DEVICE_LOCK.acquire()
        try:
            ppt.start()
            for _ in range(30):
                app.processEvents()
                time.sleep(0.01)
            waited = not done
        finally:
            utils.DEVICE_LOCK.release()
        ppt.wait(10000)
        app.processEvents()
        if not waited or not done:
            errors.append(f"partition read didn't wait for the device lock (waited={waited}, done={done})")
    finally:
        workers.RKTOOL = real_tool

    # A failed read says why instead of leaving the table empty.
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    shown = []
    real_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: shown.append(self.text()) or 0
    try:
        ops.on_partition_ppt_finished(window, "Not found any partition table!\n", 1)
        blank = list(shown)
        shown.clear()
        ops.on_partition_ppt_finished(window, "", 1)
        unknown = list(shown)
    finally:
        QMessageBox.exec = real_exec
        window.cleanup()
        window.deleteLater()
        app.processEvents()
    if blank != ["No partition table could be read"]:
        errors.append(f"blank storage on partition read showed {blank}")
    if len(unknown) != 1:
        errors.append(f"an unexplained partition read failure showed {unknown}")


def check_gpt_import_export(app):
    """Import GPT runs `rkdeveloptool gpt <parameter file>` (it has no import or
    export subcommands); Export GPT writes a parameter file from `ppt` that
    Import accepts."""
    import re

    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui import settings as app_settings
    from rkdeveloptool_gui import utils

    # `rkdeveloptool ppt` output, as print_gpt prints it.
    ppt = ("**********Partition Info(GPT)**********\r\n"
           "NO  LBA       Name                \r\n"
           "00  00004000  uboot\r\n"
           "01  00006000  misc\r\n"
           "02  00008000  boot\r\n"
           "03  00040000  rootfs\r\n")
    text = utils.build_parameter_text(utils.parse_partition_info(ppt))
    line = next(l for l in text.splitlines() if "mtdparts" in l)
    entries = line.split(":", 2)[2].split(",")
    want = ["0x00002000@0x00004000(uboot)", "0x00002000@0x00006000(misc)",
            "0x00038000@0x00008000(boot)", "-@0x00040000(rootfs:grow)"]
    if entries != want:
        errors.append(f"parameter text from ppt: {entries}")
    # Every entry in the form rkdeveloptool's parse_parameter reads.
    if not all(re.fullmatch(r"(0x[0-9a-f]+|-)@0x[0-9a-f]+\([^)]+\)", e) for e in entries):
        errors.append(f"parameter entries not in size@offset(name) form: {entries}")

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    work = tempfile.mkdtemp(dir=_tmp)
    exported = os.path.join(work, "parameter.txt")
    ran, shown = [], []

    def fake_run(cmd, key, callback=None):
        ran.append(cmd[1:])
        if callback:
            callback(True, ppt if cmd[1] == "ppt" else "")

    real = (app_settings.get_save_file, app_settings.get_open_file, window.run_command,
            window.show_message, QMessageBox.exec)
    app_settings.get_save_file = lambda *a, **k: exported
    app_settings.get_open_file = lambda *a, **k: ""
    window.run_command = fake_run
    window.show_message = lambda title, msg, icon="Information": shown.append(msg)
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.Yes
    try:
        ops.export_gpt_table(window)
        if ran != [["ppt"]] or not utils.parameter_has_mtdparts(exported):
            errors.append(f"Export GPT ran {ran}; wrote a parameter file: "
                          f"{os.path.exists(exported) and utils.parameter_has_mtdparts(exported)}")

        ran.clear()
        binary = os.path.join(work, "gpt.bin")
        with open(binary, "wb") as f:
            f.write(b"EFI PART" + b"\0" * 504)
        window.gpt_path.setText(binary)
        ops.import_gpt_table(window)
        if ran or shown != ["gpt_not_parameter"]:
            errors.append(f"importing a non-parameter file: ran {ran}, messages {shown}")

        window.gpt_path.setText(exported)
        ops.import_gpt_table(window)
        if ran != [["gpt", exported]]:
            errors.append(f"Import GPT ran {ran}, want ['gpt', <parameter file>]")
    finally:
        (app_settings.get_save_file, app_settings.get_open_file, window.run_command,
         window.show_message, QMessageBox.exec) = real
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_storage_not_switched(app):
    """Storage types are offered without running `cs`: switching the target
    to probe it left an RK3576 refusing every read and write."""
    import subprocess as sp

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui.utils import find_readback_filler

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    ran = []
    real_run = ops.subprocess.run
    ops.subprocess.run = lambda cmd, *a, **k: ran.append(cmd) or sp.CompletedProcess(cmd, 0, "Change Storage OK.", "")
    try:
        if hasattr(window, '_supported_storages'):  # as on a fresh connection
            del window._supported_storages
        window.device_mode, window.loader_loaded = "Loader", True
        ops.detect_supported_storage_types(window)
    finally:
        ops.subprocess.run = real_run
    names = [window.change_storage_combo.itemText(i) for i in range(window.change_storage_combo.count())]
    if ran or names != ["EMMC", "SD Card", "SPI NOR"]:
        errors.append(f"storage detection ran {ran} and offered {names}")
    window.cleanup()
    window.deleteLater()
    app.processEvents()

    work = tempfile.mkdtemp(dir=_tmp)
    image, back = os.path.join(work, "i.img"), os.path.join(work, "b.bin")
    data = os.urandom(8 << 20)
    with open(image, "wb") as f:
        f.write(data)
    with open(back, "wb") as f:
        f.write(data[:5 << 20] + b"\xcc" * (3 << 20))
    if find_readback_filler(back, image, len(data)) != 5 << 20:
        errors.append("find_readback_filler missed filler starting at 5 MiB")
    with open(back, "wb") as f:
        f.write(data[:100] + b"\x00" + data[101:])
    if find_readback_filler(back, image, len(data)) is not None:
        errors.append("find_readback_filler reported filler for a one-byte difference")


def check_fetch_loader(app):
    """'Get Loader for This Chip' needs a recognised chip, builds the Loader
    from rkbin (a local copy here) and fills in the Loader field."""
    from rkdeveloptool_gui import loader_fetch
    from rkdeveloptool_gui import operations as ops

    rkbin = tempfile.mkdtemp(dir=_tmp)
    files = {
        "RKBOOT/RK3576MINIALL.ini": (
            "[CHIP_NAME]\nNAME=RK3576\n[VERSION]\nMAJOR=1\nMINOR=1\n"
            "[CODE471_OPTION]\nNUM=1\nPath1=bin/ddr.bin\nSleep=1\n"
            "[CODE472_OPTION]\nNUM=1\nPath1=bin/usbplug.bin\n"
            "[LOADER_OPTION]\nNUM=2\nLOADER1=FlashData\nLOADER2=FlashBoot\n"
            "FlashData=bin/ddr.bin\nFlashBoot=bin/spl.bin\n"
            "[OUTPUT]\nPATH=rk3576_loader_test.bin\n[SYSTEM]\nNEWIDB=true\n").encode(),
        "bin/ddr.bin": b"D" * 3000, "bin/usbplug.bin": b"U" * 5000, "bin/spl.bin": b"S" * 7000,
    }
    for name, data in files.items():
        os.makedirs(os.path.dirname(os.path.join(rkbin, name)), exist_ok=True)
        with open(os.path.join(rkbin, name), "wb") as f:
            f.write(data)
    cache = tempfile.mkdtemp(dir=_tmp)
    os.environ[loader_fetch.URL_ENV] = "file://" + rkbin + "/"
    real_cache = ops.loader_cache_dir
    ops.loader_cache_dir = lambda: cache
    from PySide6.QtWidgets import QMessageBox

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    # A board in Maskrom without chip info gets the "load a Loader?" hint.
    real_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.No
    try:
        window.update_device_status()
        if window.fetch_loader_btn.isEnabled():
            errors.append("Get Loader is enabled with no board connected")
        # In Maskrom before a Loader runs rci can't answer: the USB ID tells.
        window.on_device_found(["DevNo=1\tVid=0x2207,Pid=0x350e,LocationID=101\tMaskrom"],
                               "Maskrom", "unknown_chip")
        if not window.fetch_loader_btn.isEnabled():
            errors.append("Get Loader is disabled for an RK3576 known only by its USB ID")
        if "RK3576" not in window.chip_info_label.text():
            errors.append(f"chip shown as {window.chip_info_label.text()!r} for Pid 0x350e")
        window.loader_path.setText("")
        window.fetch_loader_btn.click()
        worker = getattr(window, '_loader_fetch_worker', None)
        if worker is None:
            errors.append("Get Loader didn't start")
            return
        worker.wait(10000)
        for _ in range(20):
            app.processEvents()
        want = os.path.join(cache, "rk3576_loader_test.bin")
        if window.loader_path.text() != want or not os.path.isfile(want):
            errors.append(f"Get Loader filled in {window.loader_path.text()!r}, not {want!r}")
        if not window.fetch_loader_btn.isEnabled():
            errors.append("Get Loader stays disabled after it finished")
    finally:
        QMessageBox.exec = real_exec
        del os.environ[loader_fetch.URL_ENV]
        ops.loader_cache_dir = real_cache
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_rkfw_read_back(app):
    """After a full flash, each partition is read back at its offset from
    the parameter file and compared; filler is "couldn't verify", a real
    difference is reported by name."""


def check_reset_after_write(app):
    """A whole image written at 0x0 ends with a Reset Board button that
    runs rd; a write elsewhere doesn't ask."""


def check_loader_before_write(app):
    """Writing in Maskrom without a Loader loads the one in the Loader
    field first, re-checks the storage size, then writes."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui import utils

    work = tempfile.mkdtemp(dir=_tmp)
    param = os.path.join(work, "parameter.txt")
    with open(param, "w") as f:
        f.write("FIRMWARE_VER: 1.0\nCMDLINE: console=ttyS0 mtdparts=rk29xxnand:"
                "0x00002000@0x00004000(uboot),-@0x00008000(rootfs:grow)\n")
    if utils.parameter_partitions(param) != {"uboot": (0x4000, 0x2000), "rootfs": (0x8000, None)}:
        errors.append(f"parameter_partitions: {utils.parameter_partitions(param)}")
    parts = {}
    for name, size in (("uboot", 3000), ("rootfs", 5000), ("misc", 700)):
        parts[name] = os.path.join(work, name + ".img")
        with open(parts[name], "wb") as f:
            f.write(os.urandom(size))


    work = tempfile.mkdtemp(dir=_tmp)
    disk = os.path.join(work, "disk.img")
    with open(disk, "wb") as f:
        f.write(b"\0" * 510 + b"\x55\xaa" + b"\0" * 1536)
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    ran, offered = [], []
    loader = os.path.join(work, "loader.bin")
    with open(loader, "wb") as f:
        f.write(b"LDR " + b"\0" * 600)
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    ran, shown = [], []

    def run(readbacks):
        def fake_run(cmd, key, callback=None):
            ran.append((cmd[1], cmd[2], cmd[3]))
            name = {hex(0x4000): "uboot", hex(0x8000): "rootfs"}[cmd[2]]
            with open(cmd[-1], "wb") as f:
                f.write(readbacks[name])
            QTimer.singleShot(0, lambda: callback(True, ""))
        ran.clear()
        shown.clear()
        window.run_command = fake_run
        window.command_worker = None
        window._rkfw_read_back = True
        window._rkfw_written = [("uboot", parts["uboot"]), ("rootfs", parts["rootfs"]),
                                ("misc", parts["misc"])]
        window._rkfw_parameter = param
        window._rkfw_flashing = True
        tmp = tempfile.mkdtemp(dir=work)
        ops._verify_rkfw_parts(window, tmp)
        end = time.time() + 10
        while window._rkfw_flashing and time.time() < end:
            app.processEvents()
            time.sleep(0.005)

    def data(name, pad=0):
        with open(parts[name], "rb") as f:
            return f.read() + b"\0" * pad

    real_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: shown.append((self.windowTitle(), self.text())) or 0
    try:
        # uboot matches (the read is rounded up to whole sectors); rootfs
        # reads back only filler; misc isn't in the table.
        rootfs = b"\xcc" * 5120     # past the Loader's read limit from its start
        run({"uboot": data("uboot", 72), "rootfs": rootfs})
        if ran != [("rl", hex(0x4000), hex(6)), ("rl", hex(0x8000), hex(10))]:
            errors.append(f"read back with {ran}")
        text = shown[-1][1] if shown else ""
        if not ("1 partition(s)" in text and "misc" in text
                and f"rootfs ({window.tr('rkfw_read_back_filler_all')})" in text):
            errors.append(f"read-back report: {shown}")

        # A real difference names the partition.
        bad = bytearray(data("uboot"))
        bad[100] ^= 0xFF
        run({"uboot": bytes(bad), "rootfs": data("rootfs")})
        want = window.tr("rkfw_read_back_mismatch_message").format("uboot")
        if not shown or not shown[-1][1].startswith(want):
            errors.append(f"mismatch report: {shown}")
        if window._rkfw_flashing or getattr(window, '_rkfw_verifying', False):
            errors.append("the flash stays busy after reading back")
    finally:
        QMessageBox.exec = real_exec


    def fake_run(cmd, key, callback=None):
        ran.append(cmd[1])
        QTimer.singleShot(0, lambda: callback and callback(True, ""))

    def fake_exec(self):
        buttons = {b.text(): b for b in self.buttons()}
        offered.append(window.tr("reset_board_btn") in buttons)
        if window.tr("reset_board_btn") in buttons:
            buttons[window.tr("reset_board_btn")].click()
        return QMessageBox.StandardButton.Yes

    real = (window.run_command, QMessageBox.exec)
    window.run_command, QMessageBox.exec = fake_run, fake_exec
    window.command_worker = None
    window.current_device, window.device_mode, window.loader_loaded = "dev", "Loader", True
    try:
        for address in ("0x0", "0x8000"):
            ran.clear()
            offered.clear()
            ops._burn_file(window, disk, address, lambda p, a=address: [ops.RKTOOL, "wl", a, p])
            end = time.time() + 5
            while time.time() < end and "wl" not in ran:
                app.processEvents()
                time.sleep(0.01)
            for _ in range(30):
                app.processEvents()
                time.sleep(0.005)
            # offered[0] is the confirmation; the rest come after the write.
            if address == "0x0" and (ran != ["wl", "rd"] or offered[1:] != [True]):
                errors.append(f"whole image: ran {ran}, reset offered {offered}")
            if address != "0x0" and (ran != ["wl"] or any(offered)):
                errors.append(f"write at {address}: ran {ran}, reset offered {offered}")
    finally:
        window.run_command, QMessageBox.exec = real


    real = (window.run_command, QMessageBox.exec, ops.get_flash_capacity_bytes,
            ops._board_answers, ops.READY_ATTEMPTS, ops.READY_INTERVAL_MS)
    answers = [True]
    ops._board_answers = lambda: answers.pop(0) if len(answers) > 1 else answers[0]
    ops.READY_ATTEMPTS, ops.READY_INTERVAL_MS = 3, 10
    window.run_command = fake_run
    window.command_worker = None
    QMessageBox.exec = lambda self: shown.append(self.text()) or QMessageBox.StandardButton.Yes

    def write_once(capacity):
        ran.clear()
        window.current_device, window.device_mode = "DevNo=1\tMaskrom", "Maskrom"
        window.loader_loaded = False
        window.loader_path.setText(loader)
        ops.get_flash_capacity_bytes = lambda gui: (capacity, "test")
        ops._burn_file(window, disk, "0x0", lambda p: [ops.RKTOOL, "wl", "0x0", p])
        end = time.time() + 10
        while time.time() < end and not ("wl" in ran or any("too big" in t for t in shown)):
            app.processEvents()
            time.sleep(0.01)
        for _ in range(20):
            app.processEvents()

    try:
        write_once(1 << 30)
        if ran != ["db", "wl"] or not window.loader_loaded:
            errors.append(f"write in Maskrom ran {ran}, loader_loaded {window.loader_loaded}")
        write_once(1024)
        if ran != ["db"]:
            errors.append(f"an image too big once the size was known still ran {ran}")
        # Refused right after db, answering on the next try (as an RK3576
        # does): written. Never answering: not written.
        answers[:] = [False, True]
        write_once(1 << 30)
        if ran != ["db", "wl"]:
            errors.append(f"a board answering on the second try: ran {ran}")
        answers[:] = [False]
        shown.clear()
        write_once(1 << 30)
        end = time.time() + 3
        while time.time() < end and not shown:
            app.processEvents()
            time.sleep(0.01)
        if ran != ["db"] or not any(window.tr("loader_no_answer") in t for t in shown):
            errors.append(f"a board that never answers: ran {ran}, said {shown}")
    finally:
        (window.run_command, QMessageBox.exec, ops.get_flash_capacity_bytes,
         ops._board_answers, ops.READY_ATTEMPTS, ops.READY_INTERVAL_MS) = real


def check_rfi_capacity(app):
    """The pre-flight storage size comes from real rfi output, exactly."""
    import subprocess as sp

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui.utils import flash_capacity_bytes

    out = ("Flash Info:\n\tManufacturer: SAMSUNG, value=00\n\tFlash Size: 29824 MB\n"
           "\tFlash Size: 61079552 Sectors\n\tBlock Size: 512 KB\n")
    if flash_capacity_bytes(out) != 61079552 * 512:
        errors.append(f"flash_capacity_bytes: {flash_capacity_bytes(out)}")
    if flash_capacity_bytes("Flash Size: 29824 MB") != 29824 * 1024 ** 2:
        errors.append("flash_capacity_bytes ignores the MB line")
    if flash_capacity_bytes("Read Flash Info failed!") is not None:
        errors.append("flash_capacity_bytes found a size in a failure")

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    window._cached_flash_info = None
    calls = []
    real_run = ops.subprocess.run
    ops.subprocess.run = lambda cmd, *a, **k: calls.append(cmd) or sp.CompletedProcess(cmd, 0, out, "")
    try:
        first = ops.get_flash_capacity_bytes(window)[0]
        second = ops.get_flash_capacity_bytes(window)[0]
    finally:
        ops.subprocess.run = real_run
        window.cleanup()
        window.deleteLater()
        app.processEvents()
    if (first, second, len(calls)) != (61079552 * 512, 61079552 * 512, 1):
        errors.append(f"capacity {first}, then cached {second}, {len(calls)} rfi call(s)")


def check_idb_command():
    """A NEWIDB Loader goes into the boot area as a verified bootloader
    image at sector 0x40 (ul writes it in a layout an RK3576 rejects); an
    old-format Loader still uses ul."""
    import importlib.util
    import time as _time

    from rkdeveloptool_gui import operations as ops

    spec = importlib.util.spec_from_file_location(
        "loader_tests", os.path.join(os.path.dirname(os.path.abspath(__file__)), "loader_merge.py"))
    source = open(spec.origin).read().split("\ncheck_new()\n")[0]
    scope = {"__name__": "loader_tests"}
    exec(compile(source, spec.origin, "exec"), scope)
    lm = scope["loader_merge"]
    work = tempfile.mkdtemp(dir=_tmp)
    new = os.path.join(work, "new.bin")
    old = os.path.join(work, "old.bin")
    with open(new, "wb") as f:
        f.write(lm.merge(lm.parse_ini(scope["NEW_INI"]), scope["NEW_BLOBS"].__getitem__, _time.localtime()))
    with open(old, "wb") as f:
        f.write(lm.merge(lm.parse_ini(scope["OLD_INI"]), scope["OLD_BLOBS"].__getitem__, _time.localtime()))
    cmd = ops.loader_to_flash_command(new, work)
    if cmd[1:3] != ["wl", "0x40"] or not os.path.isfile(cmd[3]):
        errors.append(f"NEWIDB Loader written with {cmd}")
    if ops.loader_to_flash_command(old, work)[1:] != ["ul", old]:
        errors.append("an old-format Loader isn't written with ul")


def check_command_chain(app):
    """A callback that starts the next command right away (its worker
    already gone) keeps that command's callback, and the window stays busy
    while it runs."""
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    seen = []

    def second(success, output):
        seen.append("second")

    def first(success, output):
        seen.append("first")
        window.command_worker.wait(5000)       # the worker has exited
        window.run_command([RKTOOL, "rfi"], "reading_flash_info", second)
        seen.append(("busy", window._command_active))

    try:
        window.run_command([RKTOOL, "ld"], "reading_flash_info", first)
        end = time.time() + 10
        while "second" not in seen and time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        if seen[:3] != ["first", ("busy", True), "second"]:
            errors.append(f"chained commands: {seen}")
        if window._command_active:
            errors.append("the window stays busy after the chain finished")
    finally:
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_flash_options(app):
    """The Parameter tab's options take effect: verify shares the burn
    confirmation's setting, erase runs ef before a whole image, reset runs
    rd after it, retries set how often a full-flash step is retried, and
    the timeout reaches the command worker."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops

    work = tempfile.mkdtemp(dir=_tmp)
    disk = os.path.join(work, "disk.img")
    with open(disk, "wb") as f:
        f.write(b"\0" * 510 + b"\x55\xaa" + b"\0" * 1536)
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    s = window.settings
    try:
        window.verify_after_burn.setChecked(True)
        if s.get_str(app_settings.KEY_VERIFY_AFTER_WRITE) != "1":
            errors.append("Verify After Burn isn't the burn confirmation's setting")
        window.timeout_spinbox.setValue(45)
        window.retry_count_spinbox.setValue(0)
        if (s.get_int(app_settings.KEY_IDLE_TIMEOUT), s.get_int(app_settings.KEY_STEP_RETRIES)) != (45, 0):
            errors.append("timeout/retries aren't saved")

        ran = []

        def fake_run(cmd, key, callback=None):
            ran.append(cmd[1])
            QTimer.singleShot(0, lambda: callback and callback(True, ""))

        real = (window.run_command, QMessageBox.exec)
        window.run_command = fake_run
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Yes
        window.command_worker = None
        window.current_device, window.device_mode, window.loader_loaded = "dev", "Loader", True
        try:
            for erase, reset, want in ((True, True, ["ef", "wl", "rd"]), (False, False, ["wl"])):
                window.verify_after_burn.setChecked(False)
                window.erase_before_burn.setChecked(erase)
                window.reset_after_burn.setChecked(reset)
                ran.clear()
                ops._burn_file(window, disk, "0x0", lambda p: [ops.RKTOOL, "wl", "0x0", p])
                end = time.time() + 5
                while time.time() < end and len(ran) < len(want):
                    app.processEvents()
                    time.sleep(0.01)
                for _ in range(30):
                    app.processEvents()
                    time.sleep(0.005)
                if ran != want:
                    errors.append(f"erase={erase} reset={reset}: ran {ran}, want {want}")
            # Retries 0: a failed full-flash step isn't tried again.
            ran.clear()
            window.run_command = lambda cmd, key, cb=None: ran.append(cmd[1]) or QTimer.singleShot(
                0, lambda: cb(False, "boom"))
            real_msg = ops._show_rkfw_message
            ops._show_rkfw_message = lambda *a, **k: None
            tmp = tempfile.mkdtemp(dir=work)
            window._rkfw_flashing = True
            ops._run_rkfw_steps(window, [([ops.RKTOOL, "gpt", "x"], "importing_gpt", "gpt")], 0, tmp)
            end = time.time() + 5
            while time.time() < end and window._rkfw_flashing:
                app.processEvents()
                time.sleep(0.01)
            ops._show_rkfw_message = real_msg
            if ran != ["gpt"]:
                errors.append(f"retries 0 still retried: {ran}")
        finally:
            window.run_command, QMessageBox.exec = real
            window.reset_after_burn.setChecked(False)
            window.erase_before_burn.setChecked(False)
            window.verify_after_burn.setChecked(False)

        # The timeout reaches the worker.
        window.command_worker = None
        window.run_command([RKTOOL, "ld"], "reading_flash_info")
        timed = window.command_worker.idle_timeout
        window.command_worker.wait(5000)
        app.processEvents()
        if timed != 45:
            errors.append(f"idle timeout {timed}, want 45")

        # ef reports "total N, current M" (sectors): that is its progress.
        from rkdeveloptool_gui.workers import CommandWorker
        worker = CommandWorker(["ef"], "erase_flash", window.manager)
        if worker._extract_progress("Erase Flash total 61079552, current 30539776") != 50:
            errors.append("ef's progress lines aren't read as progress")
    finally:
        s.set(app_settings.KEY_IDLE_TIMEOUT, str(app_settings.DEFAULT_IDLE_TIMEOUT_S))
        s.set(app_settings.KEY_STEP_RETRIES, str(app_settings.DEFAULT_STEP_RETRIES))
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_idle_timeout(app):
    """A command that stops printing is stopped after the idle timeout."""
    from rkdeveloptool_gui.workers import CommandWorker

    hang = os.path.join(_tmp, "hang.sh")
    with open(hang, "w") as f:
        f.write("#!/bin/sh\necho start\nsleep 30\n")
    os.chmod(hang, 0o755)
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    worker = CommandWorker([hang], "reading_flash_info", window.manager)
    worker.idle_timeout = 2
    got = []
    worker.finished_signal.connect(lambda ok, msg: got.append(ok))
    started = time.time()
    worker.start()
    worker.wait(15000)
    app.processEvents()
    took = time.time() - started
    if got != [False] or not worker.timed_out or took > 10:
        errors.append(f"idle timeout: result {got}, timed_out {worker.timed_out}, {took:.1f}s")
    window.cleanup()
    window.deleteLater()
    app.processEvents()


def check_partition_erase(app):
    """Erase in a partition row writes zeros over the start of that
    partition with wl (rkdeveloptool's ef can't erase one partition), and
    No, the default, does nothing."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    window.partitions = {"boot": {"address": "0x4000", "size": "0x2000"},
                         "rootfs": {"address": "0x8000", "size": "unknown"}}
    ops.populate_partition_table(window)
    ran, answer, defaults = [], [QMessageBox.StandardButton.Yes], []

    def fake_run(cmd, key, callback=None):
        ran.append((cmd[1], cmd[2], os.path.getsize(cmd[3]), key))
        QTimer.singleShot(0, lambda: callback and callback(True, ""))

    real = (window.run_command, QMessageBox.exec)
    window.run_command = fake_run
    QMessageBox.exec = lambda self: defaults.append(self.defaultButton() is self.button(
        QMessageBox.StandardButton.No)) or answer[0]
    try:
        row_buttons = [b.text() for b in window.partition_table.cellWidget(0, 3).findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
        if window.tr("action_erase") not in row_buttons:
            errors.append(f"partition row buttons: {row_buttons}")
        ops.erase_partition(window, "boot")
        ops.erase_partition(window, "rootfs")
        answer[0] = QMessageBox.StandardButton.No
        ops.erase_partition(window, "boot")
        for _ in range(20):
            app.processEvents()
        want = [("wl", "0x4000", 0x2000 * 512, "erase_partition"),
                ("wl", "0x8000", ops.ERASE_PARTITION_BYTES, "erase_partition")]
        if ran != want or defaults != [True, True, True]:
            errors.append(f"partition erase ran {ran}, No default {defaults}")
    finally:
        window.run_command, QMessageBox.exec = real
        window.cleanup()
        window.deleteLater()
        app.processEvents()


def check_dangerous_confirmations(app):
    """Erasing the whole storage needs "I understand" ticked before Erase
    can be clicked, Cancel is the default, and the command is a bare ef.
    Changing storage asks first, No by default."""
    from PySide6.QtWidgets import QMessageBox

    from rkdeveloptool_gui import operations as ops
    from rkdeveloptool_gui import ui_panels

    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    window.stop_device_detection()
    ran, seen = [], []
    real = (window.run_command, QMessageBox.exec)
    window.run_command = lambda cmd, key, cb=None: ran.append(cmd[1:])

    def erase_dialog(tick):
        def fake(self):
            erase = next(b for b in self.buttons() if b.text() == window.tr("erase_all_btn"))
            seen.append((erase.isEnabled(), self.defaultButton() is self.button(
                QMessageBox.StandardButton.Cancel)))
            if tick:
                self.checkBox().setChecked(True)
            erase.click()
            return 0
        return fake

    def answer(button):
        def fake(self):
            seen.append(self.defaultButton() is self.button(QMessageBox.StandardButton.No))
            return button
        return fake

    try:
        QMessageBox.exec = erase_dialog(tick=False)
        ops.erase_all_storage(window)
        QMessageBox.exec = erase_dialog(tick=True)
        ops.erase_all_storage(window)
        if ran != [["ef"]] or seen != [(False, True), (False, True)]:
            errors.append(f"erase all: ran {ran}, (Erase enabled, Cancel default) {seen}")
        ran.clear()
        seen.clear()
        if window.change_storage_combo.count():
            QMessageBox.exec = answer(QMessageBox.StandardButton.No)
            ui_panels.change_storage(window)
            QMessageBox.exec = answer(QMessageBox.StandardButton.Yes)
            ui_panels.change_storage(window)
            if [r[0] for r in ran] != ["cs"] or seen != [True, True]:
                errors.append(f"change storage: ran {ran}, No default {seen}")
    finally:
        window.run_command, QMessageBox.exec = real
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
    check_dangerous_confirmations(app)
    # Reset After Burn defaults to on; the write tests below count commands
    # without the reset, and check_flash_options covers it.
    AppSettings().set(app_settings.KEY_RESET_AFTER_WRITE, "0")
    check_flash_options(app)
    check_idle_timeout(app)
    check_partition_erase(app)
    check_rkfw_read_back(app)
    check_reset_after_write(app)
    check_loader_before_write(app)
    check_rfi_capacity(app)
    check_idb_command()
    check_command_chain(app)
    check_fetch_loader(app)
    check_storage_not_switched(app)
    check_gpt_import_export(app)
    check_chip_and_device_lock(app)
    check_verify_after_write(app)
    check_progress(app)
    check_cancel(app)
    check_disconnect_during_write(app)
    check_failure_guidance(app)
    check_preflight(app)
    check_linux_usb_access(app)
    check_updates(app)
    check_settings_and_command_line(app)
    check_native_macos_style(app)
    check_layout(app)
    check_drag_and_drop(app)
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
