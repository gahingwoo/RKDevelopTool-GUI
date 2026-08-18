"""
Persistent application settings for RKDevelopTool GUI.

Backed by QSettings, so each platform gets its native store (registry on
Windows, plist on macOS, an ini file under ~/.config on Linux) without us
having to pick a file location.

Everything here is best-effort: a corrupt or unreadable settings store must
never stop the app from starting, so reads fall back to the supplied default
and writes are swallowed. Callers can rely on a value always coming back.
"""
from PySide6.QtCore import QSettings, QByteArray
from PySide6.QtWidgets import QFileDialog

ORGANIZATION = "gahingwoo"
APPLICATION = "RKDevelopTool-GUI"

# Keys. Grouped by prefix so the on-disk file stays readable if a user opens it.
KEY_LANGUAGE = "ui/language"
KEY_THEME = "ui/theme"
KEY_STYLE = "ui/style"
KEY_GEOMETRY = "window/geometry"
KEY_SPLITTER = "window/splitter"
KEY_LAST_DIR = "paths/last_dir"
KEY_LOADER_PATH = "paths/loader"
KEY_FIRMWARE_PATH = "paths/firmware"
KEY_IMAGE_PATH = "paths/image"


class AppSettings:
    """Thin, exception-proof wrapper around QSettings."""

    def __init__(self):
        try:
            self._settings = QSettings(ORGANIZATION, APPLICATION)
        except Exception as e:
            print(f"Warning: could not open settings store: {e}")
            self._settings = None

    def get(self, key, default=None):
        if self._settings is None:
            return default
        try:
            value = self._settings.value(key, default)
            return default if value is None else value
        except Exception as e:
            print(f"Warning: could not read setting {key}: {e}")
            return default

    def set(self, key, value):
        if self._settings is None:
            return
        try:
            self._settings.setValue(key, value)
        except Exception as e:
            print(f"Warning: could not write setting {key}: {e}")

    def get_str(self, key, default=""):
        """Read a value that must come back as a str.

        QSettings' ini backend returns everything as text, but the native
        Windows/macOS backends preserve types, so a value written as e.g. a
        QByteArray would otherwise leak a non-str into UI code.
        """
        value = self.get(key, default)
        if isinstance(value, str):
            return value
        return default

    def get_bytes(self, key):
        """Read a QByteArray value (window geometry and friends)."""
        value = self.get(key)
        return value if isinstance(value, QByteArray) else None

    def sync(self):
        """Flush pending writes to disk."""
        if self._settings is None:
            return
        try:
            self._settings.sync()
        except Exception as e:
            print(f"Warning: could not flush settings: {e}")


def _settings_of(gui):
    """Return the AppSettings attached to a window, or None."""
    return getattr(gui, "settings", None)


def _start_dir(gui, default_name=""):
    """Where a file dialog should open.

    Uses the directory of the last file the user picked, so the app reopens
    where they left off instead of at the process working directory. When a
    suggested filename is given it's joined onto that directory so save
    dialogs still prefill the name.
    """
    import os

    settings = _settings_of(gui)
    last_dir = settings.get_str(KEY_LAST_DIR, "") if settings else ""
    if last_dir and not os.path.isdir(last_dir):
        last_dir = ""
    if default_name:
        return os.path.join(last_dir, default_name) if last_dir else default_name
    return last_dir


def _remember(gui, path):
    """Record the directory of a chosen path for next time."""
    import os

    settings = _settings_of(gui)
    if not settings or not path:
        return
    directory = os.path.dirname(path)
    if directory:
        settings.set(KEY_LAST_DIR, directory)


def get_open_file(gui, caption, filter_str="", default_name=""):
    """QFileDialog.getOpenFileName that starts in - and updates - the last-used
    directory. Returns "" when cancelled, matching Qt."""
    path, _ = QFileDialog.getOpenFileName(
        gui, caption, _start_dir(gui, default_name), filter_str)
    _remember(gui, path)
    return path


def get_save_file(gui, caption, default_name="", filter_str=""):
    """QFileDialog.getSaveFileName variant of get_open_file()."""
    path, _ = QFileDialog.getSaveFileName(
        gui, caption, _start_dir(gui, default_name), filter_str)
    _remember(gui, path)
    return path


def get_directory(gui, caption):
    """QFileDialog.getExistingDirectory variant of get_open_file()."""
    path = QFileDialog.getExistingDirectory(gui, caption, _start_dir(gui))
    if path:
        settings = _settings_of(gui)
        if settings:
            # A directory pick is itself the location to return to, so store it
            # whole rather than its parent.
            settings.set(KEY_LAST_DIR, path)
    return path
