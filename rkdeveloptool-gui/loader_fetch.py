"""
Gets a Loader for the connected chip: downloads its RKBOOT ini and blobs
from Rockchip's rkbin repository and builds the Loader with loader_merge.
"""
import os
import re
import urllib.error
import urllib.request

from PySide6.QtCore import QThread, Signal

from . import __version__, loader_merge
from .updater import _open, describe_error

RKBIN_REPO = "https://github.com/rockchip-linux/rkbin"
RKBIN_RAW = "https://raw.githubusercontent.com/rockchip-linux/rkbin/{ref}/"
RKBIN_HEAD_API = "https://api.github.com/repos/rockchip-linux/rkbin/commits/master"
# Lets tests point the download at a local copy (a file:// URL ending in /).
URL_ENV = "RKDEVELOPTOOL_GUI_RKBIN_URL"

# The chip number rkdeveloptool reports doesn't always match the name of
# the chip's RKBOOT ini: the ini's [CHIP_NAME] holds the reported number,
# the file is named after the product.
INI_BY_CHIP = {
    "RK330C": "RK3399MINIALL.ini",
    "RK322H": "RK3328MINIALL.ini",
    "RK320A": "RK3288MINIALL.ini",
    "RK330A": "RK3368MINIALL.ini",
    "RK330B": "RK3366MINIALL.ini",
    "RK350F": "RK3506MINIALL.ini",
    "RK351A": "RK3572MINIALL.ini",
    "RK351B": "RK3538MINIALL.ini",
    "RK312A": "RK3128MINIALL.ini",
    "RK303A": "RK3036MINIALL.ini",
    "RK322A": "RK322XMINIALL.ini",
    "RK180A": "RK1808MINIALL.ini",
    "RKPX30": "PX30MINIALL.ini",
    "RK110A": "RV110XMINIALL.ini",
    "RV110E": "RV1103BMINIALL.ini",
    "RV110F": "RV1126BMINIALL.ini",
}


def ini_candidates(chip):
    """RKBOOT ini names to try for a chip name such as 'RK3576' or 'RK330C'."""
    chip = (chip or "").strip().upper()
    if not re.fullmatch(r"(RK|RV|PX)[0-9A-Z]{2,6}", chip):
        return []
    names = []
    if chip in INI_BY_CHIP:
        names.append(INI_BY_CHIP[chip])
    names.append(f"{chip}MINIALL.ini")
    # rkdeveloptool reports an RV1106 as "1106", which reads as RK1106.
    if chip.startswith("RK") and chip[2:].isdigit():
        names.append(f"RV{chip[2:]}MINIALL.ini")
    return list(dict.fromkeys(names))


def _get(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": f"RKDevelopTool-GUI/{__version__}",
        "Accept": "application/vnd.github.sha" if url == RKBIN_HEAD_API else "*/*",
    })
    with _open(request) as response:
        return response.read()


def _base_url():
    """The rkbin base URL and the commit it is pinned to (None for an
    override). Pinning keeps the ini and its blobs from one commit even if
    rkbin changes mid-download."""
    override = os.environ.get(URL_ENV)
    if override:
        return override, None
    try:
        sha = _get(RKBIN_HEAD_API).decode("ascii").strip()
    except (OSError, UnicodeDecodeError):
        sha = ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return RKBIN_RAW.format(ref="master"), None
    return RKBIN_RAW.format(ref=sha), sha


def _is_missing(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 404
    # file:// URLs raise URLError(FileNotFoundError).
    return isinstance(getattr(error, "reason", None), FileNotFoundError)


def fetch_loader(chip, dest_dir):
    """Build the Loader for `chip` into `dest_dir` and return
    (path, ini name, rkbin commit or None). A Loader already built under the
    same versioned name is reused. Raises LookupError when rkbin has nothing
    for the chip, OSError on network problems, LoaderMergeError on an ini
    this app can't build."""
    base, sha = _base_url()
    for ini_name in ini_candidates(chip):
        try:
            text = _get(base + "RKBOOT/" + ini_name).decode("utf-8", "replace")
        except urllib.error.URLError as e:
            if _is_missing(e):
                continue
            raise
        break
    else:
        raise LookupError(chip)

    options = loader_merge.parse_ini(text)
    name = os.path.basename(options["output"])
    if not name.endswith(".bin"):
        name += ".bin"
    path = os.path.join(dest_dir, name)
    if os.path.isfile(path):
        return path, ini_name, sha

    blobs = {blob: _get(base + blob) for blob in loader_merge.blob_paths(options)}
    data = loader_merge.merge(options, blobs.__getitem__)

    os.makedirs(dest_dir, exist_ok=True)
    partial = path + ".part"
    with open(partial, "wb") as f:
        f.write(data)
    os.replace(partial, path)
    return path, ini_name, sha


class LoaderFetchWorker(QThread):
    """Run fetch_loader() off the GUI thread.

    Emits:
        finished_ok(str, str, str) path, ini name, rkbin commit ('' if unknown)
        failed(str, str)          kind ('unsupported', 'bad_ini', or one of
                                  updater.describe_error's) and the raw error
    """

    finished_ok = Signal(str, str, str)
    failed = Signal(str, str)

    def __init__(self, chip, dest_dir, parent=None):
        super().__init__(parent)
        self.chip = chip
        self.dest_dir = dest_dir

    def run(self):
        try:
            path, ini_name, sha = fetch_loader(self.chip, self.dest_dir)
        except LookupError:
            self.failed.emit("unsupported", self.chip)
        except loader_merge.LoaderMergeError as e:
            self.failed.emit("bad_ini", str(e))
        except Exception as e:  # urllib raises a wide range; all mean "no answer"
            self.failed.emit(describe_error(e), str(e))
        else:
            self.finished_ok.emit(path, ini_name, sha or "")
