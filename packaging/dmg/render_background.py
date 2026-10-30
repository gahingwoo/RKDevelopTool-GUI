"""Draw the DMG window's background (1x and 2x PNG).

    python packaging/dmg/render_background.py OUT_DIR

The window is 660x500 points; the app icon sits at (165, 170), the
Applications link at (495, 170) and the note at (330, 430), as
packaging/make-dmg.sh places them.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt          # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPolygonF  # noqa: E402

W, H = 660, 500


def render(scale):
    image = QImage(W * scale, H * scale, QImage.Format.Format_ARGB32)
    image.fill(QColor("#f5f6f8"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale, scale)
    ink, soft = QColor("#2b2f36"), QColor("#5f6670")

    def text(rect, size, body, color=ink, bold=False):
        font = QFont()
        font.setPixelSize(size)
        font.setBold(bold)
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, body)

    text((0, 22, W, 30), 18, "拖到“应用程序”文件夹来安装 · Drag to Applications to install", bold=True)
    # Arrow from the app to the Applications link.
    pen = QPen(QColor("#9aa3ad"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(255, 170), QPointF(395, 170))
    p.setBrush(QColor("#9aa3ad"))
    p.drawPolygon(QPolygonF([QPointF(405, 170), QPointF(389, 160), QPointF(389, 180)]))

    p.setPen(QPen(QColor("#d9dde2"), 1))
    p.drawLine(QPointF(40, 262), QPointF(W - 40, 262))
    text((30, 274, W - 60, 22), 13, "第一次打开时 macOS 提示无法打开？ · macOS says it can't be opened?", bold=True)
    text((30, 298, W - 60, 48), 12,
         "macOS 15 及以后：系统设置 → 隐私与安全性 → 仍要打开。更早的版本：右键应用 → 打开。\n"
         "macOS 15+: System Settings → Privacy & Security → Open Anyway. Older: right-click → Open.",
         soft)
    text((30, 346, W - 60, 40), 12,
         "只需要第一次；之后应用内更新不会再提示。详见窗口里的说明文件。\n"
         "Only once: the app's own updates don't ask again. See the note in this window.",
         soft)
    p.end()
    return image


def main(out_dir):
    QGuiApplication(sys.argv[:1])
    os.makedirs(out_dir, exist_ok=True)
    render(1).save(os.path.join(out_dir, "background.png"))
    render(2).save(os.path.join(out_dir, "background@2x.png"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
