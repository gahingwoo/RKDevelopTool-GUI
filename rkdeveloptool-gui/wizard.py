"""
First-run wizard: check the setup (rkdeveloptool, USB access on Linux),
pick the language and theme, and show how a flash goes. Shown once; the
Settings page can open it again.
"""
import glob
import importlib.util
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWizard, QWizardPage,
)

from . import settings as app_settings
from .utils import safe_slot

# Set (to anything) to keep the wizard from opening by itself (tests).
NO_WIZARD_ENV = "RKDEVELOPTOOL_GUI_NO_WIZARD"


def udev_rule_installed():
    """Whether a udev rule mentions Rockchip's USB vendor id (2207)."""
    for path in glob.glob("/etc/udev/rules.d/*.rules") + glob.glob("/usr/lib/udev/rules.d/*.rules"):
        try:
            with open(path, errors="replace") as f:
                if "2207" in f.read():
                    return True
        except OSError:
            continue
    return False


def setup_checks():
    """[(ok, key, argument, command)]: what the app needs to flash a board.
    `command` is a shell line that fixes a failed check, or None."""
    from . import utils
    from .operations import get_rkdeveloptool_version
    checks = []
    # Same test the app starts with: it runs. Some builds print no version.
    if utils.ToolValidator.validate():
        version = get_rkdeveloptool_version()
        found = utils.RKTOOL if version == "unknown" else f"{version} ({utils.RKTOOL})"
        checks.append((True, "wizard_tool_ok", found, None))
    else:
        checks.append((False, "wizard_tool_missing", utils.RKTOOL, None))
    if sys.platform.startswith("linux"):
        if udev_rule_installed():
            checks.append((True, "wizard_usb_ok", "", None))
        else:
            checks.append((False, "wizard_usb_missing", "", utils.udev_fix_command()))
    return checks


def _has_module(name):
    return importlib.util.find_spec(f"{__package__}.{name}") is not None


def _label():
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    return label


class FirstRunWizard(QWizard):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        # 1. Setup
        self.check_page = QWizardPage()
        layout = QVBoxLayout(self.check_page)
        self.check_intro = _label()
        layout.addWidget(self.check_intro)
        self.check_lines = []
        for ok, key, argument, command in setup_checks():
            line = _label()
            layout.addWidget(line)
            self.check_lines.append((line, ok, key, argument))
            if command:
                fix = QLineEdit(command)
                fix.setReadOnly(True)
                fix.setCursorPosition(0)
                layout.addWidget(fix)
        layout.addStretch(1)
        self.addPage(self.check_page)

        # 2. Language and look, straight onto the status-bar pickers so
        # everything else follows (this wizard included).
        self.look_page = QWizardPage()
        layout = QVBoxLayout(self.look_page)
        self.look_note = _label()
        layout.addWidget(self.look_note)
        form = QFormLayout()
        layout.addLayout(form)
        layout.addStretch(1)
        self.language = self._mirror(gui.lang_combo)
        self.theme = self._mirror(gui.theme_combo)
        self.language_label, self.theme_label = QLabel(), QLabel()
        form.addRow(self.language_label, self.language)
        form.addRow(self.theme_label, self.theme)
        self.addPage(self.look_page)

        # 3. How a flash goes
        self.start_page = QWizardPage()
        layout = QVBoxLayout(self.start_page)
        self.start_text = _label()
        self.start_text.linkActivated.connect(safe_slot(lambda _link: self._maskrom_help()))
        layout.addWidget(self.start_text)
        layout.addStretch(1)
        self.addPage(self.start_page)

        self.retranslate()
        gui.lang_combo.currentIndexChanged.connect(self.retranslate)
        self.finished.connect(safe_slot(self._done))
        self.resize(600, 460)

    def _mirror(self, source):
        combo = QComboBox()
        for i in range(source.count()):
            combo.addItem(source.itemText(i), source.itemData(i))
        combo.setCurrentIndex(source.currentIndex())
        combo.currentIndexChanged.connect(safe_slot(source.setCurrentIndex))
        return combo

    def retranslate(self, *_):
        tr = self.gui.tr
        self.setWindowTitle(tr("wizard_title"))
        self.setButtonText(QWizard.WizardButton.NextButton, tr("wizard_next"))
        self.setButtonText(QWizard.WizardButton.BackButton, tr("wizard_back"))
        self.setButtonText(QWizard.WizardButton.FinishButton, tr("wizard_finish"))
        self.setButtonText(QWizard.WizardButton.CancelButton, tr("wizard_skip"))
        self.check_page.setTitle(tr("wizard_check_title"))
        self.check_intro.setText(tr("wizard_check_intro"))
        for line, ok, key, argument in self.check_lines:
            mark = "✓" if ok else "✗"
            line.setText(f"{mark} {tr(key).format(argument)}")
        self.look_page.setTitle(tr("wizard_look_title"))
        self.look_note.setText(tr("wizard_look_note"))
        self.language_label.setText(tr("settings_language"))
        self.theme_label.setText(tr("settings_theme"))
        self.language.setItemText(0, self.gui.lang_combo.itemText(0))
        for i in range(self.theme.count()):
            self.theme.setItemText(i, self.gui.theme_combo.itemText(i))
        self.start_page.setTitle(tr("wizard_start_title"))
        # The Maskrom guide and search are separate features; mention them
        # only when they're in this build.
        self.start_text.setText(tr("wizard_start_html").format(
            maskrom=tr("wizard_maskrom_link") if _has_module("maskrom_help") else "",
            search=tr("wizard_search_tip") if _has_module("search") else ""))

    def _maskrom_help(self):
        from .maskrom_help import show_maskrom_help
        show_maskrom_help(self.gui)

    def _done(self, _result):
        # Finished or skipped, it doesn't come back by itself.
        self.gui.settings.set(app_settings.KEY_FIRST_RUN_DONE, "1")
        try:
            self.gui.lang_combo.currentIndexChanged.disconnect(self.retranslate)
        except (RuntimeError, TypeError):
            pass


def maybe_show(gui):
    """Open the wizard on the first run."""
    if os.environ.get(NO_WIZARD_ENV) or gui.settings.get_flag(app_settings.KEY_FIRST_RUN_DONE):
        return None
    return show(gui)


def show(gui):
    wizard = FirstRunWizard(gui)
    wizard.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    wizard.setWindowModality(Qt.WindowModality.WindowModal)
    wizard.open()
    return wizard
