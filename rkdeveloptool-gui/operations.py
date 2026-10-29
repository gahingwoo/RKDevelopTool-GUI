"""
Device operations for RKDevelopTool GUI
Contains all device interaction methods with improved flash capacity detection
"""
import os
import re
import shutil
import subprocess
import tempfile
import math
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QInputDialog, QApplication, QLineEdit, QCheckBox

from . import rkfw
from . import settings as app_settings
from .utils import (
    RKTOOL, parse_partition_info, parse_flash_info,
    calculate_file_md5, format_file_size, safe_slot, is_rkfw_image,
    detect_compression, decompressed_name, DECOMPRESSIBLE,
    classify_image_file, WHOLE_IMAGE_KINDS
)
from .workers import (
    PartitionPPTWorker, CommandWorker, RKFWPrepWorker, FileHashWorker,
    DecompressWorker, CallWorker
)
from .ui_text_updates import populate_address_combo, populate_partition_combo


def _is_sector_zero(address):
    """Return True if address resolves to LBA/sector 0 (the GPT/boot area)."""
    try:
        return int(str(address).strip(), 16) == 0
    except (TypeError, ValueError):
        return False


def style_messagebox(msg_box):
    """Apply current application theme to QMessageBox via palette"""
    msg_box.setPalette(QApplication.palette())


def get_rkdeveloptool_version():
    """Get rkdeveloptool version"""
    try:
        env = os.environ.copy()
        env['NO_COLOR'] = '1'
        env['CLICOLOR'] = '0'
        env['CLICOLOR_FORCE'] = '0'
        result = subprocess.run([RKTOOL, "--version"], capture_output=True, text=True, timeout=2, env=env)
        output = (result.stdout or "") + (result.stderr or "")
        # Parse "rkdeveloptool ver 1.32" format
        m = re.search(r'ver\s+([\d.]+)', output)
        if m:
            return m.group(1)
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    return "unknown"


def read_device_info(gui):
    """Read device capability information and cache flash info"""
    gui.run_command([RKTOOL, "rfi"], "reading_device_info")


def get_detailed_device_info(gui):
    """Get detailed device information and cache flash info"""
    gui.run_command([RKTOOL, "rcb"], "reading_device_info")


def get_flash_capacity_bytes(gui):
    """
    Get flash capacity in bytes from cached info or by querying device
    Returns: (bytes_size, source_description) or (None, error_message)
    """
    # Try cached flash info first
    if hasattr(gui, '_cached_flash_info') and gui._cached_flash_info:
        capacity_str = gui._cached_flash_info.get('capacity', '')
        if capacity_str:
            m = re.match(r'([0-9.]+)\s*(MB|GB)', capacity_str, re.I)
            if m:
                val = float(m.group(1))
                unit = m.group(2).upper()
                bytes_size = int(val * 1024 ** (3 if unit == 'GB' else 2))
                return bytes_size, f"cached ({capacity_str})"

    # Query device for flash info
    try:
        env = os.environ.copy()
        env['NO_COLOR'] = '1'
        env['CLICOLOR'] = '0'
        env['CLICOLOR_FORCE'] = '0'
        from . import utils
        with utils.DEVICE_LOCK:
            result = subprocess.run([RKTOOL, "rfi"], capture_output=True, text=True,
                                    timeout=6, env=env)
        out = (result.stdout or "") + "\n" + (result.stderr or "")

        # Try to parse capacity
        m = re.search(r'capacity[:\s]*([0-9.]+)\s*(MB|GB)', out, re.I)
        if m:
            val = float(m.group(1))
            unit = m.group(2).upper()
            bytes_size = int(val * 1024 ** (3 if unit == 'GB' else 2))

            # Cache the result
            flash_info = parse_flash_info(out)
            if flash_info:
                gui._cached_flash_info = flash_info

            return bytes_size, f"detected ({val} {unit})"

        # Try to parse size field
        m2 = re.search(r'size[:\s]*(0x[0-9A-Fa-f]+)', out, re.I)
        if m2:
            bytes_size = int(m2.group(1), 16)
            return bytes_size, f"detected (0x{m2.group(1)})"

        return None, "no_capacity_info"

    except subprocess.TimeoutExpired:
        return None, "device_timeout"
    except Exception as e:
        return None, f"query_error: {str(e)}"


def backup_firmware(gui):
    """Backup entire firmware with automatic capacity detection"""
    save_path = app_settings.get_save_file(
        gui, gui.tr("save_file_dialog"), "firmware_backup.bin", gui.tr("file_dialog_all")
    )
    if not save_path:
        return

    # Try to get flash capacity automatically
    bytes_size, source = get_flash_capacity_bytes(gui)

    if bytes_size and bytes_size > 0:
        sectors = (bytes_size + 511) // 512
        length_arg = hex(sectors)

        size_mb = bytes_size / (1024 ** 2)
        size_gb = bytes_size / (1024 ** 3)

        if size_gb >= 1:
            size_display = f"{size_gb:.2f} GB"
        else:
            size_display = f"{size_mb:.2f} MB"

        gui.log_message(f"[INFO] {gui.tr('detected_flash_size')}: {size_display} ({source})")
        gui.log_message(f"[INFO] {gui.tr('backup_sectors')}: {length_arg} ({sectors:,} sectors)")

        # Confirm with user
        msg = QMessageBox()
        style_messagebox(msg)
        msg.setWindowTitle(gui.tr("confirm_backup_title"))
        msg.setIcon(QMessageBox.Icon.Question)

        detail_text = f"""
{gui.tr("backup_confirmation_message")}

{gui.tr("flash_capacity")}: {size_display}
{gui.tr("total_sectors")}: {sectors:,} ({length_arg})
{gui.tr("save_to")}: {os.path.basename(save_path)}

{gui.tr("backup_time_warning")}
        """

        msg.setText(detail_text)
        msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
        msg.setMinimumWidth(550)
        # Clear focus to prevent button highlighting
        msg.setFocus()

        if msg.exec() == QMessageBox.StandardButton.Yes:
            gui.run_command([RKTOOL, "rl", "0x0", length_arg, save_path], "backing_up")
        return

    # Fallback: ask user for length
    gui.log_message(f"[WARNING] {gui.tr('auto_detect_failed')}: {source}")

    text, ok = QInputDialog.getText(
        gui,
        gui.tr('enter_backup_length_title'),
        gui.tr('enter_backup_length_prompt') + f"\n\n{gui.tr('format_examples')}"
    )

    if not ok or not text:
        gui.show_message('Information', 'backup_cancelled')
        return

    length_arg = _parse_length_arg(text)
    if length_arg != text.strip():
        gui.log_message(f"[INFO] {gui.tr('calculated_sectors')}: {length_arg}")

    gui.run_command([RKTOOL, "rl", "0x0", length_arg, save_path], "backing_up")


def _parse_length_arg(text):
    """Convert a user-entered length ('128MB', '1.5GB', or a raw sector-count hex
    string like '0x1E0000') into the sector-count hex string rkdeveloptool expects."""
    text = text.strip()
    m = re.match(r'^([0-9.]+)\s*(MB|GB)$', text, re.I)
    if m:
        val = float(m.group(1))
        unit = m.group(2).upper()
        bytes_size = int(val * 1024 ** (3 if unit == 'GB' else 2))
        sectors = (bytes_size + 511) // 512
        return hex(sectors)
    return text


def _partition_length_arg(gui, info):
    """Return the sector-count CLI argument needed to read/write a partition in full.

    `info['size']` from parse_partition_info() is already the sector count between this
    partition's start and the next one's, except for the last partition where the size
    is unknown - there we read to the end of the detected flash capacity instead.
    """
    size = info.get('size')
    if size and size != 'unknown':
        try:
            int(size, 16)
            return size
        except (TypeError, ValueError):
            pass

    try:
        start_sectors = int(info.get('address', '0x0'), 16)
    except (TypeError, ValueError):
        return None

    bytes_size, _ = get_flash_capacity_bytes(gui)
    if not bytes_size:
        return None

    total_sectors = bytes_size // 512
    remaining = total_sectors - start_sectors
    return hex(remaining) if remaining > 0 else None


def enter_maskrom_mode(gui):
    """Switch a device in Loader mode back into Maskrom mode.

    rkdeveloptool's reset command takes a subcode (``rd [subcode]``);
    subcode 3 asks the chip to reboot into the Maskrom stage. The old code
    ran ``db <loader>``, which does the opposite - it downloads a boot file
    and pulls a Maskrom chip *into* Loader mode - so this button never
    actually entered Maskrom.
    """
    if not getattr(gui, 'current_device', None):
        gui.show_message("Warning", "connect_device_first", "Warning")
        return
    mode = getattr(gui, 'device_mode', '') or ''
    if 'Maskrom' in mode:
        gui.show_message("already_maskrom_title", "already_maskrom_message", "Information")
        return
    gui.log_message(f"[INFO] {gui.tr('entering_maskrom')}")
    gui.run_command([RKTOOL, "rd", "3"], "entering_maskrom")


def enter_loader_mode(gui):
    """Enter Loader mode"""
    load_loader(gui)


def reset_device(gui):
    """Reset/reboot device"""
    gui.run_command([RKTOOL, "rd"], "rebooting")


def read_partition_table(gui):
    """Read partition table in background"""
    try:
        if getattr(gui, '_partition_refresh_lock', False):
            gui.log_message(gui.tr('reading_partitions_already'))
            return

        if hasattr(gui, 'splitter'):
            gui._splitter_sizes_prev = gui.splitter.sizes()

        if hasattr(gui, 'partition_worker') and gui.partition_worker and gui.partition_worker.isRunning():
            gui.log_message(gui.tr('reading_partitions_already'))
            return

        gui._partition_refresh_lock = True
        gui.partition_worker = PartitionPPTWorker()
        gui.partition_worker.finished.connect(safe_slot(lambda out, code: on_partition_ppt_finished(gui, out, code)))
        gui.partition_worker.start()

        gui.log_message(gui.tr('reading_partitions'))
        gui.statusBar().showMessage(gui.tr('reading_partitions'))

    except Exception:
        gui._partition_refresh_lock = True
        try:
            env = os.environ.copy()
            env['NO_COLOR'] = '1'
            env['CLICOLOR'] = '0'
            env['CLICOLOR_FORCE'] = '0'
            from . import utils
            with utils.DEVICE_LOCK:
                result = subprocess.run([RKTOOL, "ppt"], capture_output=True, text=True,
                                        timeout=5, env=env)
            if result.returncode == 0:
                gui.partitions = parse_partition_info(result.stdout)
                populate_partition_table(gui)
                populate_partition_combo(gui)
                populate_address_combo(gui)
                gui.log_message(gui.tr('partition_read_ok'))
        except Exception:
            pass
        finally:
            gui._partition_refresh_lock = False
            gui._restore_splitter_sizes()


def on_partition_ppt_finished(gui, out, code):
    """Handle partition read completion"""
    try:
        if code == 0 and out:
            gui.partitions = parse_partition_info(out)
            populate_partition_table(gui)
            populate_partition_combo(gui)
            populate_address_combo(gui)
            gui.log_message(gui.tr('partition_read_ok'))
            gui.statusBar().showMessage(gui.tr('partition_read_ok'))
        else:
            # Say why (blank storage, no loader, device busy, ...) instead of
            # leaving the table silently empty.
            gui.log_message(out.strip() or f"[ERROR] {gui.tr('partition_read_failed')}")
            gui.statusBar().showMessage(gui.tr('partition_read_failed'), 6000)
            guidance = gui.explain_failure(out) if hasattr(gui, 'explain_failure') else None
            if guidance:
                gui.log_message(f"[ERROR] {guidance[0]}\n{guidance[1]}")
                gui._show_failure_guidance("reading_partitions", guidance[0], guidance[1], out)
            else:
                gui.show_message("Warning", "partition_read_failed", "Warning")
    except Exception as e:
        gui.log_message(f"[WARNING] parse ppt failed: {e}")
    finally:
        gui._restore_splitter_sizes()
        gui._partition_refresh_lock = False


def populate_partition_table(gui):
    """Populate partition table widget"""
    gui.partition_table.setRowCount(0)
    gui._restore_splitter_sizes()

    if not gui.partitions:
        return

    items = list(gui.partitions.items())
    gui.partition_table.setRowCount(len(items))

    for row, (name, info) in enumerate(items):
        addr = info.get('address', '')
        size = info.get('size', '')

        from PySide6.QtWidgets import QTableWidgetItem, QWidget, QHBoxLayout, QPushButton

        gui.partition_table.setItem(row, 0, QTableWidgetItem(name))
        gui.partition_table.setItem(row, 1, QTableWidgetItem(addr))
        gui.partition_table.setItem(row, 2, QTableWidgetItem(size))

        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)

        backup_btn = QPushButton(gui.tr('action_backup'))
        write_btn = QPushButton(gui.tr('action_write'))

        backup_btn.clicked.connect(safe_slot(lambda checked=False, n=name: backup_partition_by_name(gui, n)))
        write_btn.clicked.connect(safe_slot(lambda checked=False, n=name: write_partition_by_name(gui, n)))

        action_layout.addWidget(backup_btn)
        action_layout.addWidget(write_btn)

        gui.partition_table.setCellWidget(row, 3, action_widget)

    try:
        gui.partition_table.resizeColumnsToContents()
        gui.partition_table.resizeRowsToContents()
        gui.partition_table.horizontalHeader().setStretchLastSection(True)
    except (RuntimeError, AttributeError) as e:
        print(f"Warning: Failed to resize partition table: {e}")


def backup_partition_by_name(gui, name):
    """Backup partition by name"""
    save_path = app_settings.get_save_file(gui, gui.tr('save_file_dialog'), f"{name}.bin")
    if not save_path:
        return

    try:
        if gui.manual_address_enable.isChecked():
            addr = gui.manual_address.text().strip()
            if not addr:
                gui.show_message("Warning", "enter_manual_address", "Warning")
                return
            text, ok = QInputDialog.getText(
                gui, gui.tr('enter_backup_length_title'),
                gui.tr('enter_backup_length_prompt') + f"\n\n{gui.tr('format_examples')}"
            )
            if not ok or not text:
                gui.show_message('Information', 'backup_cancelled')
                return
            gui.run_command([RKTOOL, "rl", addr, _parse_length_arg(text), save_path], "backing_up")
            return
    except (AttributeError, RuntimeError) as e:
        print(f"Warning: Failed to check manual address: {e}")

    if name in gui.partitions:
        info = gui.partitions[name]
        addr = info.get('address')
        length_arg = _partition_length_arg(gui, info)
        if addr and length_arg:
            gui.run_command([RKTOOL, "rl", addr, length_arg, save_path], "backing_up")
            return
        gui.log_message(f"[WARNING] Could not determine size of partition '{name}'; backup aborted.")

    gui.show_message("Warning", "select_partition", "Warning")


def write_partition_by_name(gui, name):
    """Write partition by name"""
    file_path = app_settings.get_open_file(gui, gui.tr('browse_btn'), gui.tr('file_dialog_image'))
    if not file_path or not os.path.exists(file_path):
        return

    try:
        if gui.manual_address_enable.isChecked():
            addr = gui.manual_address.text().strip()
            if not addr:
                gui.show_message("Warning", "enter_manual_address", "Warning")
                return
            if _is_sector_zero(addr) and is_rkfw_image(file_path):
                gui.show_message("rkfw_detected_title", "rkfw_detected_message", "Critical")
                return
            _burn_file(gui, file_path, addr, lambda path: [RKTOOL, "wl", addr, path])
            return
    except (AttributeError, RuntimeError) as e:
        print(f"Warning: Failed to check manual address: {e}")

    if name:
        addr = gui.partitions.get(name, {}).get('address', name) if hasattr(gui, 'partitions') else name
        _burn_file(gui, file_path, addr, lambda path: [RKTOOL, "wlx", name, path])
        return

    gui.show_message("Warning", "select_partition", "Warning")


def onekey_burn(gui):
    """One-click burn firmware"""
    firmware_path = gui.firmware_path.text()
    if not firmware_path or not os.path.exists(firmware_path):
        gui.show_message("Warning", "select_firmware_file", "Warning")
        return
    if is_rkfw_image(firmware_path):
        _flash_rkfw_firmware(gui, firmware_path)
        return
    _burn_file(gui, firmware_path, "0x0", lambda path: [RKTOOL, "wl", "0x0", path])


def _show_rkfw_message(gui, title_key, text, icon="Critical"):
    """Show a QMessageBox for RKFW flashing errors/status with dynamic text
    that gui.show_message()'s static-key-only signature can't express."""
    msg = QMessageBox()
    style_messagebox(msg)
    msg.setWindowTitle(gui.tr(title_key))
    msg.setText(text)
    msg.setMinimumWidth(550)
    if icon == "Critical":
        msg.setIcon(QMessageBox.Icon.Critical)
    elif icon == "Warning":
        msg.setIcon(QMessageBox.Icon.Warning)
    else:
        msg.setIcon(QMessageBox.Icon.Information)
    msg.exec()


def _confirm_rkfw_flash(gui, firmware_path, rkaf_info, real_parts):
    """Show the partition list and a strong warning before a full RKFW
    (update.img) flash - this rewrites the GPT and every partition.

    Also asks whether to CRC-verify the firmware package before unpacking
    (default on). Returns (accepted, verify_crc)."""
    version = rkaf_info.version
    version_str = f"{(version >> 24) & 0xFF}.{(version >> 16) & 0xFF}.{version & 0xFFFF}"
    file_size = format_file_size(os.path.getsize(firmware_path))

    part_lines = "\n".join(
        f"  - {p.name} ({format_file_size(p.size)})" for p in real_parts
    )

    msg = QMessageBox()
    style_messagebox(msg)
    msg.setWindowTitle(gui.tr("rkfw_confirm_title"))
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setText(
        f"{gui.tr('rkfw_confirm_intro')}\n\n"
        f"{gui.tr('file_name')}: {os.path.basename(firmware_path)} ({file_size})\n"
        f"Model: {rkaf_info.model}  Manufacturer: {rkaf_info.manufacturer}  "
        f"Version: {version_str}\n\n"
        f"Partitions ({len(real_parts)}):\n{part_lines}\n\n"
        f"{gui.tr('rkfw_confirm_warning')}\n\n"
        f"{gui.tr('rkfw_confirm_proceed')}"
    )
    verify_check = QCheckBox(gui.tr("rkfw_verify_crc_checkbox"))
    verify_check.setChecked(True)
    msg.setCheckBox(verify_check)
    msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    msg.setDefaultButton(QMessageBox.StandardButton.No)
    msg.setMinimumWidth(600)
    accepted = msg.exec() == QMessageBox.StandardButton.Yes
    return accepted, verify_check.isChecked()


def _flash_rkfw_firmware(gui, firmware_path):
    """Unpack an RKFW-packed update.img and flash it in full.

    Header parsing and the confirmation dialog are fast and stay on the GUI
    thread; the slow part - CRC-verifying the whole RKAF archive and
    unpacking the Loader/parameter/every partition to a temp dir - runs on
    RKFWPrepWorker, which reports real progress so the window no longer
    freezes. The actual per-partition writes then run one by one via
    _run_rkfw_steps, which already streams rkdeveloptool's live progress.

    See rkfw.py for the on-disk format this relies on.
    """
    # Refuse a second full flash up front, before any dialogs: the flag covers
    # the whole run, while the worker check alone would only cover the
    # verify/unpack phase and leave the much longer flashing phase open.
    if getattr(gui, '_rkfw_flashing', False):
        gui.log_message(gui.tr('rkfw_flash_in_progress'))
        return
    worker = getattr(gui, '_rkfw_worker', None)
    if worker is not None and worker.isRunning():
        gui.log_message(gui.tr('rkfw_flash_in_progress'))
        return

    try:
        rkfw_info = rkfw.parse_rkfw_header(firmware_path)
        rkaf_info = rkfw.parse_rkaf_header(firmware_path, rkfw_info.fw_offset,
                                            rkfw_info.fw_size)
    except rkfw.RKFWError as e:
        gui.log_message(f"[ERROR] {e}")
        _show_rkfw_message(gui, "rkfw_parse_failed_title", str(e))
        return

    param_part = next((p for p in rkaf_info.parts if p.is_parameter), None)
    if not param_part:
        _show_rkfw_message(gui, "rkfw_no_parameter_title", gui.tr("rkfw_no_parameter_message"))
        return

    real_parts = [p for p in rkaf_info.parts if not p.is_parameter and not p.is_self]

    if hasattr(gui, 'device_mode') and 'Maskrom' not in gui.device_mode:
        gui.show_message("rkfw_requires_maskrom_title", "rkfw_requires_maskrom_message", "Warning")
        return

    confirmed, verify_crc = _confirm_rkfw_flash(gui, firmware_path, rkaf_info, real_parts)
    if not confirmed:
        return

    tmp_dir = tempfile.mkdtemp(prefix="rkdevtool_rkfw_")
    _set_rkfw_busy(gui, True)
    gui.progress_bar.setValue(0)
    gui.progress_label.setText(gui.tr("preparing_firmware"))

    worker = RKFWPrepWorker(firmware_path, rkfw_info, rkaf_info, tmp_dir,
                            gui.manager, verify_crc=verify_crc)
    gui._rkfw_worker = worker
    gui._rkfw_tmp_dir = tmp_dir
    worker.progress.connect(safe_slot(lambda v: _on_rkfw_prep_progress(gui, v)))
    worker.log.connect(safe_slot(gui.log_message))
    worker.finished.connect(safe_slot(lambda paths: _start_rkfw_steps(gui, paths, tmp_dir)))
    worker.failed.connect(safe_slot(lambda kind, msg: _on_rkfw_prep_failed(gui, kind, msg, tmp_dir)))
    worker.start()


def _set_rkfw_busy(gui, busy):
    """Disable device-touching actions while a full RKFW flash runs.

    The flag is what actually holds: the device poller re-runs
    _update_action_states() every couple of seconds (and the board
    re-enumerates after db/ul), so simply calling setEnabled(False) here
    would be undone almost immediately.
    """
    gui._rkfw_flashing = bool(busy)
    if hasattr(gui, '_update_poll_mode'):
        gui._update_poll_mode()
    try:
        gui._update_action_states()
    except Exception as e:
        print(f"Warning: could not update action states: {e}")


def _on_rkfw_prep_progress(gui, value):
    gui.progress_bar.setValue(value)
    gui.progress_label.setText(f"{gui.tr('preparing_firmware')} {value}%")


def _finish_rkfw_flow(gui, tmp_dir):
    """Clean up state shared by every exit path of an RKFW full flash."""
    if hasattr(gui, 'end_job'):
        gui.end_job()
    shutil.rmtree(tmp_dir, ignore_errors=True)
    gui._rkfw_worker = None
    gui._rkfw_tmp_dir = None
    _set_rkfw_busy(gui, False)
    gui.progress_label.setText(gui.tr("ready"))


def _on_rkfw_prep_failed(gui, kind, message, tmp_dir):
    """Handle a failed verify/unpack pass before any flashing started."""
    _finish_rkfw_flow(gui, tmp_dir)
    if kind == 'cancelled':
        gui._cancel_requested = False
        gui.log_message(f"[WARNING] {gui.tr('cancelled_log')}")
        return
    if kind == 'crc':
        gui.log_message("[ERROR] RKAF CRC mismatch")
        _show_rkfw_message(gui, "rkfw_crc_mismatch_title", gui.tr("rkfw_crc_mismatch_message"))
    else:
        gui.log_message(f"[ERROR] {message}")
        _show_rkfw_message(gui, "rkfw_extract_failed_title", message)


def _start_rkfw_steps(gui, paths, tmp_dir):
    """Begin flashing the unpacked images.

    The order follows the RK3576 behaviour documented in
    RK3576-手动刷固件指南.md: on a fresh Maskrom the chip refuses every
    "read flash info" request until a loader has been downloaded into RAM,
    so `gpt` must come *after* `db`. The loader is then persisted to the
    idb area with `ul` (never `wlx bootloader`), and every remaining
    archive partition is flashed by name - except `package-file`, which is
    tool metadata and not a real partition.
    """
    # RKAF entries that must not be written as GPT partitions:
    # - "package-file" is tool metadata consumed by Rockchip's own tools.
    # - "bootloader" is the MiniLoader/idb image; it goes to the idb area
    #   above (via `ul`), not to a GPT partition named "bootloader".
    skip_names = {"package-file", "bootloader"}

    steps = [
        ([RKTOOL, "db", paths['loader']], "loading_loader", gui.tr("rkfw_step_loader")),
        ([RKTOOL, "gpt", paths['parameter']], "importing_gpt", gui.tr("rkfw_step_gpt")),
        ([RKTOOL, "ul", paths['loader']], "writing_idb", gui.tr("rkfw_step_idb")),
    ]
    for name, part_path in paths['parts']:
        if name in skip_names:
            gui.log_message(f"[INFO] {gui.tr('rkfw_skip_partition').format(name)}")
            continue
        steps.append(([RKTOOL, "wlx", name, part_path], "burning",
                      gui.tr("rkfw_step_partition").format(name)))

    gui.log_message(f"[INFO] {gui.tr('rkfw_flash_starting').format(len(steps))}")
    # Weight each step by the file it writes (every step's last argument),
    # so the bar shows the whole flash rather than restarting per step.
    gui._rkfw_step_bytes = [os.path.getsize(cmd[-1]) if os.path.isfile(cmd[-1]) else 0
                            for cmd, _, _ in steps]
    if hasattr(gui, 'begin_job'):
        gui.begin_job(sum(gui._rkfw_step_bytes))
    _run_rkfw_steps(gui, steps, 0, tmp_dir)


def _run_rkfw_steps(gui, steps, index, tmp_dir, attempts=0):
    """Run the extracted RKFW flash steps one at a time, aborting on the
    first failure that persists after a few retries.

    Transient device-state failures are common mid-flash: `db` makes the
    board re-enumerate on USB and the next `gpt` can race it, so failed
    steps are retried a couple of times with a short pause instead of
    aborting the whole flash at the first hiccup.
    """
    max_attempts = 2  # extra attempts after the first failure

    if index >= len(steps):
        _finish_rkfw_flow(gui, tmp_dir)
        gui.log_message(f"[OK] {gui.tr('rkfw_flash_complete_title')}")
        _show_rkfw_message(gui, "rkfw_flash_complete_title",
                            gui.tr("rkfw_flash_complete_message"), "Information")
        return

    if getattr(gui, '_cancel_requested', False):
        # Cancelled between steps (e.g. while the board re-enumerated).
        gui._cancel_requested = False
        _finish_rkfw_flow(gui, tmp_dir)
        gui.log_message(f"[WARNING] {gui.tr('cancelled_log')}")
        _show_rkfw_message(gui, "cancelled_partial_title",
                           gui.tr("cancelled_partial_message"), "Warning")
        return

    cmd, description_key, label = steps[index]
    gui.log_message(f"[{index + 1}/{len(steps)}] {label}")
    sizes = getattr(gui, '_rkfw_step_bytes', None)
    if hasattr(gui, 'job_stage') and sizes and len(sizes) == len(steps):
        gui.job_stage(f"[{index + 1}/{len(steps)}] {label}", sum(sizes[:index]), sizes[index])

    def on_step_done(success, output):
        if not success and getattr(gui, '_cancel_requested', False):
            # Cancelled mid-step: no retry; the window reports it.
            _finish_rkfw_flow(gui, tmp_dir)
            return
        if not success and getattr(gui, '_lost_during_write', False):
            # The device went away mid-write; retrying can't help, and the
            # window explains how to recover once this returns.
            gui.log_message(f"[ERROR] {label}")
            _finish_rkfw_flow(gui, tmp_dir)
            return
        if not success:
            if attempts < max_attempts:
                gui.log_message(f"[WARNING] {gui.tr('rkfw_step_retry').format(attempts + 1)}")
                QTimer.singleShot(1000, safe_slot(
                    lambda: _run_rkfw_steps(gui, steps, index, tmp_dir, attempts + 1)))
                return
            gui.log_message(f"[ERROR] {label}")
            _finish_rkfw_flow(gui, tmp_dir)
            text = gui.tr("rkfw_flash_failed_message")
            guidance = gui.explain_failure(output) if hasattr(gui, 'explain_failure') else None
            if guidance:
                text += f"\n\n{label}: {guidance[0]}\n\n{guidance[1]}"
            _show_rkfw_message(gui, "rkfw_flash_failed_title", text)
            return

        # `db` and `ul` both make the device re-enumerate on USB; give the
        # freshly downloaded/written loader a generous moment to come back
        # (5 s) before the next step.
        if description_key in ('loading_loader', 'writing_idb'):
            gui.log_message(f"[INFO] {gui.tr('rkfw_waiting_reenum')}")
            QTimer.singleShot(5000, safe_slot(
                lambda: _run_rkfw_steps(gui, steps, index + 1, tmp_dir)))
            return

        # Schedule the next step on a fresh event-loop tick. Doing this from
        # inside the just-finished worker's signal handler can race the
        # worker thread's final teardown (its isRunning() is still True),
        # which makes run_command bail out with "command already running"
        # and silently stalls the whole flash chain.
        QTimer.singleShot(0, safe_slot(
            lambda: _run_rkfw_steps(gui, steps, index + 1, tmp_dir)))

    _run_when_idle(gui, cmd, description_key, on_step_done)


def _run_when_idle(gui, cmd, description_key, callback, waited_ms=0):
    """Start a command once the previous one's worker has fully exited.

    run_command() refuses to start while the last CommandWorker is still
    running and returns *without* invoking the callback - which would leave
    the flash chain stalled forever. Deferring by one tick narrows that race
    but can't close it, since the worker emits its finished signal from
    inside run(), before the thread actually exits. So poll briefly here
    instead of firing and hoping.
    """
    max_wait_ms = 15000
    worker = getattr(gui, 'command_worker', None)
    if worker is not None and worker.isRunning():
        if waited_ms >= max_wait_ms:
            gui.log_message("[ERROR] Previous command did not finish in time")
            tmp_dir = getattr(gui, '_rkfw_tmp_dir', None)
            if tmp_dir:
                _finish_rkfw_flow(gui, tmp_dir)
            _show_rkfw_message(gui, "rkfw_flash_failed_title",
                                gui.tr("rkfw_flash_failed_message"))
            return
        QTimer.singleShot(50, safe_slot(
            lambda: _run_when_idle(gui, cmd, description_key, callback,
                                    waited_ms + 50)))
        return

    gui.run_command(cmd, description_key, callback)


def load_loader(gui):
    """Load loader file"""
    loader_path = gui.loader_path.text()
    
    # If loader path not set or file doesn't exist, ask user to select
    if not loader_path or not os.path.exists(loader_path):
        loader_path = app_settings.get_open_file(
            gui, gui.tr("select_loader_file"), gui.tr("file_dialog_loader")
        )
        if not loader_path:
            return
        gui.loader_path.setText(loader_path)
    
    # In Maskrom the loader can only go to RAM (db); ul needs a loader that is
    # already running and fails here, so don't make the user pick.
    if 'Maskrom' in getattr(gui, 'device_mode', ''):
        gui.log_message(f"[INFO] {gui.tr('loader_auto_db')}")
        _start_loader(gui, "db", loader_path)
        return

    # Ask user to choose between ul (upload) or db (download)
    msg = QMessageBox()
    style_messagebox(msg)
    msg.setWindowTitle(gui.tr("loader_load_method_title"))
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setText(gui.tr("loader_load_method_message"))
    msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    
    # Set custom button text - make them clear and distinct
    msg.button(QMessageBox.StandardButton.No).setText(gui.tr("loader_download"))
    msg.button(QMessageBox.StandardButton.Yes).setText(gui.tr("loader_upload"))
    
    msg.setMinimumWidth(550)
    result = msg.exec()
    
    # Determine which command to use
    if result == QMessageBox.StandardButton.Yes:
        cmd_type = "ul"
    else:
        cmd_type = "db"
    
    _start_loader(gui, cmd_type, loader_path)


def _start_loader(gui, cmd_type, loader_path):
    """Run db/ul with the loader and record whether it actually loaded."""
    gui.run_command([RKTOOL, cmd_type, loader_path], "loading_loader")

    # Mark that we're attempting to load loader and wrap the finished signal
    if gui.command_worker:
        def on_loader_finished(success, error_msg):
            if success:
                gui.loader_loaded = True
                gui.log_message("[OK] " + gui.tr("loader_loaded_success"))
                # Don't touch the storage target here: switching it (cs) is
                # what left an RK3576 refusing every read and write.
                detect_supported_storage_types(gui)
            gui.on_command_finished(success, error_msg)
        
        try:
            gui.command_worker.finished_signal.disconnect()
        except RuntimeError:
            # Signal not connected, which is fine
            pass
        gui.command_worker.finished_signal.connect(safe_slot(on_loader_finished))


def burn_image(gui):
    """Burn custom image"""
    image_path = gui.image_path.text()
    if not image_path or not os.path.exists(image_path):
        gui.show_message("Warning", "select_image_address", "Warning")
        return

    address = gui.address_combo.currentText()
    if gui.tr("custom_address") in address:
        address = gui.custom_address.text()
    else:
        match = re.search(r'\((\S+)\)', address)
        if match:
            address = match.group(1)

    if not address:
        gui.show_message("Warning", "select_image_address", "Warning")
        return

    if _is_sector_zero(address) and is_rkfw_image(image_path):
        gui.show_message("rkfw_detected_title", "rkfw_detected_message", "Critical")
        return

    _burn_file(gui, image_path, address, lambda path: [RKTOOL, "wl", address, path])


# Pre-flight check results.
PASS, WARN, FAIL, UNKNOWN = "pass", "warn", "fail", "unknown"
_CHECK_MARKS = {PASS: "✓", WARN: "⚠", FAIL: "✗", UNKNOWN: "?"}
SECTOR_SIZE = 512


def _sector_address(address):
    """An rkdeveloptool LBA ("0x0", "0x8000", "32768"), or None."""
    try:
        return int(str(address).strip(), 0)
    except (TypeError, ValueError):
        return None


def _can_query_flash(gui):
    """Whether rfi can answer now: a device is there and, in Maskrom, a
    loader is running (otherwise it fails or times out)."""
    if getattr(gui, 'current_device', None) is None:
        return False
    return not ('Maskrom' in (getattr(gui, 'device_mode', '') or '')
                and not getattr(gui, 'loader_loaded', False))


def preflight_checks(gui, file_path, address, capacity):
    """What to check before writing file_path at address: a list of
    (status, text). Any FAIL blocks the write. capacity is the storage size
    in bytes, or None when it couldn't be read - reported as unknown, never
    as passed.
    """
    tr = gui.tr
    checks = []
    mode = getattr(gui, 'device_mode', '') or ''
    if getattr(gui, 'current_device', None) is None:
        checks.append((FAIL, tr("pf_no_device")))
    else:
        checks.append((PASS, tr("pf_device").format(mode)))
        if 'Maskrom' in mode and not getattr(gui, 'loader_loaded', False):
            checks.append((FAIL, tr("pf_need_loader")))
        else:
            checks.append((PASS, tr("pf_loader_ready")))

    lba = _sector_address(address)
    size = os.path.getsize(file_path)
    if lba == 0:
        kind = classify_image_file(file_path)
        if kind == 'loader':
            checks.append((FAIL, tr("pf_loader_at_zero")))
        elif kind in WHOLE_IMAGE_KINDS:
            checks.append((PASS, tr("pf_whole_image")))
        else:
            checks.append((WARN, tr("pf_not_whole_image")))

    if capacity is None or lba is None:
        checks.append((UNKNOWN, tr("pf_capacity_unknown")))
    else:
        end = lba * SECTOR_SIZE + size
        if end > capacity:
            checks.append((FAIL, tr("pf_capacity_too_big").format(
                format_file_size(end), format_file_size(capacity))))
        else:
            checks.append((PASS, tr("pf_capacity_fits").format(
                format_file_size(end), format_file_size(capacity))))
    return checks


def _burn_with_confirm(gui, file_path, address, on_confirm, on_cancel=None,
                       offer_verify=False):
    """Confirm a burn operation without freezing on large images.

    The MD5 shown in the dialog is computed on a FileHashWorker so the GUI
    keeps painting while a multi-GB image is read; `on_confirm()` is then
    invoked on the main thread if the user clicks Yes, and `on_cancel()`
    (if given) on every other way out.
    """
    on_cancel = on_cancel or (lambda: None)
    if getattr(gui, '_burn_confirm_active', False):
        gui.log_message(gui.tr('command_already_running'))
        on_cancel()
        return

    try:
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        size_str = format_file_size(file_size)
    except OSError as e:
        gui.log_message(f"[ERROR] {e}")
        on_cancel()
        return

    # Get current storage information
    current_storage_code = gui.change_storage_combo.currentData()
    current_storage_name = gui.change_storage_combo.currentText()
    storage_info = get_storage_info(gui, current_storage_code) if current_storage_code else {}

    gui._burn_confirm_active = True
    gui.progress_bar.setValue(0)
    gui.progress_label.setText(gui.tr("calculating_md5"))

    def show(md5sum, capacity):
        gui._burn_confirm_active = False
        gui.progress_label.setText(gui.tr("ready"))
        gui._last_burn_md5 = md5sum
        checks = preflight_checks(gui, file_path, address, capacity)
        verify = None
        if offer_verify and md5sum:
            verify = gui.settings.get_str(app_settings.KEY_VERIFY_AFTER_WRITE, "0") == "1"
        if _show_burn_confirm(gui, file_name, file_size, size_str,
                              md5sum or gui.tr("md5_unavailable"), address,
                              current_storage_name, storage_info, checks, verify):
            on_confirm()
        else:
            on_cancel()

    def on_md5_done(md5sum):
        gui._md5_worker = None
        if not _can_query_flash(gui):
            show(md5sum, None)
            return
        # rfi can take seconds on a slow device; don't freeze the window.
        gui.progress_label.setText(gui.tr("pf_reading_capacity"))
        query = CallWorker(lambda: get_flash_capacity_bytes(gui)[0])
        gui._capacity_worker = query

        def on_capacity(result):
            gui._capacity_worker = None
            show(md5sum, result if isinstance(result, int) else None)

        query.finished.connect(safe_slot(on_capacity))
        query.start()

    worker = FileHashWorker(file_path)
    # Keep a reference on the window: a QThread held only by a local goes out
    # of scope when this function returns, and PySide6 then destroys the C++
    # object mid-run ("QThread: Destroyed while thread is still running"),
    # aborting the process.
    gui._md5_worker = worker
    worker.progress.connect(safe_slot(lambda v: gui.progress_bar.setValue(v)))
    worker.finished.connect(safe_slot(on_md5_done))
    worker.start()


def _burn_file(gui, file_path, address, make_cmd):
    """Confirm and write an image, decompressing it first when it is an
    .img.xz / .img.gz / .img.bz2. make_cmd(path) builds the rkdeveloptool
    command for the file that will actually be written."""
    lba = _sector_address(address)

    def start(path, cleanup):
        size = os.path.getsize(path)
        verify = (lba is not None and getattr(gui, '_verify_after_write', False)
                  and getattr(gui, '_last_burn_md5', ''))
        expected = gui._last_burn_md5 if verify else ''
        if hasattr(gui, 'begin_job'):
            gui.begin_job(size * 2 if verify else size)
            gui.job_stage(gui.tr("stage_writing").format(os.path.basename(path)), 0, size)

        def after_write(success, output):
            if success and verify:
                _verify_written(gui, path, address, size, expected, cleanup)
            else:
                cleanup()

        gui.run_command(make_cmd(path), "burning", after_write)

    def burn(path, cleanup):
        _burn_with_confirm(gui, path, address, lambda: start(path, cleanup), on_cancel=cleanup,
                           offer_verify=lba is not None)

    _with_plain_image(gui, file_path, burn)


def _verify_written(gui, path, address, size, expected_md5, cleanup):
    """Read back what was just written at address and compare its MD5 with
    the image's. The readback is rounded up to whole sectors, so only its
    first `size` bytes are hashed."""
    name = os.path.basename(path)
    sectors = -(-size // SECTOR_SIZE)
    try:
        tmp_dir = tempfile.mkdtemp(prefix=".rkdevtool_verify_",
                                   dir=os.path.dirname(os.path.abspath(path)))
    except OSError:
        tmp_dir = tempfile.mkdtemp(prefix="rkdevtool_verify_")
    readback = os.path.join(tmp_dir, "readback.bin")

    def finish():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        cleanup()

    if hasattr(gui, 'begin_job'):
        gui.begin_job(size * 2)
        gui.job_stage(gui.tr("stage_verifying").format(name), size, size)
    gui.log_message(f"[INFO] {gui.tr('stage_verifying').format(name)}")

    def after_read(success, output):
        if not success:  # the failure itself is explained by the window
            finish()
            return
        gui.progress_label.setText(gui.tr("verify_comparing"))
        worker = FileHashWorker(readback, length=size)
        gui._verify_hash_worker = worker

        def compared(md5sum):
            gui._verify_hash_worker = None
            if md5sum and md5sum == expected_md5:
                finish()
                gui.log_message(f"[OK] {gui.tr('verify_ok').format(name)}")
                _show_rkfw_message(gui, "verify_ok_title",
                                   gui.tr("verify_ok").format(name), "Information")
                return
            # A mismatch may only mean the loader can't read part of the
            # storage back; look for its filler before calling the write bad.
            from .utils import find_readback_filler
            scan = CallWorker(lambda: find_readback_filler(readback, path, size))
            gui._verify_hash_worker = scan

            def scanned(filler_at):
                gui._verify_hash_worker = None
                finish()
                if isinstance(filler_at, int):
                    where = format_file_size(filler_at)
                    gui.log_message(f"[WARNING] {gui.tr('verify_unreliable_title')}: "
                                    f"filler from {where}")
                    _show_rkfw_message(gui, "verify_unreliable_title",
                                       gui.tr("verify_unreliable_message").format(where), "Warning")
                    return
                gui.log_message(f"[ERROR] {gui.tr('verify_mismatch_title')}: "
                                f"{md5sum or '?'} != {expected_md5}")
                _show_rkfw_message(gui, "verify_mismatch_title",
                                   gui.tr("verify_mismatch_message").format(name))

            scan.finished.connect(safe_slot(scanned))
            scan.start()

        worker.finished.connect(safe_slot(compared))
        worker.start()

    # The write's worker is still winding down inside its finished signal.
    _run_when_idle(gui, [RKTOOL, "rl", str(address), hex(sectors), readback],
                   "verifying", after_read)


def _with_plain_image(gui, file_path, on_ready):
    """Call on_ready(path, cleanup) with an uncompressed copy of file_path.

    A raw image is passed straight through. A compressed one is unpacked on
    a DecompressWorker first, next to the original when that directory is
    writable (/tmp is often a small tmpfs, too small for a multi-GB image),
    and cleanup() deletes the copy once the caller is done with it. Formats
    the standard library can't unpack are refused rather than written raw,
    which would leave the board unbootable while reporting success.
    """
    kind = detect_compression(file_path)
    if kind is None:
        on_ready(file_path, lambda: None)
        return
    if kind not in DECOMPRESSIBLE:
        _show_rkfw_message(gui, "compressed_image_title",
                           gui.tr("compressed_unsupported_message").format(kind))
        return
    worker = getattr(gui, '_decompress_worker', None)
    if worker is not None and worker.isRunning():
        gui.log_message(gui.tr('command_already_running'))
        return

    tmp_dir = _make_unpack_dir(gui, file_path)
    dest = os.path.join(tmp_dir, decompressed_name(file_path))

    def cleanup():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if getattr(gui, '_decompress_tmp_dir', None) == tmp_dir:
            gui._decompress_tmp_dir = None

    def done(path):
        gui._decompress_worker = None
        _set_image_prep_busy(gui, False)
        gui.progress_label.setText(gui.tr("ready"))
        gui.log_message(f"[OK] {gui.tr('decompress_done').format(path)}")
        if is_rkfw_image(path):
            cleanup()
            _show_rkfw_message(gui, "compressed_image_title",
                               gui.tr("compressed_rkfw_message"))
            return
        on_ready(path, cleanup)

    def failed(reason, message):
        gui._decompress_worker = None
        _set_image_prep_busy(gui, False)
        gui.progress_label.setText(gui.tr("ready"))
        cleanup()
        if reason == 'cancelled':
            gui._cancel_requested = False
            gui.log_message(f"[WARNING] {gui.tr('cancelled_log')}")
            return
        gui.log_message(f"[ERROR] {gui.tr('decompress_failed_title')}: {message}")
        if reason == 'nospace':
            text = gui.tr("decompress_nospace_message").format(tmp_dir)
        elif reason == 'corrupt':
            text = gui.tr("decompress_corrupt_message").format(message)
        else:
            text = message
        _show_rkfw_message(gui, "decompress_failed_title", text)

    def progress(value):
        gui.progress_bar.setValue(value)
        gui.progress_label.setText(f"{gui.tr('decompressing_image')} {value}%")

    gui.log_message(f"[INFO] {gui.tr('decompressing_image')}: {os.path.basename(file_path)} ({kind})")
    worker = DecompressWorker(file_path, kind, dest)
    gui._decompress_worker = worker
    gui._decompress_tmp_dir = tmp_dir
    _set_image_prep_busy(gui, True)
    gui.progress_bar.setValue(0)
    worker.progress.connect(safe_slot(progress))
    worker.finished.connect(safe_slot(done))
    worker.failed.connect(safe_slot(failed))
    worker.start()


def _make_unpack_dir(gui, file_path):
    """Temp dir for a decompressed image, where Settings says: next to the
    original (default), the system temp dir, or a chosen directory. Falls back
    to the system temp dir when the preferred place isn't writable."""
    mode = gui.settings.get_str(app_settings.KEY_UNPACK_MODE, "beside") \
        if getattr(gui, 'settings', None) else "beside"
    if mode == "temp":
        parent = None
    elif mode == "custom":
        parent = gui.settings.get_str(app_settings.KEY_UNPACK_DIR, "") or None
    else:
        parent = os.path.dirname(os.path.abspath(file_path))
    if parent:
        try:
            return tempfile.mkdtemp(prefix=".rkdevtool_unpack_", dir=parent)
        except OSError:
            pass
    return tempfile.mkdtemp(prefix="rkdevtool_unpack_")


def _set_image_prep_busy(gui, busy):
    """Disable flashing actions while an image is being decompressed."""
    gui._image_prep_busy = bool(busy)
    if hasattr(gui, '_update_cancel_button'):
        gui._update_cancel_button()
    try:
        gui._update_action_states()
    except Exception as e:
        print(f"Warning: could not update action states: {e}")


def _show_burn_confirm(gui, file_name, file_size, size_str, md5sum, address,
                       current_storage_name, storage_info, checks=(), verify=None):
    """Show the modal burn confirmation dialog; True when the user accepts.

    With a failed pre-flight check there is nothing to accept: the dialog
    explains what failed and only closes. verify, when not None, offers a
    "read back and compare" checkbox starting in that state; the choice is
    kept in gui._verify_after_write and remembered.
    """
    gui._verify_after_write = False
    blocked = any(status == FAIL for status, _ in checks)
    msg = QMessageBox()
    style_messagebox(msg)
    msg.setWindowTitle(gui.tr("confirm_burn_title"))
    msg.setIcon(QMessageBox.Icon.Critical if blocked else QMessageBox.Icon.Question)
    check_lines = "\n".join(f"{_CHECK_MARKS[status]} {text}" for status, text in checks)

    detail_text = f"""
{gui.tr("burn_confirmation_message")}

{gui.tr("file_name")}: {file_name}
{gui.tr("file_size")}: {size_str} ({file_size:,} bytes)
{gui.tr("target_address")}: {address}
MD5: {md5sum}

{gui.tr("storage_type")}: {current_storage_name} ({storage_info.get('type', 'Unknown')})

{gui.tr("pf_title")}
{check_lines}

{gui.tr("pf_blocked") if blocked else gui.tr("confirm_proceed")}
        """

    msg.setText(detail_text)
    if blocked:
        msg.setStandardButtons(QMessageBox.StandardButton.Close)
    else:
        msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    msg.setMinimumWidth(550)
    verify_box = None
    if verify is not None and not blocked:
        verify_box = QCheckBox(gui.tr("verify_after_write"))
        verify_box.setChecked(verify)
        msg.setCheckBox(verify_box)
    # Clear focus to prevent button highlighting
    msg.setFocus()

    answer = msg.exec()  # shown either way: a blocked write must say why
    if verify_box is not None:
        gui._verify_after_write = verify_box.isChecked()
        if hasattr(gui, 'settings'):
            gui.settings.set(app_settings.KEY_VERIFY_AFTER_WRITE,
                             "1" if verify_box.isChecked() else "0")
    return not blocked and answer == QMessageBox.StandardButton.Yes


def confirm_burn_operation(gui, file_path, address):
    """Legacy synchronous confirmation (computes the file MD5 inline).

    Kept for compatibility with any external callers; GUI code should use
    _burn_with_confirm() instead so big images don't freeze the interface.
    """
    try:
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        size_str = format_file_size(file_size)
    except OSError as e:
        gui.log_message(f"[ERROR] {e}")
        return False

    current_storage_code = gui.change_storage_combo.currentData()
    current_storage_name = gui.change_storage_combo.currentText()
    storage_info = get_storage_info(gui, current_storage_code) if current_storage_code else {}

    try:
        md5sum = calculate_file_md5(file_path)
    except Exception:
        md5sum = gui.tr("md5_unavailable")

    return _show_burn_confirm(gui, file_name, file_size, size_str, md5sum,
                              address, current_storage_name, storage_info)


# Storage types rkdeveloptool's `cs` accepts (1.32: EMMC, SD, SPINOR).
STORAGE_TYPES = {
    '1': {'name': 'EMMC', 'code': '1', 'type': 'eMMC Flash', 'enabled': True},
    '2': {'name': 'SD Card', 'code': '2', 'type': 'SD Card', 'enabled': True},
    '9': {'name': 'SPI NOR', 'code': '9', 'type': 'SPI NOR Flash', 'enabled': True},
}


def detect_supported_storage_types(gui):
    """Offer the storage types rkdeveloptool can switch to.

    This used to "detect" them by running `cs 1`, `cs 2` and `cs 9` in turn
    whenever a loader came up. `cs` isn't a query: it switches the loader's
    target, so the device was left on whichever ran last (an empty SD slot,
    SPI NOR), and from then on every read and write was refused (err -8)
    until the board went back through Maskrom. Found on an RK3576. The
    storage is now only switched when the user asks, with Change Storage.
    """
    if getattr(gui, '_supported_storages', None):
        return
    gui._supported_storages = {code: dict(info) for code, info in STORAGE_TYPES.items()}
    try:
        update_storage_combo(gui)
    except (AttributeError, RuntimeError) as e:
        print(f"Warning: Failed to update storage combo: {e}")


def update_storage_combo(gui):
    """
    Update storage combo box with detected/available storage types.
    """
    try:
        if not hasattr(gui, 'change_storage_combo'):
            return
        
        # Get supported storages
        supported = getattr(gui, '_supported_storages', {
            '1': {'name': 'EMMC', 'code': '1', 'type': 'eMMC Flash', 'enabled': True},
            '9': {'name': 'SPI NOR', 'code': '9', 'type': 'SPI NOR Flash', 'enabled': True},
        })
        
        # Store previous selection
        prev_text = gui.change_storage_combo.currentText()
        prev_data = gui.change_storage_combo.currentData()
        
        # Clear and repopulate combo box
        gui.change_storage_combo.clear()
        
        # Sort by code number for consistent ordering
        sorted_items = sorted(supported.items(), key=lambda x: int(x[0]))
        
        for code, storage_info in sorted_items:
            if storage_info.get('enabled', True):
                gui.change_storage_combo.addItem(
                    storage_info['name'],
                    storage_info['code']  # Use the code as data
                )
        
        # Try to restore previous selection
        if prev_data:
            idx = gui.change_storage_combo.findData(prev_data)
            if idx >= 0:
                gui.change_storage_combo.setCurrentIndex(idx)
        
    except Exception as e:
        gui.log_message(f"[WARNING] Error updating storage combo: {e}")


def get_storage_info(gui, storage_code):
    """
    Get detailed information about a specific storage type.
    Returns storage capacity, block size, partition count, etc.
    """
    # For now, return placeholder info - can be enhanced with real device queries
    storage_map = {
        '1': {'name': 'EMMC', 'type': 'eMMC Flash'},
        '2': {'name': 'SD Card', 'type': 'SD Card'},
        '9': {'name': 'SPI NOR', 'type': 'SPI NOR Flash'},
        '3': {'name': 'UFS', 'type': 'Universal Flash Storage'},
        '4': {'name': 'NAND', 'type': 'NAND Flash'},
        '10': {'name': 'NVMe SSD', 'type': 'NVMe Solid State Drive'}
    }
    
    return storage_map.get(storage_code, {'name': 'Unknown', 'type': 'Unknown'})


def read_flash_id(gui):
    """Read Flash ID and display in dialog"""
    from .utils import parse_flash_id
    from .workers import CommandWorker
    
    def on_flash_id_finished(success, output):
        if not success:
            gui.log_message("[ERROR] Failed to read Flash ID")
            return
        
        flash_id_info = parse_flash_id(output)
        if flash_id_info:
            gui._flash_id_info = flash_id_info
            
            # Build info text
            info_text = "Flash ID Information:\n\n"
            if 'manufacturer' in flash_id_info:
                info_text += f"  Manufacturer: {flash_id_info['manufacturer']}\n"
            if 'manufacturer_id' in flash_id_info:
                info_text += f"  Manufacturer ID: {flash_id_info['manufacturer_id']}\n"
            if 'device_id_hex' in flash_id_info:
                info_text += f"  Device ID: {flash_id_info['device_id_hex']}\n"
            if 'capacity' in flash_id_info:
                info_text += f"  Capacity: {flash_id_info['capacity']}\n"
            
            gui.log_message(info_text)
            
            # Show in message box only (don't overwrite device_info_text)
            msg = QMessageBox()
            style_messagebox(msg)
            msg.setWindowTitle(gui.tr("flash_id_info"))
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(info_text)
            msg.exec()
        else:
            gui.log_message("[WARNING] Could not parse Flash ID information")
    
    gui.run_command([RKTOOL, "rid"], "reading_flash_id", on_flash_id_finished)


def read_capability(gui):
    """Read device capability information and display in dialog"""
    from .utils import parse_capability, format_capability_info
    from .workers import CommandWorker
    
    def on_capability_finished(success, output):
        if not success:
            gui.log_message("[ERROR] Failed to read device capability")
            return
        
        capability_info = parse_capability(output)
        if capability_info:
            gui._device_capability = capability_info
            
            # Format and display
            info_text = format_capability_info(capability_info)
            gui.log_message(info_text)
            
            # Update device info text box if available
            if hasattr(gui, 'device_info_text'):
                gui.device_info_text.clear()
                gui.device_info_text.setText(info_text)
            
            # Show in message box
            msg = QMessageBox()
            style_messagebox(msg)
            msg.setWindowTitle(gui.tr("device_capability"))
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(info_text)
            msg.exec()
        else:
            gui.log_message("[WARNING] Could not parse device capability information")
    
    gui.run_command([RKTOOL, "rcb"], "reading_device_capability", on_capability_finished)


def show_flash_info_detailed(gui):
    """Show detailed flash information in a dialog"""
    from .utils import parse_flash_info
    
    def on_flash_info_finished(success, output):
        if not success:
            gui.log_message("[ERROR] Failed to read Flash information")
            return
        
        # Parse the output
        flash_info = parse_flash_info(output)
        if flash_info:
            # Cache the info
            gui._cached_flash_info = flash_info
            # Display dialog
            _display_flash_info_dialog(gui)
        else:
            gui.log_message("[ERROR] Failed to parse Flash information")
    
    gui.run_command([RKTOOL, "rfi"], "reading_flash_info", on_flash_info_finished)


def _display_flash_info_dialog(gui):
    """Display cached flash information in a dialog"""
    from .utils import format_flash_info_detailed
    
    if hasattr(gui, '_cached_flash_info') and gui._cached_flash_info:
        flash_info = gui._cached_flash_info
        
        # Build detailed info text
        info_text = "Detailed Flash Information:\n\n"
        
        # Basic information
        if 'manufacturer' in flash_info:
            info_text += f"  Manufacturer: {flash_info['manufacturer']}\n"
        if 'capacity' in flash_info:
            info_text += f"  Capacity: {flash_info['capacity']}\n"
        if 'id' in flash_info:
            info_text += f"  Flash ID: {flash_info['id']}\n"
        
        # Additional fields that might be present
        if 'flash_type' in flash_info:
            info_text += f"  Type: {flash_info['flash_type']}\n"
        if 'block_size' in flash_info:
            info_text += f"  Block Size: {flash_info['block_size']}\n"
        if 'page_size' in flash_info:
            info_text += f"  Page Size: {flash_info['page_size']}\n"
        if 'health_status' in flash_info:
            info_text += f"  Health: {flash_info['health_status']}\n"
        if 'wear_level' in flash_info:
            info_text += f"  Wear Level: {flash_info['wear_level']}\n"
        
        gui.log_message(info_text)
        
        # Show in message box only (don't overwrite device_info_text)
        msg = QMessageBox()
        style_messagebox(msg)
        msg.setWindowTitle(gui.tr("flash_info_detailed"))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(info_text)
        msg.exec()


def get_security_info(gui):
    """Get device security information and display in dialog"""
    from .utils import parse_security_info, format_security_info
    
    def on_security_info_finished(success, output):
        if not success:
            gui.log_message("[ERROR] Failed to read security information")
            return
        
        security_info = parse_security_info(output)
        if security_info:
            gui._security_info = security_info
            
            # Format and display
            info_text = format_security_info(security_info)
            gui.log_message(info_text)
            
            # Show in message box
            msg = QMessageBox()
            style_messagebox(msg)
            msg.setWindowTitle(gui.tr("security_info"))
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(info_text)
            msg.exec()
        else:
            gui.log_message("[WARNING] Could not parse security information")
    
    gui.run_command([RKTOOL, "rcb"], "reading_security_info", on_security_info_finished)


def test_device_connection(gui, test_count=10):
    """Test device connection stability
    
    Args:
        gui: The main GUI instance
        test_count: Number of tests to run (default: 10)
    """
    from .utils import format_test_results
    
    # Initialize test state
    test_state = {
        'total': test_count,
        'current': 0,
        'success_count': 0,
        'failed_count': 0,
        'errors': []
    }
    
    def run_single_test():
        test_state['current'] += 1
        
        # Check if all tests complete
        if test_state['current'] > test_state['total']:
            # Display results
            success_rate = (test_state['success_count'] / test_state['total']) * 100
            result_text = format_test_results(test_state)
            
            gui.log_message(f"[OK] Connection test completed!\n{result_text}")
            
            # Show in message box
            msg = QMessageBox()
            style_messagebox(msg)
            msg.setWindowTitle(gui.tr("connection_test_result"))
            msg.setIcon(QMessageBox.Icon.Information if success_rate >= 80 else QMessageBox.Icon.Warning)
            msg.setText(result_text)
            msg.exec()
            return
        
        # Run single test
        def on_test_finished(success, output):
            if success:
                test_state['success_count'] += 1
            else:
                test_state['failed_count'] += 1
                # Extract error message if available
                if output:
                    test_state['errors'].append(f"Test {test_state['current']}: {output[:50]}")
            
            # Update log with progress
            progress = f"[{test_state['current']}/{test_state['total']}] "
            status = "[OK]" if success else "[FAIL]"
            gui.log_message(f"{progress}{status} Connection test {test_state['current']}")
            
            # Continue to next test
            run_single_test()
        
        gui.run_command([RKTOOL, "td"], f"testing_device({test_state['current']}/{test_state['total']})", 
                       on_test_finished)
    
    gui.log_message(f"Starting connection stability test ({test_count} iterations)...")
    run_single_test()


def erase_partition(gui, partition_name):
    """Erase a specific partition
    
    Args:
        gui: The main GUI instance
        partition_name: Name of the partition to erase
    """
    if not partition_name or partition_name.strip() == "":
        gui.show_message("Warning", "Please select a partition to erase")
        return
    
    # Double confirmation dialog
    msg = QMessageBox()
    style_messagebox(msg)
    msg.setWindowTitle(gui.tr("erase_partition_warning_title"))
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setText(f"{gui.tr('erase_partition_warning_message')}\n\n"
                f"Partition: {partition_name}\n\n"
                f"This operation cannot be undone!")
    msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    msg.setMinimumWidth(500)
    
    if msg.exec() != QMessageBox.StandardButton.Yes:
        gui.log_message(f"[ERROR] Partition erase cancelled by user")
        return
    
    def on_finished(success, output):
        if success:
            gui.log_message(f"[OK] Partition '{partition_name}' erased successfully")
            gui.log_message(f"[INFO] Auto-refreshing partition table...")
            # Auto-refresh partition table after successful erase
            read_partition_table(gui)
        else:
            gui.log_message(f"[ERROR] Failed to erase partition: {output if output else 'Unknown error'}")
    
    gui.log_message(f"[INFO] Erasing partition '{partition_name}'...")
    gui.run_command([RKTOOL, "ef", partition_name], f"erasing_partition_{partition_name}", on_finished)


def erase_all_storage(gui):
    """Erase entire storage device - requires multiple confirmations
    
    Implements three-layer confirmation:
    1. Initial warning dialog
    2. Storage name verification input
    3. Final confirmation
    """
    current_storage = gui.change_storage_combo.currentText() if hasattr(gui, 'change_storage_combo') else "Storage"
    
    # Layer 1: Initial warning dialog
    msg1 = QMessageBox()
    style_messagebox(msg1)
    msg1.setWindowTitle(gui.tr("erase_all_warning_title"))
    msg1.setIcon(QMessageBox.Icon.Critical)
    warning_text = gui.tr("erase_flash_warning_message")
    # Replace {storage} placeholder if it exists
    if "{storage}" in warning_text:
        warning_text = warning_text.format(storage=current_storage)
    msg1.setText(warning_text)
    msg1.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    msg1.setMinimumWidth(500)
    
    if msg1.exec() != QMessageBox.StandardButton.Yes:
        gui.log_message("[ERROR] Erase all storage cancelled by user")
        return
    
    # Layer 2: Verify storage name input
    verification_prompt = gui.tr("erase_all_verification_title")
    text, ok = QInputDialog.getText(
        gui, 
        gui.tr("erase_all_verification_title"),
        f"{verification_prompt}:\n\n'{current_storage}'",
        QLineEdit.EchoMode.Normal
    )
    
    if not ok or text.strip() != current_storage:
        gui.log_message("[ERROR] Verification failed - storage name does not match. Operation cancelled.")
        return
    
    # Layer 3: Final confirmation
    msg2 = QMessageBox()
    style_messagebox(msg2)
    msg2.setWindowTitle(gui.tr("erase_all_final_confirmation_title"))
    msg2.setIcon(QMessageBox.Icon.Critical)
    msg2.setText(
        f"{gui.tr('erase_all_about_to_erase')}\n"
        f"{current_storage}\n\n"
        f"{gui.tr('erase_all_confirm_certain')}"
    )
    msg2.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    msg2.setMinimumWidth(500)
    
    if msg2.exec() != QMessageBox.StandardButton.Yes:
        gui.log_message("[ERROR] Erase all storage cancelled at final confirmation")
        return
    
    def on_finished(success, output):
        if success:
            gui.log_message(f"[OK] {current_storage} successfully erased")
            gui.log_message(f"[INFO] Auto-refreshing partition table...")
            # Auto-refresh partition table after successful erase
            read_partition_table(gui)
        else:
            gui.log_message(f"[ERROR] Failed to erase {current_storage}: {output if output else 'Unknown error'}")
    
    gui.log_message(f"[INFO] Erasing all data on {current_storage}... This may take a moment.")
    gui.run_command([RKTOOL, "ef", "all"], "erasing_all_storage", on_finished)


# ============================================================================
# Week 5: Firmware Packing/Unpacking and GPT Management
# ============================================================================

def pack_firmware(gui):
    """
    Pack firmware images into upgrade package
    
    Allows selecting input directory containing multiple .bin files and
    creates a packaged firmware file.
    """
    # Select input directory
    input_dir = app_settings.get_directory(
        gui,
        gui.tr("select_pack_input_dir") if hasattr(gui, 'tr') else "Select input directory"
    )
    if not input_dir:
        return
    
    # Select output file path
    output_path = app_settings.get_save_file(
        gui,
        gui.tr("save_packed_firmware") if hasattr(gui, 'tr') else "Save packed firmware",
        "firmware.img",
        "Image Files (*.img);;All Files (*)"
    )
    if not output_path:
        return
    
    def on_finished(success, output):
        if success:
            gui.log_message(f"[OK] {gui.tr('pack_complete') if hasattr(gui, 'tr') else 'Packing complete'}: {output_path}")
        else:
            error_msg = output if output else "Unknown error"
            gui.log_message(f"[ERROR] {gui.tr('pack_failed') if hasattr(gui, 'tr') else 'Packing failed'}: {error_msg}")
    
    gui.log_message(f"[INFO] {gui.tr('packing_firmware') if hasattr(gui, 'tr') else 'Packing firmware'}...")
    gui.run_command([RKTOOL, "pk", input_dir, output_path], "packing_firmware", on_finished)


def unpack_firmware(gui):
    """
    Unpack upgrade package into individual images
    
    Allows selecting a firmware package file and extracts all contained
    images to a selected output directory.
    """
    # The package chosen in the unpack field (browsed or dropped); ask if none.
    input_file = gui.unpack_input_path.text().strip() if hasattr(gui, 'unpack_input_path') else ""
    if not os.path.isfile(input_file):
        input_file = app_settings.get_open_file(
            gui,
            gui.tr("select_firmware_to_unpack") if hasattr(gui, 'tr') else "Select firmware package",
            "Image Files (*.img *.uimg);;All Files (*)"
        )
    if not input_file or not os.path.exists(input_file):
        return
    
    # Select output directory
    output_dir = app_settings.get_directory(
        gui,
        gui.tr("select_unpack_output_dir") if hasattr(gui, 'tr') else "Select output directory"
    )
    if not output_dir:
        return
    
    def on_finished(success, output):
        if success:
            gui.log_message(f"[OK] {gui.tr('unpack_complete') if hasattr(gui, 'tr') else 'Unpacking complete'}")
            # List extracted files
            try:
                files = os.listdir(output_dir)
                if files:
                    gui.log_message(f"[INFO] {gui.tr('extracted_files') if hasattr(gui, 'tr') else 'Extracted files'}:")
                    for f in sorted(files):
                        file_path = os.path.join(output_dir, f)
                        if os.path.isfile(file_path):
                            size_bytes = os.path.getsize(file_path)
                            size_str = format_file_size(size_bytes)
                            gui.log_message(f"  - {f} ({size_str})")
            except Exception as e:
                gui.log_message(f"[WARNING] Could not list extracted files: {e}")
        else:
            error_msg = output if output else "Unknown error"
            gui.log_message(f"[ERROR] {gui.tr('unpack_failed') if hasattr(gui, 'tr') else 'Unpacking failed'}: {error_msg}")
    
    gui.log_message(f"[INFO] {gui.tr('unpacking_firmware') if hasattr(gui, 'tr') else 'Unpacking firmware'}...")
    gui.run_command([RKTOOL, "uk", input_file, output_dir], "unpacking_firmware", on_finished)


def export_gpt_table(gui):
    """Save the device's partition table as a parameter file.

    rkdeveloptool has no command that exports a GPT (`gpt` only writes one,
    from a parameter file), so read the layout with `ppt` and write it out in
    the parameter format, which Import GPT then accepts as is.
    """
    from .utils import build_parameter_text
    output_path = app_settings.get_save_file(
        gui, gui.tr("save_gpt_table"), "parameter.txt",
        "Parameter (*.txt);;All Files (*)")
    if not output_path:
        return

    def on_finished(success, output):
        partitions = parse_partition_info(output or "") if success else {}
        if not partitions:
            gui.log_message(f"[ERROR] {gui.tr('gpt_export_failed')}")
            return
        try:
            with open(output_path, "w") as f:
                f.write(build_parameter_text(partitions))
        except OSError as e:
            gui.log_message(f"[ERROR] {gui.tr('gpt_export_failed')}: {e}")
            return
        gui.log_message(f"[OK] {gui.tr('gpt_export_complete')}: {output_path}")

    gui.log_message(f"[INFO] {gui.tr('exporting_gpt_table')}...")
    gui.run_command([RKTOOL, "ppt"], "exporting_gpt", on_finished)


def import_gpt_table(gui):
    """
    Import GPT partition table from file to device
    
    Reads a GPT partition table from a binary file and writes it to the
    device. Requires multiple confirmations to prevent data loss.
    """
    # The file chosen in the GPT field (browsed or dropped); ask if none.
    input_file = gui.gpt_path.text().strip() if hasattr(gui, 'gpt_path') else ""
    if not os.path.isfile(input_file):
        input_file = app_settings.get_open_file(
            gui, gui.tr("select_gpt_file"), "Parameter (*.txt);;All Files (*)")
    if not input_file or not os.path.exists(input_file):
        return
    # `rkdeveloptool gpt` builds the GPT from a parameter file's mtdparts
    # line; anything else (a raw .bin) would just fail after the warnings.
    from .utils import parameter_has_mtdparts
    if not parameter_has_mtdparts(input_file):
        gui.show_message("gpt_import_failed", "gpt_not_parameter", "Warning")
        return
    
    # First confirmation dialog
    msg1 = QMessageBox()
    style_messagebox(msg1)
    msg1.setWindowTitle(gui.tr("confirm_import_gpt") if hasattr(gui, 'tr') else "Confirm GPT Import")
    msg1.setIcon(QMessageBox.Icon.Warning)
    msg1.setText(
        gui.tr("import_gpt_warning") if hasattr(gui, 'tr') else
        "WARNING: Importing a new GPT table will modify the device partition structure!\n\n"
        "This operation is potentially dangerous. Make sure you know what you're doing.\n\n"
        "Do you want to continue?"
    )
    msg1.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
    msg1.setMinimumWidth(500)
    
    if msg1.exec() != QMessageBox.StandardButton.Yes:
        gui.log_message("[ERROR] GPT import cancelled by user")
        return
    
    # Show file preview if possible
    try:
        file_size = os.path.getsize(input_file)
        size_str = format_file_size(file_size)
        gui.log_message(f"[INFO] GPT file: {os.path.basename(input_file)} ({size_str})")
    except (OSError, FileNotFoundError) as e:
        print(f"Warning: Could not get file size: {e}")
    
    def on_finished(success, output):
        if success:
            gui.log_message(f"[OK] {gui.tr('gpt_import_complete') if hasattr(gui, 'tr') else 'GPT table imported'}")
            gui.log_message(f"[INFO] {gui.tr('refresh_partition_hint') if hasattr(gui, 'tr') else 'Reading partition table to reflect changes'}...")
            # Auto-refresh partition table after successful import
            read_partition_table(gui)
        else:
            error_msg = output if output else "Unknown error"
            gui.log_message(f"[ERROR] {gui.tr('gpt_import_failed') if hasattr(gui, 'tr') else 'GPT import failed'}: {error_msg}")
    
    gui.log_message(f"[INFO] {gui.tr('importing_gpt_table') if hasattr(gui, 'tr') else 'Importing GPT table'}...")
    gui.run_command([RKTOOL, "gpt", input_file], "importing_gpt", on_finished)


def read_device_params(gui):
    """
    Read device parameters from device
    
    Reads the device parameters (like MAC address, serial number, etc.)
    and displays them in a dialog.
    """
    def on_finished(success, output):
        if success:
            # Parse parameters from output
            gui.log_message(f"[OK] {gui.tr('read_params_complete') if hasattr(gui, 'tr') else 'Device parameters read'}")
            
            # Create simple display of parameters
            msg = QMessageBox()
            style_messagebox(msg)
            msg.setWindowTitle(gui.tr("device_params_title") if hasattr(gui, 'tr') else "Device Parameters")
            msg.setIcon(QMessageBox.Icon.Information)
            
            # Format output for display
            param_text = "Device Parameters:\n\n"
            if output:
                lines = output.split('\n')
                for line in lines:
                    if line.strip() and 'prm' in line.lower():
                        param_text += line + "\n"
            
            if param_text == "Device Parameters:\n\n":
                param_text = "No parameters found or device not responding"
            
            msg.setText(param_text)
            msg.setMinimumWidth(400)
            msg.exec()
        else:
            gui.log_message(f"[ERROR] {gui.tr('read_params_failed') if hasattr(gui, 'tr') else 'Failed to read device parameters'}")
    
    gui.log_message(f"[INFO] {gui.tr('reading_device_params') if hasattr(gui, 'tr') else 'Reading device parameters'}...")
    gui.run_command([RKTOOL, "prm"], "reading_device_params", on_finished)


def download_boot(gui):
    """
    Download (write) boot file to device
    
    Allows user to select a boot file and download it to the device.
    """
    boot_file = app_settings.get_open_file(
        gui,
        gui.tr("select_boot_file") if hasattr(gui, 'tr') else "Select Boot File",
        "Boot Files (*.bin);;All Files (*)"
    )
    
    if not boot_file or not os.path.exists(boot_file):
        return
    
    # Show file info
    try:
        file_size = os.path.getsize(boot_file)
        size_str = format_file_size(file_size)
        gui.log_message(f"[INFO] Boot file: {os.path.basename(boot_file)} ({size_str})")
    except OSError as e:
        print(f"Warning: Failed to stat boot file: {e}")
    
    def on_finished(success, output):
        if success:
            gui.log_message(f"[OK] {gui.tr('boot_download_complete') if hasattr(gui, 'tr') else 'Boot file downloaded successfully'}")
        else:
            error_msg = output if output else "Unknown error"
            gui.log_message(f"[ERROR] {gui.tr('boot_download_failed') if hasattr(gui, 'tr') else 'Boot download failed'}: {error_msg}")
    
    gui.log_message(f"[INFO] {gui.tr('downloading_boot') if hasattr(gui, 'tr') else 'Downloading boot file'}...")
    gui.run_command([RKTOOL, "db", boot_file], "downloading_boot", on_finished)


def upload_boot(gui):
    """
    Upload (read) boot file from device
    
    Reads the Boot area from device to local filesystem.
    Uses ReadLBA (rl) command to read from 0x8000 (Boot address)
    """
    output_path = app_settings.get_save_file(
        gui,
        gui.tr("save_boot_file") if hasattr(gui, 'tr') else "Save Boot File",
        "boot.bin",
        "Binary Files (*.bin);;All Files (*)"
    )
    
    if not output_path:
        return
    
    def on_finished(success, output):
        if success:
            gui.log_message(f"[OK] {gui.tr('boot_upload_complete') if hasattr(gui, 'tr') else 'Boot file uploaded successfully'}: {output_path}")
        else:
            error_msg = output if output else "Unknown error"
            gui.log_message(f"[ERROR] {gui.tr('boot_upload_failed') if hasattr(gui, 'tr') else 'Boot upload failed'}: {error_msg}")
    
    gui.log_message(f"[INFO] {gui.tr('uploading_boot') if hasattr(gui, 'tr') else 'Uploading boot file'}...")
    # Use ReadLBA command: rl <BeginSec> <SectorLen> <File>
    # Boot address: 0x8000, read 0x4000 sectors (32MB)
    gui.run_command([RKTOOL, "rl", "0x8000", "0x4000", output_path], "uploading_boot", on_finished)


def show_usb_device_info(gui):
    """
    Show detailed USB device information
    
    Displays VID/PID, serial number, bus information, etc.
    """
    import subprocess
    
    def on_finished(success, output):
        if success and output:
            gui.log_message(f"[OK] {gui.tr('reading_usb_info') if hasattr(gui, 'tr') else 'USB information'}")
            
            # Create dialog to show USB info
            msg = QMessageBox()
            style_messagebox(msg)
            msg.setWindowTitle(gui.tr("usb_device_info") if hasattr(gui, 'tr') else "USB Device Information")
            msg.setIcon(QMessageBox.Icon.Information)
            
            # Format USB info
            usb_info = "USB Device Information:\n\n"
            
            # Try to extract device info from output
            lines = output.split('\n')
            for line in lines:
                if line.strip():
                    # Look for important USB info patterns
                    if any(keyword in line.lower() for keyword in ['device', 'bus', 'port', 'vid', 'pid', 'serial']):
                        usb_info += line.strip() + "\n"
            
            # If no specific info found, show raw output
            if usb_info == "USB Device Information:\n\n":
                usb_info += output[:500]  # Show first 500 chars
            
            msg.setText(usb_info)
            msg.setMinimumWidth(450)
            msg.exec()
        else:
            # Try using lsusb if available
            try:
                result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout:
                    msg = QMessageBox()
                    style_messagebox(msg)
                    msg.setWindowTitle("USB Devices (lsusb)")
                    msg.setIcon(QMessageBox.Icon.Information)
                    msg.setText(result.stdout[:1000])
                    msg.setMinimumWidth(450)
                    msg.exec()
                    return
            except (subprocess.SubprocessError, OSError) as e:
                print(f"Warning: lsusb fallback failed: {e}")
            
            gui.log_message(f"[WARNING] {gui.tr('usb_info_not_available') if hasattr(gui, 'tr') else 'USB information not available'}")
    
    gui.log_message(f"[INFO] {gui.tr('reading_usb_info') if hasattr(gui, 'tr') else 'Reading USB information'}...")
    gui.run_command([RKTOOL, "ld"], "reading_usb_info", on_finished)


def export_logs_detailed(gui):
    """
    Export system logs with device information
    
    Creates a ZIP file containing operation log, device info, and other diagnostics.
    """
    import zipfile
    from datetime import datetime
    
    # Select output file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = app_settings.get_save_file(
        gui,
        gui.tr("export_logs") if hasattr(gui, 'tr') else "Export Logs",
        f"rkdevtool_logs_{timestamp}.zip",
        "ZIP Files (*.zip);;All Files (*)"
    )
    
    if not output_path:
        return
    
    try:
        # Create ZIP file
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add operation log
            log_content = gui.log_output.toPlainText()
            zf.writestr('operation_log.txt', log_content)
            
            # Add device information
            device_info = f"""Device Information Report
Generated: {datetime.now().isoformat()}

Device Status: {gui.device_mode if hasattr(gui, 'device_mode') else 'Unknown'}
Chip: {gui.chip_info if hasattr(gui, 'chip_info') else 'Unknown'}

Connected Devices:
"""
            if hasattr(gui, 'connected_devices'):
                for dev in gui.connected_devices:
                    device_info += f"  - {dev}\n"
            
            zf.writestr('device_info.txt', device_info)
            
            # Add system information
            import platform
            system_info = f"""System Information Report
Generated: {datetime.now().isoformat()}

Platform: {platform.system()}
Platform Release: {platform.release()}
Platform Version: {platform.version()}
Architecture: {platform.machine()}
Processor: {platform.processor()}
Python Version: {platform.python_version()}
"""
            zf.writestr('system_info.txt', system_info)
            
            # Try to add any existing log files
            if hasattr(gui, 'log_file') and os.path.exists(gui.log_file):
                try:
                    zf.write(gui.log_file, arcname='full_application_log.txt')
                except OSError as e:
                    print(f"Warning: Failed to include log file in export: {e}")
        
        gui.log_message(f"[OK] {gui.tr('logs_exported') if hasattr(gui, 'tr') else 'Logs exported successfully'}: {output_path}")
    except Exception as e:
        gui.log_message(f"[ERROR] {gui.tr('export_failed') if hasattr(gui, 'tr') else 'Export failed'}: {str(e)}")


# Export all operation functions
__all__ = [
    'enter_maskrom_mode', 'enter_loader_mode', 'reset_device',
    'read_device_info', 'get_detailed_device_info', 'get_flash_capacity_bytes',
    'read_partition_table', 'backup_firmware',
    'onekey_burn', 'load_loader', 'burn_image',
    'on_partition_ppt_finished', 'backup_partition_by_name',
    'write_partition_by_name', 'confirm_burn_operation',
    'detect_supported_storage_types', 'update_storage_combo', 'get_storage_info',
    'read_flash_id', 'read_capability', 'show_flash_info_detailed',
    'get_security_info', 'test_device_connection',
    'erase_partition', 'erase_all_storage',
    'pack_firmware', 'unpack_firmware', 'export_gpt_table', 'import_gpt_table',
    'read_device_params', 'download_boot', 'upload_boot', 'show_usb_device_info',
    'export_logs_detailed'
]