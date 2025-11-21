"""
Utility functions and helpers for RKDevelopTool GUI
"""
import re
import os
import hashlib
import subprocess

RKTOOL = "rkdeveloptool"

# Chip ID mapping (common Rockchip IDs)
CHIP_ID_MAP = {
    "0x330A": "RK3588",
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
    """Parse chip info and return readable chip name"""
    if not chip_text:
        return "Unknown Chip"

    # Try to extract chip ID
    match = re.search(r'0x[0-9A-Fa-f]+', chip_text)
    if match:
        chip_id = match.group(0).upper()
        if chip_id in CHIP_ID_MAP:
            return f"{CHIP_ID_MAP[chip_id]} ({chip_id})"

    # Try to match chip name directly
    for chip_name in CHIP_FAMILIES.keys():
        if chip_name.lower() in chip_text.lower():
            return f"{CHIP_FAMILIES[chip_name]} ({chip_name})"

    return chip_text


def parse_flash_info(flash_text):
    """Parse flash ID and return manufacturer and capacity"""
    if not flash_text:
        return None

    info = {}

    # Extract Flash ID
    id_match = re.search(r'Flash\s*ID[:\s]*([0-9A-Fa-f]{2})\s*([0-9A-Fa-f]{2})\s*([0-9A-Fa-f]{2})', flash_text, re.I)
    if id_match:
        manufacturer_id = id_match.group(1).upper()
        device_id1 = id_match.group(2).upper()
        device_id2 = id_match.group(3).upper()

        manufacturer = FLASH_ID_MAP.get(manufacturer_id, f"Unknown (0x{manufacturer_id})")
        info['manufacturer'] = manufacturer
        info['id'] = f"{manufacturer_id} {device_id1} {device_id2}"

        # Calculate capacity from device ID
        try:
            capacity_code = int(device_id2, 16)
            capacity_bytes = 2 ** capacity_code
            if capacity_bytes >= 1024 ** 3:
                info['capacity'] = f"{capacity_bytes / (1024 ** 3):.1f} GB"
            else:
                info['capacity'] = f"{capacity_bytes / (1024 ** 2):.0f} MB"
        except:
            pass

    # Extract capacity from text
    cap_match = re.search(r'([0-9.]+)\s*(MB|GB)', flash_text, re.I)
    if cap_match and 'capacity' not in info:
        val = float(cap_match.group(1))
        unit = cap_match.group(2).upper()
        info['capacity'] = f"{val} {unit}"

    return info if info else None


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