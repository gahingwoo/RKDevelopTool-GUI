"""
Settings tab for RKDevelopTool GUI.

Every change applies immediately. The style, theme and language pickers,
the debug-log checkbox and the Loader path are two-way mirrors of the
controls elsewhere in the window, so the existing handlers do the work and
both places always agree.
"""
import datetime
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSlider,
    QSizePolicy, QSpacerItem, QSpinBox, QVBoxLayout, QWidget
)

from . import __version__
from . import settings as app_settings
from . import utils
from .utils import safe_slot

UNPACK_BESIDE, UNPACK_TEMP, UNPACK_CUSTOM = "beside", "temp", "custom"


class FontSizeControl(QWidget):
    """A slider with a number box beside it, kept in step.

    Dragging only updates the number; the size is applied when the slider
    is released, since relaying out the whole window on every step of a
    drag stutters. Typing applies on Enter or when the box loses focus.
    """

    def __init__(self, value, on_change):
        super().__init__()
        self._on_change = on_change
        low, high = app_settings.FONT_SIZE_RANGE
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(low, high)
        self.slider.setTracking(False)
        self.slider.setPageStep(2)
        self.spin = QSpinBox()
        self.spin.setRange(low, high)
        self.spin.setSuffix(" pt")
        self.spin.setKeyboardTracking(False)
        for control in (self.slider, self.spin):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.slider.sliderMoved.connect(safe_slot(self._show))
        self.slider.valueChanged.connect(safe_slot(self.setValue))
        self.spin.valueChanged.connect(safe_slot(self.setValue))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        # Take the row's spare width (see ExpandingFieldsGrow below) without
        # raising the column's minimum width.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _show(self, value):
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)

    def value(self):
        return self.spin.value()

    def setValue(self, value):
        """Set both controls and apply the size."""
        for control in (self.slider, self.spin):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self._on_change(self.spin.value())


class SettingsPage(QWidget):
    def __init__(self, gui):
        super().__init__()
        self.gui = gui
        self.tr = gui.tr
        self.settings = gui.settings

        # Two columns: the tab sits above the log, so height is what's short.
        left = QVBoxLayout()
        left.addWidget(self._appearance_group())
        left.addWidget(self._tool_group())
        left.addWidget(self._loader_group())
        left.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(self._unpack_group())
        right.addWidget(self._logs_group())
        right.addWidget(self._updates_group())
        right.addStretch(1)
        layout = QHBoxLayout(self)
        layout.setSpacing(8)
        layout.addLayout(left, 1)
        # A clear gutter between the columns: 24 px where there's room,
        # giving way (down to 8) rather than forcing a horizontal scrollbar.
        layout.addSpacerItem(QSpacerItem(16, 0, QSizePolicy.Policy.Preferred,
                                         QSizePolicy.Policy.Minimum))
        layout.addLayout(right, 1)

    def showEvent(self, event):
        # Values that can change while the tab is hidden.
        self._show_tool_status()
        self._show_version_line()
        super().showEvent(event)

    # Appearance: copies of the status-bar pickers, kept in sync both ways
    def _mirror_combo(self, source):
        combo = QComboBox()
        for i in range(source.count()):
            combo.addItem(source.itemText(i), source.itemData(i))
        combo.setCurrentIndex(source.currentIndex())
        combo.currentIndexChanged.connect(safe_slot(source.setCurrentIndex))
        # Plain Qt slots, not safe_slot wrappers: Qt then drops these
        # connections when this page is replaced (on a language switch).
        source.currentIndexChanged.connect(combo.setCurrentIndex)
        return combo

    def _appearance_group(self):
        box = QGroupBox(self.tr("settings_appearance"))
        form = QFormLayout(box)
        # macOS keeps form fields at their size hint; let the font sliders
        # (the only Expanding fields here) use the width that's there.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow(self.tr("settings_style"), self._mirror_combo(self.gui.style_combo))
        form.addRow(self.tr("settings_theme"), self._mirror_combo(self.gui.theme_combo))
        form.addRow(self.tr("settings_language"), self._mirror_combo(self.gui.lang_combo))
        note = QLabel(self.tr("settings_appearance_note"))
        note.setWordWrap(True)
        note.setEnabled(False)
        form.addRow(note)
        self.ui_font = self._font_spin(app_settings.KEY_UI_FONT_SIZE,
                                       app_settings.DEFAULT_UI_FONT_SIZE)
        self.log_font = self._font_spin(app_settings.KEY_LOG_FONT_SIZE,
                                        app_settings.DEFAULT_LOG_FONT_SIZE)
        reset = QPushButton(self.tr("settings_font_reset"))
        reset.clicked.connect(safe_slot(self._reset_fonts))
        form.addRow(self.tr("settings_ui_font"), self.ui_font)
        form.addRow(self.tr("settings_log_font"), self.log_font)
        form.addRow("", reset)
        return box

    def _font_spin(self, key, default):
        return FontSizeControl(self.gui._font_size(key, default),
                               lambda v: self._apply_font(key, v))

    def _apply_font(self, key, value):
        if self.settings.get_str(key, "") == str(value):
            return
        self.settings.set(key, str(value))
        ui = key == app_settings.KEY_UI_FONT_SIZE
        self.gui.apply_fonts(ui=ui, log=not ui)

    def _reset_fonts(self):
        self.ui_font.setValue(app_settings.DEFAULT_UI_FONT_SIZE)
        self.log_font.setValue(app_settings.DEFAULT_LOG_FONT_SIZE)

    # rkdeveloptool
    def _tool_group(self):
        box = QGroupBox("rkdeveloptool")
        v = QVBoxLayout(box)
        self.tool_path = QLineEdit(utils.saved_rkdeveloptool())
        self.tool_path.setPlaceholderText(
            self.tr("settings_tool_auto").format(utils.auto_detected_rkdeveloptool()))
        self.tool_path.editingFinished.connect(safe_slot(self._apply_tool_path))
        browse = QPushButton(self.tr("browse_btn"))
        browse.clicked.connect(safe_slot(self._browse_tool))
        reset = QPushButton(self.tr("settings_auto_detect"))
        reset.clicked.connect(safe_slot(self._reset_tool))
        row = QHBoxLayout()
        row.addWidget(self.tool_path, 1)
        row.addWidget(browse)
        row.addWidget(reset)
        v.addLayout(row)
        self.tool_status = QLabel()
        self.tool_status.setWordWrap(True)
        self.tool_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.tool_status)
        self._show_tool_status()
        return box

    def _show_tool_status(self, error=None):
        if error:
            self.tool_status.setText(error)
            return
        version = utils.rkdeveloptool_version(utils.RKTOOL) or self.tr("settings_tool_no_version")
        self.tool_status.setText(
            self.tr("settings_tool_in_use").format(utils.RKTOOL, version))

    def _browse_tool(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("settings_tool_pick"))
        if path:
            self.tool_path.setText(path)
            self._apply_tool_path()

    def _reset_tool(self):
        self.tool_path.clear()
        self._apply_tool_path()

    def _apply_tool_path(self):
        path = self.tool_path.text().strip()
        if path and not (os.path.isfile(path) and os.access(path, os.X_OK)):
            self._show_tool_status(self.tr("settings_tool_invalid").format(path))
            return
        if os.environ.get("RKDEVELOPTOOL_BIN"):
            # The environment variable wins over the saved path at startup;
            # say so instead of silently ignoring the choice next launch.
            self.gui.log_message(f"[INFO] {self.tr('settings_tool_env_note')}")
        self.settings.set(app_settings.KEY_RKTOOL_PATH, path)
        used = utils.set_rkdeveloptool(path)
        self.gui.log_message(f"[INFO] rkdeveloptool: {used}")
        self._show_tool_status()

    # Default Loader: the same field as on the main window
    def _loader_group(self):
        box = QGroupBox(self.tr("settings_loader"))
        v = QVBoxLayout(box)
        self.loader_path = QLineEdit(self.gui.loader_path.text())
        self.gui.loader_path.textChanged.connect(self._loader_changed_elsewhere)
        self.loader_path.setPlaceholderText(self.tr("settings_loader_none"))
        self.loader_path.editingFinished.connect(safe_slot(self._apply_loader))
        browse = QPushButton(self.tr("browse_btn"))
        browse.clicked.connect(safe_slot(self._browse_loader))
        clear = QPushButton(self.tr("settings_clear"))
        clear.clicked.connect(safe_slot(lambda: (self.loader_path.clear(), self._apply_loader())))
        row = QHBoxLayout()
        row.addWidget(self.loader_path, 1)
        row.addWidget(browse)
        row.addWidget(clear)
        v.addLayout(row)
        note = QLabel(self.tr("settings_loader_note"))
        note.setWordWrap(True)
        note.setEnabled(False)
        v.addWidget(note)
        return box

    def _loader_changed_elsewhere(self, text):
        if not self.loader_path.hasFocus():
            self.loader_path.setText(text)

    def _browse_loader(self):
        path = app_settings.get_open_file(self.gui, self.tr("select_loader_file"),
                                          self.tr("file_dialog_loader"))
        if path:
            self.loader_path.setText(path)
            self._apply_loader()

    def _apply_loader(self):
        path = self.loader_path.text().strip()
        self.gui.loader_path.setText(path)
        self.settings.set(app_settings.KEY_LOADER_PATH, path)

    # Where compressed images are unpacked
    def _unpack_group(self):
        box = QGroupBox(self.tr("settings_unpack"))
        v = QVBoxLayout(box)
        mode = self.settings.get_str(app_settings.KEY_UNPACK_MODE, UNPACK_BESIDE)
        self.unpack_buttons = QButtonGroup(self)
        for key, label in ((UNPACK_BESIDE, "settings_unpack_beside"),
                           (UNPACK_TEMP, "settings_unpack_temp"),
                           (UNPACK_CUSTOM, "settings_unpack_custom")):
            button = QRadioButton(self.tr(label))
            button.setProperty("mode", key)
            button.setChecked(key == mode)
            self.unpack_buttons.addButton(button)
            v.addWidget(button)
        self.unpack_dir = QLineEdit(self.settings.get_str(app_settings.KEY_UNPACK_DIR, ""))
        self.unpack_dir.editingFinished.connect(safe_slot(self._apply_unpack))
        browse = QPushButton(self.tr("browse_btn"))
        browse.clicked.connect(safe_slot(self._browse_unpack_dir))
        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 0, 0)
        row.addWidget(self.unpack_dir, 1)
        row.addWidget(browse)
        v.addLayout(row)
        self.unpack_buttons.buttonToggled.connect(safe_slot(lambda *_: self._apply_unpack()))
        self._sync_unpack_dir_enabled()
        return box

    def _unpack_mode(self):
        checked = self.unpack_buttons.checkedButton()
        return checked.property("mode") if checked else UNPACK_BESIDE

    def _sync_unpack_dir_enabled(self):
        self.unpack_dir.setEnabled(self._unpack_mode() == UNPACK_CUSTOM)

    def _select_custom_unpack_dir(self):
        """Switch to "this folder" for the path now in the field."""
        for button in self.unpack_buttons.buttons():
            if button.property("mode") == UNPACK_CUSTOM:
                button.setChecked(True)
        self._apply_unpack()

    def _browse_unpack_dir(self):
        path = QFileDialog.getExistingDirectory(self, self.tr("settings_unpack_custom"),
                                                self.unpack_dir.text())
        if path:
            self.unpack_dir.setText(path)
            for button in self.unpack_buttons.buttons():
                if button.property("mode") == UNPACK_CUSTOM:
                    button.setChecked(True)
            self._apply_unpack()

    def _apply_unpack(self):
        self._sync_unpack_dir_enabled()
        self.settings.set(app_settings.KEY_UNPACK_MODE, self._unpack_mode())
        self.settings.set(app_settings.KEY_UNPACK_DIR, self.unpack_dir.text().strip())

    # Logs and debugging
    def _logs_group(self):
        box = QGroupBox(self.tr("settings_logs"))
        v = QVBoxLayout(box)
        debug = QCheckBox(self.tr("enable_debug_log"))
        debug.setChecked(self.gui.enable_debug_log.isChecked())
        debug.toggled.connect(safe_slot(self.gui.enable_debug_log.setChecked))
        self.gui.enable_debug_log.toggled.connect(debug.setChecked)
        v.addWidget(debug)
        row = QHBoxLayout()
        save = QPushButton(self.tr("save_log_btn"))
        from .ui_panels import save_log, export_system_log
        save.clicked.connect(safe_slot(lambda: save_log(self.gui)))
        export = QPushButton(self.tr("settings_export_diagnostics"))
        export.clicked.connect(safe_slot(lambda: export_system_log(self.gui)))
        report = QPushButton(self.tr("report_button_long"))
        report.clicked.connect(safe_slot(self.gui.report_problem))
        row.addWidget(save)
        row.addWidget(export)
        row.addWidget(report)
        row.addStretch(1)
        v.addLayout(row)
        return box

    # Updates
    def _updates_group(self):
        box = QGroupBox(self.tr("update_title"))
        v = QVBoxLayout(box)
        auto = QCheckBox(self.tr("update_auto_check"))
        auto.setChecked(self.settings.get_str(app_settings.KEY_UPDATE_AUTO, "1") == "1")
        auto.toggled.connect(safe_slot(
            lambda on: self.settings.set(app_settings.KEY_UPDATE_AUTO, "1" if on else "0")))
        v.addWidget(auto)
        self.version_line = QLabel()
        self._show_version_line()
        row = QHBoxLayout()
        row.addWidget(self.version_line, 1)
        check = QPushButton(self.tr("check_updates_label"))
        check.clicked.connect(safe_slot(self.gui.check_for_updates))
        row.addWidget(check)
        v.addLayout(row)
        return box

    def _show_version_line(self):
        try:
            last = float(self.settings.get_str(app_settings.KEY_UPDATE_LAST_CHECK, "0"))
        except ValueError:
            last = 0.0
        when = (datetime.datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M")
                if last > 0 else self.tr("settings_never"))
        self.version_line.setText(self.tr("settings_version_line").format(__version__, when))
