"""
Desktop notifications when something long finishes while the app is in
the background, and the write's progress on the Dock icon (macOS).

macOS: Notification Center through osascript. Linux: notify-send when it's
there, otherwise a tray icon's balloon. Notifications can be turned off
in Settings.
"""
import json
import shutil
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from . import settings as app_settings


def _app_active():
    return QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive


def _send(title, text, gui=None):
    text = " ".join(text.split())          # one line; AppleScript has no \n
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(text)} with title {json.dumps(title)}"
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "--app-name=RKDevelopTool GUI", title, text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif gui is not None:
        from PySide6.QtWidgets import QSystemTrayIcon
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = getattr(gui, "_notify_tray", None)
            if tray is None:
                tray = gui._notify_tray = QSystemTrayIcon(gui.windowIcon(), gui)
            tray.show()
            tray.showMessage(title, text)


def notify(gui, title, text):
    """Notify unless the user is looking at the app or turned it off.
    Returns whether a notification went out."""
    settings = getattr(gui, "settings", None)
    if settings is not None and not settings.get_flag(app_settings.KEY_NOTIFY, True):
        return False
    if _app_active():
        return False
    try:
        _send(title, text, gui)
    except OSError:
        return False
    return True


def set_progress(percent):
    """Show a write's percentage on the Dock icon; None clears it."""
    app = QGuiApplication.instance()
    if app is not None and hasattr(app, "setBadgeNumber"):
        app.setBadgeNumber(int(percent) if percent else 0)
