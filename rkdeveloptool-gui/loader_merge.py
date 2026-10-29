"""
Builds a Rockchip Loader (the file rkdeveloptool's `db` and `ul` take) from
the pieces in Rockchip's rkbin repository, the way rkbin's boot_merger does.

rkbin ships no ready-made Loader, only the DDR init, usbplug and SPL blobs
plus an RKBOOT/<CHIP>MINIALL.ini saying how to combine them, and boot_merger
itself is an x86 Linux binary. The layout here follows the open-source
boot_merger.c (rockchip-linux/u-boot, tools/rockchip) for the original
"BOOT" format. The newer "LDR " format used by NEWIDB chips (RK35xx, RV1106,
...) adds a "UsbHead" and a "FlashHead" entry, each an RKNS header (magic,
image table, SHA-256 of each image and of the header itself; see
header0_info_v2 in mainline U-Boot's tools/rkcommon.c). Its details were
read off Rockchip-built loaders: generating rk3576_spl_loader_v1.09.107.bin
and rk3588_spl_loader_v1.15.113.bin from the matching rkbin commits gives
the same bytes apart from the build time and the CRC that covers it.
"""
import configparser
import hashlib
import struct
import time

from .rkfw import rkcrc32

TAG_BOOT = b"BOOT"
TAG_LDR = b"LDR "
MERGER_VERSION_BOOT = 0x01030000
MERGER_VERSION_LDR = 0x01000000

HEADER_SIZE = 102
ENTRY_SIZE = 57
NAME_CHARS = 20
SECTOR = 512
DEFAULT_ALIGN = 2048        # boot_merger's ENTRY_ALIGN

ENTRY_471 = 1
ENTRY_472 = 2
ENTRY_LOADER = 4

RKNS_MAGIC = b"RKNS"
RKNS_HASH_AT = 0x600
RKNS_WORDS_AT = 0x58        # [BOOT1_PARAM] WORD_0..WORD_7
RKNS_IMAGES_AT = 0x78
RKNS_IMAGE_SIZE = 88
RKNS_MAX_IMAGES = 4

_RC4_KEY = bytes([124, 78, 3, 4, 85, 5, 9, 7, 45, 44, 123, 56, 23, 13, 23, 17])


class LoaderMergeError(Exception):
    """The INI doesn't describe a Loader this module knows how to build."""


def _rc4_stream(length):
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + _RC4_KEY[i % len(_RC4_KEY)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray(length)
    i = j = 0
    for x in range(length):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out[x] = s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


def _xor(data, stream):
    n = len(data)
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream[:n], "little")) \
        .to_bytes(n, "little")


def rc4(data):
    """Rockchip's P_RC4 over the whole buffer (it is its own inverse)."""
    return _xor(data, _rc4_stream(len(data)))


def rc4_sectors(data):
    """P_RC4 restarted every 512 bytes, as boot_merger stores loader entries."""
    stream = _rc4_stream(SECTOR)
    return b"".join(_xor(data[i:i + SECTOR], stream) for i in range(0, len(data), SECTOR))


def _pad(data, align):
    return data + b"\0" * (-len(data) % align)


def _flag(cfg, section, key):
    return cfg.get(section, key, fallback="").strip().lower() == "true"


def _int(value, default=0):
    value = (value or "").strip()
    if not value:
        return default
    return int(value, 0)


def parse_ini(text):
    """The parts of an RKBOOT .ini that decide what goes into the Loader."""
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str
    try:
        cfg.read_string(text)
    except configparser.Error as exc:
        raise LoaderMergeError(f"can't read the RKBOOT ini: {exc}") from exc

    def paths(section):
        count = _int(cfg.get(section, "NUM", fallback="0"))
        found = [cfg.get(section, f"Path{i}", fallback="").strip() for i in range(1, count + 1)]
        if not all(found):
            raise LoaderMergeError(f"[{section}] lists fewer paths than NUM")
        return found

    try:
        loaders = []
        for i in range(1, _int(cfg.get("LOADER_OPTION", "NUM", fallback="0")) + 1):
            name = cfg.get("LOADER_OPTION", f"LOADER{i}").strip()
            param = f"LOADER{i}_PARAM"
            loaders.append({
                "name": name,
                "path": cfg.get("LOADER_OPTION", name).strip(),
                "address": _int(cfg.get(param, "LOAD_ADDR", fallback=""), 0xFFFFFFFF),
                "flag": _int(cfg.get(param, "FLAG", fallback="")),
            })
        options = {
            "chip": cfg.get("CHIP_NAME", "NAME").strip(),
            "major": _int(cfg.get("VERSION", "MAJOR")),
            "minor": _int(cfg.get("VERSION", "MINOR"), 0),
            "code471": paths("CODE471_OPTION"),
            "code471_sleep": _int(cfg.get("CODE471_OPTION", "Sleep", fallback="")),
            "code472": paths("CODE472_OPTION"),
            "code472_sleep": _int(cfg.get("CODE472_OPTION", "Sleep", fallback="")),
            "loaders": loaders,
            "output": cfg.get("OUTPUT", "PATH").strip(),
            "new_idb": _flag(cfg, "SYSTEM", "NEWIDB"),
            "align": _int(cfg.get("SYSTEM", "ALIGN", fallback="")) * SECTOR or DEFAULT_ALIGN,
            "rc4_471": not _flag(cfg, "FLAG", "471_RC4_OFF"),
            "words": [_int(cfg.get("BOOT1_PARAM", f"WORD_{i}", fallback="")) for i in range(8)],
        }
    except (configparser.Error, ValueError) as exc:
        raise LoaderMergeError(f"incomplete RKBOOT ini: {exc}") from exc
    if not options["code471"] or not options["code472"] or not loaders:
        raise LoaderMergeError("the RKBOOT ini has no DDR, usbplug or loader entries")
    if options["new_idb"] and max(len(options["code471"]) + len(options["code472"]),
                                  len(loaders)) > RKNS_MAX_IMAGES:
        raise LoaderMergeError("more images than an RKNS header holds")
    return options


def blob_paths(options):
    """Every rkbin file the Loader is built from, without duplicates."""
    seen = []
    for path in options["code471"] + options["code472"] + [l["path"] for l in options["loaders"]]:
        if path not in seen:
            seen.append(path)
    return seen


def _chip_type(chip):
    # "RK3576" -> the ASCII of "3576" read as a big-endian word.
    return int.from_bytes(chip[2:6].encode("ascii").ljust(4, b"\0"), "big")


def _bcd(value):
    return ((value // 10 % 10) << 4) | (value % 10)


def _entry_name(path, new):
    # The file name up to the extension, cut to fit the entry. The current
    # boot_merger stops at the first dot ("rk3576_usbplug_v1"), the
    # open-source one at the last and one character shorter.
    base = path.rsplit("/", 1)[-1]
    if new:
        return base.split(".", 1)[0][:NAME_CHARS]
    if "." in base:
        base = base[:base.rindex(".")]
    return base[:NAME_CHARS - 1]


def _rkns_header(images, size, words=None):
    """An RKNS header of `size` bytes for `images` [(data, address, flag)],
    which follow it back to back."""
    header = bytearray(size)
    header[0:4] = RKNS_MAGIC
    struct.pack_into("<II", header, 8, (len(images) << 16) + 384, 1)   # 1: SHA-256
    for i, word in enumerate(words or ()):
        struct.pack_into("<I", header, RKNS_WORDS_AT + 4 * i, word)
    sector = size // SECTOR
    for i, (data, address, flag) in enumerate(images):
        at = RKNS_IMAGES_AT + i * RKNS_IMAGE_SIZE
        count = len(data) // SECTOR
        struct.pack_into("<IIII", header, at, (count << 16) + sector, address, flag, i + 1)
        header[at + 24:at + 56] = hashlib.sha256(data).digest()
        sector += count
    header[RKNS_HASH_AT:RKNS_HASH_AT + 32] = hashlib.sha256(header[:RKNS_HASH_AT]).digest()
    return bytes(header)


def merge(options, read, when=None):
    """Build the Loader. `read(path)` returns the bytes of an rkbin file;
    `when` is a time.struct_time for the header (default: now, local)."""
    new = options["new_idb"]
    align = options["align"] if new else DEFAULT_ALIGN
    blobs = {path: read(path) for path in blob_paths(options)}

    def padded(path, sectors):
        data = blobs[path]
        if sectors:
            data = _pad(data, SECTOR)
        return _pad(data, align)

    # (type, name, delay, stored bytes)
    entries = []
    usb = [padded(p, False) for p in options["code471"] + options["code472"]]
    flash = [(padded(l["path"], True), l["address"], l["flag"]) for l in options["loaders"]]
    if new:
        entries.append((ENTRY_471, "UsbHead", options["code471_sleep"],
                        _rkns_header([(d, 0xFFFFFFFF, 0) for d in usb], align,
                                     options["words"])))
    for path, data in zip(options["code471"], usb):
        stored = rc4(data) if options["rc4_471"] else data
        entries.append((ENTRY_471, _entry_name(path, new), options["code471_sleep"], stored))
    for path, data in zip(options["code472"], usb[len(options["code471"]):]):
        stored = rc4(data) if options["rc4_471"] else data
        entries.append((ENTRY_472, _entry_name(path, new), options["code472_sleep"], stored))
    if new:
        entries.append((ENTRY_LOADER, "FlashHead", 0,
                        rc4_sectors(_rkns_header(flash, align, options["words"]))))
    for loader, (data, _, _) in zip(options["loaders"], flash):
        entries.append((ENTRY_LOADER, loader["name"][:NAME_CHARS], 0, rc4_sectors(data)))

    counts = [sum(1 for e in entries if e[0] == t) for t in (ENTRY_471, ENTRY_472, ENTRY_LOADER)]
    when = when or time.localtime()
    header = bytearray(HEADER_SIZE)
    if new:
        version = (options["major"] << 8) | (options["minor"] & 0xFF)
    else:
        version = (_bcd(options["major"]) << 8) | _bcd(options["minor"])
    struct.pack_into("<4sHII", header, 0, TAG_LDR if new else TAG_BOOT, HEADER_SIZE,
                     version, MERGER_VERSION_LDR if new else MERGER_VERSION_BOOT)
    struct.pack_into("<HBBBBBI", header, 14, when.tm_year, when.tm_mon, when.tm_mday,
                     when.tm_hour, when.tm_min, when.tm_sec, _chip_type(options["chip"]))
    offset = HEADER_SIZE
    at = 25
    for count in counts:
        struct.pack_into("<BIB", header, at, count, offset, ENTRY_SIZE)
        offset += count * ENTRY_SIZE
        at += 6
    header[at + 1] = 1                      # rc4Flag: no --rc4
    if new:
        header[at + 2] = 1
        header[at + 3] = 1 if options["align"] != DEFAULT_ALIGN else 0

    table = bytearray()
    data_at = offset
    for kind, name, delay, stored in entries:
        entry = bytearray(ENTRY_SIZE)
        struct.pack_into("<BI", entry, 0, ENTRY_SIZE, kind)
        entry[5:5 + 2 * len(name)] = name.encode("utf-16-le")
        struct.pack_into("<III", entry, 45, data_at, len(stored), delay)
        table += entry
        data_at += len(stored)

    out = bytes(header) + bytes(table) + b"".join(e[3] for e in entries)
    return out + struct.pack("<I", rkcrc32(out))
