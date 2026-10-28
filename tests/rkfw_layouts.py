#!/usr/bin/env python3
"""RKFW/RKAF parser checks on synthetic update.img files, run by CI.

Builds update.img containers the way both packers in the wild do and checks
that rkfw.py parses, CRC-verifies and extracts them:

- padded_size as a 2048-byte sector count (Rockchip's SDK afptool and
  afptool-rs);
- padded_size as a byte count (the open-source afptool.c, which adds
  sizeof(buf) == 2048 per block);
- a plain MD5 tail, no tail, and a signed tail (MD5 + signature, which
  RKImage.cpp recognises as 160+ bytes after the firmware);
- >4 GiB images whose 32-bit byte counts and offsets wrapped, with and
  without the high-dword markers ("HI" in the RKFW header, "H" at file[50]
  and file[55] in each RKAF entry), written as sparse files so they take no
  real disk space.

The rows of the review on PR #22 are all covered: every small layout must
parse as before; every >4 GiB layout must parse exactly, or - for one that
can't be reconstructed (byte-count padded_size, no markers) - be refused,
never truncated.

    pip install . && python tests/rkfw_layouts.py
"""
import os
import struct
import sys
import tempfile

from rkdeveloptool_gui import rkfw

SECTOR = 2048
U32 = 1 << 32
errors = []


def _pad(n):
    return (n + SECTOR - 1) // SECTOR * SECTOR


def build(path, parts, padded_as="sectors", tail="md5", sparse_sizes=None,
          markers=False):
    """Write an update.img. parts: [(name, filename, payload bytes)].
    sparse_sizes maps a part name to a size whose payload is a hole (zeros)
    instead of real bytes. Returns {name: (pos, size)} as actually laid out."""
    sparse_sizes = sparse_sizes or {}
    loader = b"LOADER" + os.urandom(4000)
    boot_offset = rkfw.RKFW_HEADER_SIZE
    fw_offset = boot_offset + len(loader)

    entries, layout = [], {}
    pos = rkfw.RKAF_HEADER_SIZE
    for name, filename, payload in parts:
        if name == "parameter":
            body = b"PARM" + struct.pack("<I", len(payload)) + payload
            body += struct.pack("<I", rkfw.rkcrc32(payload))
            size = len(body)
        else:
            body = payload
            size = sparse_sizes.get(name, len(payload))
        alloc = _pad(size)
        padded = alloc // SECTOR if padded_as == "sectors" else alloc
        entries.append((name, filename, pos, size, padded, body))
        layout[name] = (pos, size)
        pos += alloc
    length = pos  # RKAF bytes covered by the CRC

    hdr = bytearray(rkfw.RKAF_HEADER_SIZE)
    hdr[0:4] = rkfw.RKAF_MAGIC
    struct.pack_into("<I", hdr, 4, length % U32)
    hdr[8:8 + 5] = b"model"
    struct.pack_into("<II", hdr, 132, 0x01000000, len(entries))
    for i, (name, filename, ppos, size, padded, _) in enumerate(entries):
        base = 140 + i * rkfw.RKAF_PART_SIZE
        hdr[base:base + len(name)] = name.encode()
        hdr[base + 32:base + 32 + len(filename)] = filename.encode()
        struct.pack_into("<IIIII", hdr, base + 92,
                         0, ppos % U32, 0, padded % U32, size % U32)
        if markers:
            struct.pack_into("<cIcI", hdr, base + 32 + 50,
                             b"H", ppos >> 32, b"H", size >> 32)

    with open(path, "wb") as f:
        head = bytearray(rkfw.RKFW_HEADER_SIZE)
        head[0:4] = rkfw.RKFW_MAGIC
        struct.pack_into("<II", head, 25, boot_offset, len(loader))
        struct.pack_into("<II", head, 33, fw_offset, (length + 4) % U32)
        if markers:
            struct.pack_into("<2sI", head, 55, b"HI", (length + 4) >> 32)
        f.write(head)
        f.write(loader)
        f.write(hdr)
        for name, _, ppos, size, _, body in entries:
            f.seek(fw_offset + ppos)
            if name not in sparse_sizes:
                f.write(body)
        f.seek(fw_offset + length)
        f.truncate()

    if not sparse_sizes:
        with open(path, "rb") as f:
            f.seek(fw_offset)
            crc = rkfw.rkcrc32(f.read(length))
    else:
        crc = 0  # not checked for the sparse image: CRC over 4 GiB in Python is slow
    with open(path, "ab") as f:
        f.write(struct.pack("<I", crc))
        if tail in ("md5", "signed"):
            f.write(b"0123456789abcdef0123456789abcdef")
        if tail == "signed":
            f.write(os.urandom(256))
    return fw_offset, length, layout


def check(label, cond, detail=""):
    if not cond:
        errors.append(f"{label}: {detail}")


def check_small(work, padded_as, tail):
    label = f"small/{padded_as}/{tail}"
    path = os.path.join(work, f"small-{padded_as}-{tail}.img")
    payloads = [("parameter", "parameter.txt", b"FIRMWARE_VER: 1.0\nCMDLINE: mtdparts=x\n"),
                ("boot", "Image/boot.img", os.urandom(10000)),
                ("rootfs", "Image/rootfs.img", os.urandom(SECTOR * 3)),
                ("package-file", "package-file", b"package-file\tpackage-file\n"),
                ("update", "SELF", b"")]
    fw_offset, length, layout = build(path, payloads, padded_as, tail)
    try:
        info = rkfw.parse_rkfw_header(path)
        rkaf = rkfw.parse_rkaf_header(path, info.fw_offset, info.fw_size)
    except rkfw.RKFWError as e:
        errors.append(f"{label}: valid image rejected: {e}")
        return
    check(label, rkaf.length == length, f"length {rkaf.length} != {length}")
    check(label, rkfw.verify_rkaf_crc(path, info.fw_offset, rkaf.length), "CRC check failed")
    by_name = {p.name: p for p in rkaf.parts}
    for name, filename, payload in payloads:
        if filename == "SELF":
            continue
        part = by_name.get(name)
        if part is None:
            errors.append(f"{label}: part {name} missing")
            continue
        check(label, (part.pos, part.size) == layout[name],
              f"{name} parsed at {(part.pos, part.size)}, built at {layout[name]}")
        out = os.path.join(work, f"out-{name}")
        rkfw.extract_part(path, info.fw_offset, part, out)
        with open(out, "rb") as f:
            check(label, f.read() == payload, f"{name} extracted bytes differ")


def check_large(work, padded_as, markers, tail="md5"):
    """A >4 GiB rootfs wraps the size fields and every later offset."""
    label = f">4GiB/{padded_as}/{'markers' if markers else 'no-markers'}/{tail}"
    path = os.path.join(work, "large.img")
    payload_after = os.urandom(5000)
    big = U32 + 4_000_001  # just over 4 GiB, not sector-aligned
    payloads = [("parameter", "parameter.txt", b"CMDLINE: mtdparts=x\n"),
                ("rootfs", "Image/rootfs.img", b""),
                ("misc", "Image/misc.img", payload_after)]
    fw_offset, length, layout = build(path, payloads, padded_as, tail,
                                      sparse_sizes={"rootfs": big}, markers=markers)
    refusable = padded_as == "bytes" and not markers
    try:
        info = rkfw.parse_rkfw_header(path)
        rkaf = rkfw.parse_rkaf_header(path, info.fw_offset, info.fw_size)
    except rkfw.RKFWError as e:
        if not refusable:
            errors.append(f"{label}: valid image rejected: {e}")
        return path
    check(label, rkaf.length == length, f"length {rkaf.length} != {length}")
    by_name = {p.name: p for p in rkaf.parts}
    for name in ("rootfs", "misc"):
        got = (by_name[name].pos, by_name[name].size)
        check(label, got == layout[name], f"{name} parsed at {got}, built at {layout[name]}")
    if (by_name["misc"].pos, by_name["misc"].size) == layout["misc"]:
        out = os.path.join(work, "out-misc")
        rkfw.extract_part(path, info.fw_offset, by_name["misc"], out)
        with open(out, "rb") as f:
            check(label, f.read() == payload_after, "misc (after the wrap) extracted bytes differ")
    return path


def check_truncated_large(path):
    """A >4 GiB image cut short must be refused, not parsed with the low
    32 bits of its sizes (which used to extract a truncated rootfs)."""
    with open(path, "r+b") as f:
        f.truncate(os.path.getsize(path) - 3 * SECTOR)
    try:
        info = rkfw.parse_rkfw_header(path)
        rkaf = rkfw.parse_rkaf_header(path, info.fw_offset, info.fw_size)
    except rkfw.RKFWError:
        return
    rootfs = next(p for p in rkaf.parts if p.name == "rootfs")
    errors.append(f">4GiB truncated: accepted, rootfs size {rootfs.size}")


def main():
    work = tempfile.mkdtemp(prefix="rkfw-layouts-")
    for padded_as in ("sectors", "bytes"):
        for tail in ("md5", "none", "signed"):
            check_small(work, padded_as, tail)
    for padded_as, markers in (("sectors", False), ("sectors", True),
                               ("bytes", True), ("bytes", False)):
        check_large(work, padded_as, markers)
    check_large(work, "sectors", True, tail="signed")
    check_truncated_large(check_large(work, "sectors", False))
    if errors:
        print(f"RKFW LAYOUT CHECKS FAILED ({len(errors)}):")
        for e in errors:
            print(" *", e)
        return 1
    print("rkfw layout checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
