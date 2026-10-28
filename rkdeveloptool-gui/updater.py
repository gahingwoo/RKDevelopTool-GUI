"""
Update check against the project's GitHub releases.

Only checks and points at the right download: the app is installed as a DMG,
an AppImage, a deb/rpm or a pip wheel, each updated its own way, so it never
replaces itself.
"""
import json
import os
import platform
import re
import shutil
import sys
import urllib.request

from PySide6.QtCore import QThread, Signal

from . import __version__

RELEASES_PAGE = "https://github.com/gahingwoo/RKDevelopTool-GUI/releases"
LATEST_API = "https://api.github.com/repos/gahingwoo/RKDevelopTool-GUI/releases/latest"
# Lets tests (and anyone mirroring releases) point the check elsewhere,
# including at a file:// URL.
URL_ENV = "RKDEVELOPTOOL_GUI_UPDATE_URL"
TIMEOUT_S = 8
# At most one automatic check per day.
AUTO_CHECK_INTERVAL_S = 24 * 3600


def parse_version(text):
    """'v5.10.1' -> (5, 10, 1). Anything after the numeric part (e.g. '-rc1')
    is ignored; returns None when there is no version number at all."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    if not match:
        return None
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(latest, current=__version__):
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def install_kind():
    """How this copy was installed: 'dmg', 'appimage', 'deb', 'rpm' or 'pip'."""
    if sys.platform == "darwin":
        return "dmg" if "__compiled__" in globals() or getattr(sys, "frozen", False) \
            or ".app/Contents/" in os.path.abspath(sys.executable) else "pip"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    # A Nuitka onefile build runs from a temp dir; argv[0] keeps the
    # installed path (/usr/lib/rkdeveloptool-gui/rkdevtoolgui for deb/rpm).
    for path in (sys.argv[0] if sys.argv else "", sys.executable):
        if os.path.abspath(path).startswith("/usr/lib/rkdeveloptool-gui/"):
            return "deb" if shutil.which("dpkg") else "rpm"
    return "pip"


def pick_asset(assets, kind=None, machine=None):
    """The download URL for this platform from a release's asset list, or
    None when there is no matching package (the release page is used then)."""
    kind = kind or install_kind()
    machine = (machine or platform.machine()).lower()
    arm = machine in ("arm64", "aarch64")
    patterns = {
        "dmg": r"-arm64\.dmg$" if arm else r"-x86_64\.dmg$",
        "appimage": r"-aarch64\.AppImage$" if arm else r"-x86_64\.AppImage$",
        "deb": r"_arm64\.deb$" if arm else r"_amd64\.deb$",
        "rpm": r"\.aarch64\.rpm$" if arm else r"\.x86_64\.rpm$",
    }
    pattern = patterns.get(kind)
    if not pattern:
        return None
    for asset in assets or []:
        name = asset.get("name", "")
        if re.search(pattern, name):
            return asset.get("browser_download_url")
    return None


def fetch_latest(url=None):
    """Return {'version', 'page', 'download', 'notes'} for the latest release.
    Raises OSError / ValueError on network or format problems."""
    url = url or os.environ.get(URL_ENV) or LATEST_API
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"RKDevelopTool-GUI/{__version__}",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        data = json.loads(response.read().decode("utf-8"))
    version = (data.get("tag_name") or "").lstrip("vV")
    if parse_version(version) is None:
        raise ValueError(f"unexpected release tag: {data.get('tag_name')!r}")
    return {
        "version": version,
        "page": data.get("html_url") or RELEASES_PAGE,
        "download": pick_asset(data.get("assets")),
        "notes": (data.get("body") or "").strip(),
    }


class UpdateCheckWorker(QThread):
    """Run fetch_latest() off the GUI thread.

    Emits:
        available(dict)   a newer release (see fetch_latest)
        up_to_date(str)   the latest released version, not newer than ours
        failed(str)       why the check failed (offline, rate limit, ...)
    """

    available = Signal(object)
    up_to_date = Signal(str)
    failed = Signal(str)

    def run(self):
        try:
            release = fetch_latest()
        except Exception as e:  # urllib raises a wide range; all mean "no answer"
            self.failed.emit(str(e))
            return
        if is_newer(release["version"]):
            self.available.emit(release)
        else:
            self.up_to_date.emit(release["version"])
