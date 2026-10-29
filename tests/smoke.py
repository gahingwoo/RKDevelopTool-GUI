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


def check_settings_and_command_line(app):
    """Settings dialog wiring and the manual command line."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QMessageBox

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


def check_layout(app):
    """The tab area is sized by the current tab (QTabWidget asks for the
    tallest one by default, which pushed the log down and squeezed its
    progress row onto it), and the progress row never overlaps the log."""
    window = RKDevToolGUI(TranslationManager(lang="en", settings=AppSettings()),
                          settings=AppSettings())
    try:
        window.resize(1300, 720)
        window.show()
        tabs = window.tab_widget
        tallest = max(tabs.widget(i).sizeHint().height() for i in range(tabs.count()))
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            for _ in range(10):
                app.processEvents()
            page = tabs.currentWidget()
            if page.sizeHint().height() < tallest - 50 and \
                    tabs.sizeHint().height() >= tallest:
                errors.append(f"tab {tabs.tabText(i)!r} asks for the tallest tab's height")
            log, bar = window.log_output.geometry(), window.progress_bar.geometry()
            if bar.top() <= log.bottom():
                errors.append(f"tab {tabs.tabText(i)!r}: progress row overlaps the log")
    finally:
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
    check_settings_and_command_line(app)
    check_native_macos_style(app)
    check_layout(app)
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
