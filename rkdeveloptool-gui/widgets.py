"""
Custom widgets for RKDevelopTool GUI
"""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QComboBox, QTabWidget


class CurrentPageTabWidget(QTabWidget):
    """QTabWidget sized by its current page, not its tallest one.

    QTabWidget.sizeHint() is the largest sizeHint of all pages, whatever
    their size policies, so the short Home tab asked for the height of the
    Advanced tab. The surplus went to the tab area instead of the log below
    it, and when space was short the log was squeezed to its minimum.
    """

    def _chrome(self, page):
        """Tab bar and frame: what the minimum adds on top of the page's."""
        outer, inner = super().minimumSizeHint(), page.minimumSizeHint()
        return max(outer.width() - inner.width(), 0), max(outer.height() - inner.height(), 0)

    def sizeHint(self):
        hint = super().sizeHint()
        page = self.currentWidget()
        if page is None:
            return hint
        return QSize(hint.width(), page.sizeHint().height() + self._chrome(page)[1])

    def heightForWidth(self, width):
        # Pages with word-wrapped labels make the whole column height-for-
        # width, and then the scroll area sizes it from this - which Qt also
        # takes from the tallest page, pushing the log off the bottom.
        page = self.currentWidget()
        if page is None:
            return super().heightForWidth(width)
        chrome_w, chrome_h = self._chrome(page)
        height = page.heightForWidth(width - chrome_w) if page.hasHeightForWidth() else -1
        if height < 0:
            height = page.sizeHint().height()
        return height + chrome_h


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