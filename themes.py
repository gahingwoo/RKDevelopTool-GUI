"""
Theme Manager for RKDevelopTool GUI - Using Qt Built-in Styles
Supports multiple styles: Fusion, Windows, macOS, Material, iOS, etc.
"""
import sys
from PySide6.QtWidgets import QApplication, QStyleFactory
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt


# Available styles
AVAILABLE_STYLES = [
    'Fusion',
    'Windows',
    'macOS',
    'Imagine',
    'iOS',
    'Material',
    'Universal',
    'windowsvista',
]


def get_available_styles():
    """Get list of available styles on this platform"""
    available = []
    app = QApplication.instance()
    
    for style in AVAILABLE_STYLES:
        try:
            # Try to create the style to see if it's available
            if QStyleFactory.create(style):
                available.append(style)
        except Exception:
            pass
    
    # Always include Fusion as fallback
    if 'Fusion' not in available:
        available.insert(0, 'Fusion')
    
    return available


def create_dark_palette():
    """Create a dark palette for any style"""
    palette = QPalette()
    
    # Define dark colors
    dark = QColor(43, 43, 43)
    darker = QColor(30, 30, 30)
    light = QColor(255, 255, 255)
    link_color = QColor(0, 120, 212)
    mid = QColor(80, 80, 80)
    
    # Window and general
    palette.setColor(QPalette.ColorRole.Window, dark)
    palette.setColor(QPalette.ColorRole.WindowText, light)
    palette.setColor(QPalette.ColorRole.Base, darker)
    palette.setColor(QPalette.ColorRole.AlternateBase, dark)
    palette.setColor(QPalette.ColorRole.ToolTipBase, dark)
    palette.setColor(QPalette.ColorRole.ToolTipText, light)
    palette.setColor(QPalette.ColorRole.Text, light)
    palette.setColor(QPalette.ColorRole.Button, dark)
    palette.setColor(QPalette.ColorRole.ButtonText, light)
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, link_color)
    palette.setColor(QPalette.ColorRole.Highlight, link_color)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Mid, mid)
    palette.setColor(QPalette.ColorRole.Midlight, QColor(100, 100, 100))
    palette.setColor(QPalette.ColorRole.Dark, QColor(20, 20, 20))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(0, 0, 0))
    
    # For disabled state
    disabled_text = QColor(128, 128, 128)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    
    return palette


def create_light_palette():
    """Create a light palette"""
    palette = QPalette()
    
    # Define light colors
    light = QColor(240, 240, 240)
    lighter = QColor(255, 255, 255)
    dark = QColor(40, 40, 40)
    mid = QColor(180, 180, 180)
    
    # Window and general
    palette.setColor(QPalette.ColorRole.Window, light)
    palette.setColor(QPalette.ColorRole.WindowText, dark)
    palette.setColor(QPalette.ColorRole.Base, lighter)
    palette.setColor(QPalette.ColorRole.AlternateBase, light)
    palette.setColor(QPalette.ColorRole.ToolTipBase, lighter)
    palette.setColor(QPalette.ColorRole.ToolTipText, dark)
    palette.setColor(QPalette.ColorRole.Text, dark)
    palette.setColor(QPalette.ColorRole.Button, light)
    palette.setColor(QPalette.ColorRole.ButtonText, dark)
    palette.setColor(QPalette.ColorRole.BrightText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(0, 120, 212))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 212))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Mid, mid)
    palette.setColor(QPalette.ColorRole.Midlight, QColor(200, 200, 200))
    palette.setColor(QPalette.ColorRole.Dark, QColor(100, 100, 100))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(200, 200, 200))
    
    # For disabled state
    disabled_text = QColor(160, 160, 160)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    
    return palette


# ============================================
# ThemeManager Class
# ============================================


class ThemeManager:
    """Manages application styles and themes"""
    
    DARK = 'dark'
    LIGHT = 'light'
    
    def __init__(self, window):
        self.window = window
        self.app = QApplication.instance()
        self.current_theme = 'auto'  # Start with auto theme
        self.current_style = 'Fusion'
        self._available_styles = None  # Lazy-load on first access
    
    def apply_theme(self, theme=None, style=None):
        """
        Apply a theme and optionally change style
        
        Args:
            theme: 'auto', 'dark' or 'light'
            style: Style name like 'Fusion', 'Windows', 'macOS', etc.
        """
        if theme is not None:
            self.current_theme = theme
        if style is not None:
            self.current_style = style
        
        # Set the style
        self.app.setStyle(self.current_style)
        
        # Apply appropriate palette
        if self.current_theme == 'auto':
            # For auto theme, default to dark, but let ThemeAutoManager override it
            palette = create_dark_palette()
        elif self.current_theme == self.LIGHT:
            palette = create_light_palette()
        else:
            palette = create_dark_palette()
        
        self.app.setPalette(palette)
    
    def set_style(self, style_name):
        """Set a specific style"""
        available = self.get_available_styles()
        if style_name in available:
            self.current_style = style_name
            self.apply_theme()
    
    def toggle_theme(self):
        """Toggle between dark and light"""
        if self.current_theme == self.DARK:
            self.current_theme = self.LIGHT
        else:
            self.current_theme = self.DARK
        self.apply_theme()
        return self.current_theme
    
    def get_available_styles(self):
        """Return list of available styles (lazy-loads on first call)"""
        if self._available_styles is None:
            self._available_styles = get_available_styles()
        return self._available_styles
    
    def get_style_display_name(self, style):
        """Get display name for a style"""
        return style  # Style names are already display-friendly
    
    def get_available_themes(self):
        """Return list of available theme keys"""
        return ['auto', 'dark', 'light']
    
    def get_theme_display_name(self, theme_key):
        """Get display name for a theme"""
        names = {
            'auto': '自动(Auto)',
            'dark': '深色(Dark)',
            'light': '浅色(Light)',
        }
        return names.get(theme_key, theme_key)
    
    def get_current_theme(self):
        """Get the current active theme"""
        return self.current_theme
    
    def get_current_style(self):
        """Get the current active style"""
        return self.current_style
    
    def is_dark(self):
        """Check if current theme is dark"""
        return self.current_theme == self.DARK
    
    def is_light(self):
        """Check if current theme is light"""
        return self.current_theme == self.LIGHT


# ============================================
# ThemeAutoManager Class
# ============================================

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
        from PySide6.QtCore import QTimer
        self.linux_timer = QTimer()
        self.linux_timer.timeout.connect(self.apply_system_theme)
        self.linux_timer.start(2000)  # Check every 2 seconds
    
    def _get_macos_theme(self):
        """Get current macOS system theme"""
        import subprocess
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
        import subprocess
        
        try:
            import dbus as _dbus
            # Try GNOME via dbus
            if _dbus:
                try:
                    session_bus = _dbus.SessionBus()
                    settings = session_bus.get_object(
                        "org.gnome.desktop.interface",
                        "/org/gnome/desktop/interface"
                    )
                    iface = _dbus.Interface(settings, "org.freedesktop.DBus.Properties")
                    gtk_theme = iface.Get("org.gnome.desktop.interface", "GtkTheme")
                    if "dark" in gtk_theme.lower():
                        return "dark"
                except Exception:
                    pass
        except ImportError:
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
        if not hasattr(self.gui, 'theme_combo'):
            return
        
        theme = self.get_system_theme()
        
        self.gui.theme_manager.apply_theme(theme=theme)
        
        # Update combo box
        self.gui.theme_combo.blockSignals(True)
        if theme == "dark":
            self.gui.theme_combo.setCurrentIndex(1)  # Dark option (index 1)
        else:
            self.gui.theme_combo.setCurrentIndex(2)  # Light option (index 2)
        self.gui.theme_combo.blockSignals(False)
