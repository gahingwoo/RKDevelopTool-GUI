import sys
import subprocess
import re
import os
import hashlib
import tempfile
import math
import functools

from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QListWidget, QTextEdit, QFileDialog, QLabel, QLineEdit,
    QProgressBar, QMessageBox, QComboBox, QGroupBox, QGridLayout, QCheckBox,
    QSplitter, QTableWidget, QTableWidgetItem, QSpinBox, QTextBrowser,
    QScrollArea, QHeaderView, QSizePolicy
    , QInputDialog
)


class AutoLoadCombo(QComboBox):
    """QComboBox subclass which calls a callback when the popup is shown.

    This lets us automatically trigger a partition read whenever the user
    opens the address selection dropdown.
    """
    def __init__(self, parent=None, on_open=None):
        super().__init__(parent)
        self._on_open = on_open

    def showPopup(self):
        try:
            if callable(self._on_open):
                # Trigger partition read (non-blocking; uses PartitionPPTWorker)
                self._on_open()
        except Exception:
            pass
        super().showPopup()


def _safe_slot(fn):
    """Return a safer wrapper for signal slots.

    Strategy:
    - Try calling the target with the provided args/kwargs.
    - If that raises a TypeError (signature mismatch), attempt to call
      the function with a truncated positional-arg list matching the
      target's positional parameter count.
    - If that fails, fall back to calling with no arguments.

    This approach avoids unhandled TypeError exceptions originating
    from signature mismatches when PySide6's post-load instrumentation
    inspects or connects slots in packaged runtimes.
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
            # Last resort: swallow to avoid crashing the patched connect
            return None

    return slot

from i18n import TRANSLATIONS

RKTOOL = "rkdeveloptool"

# PARTITION_PRESETS removed: prefer reading partition table at runtime
# If you need static defaults, reintroduce a minimal mapping here.

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
            # Check for rkdeveloptool in the system's PATH
            subprocess.run([RKTOOL, "--version"], check=True, capture_output=True, text=True)
            return True
        except FileNotFoundError:
            return False
        except subprocess.CalledProcessError:
            # The tool exists, but the command failed. This is acceptable.
            return True

class TranslationManager:
    """Manages language translations for the application."""
    def __init__(self, lang="zh"):
        self.lang = lang
        self.translations = TRANSLATIONS
        
    def tr(self, key):
        """Returns the translated string for a given key."""
        return self.translations.get(self.lang, {}).get(key, key)

    def set_language(self, lang):
        """Sets the active language."""
        if lang in self.translations:
            self.lang = lang

class DeviceWorker(QThread):
    """设备检测工作线程"""
    device_found = Signal(list, str, str)  # devices, mode, chip_info
    device_lost = Signal()

    def __init__(self, manager):
        super().__init__()
        self.running = False
        self.manager = manager

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
        self.running = True
        while self.running:
            try:
                result = subprocess.run([RKTOOL, "ld"], capture_output=True, text=True, timeout=3)
                lines = result.stdout.strip().splitlines()
                devices = [l for l in lines if "Did not find any rockusb device" not in l 
                          and "not found" not in l and l.strip()]
                
                if devices:
                    mode = "unknown_mode"
                    if "MASKROM" in result.stdout.upper():
                        mode = "Maskrom"
                    elif "LOADER" in result.stdout.upper():
                        mode = "Loader"
                    
                    chip_info = self.get_chip_info()
                    self.device_found.emit(devices, mode, chip_info)
                else:
                    self.device_lost.emit()
                    
            except Exception:
                self.device_lost.emit()
            # Sleep between detection attempts
            QThread.msleep(2000)

    def get_chip_info(self):
        try:
            result = subprocess.run([RKTOOL, "rci"], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown_chip"

    def stop(self):
        self.running = False


class PartitionPPTWorker(QThread):
    """Background worker to run `rkdeveloptool ppt` and emit output."""
    finished = Signal(str, int)

    def __init__(self):
        super().__init__()

    def run(self):
        try:
            result = subprocess.run([RKTOOL, "ppt"], capture_output=True, text=True, timeout=10)
            out = result.stdout or ""
            code = result.returncode
            self.finished.emit(out, code)  # Emit output and return code
        except Exception as e:
            # emit empty output with non-zero code
            self.finished.emit(str(e), 1)

class CommandWorker(QThread):
    """命令执行工作线程"""
    progress = Signal(int)
    log = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, cmd, description_key, manager):
        super().__init__()
        self.cmd = cmd
        self.description_key = description_key
        self.manager = manager

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
        success = False
        error_msg = ""
        
        try:
            description = self.tr(self.description_key)
            self.log.emit(f"🚀 {self.tr('start_executing')}{description}")
            self.log.emit(f"📝 {self.tr('command')}{' '.join(self.cmd)}")
            
            process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            # expose process for external termination requests
            try:
                self._process = process
            except Exception:
                self._process = None
            
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                line = line.strip()
                if line:
                    self.log.emit(line)
                    if "%" in line:
                        match = re.search(r'(\d+)%', line)
                        if match:
                            progress = min(int(match.group(1)), 99)
                            self.progress.emit(progress)
                            
            process.wait()
            if process.returncode == 0:
                success = True
                self.log.emit(f"✅ {description} {self.tr('success')}")
            else:
                error_msg = f"{self.tr('failure')}{process.returncode}"
                self.log.emit(f"❌ {description} {self.tr('failure')}{process.returncode}")
                
        except Exception as e:
            error_msg = str(e)
            self.log.emit(f"❌ {description} {self.tr('abnormal_execution')}{error_msg}")
            
        self.progress.emit(100 if success else 0)
        self.finished_signal.emit(success, error_msg)

    def terminate_process(self):
        """Attempt to terminate the running subprocess if any."""
        try:
            proc = getattr(self, '_process', None)
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        except Exception:
            pass

class RKDevToolGUI(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.tr = self.manager.tr
        
        # partitions: map partition name -> {'address': '0x...', 'size': '0x...'}
        self.partitions = {}
        # Ensure main window is large enough to show partition table content
        try:
            self.setMinimumSize(1200, 720)
        except Exception:
            pass
        self.set_application_font()
        
        self.device_worker = None
        self.command_worker = None
        self.connected_devices = []
        self.current_device = None
        self.device_mode = "not_connected_status"
        self.chip_info = "unknown_chip"
        
        self.setup_dark_styles()
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        # Track whether a partition refresh is in progress to avoid re-entrancy
        self._partition_refresh_lock = False

        left_scroll_area = QScrollArea()
        left_scroll_area.setWidgetResizable(True)
        self.left_panel = self.create_left_panel()
        left_scroll_area.setWidget(self.left_panel)
        self.splitter.addWidget(left_scroll_area)
        
        right_scroll_area = QScrollArea()
        right_scroll_area.setWidgetResizable(True)
        self.right_panel = self.create_right_panel()
        right_scroll_area.setWidget(self.right_panel)
        self.splitter.addWidget(right_scroll_area)
        # Save initial sizes so we can restore them after partition refreshes
        try:
            self._splitter_sizes = [350, 1050]
            self.splitter.setSizes(self._splitter_sizes)
        except Exception:
            self._splitter_sizes = None
        # Keep splitter sizes up-to-date when user manually moves the splitter
        try:
            self.splitter.splitterMoved.connect(_safe_slot(self._on_splitter_moved))
        except Exception:
            pass
        main_layout.addWidget(self.splitter)
        
        self.create_status_bar()

        self.update_ui_text()
        
        self.start_device_detection()

    def set_application_font(self):
        try:
            font_id = QFontDatabase.addApplicationFont("NotoSansCJKsc-Regular.otf")
            if font_id != -1:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    app_font = QFont(font_families[0])
                    app_font.setPointSize(11)
                    QApplication.setFont(app_font)
        except Exception:
            pass

    def setup_dark_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2c2c2c; color: #f0f0f0; }
            QGroupBox { font-weight: bold; border: 2px solid #555555; border-radius: 8px; margin-top: 1ex; padding-top: 10px; background-color: #3c3c3c; color: #f0f0f0; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 8px 0 8px; color: #f0f0f0; }
            QPushButton { background-color: #444444; border: 2px solid #555555; border-radius: 6px; padding: 8px 16px; font-size: 11px; min-height: 20px; color: #f0f0f0; }
            QPushButton:hover { background-color: #555555; border-color: #007acc; }
            QPushButton:pressed { background-color: #666666; }
            QPushButton:disabled { background-color: #3a3a3a; color: #888888; border-color: #444444; }
            QPushButton.primary { background-color: #007acc; color: white; border-color: #0056b3; }
            QPushButton.primary:hover { background-color: #0056b3; }
            QPushButton.success { background-color: #28a745; color: white; border-color: #1e7e34; }
            QPushButton.success:hover { background-color: #218838; }
            QPushButton.warning { background-color: #ffc107; color: #212529; border-color: #e0a800; }
            QPushButton.warning:hover { background-color: #e0a800; }
            QPushButton.danger { background-color: #dc3545; color: white; border-color: #c82333; }
            QPushButton.danger:hover { background-color: #c82333; }
            QLineEdit, QComboBox, QSpinBox { border: 2px solid #555555; border-radius: 4px; padding: 6px; background-color: #444444; color: #f0f0f0; }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #007acc; }
            QTextEdit, QTextBrowser { border: 2px solid #555555; border-radius: 6px; background-color: #3a3a3a; color: #f0f0f0; font-family: 'Courier New', monospace; font-size: 10px; }
            QListWidget, QTableWidget { border: 2px solid #555555; border-radius: 6px; background-color: #3a3a3a; color: #f0f0f0; alternate-background-color: #424242; }
            QListWidget::item, QTableWidget::item { padding: 4px; }
            QListWidget::item:selected, QTableWidget::item:selected { background-color: #007acc; color: white; }
            QHeaderView::section { background-color: #444444; color: #f0f0f0; padding: 4px; border: 1px solid #555555; font-weight: bold; }
            QProgressBar { border: 2px solid #555555; border-radius: 6px; text-align: center; background-color: #444444; color: #f0f0f0; }
            QProgressBar::chunk { background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #28a745, stop: 1 #1e7e34); border-radius: 4px; }
            QTabWidget::pane { border: 2px solid #555555; border-radius: 6px; background-color: #3c3c3c; }
            QTabBar::tab { background-color: #424242; border: 2px solid #555555; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 8px 16px; margin-right: 2px; color: #f0f0f0; }
            QTabBar::tab:selected { background-color: #3c3c3c; border-color: #007acc; color: #f0f0f0; }
            QTabBar::tab:hover { background-color: #555555; }
            QLabel { color: #f0f0f0; }
        """)

    def update_ui_text(self):
        # Broken into smaller helpers to keep translations organized and readable
        self._update_window_and_device_texts()
        self._update_download_tab_texts()
        self._update_partition_tab_texts()
        self._update_parameter_tab_texts()
        self._update_upgrade_tab_texts()
        self._update_advanced_tab_texts()
        self._update_misc_texts()
        self._update_statusbar_texts()


    def create_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.device_group = QGroupBox()
        device_layout = QVBoxLayout()
        self.device_status_label = QLabel()
        self.device_status_label.setStyleSheet("QLabel { color: #aaaaaa; padding: 5px; }")
        self.chip_info_label = QLabel()
        self.chip_info_label.setStyleSheet("QLabel { color: #f0f0f0; font-weight: bold; padding: 5px; }")
        self.connected_devices_label = QLabel()
        self.device_list = QListWidget()
        self.device_list.setMaximumHeight(80)
        device_layout.addWidget(self.device_status_label)
        device_layout.addWidget(self.chip_info_label)
        device_layout.addWidget(self.connected_devices_label)
        device_layout.addWidget(self.device_list)
        self.device_group.setLayout(device_layout)
        self.mode_group = QGroupBox()
        mode_layout = QVBoxLayout()
        self.enter_maskrom_btn = QPushButton()
        self.enter_maskrom_btn.setProperty("class", "warning")
        self.enter_maskrom_btn.clicked.connect(_safe_slot(self.enter_maskrom_mode))
        self.enter_loader_btn = QPushButton()  
        self.enter_loader_btn.setProperty("class", "primary")
        self.enter_loader_btn.clicked.connect(_safe_slot(self.enter_loader_mode))
        self.reset_device_btn = QPushButton()
        self.reset_device_btn.clicked.connect(_safe_slot(self.reset_device))
        mode_layout.addWidget(self.enter_maskrom_btn)
        mode_layout.addWidget(self.enter_loader_btn)
        mode_layout.addWidget(self.reset_device_btn)
        self.mode_group.setLayout(mode_layout)
        self.quick_group = QGroupBox()
        quick_layout = QVBoxLayout()
        self.read_info_btn = QPushButton()
        self.read_info_btn.setProperty("class", "primary")
        self.read_info_btn.clicked.connect(_safe_slot(self.read_device_info))
        self.read_partitions_btn = QPushButton()
        self.read_partitions_btn.clicked.connect(_safe_slot(self.read_partition_table))
        self.backup_firmware_btn = QPushButton()
        self.backup_firmware_btn.setProperty("class", "success")
        self.backup_firmware_btn.clicked.connect(_safe_slot(self.backup_firmware))
        # Add quick access to flash info commands here so they're easy to reach
        self.read_flash_id_btn = QPushButton()
        self.read_flash_id_btn.clicked.connect(_safe_slot(self.read_flash_id))
        self.read_flash_info_btn = QPushButton()
        self.read_flash_info_btn.clicked.connect(_safe_slot(self.read_flash_info))
        quick_layout.addWidget(self.read_info_btn)
        quick_layout.addWidget(self.read_partitions_btn)
        quick_layout.addWidget(self.backup_firmware_btn)
        quick_layout.addWidget(self.read_flash_id_btn)
        quick_layout.addWidget(self.read_flash_info_btn)
        self.quick_group.setLayout(quick_layout)
        layout.addWidget(self.device_group)
        layout.addWidget(self.mode_group)
        layout.addWidget(self.quick_group)
        layout.addStretch()
        return panel

    # --- UI text helper methods (split from update_ui_text) ---
    def _update_window_and_device_texts(self):
        self.setWindowTitle(self.tr("app_title"))
        self.device_group.setTitle(self.tr("device_status_group"))
        self.device_status_label.setText(self.tr("detecting_device"))
        self.chip_info_label.setText(f"{self.tr('chip')}: {self.tr(self.chip_info)}")
        self.connected_devices_label.setText(self.tr("connected_devices"))
        self.mode_group.setTitle(self.tr("mode_control_group"))
        self.enter_maskrom_btn.setText(self.tr("enter_maskrom_btn"))
        self.enter_loader_btn.setText(self.tr("enter_loader_btn"))
        self.reset_device_btn.setText(self.tr("reset_device_btn"))
        self.quick_group.setTitle(self.tr("quick_actions_group"))
        self.read_info_btn.setText(self.tr("read_info_btn"))
        self.read_partitions_btn.setText(self.tr("read_partitions_btn"))
        self.backup_firmware_btn.setText(self.tr("backup_firmware_btn"))

    def _update_download_tab_texts(self):
        self.tab_widget.setTabText(0, self.tr("download_tab"))
        self.log_group.setTitle(self.tr("log_progress_group"))
        self.clear_log_btn.setText(self.tr("clear_log_btn"))
        self.save_log_btn.setText(self.tr("save_log_btn"))
        self.progress_label.setText(self.tr("ready"))
        self.onekey_group.setTitle(self.tr("onekey_burn_group"))
        self.firmware_label.setText(self.tr("firmware_file_placeholder"))
        self.firmware_path.setPlaceholderText(self.tr("firmware_file_placeholder"))
        self.firmware_browse_btn.setText(self.tr("browse_btn"))
        self.onekey_burn_btn.setText(self.tr("start_burn_btn"))
        self.loader_group.setTitle(self.tr("loader_config_group"))
        self.loader_label.setText(self.tr("loader_file_placeholder"))
        self.loader_path.setPlaceholderText(self.tr("loader_file_placeholder"))
        self.loader_browse_btn.setText(self.tr("browse_btn"))
        self.auto_load_loader.setText(self.tr("auto_load_loader"))
        self.load_loader_btn.setText(self.tr("load_loader_btn"))
        self.image_group.setTitle(self.tr("custom_image_group"))
        self.image_label.setText(self.tr("image_file_placeholder"))
        self.image_path.setPlaceholderText(self.tr("image_file_placeholder"))
        self.image_browse_btn.setText(self.tr("browse_btn"))
        self.address_label.setText(self.tr("target_address"))
        self.custom_address.setPlaceholderText(self.tr("custom_address_placeholder"))
        self.burn_image_btn.setText(self.tr("burn_image_btn"))
        # address combo: populate with defaults and any parsed partition addresses
        self.populate_address_combo()
        # Flash maintenance quick buttons on the download page
        try:
            self.erase_flash_btn.setText(self.tr("erase_flash_btn"))
            self.test_device_btn.setText(self.tr("test_device_btn"))
        except Exception:
            pass

    def _update_partition_tab_texts(self):
        self.tab_widget.setTabText(1, self.tr("partition_tab"))
        self.partition_list_group.setTitle(self.tr("partition_info_group"))
        self.partition_table.setHorizontalHeaderLabels([self.tr("partition_name"), self.tr("start_address"), self.tr("size"), self.tr("action")])
        self.refresh_partitions_btn.setText(self.tr("refresh_partitions_btn"))
        self.partition_ops_group.setTitle(self.tr("partition_ops_group"))
        self.select_partition_label.setText(self.tr("select_partition"))
        self.partition_file_label.setText(self.tr("file_path"))
        self.partition_file_path.setPlaceholderText(self.tr("file_path"))
        self.partition_file_browse_btn.setText(self.tr("browse_btn"))
        self.burn_partition_btn.setText(self.tr("burn_partition_btn"))
        self.backup_partition_btn.setText(self.tr("backup_partition_btn"))
        # Populate partition combo from parsed partitions if available,
        # otherwise fall back to PARTITION_PRESETS.
        self.populate_partition_combo()

    def populate_partition_combo(self):
        """Fill `self.partition_combo` using `self.partitions` if present.
            If no partitions are parsed, leave the combo empty — partition
            entries should come from a live `ppt` read rather than a static
            preset mapping.
            """
        self.partition_combo.clear()
        if self.partitions:
            for name, info in self.partitions.items():
                addr = info.get('address', '')
                display = f"{name} ({addr})"
                self.partition_combo.addItem(display, name)
        else:
            # Intentionally do not populate from static presets; prefer
            # dynamic partition reads via `read_partition_table()`.
            pass

    def populate_address_combo(self):
        """Populate `self.address_combo` (download tab) with default addresses
        plus any parsed partition addresses from `self.partitions`.
        """
        try:
            # Keep only core entries: full firmware and custom address.
            # Partition entries will be appended after a ppt read (on popup).
            self.address_combo.clear()
            self.address_combo.addItem(self.tr("address_full_firmware"))
            self.address_combo.addItem(self.tr("custom_address"))

            # If we already have parsed partitions, append them as well
            if getattr(self, 'partitions', None):
                for name, info in self.partitions.items():
                    addr = info.get('address', '')
                    self.address_combo.addItem(f"{name} ({addr})")
        except Exception:
            pass

    def parse_partition_info(self, text):
        """Parse output from `rkdeveloptool ppt` and fill `self.partitions`.

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
        self.partitions = {}
        for idx, (name, start_int, addr) in enumerate(parts):
            size = None
            if idx + 1 < len(parts):
                next_start = parts[idx+1][1]
                size_val = next_start - start_int
                try:
                    size = hex(size_val)
                except Exception:
                    size = str(size_val)
            else:
                size = "unknown"
            self.partitions[name] = {'address': addr, 'size': size}

    def populate_partition_table(self):
        """Populate `self.partition_table` from `self.partitions`.
        """
        self.partition_table.setRowCount(0)
        # Ensure splitter sizes are restored even if parsing/partition data
        # is missing or the ppt read failed. This prevents the UI from
        # collapsing on subsequent refresh attempts when the worker fails.
        try:
            self._restore_splitter_sizes()
        except Exception:
            pass

        if not self.partitions:
            return
        items = list(self.partitions.items())
        self.partition_table.setRowCount(len(items))
        for row, (name, info) in enumerate(items):
            addr = info.get('address', '')
            size = info.get('size', '')
            self.partition_table.setItem(row, 0, QTableWidgetItem(name))
            self.partition_table.setItem(row, 1, QTableWidgetItem(addr))
            self.partition_table.setItem(row, 2, QTableWidgetItem(size))
            # Create action buttons per-row: Backup / Write
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            backup_btn = QPushButton(self.tr('action_backup'))
            write_btn = QPushButton(self.tr('action_write'))
            backup_btn.clicked.connect(_safe_slot(lambda checked=False, n=name: self.backup_partition_by_name(n)))
            write_btn.clicked.connect(_safe_slot(lambda checked=False, n=name: self.write_partition_by_name(n)))
            action_layout.addWidget(backup_btn)
            action_layout.addWidget(write_btn)
            self.partition_table.setCellWidget(row, 3, action_widget)
        # Resize columns/rows to fit content and ensure no truncation where possible
        try:
            self.partition_table.resizeColumnsToContents()
            self.partition_table.resizeRowsToContents()
            # Let the last column stretch to fill remaining space
            self.partition_table.horizontalHeader().setStretchLastSection(True)
        except Exception:
            pass

        # After repopulating the partition table, restore splitter sizes
        try:
            # Prefer restoring the user's most-recent sizes saved before refresh.
            if getattr(self, 'splitter', None):
                if getattr(self, '_splitter_sizes_prev', None):
                    self.splitter.setSizes(self._splitter_sizes_prev)
                elif getattr(self, '_splitter_sizes', None):
                    self.splitter.setSizes(self._splitter_sizes)
        except Exception:
            pass

    def _restore_splitter_sizes(self):
        """Restore the splitter sizes from the most recent saved state.

        This is factored out so we can call it from multiple failure/success
        code paths and ensure the UI layout remains stable even when
        partition reads fail or return no data.
        """
        try:
            if getattr(self, 'splitter', None):
                # Prefer the most recently saved sizes. Do NOT clear
                # `_splitter_sizes_prev` here — keep it for subsequent
                # refreshes until a new save occurs. Clearing it caused
                # later refreshes to fall back to the hard-coded initial
                # sizes which produced the observed shrinking behavior.
                if getattr(self, '_splitter_sizes_prev', None):
                    try:
                        self.log_message(f"🔧 Restoring splitter sizes from prev: {self._splitter_sizes_prev}")
                    except Exception:
                        pass
                    self.splitter.setSizes(self._splitter_sizes_prev)
                elif getattr(self, '_splitter_sizes', None):
                    try:
                        self.log_message(f"🔧 Restoring splitter sizes from initial: {self._splitter_sizes}")
                    except Exception:
                        pass
                    self.splitter.setSizes(self._splitter_sizes)
        except Exception:
            pass

    def _on_splitter_moved(self, pos=None, index=None):
        """Handler for splitterMoved signal to capture latest sizes."""
        try:
            if getattr(self, 'splitter', None):
                self._splitter_sizes_prev = self.splitter.sizes()
                try:
                    self.log_message(f"🔧 saved splitter sizes: {self._splitter_sizes_prev}")
                except Exception:
                    pass
        except Exception:
            pass

    def on_partition_ppt_finished(self, out, code):
        """Handler called when PartitionPPTWorker finishes."""
        try:
            if code == 0 and out:
                self.parse_partition_info(out)  # Parse the output
                self.populate_partition_table()  # Update the UI table
                self.populate_partition_combo()  # Refresh the combo box
                self.populate_address_combo()  # Refresh download address combo
                self.log_message(self.tr('partition_read_ok'))  # Log success
                self.statusBar().showMessage(self.tr('partition_read_ok'))  # Update status bar
            else:
                # Show whatever output we got and fallback to log
                self.log_message(out or self.tr('reading_partitions'))  # Log the output
                self.statusBar().showMessage(self.tr('reading_partitions'))  # Update status bar
        except Exception as e:
            self.log_message(f"⚠️ parse ppt failed: {e}")
        finally:
            # Always restore splitter sizes (saved before the ppt read)
            try:
                self._restore_splitter_sizes()
            except Exception:
                pass
            # Release refresh lock
            try:
                self._partition_refresh_lock = False
            except Exception:
                pass

    def backup_partition_by_name(self, name):
        # Prompt for save path
        save_path, _ = QFileDialog.getSaveFileName(self, self.tr('save_file_dialog'), f"{name}.bin")
        if not save_path:
            return
        # Manual override
        try:
            if getattr(self, 'manual_address_enable', None) and self.manual_address_enable.isChecked():
                addr = self.manual_address.text().strip()
                if not addr:
                    self.show_message("Warning", "enter_manual_address", "Warning")
                    return
                self.run_command([RKTOOL, "rl", addr, "0x1000", save_path], "backing_up")
                return
        except Exception:
            pass

        # Use parsed partition mapping
        if name in self.partitions:
            addr = self.partitions[name].get('address')
            if addr:
                self.run_command([RKTOOL, "rl", addr, "0x1000", save_path], "backing_up")
                return

        # Fallback: show warning
        self.show_message("Warning", "select_partition", "Warning")

    def write_partition_by_name(self, name):
        # Prompt for file to write
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr('browse_btn'), "", self.tr('file_dialog_image'))
        if not file_path or not os.path.exists(file_path):
            return
        # Manual override
        try:
            if getattr(self, 'manual_address_enable', None) and self.manual_address_enable.isChecked():
                addr = self.manual_address.text().strip()
                if not addr:
                    self.show_message("Warning", "enter_manual_address", "Warning")
                    return
                self.run_command([RKTOOL, "wl", addr, file_path], "burning")
                return
        except Exception:
            pass

        # Use wlx with partition name if possible
        if name:
            self.run_command([RKTOOL, "wlx", name, file_path], "burning")
            return

        self.show_message("Warning", "select_partition", "Warning")

    def _update_parameter_tab_texts(self):
        self.tab_widget.setTabText(2, self.tr("parameter_tab"))
        self.burn_params_group.setTitle(self.tr("burn_params_group"))
        self.verify_after_burn.setText(self.tr("verify_after_burn"))
        self.erase_before_burn.setText(self.tr("erase_before_burn"))
        self.reset_after_burn.setText(self.tr("reset_after_burn"))
        self.advanced_params_group.setTitle(self.tr("advanced_params_group"))
        self.timeout_label.setText(self.tr("command_timeout"))
        self.timeout_spinbox.setSuffix(f" {self.tr('seconds')}")
        self.retry_count_label.setText(self.tr("retry_count"))
        self.retry_count_spinbox.setSuffix(f" {self.tr('times')}")
        self.device_info_group.setTitle(self.tr("device_info_group"))
        self.get_device_info_btn.setText(self.tr("get_detailed_info_btn"))

    def _update_upgrade_tab_texts(self):
        self.tab_widget.setTabText(3, self.tr("upgrade_tab"))
        # Repurpose the upgrade tab into Pack/Unpack and pack-related tools
        try:
            self.pack_group.setTitle(self.tr("firmware_upgrade_group"))
            self.pack_label.setText(self.tr("pack_label"))
            self.pack_browse_btn.setText(self.tr("browse_btn"))
            self.pack_btn.setText(self.tr("pack_btn"))

            self.unpack_group.setTitle(self.tr("unpack_label"))
            self.unpack_label.setText(self.tr("unpack_label"))
            self.unpack_browse_btn.setText(self.tr("browse_btn"))
            self.unpack_btn.setText(self.tr("unpack_btn"))

            self.pack_ops_group.setTitle(self.tr("pack_ops_group") if hasattr(self, 'tr') else self.tr("pack_ops_group") )
            self.gpt_label.setText(self.tr("gpt_label"))
            self.gpt_browse_btn.setText(self.tr("browse_btn"))
            self.gpt_btn.setText(self.tr("gpt_btn"))
            self.prm_label.setText(self.tr("prm_label"))
            self.prm_text.setPlaceholderText(self.tr("prm_placeholder"))
            self.prm_btn.setText(self.tr("prm_btn"))
            self.tagspl_label.setText(self.tr("tagspl_label"))
            self.tagspl_browse_btn.setText(self.tr("browse_btn"))
            self.tagspl_btn.setText(self.tr("tagspl_btn"))
        except Exception:
            pass

    def _update_advanced_tab_texts(self):
        self.tab_widget.setTabText(4, self.tr("advanced_tab"))
        self.flash_ops_group.setTitle(self.tr("flash_ops_group"))
        # Erase/test moved to download tab; format removed.
        self.rw_ops_group.setTitle(self.tr("rw_ops_group"))
        self.read_address_label.setText(self.tr("start_address"))
        self.read_address.setPlaceholderText(self.tr("start_address_placeholder"))
        self.read_length_label.setText(self.tr("read_length_placeholder"))
        self.read_length.setPlaceholderText(self.tr("read_length_placeholder"))
        self.read_save_path_label.setText(self.tr("save_path_placeholder"))
        self.read_save_path.setPlaceholderText(self.tr("save_path_placeholder"))
        self.read_browse_btn.setText(self.tr("browse_btn"))
        self.read_flash_btn.setText(self.tr("read_flash_btn"))
        self.verify_group.setTitle(self.tr("verify_tools_group"))
        self.verify_file_label.setText(self.tr("verify_file_placeholder"))
        self.verify_file_path.setPlaceholderText(self.tr("verify_file_placeholder"))
        self.verify_browse_btn.setText(self.tr("browse_btn"))
        self.verify_address_label.setText(self.tr("verify_address_placeholder"))
        self.verify_address.setPlaceholderText(self.tr("verify_address_placeholder"))
        self.verify_btn.setText(self.tr("verify_file_btn"))
        self.calculate_md5_btn.setText(self.tr("calculate_md5_btn"))
        self.verify_sector_label.setText(self.tr("verify_sector_label"))
        self.verify_sector_combo.clear()
        self.verify_sector_combo.addItem(self.tr("verify_sector_512"), "512")
        self.verify_sector_combo.addItem(self.tr("verify_sector_4096"), "4096")
        self.verify_sector_combo.addItem(self.tr("verify_sector_custom"), "custom")
        self.verify_sector_custom.setPlaceholderText(self.tr("verify_sector_custom_placeholder"))
        self.debug_group.setTitle(self.tr("debug_tools_group"))
        self.enable_debug_log.setText(self.tr("enable_debug_log"))
        self.export_log_btn.setText(self.tr("export_system_log_btn"))
        self.show_usb_info_btn.setText(self.tr("show_usb_info_btn"))

    def _update_misc_texts(self):
        # Misc ops texts
        self.read_flash_id_btn.setText(self.tr("read_flash_id_btn"))
        self.read_flash_info_btn.setText(self.tr("read_flash_info_btn"))
        self.change_storage_label.setText(self.tr("change_storage_label"))
        self.change_storage_btn.setText(self.tr("change_storage_btn"))


    def _update_statusbar_texts(self):
        self.statusBar().showMessage(f"{self.tr('ready_status')}{self.tr('status_line_delimiter')}{self.tr('not_connected_status')}")
        self.connection_status.setText(f"⚪ {self.tr('not_connected')}")
        self.update_device_status()

    def create_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self.create_download_tab(), "")
        self.tab_widget.addTab(self.create_partition_tab(), "") 
        self.tab_widget.addTab(self.create_parameter_tab(), "")
        self.tab_widget.addTab(self.create_upgrade_tab(), "")
        self.tab_widget.addTab(self.create_advanced_tab(), "")
        layout.addWidget(self.tab_widget)
        self.log_group = QGroupBox()
        log_layout = QVBoxLayout()
        log_controls = QHBoxLayout()
        self.clear_log_btn = QPushButton()
        self.clear_log_btn.clicked.connect(_safe_slot(self.clear_log))
        self.save_log_btn = QPushButton()
        self.save_log_btn.clicked.connect(_safe_slot(self.save_log))
        log_controls.addWidget(self.clear_log_btn)
        log_controls.addWidget(self.save_log_btn)
        log_controls.addStretch()
        self.log_output = QTextBrowser()
        self.log_output.setMaximumHeight(200)
        self.progress_bar = QProgressBar()
        self.progress_label = QLabel()
        log_layout.addLayout(log_controls)
        log_layout.addWidget(self.log_output)
        log_layout.addWidget(self.progress_label)
        log_layout.addWidget(self.progress_bar)
        self.log_group.setLayout(log_layout)
        layout.addWidget(self.log_group)
        return panel

    def create_download_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.onekey_group = QGroupBox()
        onekey_layout = QGridLayout()
        self.firmware_label = QLabel()
        self.firmware_path = QLineEdit()
        self.firmware_browse_btn = QPushButton()
        self.register_browse(self.firmware_browse_btn, self.firmware_path, "file_dialog_firmware")
        self.onekey_burn_btn = QPushButton()
        self.onekey_burn_btn.setProperty("class", "success")
        self.onekey_burn_btn.clicked.connect(_safe_slot(self.onekey_burn))
        onekey_layout.addWidget(self.firmware_label, 0, 0)
        onekey_layout.addWidget(self.firmware_path, 0, 1)
        onekey_layout.addWidget(self.firmware_browse_btn, 0, 2)
        onekey_layout.addWidget(self.onekey_burn_btn, 1, 0, 1, 3)
        self.onekey_group.setLayout(onekey_layout)
        self.loader_group = QGroupBox()
        loader_layout = QGridLayout()
        self.loader_label = QLabel()
        self.loader_path = QLineEdit()
        self.loader_browse_btn = QPushButton()
        self.register_browse(self.loader_browse_btn, self.loader_path, "file_dialog_loader")
        self.auto_load_loader = QCheckBox()
        self.load_loader_btn = QPushButton()
        self.load_loader_btn.setProperty("class", "primary")
        self.load_loader_btn.clicked.connect(_safe_slot(self.load_loader))
        loader_layout.addWidget(self.loader_label, 0, 0)
        loader_layout.addWidget(self.loader_path, 0, 1)
        loader_layout.addWidget(self.loader_browse_btn, 0, 2)
        loader_layout.addWidget(self.auto_load_loader, 1, 0)
        loader_layout.addWidget(self.load_loader_btn, 1, 2)
        self.loader_group.setLayout(loader_layout)
        self.image_group = QGroupBox()
        image_layout = QGridLayout()
        self.image_label = QLabel()
        self.image_path = QLineEdit()
        self.image_browse_btn = QPushButton()
        self.register_browse(self.image_browse_btn, self.image_path, "file_dialog_image")
        self.address_label = QLabel()
        # Use AutoLoadCombo so opening the dropdown triggers partition read
        self.address_combo = AutoLoadCombo(self, on_open=self.read_partition_table)
        self.address_combo.currentTextChanged.connect(_safe_slot(self.on_address_changed))
        self.custom_address = QLineEdit()
        self.custom_address.setEnabled(False)
        self.burn_image_btn = QPushButton()
        self.burn_image_btn.setProperty("class", "success")
        self.burn_image_btn.clicked.connect(_safe_slot(self.burn_image))
        image_layout.addWidget(self.image_label, 0, 0)
        image_layout.addWidget(self.image_path, 0, 1)
        image_layout.addWidget(self.image_browse_btn, 0, 2)
        image_layout.addWidget(self.address_label, 1, 0)
        image_layout.addWidget(self.address_combo, 1, 1)
        image_layout.addWidget(self.custom_address, 1, 2)
        image_layout.addWidget(self.burn_image_btn, 2, 0, 1, 3)
        self.image_group.setLayout(image_layout)
        # Storage switch controls moved into the download tab for convenience
        self.change_storage_label = QLabel()
        self.change_storage_combo = QComboBox()
        # Values: 1=EMMC,2=SD,9=SPINOR
        self.change_storage_combo.addItem("EMMC", "1")
        self.change_storage_combo.addItem("SD", "2")
        self.change_storage_combo.addItem("SPINOR", "9")
        self.change_storage_btn = QPushButton()
        self.change_storage_btn.clicked.connect(_safe_slot(self.change_storage))

        layout.addWidget(self.onekey_group)
        layout.addWidget(self.loader_group)
        layout.addWidget(self.image_group)
        storage_layout = QHBoxLayout()
        storage_layout.addWidget(self.change_storage_label)
        storage_layout.addWidget(self.change_storage_combo)
        storage_layout.addWidget(self.change_storage_btn)
        layout.addLayout(storage_layout)
        # Add quick actions related to flash maintenance on the download tab
        ops_layout = QHBoxLayout()
        self.erase_flash_btn = QPushButton()
        self.erase_flash_btn.setProperty("class", "danger")
        self.erase_flash_btn.clicked.connect(_safe_slot(self.erase_flash))
        self.test_device_btn = QPushButton()
        self.test_device_btn.clicked.connect(_safe_slot(self.test_device))
        ops_layout.addWidget(self.erase_flash_btn)
        ops_layout.addWidget(self.test_device_btn)
        layout.addLayout(ops_layout)
        layout.addStretch()
        return widget

    def create_partition_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.partition_list_group = QGroupBox()
        partition_list_layout = QVBoxLayout()
        self.partition_table = QTableWidget()
        self.partition_table.setColumnCount(4)
        # Allow interactive resizing and make content-sized by default
        header = self.partition_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Improve readability for Chinese text: use application font and larger row height
        try:
            table_font = QApplication.font()
            table_font.setPointSize(max(table_font.pointSize(), 11))
            self.partition_table.setFont(table_font)
        except Exception:
            pass
        self.partition_table.verticalHeader().setDefaultSectionSize(28)
        self.partition_table.setMinimumHeight(320)
        self.partition_table.setMinimumWidth(760)
        # Ensure the partition table and its container expand to fill available space
        try:
            self.partition_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            # Make the group expand as well so the table can use available area
            try:
                self.partition_list_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            except Exception:
                pass
        except Exception:
            pass
        self.refresh_partitions_btn = QPushButton()
        self.refresh_partitions_btn.clicked.connect(_safe_slot(self.refresh_partition_table))
        partition_list_layout.addWidget(self.partition_table)
        partition_list_layout.addWidget(self.refresh_partitions_btn)
        self.partition_list_group.setLayout(partition_list_layout)
        self.partition_ops_group = QGroupBox()
        partition_ops_layout = QGridLayout()
        self.select_partition_label = QLabel()
        self.partition_combo = QComboBox()
        self.partition_file_label = QLabel()
        self.partition_file_path = QLineEdit()
        self.partition_file_browse_btn = QPushButton()
        self.register_browse(self.partition_file_browse_btn, self.partition_file_path, "file_dialog_image")
        self.burn_partition_btn = QPushButton()
        self.burn_partition_btn.setProperty("class", "success")
        self.burn_partition_btn.clicked.connect(_safe_slot(self.burn_partition))
        self.backup_partition_btn = QPushButton()
        self.backup_partition_btn.setProperty("class", "primary")
        self.backup_partition_btn.clicked.connect(_safe_slot(self.backup_partition))
        partition_ops_layout.addWidget(self.select_partition_label, 0, 0)
        partition_ops_layout.addWidget(self.partition_combo, 0, 1)
        partition_ops_layout.addWidget(self.partition_file_label, 1, 0)
        partition_ops_layout.addWidget(self.partition_file_path, 1, 1)
        partition_ops_layout.addWidget(self.partition_file_browse_btn, 1, 2)
        partition_ops_layout.addWidget(self.burn_partition_btn, 2, 0)
        partition_ops_layout.addWidget(self.backup_partition_btn, 2, 1)
        # Manual address override controls
        self.manual_address_enable = QCheckBox()
        self.manual_address_enable.setText(self.tr("manual_address_override") if hasattr(self, 'tr') else "Manual address")
        self.manual_address = QLineEdit()
        self.manual_address.setPlaceholderText("0x2000")
        partition_ops_layout.addWidget(self.manual_address_enable, 3, 0)
        partition_ops_layout.addWidget(self.manual_address, 3, 1)
        self.partition_ops_group.setLayout(partition_ops_layout)
        # Hide the old partition operations panel — consolidate operations
        # into the download tab. Keep widgets instantiated for programmatic
        # compatibility, but do not show them in the UI.
        try:
            self.partition_ops_group.hide()
        except Exception:
            pass
        # Add the partition list group and let it take remaining space
        layout.addWidget(self.partition_list_group, 1)
        layout.addStretch()
        return widget

    def create_parameter_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.burn_params_group = QGroupBox()
        burn_params_layout = QGridLayout()
        self.verify_after_burn = QCheckBox()
        self.verify_after_burn.setChecked(True)
        self.erase_before_burn = QCheckBox()
        self.erase_before_burn.setChecked(False)
        self.reset_after_burn = QCheckBox()
        self.reset_after_burn.setChecked(True)
        burn_params_layout.addWidget(self.verify_after_burn, 0, 0)
        burn_params_layout.addWidget(self.erase_before_burn, 0, 1)
        burn_params_layout.addWidget(self.reset_after_burn, 1, 0)
        self.burn_params_group.setLayout(burn_params_layout)
        self.advanced_params_group = QGroupBox()
        advanced_params_layout = QGridLayout()
        self.timeout_label = QLabel()
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(10, 300)
        self.timeout_spinbox.setValue(30)
        self.retry_count_label = QLabel()
        self.retry_count_spinbox = QSpinBox()
        self.retry_count_spinbox.setRange(0, 10)
        self.retry_count_spinbox.setValue(3)
        advanced_params_layout.addWidget(self.timeout_label, 0, 0)
        advanced_params_layout.addWidget(self.timeout_spinbox, 0, 1)
        advanced_params_layout.addWidget(self.retry_count_label, 1, 0)
        advanced_params_layout.addWidget(self.retry_count_spinbox, 1, 1)
        self.advanced_params_group.setLayout(advanced_params_layout)
        self.device_info_group = QGroupBox()
        device_info_layout = QVBoxLayout()
        self.device_info_text = QTextBrowser()
        self.device_info_text.setMaximumHeight(150)
        self.get_device_info_btn = QPushButton()
        self.get_device_info_btn.clicked.connect(_safe_slot(self.get_detailed_device_info))
        device_info_layout.addWidget(self.device_info_text)
        device_info_layout.addWidget(self.get_device_info_btn)
        self.device_info_group.setLayout(device_info_layout)
        layout.addWidget(self.burn_params_group)
        layout.addWidget(self.advanced_params_group)
        layout.addWidget(self.device_info_group)
        layout.addStretch()
        return widget

    def create_upgrade_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Pack group
        self.pack_group = QGroupBox()
        pack_layout = QGridLayout()
        self.pack_label = QLabel()
        self.pack_output_path = QLineEdit()
        self.pack_browse_btn = QPushButton()
        self.register_browse(self.pack_browse_btn, self.pack_output_path, "file_dialog_all", save=True)
        self.pack_btn = QPushButton()
        self.pack_btn.clicked.connect(_safe_slot(self.pack_bootloader))
        pack_layout.addWidget(self.pack_label, 0, 0)
        pack_layout.addWidget(self.pack_output_path, 0, 1)
        pack_layout.addWidget(self.pack_browse_btn, 0, 2)
        pack_layout.addWidget(self.pack_btn, 0, 3)
        self.pack_group.setLayout(pack_layout)

        # Unpack group
        self.unpack_group = QGroupBox()
        unpack_layout = QGridLayout()
        self.unpack_label = QLabel()
        self.unpack_input_path = QLineEdit()
        self.unpack_browse_btn = QPushButton()
        self.register_browse(self.unpack_browse_btn, self.unpack_input_path, "file_dialog_all")
        self.unpack_btn = QPushButton()
        self.unpack_btn.clicked.connect(_safe_slot(self.unpack_bootloader))
        unpack_layout.addWidget(self.unpack_label, 0, 0)
        unpack_layout.addWidget(self.unpack_input_path, 0, 1)
        unpack_layout.addWidget(self.unpack_browse_btn, 0, 2)
        unpack_layout.addWidget(self.unpack_btn, 0, 3)
        self.unpack_group.setLayout(unpack_layout)

        # GPT / PRM / Tag operations grouped together
        self.pack_ops_group = QGroupBox()
        pack_ops_layout = QGridLayout()
        self.gpt_label = QLabel()
        self.gpt_path = QLineEdit()
        self.gpt_browse_btn = QPushButton()
        self.register_browse(self.gpt_browse_btn, self.gpt_path, "file_dialog_all")
        self.gpt_btn = QPushButton()
        self.gpt_btn.clicked.connect(_safe_slot(self.write_gpt))

        self.prm_label = QLabel()
        self.prm_text = QLineEdit()
        self.prm_btn = QPushButton()
        self.prm_btn.clicked.connect(_safe_slot(self.write_parameter))

        self.tagspl_label = QLabel()
        self.tagspl_tag = QLineEdit()
        self.tagspl_spl_path = QLineEdit()
        self.tagspl_browse_btn = QPushButton()
        self.register_browse(self.tagspl_browse_btn, self.tagspl_spl_path, "file_dialog_all")
        self.tagspl_btn = QPushButton()
        self.tagspl_btn.clicked.connect(_safe_slot(self.tag_spl))

        pack_ops_layout.addWidget(self.gpt_label, 0, 0)
        pack_ops_layout.addWidget(self.gpt_path, 0, 1)
        pack_ops_layout.addWidget(self.gpt_browse_btn, 0, 2)
        pack_ops_layout.addWidget(self.gpt_btn, 0, 3)

        pack_ops_layout.addWidget(self.prm_label, 1, 0)
        pack_ops_layout.addWidget(self.prm_text, 1, 1)
        pack_ops_layout.addWidget(self.prm_btn, 1, 2)

        pack_ops_layout.addWidget(self.tagspl_label, 2, 0)
        pack_ops_layout.addWidget(self.tagspl_tag, 2, 1)
        pack_ops_layout.addWidget(self.tagspl_spl_path, 2, 2)
        pack_ops_layout.addWidget(self.tagspl_browse_btn, 2, 3)
        pack_ops_layout.addWidget(self.tagspl_btn, 2, 4)

        self.pack_ops_group.setLayout(pack_ops_layout)

        layout.addWidget(self.pack_group)
        layout.addWidget(self.unpack_group)
        layout.addWidget(self.pack_ops_group)
        layout.addStretch()
        return widget

    def create_advanced_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.flash_ops_group = QGroupBox()
        flash_ops_layout = QGridLayout()
        # Erase/test buttons were moved to the Download tab; leave the
        # flash ops group present (empty) to avoid changing layout order.
        self.flash_ops_group.setLayout(flash_ops_layout)
        self.rw_ops_group = QGroupBox()
        rw_ops_layout = QGridLayout()
        self.read_address_label = QLabel()
        self.read_address = QLineEdit()
        self.read_length_label = QLabel()
        self.read_length = QLineEdit()
        self.read_save_path_label = QLabel()
        self.read_save_path = QLineEdit()
        self.read_browse_btn = QPushButton()
        self.register_browse(self.read_browse_btn, self.read_save_path, save=True)
        self.read_flash_btn = QPushButton()
        self.read_flash_btn.setProperty("class", "primary")
        self.read_flash_btn.clicked.connect(_safe_slot(self.read_flash))
        rw_ops_layout.addWidget(self.read_address_label, 0, 0)
        rw_ops_layout.addWidget(self.read_address, 0, 1)
        rw_ops_layout.addWidget(self.read_length_label, 0, 2)
        rw_ops_layout.addWidget(self.read_length, 0, 3)
        rw_ops_layout.addWidget(self.read_save_path_label, 1, 0)
        rw_ops_layout.addWidget(self.read_save_path, 1, 1, 1, 2)
        rw_ops_layout.addWidget(self.read_browse_btn, 1, 3)
        rw_ops_layout.addWidget(self.read_flash_btn, 2, 0, 1, 4)
        self.rw_ops_group.setLayout(rw_ops_layout)
        self.verify_group = QGroupBox()
        verify_layout = QGridLayout()
        self.verify_file_label = QLabel()
        self.verify_file_path = QLineEdit()
        self.verify_browse_btn = QPushButton()
        self.register_browse(self.verify_browse_btn, self.verify_file_path, "file_dialog_all")
        self.verify_address_label = QLabel()
        self.verify_address = QLineEdit()
        self.verify_address.setPlaceholderText("校验地址 (如: 0x0)")
        self.verify_btn = QPushButton()
        self.verify_btn.setProperty("class", "success")
        self.verify_btn.clicked.connect(_safe_slot(self.verify_flash))
        self.calculate_md5_btn = QPushButton()
        self.calculate_md5_btn.clicked.connect(_safe_slot(self.calculate_md5))
        # Sector size selection for verification (512/4096/custom)
        self.verify_sector_label = QLabel()
        self.verify_sector_combo = QComboBox()
        self.verify_sector_combo.addItem("512 B", "512")
        self.verify_sector_combo.addItem("4096 B", "4096")
        self.verify_sector_combo.addItem("自定义", "custom")
        self.verify_sector_combo.currentIndexChanged.connect(_safe_slot(self.on_verify_sector_changed))
        self.verify_sector_custom = QLineEdit()
        self.verify_sector_custom.setEnabled(False)
        verify_layout.addWidget(self.verify_file_label, 0, 0)
        verify_layout.addWidget(self.verify_file_path, 0, 1)
        verify_layout.addWidget(self.verify_browse_btn, 0, 2)
        verify_layout.addWidget(self.verify_address_label, 1, 0)
        verify_layout.addWidget(self.verify_address, 1, 1)
        verify_layout.addWidget(self.verify_sector_label, 1, 2)
        verify_layout.addWidget(self.verify_sector_combo, 1, 3)
        verify_layout.addWidget(self.verify_sector_custom, 1, 4)
        verify_layout.addWidget(self.verify_btn, 2, 0)
        verify_layout.addWidget(self.calculate_md5_btn, 2, 1)
        self.verify_group.setLayout(verify_layout)
        self.debug_group = QGroupBox()
        debug_layout = QGridLayout()
        self.enable_debug_log = QCheckBox()
        self.enable_debug_log.stateChanged.connect(_safe_slot(self.toggle_debug_log))
        self.export_log_btn = QPushButton()
        self.export_log_btn.clicked.connect(_safe_slot(self.export_system_log))
        self.show_usb_info_btn = QPushButton()
        self.show_usb_info_btn.clicked.connect(_safe_slot(self.show_usb_info))
        debug_layout.addWidget(self.enable_debug_log, 0, 0, 1, 2)
        debug_layout.addWidget(self.export_log_btn, 1, 0)
        debug_layout.addWidget(self.show_usb_info_btn, 1, 1)
        self.debug_group.setLayout(debug_layout)
        # Misc / new tool commands group
        self.misc_ops_group = QGroupBox()
        misc_layout = QGridLayout()

        # Note: flash info quick buttons are created in the left panel's
        # `create_left_panel()` as `self.read_flash_id_btn` /
        # `self.read_flash_info_btn`. Do NOT recreate them here to avoid
        # duplicate widgets and blank labels. They are intentionally not
        # re-instantiated in the advanced tab's misc group.


        # Layout placement (compact) — flash info quick buttons are placed in
        # the left quick group. The misc layout begins with the pack/unpack
        # controls at row 2 to preserve existing visual order.

        # Pack/unpack and related tools are shown on the Pack/Unpack tab.
        # They were moved out of the Advanced tab to declutter advanced tools.

        self.misc_ops_group.setLayout(misc_layout)
        # Only add the flash ops group if it contains actionable widgets.
        try:
            if self.flash_ops_group.layout() and self.flash_ops_group.layout().count() > 0:
                layout.addWidget(self.flash_ops_group)
        except Exception:
            pass
        layout.addWidget(self.rw_ops_group)
        layout.addWidget(self.verify_group)
        layout.addWidget(self.debug_group)
        layout.addWidget(self.misc_ops_group)
        layout.addStretch()
        return widget

    def create_status_bar(self):
        self.statusBar()
        self.lang_combo = QComboBox()
    
        self.lang_combo.addItem("中文 (Chinese)", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setMinimumWidth(120)
        self.lang_combo.view().setMinimumWidth(120)
    
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.currentTextChanged.connect(_safe_slot(self.on_language_changed))
        self.statusBar().addPermanentWidget(self.lang_combo)
    
        self.connection_status = QLabel()
        self.connection_status.setStyleSheet("QLabel { color: #aaaaaa; margin: 0 10px; }")
        self.statusBar().addPermanentWidget(self.connection_status)

    def on_language_changed(self):
        selected_lang = self.lang_combo.currentData()
        self.manager.set_language(selected_lang)
        self.update_ui_text()

    def start_device_detection(self):
        if not self.device_worker:
            self.device_worker = DeviceWorker(self.manager)
            self.device_worker.device_found.connect(_safe_slot(self.on_device_found))
            self.device_worker.device_lost.connect(_safe_slot(self.on_device_lost))
            self.device_worker.start()

    def stop_device_detection(self):
        if self.device_worker:
            self.device_worker.stop()
            self.device_worker.wait()
            self.device_worker = None

    def on_device_found(self, devices, mode, chip_info):
        self.connected_devices = devices
        self.device_mode = mode
        self.chip_info = chip_info
        self.device_list.clear()
        for device in devices:
            self.device_list.addItem(device)
        if devices:
            self.device_list.setCurrentRow(0)
            self.current_device = devices[0]
        self.update_device_status()
        
    def on_device_lost(self):
        self.connected_devices = []
        self.current_device = None
        self.device_mode = "not_connected_status"
        self.chip_info = "unknown_chip"
        self.device_list.clear()
        self.update_device_status()

    def cleanup(self):
        """Stop background workers and running subprocesses before application exit."""
        # Robust cleanup: stop known workers and wait briefly for termination.
        # This method should be safe to call multiple times.
        try:
            # Stop device worker
            if getattr(self, 'device_worker', None):
                try:
                    self.device_worker.stop()
                    self.device_worker.wait(1000)
                except Exception:
                    pass

            # Stop partition worker
            if getattr(self, 'partition_worker', None):
                try:
                    if self.partition_worker.isRunning():
                        try:
                            # If worker exposes a terminate/stop API, call it
                            if hasattr(self.partition_worker, 'stop'):
                                self.partition_worker.stop()
                        except Exception:
                            pass
                        # Wait briefly for thread to finish
                        self.partition_worker.wait(1000)
                except Exception:
                    pass

            # Stop mass production workers (if any)
            if getattr(self, 'mass_workers', None):
                for w in list(self.mass_workers):
                    try:
                        if getattr(w, 'terminate_process', None):
                            try:
                                w.terminate_process()
                            except Exception:
                                pass
                        # Request thread stop if supported
                        try:
                            if hasattr(w, 'stop'):
                                w.stop()
                        except Exception:
                            pass
                        try:
                            w.wait(1000)
                        except Exception:
                            pass
                    except Exception:
                        pass

            # Terminate running single command worker subprocess if any
            if getattr(self, 'command_worker', None):
                try:
                    if hasattr(self.command_worker, 'terminate_process'):
                        try:
                            self.command_worker.terminate_process()
                        except Exception:
                            pass
                    try:
                        self.command_worker.wait(1000)
                    except Exception:
                        pass
                except Exception:
                    pass

            # Clear any locks
            try:
                self._partition_refresh_lock = False
            except Exception:
                pass
        except Exception:
            pass

    def update_device_status(self):
        if self.current_device:
            mode_text = self.tr(f"connected_{self.device_mode.lower()}")
            chip_text = self.chip_info
            self.device_status_label.setText(mode_text)
            self.device_status_label.setStyleSheet("QLabel { color: #28a745; padding: 5px; font-weight: bold; }")
            self.chip_info_label.setText(f"{self.tr('chip')}: {chip_text}")
            self.statusBar().showMessage(f"{self.tr('ready_status')}{self.tr('status_line_delimiter')}{mode_text}")
            self.connection_status.setText(f"🟢 {self.tr('connected')}")
        else:
            self.device_status_label.setText(self.tr("detecting_device"))
            self.device_status_label.setStyleSheet("QLabel { color: #aaaaaa; padding: 5px; }")
            self.chip_info_label.setText(f"{self.tr('chip')}: {self.tr('unknown_chip')}")
            self.statusBar().showMessage(f"{self.tr('ready_status')}{self.tr('status_line_delimiter')}{self.tr('not_connected_status')}")
            self.connection_status.setText(f"⚪ {self.tr('not_connected')}")
            
    def log_message(self, message):
        self.log_output.append(message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def show_message(self, title_key, message_key, icon="Information"):
        msg = QMessageBox()
        msg.setWindowTitle(self.tr(title_key))
        # Ensure message box can display longer Chinese messages by
        # increasing the minimum width and using the application font.
        try:
            app_font = QApplication.font()
            app_font.setPointSize(max(app_font.pointSize(), 11))
            msg.setFont(app_font)
            msg.setMinimumWidth(600)
        except Exception:
            pass
        msg.setText(self.tr(message_key))
        if icon == "Warning":
            msg.setIcon(QMessageBox.Icon.Warning)
        elif icon == "Critical":
            msg.setIcon(QMessageBox.Icon.Critical)
        else:
            msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    def browse_file(self, line_edit, filter_key):
        file_filter = self.tr(filter_key)
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("browse_btn"), "", file_filter)
        if file_path:
            line_edit.setText(file_path)

    def register_browse(self, button, line_edit, filter_key=None, save=False):
        """Helper to connect a browse button to a line_edit.
        If save is True, opens a Save dialog; otherwise Open dialog.
        If filter_key is None, use generic all-files filter.
        """
        def _on_browse():
            try:
                if save:
                    file_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_file_dialog"), "", self.tr(filter_key) if filter_key else "")
                    if file_path:
                        line_edit.setText(file_path)
                else:
                    file_filter = self.tr(filter_key) if filter_key else ""
                    file_path, _ = QFileDialog.getOpenFileName(self, self.tr("browse_btn"), "", file_filter)
                    if file_path:
                        line_edit.setText(file_path)
            except Exception:
                pass

        try:
            button.clicked.connect(_safe_slot(_on_browse))
        except Exception:
            try:
                button.clicked.connect(lambda: _on_browse())
            except Exception:
                pass

    def browse_save_path(self):
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_file_dialog"))
        if file_path:
            self.read_save_path.setText(file_path)

    def run_command(self, cmd, description_key):
        if self.command_worker and self.command_worker.isRunning():
            self.show_message("Warning", "command_already_running", "Warning")
            return
        self.progress_bar.setValue(0)
        self.progress_label.setText(self.tr('ready'))
        self.command_worker = CommandWorker(cmd, description_key, self.manager)
        # Wrap connections to avoid connecting signals directly to C-level method
        # descriptors (which can trigger post-load introspection errors in some
        # PySide6 packaging/runtime scenarios). Use small Python wrappers instead.
        self.command_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        # Always log to main log output
        self.command_worker.log.connect(_safe_slot(self.log_message))
        # If this command is reading device info, also mirror output to the
        # device info text box so the user sees detailed info in-place.
        try:
            if description_key == 'reading_device_info' and hasattr(self, 'device_info_text'):
                try:
                    self.device_info_text.clear()
                    self.device_info_text.append(self.tr('reading_device_info'))
                except Exception:
                    pass
                self.command_worker.log.connect(_safe_slot(lambda s: self.device_info_text.append(s)))
        except Exception:
            pass
        self.command_worker.finished_signal.connect(_safe_slot(self.on_command_finished))
        self.command_worker.start()

    def on_command_finished(self, success, error_msg):
        self.progress_bar.setValue(100 if success else 0)
        self.progress_label.setText(self.tr("ready_status"))
        # If this command was a verification run (we previously launched `rl`),
        # compare the temporary file's MD5 with the expected file.
        try:
            if hasattr(self, 'command_worker') and self.command_worker and getattr(self.command_worker, 'description_key', '') == 'verifying':
                tmpfile = getattr(self, '_verify_tmpfile', None)
                expected = getattr(self, '_verify_expected_file', None)
                if tmpfile and expected:
                    if success and os.path.exists(tmpfile):
                        # compute md5s
                        def md5_of(path):
                            h = hashlib.md5()
                            with open(path, 'rb') as f:
                                for chunk in iter(lambda: f.read(8192), b''):
                                    h.update(chunk)
                            return h.hexdigest()

                        try:
                            md5_tmp = md5_of(tmpfile)
                            md5_expected = md5_of(expected)
                            if md5_tmp == md5_expected:
                                self.show_message('Information', 'verification_success')
                                self.log_message(f"✅ Verification succeeded: {md5_expected}")
                            else:
                                self.show_message('Warning', 'verification_mismatch', 'Warning')
                                self.log_message(f"❌ Verification mismatch: expected {md5_expected}, got {md5_tmp}")
                        except Exception as e:
                            self.log_message(f"❌ Verification failed: {e}")
                            self.show_message('Warning', 'verification_failed', 'Warning')
                    else:
                        # RL command failed
                        self.show_message('Warning', 'verification_failed', 'Warning')
                    # cleanup temp file
                    try:
                        if tmpfile and os.path.exists(tmpfile):
                            os.remove(tmpfile)
                    except Exception as e:
                        self.log_message(f"⚠️ Failed to remove temp file: {e}")
        except Exception:
            pass

    def enter_maskrom_mode(self):
        # Prefer to supply a loader when invoking `db <Loader>`.
        loader_path = getattr(self, 'loader_path', None)
        loader = loader_path.text() if loader_path else ''
        if loader and os.path.exists(loader):
            self.run_command([RKTOOL, "db", loader], "downloading_boot")
        else:
            # Running `db` without a loader is unsafe and ambiguous.
            # Require the user to explicitly choose a loader instead of
            # silently falling back to legacy behavior.
            self.show_message("Warning", "select_loader_file", "Warning")
            return

    def enter_loader_mode(self):
        # Reuse the loader upload logic which validates the loader path.
        self.load_loader()

    def reset_device(self):
        self.run_command([RKTOOL, "rd"], "rebooting")

    def read_device_info(self):
        self.run_command([RKTOOL, "rcb"], "reading_device_info")

    def read_partition_table(self):
        # Run ppt in a background thread and update UI when ready.
        try:
            # If a refresh is already running, skip and log it
            if getattr(self, '_partition_refresh_lock', False):
                self.log_message(self.tr('reading_partitions_already'))
                return

            # Save current splitter sizes (fallback if splitterMoved wasn't fired)
            try:
                if getattr(self, 'splitter', None):
                    self._splitter_sizes_prev = self.splitter.sizes()
            except Exception:
                self._splitter_sizes_prev = None

            # Start partition read worker
            if getattr(self, 'partition_worker', None) and self.partition_worker.isRunning():
                self.log_message(self.tr('reading_partitions_already'))
                return
            self._partition_refresh_lock = True
            self.partition_worker = PartitionPPTWorker()
            self.partition_worker.finished.connect(_safe_slot(self.on_partition_ppt_finished))
            self.partition_worker.start()
            # Use non-modal notification: log + status bar.
            self.log_message(self.tr('reading_partitions'))
            self.statusBar().showMessage(self.tr('reading_partitions'))
        except Exception:
            # fallback to synchronous call if thread cannot be started
            try:
                # mark lock during synchronous fallback
                self._partition_refresh_lock = True
                result = subprocess.run([RKTOOL, "ppt"], capture_output=True, text=True, timeout=5)
                out = result.stdout.strip()
                if result.returncode == 0 and out:
                    self.parse_partition_info(out)
                    self.populate_partition_table()
                    self.populate_partition_combo()
                    self.populate_address_combo()
                    self.log_message(self.tr('partition_read_ok'))
                    self.statusBar().showMessage(self.tr('partition_read_ok'))
                    try:
                        self._restore_splitter_sizes()
                    except Exception:
                        pass
                    # clear lock after sync success
                    try:
                        self._partition_refresh_lock = False
                    except Exception:
                        pass
                else:
                    self.run_command([RKTOOL, "ppt"], "reading_partitions")
                    try:
                        self._restore_splitter_sizes()
                    except Exception:
                        pass
                    try:
                        self._partition_refresh_lock = False
                    except Exception:
                        pass
            except Exception:
                self.run_command([RKTOOL, "ppt"], "reading_partitions")
                try:
                    self._restore_splitter_sizes()
                except Exception:
                    pass
                try:
                    self._partition_refresh_lock = False
                except Exception:
                    pass

    # TODO: Implement full firmware backup functionality
    def backup_firmware(self):
        # Backup the entire flash to a user-chosen file.
        save_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_file_dialog"), "firmware_backup.bin", self.tr("file_dialog_all"))
        if not save_path:
            return

        # Try to auto-detect flash capacity via `rkdeveloptool rfi`.
        bytes_size = None
        try:
            result = subprocess.run([RKTOOL, "rfi"], capture_output=True, text=True, timeout=6)
            out = (result.stdout or "") + "\n" + (result.stderr or "")
            # Common output may include human-friendly capacity like 'Capacity: 128MB' or a hex size.
            m = re.search(r'capacity[:\s]*([0-9.]+)\s*(MB|GB)', out, re.I)
            if m:
                val = float(m.group(1))
                unit = m.group(2).upper()
                if unit == 'MB':
                    bytes_size = int(val * 1024 * 1024)
                else:
                    bytes_size = int(val * 1024 * 1024 * 1024)
            else:
                m2 = re.search(r'size[:\s]*(0x[0-9A-Fa-f]+)', out, re.I)
                if m2:
                    try:
                        bytes_size = int(m2.group(1), 16)
                    except Exception:
                        bytes_size = None
                else:
                    # fallback: pick the largest hex-looking number present
                    hexes = re.findall(r'0x[0-9A-Fa-f]+', out)
                    if hexes:
                        nums = [int(h, 16) for h in hexes]
                        bytes_size = max(nums)
        except Exception:
            bytes_size = None

        if bytes_size and bytes_size > 0:
            # Convert bytes to sectors (512B) and request rl for that many sectors
            sectors = (bytes_size + 511) // 512
            length_arg = hex(sectors)
            try:
                self.log_message(f"🔧 {self.tr('detected_flash_size')}: {bytes_size} bytes -> {length_arg} sectors")
            except Exception:
                pass
            self.run_command([RKTOOL, "rl", "0x0", length_arg, save_path], "backing_up")
            return

        # If we couldn't auto-detect, ask the user to provide a length (in sectors, hex or decimal)
        text, ok = QInputDialog.getText(self, self.tr('enter_backup_length_title'), self.tr('enter_backup_length_prompt'))
        if not ok or not text:
            # User cancelled
            try:
                self.show_message('Information', 'backup_cancelled')
            except Exception:
                pass
            return

        length_arg = text.strip()
        # Basic normalization: if user typed bytes (like '128MB'), attempt to convert
        m = re.match(r'^([0-9.]+)\s*(MB|GB)$', length_arg, re.I)
        if m:
            val = float(m.group(1))
            unit = m.group(2).upper()
            if unit == 'MB':
                bytes_size = int(val * 1024 * 1024)
            else:
                bytes_size = int(val * 1024 * 1024 * 1024)
            sectors = (bytes_size + 511) // 512
            length_arg = hex(sectors)

        # Launch background worker to perform the read
        self.run_command([RKTOOL, "rl", "0x0", length_arg, save_path], "backing_up")

    def on_address_changed(self, text):
        if self.tr("custom_address") in text:
            self.custom_address.setEnabled(True)
        else:
            self.custom_address.setEnabled(False)

    def onekey_burn(self):
        firmware_path = self.firmware_path.text()
        if not firmware_path or not os.path.exists(firmware_path):
            self.show_message("Warning", "select_firmware_file", "Warning")
            return
        # Write full firmware to LBA starting at 0 (use `wl <BeginSec> <File>`).
        self.run_command([RKTOOL, "wl", "0x0", firmware_path], "burning")
        
    def load_loader(self):
        loader_path = self.loader_path.text()
        if not loader_path or not os.path.exists(loader_path):
            self.show_message("Warning", "select_loader_file", "Warning")
            return
        self.run_command([RKTOOL, "ul", loader_path], "loading_loader")

    def burn_image(self):
        image_path = self.image_path.text()
        if not image_path or not os.path.exists(image_path):
            self.show_message("Warning", "select_image_address", "Warning")
            return
        address = self.address_combo.currentText()
        if self.tr("custom_address") in address:
            address = self.custom_address.text()
        else:
            match = re.search(r'\((\S+)\)', address)
            if match:
                address = match.group(1)
        if not address:
            self.show_message("Warning", "select_image_address", "Warning")
            return
        self.run_command([RKTOOL, "wl", address, image_path], "burning")

    def refresh_partition_table(self):
        # Trigger reading the partition table and populate the UI (sync)
        self.read_partition_table()

    def burn_partition(self):
        selected_partition_key = self.partition_combo.currentData()
        selected_partition = self.partition_combo.currentText()
        partition_path = self.partition_file_path.text()
        if not selected_partition:
            self.show_message("Warning", "select_partition", "Warning")
            return
        if not partition_path or not os.path.exists(partition_path):
            self.show_message("Warning", "select_file_for_partition", "Warning")
            return

        # If manual override is enabled, write to the provided address using `wl`.
        try:
            if getattr(self, 'manual_address_enable', None) and self.manual_address_enable.isChecked():
                addr = self.manual_address.text().strip()
                if not addr:
                    self.show_message("Warning", "enter_manual_address", "Warning")
                    return
                self.run_command([RKTOOL, "wl", addr, partition_path], "burning")
                return
        except Exception:
            pass

        # Otherwise prefer partition name key (for wlx command)
        if selected_partition_key:
            part_arg = selected_partition_key
            self.run_command([RKTOOL, "wlx", part_arg, partition_path], "burning")
            return

        # Fallback: parse address from visible text
        match = re.search(r'\((\S+)\)', selected_partition)
        if not match:
            self.show_message("Warning", "select_partition", "Warning")
            return
        part_arg = match.group(1)
        self.run_command([RKTOOL, "wl", part_arg, partition_path], "burning")
        
    def backup_partition(self):
        selected_partition_key = self.partition_combo.currentData()
        selected_partition = self.partition_combo.currentText()
        save_path = self.partition_file_path.text()
        if not selected_partition:
            self.show_message("Warning", "select_partition", "Warning")
            return
        if not save_path:
            save_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_file_dialog"))
            if not save_path:
                return

        # Manual override: read using provided address
        try:
            if getattr(self, 'manual_address_enable', None) and self.manual_address_enable.isChecked():
                addr = self.manual_address.text().strip()
                if not addr:
                    self.show_message("Warning", "enter_manual_address", "Warning")
                    return
                self.run_command([RKTOOL, "rl", addr, "0x1000", save_path], "backing_up")
                return
        except Exception:
            pass

        # Prefer parsed partitions mapping
        if selected_partition_key and selected_partition_key in self.partitions:
            address = self.partitions[selected_partition_key].get('address')
            if address:
                self.run_command([RKTOOL, "rl", address, "0x1000", save_path], "backing_up")
                return

        # Fallback: parse from visible text
        match = re.search(r'\((\S+)\)', selected_partition)
        if not match:
            self.show_message("Warning", "select_partition", "Warning")
            return
        address = match.group(1)
        self.run_command([RKTOOL, "rl", address, "0x1000", save_path], "backing_up")
        
    def get_detailed_device_info(self):
        self.run_command([RKTOOL, "rcb"], "reading_device_info")


    # New commands mapped to rkdeveloptool
    def read_flash_id(self):
        self.run_command([RKTOOL, "rid"], "reading_flash_info")

    def read_flash_info(self):
        self.run_command([RKTOOL, "rfi"], "reading_flash_info")

    # Note: `read_chip_info` and `read_capability` were removed — their
    # functionality is covered by `read_device_info` / `get_detailed_device_info`.

    def change_storage(self):
        storage = self.change_storage_combo.currentData()
        if not storage:
            self.show_message("Warning", "select_storage", "Warning")
            return
        self.run_command([RKTOOL, "cs", storage], "changing_storage")

    def pack_bootloader(self):
        outpath = self.pack_output_path.text()
        if not outpath:
            self.show_message("Warning", "select_pack_output", "Warning")
            return
        self.run_command([RKTOOL, "pack", outpath], "packing_bootloader")

    def unpack_bootloader(self):
        inpath = self.unpack_input_path.text()
        if not inpath or not os.path.exists(inpath):
            self.show_message("Warning", "select_unpack_input", "Warning")
            return
        self.run_command([RKTOOL, "unpack", inpath], "unpacking_bootloader")

    def write_gpt(self):
        gptfile = self.gpt_path.text()
        if not gptfile or not os.path.exists(gptfile):
            self.show_message("Warning", "select_gpt_file", "Warning")
            return
        self.run_command([RKTOOL, "gpt", gptfile], "writing_gpt")

    def write_parameter(self):
        prm = self.prm_text.text()
        if not prm:
            self.show_message("Warning", "select_parameter", "Warning")
            return
        self.run_command([RKTOOL, "prm", prm], "writing_parameter")

    def tag_spl(self):
        tag = self.tagspl_tag.text()
        spl = self.tagspl_spl_path.text()
        if not tag or not spl or not os.path.exists(spl):
            self.show_message("Warning", "select_tagspl_input", "Warning")
            return
        self.run_command([RKTOOL, "tagspl", tag, spl], "tagging_spl")

    def upgrade_firmware(self):
        firmware_path = self.upgrade_file_path.text()
        if not firmware_path or not os.path.exists(firmware_path):
            self.show_message("Warning", "select_firmware_file", "Warning")
            return
        # Use raw write for firmware upgrade (write LBA at 0). Adjust if a
        # dedicated `uf`/upgrade command is preferred in your rkdeveloptool.
        self.run_command([RKTOOL, "wl", "0x0", firmware_path], "upgrade")

    def erase_flash(self):
        reply = QMessageBox.question(self, self.tr("erase_flash_warning_title"),
                                     self.tr("erase_flash_warning_message"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # `ef` is the canonical erase command; avoid passing a non-standard 'all'.
            self.run_command([RKTOOL, "ef"], "erase_flash")
            
    def test_device(self):
        self.run_command([RKTOOL, "td"], "test_connection")
    

    def read_flash(self):
        address = self.read_address.text()
        length = self.read_length.text()
        save_path = self.read_save_path.text()
        if not address or not length or not save_path:
            self.show_message("Warning", "enter_address_length", "Warning")
            return
        self.run_command([RKTOOL, "rl", address, length, save_path], "reading_flash")
        
    def verify_flash(self):
        file_path = self.verify_file_path.text()
        address = self.verify_address.text()
        if not file_path or not os.path.exists(file_path):
            self.show_message("Warning", "select_file_to_verify", "Warning")
            return
        if not address:
            self.show_message("Warning", "select_address_for_verify", "Warning")
            return
        # Determine sector size from verify UI: 512/4096/custom
        sector_size = 512
        try:
            sel = self.verify_sector_combo.currentData()
            if sel == 'custom':
                custom = self.verify_sector_custom.text().strip()
                if custom:
                    sector_size = int(custom)
            else:
                sector_size = int(sel)
        except Exception:
            sector_size = 512

        # If user provided sector count directly in read_length, use it as-is
        sector_len_arg = None
        try:
            user_len = self.read_length.text().strip()
            if user_len:
                sector_len_arg = user_len
        except Exception:
            sector_len_arg = None

        if not sector_len_arg:
            try:
                fsize = os.path.getsize(file_path)
                sectors = math.ceil(fsize / sector_size)
                sector_len_arg = hex(sectors)
            except Exception:
                sector_len_arg = "0x1000"

        # Prepare a temp file path
        try:
            tf = tempfile.NamedTemporaryFile(delete=False)
            tmpfile = tf.name
            tf.close()
        except Exception:
            tmpdir = tempfile.gettempdir()
            tmpfile = os.path.join(tmpdir, f"rkverify_{os.getpid()}_{int(hashlib.md5(file_path.encode()).hexdigest(),16) % 100000}.bin")

        # Save expected file path for on_command_finished
        self._verify_tmpfile = tmpfile
        self._verify_expected_file = file_path

        # Run rl to read device into tmpfile, description key 'verifying' triggers post-check
        self.run_command([RKTOOL, "rl", address, sector_len_arg, tmpfile], "verifying")

    def calculate_md5(self):
        # Calculate MD5 of selected verify file (or prompt if empty)
        file_path = self.verify_file_path.text()
        if not file_path or not os.path.exists(file_path):
            file_path, _ = QFileDialog.getOpenFileName(self, self.tr("select_file_dialog"), "", self.tr("file_dialog_all"))
            if not file_path:
                return
        try:
            h = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            md5sum = h.hexdigest()
            self.show_message("Information", f"MD5: {md5sum}")
            self.log_message(f"MD5({file_path}) = {md5sum}")
        except Exception as e:
            self.show_message("Warning", "md5_failed")
            self.log_message(f"MD5 calculation failed: {e}")

    def on_verify_sector_changed(self, index):
        try:
            sel = self.verify_sector_combo.currentData()
            if sel == 'custom':
                self.verify_sector_custom.setEnabled(True)
            else:
                self.verify_sector_custom.setEnabled(False)
        except Exception:
            pass

    def toggle_debug_log(self, state):
        pass

    def export_system_log(self):
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_log_dialog"), "rkdevtool.log", "Log Files (*.log);;All Files (*)")
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.log_output.toPlainText())
            self.show_message("Information", "log_saved")

    def show_usb_info(self):
        self.show_message("Information", "usb_info_not_implemented")

    def clear_log(self):
        self.log_output.clear()

    def save_log(self):
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_log_dialog"), "rkdevtool.log", "Log Files (*.log);;All Files (*)")
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.log_output.toPlainText())

if __name__ == '__main__':
    # Initialize QApplication
    app = QApplication(sys.argv)
    
    # Check for rkdeveloptool before launching the GUI
    if not ToolValidator.validate():
        manager = TranslationManager() # Temporarily create manager for error message
        QMessageBox.critical(
            None,
            manager.tr("tool_not_found_title"),
            manager.tr("tool_not_found_message")
        )
        sys.exit(1)

    # If the tool is found, proceed to launch the GUI
    manager = TranslationManager()
    main_window = RKDevToolGUI(manager)
    # Ensure background workers are stopped cleanly on quit to avoid
    # "QThread: Destroyed while thread '' is still running" errors.
    app.aboutToQuit.connect(_safe_slot(lambda: main_window.cleanup()))
    main_window.show()
    sys.exit(app.exec())