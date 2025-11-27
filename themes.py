"""
Theme Manager for RKDevelopTool GUI
"""
import sys
import platform
import subprocess

# Linux dbus support
try:
    import dbus
except ImportError:
    dbus = None

# Dark Theme - Native controls with custom buttons
DARK_THEME = """
/* ===============================================
   KDE Breeze Dark Theme for Qt Widgets
   =============================================== */

/* Base */
QMainWindow, QWidget {
    background-color: #232629;
    color: #e5e9ef;
    font-size: 12px;
}

/* Group box titles */
QGroupBox {
    border: 1px solid #3d4144;
    border-radius: 6px;
    margin-top: 20px;
    padding: 12px;
}
QGroupBox:title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #cfd8dc;
}

/* Buttons */
QPushButton {
    background-color: #31363b;
    border: 1px solid #4d5257;
    border-radius: 6px;
    padding: 6px 14px;
    color: #e5e9ef;
}

QPushButton:hover {
    background-color: #3b4045;
    border-color: #5294e2;
}

QPushButton:pressed {
    background-color: #44494e;
}

/* State buttons */
QPushButton.primary {
    background-color: #3daee9;
    border: 1px solid #2b90c4;
    color: black;
}
QPushButton.primary:hover {
    background-color: #51b7ec;
}

QPushButton.success {
    background-color: #27ae60;
    border: 1px solid #1e8c4b;
}

QPushButton.danger {
    background-color: #c0392b;
    border: 1px solid #a83226;
}

QPushButton.warning {
    background-color: #f39c12;
    color: black;
    border: 1px solid #d98c10;
}

/* Scrollbar (Breeze style) */
QScrollBar:vertical {
    background: #232629;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4d5257;
    min-height: 30px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #5a6268;
}

QScrollBar:horizontal {
    background: #232629;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background: #4d5257;
    min-width: 30px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: #5a6268;
}

QScrollBar::add-line, 
QScrollBar::sub-line {
    background: none;
}

/* Text input */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #2b2f33;
    border: 1px solid #4d5257;
    border-radius: 6px;
    padding: 4px 8px;
    color: #e5e9ef;
}
QLineEdit:hover, QTextEdit:hover {
    border-color: #5294e2;
}

/* ComboBox popup */
QComboBox QAbstractItemView {
    background-color: #2b2f33;
    border: 1px solid #4d5257;
    selection-background-color: #3daee9;
    selection-color: black;
}
/* ============================
   KDE Breeze Dark: TabWidget
   ============================ */
QTabWidget::pane {
    border: 1px solid #3d4144;
    background-color: #2b2f33;
    border-radius: 6px;
}

QTabBar::tab {
    background: #31363b;
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

QTabBar::tab:selected {
    background: #3daee9;
    color: black;
}

QTabBar::tab:hover {
    background: #3b4045;
}

/* ============================
   KDE Breeze Dark: Slider
   ============================ */
QSlider::groove:horizontal {
    background: #3d4144;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 14px;
    background: #3daee9;
    margin: -4px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #51b7ec;
}

/* ============================
   KDE Breeze Dark: ProgressBar
   ============================ */
QProgressBar {
    border: 1px solid #4d5257;
    border-radius: 6px;
    background: #2b2f33;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #3daee9;
    border-radius: 6px;
}

/* ============================
   KDE Breeze Dark: Toolbar
   ============================ */
QToolBar {
    background: #2b2f33;
    border-bottom: 1px solid #3d4144;
}
QToolButton {
    background: transparent;
    padding: 6px 8px;
    border-radius: 4px;
}
QToolButton:hover {
    background: #3b4045;
}
QToolButton:checked {
    background: #3daee9;
    color: black;
}

/* ============================
   KDE Breeze Dark: Menu
   ============================ */
QMenu {
    background-color: #2b2f33;
    border: 1px solid #4d5257;
}
QMenu::item {
    padding: 6px 18px;
    background: transparent;
}
QMenu::item:selected {
    background: #3daee9;
    color: black;
}

/* ============================
   KDE Breeze Dark: CheckBox / Radio
   ============================ */
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
}
QCheckBox::indicator {
    border: 1px solid #4d5257;
    background: #2b2f33;
    border-radius: 3px;
}
QCheckBox::indicator:checked {
    background: #3daee9;
    border-color: #2b90c4;
}
QRadioButton::indicator {
    border: 1px solid #4d5257;
    background: #2b2f33;
    border-radius: 8px;
}
QRadioButton::indicator:checked {
    background: #3daee9;
    border-color: #2b90c4;
}
"""

# Light Theme - Native controls with custom buttons
LIGHT_THEME = """
/* ===============================================
   KDE Breeze Light Theme
   =============================================== */

/* Base */
QMainWindow, QWidget {
    background-color: #fafafa;
    color: #232629;
    font-size: 12px;
}

/* Group box */
QGroupBox {
    border: 1px solid #c7ccd1;
    border-radius: 6px;
    margin-top: 20px;
    padding: 12px;
}
QGroupBox:title {
    padding: 0 6px;
    color: #455a64;
}

/* Buttons */
QPushButton {
    background-color: #e9e9e9;
    border: 1px solid #c8c8c8;
    border-radius: 6px;
    padding: 6px 14px;
    color: #232629;
}

QPushButton:hover {
    background-color: #ffffff;
    border-color: #3daee9;
}

QPushButton:pressed {
    background-color: #dcdcdc;
}

/* Primary / success / danger */
QPushButton.primary {
    background-color: #3daee9;
    color: white;
    border: 1px solid #2b90c4;
}
QPushButton.success {
    background-color: #27ae60;
    color: white;
}
QPushButton.danger {
    background-color: #c0392b;
    color: white;
}
QPushButton.warning {
    background-color: #f39c12;
    color: black;
}

/* Scrollbar */
QScrollBar:vertical {
    background: #fafafa;
    width: 12px;
}
QScrollBar::handle:vertical {
    background: #c7ccd1;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #b0b6bb;
}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #c4c4c4;
    border-radius: 6px;
    padding: 4px 8px;
    color: #232629;
}
QLineEdit:hover {
    border-color: #3daee9;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #c4c4c4;
    selection-background-color: #3daee9;
    selection-color: white;
}
/* ============================
   KDE Breeze Light: TabWidget
   ============================ */
QTabWidget::pane {
    border: 1px solid #c7ccd1;
    background-color: #ffffff;
    border-radius: 6px;
}

QTabBar::tab {
    background: #e6e6e6;
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

QTabBar::tab:selected {
    background: #3daee9;
    color: white;
}
QTabBar::tab:hover {
    background: #f0f0f0;
}

/* ============================
   KDE Breeze Light: Slider
   ============================ */
QSlider::groove:horizontal {
    background: #c7ccd1;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 14px;
    background: #3daee9;
    margin: -4px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #51b7ec;
}

/* ============================
   KDE Breeze Light: ProgressBar
   ============================ */
QProgressBar {
    border: 1px solid #c7ccd1;
    border-radius: 6px;
    background: #ffffff;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #3daee9;
    border-radius: 6px;
}

/* ============================
   KDE Breeze Light: Toolbar
   ============================ */
QToolBar {
    background: #f0f0f0;
    border-bottom: 1px solid #c7ccd1;
}
QToolButton {
    padding: 6px 8px;
    border-radius: 4px;
}
QToolButton:hover {
    background: #e6e6e6;
}
QToolButton:checked {
    background: #3daee9;
    color: white;
}

/* ============================
   KDE Breeze Light: Menu
   ============================ */
QMenu {
    background-color: #ffffff;
    border: 1px solid #c7ccd1;
}
QMenu::item {
    padding: 6px 18px;
}
QMenu::item:selected {
    background: #3daee9;
    color: white;
}

/* ============================
   KDE Breeze Light: CheckBox / Radio
   ============================ */
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
}
QCheckBox::indicator {
    border: 1px solid #c4c4c4;
    background: #ffffff;
    border-radius: 3px;
}
QCheckBox::indicator:checked {
    background: #3daee9;
    border-color: #2b90c4;
}
QRadioButton::indicator {
    border: 1px solid #c4c4c4;
    background: #ffffff;
    border-radius: 8px;
}
QRadioButton::indicator:checked {
    background: #3daee9;
    border-color: #2b90c4;
}
"""


class ThemeManager:
    """
    Manages theme switching for the application
    """
    DARK = "dark"
    LIGHT = "light"

    def __init__(self, window):
        self.window = window
        self.current_theme = self.DARK

    def apply_theme(self, theme):
        """Apply the specified theme"""
        if theme == self.LIGHT:
            self.window.setStyleSheet(LIGHT_THEME)
            self.current_theme = self.LIGHT
        else:
            self.window.setStyleSheet(DARK_THEME)
            self.current_theme = self.DARK

    def toggle_theme(self):
        """Toggle between dark and light themes"""
        new_theme = self.LIGHT if self.current_theme == self.DARK else self.DARK
        self.apply_theme(new_theme)
        return self.current_theme

    def get_current_theme(self):
        """Get the current theme name"""
        return self.current_theme

    def is_dark(self):
        """Check if current theme is dark"""
        return self.current_theme == self.DARK

    def is_light(self):
        """Check if current theme is light"""
        return self.current_theme == self.LIGHT


class ThemeAutoManager:
    """Cross-platform automatic theme manager"""

    def __init__(self, gui, enable_auto=True):
        """
        Initialize automatic theme manager
        
        Args:
            gui: The main GUI window instance
            enable_auto: Whether to enable automatic theme detection (default: True)
        """
        self.gui = gui
        self.enable_auto = enable_auto
        self.platform = sys.platform
        self.linux_timer = None
        
        if enable_auto:
            self.init_auto_theme()

    def init_auto_theme(self):
        """Initialize automatic theme detection listeners"""
        if self.platform == "darwin":
            self._init_macos_listener()
        elif self.platform.startswith("linux"):
            self._init_linux_listener()

        # Apply initial theme
        self.apply_system_theme()

    def _init_macos_listener(self):
        """Initialize macOS system theme change listener (polling-based)"""
        # Use polling for macOS as it's more reliable and doesn't require PyObjC
        from PySide6.QtCore import QTimer
        self.linux_timer = QTimer()
        self.linux_timer.timeout.connect(self.apply_system_theme)
        self.linux_timer.start(2000)  # Check every 2 seconds

    def _get_macos_theme(self):
        """Get current macOS system theme"""
        try:
            result = subprocess.check_output(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                stderr=subprocess.STDOUT
            ).decode().strip()
            return "dark" if result == "Dark" else "light"
        except Exception:
            return "light"

    def _init_linux_listener(self):
        """Initialize Linux system theme change listener (polling-based)"""
        from PySide6.QtCore import QTimer
        self.linux_timer = QTimer()
        self.linux_timer.timeout.connect(self.apply_system_theme)
        self.linux_timer.start(2000)  # Check every 2 seconds

    def _get_linux_theme(self):
        """Get current Linux system theme (GNOME/KDE)"""
        # Try GNOME via dbus
        if dbus:
            try:
                session_bus = dbus.SessionBus()
                settings = session_bus.get_object(
                    "org.gnome.desktop.interface",
                    "/org/gnome/desktop/interface"
                )
                iface = dbus.Interface(settings, "org.freedesktop.DBus.Properties")
                gtk_theme = iface.Get("org.gnome.desktop.interface", "GtkTheme")
                if "dark" in gtk_theme.lower():
                    return "dark"
            except Exception:
                pass

        # Try KDE
        try:
            proc = subprocess.run(
                ["lookandfeeltool", "-d"], capture_output=True, text=True
            )
            if "dark" in proc.stdout.lower():
                return "dark"
        except Exception:
            pass

        return "light"

    def get_system_theme(self):
        """Get current system theme based on platform"""
        if self.platform == "darwin":
            return self._get_macos_theme()
        elif self.platform.startswith("linux"):
            return self._get_linux_theme()
        else:
            return "light"

    def apply_system_theme(self):
        """Apply system theme to the application"""
        if not self.enable_auto:
            return
        
        # Check if UI is ready
        if not hasattr(self.gui, 'theme_checkbox'):
            return
        
        theme = self.get_system_theme()
        from PySide6.QtCore import Qt
        
        if theme == "dark":
            self.gui.theme_manager.apply_theme(self.gui.theme_manager.DARK)
            self.gui.theme_checkbox.blockSignals(True)
            self.gui.theme_checkbox.setCheckState(Qt.CheckState.Unchecked)
            self.gui.theme_checkbox.setText("🌙")
            self.gui.theme_checkbox.blockSignals(False)
        else:
            self.gui.theme_manager.apply_theme(self.gui.theme_manager.LIGHT)
            self.gui.theme_checkbox.blockSignals(True)
            self.gui.theme_checkbox.setCheckState(Qt.CheckState.Checked)
            self.gui.theme_checkbox.setText("☀️")
            self.gui.theme_checkbox.blockSignals(False)

    def on_system_theme_changed(self, *_):
        """Callback for system theme change notification"""
        self.apply_system_theme()
