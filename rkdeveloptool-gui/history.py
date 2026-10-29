"""
Flash history: what was written to which chip, when, and how it went.

Kept as a small JSON list, newest first, in the app's data directory (next
to the settings file when RKDEVELOPTOOL_GUI_SETTINGS points elsewhere, as
the tests do). Like the settings, everything here is best-effort: a
missing or damaged file reads as an empty history and a failed write is
ignored, so flashing never depends on it.
"""
import json
import os
import time

MAX_ENTRIES = 200
FILE_NAME = "history.json"

# Results a flash can end with.
OK = "ok"
FAILED = "failed"
CANCELLED = "cancelled"
MISMATCH = "mismatch"        # read back differently from the image
UNVERIFIED = "unverified"    # written; the read-back couldn't confirm it


def history_path():
    override = os.environ.get("RKDEVELOPTOOL_GUI_SETTINGS")
    if override:
        return os.path.join(os.path.dirname(os.path.abspath(override)), FILE_NAME)
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return os.path.join(base, FILE_NAME)


def load():
    try:
        with open(history_path(), encoding="utf-8") as f:
            entries = json.load(f)
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    except (OSError, ValueError):
        return []


def _save(entries):
    path = history_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        partial = path + ".part"
        with open(partial, "w", encoding="utf-8") as f:
            json.dump(entries[:MAX_ENTRIES], f, ensure_ascii=False, indent=1)
        os.replace(partial, path)
    except OSError as e:
        print(f"Warning: could not save the flash history: {e}")


def add(image, result, kind="image", address="", loader="", chip="", seconds=None, note=""):
    """Record one flash. image is the file the user chose (an .img.xz stays
    an .img.xz, not the temporary decompressed copy)."""
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "image": image or "",
        "kind": kind,
        "address": address or "",
        "loader": loader or "",
        "chip": chip or "",
        "result": result,
        "seconds": None if seconds is None else int(seconds),
        "note": note or "",
    }
    _save([entry] + load())
    return entry


def clear():
    _save([])
