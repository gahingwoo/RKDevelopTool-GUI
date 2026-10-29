"""
RKDevelopTool Professional GUI - Optimized Main File
Cross-platform Rockchip flashing tool with modern interface
"""
import sys
import os
import re
import shutil
import subprocess
import tempfile
import math
import locale
import shlex
import time
import warnings

# Nuitka-compiled builds on Python 3.14 can crash inside CPython's warnings
# machinery (SystemError: funcobject.c:446 -> segfault) when a warning is
# emitted. Silence warnings only in the compiled binary so the GUI starts
# reliably; source runs keep their warnings for development.
if "__compiled__" in globals():
    warnings.simplefilter("ignore")

from PySide6.QtCore import Qt, QTimer, QUrl, QEvent
from PySide6.QtGui import (
    QFontDatabase, QIcon, QDesktopServices, QAction, QKeySequence, QShortcut
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QListWidget, QTextEdit, QLabel, QLineEdit,
    QProgressBar, QMessageBox, QComboBox, QGroupBox, QGridLayout, QCheckBox,
    QSplitter, QTableWidget, QTableWidgetItem, QSpinBox, QTextBrowser,
    QScrollArea, QHeaderView, QSizePolicy, QInputDialog
)

# Import our modularized components
from .utils import (
    RKTOOL, ToolValidator, parse_flash_info, calculate_file_md5,
    format_file_size, parse_partition_info, safe_slot, parse_chip_info
)
from .workers import DeviceWorker, PartitionPPTWorker, CommandWorker
from .widgets import AutoLoadCombo
from .i18n import TRANSLATIONS
from .themes import ThemeManager, ThemeAutoManager
from .operations import style_messagebox
from .log_widget import RealtimeLogWidget
from . import settings as app_settings
from . import updater
from . import __version__
from .settings import AppSettings


class TranslationManager:

    @staticmethod
    def detect_system_language():
        # NOTE: do NOT use locale.getdefaultlocale() here. It is deprecated and,
        # when compiled with Nuitka on Python 3.14, emitting its DeprecationWarning
        # crashes (SystemError: bad argument to internal function -> segfault).
        # Detect the language from the standard locale environment variables
        # instead (this is what getdefaultlocale did internally on POSIX).
        try:
            system_lang = None

            for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
                value = os.environ.get(var)
                if value and value not in ("C", "POSIX"):
                    # LANGUAGE can be a colon-separated list; take the first
                    system_lang = value.split(":")[0]
                    break

            # macOS: an app started from Finder gets no LANG at all, so read the
            # user's preferred languages directly (e.g. "zh-Hans-CN").
            if not system_lang and sys.platform == "darwin":
                try:
                    out = subprocess.run(
                        ["defaults", "read", "-g", "AppleLanguages"],
                        capture_output=True, text=True, timeout=2).stdout
                    # Output looks like: ( "zh-Hans-CN", "en-US" )
                    first = re.search(r'[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*', out)
                    system_lang = first.group(0) if first else None
                except Exception:
                    system_lang = None

            # Windows: ask the OS for the UI language
            if not system_lang and sys.platform == "win32":
                try:
                    import ctypes
                    lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                    system_lang = locale.windows_locale.get(lcid)
                except Exception:
                    system_lang = None

            # Fallback to the configured locale (non-deprecated call)
            if not system_lang:
                try:
                    system_lang = locale.getlocale()[0]
                except Exception:
                    system_lang = None

            if system_lang:
                # Language code from 'en_US.UTF-8', 'zh-Hans-CN', ...
                lang_code = re.split(r'[._-]', system_lang)[0].lower()
                if lang_code in ('zh', 'en'):
                    return lang_code
        except Exception as e:
            print(f"Failed to detect system language: {e}")

        # Unknown, unsupported or unset (the C locale) -> English. Chinese is
        # only picked when the system actually asks for it.
        return 'en'

    def __init__(self, lang=None, settings=None):
        self.settings = settings
        self.translations = TRANSLATIONS

        # No explicit language asked for -> fall back to the one the user
        # picked last time, so the choice survives a restart.
        if lang is None and settings is not None:
            lang = settings.get_str(app_settings.KEY_LANGUAGE, "") or None

        if lang is None or lang == 'auto' or lang not in TRANSLATIONS:
            self.auto_mode = True
            self.lang = self.detect_system_language()
        else:
            self.auto_mode = False
            self.lang = lang

    def tr(self, key):
        """Returns the translated string for a given key."""
        return self.translations.get(self.lang, {}).get(key, key)

    def set_language(self, lang):
        """Sets the active language and remembers it for the next launch."""
        if lang == 'auto':
            self.auto_mode = True
            self.lang = self.detect_system_language()
        elif lang in self.translations:
            self.auto_mode = False
            self.lang = lang
        else:
            return

        if self.settings is not None:
            self.settings.set(app_settings.KEY_LANGUAGE, lang)


class RKDevToolGUI(QMainWindow):
    def __init__(self, manager, settings=None):
        super().__init__()
        self.manager = manager
        self.tr = self.manager.tr
        # Shared with the translation manager when main() built one, so both
        # read and write the same store.
        self.settings = settings if settings is not None else AppSettings()

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
        self.loader_loaded = False  # Track if loader has been loaded
        self.maskrom_device_shown_hint = False  # Track if we've shown loader hint for current device
        self.debug_enabled = False  # Track debug logging state

        # UI Setup
        # Both panels scroll, so the layout itself needs very little room; the
        # minimum only keeps the status bar readable. Open at the preferred
        # size but never larger than the screen, so small laptop screens (and
        # the AppImage catalog's 800x600 test screen) show the whole window.
        # A saved geometry (restore_settings) still takes precedence.
        self.setMinimumSize(800, 560)
        preferred_w, preferred_h = 1300, 720
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            preferred_w = min(preferred_w, avail.width())
            preferred_h = min(preferred_h, avail.height())
        self.resize(max(preferred_w, 800), max(preferred_h, 560))
        self.set_application_font()

        # Initialize theme manager, restoring the theme/style picked last time.
        # Both are validated against what this platform actually offers - a
        # settings file carried over from another OS can name a style that
        # doesn't exist here.
        self.theme_manager = ThemeManager(self)
        saved_theme = self.settings.get_str(app_settings.KEY_THEME, 'auto')
        if saved_theme not in self.theme_manager.get_available_themes():
            saved_theme = 'auto'
        saved_style = self.settings.get_str(app_settings.KEY_STYLE, '')
        if saved_style not in self.theme_manager.get_available_styles():
            saved_style = None
        self.theme_manager.apply_theme(theme=saved_theme, style=saved_style)

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
        self._splitter_sizes = [430, 970]
        self.splitter.setSizes(self._splitter_sizes)
        self.splitter.splitterMoved.connect(safe_slot(self._on_splitter_moved))

        main_layout.addWidget(self.splitter)

        # Status bar
        self.create_status_bar()

        # Initialize automatic theme manager (after UI is created). Only follow
        # the system theme when the user actually left the setting on 'auto' -
        # otherwise it would immediately override their saved dark/light choice.
        self.theme_auto_manager = ThemeAutoManager(
            self, enable_auto=self.theme_manager.get_current_theme() == 'auto')

        # Update UI text
        self.update_ui_text()

        # Restore remembered file paths and window geometry
        self.restore_settings()

        # Start device detection
        self.start_device_detection()

        # Look for a newer release once the window is up (at most daily).
        QTimer.singleShot(3000, safe_slot(self._auto_check_for_updates))

    def _persisted_path_fields(self):
        """Map settings key -> the QLineEdit whose contents should survive a
        restart. Built lazily because these widgets are created during UI
        setup, and a missing one must not be fatal."""
        fields = {
            app_settings.KEY_LOADER_PATH: 'loader_path',
            app_settings.KEY_FIRMWARE_PATH: 'firmware_path',
            app_settings.KEY_IMAGE_PATH: 'image_path',
        }
        return {key: getattr(self, attr) for key, attr in fields.items()
                if hasattr(self, attr)}

    def restore_settings(self):
        """Reapply the window geometry and file paths saved last session."""
        try:
            geometry = self.settings.get_bytes(app_settings.KEY_GEOMETRY)
            if geometry:
                self.restoreGeometry(geometry)

            splitter_sizes = self.settings.get(app_settings.KEY_SPLITTER)
            if splitter_sizes and hasattr(self, 'splitter'):
                # QSettings' ini backend hands lists back as strings.
                sizes = [int(s) for s in splitter_sizes]
                if len(sizes) == self.splitter.count() and all(s >= 0 for s in sizes):
                    self.splitter.setSizes(sizes)

            if self.settings.get_str(app_settings.KEY_DEBUG_LOG, "0") == "1":
                self.enable_debug_log.setChecked(True)

            for key, widget in self._persisted_path_fields().items():
                saved = self.settings.get_str(key, "")
                # Only restore paths that still exist - a stale entry pointing
                # at a deleted or unplugged-drive file is worse than an empty
                # field, since it silently fails at flash time.
                if saved and os.path.exists(saved):
                    widget.setText(saved)
        except Exception as e:
            print(f"Warning: could not restore settings: {e}")

    def save_settings(self):
        """Persist window geometry and file paths for the next launch."""
        try:
            self.settings.set(app_settings.KEY_GEOMETRY, self.saveGeometry())

            if hasattr(self, 'splitter'):
                self.settings.set(app_settings.KEY_SPLITTER,
                                   [str(s) for s in self.splitter.sizes()])

            for key, widget in self._persisted_path_fields().items():
                self.settings.set(key, widget.text())

            self.settings.sync()
        except Exception as e:
            print(f"Warning: could not save settings: {e}")

    def set_application_font(self):
        """Use the system default font at a consistent size.

        CJK glyphs are provided by the platform's system fonts; no font file
        is bundled.
        """
        try:
            # Use the platform's general-purpose system font; CJK glyphs come
            # from the system fonts, so no font file is bundled.
            app_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
            app_font.setPointSize(11)
            QApplication.setFont(app_font)
        except Exception:
            pass

    def create_left_panel(self):
        """Create left sidebar with device info and quick actions"""
        from .ui_panels import create_device_panel, create_mode_panel, create_quick_panel

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

        return panel

    def create_right_panel(self):
        """Create right main panel with tabs"""
        from .ui_panels import (
            create_home_tab, create_download_tab, create_partition_tab,
            create_parameter_tab, create_upgrade_tab, create_advanced_tab,
            create_log_panel
        )

        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Tab widget
        self.tab_widget = QTabWidget()

        # Home tab (task-oriented landing page)
        self.home_tab, home_widgets = create_home_tab(self)
        self.home_status_banner = home_widgets['status_banner']
        self.home_cards_label = home_widgets['cards_label']
        self.home_flash_card = home_widgets['flash_card']
        self.home_backup_card = home_widgets['backup_card']
        self.home_partition_card = home_widgets['partition_card']
        self.home_maskrom_card = home_widgets['maskrom_card']
        self.home_guide_group = home_widgets['guide_group']
        self.home_guide_text = home_widgets['guide_text']

        # Download tab
        download_tab, download_widgets = create_download_tab(self)
        self.download_tab = download_tab
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
        self.partition_tab = partition_tab
        self.partition_list_group = partition_widgets['list_group']
        self.partition_table = partition_widgets['table']
        self.refresh_partitions_btn = partition_widgets['refresh_btn']
        self.partition_ops_group = partition_widgets['ops_group']
        self.partition_combo = partition_widgets['combo']
        self.partition_file_path = partition_widgets['file_path']
        self.partition_file_browse_btn = partition_widgets['file_browse']
        self.burn_partition_btn = partition_widgets['burn_btn']
        self.backup_partition_btn = partition_widgets['backup_btn']
        self.erase_partition_btn = partition_widgets['erase_partition_btn']
        self.erase_all_btn = partition_widgets['erase_all_btn']
        self.manual_address_enable = partition_widgets['manual_enable']
        self.manual_address = partition_widgets['manual_address']
        self.select_partition_label = partition_widgets.get('select_label')
        self.partition_file_label = partition_widgets.get('file_label')
        self.danger_group = partition_widgets.get('danger_group')
        self.danger_label = partition_widgets.get('danger_label')

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
        self.get_security_info_btn = param_widgets['security_btn']
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
        self.gpt_export_btn = upgrade_widgets['gpt_export_btn']
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
        self.boot_group = advanced_widgets.get('boot_group')
        self.download_boot_btn = advanced_widgets.get('download_boot')
        self.upload_boot_btn = advanced_widgets.get('upload_boot')
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

        # Add tabs (Home first so newbies land on guidance, not raw commands)
        self.tab_widget.addTab(self.home_tab, "")
        self.tab_widget.addTab(download_tab, "")
        self.tab_widget.addTab(partition_tab, "")
        self.tab_widget.addTab(parameter_tab, "")
        self.tab_widget.addTab(upgrade_tab, "")
        self.tab_widget.addTab(advanced_tab, "")

        # Size the tab area to the CURRENT tab instead of the tallest one.
        # Otherwise short tabs (e.g. Home) get stretched to the Advanced tab's
        # height, leaving a large empty gap. The freed space goes to the log.
        self.tab_widget.currentChanged.connect(safe_slot(self._resize_tabs_to_current))

        layout.addWidget(self.tab_widget)

        # Command line: shows the exact rkdeveloptool command of the last
        # operation (to copy, script or learn from) and runs whatever is typed
        # or edited there - rkdeveloptool arguments only, never a shell.
        equiv_row = QHBoxLayout()
        self.equiv_command_label = QLabel()
        self.equiv_command_field = QLineEdit()
        self.equiv_command_field.returnPressed.connect(safe_slot(self.run_manual_command))
        self.equiv_command_field.installEventFilter(self)
        self._command_history = []
        self._history_pos = 0
        # Use the platform's default fixed-width font (Menlo/Consolas/etc.)
        # instead of the literal family "monospace", which doesn't exist on
        # macOS/Windows and triggers a slow font-alias lookup at startup.
        self.equiv_command_field.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.equiv_command_copy_btn = QPushButton()
        self.equiv_command_copy_btn.clicked.connect(safe_slot(self._copy_equiv_command))
        self.run_command_btn = QPushButton()
        self.run_command_btn.clicked.connect(safe_slot(self.run_manual_command))
        equiv_row.addWidget(self.equiv_command_label)
        equiv_row.addWidget(self.equiv_command_field, 1)
        equiv_row.addWidget(self.run_command_btn)
        equiv_row.addWidget(self.equiv_command_copy_btn)
        layout.addLayout(equiv_row)

        # Log panel - using enhanced real-time log widget
        self.log_widget = RealtimeLogWidget()
        self.log_output = self.log_widget.log_display
        self.progress_bar = self.log_widget.progress_bar
        self.progress_label = self.log_widget.progress_label
        self.clear_log_btn = self.log_widget.clear_btn
        self.save_log_btn = self.log_widget.export_btn
        
        # Set up export callback
        from .ui_panels import save_log
        self.log_widget.set_export_callback(
            safe_slot(lambda: save_log(self))
        )

        # Log fills the space left below the (now current-tab-sized) tab area,
        # so it's always visible and short tabs don't leave a gray void.
        self.log_widget.setMinimumHeight(180)
        layout.addWidget(self.log_widget, 1)

        # Apply the initial current-tab sizing once widgets exist.
        self._resize_tabs_to_current(self.tab_widget.currentIndex())

        return panel

    def _resize_tabs_to_current(self, index):
        """Make the tab widget take the height of the current tab only.

        Non-current pages get an Ignored vertical size policy so they don't
        inflate the tab widget's size hint; the current page uses its natural
        height. This keeps short tabs compact and lets the log panel fill the
        rest of the column.
        """
        for i in range(self.tab_widget.count()):
            page = self.tab_widget.widget(i)
            if page is None:
                continue
            vpol = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            page.setSizePolicy(QSizePolicy.Policy.Preferred, vpol)
        current = self.tab_widget.widget(index)
        if current is not None:
            current.adjustSize()

    def create_status_bar(self):
        """Create status bar with style, theme and language selectors"""
        self.statusBar()

        # Style selector combo
        self.style_combo = QComboBox()
        available_styles = self.theme_manager.get_available_styles()
        for style in available_styles:
            self.style_combo.addItem(style, style)
        
        current_style = self.theme_manager.get_current_style()
        idx = self.style_combo.findData(current_style)
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)
        
        self.style_combo.setMinimumWidth(100)
        self.style_combo.currentIndexChanged.connect(safe_slot(self.on_style_changed))
        self.statusBar().addPermanentWidget(self.style_combo)

        # Separator
        separator1 = QLabel(" | ")
        self.statusBar().addPermanentWidget(separator1)

        # Theme selector combo (auto/dark/light)
        self.theme_combo = QComboBox()
        for theme_key in self.theme_manager.get_available_themes():
            display_name = self.theme_manager.get_theme_display_name(theme_key)
            self.theme_combo.addItem(display_name, theme_key)
        
        current_theme = self.theme_manager.get_current_theme()
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        
        self.theme_combo.setMinimumWidth(140)
        self.theme_combo.currentIndexChanged.connect(safe_slot(self.on_theme_changed))
        self.statusBar().addPermanentWidget(self.theme_combo)

        # Separator
        separator2 = QLabel(" | ")
        self.statusBar().addPermanentWidget(separator2)

        # Language selector
        self.lang_combo = QComboBox()
        # "Auto" follows the UI language; the languages themselves are always
        # named in their own script, so someone stuck in a language they can't
        # read can still find theirs.
        self.lang_combo.addItem(self.tr("lang_auto"), "auto")
        self.lang_combo.addItem("中文(Chinese)", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setMinimumWidth(140)

        # Set current language based on manager's state
        if self.manager.auto_mode:
            self.lang_combo.setCurrentIndex(0)  # Auto
        else:
            idx = self.lang_combo.findData(self.manager.lang)
            self.lang_combo.setCurrentIndex(idx if idx >= 0 else 2)  # English

        # Index, not text: the "Auto" label is retranslated on a language
        # switch, and a text-change signal would re-enter the switch.
        self.lang_combo.currentIndexChanged.connect(safe_slot(self.on_language_changed))
        self.statusBar().addPermanentWidget(self.lang_combo)

        # Connection status
        self.connection_status = QLabel()
        self.statusBar().addPermanentWidget(self.connection_status)

        # Version; click to check for updates. Turns into "update available"
        # when a newer release is found.
        self._update_release = None
        self._update_worker = None
        self.update_button = QPushButton()
        self.update_button.setFlat(True)
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.clicked.connect(safe_slot(self.check_for_updates))
        self.statusBar().addPermanentWidget(self.update_button)
        self._refresh_update_button()

        # The Settings tab mirrors the pickers above, so it's built after them.
        from .settings_page import SettingsPage
        self.settings_page = SettingsPage(self)
        self.tab_widget.addTab(self.settings_page, "")
        self._resize_tabs_to_current(self.tab_widget.currentIndex())

        # macOS: "Settings…" in the application menu with Cmd+, (Qt moves an
        # action with PreferencesRole there). Elsewhere Ctrl+, opens it too.
        self.settings_action = QAction(self)
        self.settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.settings_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Preferences))
        self.settings_action.triggered.connect(safe_slot(self.open_settings))
        if sys.platform == "darwin":
            # Qt moves the Settings action into the application menu; give
            # the menu it came from real items so it isn't left empty.
            self.help_menu = self.menuBar().addMenu("")
            self.check_updates_action = self.help_menu.addAction("")
            self.check_updates_action.triggered.connect(safe_slot(self.check_for_updates))
            self.release_page_action = self.help_menu.addAction("")
            self.release_page_action.triggered.connect(safe_slot(
                lambda: QDesktopServices.openUrl(QUrl(updater.RELEASES_PAGE))))
            self.help_menu.addAction(self.settings_action)
        else:
            QShortcut(QKeySequence("Ctrl+,"), self, activated=safe_slot(self.open_settings))

    def on_style_changed(self):
        """Handle style selection change"""
        selected_style = self.style_combo.currentData()
        if selected_style:
            self.theme_manager.set_style(selected_style)
            self.settings.set(app_settings.KEY_STYLE, selected_style)

    def on_theme_changed(self):
        """Handle theme selection change"""
        selected_theme = self.theme_combo.currentData()

        if selected_theme == 'auto':
            # Enable automatic theme detection
            if hasattr(self, 'theme_auto_manager'):
                self.theme_auto_manager.enable_auto = True
                self.theme_auto_manager.apply_system_theme()
        elif selected_theme:
            # Disable auto and apply selected theme
            if hasattr(self, 'theme_auto_manager'):
                self.theme_auto_manager.enable_auto = False
            self.theme_manager.apply_theme(theme=selected_theme)

        if selected_theme:
            self.settings.set(app_settings.KEY_THEME, selected_theme)

    def update_ui_text(self):
        """Update all UI text based on current language"""
        from .ui_text_updates import update_all_ui_text
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
        from .operations import detect_supported_storage_types
        
        self.connected_devices = devices
        self.device_mode = mode
        self.chip_info = chip_info
        self.device_list.clear()
        for device in devices:
            self.device_list.addItem(device)
        if devices:
            self.device_list.setCurrentRow(0)
            self.current_device = devices[0]
            
            # If we can read chip info, it means loader is responding - don't need to prompt
            if chip_info and chip_info != "unknown_chip":
                self.loader_loaded = True
            else:
                self.loader_loaded = False
            
            # Detect supported storage types for the connected device
            detect_supported_storage_types(self)
            
            # Show dialog only once when device connects in Maskrom mode AND no chip info
            if "Maskrom" in mode and not self.maskrom_device_shown_hint and self.loader_loaded == False:
                self.maskrom_device_shown_hint = True  # Set immediately to prevent repeat
                self._show_loader_hint()
        self.update_device_status()

    def on_device_lost(self):
        """Handle device lost event"""
        self.connected_devices = []
        self.current_device = None
        self.device_mode = "not_connected_status"
        self.chip_info = "unknown_chip"
        self.device_list.clear()
        # Reset per-device state so a newly plugged-in device (which may differ
        # in loader/flash-capacity terms) isn't treated as if it were the one we lost.
        self.loader_loaded = False
        self.maskrom_device_shown_hint = False
        self._cached_flash_info = None
        self.update_device_status()

    # Buttons / inputs that only make sense when a device is connected.
    # Used by _update_action_states to avoid the "click then get an error" trap.
    _DEVICE_DEPENDENT_WIDGETS = [
        'enter_maskrom_btn', 'home_maskrom_card',
        'enter_loader_btn', 'reset_device_btn',
        'read_info_btn', 'read_partitions_btn', 'backup_firmware_btn', 'home_backup_card',
        'read_flash_id_btn', 'read_flash_info_btn',
        'onekey_burn_btn', 'load_loader_btn', 'burn_image_btn',
        'change_storage_btn', 'erase_flash_btn', 'test_device_btn',
        'refresh_partitions_btn', 'burn_partition_btn', 'backup_partition_btn',
        'erase_partition_btn', 'erase_all_btn',
        'get_device_info_btn', 'get_security_info_btn',
        'gpt_btn', 'gpt_export_btn', 'prm_btn',
        'read_flash_btn', 'verify_btn',
        'download_boot_btn', 'upload_boot_btn',
    ]

    # Actions that must stay disabled for the whole duration of a one-click
    # full flash, even as the device disappears and re-enumerates. Not all of
    # these are device-dependent (the home cards aren't), so this set is
    # applied on top of the list above rather than as a subset of it.
    _FLASH_BUSY_WIDGETS = frozenset({
        'onekey_burn_btn', 'burn_image_btn', 'home_flash_card',
        'burn_partition_btn', 'erase_flash_btn', 'erase_all_btn',
        'erase_partition_btn', 'load_loader_btn',
        'enter_maskrom_btn', 'home_maskrom_card', 'enter_loader_btn',
        'reset_device_btn',
    })

    def _update_action_states(self):
        """Enable device-dependent controls only when a device is connected.

        Newbies no longer get confusing errors from clicking actions with no
        device attached; the disabled state plus tooltip makes the prerequisite
        obvious. Offline tools (pack/unpack, md5, tag spl, mass production) stay
        enabled because they don't need a live device.
        """
        connected = self.current_device is not None
        hint = "" if connected else self.tr("connect_device_first")
        # A full RKFW flash owns the device for its whole run, but the poller
        # re-runs this every 2 s (and the board re-enumerates after db/ul),
        # which would otherwise re-enable these mid-flash and let the user
        # start a second flash on top of the running one.
        flashing = (getattr(self, '_rkfw_flashing', False)
                    or getattr(self, '_image_prep_busy', False))

        for attr in self._DEVICE_DEPENDENT_WIDGETS:
            if flashing and attr in self._FLASH_BUSY_WIDGETS:
                continue
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            widget.setEnabled(connected)
            widget.setToolTip(hint)

        for attr in self._FLASH_BUSY_WIDGETS:
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            if flashing:
                widget.setEnabled(False)
            elif attr not in self._DEVICE_DEPENDENT_WIDGETS:
                # Not device-gated, so restore it unconditionally once the
                # flash is over.
                widget.setEnabled(True)

    def update_device_status(self):
        """Update device status display"""
        self._update_action_states()
        if self.current_device:
            mode_text = self.tr(f"connected_{self.device_mode.lower()}")
            # Parse chip info to show readable chip name
            chip_text = parse_chip_info(self.chip_info) if self.chip_info else self.tr('unknown_chip')
            self.device_status_label.setText(mode_text)
            self.device_status_label.setStyleSheet("QLabel { color: #28a745; padding: 5px; font-weight: bold; }")
            self.chip_info_label.setText(f"{self.tr('chip')}: {chip_text}")
            self.statusBar().showMessage(f"{self.tr('ready_status')}{self.tr('status_line_delimiter')}{mode_text}")
            self.connection_status.setText(f"{self.tr('connected')}")
            self._update_home_banner(True, f"{mode_text} · {self.tr('chip')}: {chip_text}")
        else:
            self.device_status_label.setText(self.tr("detecting_device"))
            self.device_status_label.setStyleSheet("QLabel { padding: 5px; }")
            self.chip_info_label.setText(f"{self.tr('chip')}: {self.tr('unknown_chip')}")
            self.statusBar().showMessage(
                f"{self.tr('ready_status')}{self.tr('status_line_delimiter')}{self.tr('not_connected_status')}")
            self.connection_status.setText(f"{self.tr('not_connected')}")
            self._update_home_banner(False, f"{self.tr('home_banner_disconnected')}")

    def _update_home_banner(self, connected, text):
        """Update the home tab connection banner (plain text, native look)."""
        banner = getattr(self, 'home_status_banner', None)
        if banner is None:
            return
        color = "#28a745" if connected else "#888888"
        banner.setStyleSheet(f"QLabel {{ padding: 4px 2px; font-weight: bold; color: {color}; }}")
        banner.setText(text)

    # Utility methods
    def log_message(self, message):
        """Add message to real-time log output"""
        self.log_widget.add_log(message)
        # Also append to text browser for backward compatibility
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )

    def show_message(self, title_key, message_key, icon="Information"):
        """Show message box"""
        msg = QMessageBox()
        # Use application palette for automatic theme following
        msg.setPalette(QApplication.palette())
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
            file_filter = self.tr(filter_key) if filter_key else ""
            if save:
                file_path = app_settings.get_save_file(
                    self, self.tr("save_file_dialog"), filter_str=file_filter)
            else:
                file_path = app_settings.get_open_file(
                    self, self.tr("browse_btn"), filter_str=file_filter)
            if file_path:
                line_edit.setText(file_path)

        button.clicked.connect(safe_slot(_on_browse))

    def run_command(self, cmd, description_key, callback=None):
        """Run command in background worker with optional callback"""
        if self.command_worker and self.command_worker.isRunning():
            self.show_message("Warning", "command_already_running", "Warning")
            return

        self.progress_bar.setValue(0)
        self.progress_label.setText(self.tr('ready'))

        # Surface the exact command for power users (copyable, scriptable).
        if hasattr(self, 'equiv_command_field'):
            self.equiv_command_field.setText(' '.join(str(c) for c in cmd))

        self.command_worker = CommandWorker(cmd, description_key, self.manager)
        # Use safe_slot for all signal connections to handle thread-safety
        self.command_worker.progress.connect(safe_slot(lambda v: self.progress_bar.setValue(v)))
        self.command_worker.log.connect(safe_slot(self.log_message))

        # Mirror to device info text if reading device info
        if description_key == 'reading_device_info' and hasattr(self, 'device_info_text'):
            self.device_info_text.clear()
            self.device_info_text.append(self.tr('reading_device_info'))
            self.command_worker.log.connect(safe_slot(lambda s: self.device_info_text.append(s)))
        
        # Mirror to device info text if reading device capability
        if description_key == 'reading_device_capability' and hasattr(self, 'device_info_text'):
            self.device_info_text.clear()
            self.device_info_text.append(self.tr('reading_device_capability'))
            self.command_worker.log.connect(safe_slot(lambda s: self.device_info_text.append(s)))

        # Store callback if provided
        if callback:
            self._command_callback = callback
        else:
            self._command_callback = None

        self.command_worker.finished_signal.connect(safe_slot(self.on_command_finished))
        self.command_worker.start()

    def on_command_finished(self, success, error_msg):
        """Handle command completion"""
        self.progress_bar.setValue(100 if success else 0)
        self.progress_label.setText(self.tr("ready_status"))
        # Call callback if provided
        if hasattr(self, '_command_callback') and self._command_callback:
            try:
                # Get the command output from the worker if it has output
                output = ""
                if hasattr(self.command_worker, 'output'):
                    output = self.command_worker.output
                self._command_callback(success, output)
            except Exception as e:
                self.log_message(f"[ERROR] Callback error: {e}")
            finally:
                self._command_callback = None
        # If command failed and in Maskrom mode and no chip info, suggest loading Loader
        # (only show once per device connection via maskrom_device_shown_hint flag)
        if (not success and "Maskrom" in self.device_mode and 
            not self.loader_loaded and not self.maskrom_device_shown_hint):
            self.maskrom_device_shown_hint = True
            self._show_loader_hint(is_failure=True)

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
                    self.log_message(f"[OK] Verification succeeded: {md5_expected}")
                else:
                    self.show_message('Warning', 'verification_mismatch', 'Warning')
                    self.log_message(f"[ERROR] Verification mismatch: expected {md5_expected}, got {md5_tmp}")
            except Exception as e:
                self.log_message(f"[ERROR] Verification failed: {e}")
                self.show_message('Warning', 'verification_failed', 'Warning')
            finally:
                try:
                    if os.path.exists(tmpfile):
                        os.remove(tmpfile)
                except Exception as e:
                    self.log_message(f"[WARNING] Failed to remove temp file: {e}")

        # Clean up verification state
        self._verify_tmpfile = None
        self._verify_expected_file = None

    # Settings
    def open_settings(self):
        self.tab_widget.setCurrentWidget(self.settings_page)

    def _rebuild_settings_page(self):
        """Recreate the Settings tab in the current language. Deferred: the
        language picker on that tab may be the one whose signal got us here."""
        def rebuild():
            from .settings_page import SettingsPage
            old = self.settings_page
            index = self.tab_widget.indexOf(old)
            current = self.tab_widget.currentIndex()
            self.settings_page = SettingsPage(self)
            self.tab_widget.removeTab(index)
            self.tab_widget.insertTab(index, self.settings_page, self.tr("settings_title"))
            self.tab_widget.setCurrentIndex(current)
            self._resize_tabs_to_current(current)
            old.deleteLater()
        QTimer.singleShot(0, safe_slot(rebuild))

    # Command line
    # Commands that write to or erase the device: confirm before running.
    _WRITING_COMMANDS = {"ef", "wl", "wlx", "ul", "gpt", "prm", "wlf"}

    def eventFilter(self, obj, event):
        """Up/Down in the command line walk through earlier commands."""
        if obj is getattr(self, 'equiv_command_field', None) and \
                event.type() == QEvent.Type.KeyPress and \
                event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self._command_history:
            step = -1 if event.key() == Qt.Key.Key_Up else 1
            self._history_pos = max(0, min(len(self._command_history),
                                           self._history_pos + step))
            text = (self._command_history[self._history_pos]
                    if self._history_pos < len(self._command_history) else "")
            self.equiv_command_field.setText(text)
            return True
        return super().eventFilter(obj, event)

    def parse_manual_command(self, text):
        """rkdeveloptool arguments from the command line, or None.

        A leading `rkdeveloptool` (or any path to it, as the field shows after
        a button press) is dropped; everything after it is passed as argv, so
        nothing reaches a shell.
        """
        try:
            args = shlex.split(text)
        except ValueError:
            return None
        if args and os.path.basename(args[0]).lower() in ("rkdeveloptool", "rkdeveloptool.exe"):
            args = args[1:]
        return args or None

    def run_manual_command(self):
        text = self.equiv_command_field.text().strip()
        args = self.parse_manual_command(text)
        if not args:
            if text:
                self.log_message(f"[ERROR] {self.tr('manual_command_invalid')}")
            return
        if getattr(self, '_rkfw_flashing', False) or getattr(self, '_image_prep_busy', False) \
                or (self.command_worker is not None and self.command_worker.isRunning()):
            self.show_message("Warning", "command_already_running", "Warning")
            return
        display = " ".join(shlex.quote(a) for a in ["rkdeveloptool", *args])
        if args[0].lower() in self._WRITING_COMMANDS:
            reply = QMessageBox.warning(
                self, self.tr("manual_command_confirm_title"),
                self.tr("manual_command_confirm_message").format(display),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        if not self._command_history or self._command_history[-1] != text:
            self._command_history.append(text)
        self._history_pos = len(self._command_history)
        self.run_command([RKTOOL, *args], "manual_command")

    def _copy_equiv_command(self):
        """Copy the equivalent rkdeveloptool command to the clipboard."""
        text = self.equiv_command_field.text().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage(self.tr("command_copied"), 2000)

    def on_language_changed(self):
        """Handle language change"""
        selected_lang = self.lang_combo.currentData()
        self.manager.set_language(selected_lang)
        # Update UI with new language
        self.update_ui_text()
        self._rebuild_settings_page()
        # Update language combo display
        if selected_lang == 'auto':
            print(f"语言切换为自动模式 (检测到: {self.manager.lang})")
        else:
            print(f"语言切换为: {selected_lang}")

    # Update check
    def _refresh_update_button(self):
        if self._update_release:
            self.update_button.setText(
                self.tr("update_available").format(self._update_release["version"]))
            self.update_button.setStyleSheet("font-weight: bold;")
        else:
            # Say what clicking does: a bare "v5.5.0" reads as a label.
            self.update_button.setText(
                f"v{__version__} · {self.tr('check_updates_label')}")
            self.update_button.setStyleSheet("")
        self.update_button.setToolTip(self.tr("check_updates_tooltip"))

    def _auto_check_for_updates(self):
        if self.settings.get_str(app_settings.KEY_UPDATE_AUTO, "1") != "1":
            return
        try:
            last = float(self.settings.get_str(app_settings.KEY_UPDATE_LAST_CHECK, "0"))
        except ValueError:
            last = 0.0
        if 0 <= time.time() - last < updater.AUTO_CHECK_INTERVAL_S:
            return
        self._start_update_check(manual=False)

    def check_for_updates(self):
        """Status-bar click: show a known update, or check now."""
        if self._update_release:
            self._show_update_dialog(self._update_release)
            return
        self._start_update_check(manual=True)

    def _start_update_check(self, manual):
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        worker = updater.UpdateCheckWorker()
        self._update_worker = worker
        if manual:
            self.update_button.setText(self.tr("checking_updates"))
        worker.available.connect(safe_slot(lambda r: self._on_update_available(r, manual)))
        worker.up_to_date.connect(safe_slot(lambda v: self._on_update_none(v, manual)))
        worker.failed.connect(safe_slot(lambda kind, e: self._on_update_failed(kind, e, manual)))
        worker.start()

    def _on_update_available(self, release, manual):
        self.settings.set(app_settings.KEY_UPDATE_LAST_CHECK, str(time.time()))
        self._update_release = release
        self._refresh_update_button()
        self.log_message(f"[INFO] {self.tr('update_available').format(release['version'])}")
        if manual:
            self._show_update_dialog(release)

    def _on_update_none(self, latest, manual):
        self.settings.set(app_settings.KEY_UPDATE_LAST_CHECK, str(time.time()))
        self._refresh_update_button()
        if manual:
            self._update_message(self.tr("update_none_message").format(__version__),
                                 QMessageBox.Icon.Information)

    def _on_update_failed(self, kind, error, manual):
        self._refresh_update_button()
        if manual:
            self.log_message(f"[WARNING] {self.tr('update_failed_title')}: {error}")
            reason = self.tr(f"update_error_{kind}")
            self._update_message(self.tr("update_failed_message").format(reason),
                                 QMessageBox.Icon.Warning, page=updater.RELEASES_PAGE,
                                 details=error)

    def _show_update_dialog(self, release):
        text = self.tr("update_found_message").format(release["version"], __version__)
        if not release.get("download"):
            text += "\n\n" + self.tr("update_no_package_hint")
        self._update_message(text, QMessageBox.Icon.Information,
                             download=release.get("download") or release["page"],
                             page=release["page"], notes=release.get("notes"))

    def _update_message(self, text, icon, download=None, page=None, notes=None,
                        details=None):
        """Update result dialog with an 'automatically check' checkbox."""
        msg = QMessageBox(self)
        style_messagebox(msg)
        msg.setWindowTitle(self.tr("update_title"))
        msg.setIcon(icon)
        msg.setText(text)
        if notes or details:
            msg.setDetailedText(notes or details)
        auto = QCheckBox(self.tr("update_auto_check"))
        auto.setChecked(self.settings.get_str(app_settings.KEY_UPDATE_AUTO, "1") == "1")
        msg.setCheckBox(auto)
        download_btn = page_btn = None
        if download:
            download_btn = msg.addButton(self.tr("update_download"),
                                         QMessageBox.ButtonRole.AcceptRole)
        if page and page != download:
            page_btn = msg.addButton(self.tr("update_release_page"),
                                     QMessageBox.ButtonRole.ActionRole)
        msg.addButton(self.tr("update_close"), QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        self.settings.set(app_settings.KEY_UPDATE_AUTO, "1" if auto.isChecked() else "0")
        clicked = msg.clickedButton()
        if download_btn is not None and clicked is download_btn:
            QDesktopServices.openUrl(QUrl(download))
        elif page_btn is not None and clicked is page_btn:
            QDesktopServices.openUrl(QUrl(page))

    def _show_loader_hint(self, is_failure=False):
        """Show hint dialog to load Loader when in Maskrom mode"""
        from . import operations
        
        if is_failure:
            # Show warning dialog when command fails
            msg = QMessageBox()
            # Use application palette for automatic theme following
            msg.setPalette(QApplication.palette())
            msg.setWindowTitle(self.tr("warning_title"))
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                self.tr("command_execution_failed") + "\n\n"
                + self.tr("loader_hint_message")
            )
            msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
            msg.setMinimumWidth(500)
            
            if msg.exec() == QMessageBox.StandardButton.Yes:
                self._auto_load_loader()
        else:
            # On initial device connection, show info dialog
            msg = QMessageBox()
            style_messagebox(msg)
            msg.setWindowTitle(self.tr("tip"))
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(
                self.tr("loader_hint_message")
            )
            msg.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
            msg.setMinimumWidth(500)
            
            if msg.exec() == QMessageBox.StandardButton.Yes:
                self._auto_load_loader()

    def _auto_load_loader(self):
        """Automatically load Loader"""
        from . import operations

        # load_loader() asks for the file when none is set, and marks the
        # loader as loaded only once db/ul has actually succeeded.
        operations.load_loader(self)

    def cleanup(self):
        """Cleanup before exit"""
        try:
            # Stop automatic theme manager
            if hasattr(self, 'theme_auto_manager') and self.theme_auto_manager:
                try:
                    if hasattr(self.theme_auto_manager, 'linux_timer') and self.theme_auto_manager.linux_timer:
                        self.theme_auto_manager.linux_timer.stop()
                except Exception as e:
                    print(f"Failed to stop theme timer: {e}")

            # Stop device worker. Its loop can block up to ~3s in a subprocess call
            # plus a 2s sleep before it re-checks the stop flag, so give it enough
            # time to actually exit rather than racing ahead while it's still running.
            if self.device_worker:
                try:
                    self.device_worker.stop()
                    if not self.device_worker.wait(6000):
                        print("Warning: device worker did not stop within timeout")
                except Exception as e:
                    print(f"Failed to stop device worker: {e}")

            # Stop partition worker
            if self.partition_worker and self.partition_worker.isRunning():
                try:
                    self.partition_worker.wait(1000)
                except Exception as e:
                    print(f"Failed to stop partition worker: {e}")

            # Stop mass workers
            if self.mass_workers:
                for w in self.mass_workers:
                    try:
                        if hasattr(w, 'terminate_process'):
                            w.terminate_process()
                        w.wait(1000)
                    except Exception as e:
                        print(f"Failed to stop mass worker: {e}")

            # Stop command worker
            if self.command_worker:
                try:
                    if hasattr(self.command_worker, 'terminate_process'):
                        self.command_worker.terminate_process()
                    self.command_worker.wait(1000)
                except Exception as e:
                    print(f"Failed to stop command worker: {e}")

            # Stop the RKFW prep worker (background verify/unpack) if running.
            prep_worker = getattr(self, '_rkfw_worker', None)
            if prep_worker is not None:
                try:
                    if prep_worker.isRunning():
                        prep_worker.wait(3000)
                except Exception as e:
                    print(f"Failed to stop rkfw prep worker: {e}")
                self._rkfw_worker = None
            try:
                tmp_dir = getattr(self, '_rkfw_tmp_dir', None)
                if tmp_dir:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    self._rkfw_tmp_dir = None
            except Exception:
                pass

            # An update check can't be interrupted, but its request times out;
            # wait for it rather than destroying a running QThread (which aborts).
            update_worker = getattr(self, '_update_worker', None)
            if update_worker is not None and update_worker.isRunning():
                update_worker.wait((updater.TIMEOUT_S + 2) * 1000)

            # Stop a running image decompression and drop its (multi-GB) copy.
            unpack_worker = getattr(self, '_decompress_worker', None)
            if unpack_worker is not None:
                try:
                    unpack_worker.stop()
                    unpack_worker.wait(5000)
                except Exception as e:
                    print(f"Failed to stop decompress worker: {e}")
                self._decompress_worker = None
            unpack_dir = getattr(self, '_decompress_tmp_dir', None)
            if unpack_dir:
                shutil.rmtree(unpack_dir, ignore_errors=True)
                self._decompress_tmp_dir = None

            self._partition_refresh_lock = False
        except Exception as e:
            print(f"Cleanup error: {e}")

    def closeEvent(self, event):
        """Handle window close event"""
        try:
            busy = (self.command_worker is not None and self.command_worker.isRunning()) or \
                   any(w.isRunning() for w in self.mass_workers) or \
                   (getattr(self, '_rkfw_worker', None) is not None and
                    self._rkfw_worker.isRunning()) or \
                   (getattr(self, '_decompress_worker', None) is not None and
                    self._decompress_worker.isRunning())
            if busy:
                reply = QMessageBox.question(
                    self, self.tr("warning_title"), self.tr("close_while_busy_warning"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return

            # Save before cleanup, while the widgets are still alive to read.
            self.save_settings()
            self.cleanup()
            event.accept()
        except Exception as e:
            print(f"Close event error: {e}")
            event.accept()

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


def load_app_icon():
    """Window/taskbar icon, built from the bundled PNG sizes.

    Rendered from packaging/icon/rkdeveloptool-gui.svg by
    packaging/icon/render.py. Returns an empty icon if the assets are missing
    (e.g. a stripped-down source checkout) rather than failing to start.
    """
    icon = QIcon()
    icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")
    for size in (16, 32, 48, 64, 128, 256):
        path = os.path.join(icon_dir, f"rkdeveloptool-gui-{size}.png")
        if os.path.exists(path):
            icon.addFile(path)
    return icon


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Names QSettings uses to locate its store; set before anything reads it.
    app.setOrganizationName(app_settings.ORGANIZATION)
    app.setApplicationName(app_settings.APPLICATION)
    # Lets Wayland compositors and Linux docks match the window to the
    # installed io.github.gahingwoo.rkdeveloptool_gui.desktop entry (and so to its icon).
    app.setDesktopFileName("io.github.gahingwoo.rkdeveloptool_gui")
    app.setWindowIcon(load_app_icon())

    settings = AppSettings()

    # Check for rkdeveloptool
    if not ToolValidator.validate():
        manager = TranslationManager(settings=settings)
        QMessageBox.critical(
            None,
            manager.tr("tool_not_found_title"),
            manager.tr("tool_not_found_message")
        )
        sys.exit(1)

    # Launch GUI
    manager = TranslationManager(settings=settings)
    main_window = RKDevToolGUI(manager, settings=settings)

    # Connect both closeEvent and aboutToQuit for proper cleanup
    app.aboutToQuit.connect(safe_slot(lambda: main_window.cleanup()))
    main_window.show()

    try:
        exit_code = app.exec()
        main_window.cleanup()  # Ensure cleanup happens
        return exit_code
    except Exception as e:
        print(f"Application error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)