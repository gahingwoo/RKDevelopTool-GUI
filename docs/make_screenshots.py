"""
Render the README screenshots into docs/images, in English and Chinese.

    pip install .   # the app as it will ship
    python docs/make_screenshots.py

Run it on macOS for the native look. The windows are drawn off screen
(opacity 0), nothing talks to a board (rkdeveloptool is a stub), and the
settings and history live in a temporary folder. The board, image and
numbers are staged: an ArmSoM CM5 (RK3576) in Maskrom, as tested.
"""
import os
import stat
import sys
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="rkgui-shots-")
_stub = os.path.join(_tmp, "rkdeveloptool")
with open(_stub, "w") as f:
    f.write('#!/bin/sh\necho "rkdeveloptool ver 1.32"\nexit 0\n')
os.chmod(_stub, os.stat(_stub).st_mode | stat.S_IXUSR)
os.environ["RKDEVELOPTOOL_BIN"] = _stub
os.environ["RKDEVELOPTOOL_GUI_SETTINGS"] = os.path.join(_tmp, "settings.ini")
os.environ["RKDEVELOPTOOL_GUI_NO_WIZARD"] = "1"
os.environ["RKDEVELOPTOOL_GUI_UPDATE_URL"] = "file://" + os.path.join(_tmp, "none.json")

from PySide6.QtCore import QPoint                       # noqa: E402
from PySide6.QtGui import QPainter, QPixmap             # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication(sys.argv)

from rkdeveloptool_gui import history                     # noqa: E402
from rkdeveloptool_gui import operations as ops          # noqa: E402
from rkdeveloptool_gui import settings as app_settings   # noqa: E402
from rkdeveloptool_gui.maskrom_help import show_maskrom_help  # noqa: E402
from rkdeveloptool_gui.progress import format_eta, format_speed  # noqa: E402
from rkdeveloptool_gui.rkdevtoolgui import RKDevToolGUI, TranslationManager  # noqa: E402
from rkdeveloptool_gui.settings import AppSettings       # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
DEVICE = "DevNo=1\tVid=0x2207,Pid=0x350e,LocationID=101\tMaskrom"
IMAGE = "~/Downloads/armsom-cm5-rk3576-debian12-server.img.xz"
RAW = "~/Downloads/armsom-cm5-rk3576-debian12-server.img"
LOADER = "~/Downloads/rk3576_spl_loader_v1.09.107.bin"
CAPACITY = 61079552 * 512          # the CM5's eMMC, from rfi


def settle(ms=300):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def save(pixmap, name, lang):
    path = os.path.join(OUT, f"{name}_{lang}.png")
    pixmap.save(path)
    print("wrote", path)


def make_window(lang):
    settings = AppSettings()
    settings.set(app_settings.KEY_THEME, "dark")
    settings.set(app_settings.KEY_STYLE, "macOS")
    settings.set(app_settings.KEY_LANGUAGE, lang)
    window = RKDevToolGUI(TranslationManager(lang=lang, settings=settings), settings=settings)
    window.stop_device_detection()
    window.setWindowOpacity(0.0)
    window.show()
    settle()
    # As narrow as the layout allows, so nothing is cut off on the right.
    window.resize(max(1300, window.minimumSizeHint().width()), 1000)
    settle()
    # Connected in Maskrom with the Loader running; no "load it now?" prompt.
    window.maskrom_device_shown_hint = True
    real_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.No
    try:
        window.on_device_found([DEVICE], "Maskrom", "RK3576")
    finally:
        QMessageBox.exec = real_exec
    window.loader_loaded = True
    settle()
    return window


def home(window, lang):
    """Writing a decompressed image: overall progress, speed, time left."""
    tr = window.tr
    window.tab_widget.setCurrentWidget(window.download_tab)
    window.image_path.setText(IMAGE)
    window.loader_path.setText(LOADER)
    window.equiv_command_field.setText(f"rkdeveloptool wl 0x0 {RAW}")
    window.log_widget.clear_log()
    for line in (f"[OK] {tr('decompress_done').format(RAW)}",
                 f"[OK] {tr('loader_loaded_success')}",
                 "Write LBA from file (46%)"):
        window.log_message(line)
    stage = tr("stage_writing").format("armsom-cm5-rk3576-debian12-server.img")
    window.progress_bar.setValue(46)
    window.progress_label.setText(" · ".join(
        (f"{stage} 46%", format_speed(21.4e6), format_eta(tr, 71))))
    settle()
    save(window.grab(), "home", lang)


def idle(window):
    """No write in progress: an empty log and a ready progress row."""
    window.log_widget.clear_log()
    window.equiv_command_field.clear()
    window.progress_bar.setValue(0)
    window.progress_label.setText(window.tr("ready_status"))


def preflight(window, lang):
    """The burn confirmation with its checks."""
    raw = os.path.join(_tmp, "armsom-cm5-rk3576-debian12-server.img")
    with open(raw, "wb") as f:
        f.write(b"\0" * 510 + b"\x55\xaa")
        f.truncate(2_684_354_560)                       # sparse, 2.5 GB
    checks = ops.preflight_checks(window, raw, "0x0", CAPACITY)
    shots = []
    real_exec = QMessageBox.exec

    def grab(box):
        settle(100)
        shots.append(box.grab())
        return QMessageBox.StandardButton.No

    QMessageBox.exec = grab
    try:
        ops._show_burn_confirm(window, os.path.basename(raw), 2_684_354_560, "2.50 GB",
                               "3f9a1c0e5b7d42a8c6e1f0b9d2a7c4e5", "0x0",
                               window.change_storage_combo.currentText(),
                               ops.get_storage_info(window, window.change_storage_combo.currentData()),
                               checks, True)
    finally:
        QMessageBox.exec = real_exec
    save(shots[0], "preflight", lang)


def history_tab(window, lang):
    """Past flashes, newest first."""
    history.clear()
    entries = (
        ("/Users/demo/Downloads/armsom-cm5-rk3576-debian12-xfce.img", history.OK, "update.img", "", 254, ""),
        ("/Users/demo/Downloads/armsom-cm5-rk3576-debian12-server.img.xz", history.FAILED, "image", "0x0", 41, ""),
        ("/Users/demo/Downloads/armsom-cm5-rk3576-debian12-server.img.xz", history.OK, "image", "0x0", 183,
         window.tr("history_verified")),
    )
    for image, result, kind, address, seconds, note in reversed(entries):
        history.add(image, result, kind=kind, address=address, chip="RK3576",
                    loader="/Users/demo/Downloads/rk3576_spl_loader_v1.09.107.bin",
                    seconds=seconds, note=note)
    # Spread the times out: newest a few minutes ago, the others before it.
    now = time.time()
    entries = history.load()
    for entry, minutes_ago in zip(entries, (6, 19, 27)):
        entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - minutes_ago * 60))
    history._save(entries)
    window.refresh_history()
    idle(window)
    window.tab_widget.setCurrentWidget(window.history_tab)
    settle()
    save(window.grab(), "history", lang)


def search(window, lang):
    """Ctrl/Cmd+K: the search window with what matches "backup"."""
    idle(window)
    window.tab_widget.setCurrentIndex(0)
    palette = window.search_palette
    palette.open()
    palette.setWindowOpacity(0.0)
    palette.field.setText("备份" if lang == "zh" else "backup")
    settle()
    shot = window.grab()
    painter = QPainter(shot)
    corner = palette.mapToGlobal(QPoint(0, 0)) - window.mapToGlobal(QPoint(0, 0))
    painter.drawPixmap(corner, palette.grab())
    painter.end()
    palette.hide()
    save(crop_top(shot), "search", lang)


def crop_top(shot):
    """The top of the window, where the search window opens."""
    ratio = shot.devicePixelRatio()
    piece = shot.copy(0, 0, shot.width(), int(560 * ratio))
    piece.setDevicePixelRatio(ratio)
    return piece


def maskrom(window, lang):
    dialog = show_maskrom_help(window)
    dialog.setWindowOpacity(0.0)
    settle()
    save(dialog.grab(), "maskrom", lang)
    dialog.close()


def main():
    os.makedirs(OUT, exist_ok=True)
    for lang in ("en", "zh"):
        window = make_window(lang)
        for shot in (home, preflight, history_tab, search, maskrom):
            shot(window, lang)
            settle()
        window.cleanup()
        window.deleteLater()
        settle()
    history.clear()


if __name__ == "__main__":
    main()
