"""
Device operations for RKDevelopTool GUI
Contains all device interaction methods with improved flash capacity detection
"""
import os
import re
import subprocess
import tempfile
import math
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QApplication

from utils import (
    RKTOOL, parse_partition_info, parse_flash_info,
    calculate_file_md5, format_file_size, safe_slot
)
from workers import PartitionPPTWorker


def read_device_info(gui):
    """Read device capability information and cache flash info"""
    def on_finished(output, return_code):
        if return_code == 0 and output:
            # Parse and cache flash info
            flash_info = parse_flash_info(output)
            if flash_info:
                gui._cached_flash_info = flash_info
                capacity_str = flash_info.get('capacity', '')
                if capacity_str:
                    gui.log_message(f"💾 {gui.tr('detected_flash_size')}: {capacity_str}")

    gui.run_command([RKTOOL, "rfi"], "reading_device_info", callback=on_finished)


def get_detailed_device_info(gui):
    """Get detailed device information and cache flash info"""
    def on_finished(output, return_code):
        if return_code == 0 and output:
            flash_info = parse_flash_info(output)
            if flash_info:
                gui._cached_flash_info = flash_info

    gui.run_command([RKTOOL, "rcb"], "reading_device_info", callback=on_finished)


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
        result = subprocess.run([RKTOOL, "rfi"], capture_output=True, text=True, timeout=6)
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
    save_path, _ = QFileDialog.getSaveFileName(
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

        gui.log_message(f"🔧 {gui.tr('detected_flash_size')}: {size_display} ({source})")
        gui.log_message(f"📊 {gui.tr('backup_sectors')}: {length_arg} ({sectors:,} sectors)")

        # Confirm with user
        msg = QMessageBox()
        msg.setWindowTitle(gui.tr("confirm_backup_title"))
        msg.setIcon(QMessageBox.Icon.Question)

        detail_text = f"""
{gui.tr("backup_confirmation_message")}

💾 {gui.tr("flash_capacity")}: {size_display}
📊 {gui.tr("total_sectors")}: {sectors:,} ({length_arg})
📁 {gui.tr("save_to")}: {os.path.basename(save_path)}

{gui.tr("backup_time_warning")}
        """

        msg.setText(detail_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            gui.run_command([RKTOOL, "rl", "0x0", length_arg, save_path], "backing_up")
        return

    # Fallback: ask user for length
    gui.log_message(f"⚠️ {gui.tr('auto_detect_failed')}: {source}")

    text, ok = QInputDialog.getText(
        gui,
        gui.tr('enter_backup_length_title'),
        gui.tr('enter_backup_length_prompt') + f"\n\n💡 {gui.tr('format_examples')}"
    )

    if not ok or not text:
        gui.show_message('Information', 'backup_cancelled')
        return

    length_arg = text.strip()

    # Convert MB/GB to sectors
    m = re.match(r'^([0-9.]+)\s*(MB|GB)$', length_arg, re.I)
    if m:
        val = float(m.group(1))
        unit = m.group(2).upper()
        bytes_size = int(val * 1024 ** (3 if unit == 'GB' else 2))
        sectors = (bytes_size + 511) // 512
        length_arg = hex(sectors)
        gui.log_message(f"📊 {gui.tr('calculated_sectors')}: {length_arg} ({sectors:,} sectors)")

    gui.run_command([RKTOOL, "rl", "0x0", length_arg, save_path], "backing_up")


def enter_maskrom_mode(gui):
    """Enter Maskrom mode"""
    loader = gui.loader_path.text() if hasattr(gui, 'loader_path') else ''
    if loader and os.path.exists(loader):
        gui.run_command([RKTOOL, "db", loader], "downloading_boot")
    else:
        gui.show_message("Warning", "select_loader_file", "Warning")


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
            result = subprocess.run([RKTOOL, "ppt"], capture_output=True, text=True, timeout=5)
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
            gui.log_message(out or gui.tr('reading_partitions'))
            gui.statusBar().showMessage(gui.tr('reading_partitions'))
    except Exception as e:
        gui.log_message(f"⚠️ parse ppt failed: {e}")
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
    except:
        pass


def populate_partition_combo(gui):
    """Populate partition combo box"""
    gui.partition_combo.clear()
    if gui.partitions:
        for name, info in gui.partitions.items():
            addr = info.get('address', '')
            display = f"{name} ({addr})"
            gui.partition_combo.addItem(display, name)


def populate_address_combo(gui):
    """Populate address combo box"""
    try:
        gui.address_combo.clear()
        gui.address_combo.addItem(gui.tr("address_full_firmware"))
        gui.address_combo.addItem(gui.tr("custom_address"))

        if gui.partitions:
            for name, info in gui.partitions.items():
                addr = info.get('address', '')
                gui.address_combo.addItem(f"{name} ({addr})")
    except:
        pass


def backup_partition_by_name(gui, name):
    """Backup partition by name"""
    save_path, _ = QFileDialog.getSaveFileName(gui, gui.tr('save_file_dialog'), f"{name}.bin")
    if not save_path:
        return

    try:
        if gui.manual_address_enable.isChecked():
            addr = gui.manual_address.text().strip()
            if not addr:
                gui.show_message("Warning", "enter_manual_address", "Warning")
                return
            gui.run_command([RKTOOL, "rl", addr, "0x1000", save_path], "backing_up")
            return
    except:
        pass

    if name in gui.partitions:
        addr = gui.partitions[name].get('address')
        if addr:
            gui.run_command([RKTOOL, "rl", addr, "0x1000", save_path], "backing_up")
            return

    gui.show_message("Warning", "select_partition", "Warning")


def write_partition_by_name(gui, name):
    """Write partition by name"""
    file_path, _ = QFileDialog.getOpenFileName(gui, gui.tr('browse_btn'), "", gui.tr('file_dialog_image'))
    if not file_path or not os.path.exists(file_path):
        return

    try:
        if gui.manual_address_enable.isChecked():
            addr = gui.manual_address.text().strip()
            if not addr:
                gui.show_message("Warning", "enter_manual_address", "Warning")
                return
            gui.run_command([RKTOOL, "wl", addr, file_path], "burning")
            return
    except:
        pass

    if name:
        gui.run_command([RKTOOL, "wlx", name, file_path], "burning")
        return

    gui.show_message("Warning", "select_partition", "Warning")


def onekey_burn(gui):
    """One-click burn firmware"""
    firmware_path = gui.firmware_path.text()
    if not firmware_path or not os.path.exists(firmware_path):
        gui.show_message("Warning", "select_firmware_file", "Warning")
        return
    gui.run_command([RKTOOL, "wl", "0x0", firmware_path], "burning")


def load_loader(gui):
    """Load loader file"""
    loader_path = gui.loader_path.text()
    if not loader_path or not os.path.exists(loader_path):
        gui.show_message("Warning", "select_loader_file", "Warning")
        return
    gui.run_command([RKTOOL, "ul", loader_path], "loading_loader")


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

    if not confirm_burn_operation(gui, image_path, address):
        return

    gui.run_command([RKTOOL, "wl", address, image_path], "burning")


def confirm_burn_operation(gui, file_path, address):
    """Show confirmation dialog before burning"""
    try:
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        size_str = format_file_size(file_size)
        md5sum = calculate_file_md5(file_path)

        msg = QMessageBox()
        msg.setWindowTitle(gui.tr("confirm_burn_title"))
        msg.setIcon(QMessageBox.Icon.Question)

        detail_text = f"""
{gui.tr("burn_confirmation_message")}

📁 {gui.tr("file_name")}: {file_name}
📊 {gui.tr("file_size")}: {size_str} ({file_size:,} bytes)
📍 {gui.tr("target_address")}: {address}
🔐 MD5: {md5sum}

{gui.tr("confirm_proceed")}
        """

        msg.setText(detail_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.setMinimumWidth(500)

        return msg.exec() == QMessageBox.StandardButton.Yes

    except Exception as e:
        gui.log_message(f"⚠️ Confirmation dialog error: {e}")
        reply = QMessageBox.question(
            gui, gui.tr("confirm_burn_title"), gui.tr("confirm_burn_simple"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes


# Export all operation functions
__all__ = [
    'enter_maskrom_mode', 'enter_loader_mode', 'reset_device',
    'read_device_info', 'get_detailed_device_info', 'get_flash_capacity_bytes',
    'read_partition_table', 'backup_firmware',
    'onekey_burn', 'load_loader', 'burn_image',
    'on_partition_ppt_finished', 'backup_partition_by_name',
    'write_partition_by_name', 'confirm_burn_operation'
]