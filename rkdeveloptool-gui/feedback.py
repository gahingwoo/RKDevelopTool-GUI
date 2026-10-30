"""
Report a problem on GitHub: a dialog that shows what will be sent, lets the
user edit it, then opens the repository's bug form in the browser with the
fields filled in. Nothing is sent from the app itself; the user submits the
issue from their own GitHub account.
"""
import os
import platform
import re
from urllib.parse import urlencode

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout,
)

from . import __version__

NEW_ISSUE = "https://github.com/gahingwoo/RKDevelopTool-GUI/issues/new"
TEMPLATE = "bug_report.yml"
LOG_LINES = 60
# GitHub refuses very long URLs; leave room below its ~8 KB limit.
MAX_URL = 7000


def redact(text):
    """Hide the user's home directory and account name."""
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "~")
    user = os.path.basename(home)
    if len(user) > 2:
        text = re.sub(r"\b%s\b" % re.escape(user), "<user>", text)
    return text


def os_description():
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
    try:
        with open("/etc/os-release") as f:
            info = dict(line.rstrip().split("=", 1) for line in f if "=" in line)
        name = info.get("PRETTY_NAME", "").strip('"')
    except OSError:
        name = ""
    return f"{name or platform.system()} ({platform.machine()})"


def gather(gui, problem="", log=None):
    """The form's fields for the window's current state."""
    from . import updater
    from .operations import get_rkdeveloptool_version, loader_chip
    if log is None:
        log = gui.log_output.toPlainText() if hasattr(gui, "log_output") else ""
    log = "\n".join(log.strip().splitlines()[-LOG_LINES:])
    image = ""
    for attr in ("firmware_path", "image_path"):
        field = getattr(gui, attr, None)
        if field is not None and field.text().strip():
            image = os.path.basename(field.text().strip())
            break
    try:
        tool = get_rkdeveloptool_version() or ""
    except Exception:
        tool = ""
    return {
        "what-happened": problem,
        "chip": loader_chip(gui) or "",
        "image": image,
        "app-version": __version__,
        "os": os_description(),
        "install": updater.install_kind(),
        "rkdeveloptool": tool,
        "log": redact(log),
    }


def issue_url(title, fields):
    """The prefilled form URL, with the log trimmed from the top to fit."""
    fields = dict(fields)
    while True:
        query = {"template": TEMPLATE, "title": title}
        query.update({k: v for k, v in fields.items() if v})
        url = NEW_ISSUE + "?" + urlencode(query)
        if len(url) <= MAX_URL or not fields.get("log"):
            return url
        lines = fields["log"].splitlines()
        fields["log"] = "\n".join(lines[max(1, len(lines) // 4):]) if len(lines) > 1 else ""


class ReportDialog(QDialog):
    """Shows what goes into the report and lets the user change it."""

    def __init__(self, gui, title="", problem="", log=None):
        super().__init__(gui)
        tr = gui.tr
        self.setWindowTitle(tr("report_title"))
        self.fields = gather(gui, problem, log)
        layout = QVBoxLayout(self)
        intro = QLabel(tr("report_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.title = QLineEdit(title)
        self.board = QLineEdit()
        self.board.setPlaceholderText(tr("report_board_hint"))
        self.problem = QPlainTextEdit(problem)
        self.problem.setPlaceholderText(tr("report_problem_hint"))
        self.problem.setFixedHeight(90)
        self.log = QPlainTextEdit(self.fields["log"])
        form.addRow(tr("report_issue_title"), self.title)
        form.addRow(tr("report_board"), self.board)
        form.addRow(tr("report_problem"), self.problem)
        f = self.fields
        details = " · ".join(x for x in (
            f["chip"], f"RKDevelopTool GUI {f['app-version']}", f["os"],
            tr("report_installed_from").format(f["install"]),
            f"rkdeveloptool {f['rkdeveloptool']}" if f["rkdeveloptool"] else "") if x)
        detail_label = QLabel(details)
        detail_label.setWordWrap(True)
        form.addRow(tr("report_details"), detail_label)
        form.addRow(tr("report_log"), self.log)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel_btn"))
        self.open_button = buttons.addButton(tr("report_open"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(640, 560)

    def url(self):
        fields = dict(self.fields)
        fields.update({"board": self.board.text().strip(),
                       "what-happened": self.problem.toPlainText().strip(),
                       "log": self.log.toPlainText().strip()})
        return issue_url(self.title.text().strip() or "Problem report", fields)


def report_problem(gui, title="", problem="", log=None):
    """Open the report dialog; on OK, open the prefilled GitHub form."""
    dialog = ReportDialog(gui, title, problem, log)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        QDesktopServices.openUrl(QUrl(dialog.url()))
        return True
    return False
