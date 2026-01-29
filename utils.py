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

ASCII_CHIP_MAP = {
    "6753": "RK3576",
    "330A": "RK3588",
    "3368": "RK3368",
    "3399": "RK3399",
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
    - ASCII byte sequences: "36 37 35 33..." (decimal ASCII codes) -> "6753" -> "RK3576"
    - Hex IDs: "0x330A" -> "RK3588"
    - Direct names: "RK3399" -> "RK3399"
    """
    if not chip_text:
        return "Unknown Chip"

    chip_text = chip_text.strip()
    
    # Try to parse ASCII byte sequence (rkdeveloptool rci format)
    # Example: "36 37 35 33..." where each number is ASCII decimal code
    # 36=ASCII('6'), 37=ASCII('7'), 35=ASCII('5'), 33=ASCII('3')
    if ' ' in chip_text:
        try:
            byte_parts = chip_text.split()[:4]  # Take first 4 parts
            chip_id_str = ''
            for b in byte_parts:
                ascii_val = int(b)
                # Convert ASCII code to character, and keep only digits
                char = chr(ascii_val)
                if char.isdigit():
                    chip_id_str += char
            
            if chip_id_str and len(chip_id_str) >= 3:
                # Check if it matches our ASCII chip map
                if chip_id_str in ASCII_CHIP_MAP:
                    return ASCII_CHIP_MAP[chip_id_str]
                else:
                    return f"RK{chip_id_str}"  # Default to RKxxxx format
        except (ValueError, OverflowError):
            pass

    # Try to extract chip ID in hex format
    match = re.search(r'0x[0-9A-Fa-f]+', chip_text)
    if match:
        chip_id = match.group(0).upper()
        if chip_id in CHIP_ID_MAP:
            return CHIP_ID_MAP[chip_id]

    # Try to match chip name directly
    for chip_name in CHIP_FAMILIES.keys():
        if chip_name.lower() in chip_text.lower():
            return chip_name

    return chip_text


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
        except:
            pass
    
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
    lines = ["📋 Device Capability Information:\n"]
    
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
    lines = ["📦 Detailed Flash Information:\n"]
    
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