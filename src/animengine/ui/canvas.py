"""The drawing canvas: renders the current frame, handles zoom/pan and
forwards mouse input to the active tool."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPicture
from PySide6.QtWidgets import QWidget

from animengine.core import Vec2
from animengine.core.layers import RasterLayer, VectorLayer, interpolate_shapes
from animengine.render import paint_raster, paint_shape

from .state import EditorState
from .tools import Tool, ToolEvent

MAX_OVERLAY_POINTS = 4000  # never draw more point markers than this per frame


class CanvasView(QWidget):
    MIN_ZOOM, MAX_ZOOM = 0.05, 32.0

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.zoom = 1.0
        self.pan = QPointF(40, 40)
        self.tool: Tool | None = None
        self._panning = False
        self._pan_start = QPointF()
        self._space_down = False
        # render caches: layer id -> ((shape identity, epoch), QPicture)
        self._layer_pics: dict[int, tuple[tuple, QPicture]] = {}
        self._drag_static: tuple[object, QPicture] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        state.add_listener(self.update)

    # -------------------------------------------------------- coordinates
    def to_screen(self, p: Vec2) -> QPointF:
        return QPointF(p.x * self.zoom + self.pan.x(), p.y * self.zoom + self.pan.y())

    def to_doc(self, p: QPointF) -> Vec2:
        return Vec2((p.x() - self.pan.x()) / self.zoom, (p.y() - self.pan.y()) / self.zoom)

    def fit_view(self) -> None:
        doc = self.state.doc
        if doc.width <= 0 or doc.height <= 0:
            return
        margin = 40
        zx = (self.width() - margin * 2) / doc.width
        zy = (self.height() - margin * 2) / doc.height
        self.zoom = max(self.MIN_ZOOM, min(zx, zy, self.MAX_ZOOM))
        self.pan = QPointF((self.width() - doc.width * self.zoom) / 2,
                           (self.height() - doc.height * self.zoom) / 2)
        self.update()

    # ------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:
        state = self.state
        doc = state.doc
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(70, 70, 75))

        painter.save()
        painter.translate(self.pan)
        painter.scale(self.zoom, self.zoom)
        painter.fillRect(0, 0, doc.width, doc.height, QColor(255, 255, 255))
        painter.setClipRect(0, 0, doc.width, doc.height)

        if state.onion_skin and not state.playing:
            self._paint_onion(painter)
        self._paint_layers(painter)
        painter.restore()

        if state.show_grid:
            self._paint_grid(painter)

        # frame border
        painter.setPen(QPen(QColor(20, 20, 20), 1))
        tl = self.to_screen(Vec2(0, 0))
        br = self.to_screen(Vec2(doc.width, doc.height))
        painter.drawRect(int(tl.x()), int(tl.y()), int(br.x() - tl.x()), int(br.y() - tl.y()))

        if state.show_points and not state.playing:
            self._paint_points(painter)
        if self.tool is not None and not state.playing:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            self.tool.draw_overlay(painter, self.to_screen)
        painter.end()

    def _paint_layers(self, painter: QPainter) -> None:
        """Paint all layers with per-layer picture caching.

        Exact/held vector keyframes render into a QPicture cached by
        (shape identity, epoch), so pan/zoom/overlay repaints are O(1) even
        for enormous drawings. During a drag the active shape is split into
        a cached static picture plus the moving connections drawn live.
        """
        state = self.state
        doc = state.doc
        drag = state.active_drag
        for layer in doc.layers:
            if not layer.visible:
                continue
            painter.save()
            painter.setOpacity(layer.opacity)
            if isinstance(layer, VectorLayer):
                k0, k1, t = layer._segment(state.frame)
                if k0 is None:
                    painter.restore()
                    continue
                if k1 is not None and t > 0.0:  # tweened frame: draw directly
                    paint_shape(painter, interpolate_shapes(k0.shape, k1.shape, t))
                else:
                    shape = k0.shape
                    if drag is not None and drag.shape is shape:
                        if self._drag_static is None or self._drag_static[0] is not drag.token:
                            pic = QPicture()
                            p2 = QPainter(pic)
                            paint_shape(p2, shape, skip_conns=drag.conns)
                            p2.end()
                            self._drag_static = (drag.token, pic)
                        painter.drawPicture(0, 0, self._drag_static[1])
                        paint_shape(painter, shape, only_conns=drag.conns)
                    else:
                        key = (id(shape), shape.epoch)
                        cached = self._layer_pics.get(layer.id)
                        if cached is None or cached[0] != key:
                            pic = QPicture()
                            p2 = QPainter(pic)
                            paint_shape(p2, shape)
                            p2.end()
                            cached = (key, pic)
                            self._layer_pics[layer.id] = cached
                        painter.drawPicture(0, 0, cached[1])
            elif isinstance(layer, RasterLayer):
                st = layer.state_at(state.frame)
                if st is not None:
                    image = doc.images.get(st[0])
                    if image is not None:
                        paint_raster(painter, image, st[1], opacity=1.0)
            painter.restore()

    def _paint_onion(self, painter: QPainter) -> None:
        state = self.state
        doc = state.doc
        for offset in (-1, 1):
            frame = state.frame + offset
            if frame < 0 or frame >= doc.length:
                continue
            painter.save()
            painter.setOpacity(0.25)
            for layer in doc.layers:
                if not layer.visible:
                    continue
                if isinstance(layer, VectorLayer):
                    shape = layer.shape_at(frame)
                    if shape is not None:
                        paint_shape(painter, shape)
                elif isinstance(layer, RasterLayer):
                    st = layer.state_at(frame)
                    if st is not None:
                        image = doc.images.get(st[0])
                        if image is not None:
                            paint_raster(painter, image, st[1], opacity=0.6)
            painter.restore()

    def _paint_grid(self, painter: QPainter) -> None:
        doc = self.state.doc
        step = 50
        painter.setPen(QPen(QColor(120, 120, 130, 90), 1))
        for gx in range(0, doc.width + 1, step):
            a, b = self.to_screen(Vec2(gx, 0)), self.to_screen(Vec2(gx, doc.height))
            painter.drawLine(a, b)
        for gy in range(0, doc.height + 1, step):
            a, b = self.to_screen(Vec2(0, gy)), self.to_screen(Vec2(doc.width, gy))
            painter.drawLine(a, b)

    def _paint_points(self, painter: QPainter) -> None:
        state = self.state
        layer = state.project.active_layer
        if not isinstance(layer, VectorLayer):
            return
        shape = layer.shape_at(state.frame)
        if shape is None or not shape.points:
            return
        # only points inside the viewport, hard-capped so huge drawings
        # never stall the repaint
        tl = self.to_doc(QPointF(0, 0))
        br = self.to_doc(QPointF(self.width(), self.height()))
        visible = shape.points_in_rect(tl.x, tl.y, br.x, br.y, anchors_only=False)
        if len(visible) > MAX_OVERLAY_POINTS:
            visible = visible[:MAX_OVERLAY_POINTS]
        painter.setPen(QPen(QColor(0, 140, 0), 1))
        for p in visible:
            if p.is_control and p.anchor in shape.points:
                painter.drawLine(self.to_screen(p.pos),
                                 self.to_screen(shape.pos(p.anchor)))
        for p in visible:
            sp = self.to_screen(p.pos)
            if p.is_control:
                painter.setBrush(QColor(90, 220, 90))
                painter.setPen(QPen(QColor(0, 100, 0), 1))
                painter.drawEllipse(sp, 3.5, 3.5)
            else:
                selected = p.id in state.selected_points
                painter.setBrush(QColor(255, 80, 80) if selected else QColor(255, 220, 0))
                painter.setPen(QPen(QColor(60, 60, 0), 1))
                painter.drawEllipse(sp, 4.5, 4.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # --------------------------------------------------------------- input
    def _tool_event(self, event) -> ToolEvent:
        mods = event.modifiers()
        return ToolEvent(
            pos=self.to_doc(event.position()),
            ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
            shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
            alt=bool(mods & Qt.KeyboardModifier.AltModifier),
            view_scale=self.zoom,
        )

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        if self.state.playing:
            return
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_down
        ):
            self._panning = True
            self._pan_start = event.position() - self.pan
            return
        if self.tool is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.tool.press(self._tool_event(event))
        elif event.button() == Qt.MouseButton.RightButton:
            self.tool.right_press(self._tool_event(event))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            self.pan = event.position() - self._pan_start
            self.update()
            return
        if self.tool is not None and not self.state.playing:
            self.tool.move(self._tool_event(event))
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton,
                                                Qt.MouseButton.LeftButton):
            self._panning = False
            return
        if self.tool is not None and event.button() == Qt.MouseButton.LeftButton \
                and not self.state.playing:
            self.tool.release(self._tool_event(event))
            self.update()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_zoom = max(self.MIN_ZOOM, min(self.zoom * factor, self.MAX_ZOOM))
        # zoom about the cursor
        mouse = event.position()
        doc_pos = self.to_doc(mouse)
        self.zoom = new_zoom
        self.pan = mouse - QPointF(doc_pos.x * self.zoom, doc_pos.y * self.zoom)
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
        else:
            super().keyReleaseEvent(event)
