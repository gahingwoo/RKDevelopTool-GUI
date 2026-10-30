#!/usr/bin/env python3
"""Loader builder checks on synthetic rkbin files, run by CI.

loader_merge.py was checked by hand against Loaders Rockchip built: from the
matching rkbin commits it reproduces rk3576_spl_loader_v1.09.107.bin,
rk3588_spl_loader_v1.15.113.bin and rk3399_loader_v1.20.119.bin byte for
byte (with their build time). Those blobs aren't in this repository, so this
file reads Loaders built from made-up blobs back with its own parser, RC4
and CRC, and checks the layout those three files have:

- "LDR " (NEWIDB) Loaders: a UsbHead and a FlashHead RKNS header whose
  SHA-256s cover each image and the header; 471/472 data stored plain,
  loader data RC4'd per 512 bytes; entries padded to ALIGN sectors (2 KiB
  by default); names cut at the first dot; version not BCD.
- "BOOT" Loaders: 471/472 data RC4'd as a whole, loader data per 512 bytes,
  names cut at the last dot to 19 characters, BCD version.
- Both end in Rockchip's CRC-32 of everything before it.
- The bootloader a NEWIDB Loader puts at sector 0x40 (what rkdeveloptool's
  ul gets wrong on an RK3576) is FlashHead + Boost + Data + Boot, decrypted.

It also builds a Loader through loader_fetch from a file:// copy of rkbin.

    pip install . && python tests/loader_merge.py
"""
import hashlib
import os
import struct
import sys
import tempfile
import time

from rkdeveloptool_gui import loader_fetch, loader_merge

errors = []
WHEN = time.struct_time((2025, 4, 11, 19, 54, 33, 0, 1, -1))


def check(cond, what):
    if not cond:
        errors.append(what)


def rc4(data):
    key = bytes([124, 78, 3, 4, 85, 5, 9, 7, 45, 44, 123, 56, 23, 13, 23, 17])
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i & 15]) % 256
        s[i], s[j] = s[j], s[i]
    out = bytearray(data)
    i = j = 0
    for x in range(len(out)):
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out[x] ^= s[(s[i] + s[j]) % 256]
    return bytes(out)


def rc4_512(data):
    return b"".join(rc4(data[i:i + 512]) for i in range(0, len(data), 512))


def crc32_rk(data):
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C10DB7) if crc & 0x80000000 else crc << 1
            crc &= 0xFFFFFFFF
    return crc


def pad(data, align):
    return data + b"\0" * (-len(data) % align)


def read_loader(data):
    tag, size, version, merger = struct.unpack_from("<4sHII", data, 0)
    when = struct.unpack_from("<HBBBBB", data, 14)
    chip = data[21:25]
    entries = []
    at = 25
    for _ in range(3):
        count, offset, esize = struct.unpack_from("<BIB", data, at)
        at += 6
        for i in range(count):
            e = data[offset + i * esize:offset + (i + 1) * esize]
            kind, = struct.unpack_from("<I", e, 1)
            name = e[5:45].decode("utf-16-le").split("\0")[0]
            doff, dsize, delay = struct.unpack_from("<III", e, 45)
            entries.append((kind, name, data[doff:doff + dsize], delay, doff))
    return {"tag": tag, "size": size, "version": version, "merger": merger,
            "when": when, "chip": chip, "flags": data[at:at + 4], "entries": entries}


def check_rkns(header, images, words, what):
    check(header[:4] == b"RKNS", f"{what}: magic {header[:4]!r}")
    nimage_size, flag = struct.unpack_from("<II", header, 8)
    check(nimage_size == (len(images) << 16) + 384 and flag == 1,
          f"{what}: size/nimage {nimage_size:#x}, flag {flag}")
    check(header[0x600:0x620] == hashlib.sha256(header[:0x600]).digest(), f"{what}: header hash")
    for i, word in enumerate(words):
        check(struct.unpack_from("<I", header, 0x58 + 4 * i)[0] == word, f"{what}: WORD_{i}")
    sector = len(header) // 512
    for i, (data, address) in enumerate(images):
        so, addr, flag, counter = struct.unpack_from("<IIII", header, 0x78 + 88 * i)
        at = 0x78 + 88 * i + 24
        check(so == ((len(data) // 512) << 16) + sector, f"{what}: image {i} size/offset {so:#x}")
        check(addr == address and counter == i + 1, f"{what}: image {i} address {addr:#x}")
        check(header[at:at + 32] == hashlib.sha256(data).digest(), f"{what}: image {i} hash")
        sector += len(data) // 512


def make_rkbin(root, files):
    for path, data in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)


def blob(seed, size):
    return (hashlib.sha256(seed.encode()).digest() * (size // 32 + 1))[:size]


NEW_INI = """[CHIP_NAME]
NAME=RK3576
[VERSION]
MAJOR=1
MINOR=100
[CODE471_OPTION]
NUM=1
Path1=bin/rk35/rk3576_ddr_lp4_2112MHz_lp5_2736MHz_v1.09.bin
Sleep=1
[CODE472_OPTION]
NUM=1
Path1=bin/rk35/rk3576_usbplug_v1.04.bin
[LOADER_OPTION]
NUM=3
LOADER1=FlashBoost
LOADER2=FlashData
LOADER3=FlashBoot
FlashBoost=bin/rk35/rk3576_boost_v1.03.bin
FlashData=bin/rk35/rk3576_ddr_lp4_2112MHz_lp5_2736MHz_v1.09.bin
FlashBoot=bin/rk35/rk3576_spl_v1.07.bin
[LOADER1_PARAM]
LOAD_ADDR=0x3FFC0000
FLAG=0x0
[LOADER2_PARAM]
LOAD_ADDR=0x3FF81000
FLAG=0x0
[OUTPUT]
PATH=rk3576_spl_loader_v1.09.107.bin
[SYSTEM]
NEWIDB=true
ALIGN=8
[FLAG]
471_RC4_OFF=true
RC4_OFF=true
[BOOT1_PARAM]
WORD_2=0x100
"""

NEW_BLOBS = {
    "bin/rk35/rk3576_ddr_lp4_2112MHz_lp5_2736MHz_v1.09.bin": blob("ddr", 75936),
    "bin/rk35/rk3576_usbplug_v1.04.bin": blob("usbplug", 340232),
    "bin/rk35/rk3576_boost_v1.03.bin": blob("boost", 2604),
    "bin/rk35/rk3576_spl_v1.07.bin": blob("spl", 260824),
}

OLD_INI = """[CHIP_NAME]
NAME=RK330C
[VERSION]
MAJOR=1
MINOR=19
[CODE471_OPTION]
NUM=1
Path1=bin/rk33/rk3399_ddr_800MHz_v1.20.bin
Sleep=1
[CODE472_OPTION]
NUM=1
Path1=bin/rk33/rk3399_usbplug_v1.19.bin
[LOADER_OPTION]
NUM=2
LOADER1=FlashData
LOADER2=FlashBoot
FlashData=bin/rk33/rk3399_ddr_800MHz_v1.20.bin
FlashBoot=bin/rk33/rk3399_miniloader_v1.19.bin
[OUTPUT]
PATH=rk3399_loader_v1.20.119.bin
"""

OLD_BLOBS = {
    "bin/rk33/rk3399_ddr_800MHz_v1.20.bin": blob("ddr3399", 70001),
    "bin/rk33/rk3399_usbplug_v1.19.bin": blob("plug3399", 60001),
    "bin/rk33/rk3399_miniloader_v1.19.bin": blob("mini3399", 88001),
}


def check_new():
    out = loader_merge.merge(loader_merge.parse_ini(NEW_INI), NEW_BLOBS.__getitem__, WHEN)
    info = read_loader(out)
    check(info["tag"] == b"LDR " and info["size"] == 102, f"LDR header {info['tag']!r}")
    check(info["version"] == 0x164 and info["merger"] == 0x01000000,
          f"LDR version {info['version']:#x} / {info['merger']:#x}")
    check(info["when"] == (2025, 4, 11, 19, 54, 33), f"LDR time {info['when']}")
    check(info["chip"] == b"6753", f"LDR chip {info['chip']!r}")
    check(info["flags"] == b"\0\1\1\1", f"LDR sign/rc4/reserved {info['flags'].hex()}")
    names = [(e[0], e[1], len(e[2]), e[3]) for e in info["entries"]]
    want = [(1, "UsbHead", 0x1000, 1), (1, "rk3576_ddr_lp4_2112M", 0x13000, 1),
            (2, "rk3576_usbplug_v1", 0x54000, 0), (4, "FlashHead", 0x1000, 0),
            (4, "FlashBoost", 0x1000, 0), (4, "FlashData", 0x13000, 0),
            (4, "FlashBoot", 0x40000, 0)]
    check(names == want, f"LDR entries {names}")
    offsets = [e[4] for e in info["entries"]]
    check(offsets[0] == 102 + 7 * 57 and all(
        offsets[i + 1] == offsets[i] + len(info["entries"][i][2]) for i in range(6)),
        f"LDR entry data not back to back: {offsets}")

    ddr, plug, boost, spl = (pad(NEW_BLOBS[p], 4096) for p in (
        "bin/rk35/rk3576_ddr_lp4_2112MHz_lp5_2736MHz_v1.09.bin",
        "bin/rk35/rk3576_usbplug_v1.04.bin", "bin/rk35/rk3576_boost_v1.03.bin",
        "bin/rk35/rk3576_spl_v1.07.bin"))
    data = [e[2] for e in info["entries"]]
    check(data[1] == ddr and data[2] == plug, "LDR 471/472 data not stored plain")
    check(rc4_512(data[4]) == boost and rc4_512(data[5]) == ddr and rc4_512(data[6]) == spl,
          "LDR loader data not RC4'd per 512 bytes")
    check_rkns(data[0], [(ddr, 0xFFFFFFFF), (plug, 0xFFFFFFFF)], [0, 0, 0x100], "UsbHead")
    check_rkns(rc4_512(data[3]), [(boost, 0x3FFC0000), (ddr, 0x3FF81000), (spl, 0xFFFFFFFF)],
               [0, 0, 0x100], "FlashHead")
    check(struct.unpack("<I", out[-4:])[0] == crc32_rk(out[:-4]), "LDR CRC")

    # Without ALIGN: 2 KiB entries and RKNS headers, reserved[1] clear.
    out = loader_merge.merge(loader_merge.parse_ini(NEW_INI.replace("ALIGN=8\n", "")),
                             NEW_BLOBS.__getitem__, WHEN)
    info = read_loader(out)
    check(info["flags"] == b"\0\1\1\0", f"LDR without ALIGN flags {info['flags'].hex()}")
    plug = NEW_BLOBS["bin/rk35/rk3576_usbplug_v1.04.bin"]
    check(len(info["entries"][0][2]) == 0x800 and len(info["entries"][2][2]) ==
          len(pad(plug, 2048)) != len(pad(plug, 4096)), "LDR without ALIGN not padded to 2 KiB")
    check_rkns(info["entries"][0][2], [(pad(NEW_BLOBS[p], 2048), 0xFFFFFFFF) for p in (
        "bin/rk35/rk3576_ddr_lp4_2112MHz_lp5_2736MHz_v1.09.bin",
        "bin/rk35/rk3576_usbplug_v1.04.bin")], [0, 0, 0x100], "UsbHead without ALIGN")


def check_old():
    out = loader_merge.merge(loader_merge.parse_ini(OLD_INI), OLD_BLOBS.__getitem__, WHEN)
    info = read_loader(out)
    check(info["tag"] == b"BOOT" and info["version"] == 0x119 and info["merger"] == 0x01030000,
          f"BOOT header {info['tag']!r} {info['version']:#x} {info['merger']:#x}")
    check(info["chip"] == b"C033" and info["flags"] == b"\0\1\0\0",
          f"BOOT chip/flags {info['chip']!r} {info['flags'].hex()}")
    names = [(e[0], e[1], len(e[2]), e[3]) for e in info["entries"]]
    want = [(1, "rk3399_ddr_800MHz_v", 0x11800, 1), (2, "rk3399_usbplug_v1.1", 0xF000, 0),
            (4, "FlashData", 0x11800, 0), (4, "FlashBoot", 0x15800, 0)]
    check(names == want, f"BOOT entries {names}")
    ddr = pad(OLD_BLOBS["bin/rk33/rk3399_ddr_800MHz_v1.20.bin"], 2048)
    plug = pad(OLD_BLOBS["bin/rk33/rk3399_usbplug_v1.19.bin"], 2048)
    mini = pad(OLD_BLOBS["bin/rk33/rk3399_miniloader_v1.19.bin"], 2048)
    data = [e[2] for e in info["entries"]]
    check(rc4(data[0]) == ddr and rc4(data[1]) == plug, "BOOT 471/472 not RC4'd as a whole")
    check(rc4_512(data[2]) == ddr and rc4_512(data[3]) == mini,
          "BOOT loader data not RC4'd per 512 bytes")
    check(struct.unpack("<I", out[-4:])[0] == crc32_rk(out[:-4]), "BOOT CRC")


def check_bad_ini():
    for text in ("", NEW_INI.replace("NUM=1\nPath1=bin/rk35/rk3576_usbplug_v1.04.bin", "NUM=2"),
                 "[CHIP_NAME]\nNAME=RK3576\n"):
        try:
            loader_merge.parse_ini(text)
        except loader_merge.LoaderMergeError:
            continue
        errors.append(f"accepted a broken ini: {text[:40]!r}")


def check_fetch():
    check(loader_fetch.ini_candidates("RK330C")[0] == "RK3399MINIALL.ini", "RK330C ini")
    check(loader_fetch.ini_candidates("RK3576") == ["RK3576MINIALL.ini", "RV3576MINIALL.ini"],
          f"RK3576 ini {loader_fetch.ini_candidates('RK3576')}")
    check(loader_fetch.ini_candidates("Unknown Chip") == [], "an unknown chip has ini names")

    rkbin = tempfile.mkdtemp()
    make_rkbin(rkbin, dict(OLD_BLOBS, **{"RKBOOT/RK3399MINIALL.ini": OLD_INI.encode()}))
    os.environ[loader_fetch.URL_ENV] = "file://" + rkbin + "/"
    dest = tempfile.mkdtemp()
    path, ini_name, sha = loader_fetch.fetch_loader("RK330C", dest)
    check(os.path.basename(path) == "rk3399_loader_v1.20.119.bin" and ini_name ==
          "RK3399MINIALL.ini" and sha is None, f"fetched {path} {ini_name} {sha}")
    with open(path, "rb") as f:
        built = f.read()
    check(read_loader(built)["tag"] == b"BOOT", "fetched Loader isn't a Loader")
    # Built again from the same recipe: the file already there is used.
    os.remove(os.path.join(rkbin, "bin/rk33/rk3399_usbplug_v1.19.bin"))
    again, _, _ = loader_fetch.fetch_loader("RK330C", dest)
    check(again == path, "a Loader already built was rebuilt")
    try:
        loader_fetch.fetch_loader("RK3576", dest)
    except LookupError:
        pass
    else:
        errors.append("a chip with no ini in rkbin produced a Loader")
    del os.environ[loader_fetch.URL_ENV]


def check_idblock():
    """The bootloader a NEWIDB Loader puts at sector 0x40 is its FlashHead
    and loader entries, decrypted, with every RKNS hash right; an old BOOT
    Loader has none (ul writes it); a damaged one is refused."""
    built = loader_merge.merge(loader_merge.parse_ini(NEW_INI), NEW_BLOBS.__getitem__, WHEN)
    idb = loader_merge.idblock_from_loader(built)
    ddr, boost, spl = (pad(NEW_BLOBS[p], 4096) for p in (
        "bin/rk35/rk3576_ddr_lp4_2112MHz_lp5_2736MHz_v1.09.bin",
        "bin/rk35/rk3576_boost_v1.03.bin", "bin/rk35/rk3576_spl_v1.07.bin"))
    check(idb is not None and idb[0x1000:] == boost + ddr + spl,
          "idblock isn't FlashHead + boost + ddr + spl")
    if idb is not None:
        check_rkns(idb[:0x1000], [(boost, 0x3FFC0000), (ddr, 0x3FF81000), (spl, 0xFFFFFFFF)],
                   [0, 0, 0x100], "idblock header")
    old = loader_merge.merge(loader_merge.parse_ini(OLD_INI), OLD_BLOBS.__getitem__, WHEN)
    check(loader_merge.idblock_from_loader(old) is None, "a BOOT Loader got an idblock")
    # A Loader whose FlashBoot was cut or changed doesn't verify.
    info = read_loader(built)
    boot_at = info["entries"][-1][4]
    broken = bytearray(built)
    broken[boot_at + 600] ^= 0xFF
    try:
        loader_merge.idblock_from_loader(bytes(broken))
    except loader_merge.LoaderMergeError:
        pass
    else:
        errors.append("a Loader with a damaged FlashBoot gave an idblock")


check_new()
check_old()
check_bad_ini()
check_idblock()
check_fetch()

if errors:
    print(f"LOADER MERGE CHECKS FAILED ({len(errors)}):")
    for e in errors:
        print(" *", e)
    sys.exit(1)
print("loader merge checks passed")
