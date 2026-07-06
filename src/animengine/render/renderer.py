"""Headless frame renderer.

Renders Document frames to QImage via QPainter — no window required (works
with the offscreen Qt platform), so the GUI canvas, exporters, tests and the
MCP server all share identical output.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)

from animengine.core import Color, ConnKind, Document, Placement, RasterImage, Shape
from animengine.core.layers import RasterLayer, VectorLayer

_app: QGuiApplication | None = None


def ensure_gui_app() -> QGuiApplication:
    """Create a (possibly offscreen) QGuiApplication if none exists yet."""
    global _app
    app = QGuiApplication.instance()
    if app is None:
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QGuiApplication(sys.argv[:1])
        app = _app
    return app


def qcolor(c: Color) -> QColor:
    return QColor(c.r, c.g, c.b, c.a)


def qimage_from_raster(img: RasterImage) -> QImage:
    h, w = img.pixels.shape[:2]
    buf = np.ascontiguousarray(img.pixels)
    qimg = QImage(buf.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return qimg.copy()  # detach from the numpy buffer


def raster_from_qimage(qimg: QImage) -> np.ndarray:
    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    arr = np.frombuffer(ptr, np.uint8, count=h * qimg.bytesPerLine()).reshape(
        h, qimg.bytesPerLine()
    )[:, : w * 4]
    return arr.reshape(h, w, 4).copy()


# --------------------------------------------------------------- paths
def connection_path(shape: Shape, conn_id: int) -> QPainterPath:
    conn = shape.connections[conn_id]
    a, b = shape.pos(conn.p1), shape.pos(conn.p2)
    path = QPainterPath()
    path.moveTo(a.x, a.y)
    if conn.kind is ConnKind.LINE:
        path.lineTo(b.x, b.y)
    elif conn.kind is ConnKind.QUAD:
        c = shape.pos(conn.c1)
        path.quadTo(c.x, c.y, b.x, b.y)
    else:
        c1, c2 = shape.pos(conn.c1), shape.pos(conn.c2)
        path.cubicTo(c1.x, c1.y, c2.x, c2.y, b.x, b.y)
    return path


def _append_loop(path: QPainterPath, shape: Shape, loop) -> None:
    first = True
    for e in loop:
        conn = shape.connections.get(e.conn_id)
        if conn is None:
            return
        p_from = conn.p2 if e.reversed else conn.p1
        p_to = conn.p1 if e.reversed else conn.p2
        a, b = shape.pos(p_from), shape.pos(p_to)
        if first:
            path.moveTo(a.x, a.y)
            first = False
        if conn.kind is ConnKind.LINE:
            path.lineTo(b.x, b.y)
        elif conn.kind is ConnKind.QUAD:
            c = shape.pos(conn.c1)
            path.quadTo(c.x, c.y, b.x, b.y)
        else:
            c1, c2 = shape.pos(conn.c1), shape.pos(conn.c2)
            if e.reversed:
                c1, c2 = c2, c1
            path.cubicTo(c1.x, c1.y, c2.x, c2.y, b.x, b.y)
    path.closeSubpath()


def fill_path(shape: Shape, fill) -> QPainterPath | None:
    if any(any(e.conn_id not in shape.connections for e in loop) for loop in fill.loops):
        return None  # boundary connection deleted -> fill invalid
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for loop in fill.loops:
        _append_loop(path, shape, loop)
    return path


# ------------------------------------------------------------ painting
def paint_shape(painter: QPainter, shape: Shape, *, antialias: bool = True,
                stroke_scale: float = 1.0) -> None:
    """Draw one vector shape: fills first, then strokes (v1 draw order)."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, antialias)
    for f in shape.fills.values():
        path = fill_path(shape, f)
        if path is not None:
            painter.fillPath(path, qcolor(f.color))
    for conn in shape.connections.values():
        if conn.only_shape:
            continue
        pen = QPen(qcolor(conn.color), conn.width * stroke_scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(connection_path(shape, conn.id))


def paint_raster(painter: QPainter, image: RasterImage, placement: Placement,
                 *, opacity: float = 1.0) -> None:
    qimg = qimage_from_raster(image)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setOpacity(opacity * placement.opacity)
    t = QTransform()
    cx, cy = image.width / 2, image.height / 2
    # translate to placement position + center, rotate about center, scale
    t.translate(placement.pos.x + cx * placement.scale.x,
                placement.pos.y + cy * placement.scale.y)
    t.rotate(placement.rotation_deg)
    t.scale(placement.scale.x, placement.scale.y)
    t.translate(-cx, -cy)
    painter.setTransform(t, combine=True)
    painter.drawImage(0, 0, qimg)
    painter.restore()


def render_frame(
    doc: Document,
    frame: int,
    *,
    scale: float = 1.0,
    background: Color | None = None,
    transparent: bool = False,
    antialias: bool = True,
) -> QImage:
    """Render one frame of the document at native resolution × scale."""
    ensure_gui_app()
    w = max(1, round(doc.width * scale))
    h = max(1, round(doc.height * scale))
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    if transparent:
        img.fill(Qt.GlobalColor.transparent)
    else:
        bg = background if background is not None else doc.background
        img.fill(qcolor(bg) if bg is not None else Qt.GlobalColor.white)

    painter = QPainter(img)
    try:
        painter.scale(scale, scale)
        paint_document(painter, doc, frame, antialias=antialias)
    finally:
        painter.end()
    return img


def paint_document(painter: QPainter, doc: Document, frame: int, *,
                   antialias: bool = True) -> None:
    """Paint all visible layers of *frame* in draw order (layers[0] = bottom)."""
    for layer in doc.layers:
        if not layer.visible:
            continue
        painter.save()
        painter.setOpacity(layer.opacity)
        if isinstance(layer, VectorLayer):
            shape = layer.shape_at(frame)
            if shape is not None:
                paint_shape(painter, shape, antialias=antialias)
        elif isinstance(layer, RasterLayer):
            state = layer.state_at(frame)
            if state is not None:
                image_id, placement = state
                image = doc.images.get(image_id)
                if image is not None:
                    paint_raster(painter, image, placement, opacity=1.0)
        painter.restore()


def render_frame_png(doc: Document, frame: int, *, scale: float = 1.0,
                     transparent: bool = False) -> bytes:
    """Render a frame and encode it as PNG bytes (for the MCP server / API)."""
    from PySide6.QtCore import QBuffer, QIODevice

    img = render_frame(doc, frame, scale=scale, transparent=transparent)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())
