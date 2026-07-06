"""Canvas tools.

Every original tool is here, modernized:
- line / rectangle / cubic curve (multi-click, right-click steps back)
- freehand polyline + freehand smooth curve (with simplification, auto-close)
- bucket fill (left fill/recolor, right delete)
- select & transform: marquee -> box with scale (corner) and rotate (outer
  corner) handles; drag points/connections/fills; optional cut-out mode that
  slices strokes at the marquee border like v1's default
- add-point, scissors (Alt = detach), style applicator, parameter picker
  (syringe), point eraser
- raster: brush, raster eraser, move/transform bitmap

All coordinates arriving here are document-space; `view_scale` converts
screen-pixel tolerances (hit radii stay 15 *screen* px like v1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from animengine.api import SNAP_RADIUS
from animengine.core import Vec2
from animengine.core.layers import RasterLayer, VectorLayer

from .state import ActiveDrag, EditorState

_OVERLAY_BLUE = QColor(60, 120, 255)


def _conns_of_points(shape, point_ids) -> set[int]:
    """All connections touching any of the given points (index-accelerated)."""
    idx = shape.index()
    out: set[int] = set()
    for pid in point_ids:
        out |= idx.adjacency.get(pid, set())
    return out


def _with_attached_controls(shape, point_ids: set[int]) -> set[int]:
    """Extend a point set with control handles anchored to its anchor points,
    so curves attached at shared/welded vertices follow the drag."""
    out = set(point_ids)
    for pid in point_ids:
        out |= {c.id for c in shape.controls_of(pid)}
    return out


@dataclass
class ToolEvent:
    pos: Vec2  # document coords
    ctrl: bool = False
    shift: bool = False
    alt: bool = False
    view_scale: float = 1.0  # doc px -> screen px factor

    def hit_radius(self, screen_px: float = SNAP_RADIUS) -> float:
        return screen_px / max(self.view_scale, 1e-6)


class Tool:
    name = "tool"
    label = "Tool"
    shortcut = ""
    status_hint = ""
    wants_raster = False  # tool targets raster layers

    def __init__(self, state: EditorState):
        self.state = state

    # lifecycle
    def activate(self) -> None: ...
    def deactivate(self) -> None:
        self.cancel()

    def press(self, ev: ToolEvent) -> None: ...
    def move(self, ev: ToolEvent) -> None: ...
    def release(self, ev: ToolEvent) -> None: ...
    def right_press(self, ev: ToolEvent) -> None:
        self.cancel()

    def cancel(self) -> None: ...
    def draw_overlay(self, painter: QPainter, to_screen) -> None: ...

    # helpers -----------------------------------------------------------
    @property
    def project(self):
        return self.state.project

    def shape_now(self):
        """Live shape of the active layer's current frame (None if not vector)."""
        layer = self.project.active_layer
        if not isinstance(layer, VectorLayer):
            return None
        return layer.shape_at(self.project.current_frame)

    def _pen(self, color=_OVERLAY_BLUE, width=1.5, dash=False) -> QPen:
        pen = QPen(color, width)
        pen.setCosmetic(True)
        if dash:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen


# ---------------------------------------------------------------- drawing
class LineTool(Tool):
    name, label, shortcut = "line", "Line", "L"
    status_hint = "Drag to draw a line. Ctrl disables snapping. Right-click cancels."

    def __init__(self, state):
        super().__init__(state)
        self.start: Vec2 | None = None
        self.end: Vec2 | None = None

    def press(self, ev: ToolEvent) -> None:
        self.start = self.end = ev.pos

    def move(self, ev: ToolEvent) -> None:
        if self.start is not None:
            self.end = ev.pos

    def release(self, ev: ToolEvent) -> None:
        if self.start is None:
            return
        start, end = self.start, ev.pos
        self.cancel()
        if start.distance_to(end) <= 5 / max(ev.view_scale, 1e-6):
            return  # v1: ignore tiny strokes
        self.project.add_line(start.x, start.y, end.x, end.y,
                              width=self.state.stroke_width,
                              color=self.state.stroke_color,
                              snap=self.state.snap and not ev.ctrl)

    def cancel(self) -> None:
        self.start = self.end = None

    def draw_overlay(self, painter, to_screen) -> None:
        if self.start is not None and self.end is not None:
            painter.setPen(self._pen())
            painter.drawLine(to_screen(self.start), to_screen(self.end))


class RectTool(Tool):
    name, label, shortcut = "rect", "Rectangle", "R"
    status_hint = "Drag to draw a rectangle. Right-click cancels."

    def __init__(self, state):
        super().__init__(state)
        self.start: Vec2 | None = None
        self.end: Vec2 | None = None

    def press(self, ev: ToolEvent) -> None:
        self.start = self.end = ev.pos

    def move(self, ev: ToolEvent) -> None:
        if self.start is not None:
            self.end = ev.pos

    def release(self, ev: ToolEvent) -> None:
        if self.start is None:
            return
        a, b = self.start, ev.pos
        self.cancel()
        x, y = min(a.x, b.x), min(a.y, b.y)
        w, h = abs(b.x - a.x), abs(b.y - a.y)
        if w < 3 or h < 3:
            return
        self.project.add_rect(x, y, w, h, width=self.state.stroke_width,
                              color=self.state.stroke_color)

    def cancel(self) -> None:
        self.start = self.end = None

    def draw_overlay(self, painter, to_screen) -> None:
        if self.start is None or self.end is None:
            return
        painter.setPen(self._pen())
        a, b = to_screen(self.start), to_screen(self.end)
        painter.drawRect(min(a.x(), b.x()), min(a.y(), b.y()),
                         abs(b.x() - a.x()), abs(b.y() - a.y()))


class CurveTool(Tool):
    name, label, shortcut = "curve", "Curve", "C"
    status_hint = ("Click start, end, then two control points to place a cubic "
                   "curve. Right-click steps back.")

    def __init__(self, state):
        super().__init__(state)
        self.pts: list[Vec2] = []  # start, end, ctrl1, ctrl2
        self.hover: Vec2 | None = None

    def press(self, ev: ToolEvent) -> None:
        self.pts.append(ev.pos)
        if len(self.pts) == 4:
            start, end, c1, c2 = self.pts
            self.cancel()
            self.project.add_curve(start.x, start.y, c1.x, c1.y, c2.x, c2.y,
                                   end.x, end.y, width=self.state.stroke_width,
                                   color=self.state.stroke_color,
                                   snap=self.state.snap and not ev.ctrl)

    def move(self, ev: ToolEvent) -> None:
        self.hover = ev.pos

    def right_press(self, ev: ToolEvent) -> None:
        if self.pts:
            self.pts.pop()  # v1: step one control point back
        else:
            self.cancel()

    def cancel(self) -> None:
        self.pts = []
        self.hover = None

    def draw_overlay(self, painter, to_screen) -> None:
        if not self.pts:
            return
        from PySide6.QtGui import QPainterPath

        pts = self.pts + ([self.hover] if self.hover else [])
        painter.setPen(self._pen())
        path = QPainterPath()
        s = to_screen(pts[0])
        path.moveTo(s)
        if len(pts) == 2:
            path.lineTo(to_screen(pts[1]))
        elif len(pts) == 3:
            path.quadTo(to_screen(pts[2]), to_screen(pts[1]))
        elif len(pts) >= 4:
            path.cubicTo(to_screen(pts[2]), to_screen(pts[3]), to_screen(pts[1]))
        painter.drawPath(path)
        painter.setPen(self._pen(QColor(0, 180, 0)))
        for p in pts[2:]:
            sp = to_screen(p)
            painter.drawEllipse(sp, 4, 4)


class _FreehandTool(Tool):
    """Shared freehand collection + simplification."""

    simplify_eps = 6.0  # screen px

    def __init__(self, state):
        super().__init__(state)
        self.pts: list[Vec2] = []

    def press(self, ev: ToolEvent) -> None:
        self.pts = [ev.pos]

    def move(self, ev: ToolEvent) -> None:
        if self.pts and ev.pos.distance_to(self.pts[-1]) > 3 / max(ev.view_scale, 1e-6):
            self.pts.append(ev.pos)

    def cancel(self) -> None:
        self.pts = []

    def draw_overlay(self, painter, to_screen) -> None:
        if len(self.pts) > 1:
            painter.setPen(self._pen())
            for a, b in zip(self.pts, self.pts[1:], strict=False):
                painter.drawLine(to_screen(a), to_screen(b))

    def _finish(self, ev: ToolEvent) -> tuple[list[Vec2], bool] | None:
        pts, self.pts = self.pts, []
        if len(pts) < 2:
            return None
        eps = self.simplify_eps / max(ev.view_scale, 1e-6)
        pts = _rdp(pts, eps)
        close = len(pts) > 2 and pts[0].distance_to(pts[-1]) <= ev.hit_radius()
        if close:
            pts = pts[:-1] if pts[-1].distance_to(pts[0]) < 1e-6 else pts
        return pts, close


class PolylineTool(_FreehandTool):
    name, label, shortcut = "pen", "Pen (freehand)", "P"
    status_hint = ("Draw freehand; the stroke is simplified to a polyline and "
                   "closes if you end near the start.")

    def release(self, ev: ToolEvent) -> None:
        result = self._finish(ev)
        if result is None:
            return
        pts, close = result
        if len(pts) < 2:
            return
        self.project.add_polyline([(p.x, p.y) for p in pts], close=close,
                                  width=self.state.stroke_width,
                                  color=self.state.stroke_color,
                                  snap=self.state.snap and not ev.ctrl)


class SmoothPenTool(_FreehandTool):
    name, label, shortcut = "smoothpen", "Smooth pen", "Q"
    status_hint = "Freehand stroke fitted with smooth curves."
    simplify_eps = 12.0

    def release(self, ev: ToolEvent) -> None:
        result = self._finish(ev)
        if result is None:
            return
        pts, close = result
        if len(pts) < 2:
            return
        self.project.add_smooth_curve([(p.x, p.y) for p in pts], close=close,
                                      width=self.state.stroke_width,
                                      color=self.state.stroke_color)


def _rdp(pts: list[Vec2], eps: float) -> list[Vec2]:
    """Ramer-Douglas-Peucker polyline simplification."""
    if len(pts) < 3:
        return pts
    from animengine.core.geometry import point_segment_distance

    a, b = pts[0], pts[-1]
    idx, dmax = 0, 0.0
    for i in range(1, len(pts) - 1):
        d = point_segment_distance(pts[i], a, b)
        if d > dmax:
            idx, dmax = i, d
    if dmax <= eps:
        return [a, b]
    left = _rdp(pts[: idx + 1], eps)
    right = _rdp(pts[idx:], eps)
    return left[:-1] + right


class FillTool(Tool):
    name, label, shortcut = "fill", "Fill", "F"
    status_hint = "Click inside a closed outline to fill/recolor. Right-click deletes a fill."

    def press(self, ev: ToolEvent) -> None:
        self.project.fill_region(ev.pos.x, ev.pos.y, self.state.fill_color)

    def right_press(self, ev: ToolEvent) -> None:
        self.project.remove_fill_at(ev.pos.x, ev.pos.y)


# ------------------------------------------------------------- edit tools
class AddPointTool(Tool):
    name, label, shortcut = "addpoint", "Add point", "A"
    status_hint = "Click on a line to insert a point there."

    def press(self, ev: ToolEvent) -> None:
        self.project.cut_connection_at(ev.pos.x, ev.pos.y, max_dist=ev.hit_radius())


class ScissorsTool(Tool):
    name, label, shortcut = "cut", "Scissors", "X"
    status_hint = "Click a line to cut it in two. Alt-click detaches it from its neighbours."

    def press(self, ev: ToolEvent) -> None:
        if ev.alt:
            self.project.separate_connection_at(ev.pos.x, ev.pos.y,
                                                max_dist=ev.hit_radius())
        else:
            self.project.cut_connection_at(ev.pos.x, ev.pos.y, max_dist=ev.hit_radius())


class StyleTool(Tool):
    name, label, shortcut = "style", "Apply style", "Y"
    status_hint = "Click a line to apply the current stroke width and color."

    def press(self, ev: ToolEvent) -> None:
        shape = self.shape_now()
        if shape is None:
            return
        conn = shape.nearest_connection(ev.pos, max_dist=ev.hit_radius())
        if conn is not None:
            self.project.set_connection_style(conn.id, width=self.state.stroke_width,
                                              color=self.state.stroke_color)


class PickerTool(Tool):
    name, label, shortcut = "picker", "Pick style", "I"
    status_hint = "Click a line to pick up its width and color (syringe)."

    def press(self, ev: ToolEvent) -> None:
        shape = self.shape_now()
        if shape is None:
            return
        conn = shape.nearest_connection(ev.pos, max_dist=ev.hit_radius())
        if conn is not None:
            self.state.stroke_width = conn.width
            self.state.stroke_color = conn.color
            self.state.notify()


class EraserTool(Tool):
    name, label, shortcut = "eraser", "Eraser", "E"
    status_hint = "Drag to erase points (and their lines)."

    def __init__(self, state):
        super().__init__(state)
        self.session = None
        self.cursor: Vec2 | None = None

    def press(self, ev: ToolEvent) -> None:
        self.session = self.project.edit_shape()
        self._erase(ev)

    def move(self, ev: ToolEvent) -> None:
        self.cursor = ev.pos
        if self.session is not None:
            self._erase(ev)

    def _erase(self, ev: ToolEvent) -> None:
        shape = self.session.shape
        r = self.state.eraser_radius
        doomed = [p.id for p in shape.points_in_rect(ev.pos.x - r, ev.pos.y - r,
                                                     ev.pos.x + r, ev.pos.y + r)
                  if p.pos.distance_to(ev.pos) <= r]
        for pid in doomed:
            shape.remove_point(pid)

    def release(self, ev: ToolEvent) -> None:
        if self.session is not None:
            self.session.commit("Erase")
            self.session = None

    def cancel(self) -> None:
        if self.session is not None:
            self.session.cancel()
            self.session = None

    def draw_overlay(self, painter, to_screen) -> None:
        if self.cursor is not None:
            painter.setPen(self._pen(QColor(200, 60, 60)))
            c = to_screen(self.cursor)
            r = self.state.eraser_radius * self._scale(to_screen)
            painter.drawEllipse(c, r, r)

    @staticmethod
    def _scale(to_screen) -> float:
        a = to_screen(Vec2(0, 0))
        b = to_screen(Vec2(1, 0))
        return abs(b.x() - a.x())


# ------------------------------------------------------------- selection
@dataclass
class _DragState:
    mode: str  # "marquee" | "move" | "scale" | "rotate" | "point" | "conn" | "fill"
    start: Vec2
    session: object | None = None
    point_id: int | None = None
    extra: dict = field(default_factory=dict)


class SelectTool(Tool):
    name, label, shortcut = "select", "Select / Transform", "S"
    status_hint = ("Drag a box to select. Corners scale, outer squares rotate, "
                   "inside moves. Drag points/lines/fills directly. Del deletes. "
                   "Ctrl adds to selection.")

    HANDLE_PX = 10.0

    def __init__(self, state):
        super().__init__(state)
        self.drag: _DragState | None = None
        self.marquee_end: Vec2 | None = None

    # -- hit helpers -----------------------------------------------------
    def _box_handles(self) -> dict[str, Vec2]:
        box = self.state.selection_box
        if box is None:
            return {}
        x0, y0, x1, y1 = box
        return {
            "nw": Vec2(x0, y0), "ne": Vec2(x1, y0),
            "se": Vec2(x1, y1), "sw": Vec2(x0, y1),
        }

    def press(self, ev: ToolEvent) -> None:
        state = self.state
        shape = self.shape_now()
        box = state.selection_box

        # 1. transform-box handles
        if box is not None:
            r = self.HANDLE_PX / max(ev.view_scale, 1e-6)
            for name, corner in self._box_handles().items():
                rot_pos = self._rotate_handle_pos(name, corner, r)
                if ev.pos.distance_to(rot_pos) <= r:
                    self._begin_transform("rotate", ev, anchor=name)
                    return
                if ev.pos.distance_to(corner) <= r:
                    self._begin_transform("scale", ev, anchor=name)
                    return
            x0, y0, x1, y1 = box
            if x0 <= ev.pos.x <= x1 and y0 <= ev.pos.y <= y1:
                self._begin_transform("move", ev)
                return

        if shape is None:
            return
        # 2. direct hits: point > connection > fill
        pt = shape.nearest_point(ev.pos, max_dist=ev.hit_radius())
        if pt is not None:
            session = self.project.edit_shape()
            self.drag = _DragState("point", ev.pos, session, pt.id)
            self._mark_drag(session.shape, {pt.id})
            return
        conn = shape.nearest_connection(ev.pos, max_dist=ev.hit_radius())
        if conn is not None:
            session = self.project.edit_shape()
            ids = {conn.p1, conn.p2, *conn.control_ids()}
            ids = _with_attached_controls(session.shape, ids)
            self.drag = _DragState("conn", ev.pos, session,
                                   extra={"ids": ids, "last": ev.pos})
            self._mark_drag(session.shape, ids)
            return
        fill = next((f for f in shape.fills.values()
                     if shape.fill_contains(f, ev.pos)), None)
        if fill is not None:
            session = self.project.edit_shape()
            live = session.shape
            live_fill = live.fills[fill.id]
            # Flash-style: neighbours sharing this fill's boundary keep a
            # stationary copy (their "bite"), so the drag can't deform them
            live.detach_fill_boundary(fill.id)
            fill_conns = set(live_fill.connection_ids())
            idx = live.index()
            ids: set[int] = set()
            for cid in fill_conns:
                c = live.connections.get(cid)
                if c:
                    ids |= {c.p1, c.p2, *c.control_ids()}
            # Flash-style: rip the fill free of geometry welded onto its
            # boundary, so dragging it never deforms the shapes it touched
            for pid in list(ids):
                p = live.points.get(pid)
                if p is None or p.is_control:
                    continue
                if idx.adjacency.get(pid, set()) - fill_conns:
                    ids.discard(pid)
                    ids.add(live.detach_point(pid, fill_conns))
            ids = _with_attached_controls(live, ids)
            self.drag = _DragState("fill", ev.pos, session,
                                   extra={"ids": ids, "last": ev.pos})
            self._mark_drag(live, ids)
            return
        # 3. empty space: marquee
        if not ev.ctrl:
            state.clear_selection()
        self.drag = _DragState("marquee", ev.pos)
        self.marquee_end = ev.pos

    def _rotate_handle_pos(self, name: str, corner: Vec2, r: float) -> Vec2:
        box = self.state.selection_box
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        d = (corner - Vec2(cx, cy)).normalized()
        return corner + d * (2.2 * r)

    def _begin_transform(self, mode: str, ev: ToolEvent, anchor: str | None = None) -> None:
        session = self.project.edit_shape()
        box = self.state.selection_box
        ids = set(self.state.selected_points)
        shape = session.shape
        for pid in list(ids):
            p = shape.points.get(pid)
            if p is not None:
                ids |= {c.id for c in shape.controls_of(pid)}
        originals = {pid: shape.points[pid].pos for pid in ids if pid in shape.points}
        self.drag = _DragState(mode, ev.pos, session,
                               extra={"anchor": anchor, "box0": box,
                                      "originals": originals})
        self._mark_drag(shape, set(originals))

    def _mark_drag(self, shape, point_ids: set[int]) -> None:
        """Tell the canvas which connections move so it can cache the rest."""
        self.state.active_drag = ActiveDrag(shape, _conns_of_points(shape, point_ids))

    def move(self, ev: ToolEvent) -> None:
        d = self.drag
        if d is None:
            return
        if d.mode == "marquee":
            self.marquee_end = ev.pos
            return
        shape = d.session.shape
        if d.mode == "point":
            p = shape.points.get(d.point_id)
            if p is None:
                return
            delta = ev.pos - p.pos
            shape.move_point(p.id, ev.pos)
            for ctrl in shape.controls_of(p.id):
                shape.move_point(ctrl.id, ctrl.pos + delta)
        elif d.mode in ("conn", "fill"):
            delta = ev.pos - d.extra["last"]
            d.extra["last"] = ev.pos
            for pid in d.extra["ids"]:
                if pid in shape.points:
                    shape.move_point(pid, shape.pos(pid) + delta)
        elif d.mode == "move":
            delta = ev.pos - d.start
            for pid, orig in d.extra["originals"].items():
                if pid in shape.points:
                    shape.move_point(pid, orig + delta)
            x0, y0, x1, y1 = d.extra["box0"]
            self.state.selection_box = (x0 + delta.x, y0 + delta.y,
                                        x1 + delta.x, y1 + delta.y)
        elif d.mode == "scale":
            self._apply_scale(ev)
        elif d.mode == "rotate":
            self._apply_rotate(ev)

    def _apply_scale(self, ev: ToolEvent) -> None:
        d = self.drag
        x0, y0, x1, y1 = d.extra["box0"]
        anchor_map = {"nw": Vec2(x1, y1), "ne": Vec2(x0, y1),
                      "se": Vec2(x0, y0), "sw": Vec2(x1, y0)}
        fixed = anchor_map[d.extra["anchor"]]
        w0 = {"nw": x0 - x1, "ne": x1 - x0, "se": x1 - x0, "sw": x0 - x1}[d.extra["anchor"]]
        h0 = {"nw": y0 - y1, "ne": y0 - y1, "se": y1 - y0, "sw": y1 - y0}[d.extra["anchor"]]
        sx = (ev.pos.x - fixed.x) / w0 if abs(w0) > 1e-6 else 1.0
        sy = (ev.pos.y - fixed.y) / h0 if abs(h0) > 1e-6 else 1.0
        if ev.shift:  # uniform
            s = max(abs(sx), abs(sy))
            sx = math.copysign(s, sx)
            sy = math.copysign(s, sy)
        shape = d.session.shape
        for pid, orig in d.extra["originals"].items():
            if pid in shape.points:
                v = orig - fixed
                shape.move_point(pid, fixed + Vec2(v.x * sx, v.y * sy))
        xs = [fixed.x, fixed.x + w0 * sx]
        ys = [fixed.y, fixed.y + h0 * sy]
        self.state.selection_box = (min(xs), min(ys), max(xs), max(ys))

    def _apply_rotate(self, ev: ToolEvent) -> None:
        d = self.drag
        x0, y0, x1, y1 = d.extra["box0"]
        center = Vec2((x0 + x1) / 2, (y0 + y1) / 2)
        a0 = math.atan2(d.start.y - center.y, d.start.x - center.x)
        a1 = math.atan2(ev.pos.y - center.y, ev.pos.x - center.x)
        angle = a1 - a0
        shape = d.session.shape
        for pid, orig in d.extra["originals"].items():
            if pid in shape.points:
                shape.move_point(pid, orig.rotated(angle, around=center))
        d.extra["angle"] = angle

    def release(self, ev: ToolEvent) -> None:
        d = self.drag
        self.drag = None
        self.state.active_drag = None
        if d is None:
            return
        state = self.state
        if d.mode == "marquee":
            end = self.marquee_end or ev.pos
            self.marquee_end = None
            x0, x1 = sorted((d.start.x, end.x))
            y0, y1 = sorted((d.start.y, end.y))
            if x1 - x0 < 2 and y1 - y0 < 2:
                state.clear_selection()
                state.notify()
                return
            self._select_rect(x0, y0, x1, y1, additive=ev.ctrl)
            return
        # transforms / drags: commit as one undo step
        moved = ev.pos.distance_to(d.start) > 1e-9
        if d.mode in ("point", "conn", "fill") and not moved:
            d.session.cancel()  # plain click: no edit, no accidental weld
            return
        label = {"point": "Move point", "conn": "Move connection",
                 "fill": "Move fill", "move": "Move selection",
                 "scale": "Scale selection", "rotate": "Rotate selection"}[d.mode]
        if d.mode == "point" and not ev.ctrl:
            # v1: dropping a point onto another welds them
            shape = d.session.shape
            p = shape.points.get(d.point_id)
            if p is not None and not p.is_control:
                target = shape.nearest_point(p.pos, max_dist=ev.hit_radius(),
                                             include_controls=False,
                                             exclude={p.id})
                if target is not None:
                    shape.merge_points(target.id, p.id)
        if d.mode == "point":
            moved = {d.point_id,
                     *(c.id for c in d.session.shape.controls_of(d.point_id))}
        elif d.mode in ("conn", "fill"):
            moved = d.extra["ids"]
        else:  # move / scale / rotate via the transform box
            moved = set(d.extra["originals"])
        shape = d.session.shape
        moved_conns = _conns_of_points(shape, moved)
        shape.insert_intersections(list(moved_conns))
        self._drop_merge(shape, moved, d.session.before_shape)
        d.session.commit(label)
        if d.mode in ("move", "scale", "rotate"):
            state.recompute_selection_box()
        state.notify()

    @staticmethod
    def _drop_merge(shape, moved_point_ids: set[int], before) -> None:
        """Flash-style drop: fills that moved come to the front and consume
        the geometry they newly cover; half-covered fills keep their visible
        remainder."""
        alive = {pid for pid in moved_point_ids if pid in shape.points}
        moved_conns = _conns_of_points(shape, alive)
        moved_fills = [fid for fid, f in shape.fills.items()
                       if f.connection_ids() & moved_conns]
        if not moved_fills:
            return
        spare: set[int] = set()
        for fid in moved_fills:
            spare |= shape.fills[fid].connection_ids()
        for fid in moved_fills:
            shape.raise_fill(fid)
        for fid in moved_fills:
            shape.consume_under_fill(fid, spare=spare, before=before)

    def _select_rect(self, x0: float, y0: float, x1: float, y1: float,
                     additive: bool) -> None:
        state = self.state
        if state.cut_out_selection:
            session = self.project.edit_shape()
            corners = [Vec2(x0, y0), Vec2(x1, y0), Vec2(x1, y1), Vec2(x0, y1)]
            n = 0
            for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
                n += len(session.shape.split_at_segment(a, b))
            if n:
                session.commit("Cut out selection")
            else:
                session.cancel()
        shape = self.shape_now()
        if shape is None:
            return
        if not additive:
            state.selected_points.clear()
        for p in shape.points_in_rect(x0, y0, x1, y1):
            state.selected_points.add(p.id)
        state.recompute_selection_box()
        state.notify()

    def delete_selection(self) -> None:
        state = self.state
        if not state.selected_points:
            return
        ids = set(state.selected_points)

        def fn(shape):
            for pid in ids:
                shape.remove_point(pid)

        self.project._edit("Delete selection", fn)
        state.clear_selection()
        state.notify()

    def right_press(self, ev: ToolEvent) -> None:
        if self.drag is not None and self.drag.session is not None:
            self.drag.session.cancel()
        self.drag = None
        self.marquee_end = None
        self.state.active_drag = None
        self.state.clear_selection()
        self.state.notify()

    def cancel(self) -> None:
        if self.drag is not None and self.drag.session is not None:
            self.drag.session.cancel()
        self.drag = None
        self.marquee_end = None
        self.state.active_drag = None

    def draw_overlay(self, painter, to_screen) -> None:
        d = self.drag
        if d is not None and d.mode == "marquee" and self.marquee_end is not None:
            painter.setPen(self._pen(dash=True))
            a, b = to_screen(d.start), to_screen(self.marquee_end)
            painter.drawRect(min(a.x(), b.x()), min(a.y(), b.y()),
                             abs(b.x() - a.x()), abs(b.y() - a.y()))
        box = self.state.selection_box
        if box is not None:
            x0, y0, x1, y1 = box
            painter.setPen(self._pen(QColor(0, 0, 0), dash=True))
            a, b = to_screen(Vec2(x0, y0)), to_screen(Vec2(x1, y1))
            painter.drawRect(a.x(), a.y(), b.x() - a.x(), b.y() - a.y())
            r = self.HANDLE_PX / 2 + 2
            painter.setPen(self._pen(QColor(0, 0, 0), 1))
            for name, corner in self._box_handles().items():
                c = to_screen(corner)
                painter.setBrush(QColor(255, 220, 0))
                painter.drawEllipse(c, r, r)
                rp = self._rotate_handle_pos(name, corner, 10)
                rc = to_screen(rp)
                painter.setBrush(QColor(120, 200, 255))
                painter.drawRect(int(rc.x() - 4), int(rc.y() - 4), 8, 8)
            painter.setBrush(Qt.BrushStyle.NoBrush)


# --------------------------------------------------------------- raster
class BrushTool(Tool):
    name, label, shortcut = "brush", "Brush (raster)", "B"
    status_hint = "Paint into the active raster layer."
    wants_raster = True
    erase = False

    def __init__(self, state):
        super().__init__(state)
        self.session = None
        self.last: Vec2 | None = None

    def press(self, ev: ToolEvent) -> None:
        layer = self.project.active_layer
        if not isinstance(layer, RasterLayer):
            return
        self.session = self.project.edit_raster()
        self.last = ev.pos
        self._paint(ev.pos, ev.pos)

    def move(self, ev: ToolEvent) -> None:
        if self.session is not None and self.last is not None:
            self._paint(self.last, ev.pos)
            self.last = ev.pos

    def _paint(self, a: Vec2, b: Vec2) -> None:
        from animengine.render import qcolor, qimage_from_raster, raster_from_qimage

        layer = self.project.active_layer
        kf = layer.keyframes.get(self.project.current_frame) or layer.ensure_keyframe(
            self.project.current_frame)
        pl = kf.placement
        image = self.session.image
        qimg = qimage_from_raster(image)
        painter = QPainter(qimg)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self.erase:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.scale(1 / pl.scale.x, 1 / pl.scale.y)
            painter.translate(-pl.pos.x, -pl.pos.y)
            pen = QPen(qcolor(self.state.stroke_color), self.state.brush_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
        finally:
            painter.end()
        image.pixels = raster_from_qimage(qimg)

    def release(self, ev: ToolEvent) -> None:
        if self.session is not None:
            self.session.commit("Erase (raster)" if self.erase else "Brush stroke")
            self.session = None
        self.last = None

    def cancel(self) -> None:
        if self.session is not None:
            self.session.cancel()
            self.session = None
        self.last = None


class RasterEraserTool(BrushTool):
    name, label, shortcut = "rerase", "Eraser (raster)", "K"
    status_hint = "Erase pixels from the active raster layer."
    erase = True


class RasterMoveTool(Tool):
    name, label, shortcut = "rmove", "Move bitmap", "M"
    status_hint = ("Drag to move the raster layer. Shift-drag scales, "
                   "Alt-drag rotates.")
    wants_raster = True

    def __init__(self, state):
        super().__init__(state)
        self.session = None
        self.start: Vec2 | None = None
        self.orig = None

    def press(self, ev: ToolEvent) -> None:
        layer = self.project.active_layer
        if not isinstance(layer, RasterLayer):
            return
        try:
            self.session = self.project.edit_placement()
        except ValueError:
            return
        self.start = ev.pos
        self.orig = self.session.keyframe.placement.copy()

    def move(self, ev: ToolEvent) -> None:
        if self.session is None or self.start is None:
            return
        pl = self.session.keyframe.placement
        delta = ev.pos - self.start
        if ev.shift:
            factor = 1.0 + delta.x / 200.0
            factor = max(0.05, factor)
            pl.scale = Vec2(self.orig.scale.x * factor, self.orig.scale.y * factor)
            pl.pos = self.orig.pos
            pl.rotation_deg = self.orig.rotation_deg
        elif ev.alt:
            pl.rotation_deg = self.orig.rotation_deg + delta.x * 0.5
            pl.pos = self.orig.pos
            pl.scale = self.orig.scale
        else:
            pl.pos = self.orig.pos + delta
            pl.scale = self.orig.scale
            pl.rotation_deg = self.orig.rotation_deg

    def release(self, ev: ToolEvent) -> None:
        if self.session is not None:
            self.session.commit("Transform bitmap")
            self.session = None

    def cancel(self) -> None:
        if self.session is not None:
            self.session.cancel()
            self.session = None


ALL_TOOLS: list[type[Tool]] = [
    SelectTool, LineTool, RectTool, CurveTool, PolylineTool, SmoothPenTool,
    FillTool, AddPointTool, ScissorsTool, StyleTool, PickerTool, EraserTool,
    BrushTool, RasterEraserTool, RasterMoveTool,
]
