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
from workers import PartitionPPTWorker, CommandWorker


# Dark theme stylesheet for QMessageBox
MESSAGEBOX_DARK_STYLE = """
QMessageBox {
    background-color: #232629;
    color: #e5e9ef;
}
QMessageBox QLabel {
    color: #e5e9ef;
}
QMessageBox QPushButton {
    background-color: #31363b;
    border: 1px solid #4d5257;
    border-radius: 6px;
    padding: 6px 14px;
    color: #e5e9ef;
    min-width: 60px;
}
QMessageBox QPushButton:hover {
    background-color: #3b4045;
    border-color: #5294e2;
}
QMessageBox QPushButton:pressed {
    background-color: #44494e;
}
"""


def style_messagebox(msg_box):
    """Apply dark theme style to QMessageBox"""
    msg_box.setStyleSheet(MESSAGEBOX_DARK_STYLE)


def get_rkdeveloptool_version():
    """Get rkdeveloptool version"""
    try:
        result = subprocess.run([RKTOOL, "--version"], capture_output=True, text=True, timeout=2)
        output = (result.stdout or "") + (result.stderr or "")
        # Parse "rkdeveloptool ver 1.32" format
        m = re.search(r'ver\s+([\d.]+)', output)
        if m:
            return m.group(1)
    except:
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
        style_messagebox(msg)
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
        msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
        msg.setMinimumWidth(550)
        # Clear focus to prevent button highlighting
        msg.setFocus()

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
    
    # If loader path not set or file doesn't exist, ask user to select
    if not loader_path or not os.path.exists(loader_path):
        loader_path, _ = QFileDialog.getOpenFileName(
            gui, gui.tr("select_loader_file"), "", gui.tr("file_dialog_loader")
        )
        if not loader_path:
            return
        gui.loader_path.setText(loader_path)
    
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
    
    gui.run_command([RKTOOL, cmd_type, loader_path], "loading_loader")
    
    # Mark that we're attempting to load loader and wrap the finished signal
    if gui.command_worker:
        def on_loader_finished(success, error_msg):
            if success:
                gui.loader_loaded = True
                gui.log_message("✅ " + gui.tr("loader_loaded_success"))
                # Re-detect storage types now that loader is loaded
                # This allows hardware like SD cards and SSDs to be recognized
                gui.log_message("🔄 Re-detecting storage types...")
                detect_supported_storage_types(gui)
            gui.on_command_finished(success, error_msg)
        
        try:
            gui.command_worker.finished_signal.disconnect()
        except:
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

    if not confirm_burn_operation(gui, image_path, address):
        return

    gui.run_command([RKTOOL, "wl", address, image_path], "burning")


def confirm_burn_operation(gui, file_path, address):
    """Show confirmation dialog before burning with storage information"""
    try:
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        size_str = format_file_size(file_size)
        md5sum = calculate_file_md5(file_path)
        
        # Get current storage information
        current_storage_code = gui.change_storage_combo.currentData()
        current_storage_name = gui.change_storage_combo.currentText()
        storage_info = get_storage_info(gui, current_storage_code) if current_storage_code else {}

        msg = QMessageBox()
        style_messagebox(msg)
        msg.setWindowTitle(gui.tr("confirm_burn_title"))
        msg.setIcon(QMessageBox.Icon.Question)

        detail_text = f"""
{gui.tr("burn_confirmation_message")}

📁 {gui.tr("file_name")}: {file_name}
📊 {gui.tr("file_size")}: {size_str} ({file_size:,} bytes)
📍 {gui.tr("target_address")}: {address}
🔐 MD5: {md5sum}

💾 {gui.tr("storage_type")}: {current_storage_name} ({storage_info.get('type', 'Unknown')})

{gui.tr("confirm_proceed")}
        """

        msg.setText(detail_text)
        msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
        msg.setMinimumWidth(550)
        # Clear focus to prevent button highlighting
        msg.setFocus()

        return msg.exec() == QMessageBox.StandardButton.Yes

    except Exception as e:
        gui.log_message(f"⚠️ Confirmation dialog error: {e}")
        reply = QMessageBox.question(
            gui, gui.tr("confirm_burn_title"), gui.tr("confirm_burn_simple"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes


def detect_supported_storage_types(gui):
    """
    Detect supported storage types by testing each one.
    Only initializes storage types that the device actually supports.
    
    Note: Storage detection requires Loader to be loaded.
    In Maskrom mode without Loader, only fallback types will be available.
    
    Supported storage types depend on rkdeveloptool version and device hardware:
    - rkdeveloptool 1.32: EMMC (1), SD (2), SPINOR (9)
    """
    try:
        if not hasattr(gui, '_supported_storages'):
            # Storage types supported by rkdeveloptool 1.32
            # These are the officially documented storage types
            all_types = {
                '1': {'name': 'EMMC', 'code': '1', 'type': 'eMMC Flash'},
                '2': {'name': 'SD Card', 'code': '2', 'type': 'SD Card'},
                '9': {'name': 'SPI NOR', 'code': '9', 'type': 'SPI NOR Flash'},
                # For newer rkdeveloptool versions (uncomment if your version supports these):
                # '3': {'name': 'UFS', 'code': '3', 'type': 'Universal Flash Storage'},
                # '4': {'name': 'NAND', 'code': '4', 'type': 'NAND Flash'},
                # '10': {'name': 'NVMe SSD', 'code': '10', 'type': 'NVMe Solid State Drive'},
            }
            
            # Start with empty dict - will be populated by detection
            gui._supported_storages = {}
            
            # Check if device is in Maskrom mode without Loader
            # In this mode, storage detection won't work
            is_maskrom_no_loader = (
                hasattr(gui, 'device_mode') and 'Maskrom' in gui.device_mode and
                hasattr(gui, 'loader_loaded') and not gui.loader_loaded
            )
            
            if is_maskrom_no_loader:
                gui.log_message("⚠️ Device in Maskrom mode - load firmware to detect storage types")
                # Use default types that are most likely available
                gui._supported_storages = {
                    '1': {'name': 'EMMC', 'code': '1', 'type': 'eMMC Flash', 'enabled': True},
                    '9': {'name': 'SPI NOR', 'code': '9', 'type': 'SPI NOR Flash', 'enabled': True},
                }
            else:
                # Test which storage types are actually available
                # by attempting to switch to each one
                available = []
                for code, info in all_types.items():
                    try:
                        result = subprocess.run(
                            [RKTOOL, "cs", code],
                            capture_output=True,
                            text=True,
                            timeout=3
                        )
                        output = (result.stdout or "") + (result.stderr or "")
                        
                        # Check for explicit success or failure
                        has_not_available = "is not available" in output
                        has_ok = "Change Storage OK" in output
                        
                        # Success if has "OK" or no "not available" message
                        is_success = has_ok or (not has_not_available and result.returncode == 0)
                        
                        if is_success and not has_not_available:
                            gui._supported_storages[code] = {
                                'name': info['name'],
                                'code': code,
                                'type': info['type'],
                                'enabled': True
                            }
                            available.append(f"{info['name']} ({code})")
                            gui.log_message(f"✓ Storage {code}: {info['name']}")
                        else:
                            # Only log if explicitly not available
                            if has_not_available:
                                gui.log_message(f"✗ Storage {code}: {info['name']} not available")
                    except Exception as e:
                        gui.log_message(f"✗ Storage {code} error: {str(e)[:50]}")
                
                if available:
                    gui.log_message(f"📦 Detected {len(available)} storage type(s): {', '.join(available)}")
                elif gui._supported_storages:
                    # Some were added despite errors
                    gui.log_message(f"📦 Detected storage types: {', '.join([info['name'] for info in gui._supported_storages.values()])}")
                else:
                    # No storage detected - use defaults
                    gui._supported_storages = {
                        '1': {'name': 'EMMC', 'code': '1', 'type': 'eMMC Flash', 'enabled': True},
                        '9': {'name': 'SPI NOR', 'code': '9', 'type': 'SPI NOR Flash', 'enabled': True},
                    }
                    gui.log_message("📦 Using default storage types (EMMC, SPI NOR)")
                    gui.log_message("💡 If your device has other storage, check:")
                    gui.log_message("   - Is eMMC/SD physically installed on the board?")
                    gui.log_message("   - Is rkdeveloptool up to date? (current: 1.32)")
        
        # Update UI combo box with detected types
        update_storage_combo(gui)
    except Exception as e:
        # Fallback to basic types if detection fails
        import sys
        print(f"Warning: Storage detection failed: {e}", file=sys.stderr)
        if not hasattr(gui, '_supported_storages'):
            gui._supported_storages = {
                '1': {'name': 'EMMC', 'code': '1', 'type': 'eMMC Flash', 'enabled': True},
                '9': {'name': 'SPI NOR', 'code': '9', 'type': 'SPI NOR Flash', 'enabled': True},
            }
        try:
            update_storage_combo(gui)
        except:
            pass


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
        gui.log_message(f"⚠️ Error updating storage combo: {e}")


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
    from utils import parse_flash_id
    from workers import CommandWorker
    
    def on_flash_id_finished(success, output):
        if not success:
            gui.log_message("❌ Failed to read Flash ID")
            return
        
        flash_id_info = parse_flash_id(output)
        if flash_id_info:
            gui._flash_id_info = flash_id_info
            
            # Build info text
            info_text = "📦 Flash ID Information:\n\n"
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
            gui.log_message("⚠️ Could not parse Flash ID information")
    
    gui.run_command([RKTOOL, "rid"], "reading_flash_id", on_flash_id_finished)


def read_capability(gui):
    """Read device capability information and display in dialog"""
    from utils import parse_capability, format_capability_info
    from workers import CommandWorker
    
    def on_capability_finished(success, output):
        if not success:
            gui.log_message("❌ Failed to read device capability")
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
            gui.log_message("⚠️ Could not parse device capability information")
    
    gui.run_command([RKTOOL, "rcb"], "reading_device_capability", on_capability_finished)


def show_flash_info_detailed(gui):
    """Show detailed flash information in a dialog"""
    from utils import parse_flash_info
    
    def on_flash_info_finished(success, output):
        if not success:
            gui.log_message("❌ Failed to read Flash information")
            return
        
        # Parse the output
        flash_info = parse_flash_info(output)
        if flash_info:
            # Cache the info
            gui._cached_flash_info = flash_info
            # Display dialog
            _display_flash_info_dialog(gui)
        else:
            gui.log_message("❌ Failed to parse Flash information")
    
    gui.run_command([RKTOOL, "rfi"], "reading_flash_info", on_flash_info_finished)


def _display_flash_info_dialog(gui):
    """Display cached flash information in a dialog"""
    from utils import format_flash_info_detailed
    
    if hasattr(gui, '_cached_flash_info') and gui._cached_flash_info:
        flash_info = gui._cached_flash_info
        
        # Build detailed info text
        info_text = "📦 Detailed Flash Information:\n\n"
        
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


# Export all operation functions
__all__ = [
    'enter_maskrom_mode', 'enter_loader_mode', 'reset_device',
    'read_device_info', 'get_detailed_device_info', 'get_flash_capacity_bytes',
    'read_partition_table', 'backup_firmware',
    'onekey_burn', 'load_loader', 'burn_image',
    'on_partition_ppt_finished', 'backup_partition_by_name',
    'write_partition_by_name', 'confirm_burn_operation',
    'detect_supported_storage_types', 'update_storage_combo', 'get_storage_info',
    'read_flash_id', 'read_capability', 'show_flash_info_detailed'
]