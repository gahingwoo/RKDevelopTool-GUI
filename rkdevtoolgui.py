import sys
import subprocess
import re
import os
import hashlib

from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QListWidget, QTextEdit, QFileDialog, QLabel, QLineEdit,
    QProgressBar, QMessageBox, QComboBox, QGroupBox, QGridLayout, QCheckBox,
    QSplitter, QTableWidget, QTableWidgetItem, QSpinBox, QTextBrowser,
    QScrollArea, QHeaderView
)

from i18n import TRANSLATIONS

RKTOOL = "rkdeveloptool"

PARTITION_PRESETS = {
    "parameter": {"address": "0x2000", "zh": "参数分区", "en": "Parameter"},
    "uboot": {"address": "0x4000", "zh": "U-Boot", "en": "U-Boot"},
    "trust": {"address": "0x6000", "zh": "Trust", "en": "Trust"},
    "boot": {"address": "0x8000", "zh": "Boot内核", "en": "Boot Kernel"},
    "recovery": {"address": "0x10000", "zh": "Recovery", "en": "Recovery"},
    "backup": {"address": "0x18000", "zh": "备份分区", "en": "Backup Partition"},
    "system": {"address": "0x20000", "zh": "System系统", "en": "System"},
    "vendor": {"address": "0x120000", "zh": "Vendor", "en": "Vendor"},
    "oem": {"address": "0x140000", "zh": "OEM定制", "en": "OEM Custom"},
    "userdata": {"address": "0x160000", "zh": "用户数据", "en": "Userdata"}
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
    device_found = pyqtSignal(list, str, str)  # devices, mode, chip_info
    device_lost = pyqtSignal()

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
                
            self.msleep(2000)

    def get_chip_info(self):
        try:
            result = subprocess.run([RKTOOL, "cc"], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown_chip"

    def stop(self):
        self.running = False

class CommandWorker(QThread):
    """命令执行工作线程"""
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

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

class RKDevToolGUI(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.tr = self.manager.tr
        
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
        
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_scroll_area = QScrollArea()
        left_scroll_area.setWidgetResizable(True)
        self.left_panel = self.create_left_panel()
        left_scroll_area.setWidget(self.left_panel)
        splitter.addWidget(left_scroll_area)
        
        right_scroll_area = QScrollArea()
        right_scroll_area.setWidgetResizable(True)
        self.right_panel = self.create_right_panel()
        right_scroll_area.setWidget(self.right_panel)
        splitter.addWidget(right_scroll_area)
        
        splitter.setSizes([350, 1050])
        main_layout.addWidget(splitter)
        
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
        self.tab_widget.setTabText(0, self.tr("download_tab"))
        self.tab_widget.setTabText(1, self.tr("partition_tab"))
        self.tab_widget.setTabText(2, self.tr("parameter_tab"))
        self.tab_widget.setTabText(3, self.tr("upgrade_tab"))
        self.tab_widget.setTabText(4, self.tr("advanced_tab"))
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
        self.address_combo.clear()
        self.address_combo.addItem(self.tr("address_full_firmware"))
        self.address_combo.addItem(self.tr("address_parameter"))
        self.address_combo.addItem(self.tr("address_uboot"))
        self.address_combo.addItem(self.tr("address_trust"))
        self.address_combo.addItem(self.tr("address_boot"))
        self.address_combo.addItem(self.tr("address_recovery"))
        self.address_combo.addItem(self.tr("address_system"))
        self.address_combo.addItem(self.tr("custom_address"))
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
        self.partition_combo.clear()
        for key, value in PARTITION_PRESETS.items():
            self.partition_combo.addItem(f"{self.tr(value.get(self.manager.lang, key))} ({value['address']})", key)
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
        self.upgrade_group.setTitle(self.tr("firmware_upgrade_group"))
        self.upgrade_label.setText(self.tr("upgrade_file_placeholder"))
        self.upgrade_file_path.setPlaceholderText(self.tr("upgrade_file_placeholder"))
        self.upgrade_browse_btn.setText(self.tr("browse_btn"))
        self.upgrade_btn.setText(self.tr("start_upgrade_btn"))
        self.flash_ops_group.setTitle(self.tr("flash_ops_group"))
        self.erase_flash_btn.setText(self.tr("erase_flash_btn"))
        self.test_device_btn.setText(self.tr("test_device_btn"))
        self.format_flash_btn.setText(self.tr("format_flash_btn"))
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
        self.debug_group.setTitle(self.tr("debug_tools_group"))
        self.enable_debug_log.setText(self.tr("enable_debug_log"))
        self.export_log_btn.setText(self.tr("export_system_log_btn"))
        self.show_usb_info_btn.setText(self.tr("show_usb_info_btn"))
        self.statusBar().showMessage(f"{self.tr('ready_status')}{self.tr('status_line_delimiter')}{self.tr('not_connected_status')}")
        self.connection_status.setText(f"⚪ {self.tr('not_connected')}")
        self.update_device_status()


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
        self.enter_maskrom_btn.clicked.connect(self.enter_maskrom_mode)
        self.enter_loader_btn = QPushButton()  
        self.enter_loader_btn.setProperty("class", "primary")
        self.enter_loader_btn.clicked.connect(self.enter_loader_mode)
        self.reset_device_btn = QPushButton()
        self.reset_device_btn.clicked.connect(self.reset_device)
        mode_layout.addWidget(self.enter_maskrom_btn)
        mode_layout.addWidget(self.enter_loader_btn)
        mode_layout.addWidget(self.reset_device_btn)
        self.mode_group.setLayout(mode_layout)
        self.quick_group = QGroupBox()
        quick_layout = QVBoxLayout()
        self.read_info_btn = QPushButton()
        self.read_info_btn.setProperty("class", "primary")
        self.read_info_btn.clicked.connect(self.read_device_info)
        self.read_partitions_btn = QPushButton()
        self.read_partitions_btn.clicked.connect(self.read_partition_table)
        self.backup_firmware_btn = QPushButton()
        self.backup_firmware_btn.setProperty("class", "success")
        self.backup_firmware_btn.clicked.connect(self.backup_firmware)
        quick_layout.addWidget(self.read_info_btn)
        quick_layout.addWidget(self.read_partitions_btn)
        quick_layout.addWidget(self.backup_firmware_btn)
        self.quick_group.setLayout(quick_layout)
        layout.addWidget(self.device_group)
        layout.addWidget(self.mode_group)
        layout.addWidget(self.quick_group)
        layout.addStretch()
        return panel

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
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.save_log_btn = QPushButton()
        self.save_log_btn.clicked.connect(self.save_log)
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
        self.firmware_browse_btn.clicked.connect(lambda: self.browse_file(self.firmware_path, "file_dialog_firmware"))
        self.onekey_burn_btn = QPushButton()
        self.onekey_burn_btn.setProperty("class", "success")
        self.onekey_burn_btn.clicked.connect(self.onekey_burn)
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
        self.loader_browse_btn.clicked.connect(lambda: self.browse_file(self.loader_path, "file_dialog_loader"))
        self.auto_load_loader = QCheckBox()
        self.load_loader_btn = QPushButton()
        self.load_loader_btn.setProperty("class", "primary")
        self.load_loader_btn.clicked.connect(self.load_loader)
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
        self.image_browse_btn.clicked.connect(lambda: self.browse_file(self.image_path, "file_dialog_image"))
        self.address_label = QLabel()
        self.address_combo = QComboBox()
        self.address_combo.currentTextChanged.connect(self.on_address_changed)
        self.custom_address = QLineEdit()
        self.custom_address.setEnabled(False)
        self.burn_image_btn = QPushButton()
        self.burn_image_btn.setProperty("class", "success")
        self.burn_image_btn.clicked.connect(self.burn_image)
        image_layout.addWidget(self.image_label, 0, 0)
        image_layout.addWidget(self.image_path, 0, 1)
        image_layout.addWidget(self.image_browse_btn, 0, 2)
        image_layout.addWidget(self.address_label, 1, 0)
        image_layout.addWidget(self.address_combo, 1, 1)
        image_layout.addWidget(self.custom_address, 1, 2)
        image_layout.addWidget(self.burn_image_btn, 2, 0, 1, 3)
        self.image_group.setLayout(image_layout)
        layout.addWidget(self.onekey_group)
        layout.addWidget(self.loader_group)
        layout.addWidget(self.image_group)
        layout.addStretch()
        return widget

    def create_partition_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.partition_list_group = QGroupBox()
        partition_list_layout = QVBoxLayout()
        self.partition_table = QTableWidget()
        self.partition_table.setColumnCount(4)
        self.partition_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.refresh_partitions_btn = QPushButton()
        self.refresh_partitions_btn.clicked.connect(self.refresh_partition_table)
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
        self.partition_file_browse_btn.clicked.connect(
            lambda: self.browse_file(self.partition_file_path, "file_dialog_image"))
        self.burn_partition_btn = QPushButton()
        self.burn_partition_btn.setProperty("class", "success")
        self.burn_partition_btn.clicked.connect(self.burn_partition)
        self.backup_partition_btn = QPushButton()
        self.backup_partition_btn.setProperty("class", "primary")
        self.backup_partition_btn.clicked.connect(self.backup_partition)
        partition_ops_layout.addWidget(self.select_partition_label, 0, 0)
        partition_ops_layout.addWidget(self.partition_combo, 0, 1)
        partition_ops_layout.addWidget(self.partition_file_label, 1, 0)
        partition_ops_layout.addWidget(self.partition_file_path, 1, 1)
        partition_ops_layout.addWidget(self.partition_file_browse_btn, 1, 2)
        partition_ops_layout.addWidget(self.burn_partition_btn, 2, 0)
        partition_ops_layout.addWidget(self.backup_partition_btn, 2, 1)
        self.partition_ops_group.setLayout(partition_ops_layout)
        layout.addWidget(self.partition_list_group)
        layout.addWidget(self.partition_ops_group)
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
        self.get_device_info_btn.clicked.connect(self.get_detailed_device_info)
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
        self.upgrade_group = QGroupBox()
        upgrade_layout = QGridLayout()
        self.upgrade_label = QLabel()
        self.upgrade_file_path = QLineEdit()
        self.upgrade_browse_btn = QPushButton()
        self.upgrade_browse_btn.clicked.connect(
            lambda: self.browse_file(self.upgrade_file_path, "file_dialog_firmware"))
        self.upgrade_btn = QPushButton()
        self.upgrade_btn.setProperty("class", "warning")
        self.upgrade_btn.clicked.connect(self.upgrade_firmware)
        upgrade_layout.addWidget(self.upgrade_label, 0, 0)
        upgrade_layout.addWidget(self.upgrade_file_path, 0, 1)
        upgrade_layout.addWidget(self.upgrade_browse_btn, 0, 2)
        upgrade_layout.addWidget(self.upgrade_btn, 1, 0, 1, 3)
        self.upgrade_group.setLayout(upgrade_layout)
        layout.addWidget(self.upgrade_group)
        layout.addStretch()
        return widget

    def create_advanced_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.flash_ops_group = QGroupBox()
        flash_ops_layout = QGridLayout()
        self.erase_flash_btn = QPushButton()
        self.erase_flash_btn.setProperty("class", "danger")
        self.erase_flash_btn.clicked.connect(self.erase_flash)
        self.test_device_btn = QPushButton()
        self.test_device_btn.clicked.connect(self.test_device)
        self.format_flash_btn = QPushButton()
        self.format_flash_btn.setProperty("class", "danger")
        self.format_flash_btn.clicked.connect(self.format_flash)
        flash_ops_layout.addWidget(self.erase_flash_btn, 0, 0)
        flash_ops_layout.addWidget(self.test_device_btn, 0, 1)
        flash_ops_layout.addWidget(self.format_flash_btn, 1, 0)
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
        self.read_browse_btn.clicked.connect(self.browse_save_path)
        self.read_flash_btn = QPushButton()
        self.read_flash_btn.setProperty("class", "primary")
        self.read_flash_btn.clicked.connect(self.read_flash)
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
        self.verify_browse_btn.clicked.connect(lambda: self.browse_file(self.verify_file_path, "file_dialog_all"))
        self.verify_address_label = QLabel()
        self.verify_address = QLineEdit()
        self.verify_address.setPlaceholderText("校验地址 (如: 0x0)")
        self.verify_btn = QPushButton()
        self.verify_btn.setProperty("class", "success")
        self.verify_btn.clicked.connect(self.verify_flash)
        self.calculate_md5_btn = QPushButton()
        self.calculate_md5_btn.clicked.connect(self.calculate_md5)
        verify_layout.addWidget(self.verify_file_label, 0, 0)
        verify_layout.addWidget(self.verify_file_path, 0, 1)
        verify_layout.addWidget(self.verify_browse_btn, 0, 2)
        verify_layout.addWidget(self.verify_address_label, 1, 0)
        verify_layout.addWidget(self.verify_address, 1, 1)
        verify_layout.addWidget(self.verify_btn, 2, 0)
        verify_layout.addWidget(self.calculate_md5_btn, 2, 1)
        self.verify_group.setLayout(verify_layout)
        self.debug_group = QGroupBox()
        debug_layout = QGridLayout()
        self.enable_debug_log = QCheckBox()
        self.enable_debug_log.stateChanged.connect(self.toggle_debug_log)
        self.export_log_btn = QPushButton()
        self.export_log_btn.clicked.connect(self.export_system_log)
        self.show_usb_info_btn = QPushButton()
        self.show_usb_info_btn.clicked.connect(self.show_usb_info)
        debug_layout.addWidget(self.enable_debug_log, 0, 0, 1, 2)
        debug_layout.addWidget(self.export_log_btn, 1, 0)
        debug_layout.addWidget(self.show_usb_info_btn, 1, 1)
        self.debug_group.setLayout(debug_layout)
        layout.addWidget(self.flash_ops_group)
        layout.addWidget(self.rw_ops_group)
        layout.addWidget(self.verify_group)
        layout.addWidget(self.debug_group)
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
        self.lang_combo.currentTextChanged.connect(self.on_language_changed)
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
            self.device_worker.device_found.connect(self.on_device_found)
            self.device_worker.device_lost.connect(self.on_device_lost)
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

    def browse_save_path(self):
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_file_dialog"))
        if file_path:
            self.read_save_path.setText(file_path)

    def run_command(self, cmd, description_key):
        if self.command_worker and self.command_worker.isRunning():
            self.show_message("Warning", "A command is already running. Please wait.")
            return
        self.progress_bar.setValue(0)
        self.progress_label.setText(self.tr('ready'))
        self.command_worker = CommandWorker(cmd, description_key, self.manager)
        self.command_worker.progress.connect(self.progress_bar.setValue)
        self.command_worker.log.connect(self.log_message)
        self.command_worker.finished_signal.connect(self.on_command_finished)
        self.command_worker.start()

    def on_command_finished(self, success, error_msg):
        self.progress_bar.setValue(100 if success else 0)
        self.progress_label.setText(self.tr("ready_status"))

    def enter_maskrom_mode(self):
        self.run_command([RKTOOL, "rf"], "rebooting")

    def enter_loader_mode(self):
        self.run_command([RKTOOL, "ul"], "loading_loader")

    def reset_device(self):
        self.run_command([RKTOOL, "rb"], "rebooting")

    def read_device_info(self):
        self.run_command([RKTOOL, "ri"], "reading_device_info")

    def read_partition_table(self):
        self.run_command([RKTOOL, "gpt"], "reading_partitions")

    # TODO: Implement full firmware backup functionality
    def backup_firmware(self):
        self.show_message("Warning", "Full firmware backup not yet implemented.")

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
        self.run_command([RKTOOL, "ef", firmware_path], "burning")
        
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
        self.partition_table.setRowCount(0)
        self.show_message("Information", "Reading partition table...")

    def burn_partition(self):
        selected_partition = self.partition_combo.currentText()
        partition_path = self.partition_file_path.text()
        if not selected_partition:
            self.show_message("Warning", "select_partition", "Warning")
            return
        if not partition_path or not os.path.exists(partition_path):
            self.show_message("Warning", "select_file_for_partition", "Warning")
            return
        match = re.search(r'\((\S+)\)', selected_partition)
        if not match:
            self.show_message("Warning", "select_partition", "Warning")
            return
        address = match.group(1)
        self.run_command([RKTOOL, "wl", address, partition_path], "burning")
        
    def backup_partition(self):
        selected_partition = self.partition_combo.currentText()
        save_path = self.partition_file_path.text()
        if not selected_partition:
            self.show_message("Warning", "select_partition", "Warning")
            return
        if not save_path:
            save_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_file_dialog"))
            if not save_path:
                return
        match = re.search(r'\((\S+)\)', selected_partition)
        if not match:
            self.show_message("Warning", "select_partition", "Warning")
            return
        address = match.group(1)
        self.run_command([RKTOOL, "rl", address, "0x1000", save_path], "backing_up")
        
    def get_detailed_device_info(self):
        self.run_command([RKTOOL, "ri"], "reading_device_info")

    def upgrade_firmware(self):
        firmware_path = self.upgrade_file_path.text()
        if not firmware_path or not os.path.exists(firmware_path):
            self.show_message("Warning", "select_firmware_file", "Warning")
            return
        self.run_command([RKTOOL, "uf", firmware_path], "upgrade")

    def erase_flash(self):
        reply = QMessageBox.question(self, self.tr("erase_flash_warning_title"),
                                     self.tr("erase_flash_warning_message"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.run_command([RKTOOL, "ef", "all"], "erase_flash")
            
    def test_device(self):
        self.run_command([RKTOOL, "test"], "test_connection")

    def format_flash(self):
        reply = QMessageBox.question(self, self.tr("format_flash_warning_title"),
                                     self.tr("format_flash_warning_message"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.run_command([RKTOOL, "format"], "format_flash")
            
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
        self.run_command([RKTOOL, "verify", address, file_path], "verifying")

    def calculate_md5(self):
        self.show_message("Information", "MD5 calculation not yet implemented.")

    def toggle_debug_log(self, state):
        pass

    def export_system_log(self):
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("save_log_dialog"), "rkdevtool.log", "Log Files (*.log);;All Files (*)")
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.log_output.toPlainText())
            self.show_message("Information", "Log saved successfully.")

    def show_usb_info(self):
        self.show_message("Information", "USB information not yet implemented.")

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
    main_window.show()
    sys.exit(app.exec())