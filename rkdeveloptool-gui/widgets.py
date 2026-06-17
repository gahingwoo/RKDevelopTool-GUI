"""
Custom widgets for RKDevelopTool GUI
"""
from PySide6.QtWidgets import QComboBox


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
                self._on_open()
        except Exception:
            pass
        super().showPopup()