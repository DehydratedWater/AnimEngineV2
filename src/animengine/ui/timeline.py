"""Timeline: per-layer keyframe grid + playback controls.

Upgrades over v1's view-only grid: click/drag to scrub, click a row to pick
the layer, double-click to add a keyframe, drag keyframes to move them,
right-click context menu (add/remove/copy keyframe, interpolation), audio
clip bars, adjustable fps, loop playback.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from animengine.core import Interp

from .state import EditorState

CELL_W, CELL_H, HEADER_H, NAME_W = 14, 24, 22, 120


class TimelineGrid(QWidget):
    frame_clicked = Signal(int)

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self._drag_scrub = False
        self._drag_key: tuple[int, int] | None = None  # (layer_id, frame)
        self.setMouseTracking(True)
        state.add_listener(self._refresh)

    def _refresh(self) -> None:
        doc = self.state.doc
        frames = max(doc.length + 24, 60)
        rows = max(len(doc.layers), 1)
        self.setMinimumSize(NAME_W + frames * CELL_W,
                            HEADER_H + rows * CELL_H + 18 * len(doc.audio_clips))
        self.updateGeometry()
        self.update()

    # rows are displayed top layer first (reverse of doc order)
    def _row_layer(self, row: int):
        doc = self.state.doc
        idx = len(doc.layers) - 1 - row
        if 0 <= idx < len(doc.layers):
            return doc.layers[idx]
        return None

    def _layer_row(self, layer_id: int) -> int:
        doc = self.state.doc
        return len(doc.layers) - 1 - self.state.doc.layer_index(layer_id)

    def paintEvent(self, event) -> None:
        state = self.state
        doc = state.doc
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(45, 45, 50))
        frames = max(doc.length + 24, 60)

        # header: frame numbers
        painter.setPen(QPen(QColor(180, 180, 190)))
        for f in range(0, frames, 5):
            x = NAME_W + f * CELL_W
            painter.drawText(QRectF(x, 0, CELL_W * 5, HEADER_H),
                             Qt.AlignmentFlag.AlignVCenter, str(f))
        # current frame column
        cx = NAME_W + state.frame * CELL_W
        painter.fillRect(cx, 0, CELL_W, self.height(), QColor(200, 60, 60, 70))

        for row in range(len(doc.layers)):
            layer = self._row_layer(row)
            if layer is None:
                continue
            y = HEADER_H + row * CELL_H
            active = layer.id == state.project.active_layer_id
            # layer name cell
            painter.fillRect(0, y, NAME_W, CELL_H,
                             QColor(80, 80, 120) if active else QColor(58, 58, 64))
            painter.setPen(QPen(QColor(230, 230, 235)))
            flags = "" if layer.visible else " (hidden)"
            painter.drawText(QRectF(6, y, NAME_W - 8, CELL_H),
                             Qt.AlignmentFlag.AlignVCenter,
                             f"{layer.name}{flags}")
            # keyframe cells
            keys = layer.key_frames_sorted()
            painter.setPen(QPen(QColor(70, 70, 78)))
            for f in range(frames):
                painter.drawRect(NAME_W + f * CELL_W, y, CELL_W, CELL_H)
            for i, kf_frame in enumerate(keys):
                x = NAME_W + kf_frame * CELL_W
                nxt = keys[i + 1] if i + 1 < len(keys) else None
                kf = layer.keyframes[kf_frame]
                # tween span bar
                span_end = (nxt if nxt is not None else min(doc.length, frames))
                if span_end > kf_frame + 1:
                    interp_col = (QColor(90, 90, 100)
                                  if getattr(kf, "interp", None) is Interp.HOLD
                                  else QColor(90, 140, 200, 120))
                    painter.fillRect(x + CELL_W, y + CELL_H // 2 - 2,
                                     (span_end - kf_frame - 1) * CELL_W, 4, interp_col)
                # keyframe diamond
                painter.setBrush(QColor(240, 240, 245))
                painter.setPen(QPen(QColor(20, 20, 20)))
                cx_ = x + CELL_W / 2
                cy_ = y + CELL_H / 2
                painter.drawEllipse(QRectF(cx_ - 4, cy_ - 4, 8, 8))
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # audio clip bars
        ay = HEADER_H + len(doc.layers) * CELL_H
        for clip in doc.audio_clips:
            dur_frames = int((clip.duration_sec or 1.0) * doc.fps)
            x = NAME_W + clip.start_frame * CELL_W
            painter.fillRect(x, ay + 2, max(CELL_W, dur_frames * CELL_W), 14,
                             QColor(90, 170, 90, 160))
            painter.setPen(QPen(QColor(235, 255, 235)))
            painter.drawText(QRectF(x + 4, ay, 300, 18),
                             Qt.AlignmentFlag.AlignVCenter, f"♪ {clip.name}")
            ay += 18
        painter.end()

    # ------------------------------------------------------------- input
    def _hit(self, pos) -> tuple[int | None, int]:
        """(layer_id or None, frame) under the cursor."""
        frame = max(0, int((pos.x() - NAME_W) // CELL_W))
        row = int((pos.y() - HEADER_H) // CELL_H)
        layer = self._row_layer(row) if pos.y() >= HEADER_H else None
        return (layer.id if layer else None, frame)

    def mousePressEvent(self, event) -> None:
        layer_id, frame = self._hit(event.position())
        state = self.state
        if event.button() == Qt.MouseButton.LeftButton:
            if layer_id is not None:
                state.project.set_active_layer(layer_id)
                layer = state.doc.layer(layer_id)
                if frame in layer.keyframes:
                    self._drag_key = (layer_id, frame)
            state.project.set_frame(min(frame, state.doc.length + 23))
            self._drag_scrub = self._drag_key is None
            state.notify()
        elif event.button() == Qt.MouseButton.RightButton:
            self._context_menu(event, layer_id, frame)

    def mouseMoveEvent(self, event) -> None:
        _, frame = self._hit(event.position())
        state = self.state
        if self._drag_key is not None:
            layer_id, src = self._drag_key
            if frame != src and frame >= 0:
                layer = state.doc.layer(layer_id)
                if frame not in layer.keyframes:
                    layer.move_keyframe(src, frame)
                    state.doc.extend_to(frame)
                    self._drag_key = (layer_id, frame)
                    state.notify()
        elif self._drag_scrub:
            state.project.set_frame(frame)
            state.notify()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_scrub = False
        self._drag_key = None

    def mouseDoubleClickEvent(self, event) -> None:
        layer_id, frame = self._hit(event.position())
        if layer_id is not None:
            self.state.project.add_keyframe(layer_id, frame)
            self.state.notify()

    def _context_menu(self, event, layer_id: int | None, frame: int) -> None:
        state = self.state
        menu = QMenu(self)
        if layer_id is not None:
            layer = state.doc.layer(layer_id)
            has_kf = frame in layer.keyframes
            act_add = menu.addAction("Add keyframe")
            act_add.setEnabled(not has_kf)
            act_rm = menu.addAction("Remove keyframe")
            act_rm.setEnabled(has_kf and len(layer.keyframes) > 1)
            act_copy = menu.addAction("Copy previous keyframe here")
            menu.addSeparator()
            interp_menu = menu.addMenu("Interpolation to next")
            interp_actions = {}
            if has_kf:
                current = layer.keyframes[frame].interp
                for interp in Interp:
                    a = interp_menu.addAction(interp.value.replace("_", " "))
                    a.setCheckable(True)
                    a.setChecked(interp is current)
                    interp_actions[a] = interp
            else:
                interp_menu.setEnabled(False)
            chosen = menu.exec(event.globalPosition().toPoint())
            if chosen is None:
                return
            if chosen is act_add:
                state.project.add_keyframe(layer_id, frame)
            elif chosen is act_rm:
                state.project.remove_keyframe(layer_id, frame)
            elif chosen is act_copy:
                prev = layer.prev_key_frame(frame)
                if prev is not None:
                    state.doc.copy_keyframe_forward(layer_id, prev, frame)
            elif chosen in interp_actions:
                state.project.set_keyframe_interp(interp_actions[chosen].value,
                                                  layer_id, frame)
            state.notify()


class TimelinePanel(QWidget):
    """Playback bar + scrollable grid."""

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)

        def btn(text: str, tip: str, fn) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(40)
            b.clicked.connect(fn)
            bar.addWidget(b)
            return b

        btn("|<", "Go to start", lambda: self._goto(0))
        btn("<", "Previous frame (Left)", self._prev)
        self.play_btn = btn("▶", "Play/Pause (Space handled by canvas focus... use this)",
                            self.toggle_play)
        btn(">", "Next frame; extends animation at the end (Right)", self._next)
        btn(">|", "Go to end", lambda: self._goto(self.state.doc.length - 1))
        btn("c→", "Copy current frame forward to a new keyframe (v1's c-->)",
            self._copy_forward)
        btn("del", "Remove keyframes at current frame", self._delete_frame)

        self.counter = QLabel("1 / 1")
        self.counter.setMinimumWidth(70)
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.counter)

        bar.addWidget(QLabel("fps:"))
        self.fps_box = QDoubleSpinBox()
        self.fps_box.setRange(1, 360)
        self.fps_box.setDecimals(1)
        self.fps_box.setValue(state.doc.fps)
        self.fps_box.valueChanged.connect(self._set_fps)
        bar.addWidget(self.fps_box)
        bar.addStretch(1)

        self.grid = TimelineGrid(state)
        scroll = QScrollArea()
        scroll.setWidget(self.grid)
        scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(scroll)

        state.add_listener(self._sync)
        self._sync()

    # ------------------------------------------------------------ actions
    def _goto(self, frame: int) -> None:
        self.state.project.set_frame(max(0, frame))
        self.state.notify()

    def _prev(self) -> None:
        self.state.project.prev_frame()
        self.state.notify()

    def _next(self) -> None:
        self.state.project.next_frame()
        self.state.notify()

    def _copy_forward(self) -> None:
        self.state.project.copy_frame_forward()
        self.state.notify()

    def _delete_frame(self) -> None:
        p = self.state.project
        for layer in list(p.doc.layers):
            if p.current_frame in layer.keyframes and len(layer.keyframes) > 1:
                p.remove_keyframe(layer.id, p.current_frame)
        self.state.notify()

    def _set_fps(self, value: float) -> None:
        self.state.doc.fps = value
        if self.state.playing:
            self.timer.setInterval(round(1000 / value))

    def toggle_play(self) -> None:
        state = self.state
        state.playing = not state.playing
        if state.playing:
            self.timer.start(round(1000 / max(1.0, state.doc.fps)))
            self.play_btn.setText("⏸")
        else:
            self.timer.stop()
            self.play_btn.setText("▶")
        state.notify()

    def _tick(self) -> None:
        p = self.state.project
        nxt = p.current_frame + 1
        if nxt >= p.doc.length:
            nxt = 0  # loop like v1
        p.current_frame = nxt
        self.state.notify()

    def _sync(self) -> None:
        p = self.state.project
        self.counter.setText(f"{p.current_frame + 1} / {p.doc.length}")
        if abs(self.fps_box.value() - p.doc.fps) > 1e-9:
            self.fps_box.blockSignals(True)
            self.fps_box.setValue(p.doc.fps)
            self.fps_box.blockSignals(False)
