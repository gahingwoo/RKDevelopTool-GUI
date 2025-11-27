"""
RKDevelopTool Professional GUI - Optimized Main File
Cross-platform Rockchip flashing tool with modern interface
"""
import sys
import os
import tempfile
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QListWidget, QTextEdit, QFileDialog, QLabel, QLineEdit,
    QProgressBar, QMessageBox, QComboBox, QGroupBox, QGridLayout, QCheckBox,
    QSplitter, QTableWidget, QTableWidgetItem, QSpinBox, QTextBrowser,
    QScrollArea, QHeaderView, QSizePolicy, QInputDialog
)

# Import our modularized components
from utils import (
    RKTOOL, ToolValidator, parse_flash_info, calculate_file_md5,
    format_file_size, parse_partition_info, safe_slot
)
from workers import DeviceWorker, PartitionPPTWorker, CommandWorker
from widgets import AutoLoadCombo
from i18n import TRANSLATIONS
from themes import ThemeManager, ThemeAutoManager


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


class RKDevToolGUI(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.tr = self.manager.tr

        # State
        self.partitions = {}
        self.connected_devices = []
        self.current_device = None
        self.device_mode = "not_connected_status"
        self.chip_info = "unknown_chip"
        self.device_worker = None
        self.command_worker = None
        self.partition_worker = None
        self.mass_workers = []
        self.mass_production_active = False
        self._partition_refresh_lock = False

        # UI Setup
        self.setMinimumSize(1200, 720)
        self.set_application_font()

        # Initialize theme manager
        self.theme_manager = ThemeManager(self)
        self.theme_manager.apply_theme(ThemeManager.DARK)

        # Create main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Create splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel (device info & quick actions)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        self.left_panel = self.create_left_panel()
        left_scroll.setWidget(self.left_panel)
        self.splitter.addWidget(left_scroll)

        # Right panel (main operations)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        self.right_panel = self.create_right_panel()
        right_scroll.setWidget(self.right_panel)
        self.splitter.addWidget(right_scroll)

        # Set splitter sizes
        self._splitter_sizes = [350, 1050]
        self.splitter.setSizes(self._splitter_sizes)
        self.splitter.splitterMoved.connect(safe_slot(self._on_splitter_moved))

        main_layout.addWidget(self.splitter)

        # Status bar
        self.create_status_bar()

        # Initialize automatic theme manager (after UI is created)
        self.theme_auto_manager = ThemeAutoManager(self, enable_auto=True)

        # Update UI text
        self.update_ui_text()

        # Start device detection
        self.start_device_detection()

    def set_application_font(self):
        """Set application font for better CJK support"""
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

    def create_left_panel(self):
        """Create left sidebar with device info and quick actions"""
        from ui_panels import create_device_panel, create_mode_panel, create_quick_panel

        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Device status group
        self.device_group, device_widgets = create_device_panel(self)
        self.device_status_label = device_widgets['status']
        self.chip_info_label = device_widgets['chip']
        self.connected_devices_label = device_widgets['label']
        self.device_list = device_widgets['list']

        # Mode control group
        self.mode_group, mode_widgets = create_mode_panel(self)
        self.enter_maskrom_btn = mode_widgets['maskrom']
        self.enter_loader_btn = mode_widgets['loader']
        self.reset_device_btn = mode_widgets['reset']

        # Quick actions group
        self.quick_group, quick_widgets = create_quick_panel(self)
        self.read_info_btn = quick_widgets['info']
        self.read_partitions_btn = quick_widgets['partitions']
        self.backup_firmware_btn = quick_widgets['backup']
        self.read_flash_id_btn = quick_widgets['flash_id']
        self.read_flash_info_btn = quick_widgets['flash_info']

        layout.addWidget(self.device_group)
        layout.addWidget(self.mode_group)
        layout.addWidget(self.quick_group)
        layout.addStretch()

        return panel

    def create_right_panel(self):
        """Create right main panel with tabs"""
        from ui_panels import (
            create_download_tab, create_partition_tab, create_parameter_tab,
            create_upgrade_tab, create_advanced_tab, create_log_panel
        )

        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Tab widget
        self.tab_widget = QTabWidget()

        # Download tab
        download_tab, download_widgets = create_download_tab(self)
        self.onekey_group = download_widgets['onekey_group']
        self.firmware_path = download_widgets['firmware_path']
        self.firmware_browse_btn = download_widgets['firmware_browse']
        self.onekey_burn_btn = download_widgets['burn_btn']
        self.loader_group = download_widgets['loader_group']
        self.loader_path = download_widgets['loader_path']
        self.loader_browse_btn = download_widgets['loader_browse']
        self.auto_load_loader = download_widgets['auto_load']
        self.load_loader_btn = download_widgets['load_btn']
        self.image_group = download_widgets['image_group']
        self.image_path = download_widgets['image_path']
        self.image_browse_btn = download_widgets['image_browse']
        self.address_combo = download_widgets['address_combo']
        self.custom_address = download_widgets['custom_address']
        self.burn_image_btn = download_widgets['burn_image_btn']
        self.change_storage_label = download_widgets['storage_label']
        self.change_storage_combo = download_widgets['storage_combo']
        self.change_storage_btn = download_widgets['storage_btn']
        self.erase_flash_btn = download_widgets['erase_btn']
        self.test_device_btn = download_widgets['test_btn']
        self.firmware_label = download_widgets.get('firmware_label')
        self.loader_label = download_widgets.get('loader_label')
        self.image_label = download_widgets.get('image_label')
        self.address_label = download_widgets.get('address_label')

        # Partition tab
        partition_tab, partition_widgets = create_partition_tab(self)
        self.partition_list_group = partition_widgets['list_group']
        self.partition_table = partition_widgets['table']
        self.refresh_partitions_btn = partition_widgets['refresh_btn']
        self.partition_ops_group = partition_widgets['ops_group']
        self.partition_combo = partition_widgets['combo']
        self.partition_file_path = partition_widgets['file_path']
        self.partition_file_browse_btn = partition_widgets['file_browse']
        self.burn_partition_btn = partition_widgets['burn_btn']
        self.backup_partition_btn = partition_widgets['backup_btn']
        self.manual_address_enable = partition_widgets['manual_enable']
        self.manual_address = partition_widgets['manual_address']
        self.select_partition_label = partition_widgets.get('select_label')
        self.partition_file_label = partition_widgets.get('file_label')

        # Parameter tab
        parameter_tab, param_widgets = create_parameter_tab(self)
        self.burn_params_group = param_widgets['burn_group']
        self.verify_after_burn = param_widgets['verify']
        self.erase_before_burn = param_widgets['erase']
        self.reset_after_burn = param_widgets['reset']
        self.advanced_params_group = param_widgets['advanced_group']
        self.timeout_spinbox = param_widgets['timeout']
        self.retry_count_spinbox = param_widgets['retry']
        self.device_info_group = param_widgets['info_group']
        self.device_info_text = param_widgets['info_text']
        self.get_device_info_btn = param_widgets['info_btn']
        self.timeout_label = param_widgets.get('timeout_label')
        self.retry_count_label = param_widgets.get('retry_label')

        # Upgrade tab
        upgrade_tab, upgrade_widgets = create_upgrade_tab(self)
        self.pack_group = upgrade_widgets['pack_group']
        self.pack_output_path = upgrade_widgets['pack_output']
        self.pack_browse_btn = upgrade_widgets['pack_browse']
        self.pack_btn = upgrade_widgets['pack_btn']
        self.unpack_group = upgrade_widgets['unpack_group']
        self.unpack_input_path = upgrade_widgets['unpack_input']
        self.unpack_browse_btn = upgrade_widgets['unpack_browse']
        self.unpack_btn = upgrade_widgets['unpack_btn']
        self.pack_ops_group = upgrade_widgets['ops_group']
        self.gpt_path = upgrade_widgets['gpt_path']
        self.gpt_browse_btn = upgrade_widgets['gpt_browse']
        self.gpt_btn = upgrade_widgets['gpt_btn']
        self.prm_text = upgrade_widgets['prm_text']
        self.prm_btn = upgrade_widgets['prm_btn']
        self.tagspl_tag = upgrade_widgets['tagspl_tag']
        self.tagspl_spl_path = upgrade_widgets['tagspl_path']
        self.tagspl_browse_btn = upgrade_widgets['tagspl_browse']
        self.tagspl_btn = upgrade_widgets['tagspl_btn']
        self.pack_label = upgrade_widgets.get('pack_label')
        self.unpack_label = upgrade_widgets.get('unpack_label')
        self.gpt_label = upgrade_widgets.get('gpt_label')
        self.prm_label = upgrade_widgets.get('prm_label')
        self.tagspl_label = upgrade_widgets.get('tagspl_label')

        # Advanced tab
        advanced_tab, advanced_widgets = create_advanced_tab(self)
        self.flash_ops_group = advanced_widgets['flash_group']
        self.rw_ops_group = advanced_widgets['rw_group']
        self.read_address = advanced_widgets['read_address']
        self.read_length = advanced_widgets['read_length']
        self.read_save_path = advanced_widgets['read_save']
        self.read_browse_btn = advanced_widgets['read_browse']
        self.read_flash_btn = advanced_widgets['read_btn']
        self.verify_group = advanced_widgets['verify_group']
        self.verify_file_path = advanced_widgets['verify_file']
        self.verify_browse_btn = advanced_widgets['verify_browse']
        self.verify_address = advanced_widgets['verify_address']
        self.verify_btn = advanced_widgets['verify_btn']
        self.calculate_md5_btn = advanced_widgets['md5_btn']
        self.verify_sector_combo = advanced_widgets['sector_combo']
        self.verify_sector_custom = advanced_widgets['sector_custom']
        self.debug_group = advanced_widgets['debug_group']
        self.enable_debug_log = advanced_widgets['debug_log']
        self.export_log_btn = advanced_widgets['export_log']
        self.show_usb_info_btn = advanced_widgets['usb_info']
        self.mass_production_group = advanced_widgets['mass_group']
        self.mass_device_list = advanced_widgets['mass_list']
        self.mass_scan_btn = advanced_widgets['mass_scan']
        self.mass_firmware_path = advanced_widgets['mass_firmware']
        self.mass_firmware_browse_btn = advanced_widgets['mass_browse']
        self.mass_start_btn = advanced_widgets['mass_start']
        self.mass_stop_btn = advanced_widgets['mass_stop']
        self.mass_progress_label = advanced_widgets['mass_progress']
        self.read_address_label = advanced_widgets.get('read_address_label')
        self.read_length_label = advanced_widgets.get('read_length_label')
        self.read_save_path_label = advanced_widgets.get('read_save_label')
        self.verify_file_label = advanced_widgets.get('verify_file_label')
        self.verify_address_label = advanced_widgets.get('verify_address_label')
        self.verify_sector_label = advanced_widgets.get('verify_sector_label')
        self.mass_firmware_label = advanced_widgets.get('mass_firmware_label')

        # Add tabs
        self.tab_widget.addTab(download_tab, "")
        self.tab_widget.addTab(partition_tab, "")
        self.tab_widget.addTab(parameter_tab, "")
        self.tab_widget.addTab(upgrade_tab, "")
        self.tab_widget.addTab(advanced_tab, "")

        layout.addWidget(self.tab_widget)

        # Log panel
        self.log_group, log_widgets = create_log_panel(self)
        self.clear_log_btn = log_widgets['clear']
        self.save_log_btn = log_widgets['save']
        self.log_output = log_widgets['output']
        self.progress_bar = log_widgets['progress']
        self.progress_label = log_widgets['label']

        layout.addWidget(self.log_group)

        return panel

    def create_status_bar(self):
        """Create status bar with theme checkbox and language selector"""
        self.statusBar()

        # Theme toggle checkbox
        self.theme_checkbox = QCheckBox()
        self.theme_checkbox.setText("🌙")
        self.theme_checkbox.setToolTip("Toggle Light/Dark Theme")
        self.theme_checkbox.stateChanged.connect(safe_slot(self.on_theme_toggle))
        self.statusBar().addPermanentWidget(self.theme_checkbox)

        # Separator
        separator = QLabel(" | ")
        self.statusBar().addPermanentWidget(separator)

        # Language selector
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("中文 (Chinese)", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setMinimumWidth(120)
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.currentTextChanged.connect(safe_slot(self.on_language_changed))
        self.statusBar().addPermanentWidget(self.lang_combo)

        # Connection status
        self.connection_status = QLabel()
        self.statusBar().addPermanentWidget(self.connection_status)

    def on_theme_toggle(self, state):
        """Handle theme toggle checkbox"""
        if state == Qt.CheckState.Checked.value:
            self.theme_manager.apply_theme(ThemeManager.LIGHT)
            self.theme_checkbox.setText("☀️")
        else:
            self.theme_manager.apply_theme(ThemeManager.DARK)
            self.theme_checkbox.setText("🌙")

    def update_ui_text(self):
        """Update all UI text based on current language"""
        from ui_text_updates import update_all_ui_text
        update_all_ui_text(self)

    # Device management methods
    def start_device_detection(self):
        """Start background device detection"""
        if not self.device_worker:
            self.device_worker = DeviceWorker(self.manager)
            self.device_worker.device_found.connect(safe_slot(self.on_device_found))
            self.device_worker.device_lost.connect(safe_slot(self.on_device_lost))
            self.device_worker.start()

    def stop_device_detection(self):
        """Stop device detection worker"""
        if self.device_worker:
            self.device_worker.stop()
            self.device_worker.wait()
            self.device_worker = None

    def on_device_found(self, devices, mode, chip_info):
        """Handle device found event"""
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
        """Handle device lost event"""
        self.connected_devices = []
        self.current_device = None
        self.device_mode = "not_connected_status"
        self.chip_info = "unknown_chip"
        self.device_list.clear()
        self.update_device_status()

    def update_device_status(self):
        """Update device status display"""
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
            self.statusBar().showMessage(
                f"{self.tr('ready_status')}{self.tr('status_line_delimiter')}{self.tr('not_connected_status')}")
            self.connection_status.setText(f"⚪ {self.tr('not_connected')}")

    # Utility methods
    def log_message(self, message):
        """Add message to log output"""
        self.log_output.append(message)
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )

    def show_message(self, title_key, message_key, icon="Information"):
        """Show message box"""
        msg = QMessageBox()
        msg.setWindowTitle(self.tr(title_key))
        msg.setText(self.tr(message_key))
        msg.setMinimumWidth(600)

        if icon == "Warning":
            msg.setIcon(QMessageBox.Icon.Warning)
        elif icon == "Critical":
            msg.setIcon(QMessageBox.Icon.Critical)
        else:
            msg.setIcon(QMessageBox.Icon.Information)

        msg.exec()

    def register_browse(self, button, line_edit, filter_key=None, save=False):
        """Helper to connect a browse button to a line_edit"""

        def _on_browse():
            if save:
                file_path, _ = QFileDialog.getSaveFileName(
                    self, self.tr("save_file_dialog"), "",
                    self.tr(filter_key) if filter_key else ""
                )
            else:
                file_filter = self.tr(filter_key) if filter_key else ""
                file_path, _ = QFileDialog.getOpenFileName(
                    self, self.tr("browse_btn"), "", file_filter
                )
            if file_path:
                line_edit.setText(file_path)

        button.clicked.connect(safe_slot(_on_browse))

    def run_command(self, cmd, description_key):
        """Run command in background worker"""
        if self.command_worker and self.command_worker.isRunning():
            self.show_message("Warning", "command_already_running", "Warning")
            return

        self.progress_bar.setValue(0)
        self.progress_label.setText(self.tr('ready'))

        self.command_worker = CommandWorker(cmd, description_key, self.manager)
        self.command_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.command_worker.log.connect(safe_slot(self.log_message))

        # Mirror to device info text if reading device info
        if description_key == 'reading_device_info' and hasattr(self, 'device_info_text'):
            self.device_info_text.clear()
            self.device_info_text.append(self.tr('reading_device_info'))
            self.command_worker.log.connect(safe_slot(lambda s: self.device_info_text.append(s)))

        self.command_worker.finished_signal.connect(safe_slot(self.on_command_finished))
        self.command_worker.start()

    def on_command_finished(self, success, error_msg):
        """Handle command completion"""
        self.progress_bar.setValue(100 if success else 0)
        self.progress_label.setText(self.tr("ready_status"))

        # Handle verification completion
        if hasattr(self, '_verify_tmpfile'):
            self._handle_verification_result(success)

    def _handle_verification_result(self, success):
        """Handle verification command result"""
        tmpfile = getattr(self, '_verify_tmpfile', None)
        expected = getattr(self, '_verify_expected_file', None)

        if tmpfile and expected and success and os.path.exists(tmpfile):
            try:
                md5_tmp = calculate_file_md5(tmpfile)
                md5_expected = calculate_file_md5(expected)

                if md5_tmp == md5_expected:
                    self.show_message('Information', 'verification_success')
                    self.log_message(f"✅ Verification succeeded: {md5_expected}")
                else:
                    self.show_message('Warning', 'verification_mismatch', 'Warning')
                    self.log_message(f"❌ Verification mismatch: expected {md5_expected}, got {md5_tmp}")
            except Exception as e:
                self.log_message(f"❌ Verification failed: {e}")
                self.show_message('Warning', 'verification_failed', 'Warning')
            finally:
                try:
                    if os.path.exists(tmpfile):
                        os.remove(tmpfile)
                except Exception as e:
                    self.log_message(f"⚠️ Failed to remove temp file: {e}")

        # Clean up verification state
        self._verify_tmpfile = None
        self._verify_expected_file = None

    def on_language_changed(self):
        """Handle language change"""
        selected_lang = self.lang_combo.currentData()
        self.manager.set_language(selected_lang)
        self.update_ui_text()

    def cleanup(self):
        """Cleanup before exit"""
        try:
            # Stop device worker
            if self.device_worker:
                self.device_worker.stop()
                self.device_worker.wait(1000)

            # Stop partition worker
            if self.partition_worker and self.partition_worker.isRunning():
                self.partition_worker.wait(1000)

            # Stop mass workers
            if self.mass_workers:
                for w in self.mass_workers:
                    try:
                        if hasattr(w, 'terminate_process'):
                            w.terminate_process()
                        w.wait(1000)
                    except:
                        pass

            # Stop command worker
            if self.command_worker:
                if hasattr(self.command_worker, 'terminate_process'):
                    self.command_worker.terminate_process()
                self.command_worker.wait(1000)

            self._partition_refresh_lock = False
        except Exception:
            pass

    def _on_splitter_moved(self, pos=None, index=None):
        """Save splitter sizes when moved"""
        try:
            self._splitter_sizes_prev = self.splitter.sizes()
        except Exception:
            pass

    def _restore_splitter_sizes(self):
        """Restore saved splitter sizes"""
        try:
            if hasattr(self, '_splitter_sizes_prev') and self._splitter_sizes_prev:
                self.splitter.setSizes(self._splitter_sizes_prev)
            elif hasattr(self, '_splitter_sizes'):
                self.splitter.setSizes(self._splitter_sizes)
        except Exception:
            pass


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Check for rkdeveloptool
    if not ToolValidator.validate():
        manager = TranslationManager()
        QMessageBox.critical(
            None,
            manager.tr("tool_not_found_title"),
            manager.tr("tool_not_found_message")
        )
        sys.exit(1)

    # Launch GUI
    manager = TranslationManager()
    main_window = RKDevToolGUI(manager)
    app.aboutToQuit.connect(safe_slot(lambda: main_window.cleanup()))
    main_window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()