"""
Search the window's controls: type what you want to do ("刷机", "erase",
"loader", "备份") and jump to the button, checkbox or setting that does it.

The index is built from the window itself: every button, checkbox and group
box on the tabs, the left panel and the Settings page, under its text in
both languages (the same translation key, looked up in each language), its
tooltip, and a few everyday words a newcomer might use instead of the
app's own. Choosing a result switches to its page, scrolls it into view and
flashes it; it never presses anything.
"""
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QGraphicsDropShadowEffect, QGroupBox, QLineEdit,
    QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QWidget,
)

from .i18n import TRANSLATIONS

# Words that mean the same thing to someone new to this.
SYNONYMS = [
    {"刷机", "烧录", "写入", "flash", "burn", "write", "install"},
    {"擦除", "清空", "格式化", "erase", "wipe", "format"},
    {"备份", "导出", "读出", "backup", "dump", "export", "save"},
    {"loader", "引导", "bootloader", "miniloader", "spl", "db"},
    {"maskrom", "救砖", "变砖", "recovery", "brick", "unbrick", "rescue"},
    {"分区", "gpt", "parameter", "partition", "mtdparts", "ppt"},
    {"重启", "reset", "reboot", "restart"},
    {"更新", "升级", "update", "upgrade"},
    {"设置", "偏好", "settings", "preferences", "options"},
    {"日志", "log", "logs"},
    {"历史", "记录", "history"},
    {"批量", "流水线", "量产", "production", "mass", "batch", "line"},
    {"芯片", "型号", "chip"},
    {"存储", "emmc", "sd", "spi", "nor", "storage"},
    {"命令", "终端", "command", "terminal"},
    {"校验", "验证", "verify", "check", "md5", "checksum"},
    {"字体", "字号", "font", "size"},
    {"主题", "深色", "浅色", "dark", "light", "theme"},
    {"语言", "language", "中文", "english"},
    {"反馈", "报告", "问题", "bug", "issue", "report", "feedback"},
    {"镜像", "固件", "image", "firmware", "img"},
]

MAX_RESULTS = 12
FLASH_MS = 1800


def _clean(text):
    return (text or "").replace("&", "").replace("…", "").strip()


def _other_languages(text, lang):
    """The same string in the other languages, via its translation key."""
    keys = [k for k, v in TRANSLATIONS.get(lang, {}).items() if isinstance(v, str) and _clean(v) == text]
    out = []
    for other, table in TRANSLATIONS.items():
        if other != lang:
            out += [_clean(table[k]) for k in keys if isinstance(table.get(k), str)]
    return out


class Entry:
    def __init__(self, widget, label, page_index, page_name, haystack):
        self.widget, self.label = widget, label
        self.page_index, self.page_name = page_index, page_name
        self.haystack = haystack          # lower-cased texts to match against


def build_index(gui):
    """Entries for the window's visible controls, in tab order."""
    tabs = gui.tab_widget
    lang = getattr(gui.manager, "lang", "en") if hasattr(gui, "manager") else "en"
    places = [(i, tabs.widget(i), _clean(tabs.tabText(i))) for i in range(tabs.count())]
    if getattr(gui, "left_panel", None) is not None:
        places.append((None, gui.left_panel, ""))
    entries, seen = [], set()
    for index, page, page_name in places:
        for widget in page.findChildren(QAbstractButton) + page.findChildren(QGroupBox):
            full = _clean(widget.title() if isinstance(widget, QGroupBox) else widget.text())
            label = full.split("\n")[0].strip()     # cards: title, then a description
            if len(label) < 2 or not widget.isVisibleTo(page) or (label, index) in seen:
                continue
            seen.add((label, index))
            texts = [label, full, page_name] + _other_languages(full, lang)
            tip = widget.property("baseTip") or widget.toolTip()
            if tip:
                texts.append(tip)
            entries.append(Entry(widget, label, index, page_name, [t.lower() for t in texts if t]))
    return entries


def _expand(token):
    """The token and any everyday words grouped with it."""
    words = {token}
    for group in SYNONYMS:
        if token in group or any(token in w for w in group if len(token) >= 2):
            words |= group
    return words


def search(entries, query):
    """Best matches first: every word of the query must match the entry's
    texts directly or through a synonym."""
    tokens = [t for t in query.lower().split() if t]
    if not tokens:
        return []
    scored = []
    for entry in entries:
        label = entry.haystack[0]
        score = 0
        for token in tokens:
            if label.startswith(token):
                score += 6
            elif token in label:
                score += 4
            elif any(token in h for h in entry.haystack[1:]):
                score += 2
            elif any(w in label for w in _expand(token)):
                score += 2
            elif any(w in h for w in _expand(token) for h in entry.haystack[1:]):
                score += 1
            else:
                score = 0
                break
        if score:
            scored.append((-score, len(label), entry))
    scored.sort(key=lambda s: (s[0], s[1]))
    return [entry for _, _, entry in scored[:MAX_RESULTS]]


class Flash(QWidget):
    """A highlight drawn over a control: an accent-coloured frame and a
    light fill that blink a few times and go. Painted on top rather than
    set as a style sheet, which native macOS buttons barely show."""

    BLINKS = 3

    def __init__(self, target):
        super().__init__(target.parentWidget())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._target = target
        self._ticks = 0
        # The page may still be laying out after the tab switch: follow it.
        target.installEventFilter(self)
        self._place()
        self.show()
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(FLASH_MS // (self.BLINKS * 2))

    def _place(self):
        self.setGeometry(self._target.geometry().adjusted(-5, -5, 5, 5))
        self.raise_()

    def eventFilter(self, obj, event):
        if obj is self._target and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._place()
        return False

    def _tick(self):
        self._ticks += 1
        if self._ticks >= self.BLINKS * 2:
            self.deleteLater()
            return
        self.setVisible(self._ticks % 2 == 0)

    def paintEvent(self, event):
        color = self.palette().color(QPalette.ColorRole.Highlight)
        if self.palette().color(QPalette.ColorRole.Window).lightness() < 128:
            color = color.lighter(170)      # dark themes use a deep blue
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(color)
        fill.setAlpha(60)
        painter.setBrush(fill)
        painter.setPen(QPen(color, 3))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 6, 6)


def reveal(gui, entry):
    """Go to the entry's page, scroll it into view and flash it."""
    widget = entry.widget
    if entry.page_index is not None:
        gui.tab_widget.setCurrentIndex(entry.page_index)
    Flash(widget)

    def scroll():
        # Once the new page has its layout, or it scrolls to stale places.
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget, 50, 80)
            parent = parent.parentWidget()

    QTimer.singleShot(0, widget, scroll)
    if widget.isEnabled() and widget.focusPolicy() != Qt.FocusPolicy.NoFocus:
        widget.setFocus(Qt.FocusReason.ShortcutFocusReason)


class SearchPalette(QFrame):
    """The search box: opened with Ctrl/Cmd+K or the status-bar button,
    over the top of the window, with the results listed under the field.
    Enter or a click opens a result; Escape, a click elsewhere or moving
    the focus away closes it.

    It's a panel inside the main window, not a popup window of its own:
    macOS gives a Qt.Popup window no input method, so Chinese (pinyin)
    couldn't be typed into it."""

    WIDTH = 520

    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.hide()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.field = QLineEdit()
        self.field.setClearButtonEnabled(True)
        self.results = QListWidget()
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # typing stays in the field
        self.results.hide()
        layout.addWidget(self.field)
        layout.addWidget(self.results)
        self.results.itemClicked.connect(self._open)
        self.field.textChanged.connect(self._update)
        self.field.returnPressed.connect(lambda: self._open(self.results.currentItem()))
        self.field.installEventFilter(self)
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self._index = None

    def open(self):
        self._index = None              # the window may have changed
        self.field.clear()
        self._update("")
        self.move((self.gui.width() - self.WIDTH) // 2, 60)
        # Watch clicks elsewhere only while open: an application-wide
        # filter sees every event.
        QApplication.instance().installEventFilter(self)
        self.show()
        self.raise_()
        self.field.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def _focus_changed(self, _old, new):
        if self.isVisible() and (new is None or not self.isAncestorOf(new)):
            self.hide()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and self.isVisible() and isinstance(obj, QWidget) \
                and obj.window() is self.gui and obj is not self and not self.isAncestorOf(obj):
            self.hide()                 # a click elsewhere in the window
            return False
        if obj is self.field and kind == QEvent.Type.ShortcutOverride \
                and event.key() == Qt.Key.Key_Escape:
            event.accept()              # Escape closes search, not the window's Cancel
            return True
        if obj is self.field and kind == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.results.count():
                row = self.results.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                self.results.setCurrentRow(max(0, min(row, self.results.count() - 1)))
                return True
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return QObject.eventFilter(self, obj, event)

    def matches(self, text):
        if self._index is None:
            self._index = build_index(self.gui)
        return search(self._index, text)

    def _update(self, text):
        found = self.matches(text) if text.strip() else []
        self.results.clear()
        for entry in found:
            where = entry.page_name or self.gui.tr("search_left_panel")
            item = QListWidgetItem(self.gui.tr("search_result").format(entry.label, where))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.results.addItem(item)
        if not found and text.strip():
            self.results.addItem(self.gui.tr("search_nothing"))
            self.results.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        self.results.setVisible(self.results.count() > 0)
        if self.results.count():
            self.results.setCurrentRow(0)
            rows = min(self.results.count(), MAX_RESULTS)
            self.results.setFixedHeight(rows * self.results.sizeHintForRow(0) + 6)
        self.setFixedWidth(self.WIDTH)
        self.adjustSize()

    def _open(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if entry is None:
            return
        self.hide()
        reveal(self.gui, entry)
