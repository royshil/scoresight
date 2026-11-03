"""Renders a release's square social post (1080x1080 PNG) for YouTube posts,
LinkedIn, X and the like: the logo, NEW RELEASE, the version in large amber,
a tagline, four items (a title and a line under it) and the footer.

    python brand/release_post.py --tagline "Your phone is the camera." \\
        --item "Phone camera" "Scan a QR code: your phone streams to ScoreSight, no app" \\
        --item ... (four in all) -o scoresight-0.4.3-post.png

--version defaults to src/version.py. Fails if a line is too long for the
picture. PySide6 only (any venv of the app).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

W = H = 1080
LEFT = 85
FOOTER_TOP = 993
TEXT_RIGHT = W - 40
FOOTER_LEFT = "Free and open source · Windows · macOS · Linux"
FOOTER_RIGHT = "github.com/royshil/scoresight"


def app_version() -> str:
    text = (ROOT / "src" / "version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def render(path: Path, version: str, tagline: str, items: list[tuple[str, str]]):
    import scoresight_brand as brand
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (
        QBrush,
        QFontMetricsF,
        QLinearGradient,
        QPainterPath,
        QPen,
        QRadialGradient,
    )

    tagline_font = brand.font(40, "bold", brand.TEXT_FONT)
    title_font = brand.font(34, "bold", brand.TEXT_FONT)
    sub_font = brand.font(23, "regular", brand.TEXT_FONT)
    too_long = [
        text
        for font, x, texts in (
            (tagline_font, LEFT, [tagline]),
            (title_font, LEFT + 32, [t for t, _ in items]),
            (sub_font, LEFT + 32, [s for _, s in items]),
        )
        for text in texts
        if x + QFontMetricsF(font).horizontalAdvance(text) > TEXT_RIGHT
    ]
    if too_long:
        sys.exit("Too long for the picture, shorten: " + " | ".join(too_long))

    def draw(p):
        # The social preview's background: gradient, blue glow, amber dots.
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0, brand.color(brand.INK_3))
        g.setColorAt(1, brand.color(brand.INK))
        p.fillRect(QRectF(0, 0, W, H), QBrush(g))
        glow = QRadialGradient(QPointF(W * 0.78, H * 0.3), W * 0.55)
        glow.setColorAt(0, brand.color(brand.BLUE, 0.14))
        glow.setColorAt(1, brand.color(brand.BLUE, 0.0))
        p.fillRect(QRectF(0, 0, W, H), QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        for y in range(14, 620, 22):
            for x in range(W // 2, W, 22):
                fx = (x - W / 2) / (W / 2)
                fy = max(0.0, 1 - y / 620)
                p.setBrush(brand.color(brand.AMBER, 0.015 + 0.06 * fx * fy))
                p.drawEllipse(QPointF(x, y), 2.2, 2.2)

        brand.draw_lockup(p, LEFT, 80, 92)

        p.setPen(brand.color(brand.BLUE))
        p.setFont(brand.font(29, "bold", brand.TEXT_FONT, spacing=5.5))
        p.drawText(
            QRectF(LEFT + 3, 236, 600, 44), Qt.AlignmentFlag.AlignVCenter, "NEW RELEASE"
        )

        # The version: amber, with a glow. A longer one (0.10.12) gets smaller.
        size = 262
        f = brand.font(size, "black", brand.TEXT_FONT, italic=True, spacing=-4)
        while QFontMetricsF(f).horizontalAdvance(version) > W - 2 * LEFT and size > 120:
            size -= 6
            f = brand.font(size, "black", brand.TEXT_FONT, italic=True, spacing=-4)
        number = QPainterPath()
        number.addText(QPointF(LEFT - 8, 475), f, version)
        for width, alpha in ((34, 0.05), (22, 0.08), (12, 0.14)):
            p.strokePath(
                number,
                QPen(
                    brand.color(brand.AMBER, alpha),
                    width,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                ),
            )
        fill = QLinearGradient(0, 300, 0, 480)
        fill.setColorAt(0, brand.color(brand.AMBER_HOT))
        fill.setColorAt(1, brand.color(brand.AMBER))
        p.fillPath(number, QBrush(fill))

        p.setPen(brand.color(brand.WHITE))
        p.setFont(tagline_font)
        p.drawText(QRectF(LEFT, 512, 950, 56), Qt.AlignmentFlag.AlignVCenter, tagline)

        y = 610
        for title, sub in items:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(brand.color(brand.AMBER))
            p.drawRoundedRect(QRectF(LEFT, y + 2, 7, 64), 3.5, 3.5)
            p.setPen(brand.color(brand.WHITE))
            p.setFont(title_font)
            p.drawText(
                QRectF(LEFT + 32, y - 4, 950, 42), Qt.AlignmentFlag.AlignVCenter, title
            )
            p.setPen(brand.color(brand.MUTED))
            p.setFont(sub_font)
            p.drawText(
                QRectF(LEFT + 32, y + 38, 950, 32), Qt.AlignmentFlag.AlignVCenter, sub
            )
            y += 100

        p.fillRect(
            QRectF(0, FOOTER_TOP, W, H - FOOTER_TOP), brand.color(brand.INK, 0.75)
        )
        p.fillRect(QRectF(0, FOOTER_TOP, W, 1), brand.color("#FFFFFF", 0.05))
        p.setPen(brand.color(brand.MUTED))
        p.setFont(brand.font(24, "regular", brand.TEXT_FONT))
        p.drawText(
            QRectF(LEFT, FOOTER_TOP, 700, H - FOOTER_TOP),
            Qt.AlignmentFlag.AlignVCenter,
            FOOTER_LEFT,
        )
        p.setPen(brand.color(brand.WHITE))
        p.setFont(brand.font(27, "semibold", brand.TEXT_FONT))
        p.drawText(
            QRectF(0, FOOTER_TOP, W - LEFT, H - FOOTER_TOP),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            FOOTER_RIGHT,
        )

    brand.render_png(path, W, H, draw)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=None, help="default: src/version.py")
    parser.add_argument("--tagline", required=True)
    parser.add_argument(
        "--item",
        nargs=2,
        action="append",
        required=True,
        metavar=("TITLE", "LINE"),
        help="four times: a title and the line under it",
    )
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.item) != 4:
        parser.error(f"give four --item, not {len(args.item)}")

    from PySide6.QtGui import QGuiApplication

    import scoresight_brand as brand

    app = QGuiApplication(sys.argv[:1])  # noqa: F841 (fonts need it)
    brand.load_fonts()
    render(args.output, args.version or app_version(), args.tagline, args.item)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
