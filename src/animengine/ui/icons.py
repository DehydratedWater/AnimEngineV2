"""Programmatically drawn toolbar icons (no asset files needed).

Each glyph is painted with QPainter at the requested size; light strokes on
transparent background so they read on the dark toolbar.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

FG = QColor(225, 225, 230)
ACCENT = QColor(255, 200, 60)
BLUE = QColor(110, 170, 255)
RED = QColor(235, 100, 100)


def _pen(color=FG, width=1.8) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _dot(p: QPainter, x: float, y: float, r: float = 2.0, color=ACCENT) -> None:
    p.setPen(QPen(QColor(40, 40, 40), 0.8))
    p.setBrush(color)
    p.drawEllipse(QPointF(x, y), r, r)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_select(p: QPainter, s: float) -> None:
    pen = _pen()
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawRect(QRectF(s * .12, s * .12, s * .55, s * .55))
    # cursor arrow
    path = QPainterPath(QPointF(s * .5, s * .45))
    path.lineTo(s * .88, s * .72)
    path.lineTo(s * .68, s * .76)
    path.lineTo(s * .78, s * .95)
    path.lineTo(s * .70, s * .98)
    path.lineTo(s * .60, s * .80)
    path.lineTo(s * .48, s * .92)
    path.closeSubpath()
    p.setPen(QPen(QColor(40, 40, 40), 1))
    p.setBrush(FG)
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_line(p: QPainter, s: float) -> None:
    p.setPen(_pen(width=2.2))
    p.drawLine(QPointF(s * .15, s * .85), QPointF(s * .85, s * .15))
    _dot(p, s * .15, s * .85)
    _dot(p, s * .85, s * .15)


def _draw_rect(p: QPainter, s: float) -> None:
    p.setPen(_pen(width=2.0))
    p.drawRect(QRectF(s * .15, s * .22, s * .7, s * .56))
    for x, y in [(.15, .22), (.85, .22), (.85, .78), (.15, .78)]:
        _dot(p, s * x, s * y)


def _draw_curve(p: QPainter, s: float) -> None:
    path = QPainterPath(QPointF(s * .12, s * .82))
    path.cubicTo(QPointF(s * .30, s * .15), QPointF(s * .70, s * .90),
                 QPointF(s * .88, s * .20))
    p.setPen(_pen(width=2.2))
    p.drawPath(path)
    p.setPen(_pen(QColor(120, 220, 120), 1.0))
    p.drawLine(QPointF(s * .12, s * .82), QPointF(s * .30, s * .15))
    _dot(p, s * .30, s * .15, 1.8, QColor(120, 220, 120))
    _dot(p, s * .12, s * .82)
    _dot(p, s * .88, s * .20)


def _draw_pen(p: QPainter, s: float) -> None:
    path = QPainterPath(QPointF(s * .12, s * .85))
    for x, y in [(.32, .45), (.52, .70), (.70, .30), (.88, .50)]:
        path.lineTo(s * x, s * y)
    p.setPen(_pen(width=2.0))
    p.drawPath(path)
    for x, y in [(.12, .85), (.32, .45), (.52, .70), (.70, .30), (.88, .50)]:
        _dot(p, s * x, s * y, 1.6)


def _draw_smoothpen(p: QPainter, s: float) -> None:
    path = QPainterPath(QPointF(s * .10, s * .70))
    path.cubicTo(QPointF(s * .30, s * .20), QPointF(s * .45, s * .95),
                 QPointF(s * .65, s * .45))
    path.cubicTo(QPointF(s * .78, s * .15), QPointF(s * .85, s * .35),
                 QPointF(s * .92, s * .30))
    p.setPen(_pen(width=2.2))
    p.drawPath(path)


def _draw_fill(p: QPainter, s: float) -> None:
    # tilted bucket
    p.save()
    p.translate(s * .45, s * .48)
    p.rotate(-30)
    p.setPen(_pen(width=1.8))
    p.setBrush(QColor(90, 90, 100))
    p.drawRect(QRectF(-s * .18, -s * .16, s * .36, s * .34))
    p.restore()
    # pouring paint
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(BLUE)
    drop = QPainterPath(QPointF(s * .72, s * .55))
    drop.cubicTo(QPointF(s * .62, s * .72), QPointF(s * .82, s * .72),
                 QPointF(s * .72, s * .55))
    p.drawPath(drop)
    p.drawEllipse(QPointF(s * .72, s * .78), s * .10, s * .07)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_addpoint(p: QPainter, s: float) -> None:
    p.setPen(_pen(width=2.0))
    p.drawLine(QPointF(s * .12, s * .70), QPointF(s * .88, s * .40))
    _dot(p, s * .5, s * .55, 2.4)
    p.setPen(_pen(ACCENT, 1.8))
    p.drawLine(QPointF(s * .72, s * .12), QPointF(s * .72, s * .32))
    p.drawLine(QPointF(s * .62, s * .22), QPointF(s * .82, s * .22))


def _draw_cut(p: QPainter, s: float) -> None:
    p.setPen(_pen(width=1.8))
    p.drawLine(QPointF(s * .25, s * .15), QPointF(s * .70, s * .80))
    p.drawLine(QPointF(s * .70, s * .15), QPointF(s * .25, s * .80))
    p.drawEllipse(QPointF(s * .20, s * .88), s * .09, s * .09)
    p.drawEllipse(QPointF(s * .75, s * .88), s * .09, s * .09)
    p.setPen(_pen(RED, 1.4))
    p.drawLine(QPointF(s * .88, s * .30), QPointF(s * .88, s * .60))


def _draw_style(p: QPainter, s: float) -> None:
    p.setPen(_pen(BLUE, 4.0))
    p.drawLine(QPointF(s * .15, s * .30), QPointF(s * .85, s * .30))
    p.setPen(_pen(width=1.6))
    p.drawLine(QPointF(s * .15, s * .72), QPointF(s * .85, s * .72))
    p.setPen(_pen(ACCENT, 1.6))
    p.drawLine(QPointF(s * .5, s * .40), QPointF(s * .5, s * .62))
    p.drawLine(QPointF(s * .42, s * .54), QPointF(s * .5, s * .62))
    p.drawLine(QPointF(s * .58, s * .54), QPointF(s * .5, s * .62))


def _draw_picker(p: QPainter, s: float) -> None:
    # eyedropper
    p.setPen(_pen(width=2.0))
    p.drawLine(QPointF(s * .30, s * .70), QPointF(s * .68, s * .32))
    p.setPen(_pen(width=5.0))
    p.drawLine(QPointF(s * .66, s * .34), QPointF(s * .80, s * .20))
    p.setPen(_pen(BLUE, 2.0))
    p.drawLine(QPointF(s * .30, s * .70), QPointF(s * .18, s * .82))
    p.setPen(_pen(width=1.4))
    p.drawLine(QPointF(s * .12, s * .90), QPointF(s * .88, s * .90))


def _draw_eraser(p: QPainter, s: float) -> None:
    p.save()
    p.translate(s * .5, s * .5)
    p.rotate(-35)
    p.setPen(_pen(width=1.6))
    p.setBrush(QColor(230, 130, 160))
    p.drawRoundedRect(QRectF(-s * .28, -s * .16, s * .34, s * .32), 2, 2)
    p.setBrush(FG)
    p.drawRect(QRectF(s * .06, -s * .16, s * .22, s * .32))
    p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(QColor(150, 150, 160), 1.2))
    p.drawLine(QPointF(s * .15, s * .88), QPointF(s * .85, s * .88))


def _draw_brush(p: QPainter, s: float) -> None:
    p.setPen(_pen(width=2.0))
    p.drawLine(QPointF(s * .70, s * .15), QPointF(s * .45, s * .48))
    ferrule = QPainterPath(QPointF(s * .45, s * .48))
    ferrule.cubicTo(QPointF(s * .20, s * .60), QPointF(s * .35, s * .85),
                    QPointF(s * .18, s * .88))
    ferrule.cubicTo(QPointF(s * .45, s * .92), QPointF(s * .50, s * .62),
                    QPointF(s * .52, s * .55))
    ferrule.closeSubpath()
    p.setPen(QPen(QColor(40, 40, 40), 0.8))
    p.setBrush(BLUE)
    p.drawPath(ferrule)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_rerase(p: QPainter, s: float) -> None:
    # checkerboard = transparency
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(4):
        for j in range(4):
            if (i + j) % 2 == 0:
                p.setBrush(QColor(120, 120, 130))
                p.drawRect(QRectF(s * (.12 + i * .10), s * (.55 + j * .10),
                                  s * .10, s * .10))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.save()
    p.translate(s * .58, s * .38)
    p.rotate(-35)
    p.setPen(_pen(width=1.6))
    p.setBrush(QColor(230, 130, 160))
    p.drawRoundedRect(QRectF(-s * .24, -s * .14, s * .30, s * .28), 2, 2)
    p.setBrush(FG)
    p.drawRect(QRectF(s * .06, -s * .14, s * .18, s * .28))
    p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_rmove(p: QPainter, s: float) -> None:
    p.setPen(_pen(width=1.6))
    p.drawRect(QRectF(s * .18, s * .18, s * .45, s * .45))
    p.setPen(_pen(QColor(150, 150, 160), 1.2))
    p.drawEllipse(QPointF(s * .34, s * .34), s * .06, s * .06)
    p.drawLine(QPointF(s * .22, s * .58), QPointF(s * .40, s * .40))
    # move arrows
    p.setPen(_pen(ACCENT, 1.8))
    c = QPointF(s * .70, s * .70)
    for dx, dy in [(.16, 0), (-.16, 0), (0, .16), (0, -.16)]:
        tip = QPointF(c.x() + s * dx, c.y() + s * dy)
        p.drawLine(c, tip)
        nx, ny = dx / abs(dx or 1) if dx else 0, dy / abs(dy or 1) if dy else 0
        p.drawLine(tip, QPointF(tip.x() - s * .05 * (nx or 1) + s * .05 * ny * 0,
                                tip.y() - s * .05 * (ny or 1)))


_DRAWERS = {
    "select": _draw_select,
    "line": _draw_line,
    "rect": _draw_rect,
    "curve": _draw_curve,
    "pen": _draw_pen,
    "smoothpen": _draw_smoothpen,
    "fill": _draw_fill,
    "addpoint": _draw_addpoint,
    "cut": _draw_cut,
    "style": _draw_style,
    "picker": _draw_picker,
    "eraser": _draw_eraser,
    "brush": _draw_brush,
    "rerase": _draw_rerase,
    "rmove": _draw_rmove,
}

_cache: dict[tuple[str, int], QIcon] = {}


def tool_icon(name: str, size: int = 28) -> QIcon:
    key = (name, size)
    if key in _cache:
        return _cache[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    drawer = _DRAWERS.get(name)
    if drawer is not None:
        drawer(painter, float(size))
    painter.end()
    icon = QIcon(pm)
    _cache[key] = icon
    return icon
