"""
"How do I get into Maskrom?": the ways to put a Rockchip board into the
mode rkdeveloptool flashes in, and what to check when it doesn't show up.
Board-independent: the button's name and the USB port vary, so the steps
say what to look for rather than naming boards.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout


def show_maskrom_help(gui):
    dialog = QDialog(gui)
    dialog.setWindowTitle(gui.tr("maskrom_help_title"))
    layout = QVBoxLayout(dialog)
    text = QTextBrowser()
    text.setOpenExternalLinks(True)
    text.setHtml(gui.tr("maskrom_help_html"))
    layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.button(QDialogButtonBox.StandardButton.Close).setText(gui.tr("update_close"))
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(600, 560)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()
    return dialog
