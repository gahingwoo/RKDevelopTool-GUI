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
import ssl
import sys
import urllib.error
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
    asset = pick_asset_info(assets, kind, machine)
    return asset["url"] if asset else None


def pick_asset_info(assets, kind=None, machine=None):
    """{url, name, size, digest} of this platform's package, or None."""
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
            return {"url": asset.get("browser_download_url"), "name": name,
                    "size": asset.get("size") or 0, "digest": asset.get("digest") or ""}
    return None


# CA bundles to fall back on when Python's own OpenSSL has none. python.org's
# macOS Python ships an empty cert directory until "Install Certificates" is
# run, and a bundled Python may point at the build machine's paths.
_CA_BUNDLES = (
    "/etc/ssl/cert.pem",                                  # macOS, Alpine, Arch
    "/etc/ssl/certs/ca-certificates.crt",                 # Debian, Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",                   # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",                             # openSUSE
)


def _fallback_contexts():
    """SSL contexts built from CA bundles found on this machine."""
    paths = []
    try:
        import certifi
        paths.append(certifi.where())
    except ImportError:
        pass
    paths += [p for p in _CA_BUNDLES if os.path.isfile(p)]
    for path in paths:
        try:
            yield ssl.create_default_context(cafile=path)
        except (OSError, ssl.SSLError):
            continue


def _is_cert_error(error):
    reason = getattr(error, "reason", error)
    return isinstance(reason, ssl.SSLCertVerificationError)


def _open(request):
    """urlopen with the default trust store, retrying with the machine's CA
    bundles when that store can't verify the certificate."""
    try:
        return urllib.request.urlopen(request, timeout=TIMEOUT_S)
    except urllib.error.URLError as e:
        if not _is_cert_error(e):
            raise
        first_error = e
    for context in _fallback_contexts():
        try:
            return urllib.request.urlopen(request, timeout=TIMEOUT_S, context=context)
        except urllib.error.URLError as e:
            if not _is_cert_error(e):
                raise
    raise first_error


def describe_error(error):
    """Short, translatable reason for a failed check: 'cert', 'offline',
    'rate_limit' or 'other'."""
    if _is_cert_error(error):
        return "cert"
    if isinstance(error, urllib.error.HTTPError) and error.code in (403, 429):
        return "rate_limit"
    if isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "offline"
    return "other"


def fetch_latest(url=None):
    """Return {'version', 'page', 'download', 'notes'} for the latest release.
    Raises OSError / ValueError on network or format problems."""
    url = url or os.environ.get(URL_ENV) or LATEST_API
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"RKDevelopTool-GUI/{__version__}",
    })
    with _open(request) as response:
        data = json.loads(response.read().decode("utf-8"))
    version = (data.get("tag_name") or "").lstrip("vV")
    if parse_version(version) is None:
        raise ValueError(f"unexpected release tag: {data.get('tag_name')!r}")
    return {
        "version": version,
        "page": data.get("html_url") or RELEASES_PAGE,
        "download": pick_asset(data.get("assets")),
        "asset": pick_asset_info(data.get("assets")),
        "notes": (data.get("body") or "").strip(),
    }


class UpdateCheckWorker(QThread):
    """Run fetch_latest() off the GUI thread.

    Emits:
        available(dict)   a newer release (see fetch_latest)
        up_to_date(str)   the latest released version, not newer than ours
        failed(str, str)  kind ('cert', 'offline', 'rate_limit', 'other')
                          and the raw error
    """

    available = Signal(object)
    up_to_date = Signal(str)
    failed = Signal(str, str)  # kind (see describe_error), raw message

    def run(self):
        try:
            release = fetch_latest()
        except Exception as e:  # urllib raises a wide range; all mean "no answer"
            self.failed.emit(describe_error(e), str(e))
            return
        if is_newer(release["version"]):
            self.available.emit(release)
        else:
            self.up_to_date.emit(release["version"])


# Installing an update in place
#
# Only for copies installed from a package this app knows how to replace:
# the AppImage file itself, the .app from the DMG, or the deb/rpm through
# the system's package manager. The download must match the SHA-256 digest
# GitHub publishes for the release asset; without one nothing is installed.
SELF_UPDATE_KINDS = ("appimage", "dmg", "deb", "rpm")
# Lets tests point the DMG install at a copy of the app elsewhere.
APP_PATH_ENV = "RKDEVELOPTOOL_GUI_APP_PATH"


class UpdateError(Exception):
    """An update couldn't be downloaded, checked or installed."""


def can_self_update(release, kind=None):
    asset = (release or {}).get("asset") or {}
    return (kind or install_kind()) in SELF_UPDATE_KINDS and bool(asset.get("url")) \
        and str(asset.get("digest", "")).startswith("sha256:")


def download(asset, dest_dir, progress=None, cancelled=lambda: False):
    """Download a release asset into dest_dir, checking its SHA-256."""
    import hashlib
    want = str(asset.get("digest", ""))
    if not want.startswith("sha256:"):
        raise UpdateError("the release doesn't publish a checksum for this package")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, os.path.basename(asset["name"]))
    request = urllib.request.Request(asset["url"], headers={
        "User-Agent": f"RKDevelopTool-GUI/{__version__}"})
    digest = hashlib.sha256()
    done, total = 0, int(asset.get("size") or 0)
    with _open(request) as response, open(path + ".part", "wb") as f:
        while True:
            if cancelled():
                raise UpdateError("cancelled")
            chunk = response.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(min(done * 100 // total, 100))
    if digest.hexdigest() != want.split(":", 1)[1].lower():
        os.remove(path + ".part")
        raise UpdateError("the download doesn't match the release's checksum")
    os.replace(path + ".part", path)
    return path


def app_bundle_path():
    """The .app this copy runs from (macOS), or None."""
    override = os.environ.get(APP_PATH_ENV)
    if override:
        return override
    path = os.path.abspath(sys.executable)
    while path and path != "/":
        if path.endswith(".app"):
            return path
        path = os.path.dirname(path)
    return None


def _run(cmd, **kwargs):
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise UpdateError((result.stderr or result.stdout or f"{cmd[0]} failed").strip()[-400:])
    return result.stdout


def _install_appimage(path):
    target = os.environ.get("APPIMAGE")
    if not target:
        raise UpdateError("not running from an AppImage")
    staged = target + ".new"
    shutil.copyfile(path, staged)
    os.chmod(staged, 0o755)
    os.replace(staged, target)      # atomic; the running copy keeps its inode
    return [target]


def _install_dmg(path):
    import shlex
    import tempfile
    target = app_bundle_path()
    if not target:
        raise UpdateError("not running from an .app")
    mount = tempfile.mkdtemp(prefix="rkdevtool_update_")
    _run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mount, path])
    try:
        apps = [n for n in os.listdir(mount) if n.endswith(".app")]
        if not apps:
            raise UpdateError("the disk image has no .app")
        source = os.path.join(mount, apps[0])
        parent, name = os.path.split(target)
        staged, old = os.path.join(parent, f".{name}.new"), os.path.join(parent, f".{name}.old")
        script = (f"rm -rf {shlex.quote(staged)} {shlex.quote(old)} && "
                  f"ditto {shlex.quote(source)} {shlex.quote(staged)} && "
                  f"mv {shlex.quote(target)} {shlex.quote(old)} && "
                  f"mv {shlex.quote(staged)} {shlex.quote(target)} && "
                  f"rm -rf {shlex.quote(old)} && "
                  f"(xattr -dr com.apple.quarantine {shlex.quote(target)} || true)")
        if os.access(parent, os.W_OK) and os.access(target, os.W_OK):
            _run(["/bin/sh", "-c", script])
        else:
            # macOS's own administrator prompt does the copy.
            _run(["osascript", "-e",
                  f"do shell script {json.dumps(script)} with administrator privileges"])
    finally:
        _run(["hdiutil", "detach", "-quiet", mount])
        shutil.rmtree(mount, ignore_errors=True)
    return ["open", "-n", target]


def _install_package(path, kind):
    """deb/rpm through the package manager, with the system's own
    authentication dialog (pkexec)."""
    if not shutil.which("pkexec"):
        raise UpdateError(f"pkexec isn't available; install {path} with your package manager")
    if kind == "deb":
        cmd = (["apt-get", "install", "-y", path] if shutil.which("apt-get")
               else ["dpkg", "-i", path])
    elif shutil.which("dnf"):
        cmd = ["dnf", "install", "-y", path]
    elif shutil.which("zypper"):
        cmd = ["zypper", "--non-interactive", "install", "--allow-unsigned-rpm", path]
    else:
        cmd = ["rpm", "-U", path]
    _run(["pkexec"] + cmd)
    return [os.path.abspath(sys.argv[0])]


def install(path, kind=None):
    """Install a downloaded package over this copy; return the command that
    starts the new version."""
    kind = kind or install_kind()
    if kind == "appimage":
        return _install_appimage(path)
    if kind == "dmg":
        return _install_dmg(path)
    if kind in ("deb", "rpm"):
        return _install_package(path, kind)
    raise UpdateError(f"can't update a {kind} install in place")


class UpdateInstallWorker(QThread):
    """Download, check and install an update off the GUI thread.

    Emits progress(int) while downloading, then installed(list) with the
    command that starts the new version, or failed(str).
    """

    progress = Signal(int)
    installing = Signal()
    installed = Signal(object)
    failed = Signal(str)

    def __init__(self, release, dest_dir, parent=None):
        super().__init__(parent)
        self.release = release
        self.dest_dir = dest_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            path = download(self.release["asset"], self.dest_dir, self.progress.emit,
                            lambda: self._cancel)
            self.installing.emit()
            self.installed.emit(install(path))
        except Exception as e:  # network, checksum, installer: all mean "not installed"
            self.failed.emit(str(e))
