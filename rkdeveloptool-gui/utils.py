"""
Utility functions and helpers for RKDevelopTool GUI
"""
import re
import os
import sys
import shutil
import hashlib
import subprocess
import threading


def _candidate_tool_dirs():
    """Directories that may hold a bundled rkdeveloptool, most specific first."""
    dirs = []
    # Next to the running (frozen) executable, e.g. .app Contents/MacOS,
    # AppImage AppRun dir, or the onefile extraction dir.
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        dirs += [exe_dir, os.path.join(exe_dir, "bin"),
                 os.path.normpath(os.path.join(exe_dir, "..", "Resources"))]
    except Exception:
        pass
    # Next to this source module (running from a checkout).
    try:
        mod_dir = os.path.dirname(os.path.abspath(__file__))
        dirs += [mod_dir, os.path.join(mod_dir, "bin")]
    except Exception:
        pass
    # AppImage mount point.
    appdir = os.environ.get("APPDIR")
    if appdir:
        dirs += [os.path.join(appdir, "usr", "bin"),
                 os.path.join(appdir, "usr", "lib", "rkdeveloptool-gui")]
    # System install location used by the .deb / .rpm packages.
    dirs += ["/usr/lib/rkdeveloptool-gui", "/usr/libexec/rkdeveloptool-gui"]
    return dirs


def _is_executable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def saved_rkdeveloptool():
    """The rkdeveloptool path chosen in Settings, or "" for auto-detect."""
    try:
        from .settings import AppSettings, KEY_RKTOOL_PATH
        return AppSettings().get_str(KEY_RKTOOL_PATH, "")
    except Exception:
        return ""


def _find_rkdeveloptool(use_saved=True):
    """Locate rkdeveloptool: RKDEVELOPTOOL_BIN, the path chosen in Settings,
    a bundled copy, then PATH."""
    override = os.environ.get("RKDEVELOPTOOL_BIN")
    if _is_executable(override):
        return override
    if use_saved:
        saved = saved_rkdeveloptool()
        if _is_executable(saved):
            return saved
    name = "rkdeveloptool.exe" if os.name == "nt" else "rkdeveloptool"
    for d in _candidate_tool_dirs():
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return shutil.which("rkdeveloptool") or "rkdeveloptool"


RKTOOL = _find_rkdeveloptool()

# Held while something outside the command runner talks to the device (ppt,
# rfi). The device poller only runs its own device-opening `rci` when it can
# take this without waiting; otherwise that poll just enumerates. Two
# rkdeveloptool processes opening the board at once make one of them fail.
DEVICE_LOCK = threading.Lock()


def auto_detected_rkdeveloptool():
    """What auto-detection finds, ignoring the path chosen in Settings."""
    return _find_rkdeveloptool(use_saved=False)


def set_rkdeveloptool(path):
    """Switch the rkdeveloptool binary at runtime ('' = auto-detect).

    Modules took RKTOOL with `from .utils import RKTOOL` at import time, so
    their copies are updated too; ui_panels imports it at call time and
    picks up the new value by itself. Returns the path now in use.
    """
    global RKTOOL
    RKTOOL = path if _is_executable(path) else auto_detected_rkdeveloptool()
    package = __name__.rsplit(".", 1)[0]
    for name in ("operations", "workers", "rkdevtoolgui"):
        module = sys.modules.get(f"{package}.{name}")
        if module is not None and hasattr(module, "RKTOOL"):
            module.RKTOOL = RKTOOL
    return RKTOOL


def rkdeveloptool_version(path):
    """`rkdeveloptool -v` output for a given binary, or "" if it won't run."""
    try:
        result = subprocess.run([path, "-v"], capture_output=True, text=True, timeout=3)
        return (result.stdout or result.stderr).strip().splitlines()[0] if \
            (result.stdout or result.stderr).strip() else ""
    except (OSError, subprocess.SubprocessError):
        return ""

# Chip ID mapping (common Rockchip IDs)
CHIP_ID_MAP = {
    "0x330A": "RK3368",
    "0x330C": "RK3399",
    "0x3588": "RK3588",
    "0x3568": "RK3568",
    "0x3566": "RK3566",
    "0x3399": "RK3399",
    "0x3368": "RK3368",
    "0x3328": "RK3328",
    "0x3288": "RK3288",
    "0x3188": "RK3188",
    "0x3066": "RK3066",
}

# Older chips report an internal number instead of the product's. These
# pairs come from the [CHIP_NAME] in each chip's RKBOOT ini in rkbin.
INTERNAL_CHIP_NAMES = {
    "330A": "RK3368",
    "330B": "RK3366",
    "330C": "RK3399",
    "322H": "RK3328",
    "322A": "RK322X",
    "320A": "RK3288",
    "312A": "RK3128",
    "303A": "RK3036",
    "180A": "RK1808",
    "350F": "RK3506",
    "351A": "RK3572",
    "351B": "RK3538",
}

# Flash ID mapping (common manufacturers)
FLASH_ID_MAP = {
    "C8": "GigaDevice",
    "EF": "Winbond",
    "20": "XMC",
    "C2": "ESMT",
    "1C": "EON",
    "A1": "Fudan Micro",
    "5E": "Zbit",
    "0B": "XTX",
}

CHIP_FAMILIES = {
    "RK3066": "RK3066 Family",
    "RK3188": "RK3188 Family",
    "RK3288": "RK3288 Family",
    "RK3328": "RK3328 Family",
    "RK3368": "RK3368 Family",
    "RK3399": "RK3399 Family",
    "RK3566": "RK3566 Family",
    "RK3568": "RK3568 Family",
    "RK3588": "RK3588 Family"
}


class ToolValidator:
    """Checks if the required external tool is available."""

    @staticmethod
    def validate():
        try:
            subprocess.run([RKTOOL, "--version"], check=True, capture_output=True, text=True)
            return True
        except FileNotFoundError:
            return False
        except subprocess.CalledProcessError:
            return True


def parse_chip_info(chip_text):
    """Parse chip info and return readable chip name in RKxxxx format
    
    Handles multiple formats:
    - rkdeveloptool rci output: "Chip Info: 36 37 35 33 ..." (hex ASCII bytes,
      little-endian) -> "6753" reversed -> "RK3576"
    - Hex IDs: "0x330A" -> "RK3368"
    - Direct names: "RK3399" -> "RK3399"
    """
    if not chip_text:
        return "Unknown Chip"

    chip_text = chip_text.strip()

    # rkdeveloptool rci prints "Chip Info: 36 37 35 33 0 0 ...": the 16 chip
    # info bytes in unpadded hex (RKLog PrintBuffer, "%X"). The first four
    # are the chip number in ASCII, stored little-endian: 36 37 35 33 is
    # "6753", read backwards "3576", an RK3576.
    body = re.sub(r'^\s*Chip Info:\s*', '', chip_text, flags=re.I)
    byte_parts = body.split()
    if len(byte_parts) >= 4 and all(re.fullmatch(r'[0-9A-Fa-f]{1,2}', b) for b in byte_parts[:4]):
        try:
            raw = "".join(chr(int(b, 16)) for b in byte_parts[:4])
        except ValueError:
            raw = ""
        number = raw[::-1].upper()
        if number in INTERNAL_CHIP_NAMES:
            return INTERNAL_CHIP_NAMES[number]
        if re.fullmatch(r'[0-9A-Z]{4}', number):
            return f"RK{number}"

    # Try to extract chip ID in hex format
    match = re.search(r'0x[0-9A-Fa-f]+', chip_text)
    if match:
        chip_id = "0x" + match.group(0)[2:].upper()
        if chip_id in CHIP_ID_MAP:
            return CHIP_ID_MAP[chip_id]

    # Try to match chip name directly
    for chip_name in CHIP_FAMILIES.keys():
        if chip_name.lower() in chip_text.lower():
            return chip_name

    return chip_text


def flash_capacity_bytes(rfi_text):
    """Storage size in bytes from `rkdeveloptool rfi` output, or None.

    rfi prints the size twice, "Flash Size: 29824 MB" and "Flash Size:
    61079552 Sectors"; the sector count is exact, the MB figure rounded.
    """
    text = rfi_text or ""
    match = re.search(r'Flash\s+Size\s*:\s*(\d+)\s*Sectors', text, re.I)
    if match:
        return int(match.group(1)) * 512
    match = re.search(r'Flash\s+Size\s*:\s*([0-9.]+)\s*(MB|GB)', text, re.I)
    if match:
        return int(float(match.group(1)) * 1024 ** (3 if match.group(2).upper() == 'GB' else 2))
    return None


# The chip behind a Rockchip USB product ID in Maskrom, where rci can't
# answer until a Loader runs. From rkdeveloptool's 99-rk-rockusb.rules, plus
# 0x350b (RK3588, Radxa's and MNT's Maskrom docs) and 0x350e (an RK3576
# seen here). 0x350a is listed as RK3566; the RK3568 shares it and its Loader.
MASKROM_PID_CHIP = {
    0x301A: "RK3036",
    0x310C: "RK3128",
    0x320B: "RK3229",
    0x320A: "RK3288",
    0x320C: "RK3328",
    0x330A: "RK3368",
    0x330C: "RK3399",
    0x350A: "RK3568",
    0x350B: "RK3588",
    0x350E: "RK3576",
}


def chip_from_device(device_line):
    """The chip for an `rkdeveloptool ld` line ("... Pid=0x350e ..."), or None."""
    match = re.search(r'Pid=0x([0-9A-Fa-f]{4})', device_line or "")
    return MASKROM_PID_CHIP.get(int(match.group(1), 16)) if match else None


def parse_flash_info(flash_text):
    """Parse flash info from rkdeveloptool rfi output"""
    if not flash_text:
        return None

    info = {}

    # Extract Manufacturer
    mfg_match = re.search(r'Manufacturer\s*:\s*([A-Z0-9\s,]+?)(?:,\s*value|$)', flash_text, re.I)
    if mfg_match:
        info['manufacturer'] = mfg_match.group(1).strip()

    # Extract Flash Size (first occurrence usually is the main one)
    size_match = re.search(r'Flash\s+Size\s*:\s*([0-9.]+\s*(?:MB|GB|KB))', flash_text, re.I)
    if size_match:
        info['capacity'] = size_match.group(1).strip()

    # Extract Block Size
    block_match = re.search(r'Block\s+Size\s*:\s*([0-9.]+\s*(?:KB|MB))', flash_text, re.I)
    if block_match:
        info['block_size'] = block_match.group(1).strip()

    # Extract Page Size
    page_match = re.search(r'Page\s+Size\s*:\s*([0-9.]+\s*(?:KB|Bytes))', flash_text, re.I)
    if page_match:
        info['page_size'] = page_match.group(1).strip()

    # Extract ECC Bits
    ecc_match = re.search(r'ECC\s+Bits\s*:\s*([0-9]+)', flash_text, re.I)
    if ecc_match:
        info['ecc_bits'] = ecc_match.group(1).strip()

    # Extract Access Time
    access_match = re.search(r'Access\s+Time\s*:\s*([0-9]+)', flash_text, re.I)
    if access_match:
        info['access_time'] = access_match.group(1).strip()

    # Extract Flash CS info
    cs_match = re.search(r'Flash\s+CS\s*:\s*([^\n]+)', flash_text, re.I)
    if cs_match:
        info['flash_cs'] = cs_match.group(1).strip()

    # Legacy: Extract Flash ID from old format if present
    id_match = re.search(r'Flash\s*ID[:\s]*([0-9A-Fa-f]{2})\s*([0-9A-Fa-f]{2})\s*([0-9A-Fa-f]{2})', flash_text, re.I)
    if id_match:
        manufacturer_id = id_match.group(1).upper()
        device_id1 = id_match.group(2).upper()
        device_id2 = id_match.group(3).upper()
        info['id'] = f"{manufacturer_id} {device_id1} {device_id2}"

    return info if info else None


def is_rkfw_image(file_path):
    """Check whether a file is an RKFW-packed firmware image (e.g. update.img).

    RKFW containers start with the 4-byte magic b"RKFW" and hold a Loader
    plus an RKAF partition archive - they must not be written raw to
    sector 0 via `wl 0x0`, which only works for unpacked GPT disk images.
    """
    try:
        with open(file_path, 'rb') as f:
            return f.read(4) == b'RKFW'
    except OSError:
        return False


# Linux USB access. Without a udev rule only root can open a Rockchip
# device, and rkdeveloptool either doesn't find it or fails on every command.
# packaging/70-rkdeveloptool-gui.rules holds the same rule (the deb/rpm
# install it); tests keep the two in step.
ROCKCHIP_USB_VENDOR = "2207"
UDEV_RULE = 'SUBSYSTEM=="usb", ATTR{idVendor}=="2207", TAG+="uaccess"'
UDEV_RULE_FILE = "/etc/udev/rules.d/70-rkdeveloptool-gui.rules"


def inaccessible_rockchip_usb(sysfs="/sys/bus/usb/devices", devfs="/dev/bus/usb",
                              linux=None):
    """USB device nodes of connected Rockchip devices the current user can't
    open read-write. Empty off Linux, or when everything is accessible."""
    if linux is None:
        linux = sys.platform.startswith("linux")
    if not linux:
        return []
    try:
        entries = os.listdir(sysfs)
    except OSError:
        return []
    blocked = []
    for name in sorted(entries):
        base = os.path.join(sysfs, name)
        try:
            with open(os.path.join(base, "idVendor")) as f:
                if f.read().strip().lower() != ROCKCHIP_USB_VENDOR:
                    continue
            with open(os.path.join(base, "busnum")) as f:
                bus = int(f.read())
            with open(os.path.join(base, "devnum")) as f:
                dev = int(f.read())
        except (OSError, ValueError):
            continue
        node = os.path.join(devfs, f"{bus:03d}", f"{dev:03d}")
        if os.path.exists(node) and not os.access(node, os.R_OK | os.W_OK):
            blocked.append(node)
    return blocked


def udev_fix_command():
    """One shell command that installs the udev rule and applies it."""
    return (f"echo '{UDEV_RULE}' | sudo tee {UDEV_RULE_FILE} && "
            "sudo udevadm control --reload-rules && "
            f"sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor={ROCKCHIP_USB_VENDOR}")


# Leading bytes of the archive formats distro images ship in (Armbian, Ubuntu,
# Debian and vendor images are usually .img.xz or .img.gz). Written raw with
# `wl`, any of them leaves the board unbootable while the flash "succeeds".
_COMPRESSION_MAGIC = (
    (b"\xfd7zXZ\x00", "xz"),
    (b"\x1f\x8b\x08", "gzip"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"PK\x03\x04", "zip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
)

# Formats DecompressWorker can unpack with the standard library alone.
DECOMPRESSIBLE = ("xz", "gzip", "bzip2")

_COMPRESSED_SUFFIXES = (".xz", ".gz", ".bz2", ".zst", ".zip", ".7z")


def detect_compression(file_path):
    """Return the archive format of a file ('xz', 'gzip', 'bzip2', 'zstd',
    'zip' or '7z'), or None for anything else (raw disk images included)."""
    try:
        with open(file_path, 'rb') as f:
            head = f.read(8)
    except OSError:
        return None
    for magic, kind in _COMPRESSION_MAGIC:
        if head.startswith(magic):
            return kind
    # "BZh" plus the block-size digit '1'..'9'.
    if len(head) >= 4 and head[:3] == b"BZh" and 0x31 <= head[3] <= 0x39:
        return "bzip2"
    return None


def decompressed_name(file_path):
    """File name for the decompressed copy: 'Armbian.img.xz' -> 'Armbian.img'."""
    name = os.path.basename(file_path)
    root, ext = os.path.splitext(name)
    if ext.lower() in _COMPRESSED_SUFFIXES and root:
        return root
    return name + ".img"


# What classify_image_file() may return, by what it means for flashing.
WHOLE_IMAGE_KINDS = ("rkfw", "compressed", "disk")


def classify_image_file(file_path):
    """Rough type of a file someone wants to flash, from its contents:

    'loader'      Rockchip loader (BOOT / LDR tag)
    'rkfw'        RKFW update.img
    'compressed'  xz / gzip / bzip2 / zstd / zip / 7z archive
    'disk'        whole-disk image: MBR boot signature or a GPT header
    'other'       anything else (a single partition image, a text file...)
    None          unreadable
    """
    try:
        with open(file_path, 'rb') as f:
            head = f.read(520)
    except OSError:
        return None
    if head[:4] in (b"BOOT", b"LDR "):
        return 'loader'
    if head[:4] == b"RKFW":
        return 'rkfw'
    if detect_compression(file_path):
        return 'compressed'
    if len(head) >= 520 and (head[510:512] == b"\x55\xaa" or head[512:520] == b"EFI PART"):
        return 'disk'
    return 'other'


READBACK_FILLER = b"\xcc" * 512


def find_readback_filler(readback, image, size, chunk=4 << 20):
    """Byte offset of the first sector that read back as filler (all 0xCC)
    where the image has something else, or None.

    Some loaders (seen on an RK3576 with rkdeveloptool 1.32) return 0xCC
    instead of data for reads past a point, though writes there land fine;
    a readback comparison can't tell anything about that range.
    """
    with open(readback, "rb") as rb, open(image, "rb") as im:
        offset = 0
        while offset < size:
            a = rb.read(min(chunk, size - offset))
            b = im.read(len(a))
            if not a:
                break
            if a != b:
                for i in range(0, len(a) - 511, 512):
                    if a[i:i + 512] == READBACK_FILLER and b[i:i + 512] != READBACK_FILLER:
                        return offset + i
            offset += len(a)
    return None


def compare_readback(readback, image, size, chunk=4 << 20):
    """Compare the first `size` bytes read back with the image.

    Returns ("ok", None), ("mismatch", offset) or ("unverified", offset),
    the last when the first difference is loader filler (see
    find_readback_filler): nothing can be said from there on.
    """
    with open(readback, "rb") as rb, open(image, "rb") as im:
        offset = 0
        while offset < size:
            b = im.read(min(chunk, size - offset))
            a = rb.read(len(b))
            if not b:
                break
            if a != b:
                for i in range(0, len(b), 512):
                    got = a[i:i + 512]
                    if got != b[i:i + 512]:
                        filler = bool(got) and got == READBACK_FILLER[:len(got)]
                        return ("unverified" if filler else "mismatch"), offset + i
            offset += len(b)
    return "ok", None


def parameter_partitions(path):
    """{name: (start, size)} in 512-byte sectors from a parameter file's
    mtdparts ("0x2000@0x4000(uboot),-@0x40000(rootfs:grow)"); size is None
    for a partition that grows to the end."""
    parts = {}
    try:
        with open(path, "r", errors="replace") as f:
            text = f.read(1 << 20)
    except OSError:
        return parts
    for line in text.splitlines():
        if line.lstrip().startswith("#") or "mtdparts" not in line:
            continue
        for size, start, name in re.findall(r'(-|0x[0-9A-Fa-f]+)@(0x[0-9A-Fa-f]+)\(([^)]+)\)', line):
            parts[name.split(":")[0]] = (int(start, 16), None if size == "-" else int(size, 16))
    return parts


def calculate_file_md5(file_path):
    """Calculate MD5 hash of a file"""
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        raise Exception(f"MD5 calculation failed: {e}")


def format_file_size(size_bytes):
    """Format file size to human readable format"""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_bytes / 1024:.2f} KB"


def parse_partition_info(text):
    """Parse output from `rkdeveloptool ppt` and return partition dict

    Expected lines like:
    NO  LBA       Name
    00  00002000  security
    """
    parts = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # match lines like: index  LBA  name
        m = re.match(r'^(?:\d+)[\s,]+([0-9A-Fa-f]+)[\s,]+(\S+)$', line)
        if m:
            lba = m.group(1)
            name = m.group(2)
            try:
                start_int = int(lba, 16)
                addr = hex(start_int)
            except Exception:
                addr = f"0x{lba}"
            parts.append((name, start_int, addr))

    # Sort by start_int and build mapping
    parts.sort(key=lambda x: x[1])
    partitions = {}

    for idx, (name, start_int, addr) in enumerate(parts):
        size = None
        if idx + 1 < len(parts):
            next_start = parts[idx + 1][1]
            size_val = next_start - start_int
            try:
                size = hex(size_val)
            except Exception:
                size = str(size_val)
        else:
            size = "unknown"
        partitions[name] = {'address': addr, 'size': size}

    return partitions


def build_parameter_text(partitions):
    """A Rockchip parameter file (what `rkdeveloptool gpt` reads) for a
    partition table as parse_partition_info() returns it.

    `ppt` gives only where each partition starts, so a partition's size is
    the distance to the next one, and the last is written as "-" (grow to the
    end of the storage), which rkdeveloptool and the SDK both accept.
    """
    parts = sorted(((int(info['address'], 16), name) for name, info in partitions.items()),
                   key=lambda p: p[0])
    entries = []
    for i, (start, name) in enumerate(parts):
        if i + 1 < len(parts):
            entries.append(f"0x{parts[i + 1][0] - start:08x}@0x{start:08x}({name})")
        else:
            label = name if name.endswith(":grow") else f"{name}:grow"
            entries.append(f"-@0x{start:08x}({label})")
    return ("# Partition table read from the device with `rkdeveloptool ppt`.\n"
            "# Each size is the distance to the next partition; the last one grows\n"
            "# to the end of the storage. Partition UUIDs are not included.\n"
            "FIRMWARE_VER: 1.0\n"
            "TYPE: GPT\n"
            "CMDLINE: mtdparts=rk29xxnand:" + ",".join(entries) + "\n")


def parameter_has_mtdparts(path):
    """Whether a file looks like a parameter file rkdeveloptool can use."""
    try:
        with open(path, "r", errors="replace") as f:
            return any("mtdparts" in line and not line.lstrip().startswith("#")
                       for line in f.read(1 << 20).splitlines())
    except OSError:
        return False


def safe_slot(fn):
    """Return a safer wrapper for signal slots.

    Strategy:
    - Try calling the target with the provided args/kwargs.
    - If that raises a TypeError (signature mismatch), attempt to call
      the function with a truncated positional-arg list matching the
      target's positional parameter count.
    - If that fails, fall back to calling with no arguments.
    """
    import inspect
    import functools

    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        sig = None

    @functools.wraps(fn)
    def slot(*a, **k):
        # 1) try full call
        try:
            return fn(*a, **k)
        except TypeError:
            pass

        # 2) try truncated positional args based on signature
        if sig is not None:
            try:
                pos_params = [p for p in sig.parameters.values()
                              if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
                num_pos = len(pos_params)
                try_args = a[:num_pos]
                return fn(*try_args)
            except Exception:
                pass

        # 3) try calling without args
        try:
            return fn()
        except Exception:
            return None

    return slot


def parse_flash_id(output: str) -> dict:
    """Parse Flash ID from rkdeveloptool rid output
    
    Returns a dict with keys: manufacturer, device_id, capacity, etc.
    """
    info = {}
    
    # Parse Flash ID (hex format: 4E 4F 52 or similar)
    # The output is usually: Flash ID: XX YY ZZ ...
    id_match = re.search(r'Flash\s*ID\s*:\s*([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})', output, re.I)
    if id_match:
        manufacturer_id = id_match.group(1).upper()
        device_id1 = id_match.group(2).upper()
        device_id2 = id_match.group(3).upper()
        
        manufacturer = FLASH_ID_MAP.get(manufacturer_id, f"Unknown (0x{manufacturer_id})")
        info['manufacturer'] = manufacturer
        info['manufacturer_id'] = f"0x{manufacturer_id}"
        info['device_id'] = f"{device_id1} {device_id2}"
        info['device_id_hex'] = f"0x{device_id1}{device_id2}"
        
        # Try to calculate capacity from device ID
        # Device ID typically has high byte = density code
        try:
            # Try using device_id1 first (most significant byte)
            capacity_code = int(device_id1, 16)
            # Check if it's a valid power of 2
            if capacity_code > 0 and (capacity_code & (capacity_code - 1)) == 0:
                # It's a power of 2, use as byte multiplier
                capacity_bytes = capacity_code * (1024 * 1024)  # Assume in MB
                if capacity_bytes >= 1024 ** 3:
                    info['capacity'] = f"{capacity_bytes / (1024 ** 3):.1f} GB"
                else:
                    info['capacity'] = f"{capacity_bytes / (1024 ** 2):.0f} MB"
        except (ValueError, KeyError, TypeError) as e:
            print(f"Warning: Could not parse device capacity: {e}")
    
    # Extract capacity from text if not already found
    cap_match = re.search(r'([0-9.]+)\s*(MB|GB)', output, re.I)
    if cap_match and 'capacity' not in info:
        val = float(cap_match.group(1))
        unit = cap_match.group(2).upper()
        info['capacity'] = f"{val} {unit}"
    
    return info


def parse_capability(output: str) -> dict:
    """Parse device capability from rkdeveloptool rcb output
    
    Returns a dict with device capability information
    """
    info = {}
    
    # Extract capability code from "Capability:51 17 00 00..." format
    cap_match = re.search(r'Capability\s*:\s*([0-9A-Fa-f\s]+?)(?:\n|$)', output, re.I)
    if cap_match:
        cap_code = cap_match.group(1).strip()
        info['capability_code'] = cap_code
    
    # Extract various capability fields
    patterns = [
        (r'Direct\s+LBA\s*:\s*(\w+)', 'direct_lba'),
        (r'Read\s+Com\s+Log\s*:\s*(\w+)', 'read_com_log'),
        (r'Read\s+Secure\s+Mode\s*:\s*(\w+)', 'secure_mode'),
        (r'New\s+IDB\s*:\s*(\w+)', 'new_idb'),
        (r'(?:Erase\s+)?Block\s+Size\s*[:\s]*([0-9.]+\s*(?:KB|MB|Bytes))', 'block_size'),
        (r'(?:Write\s+)?Page\s+Size\s*[:\s]*([0-9.]+\s*(?:Bytes|KB|Byte))', 'write_page_size'),
        (r'(?:Read\s+)?Page\s+Size\s*[:\s]*([0-9.]+\s*(?:Bytes|KB|Byte))', 'read_page_size'),
        (r'IDB\s+Version\s*[:\s]*([0-9A-Fa-f.]+)', 'idb_version'),
        (r'(?:ROM|Bootloader)\s+Version\s*[:\s]*([0-9A-Fa-f.]+)', 'bootloader_version'),
        (r'(?:Chip|Device)\s+(?:Name|Type)\s*[:\s]*(\S+)', 'chip_name'),
    ]
    
    for pattern, key in patterns:
        match = re.search(pattern, output, re.I)
        if match:
            info[key] = match.group(1).strip()
    
    # Check for specific features/capabilities
    features = []
    if re.search(r'Direct\s+LBA.*enabled', output, re.I):
        features.append('Direct LBA')
    if re.search(r'New\s+IDB.*enabled', output, re.I):
        features.append('New IDB')
    if re.search(r'Secure\s+Mode.*enabled', output, re.I):
        features.append('Secure Mode')
    
    if features:
        info['features'] = ', '.join(features)
    
    return info


def format_capability_info(capability: dict) -> str:
    """Format capability information as readable text"""
    lines = ["Device Capability Information:\n"]
    
    if 'chip_name' in capability:
        lines.append(f"  Chip: {capability['chip_name']}")
    
    if 'flash_types' in capability:
        lines.append(f"  Supported Flash Types: {capability['flash_types']}")
    
    if 'block_size' in capability:
        lines.append(f"  Block Size: {capability['block_size']}")
    
    if 'write_page_size' in capability:
        lines.append(f"  Write Page Size: {capability['write_page_size']}")
    
    if 'read_page_size' in capability:
        lines.append(f"  Read Page Size: {capability['read_page_size']}")
    
    if 'idb_version' in capability:
        lines.append(f"  IDB Version: {capability['idb_version']}")
    
    if 'bootloader_version' in capability:
        lines.append(f"  Bootloader Version: {capability['bootloader_version']}")
    
    if 'features' in capability:
        lines.append(f"  Features: {capability['features']}")
    
    return '\n'.join(lines)


def format_flash_info_detailed(flash_info: dict) -> str:
    """Format flash information as detailed readable text"""
    lines = ["Detailed Flash Information:\n"]
    
    # Basic info
    if 'flash_type' in flash_info:
        lines.append(f"  Type: {flash_info['flash_type']}")
    
    if 'manufacturer' in flash_info:
        lines.append(f"  Manufacturer: {flash_info['manufacturer']}")
    
    if 'id' in flash_info:
        lines.append(f"  ID: {flash_info['id']}")
    
    if 'capacity' in flash_info:
        lines.append(f"  Capacity: {flash_info['capacity']}")
    
    # Advanced info
    if 'block_size' in flash_info:
        lines.append(f"  Block Size: {flash_info['block_size']}")
    
    if 'page_size' in flash_info:
        lines.append(f"  Page Size: {flash_info['page_size']}")
    
    if 'health_status' in flash_info:
        lines.append(f"  Health: {flash_info['health_status']}")
    
    if 'wear_level' in flash_info:
        lines.append(f"  Wear Level: {flash_info['wear_level']}")
    
    return '\n'.join(lines)


def parse_security_info(output: str) -> dict:
    """Parse device security information from rkdeveloptool rcb output
    
    Returns a dict with security information including:
    - secure_boot: Enabled/Disabled
    - device_lock: Locked/Unlocked
    - bootloader_version: Version info
    - security_policy: Current security policy
    """
    info = {}
    
    # Check for Secure Boot status
    if re.search(r'Secure\s+Boot.*Enabled', output, re.I):
        info['secure_boot'] = True
        info['secure_boot_status'] = "Enabled"
    elif re.search(r'Secure\s+Boot.*Disabled', output, re.I):
        info['secure_boot'] = False
        info['secure_boot_status'] = "Disabled"
    
    # Check for Device Lock status
    if re.search(r'Device\s+Lock.*Locked', output, re.I):
        info['device_locked'] = True
        info['device_lock_status'] = "Locked"
    elif re.search(r'Device\s+(?:Lock|Status).*Unlocked', output, re.I):
        info['device_locked'] = False
        info['device_lock_status'] = "Unlocked"
    
    # Extract Bootloader version
    bl_match = re.search(r'(?:Bootloader|BL)\s+(?:Version|Ver)\s*[:\s]*([0-9A-Fa-f.v]+)', output, re.I)
    if bl_match:
        info['bootloader_version'] = bl_match.group(1).strip()
    
    # Extract ROM version
    rom_match = re.search(r'ROM\s+(?:Version|Ver)\s*[:\s]*([0-9A-Fa-f.v]+)', output, re.I)
    if rom_match:
        info['rom_version'] = rom_match.group(1).strip()
    
    # Check for Write Protection
    if re.search(r'Write\s+Protection.*Enabled', output, re.I):
        info['write_protection'] = True
        info['write_protection_status'] = "Enabled"
    
    # Check for Read Protection
    if re.search(r'Read\s+Protection.*Enabled', output, re.I):
        info['read_protection'] = True
        info['read_protection_status'] = "Enabled"
    
    # Check for special security modes
    security_modes = []
    if re.search(r'Verified\s+Boot|AVB', output, re.I):
        security_modes.append("AVB (Verified Boot)")
    if re.search(r'TEE|Trusted\s+Environment', output, re.I):
        security_modes.append("TEE (Trusted Execution Environment)")
    if re.search(r'DRM', output, re.I):
        security_modes.append("DRM")
    
    if security_modes:
        info['security_modes'] = ', '.join(security_modes)
    
    # Default values if not explicitly found in output
    if 'secure_boot_status' not in info:
        info['secure_boot'] = False
        info['secure_boot_status'] = "Unknown"
    
    if 'device_lock_status' not in info:
        info['device_locked'] = False
        info['device_lock_status'] = "Unknown"
    
    return info


def format_security_info(security: dict) -> str:
    """Format security information as readable text"""
    lines = ["Device Security Information:\n"]
    
    # Secure Boot Status
    if 'secure_boot_status' in security:
        lines.append(f"  Secure Boot: {security['secure_boot_status']}")

    # Device Lock Status
    if 'device_lock_status' in security:
        lines.append(f"  Device Lock: {security['device_lock_status']}")
    
    # Bootloader Version
    if 'bootloader_version' in security:
        lines.append(f"Bootloader Version: {security['bootloader_version']}")
    
    # ROM Version
    if 'rom_version' in security:
        lines.append(f"ROM Version: {security['rom_version']}")
    
    # Write Protection
    if 'write_protection_status' in security:
        lines.append(f"  Write Protection: {security['write_protection_status']}")

    # Read Protection
    if 'read_protection_status' in security:
        lines.append(f"  Read Protection: {security['read_protection_status']}")
    
    # Security Modes
    if 'security_modes' in security:
        lines.append(f"Security Modes: {security['security_modes']}")
    
    # Add warnings if needed
    lines.append("")
    if security.get('secure_boot'):
        lines.append("Secure Boot is ENABLED - Some operations may be restricted")
    if security.get('device_locked'):
        lines.append("Device is LOCKED - Unlocking required for certain operations")
    
    return '\n'.join(lines)


def format_test_results(test_state: dict) -> str:
    """Format connection test results as readable text"""
    total = test_state['total']
    success = test_state['success_count']
    failed = test_state['failed_count']
    success_rate = (success / total * 100) if total > 0 else 0
    
    lines = ["Connection Stability Test Results:\n"]
    lines.append(f"  Total Tests: {total}")
    lines.append(f"Successful: {success}")
    lines.append(f"Failed: {failed}")
    lines.append(f"Success Rate: {success_rate:.1f}%")
    
    if success_rate >= 95:
        lines.append("\nExcellent! Connection is very stable")
    elif success_rate >= 80:
        lines.append("\nGood connection stability")
    elif success_rate >= 60:
        lines.append("\nConnection has some instability - consider checking USB cable/port")
    else:
        lines.append("\nPoor connection stability - check USB connection and try again")
    
    if test_state.get('errors'):
        lines.append("\nErrors:")
        for error in test_state['errors'][:3]:  # Show first 3 errors
            lines.append(f"    - {error}")
        if len(test_state['errors']) > 3:
            lines.append(f"    ... and {len(test_state['errors']) - 3} more")
    
    return '\n'.join(lines)
