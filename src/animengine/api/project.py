"""High-level programmatic API.

Everything the GUI tools and the MCP server do goes through AnimProject, so
every mutation is undoable and works headless. Coordinates are document
pixels; colors are hex strings or Color objects.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from animengine.audio import load_audio_clip
from animengine.core import (
    Color,
    Command,
    Document,
    Interp,
    Placement,
    RasterLayer,
    Shape,
    Vec2,
    VectorLayer,
)
from animengine.core.commands import FunctionCommand
from animengine.core.layers import Layer
from animengine.io import load_legacy_ae, load_project, save_project, shape_to_dict
from animengine.io.export import (
    export_gif,
    export_image,
    export_png_sequence,
    export_sprite_sheet,
    export_svg,
    export_video,
)

SNAP_RADIUS = 15.0  # v1's screen-space snap radius, in document px


def _color(c: str | Color | None, default: Color = Color(0, 0, 0)) -> Color:
    if c is None:
        return default
    if isinstance(c, Color):
        return c
    return Color.from_hex(c)


class _ShapeEdit(Command):
    """Undoable mutation of one vector keyframe's shape."""

    def __init__(self, label: str, layer: VectorLayer, frame: int,
                 fn: Callable[[Shape], Any]):
        self.label = label
        self._layer = layer
        self._frame = frame
        self._fn = fn
        self._had_kf = False
        self._before: Shape | None = None
        self._after: Shape | None = None

    def do(self) -> Any:
        kf = self._layer.keyframes.get(self._frame)
        self._had_kf = kf is not None
        self._before = kf.shape.clone() if kf else None
        kf = self._layer.ensure_keyframe(self._frame)
        result = self._fn(kf.shape)
        self._after = kf.shape.clone()
        return result

    def redo(self) -> Any:
        kf = self._layer.ensure_keyframe(self._frame)
        kf.shape = self._after.clone()
        return None

    def undo(self) -> None:
        if not self._had_kf:
            self._layer.keyframes.pop(self._frame, None)
        elif self._before is not None:
            self._layer.keyframes[self._frame].shape = self._before.clone()


class AnimProject:
    """A live animation project: document + cursor state + undoable operations."""

    def __init__(self, width: int = 1280, height: int = 720, fps: float = 30.0,
                 doc: Document | None = None):
        self.doc = doc if doc is not None else Document(width, height, fps)
        if not self.doc.layers:
            self.doc.add_vector_layer("Layer 1")
        self.current_frame = 0
        self.active_layer_id = self.doc.layers[-1].id
        self.path: Path | None = None

    # ------------------------------------------------------------- files
    @classmethod
    def open(cls, path: str | Path) -> AnimProject:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".aep2":
            doc = load_project(path)
        elif suffix in (".ae", ".txt") or suffix == "":
            doc = load_legacy_ae(path)
        elif suffix == ".svg":
            from animengine.io.importers import import_svg
            doc = import_svg(path)
        elif suffix == ".json":
            from animengine.io.importers import import_lottie
            doc = import_lottie(path)
        elif suffix == ".gif":
            from animengine.io.importers import import_gif
            doc = import_gif(path)
        else:
            raise ValueError(f"don't know how to open {path.name!r}")
        proj = cls(doc=doc)
        proj.path = path if suffix == ".aep2" else None
        return proj

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no save path set — pass one")
        self.path = save_project(self.doc, target)
        return self.path

    # ------------------------------------------------------- undo / redo
    def undo(self) -> str | None:
        return self.doc.commands.undo()

    def redo(self) -> str | None:
        return self.doc.commands.redo()

    # ----------------------------------------------------------- layers
    @property
    def active_layer(self) -> Layer:
        return self.doc.layer(self.active_layer_id)

    def _resolve_layer(self, layer_id: int | None) -> Layer:
        return self.doc.layer(layer_id) if layer_id is not None else self.active_layer

    def _vector_layer(self, layer_id: int | None) -> VectorLayer:
        layer = self._resolve_layer(layer_id)
        if not isinstance(layer, VectorLayer):
            raise TypeError(f"layer {layer.id} ({layer.name}) is not a vector layer")
        if layer.locked:
            raise PermissionError(f"layer {layer.id} ({layer.name}) is locked")
        return layer

    def add_layer(self, kind: str = "vector", name: str | None = None) -> Layer:
        def make() -> Layer:
            if kind == "vector":
                return self.doc.add_vector_layer(name)
            return self.doc.add_raster_layer(name)

        holder: dict[str, Layer] = {}

        def do() -> Layer:
            if "layer" in holder:  # redo: reinsert the same object
                self.doc.layers.append(holder["layer"])
            else:
                holder["layer"] = make()
            self.active_layer_id = holder["layer"].id
            return holder["layer"]

        def undo() -> None:
            self.doc.remove_layer(holder["layer"].id)
            if self.active_layer_id == holder["layer"].id and self.doc.layers:
                self.active_layer_id = self.doc.layers[-1].id

        return self.doc.commands.push(FunctionCommand(f"Add {kind} layer", do, undo))

    def remove_layer(self, layer_id: int) -> None:
        state: dict[str, Any] = {}

        def do() -> None:
            state["index"] = self.doc.layer_index(layer_id)
            state["layer"] = self.doc.remove_layer(layer_id)
            if self.active_layer_id == layer_id and self.doc.layers:
                self.active_layer_id = self.doc.layers[-1].id

        def undo() -> None:
            self.doc.layers.insert(state["index"], state["layer"])

        self.doc.commands.push(FunctionCommand("Remove layer", do, undo))

    def rename_layer(self, layer_id: int, name: str) -> None:
        layer = self.doc.layer(layer_id)
        old = layer.name
        self.doc.run("Rename layer",
                     lambda: setattr(layer, "name", name),
                     lambda: setattr(layer, "name", old))

    def set_layer_props(self, layer_id: int, *, visible: bool | None = None,
                        locked: bool | None = None, opacity: float | None = None) -> None:
        layer = self.doc.layer(layer_id)
        old = (layer.visible, layer.locked, layer.opacity)

        def do() -> None:
            if visible is not None:
                layer.visible = visible
            if locked is not None:
                layer.locked = locked
            if opacity is not None:
                layer.opacity = max(0.0, min(1.0, opacity))

        def undo() -> None:
            layer.visible, layer.locked, layer.opacity = old

        self.doc.run("Layer properties", do, undo)

    def move_layer(self, layer_id: int, new_index: int) -> None:
        old_index = self.doc.layer_index(layer_id)
        self.doc.run("Reorder layer",
                     lambda: self.doc.move_layer(layer_id, new_index),
                     lambda: self.doc.move_layer(layer_id, old_index))

    def set_active_layer(self, layer_id: int) -> None:
        self.doc.layer(layer_id)  # validate
        self.active_layer_id = layer_id

    # ------------------------------------------------------------ frames
    def set_frame(self, frame: int) -> int:
        self.current_frame = max(0, frame)
        self.doc.extend_to(self.current_frame)
        return self.current_frame

    def next_frame(self, *, extend: bool = True) -> int:
        nxt = self.current_frame + 1
        if not extend:
            nxt = self.doc.clamp_frame(nxt)
        return self.set_frame(nxt)

    def prev_frame(self) -> int:
        self.current_frame = max(0, self.current_frame - 1)
        return self.current_frame

    def copy_frame_forward(self, layer_id: int | None = None) -> int:
        """v1's `c-->`: duplicate current state of layer(s) onto the next frame."""
        src = self.current_frame
        dst = src + 1
        layers = [self._resolve_layer(layer_id)] if layer_id is not None else self.doc.layers
        state: dict[int, Any] = {}

        def do() -> int:
            for layer in layers:
                state[layer.id] = layer.keyframes.get(dst)
                self.doc.copy_keyframe_forward(layer.id, src, dst)
            self.current_frame = dst
            return dst

        def undo() -> None:
            for layer in layers:
                if state.get(layer.id) is None:
                    layer.keyframes.pop(dst, None)
                else:
                    layer.keyframes[dst] = state[layer.id]
            self.current_frame = src

        return self.doc.commands.push(FunctionCommand("Copy frame forward", do, undo))

    def add_keyframe(self, layer_id: int | None = None, frame: int | None = None) -> None:
        layer = self._resolve_layer(layer_id)
        frame = self.current_frame if frame is None else frame

        def do() -> None:
            layer.ensure_keyframe(frame)
            self.doc.extend_to(frame)

        def undo() -> None:
            layer.keyframes.pop(frame, None)

        if frame not in layer.keyframes:
            self.doc.run("Add keyframe", do, undo)

    def remove_keyframe(self, layer_id: int | None = None, frame: int | None = None) -> None:
        layer = self._resolve_layer(layer_id)
        frame = self.current_frame if frame is None else frame
        kf = layer.keyframes.get(frame)
        if kf is None:
            return
        self.doc.run("Remove keyframe",
                     lambda: layer.keyframes.pop(frame, None),
                     lambda: layer.keyframes.__setitem__(frame, kf))

    def set_keyframe_interp(self, interp: str, layer_id: int | None = None,
                            frame: int | None = None) -> None:
        layer = self._resolve_layer(layer_id)
        frame = self.current_frame if frame is None else frame
        kf = layer.keyframes.get(frame)
        if kf is None:
            raise KeyError(f"no keyframe at frame {frame}")
        new = Interp(interp)
        old = kf.interp
        self.doc.run("Set interpolation",
                     lambda: setattr(kf, "interp", new),
                     lambda: setattr(kf, "interp", old))

    def set_length(self, length: int) -> None:
        old = self.doc.length
        new = max(1, length)
        self.doc.run("Set length",
                     lambda: setattr(self.doc, "length", new),
                     lambda: setattr(self.doc, "length", old))

    # ----------------------------------------------------------- drawing
    def _edit(self, label: str, fn: Callable[[Shape], Any],
              layer_id: int | None = None, frame: int | None = None) -> Any:
        layer = self._vector_layer(layer_id)
        frame = self.current_frame if frame is None else frame
        self.doc.extend_to(frame)
        return self.doc.commands.push(_ShapeEdit(label, layer, frame, fn))

    def add_line(self, x1: float, y1: float, x2: float, y2: float, *,
                 width: float = 3.0, color: str | Color | None = None,
                 snap: bool = True, layer_id: int | None = None,
                 frame: int | None = None) -> dict:
        col = _color(color)
        radius = SNAP_RADIUS if snap else 0.0

        def fn(shape: Shape) -> dict:
            conn = shape.add_line(Vec2(x1, y1), Vec2(x2, y2), width=width,
                                  color=col, snap_radius=radius)
            shape.insert_intersections([conn.id])
            return {"connection_id": conn.id, "p1": conn.p1, "p2": conn.p2}

        return self._edit("Add line", fn, layer_id, frame)

    def add_curve(self, x1: float, y1: float, cx1: float, cy1: float,
                  cx2: float, cy2: float, x2: float, y2: float, *,
                  width: float = 3.0, color: str | Color | None = None,
                  snap: bool = True, layer_id: int | None = None,
                  frame: int | None = None) -> dict:
        col = _color(color)
        radius = SNAP_RADIUS if snap else 0.0

        def fn(shape: Shape) -> dict:
            conn = shape.add_cubic_curve(Vec2(x1, y1), Vec2(cx1, cy1), Vec2(cx2, cy2),
                                         Vec2(x2, y2), width=width, color=col,
                                         snap_radius=radius)
            shape.insert_intersections([conn.id])
            return {"connection_id": conn.id, "p1": conn.p1, "p2": conn.p2}

        return self._edit("Add curve", fn, layer_id, frame)

    def add_rect(self, x: float, y: float, w: float, h: float, *,
                 width: float = 3.0, color: str | Color | None = None,
                 layer_id: int | None = None, frame: int | None = None) -> dict:
        col = _color(color)

        def fn(shape: Shape) -> dict:
            pts = [Vec2(x, y), Vec2(x + w, y), Vec2(x + w, y + h), Vec2(x, y + h)]
            ids = [shape.add_point(p).id for p in pts]
            conns = [
                shape.add_connection(ids[i], ids[(i + 1) % 4], width=width, color=col).id
                for i in range(4)
            ]
            shape.insert_intersections(conns)
            return {"point_ids": ids, "connection_ids": conns}

        return self._edit("Add rectangle", fn, layer_id, frame)

    def add_polyline(self, points: Iterable[tuple[float, float]], *, close: bool = False,
                     width: float = 3.0, color: str | Color | None = None,
                     snap: bool = True, layer_id: int | None = None,
                     frame: int | None = None) -> dict:
        pts = [Vec2(x, y) for x, y in points]
        if len(pts) < 2:
            raise ValueError("need at least two points")
        col = _color(color)
        radius = SNAP_RADIUS if snap else 0.0

        def fn(shape: Shape) -> dict:
            first = shape.find_or_add_point(pts[0], radius)
            created = {first.id}
            prev = first
            conn_ids = []
            for i, p in enumerate(pts[1:], start=1):
                # like v1's freehand: only the stroke's endpoints snap
                if i == len(pts) - 1:
                    nxt = shape.find_or_add_point(p, radius, exclude=created)
                else:
                    nxt = shape.add_point(p)
                created.add(nxt.id)
                if nxt.id != prev.id:
                    conn_ids.append(shape.add_connection(prev.id, nxt.id,
                                                         width=width, color=col).id)
                prev = nxt
            if close and prev.id != first.id:
                conn_ids.append(shape.add_connection(prev.id, first.id,
                                                     width=width, color=col).id)
            shape.insert_intersections(conn_ids)
            return {"connection_ids": conn_ids}

        return self._edit("Add polyline", fn, layer_id, frame)

    def add_point(self, x: float, y: float, *, layer_id: int | None = None,
                  frame: int | None = None) -> int:
        return self._edit("Add point", lambda s: s.add_point(Vec2(x, y)).id,
                          layer_id, frame)

    def connect_points(self, p1: int, p2: int, *, width: float = 3.0,
                       color: str | Color | None = None, layer_id: int | None = None,
                       frame: int | None = None) -> int:
        col = _color(color)

        def fn(shape: Shape) -> int:
            conn = shape.add_connection(p1, p2, width=width, color=col)
            shape.insert_intersections([conn.id])
            return conn.id

        return self._edit("Connect points", fn, layer_id, frame)

    def move_point(self, point_id: int, x: float, y: float, *,
                   merge: bool = True, layer_id: int | None = None,
                   frame: int | None = None) -> None:
        def fn(shape: Shape) -> None:
            if point_id not in shape.points:
                raise KeyError(f"no point {point_id}")
            # control handles follow their anchor like v1's TechPoints
            old = shape.pos(point_id)
            delta = Vec2(x, y) - old
            shape.move_point(point_id, Vec2(x, y))
            for ctrl in shape.controls_of(point_id):
                shape.move_point(ctrl.id, ctrl.pos + delta)
            if merge and not shape.points[point_id].is_control:
                target = None
                for p in shape.anchor_points():
                    if p.id != point_id and p.pos.distance_to(Vec2(x, y)) <= SNAP_RADIUS:
                        target = p
                        break
                if target is not None:
                    shape.merge_points(target.id, point_id)

        self._edit("Move point", fn, layer_id, frame)

    def move_points(self, offsets: dict[int, tuple[float, float]], *,
                    layer_id: int | None = None, frame: int | None = None) -> None:
        """Move many points at once (absolute positions)."""
        def fn(shape: Shape) -> None:
            for pid, (x, y) in offsets.items():
                if pid in shape.points:
                    shape.move_point(pid, Vec2(x, y))

        self._edit("Move points", fn, layer_id, frame)

    def transform_points(self, point_ids: Iterable[int], *, dx: float = 0.0, dy: float = 0.0,
                         scale_x: float = 1.0, scale_y: float = 1.0,
                         rotate_deg: float = 0.0,
                         pivot: tuple[float, float] | None = None,
                         layer_id: int | None = None, frame: int | None = None) -> None:
        """Translate/scale/rotate a set of points (the transform-box operation)."""
        ids = list(point_ids)

        def fn(shape: Shape) -> None:
            pts = [shape.points[i] for i in ids if i in shape.points]
            # include control handles of selected anchors
            extra = [c for p in pts for c in shape.controls_of(p.id)
                     if c.id not in {q.id for q in pts}]
            pts += extra
            if not pts:
                return
            if pivot is None:
                cx = sum(p.pos.x for p in pts) / len(pts)
                cy = sum(p.pos.y for p in pts) / len(pts)
            else:
                cx, cy = pivot
            center = Vec2(cx, cy)
            for p in pts:
                v = p.pos - center
                v = Vec2(v.x * scale_x, v.y * scale_y)
                if rotate_deg:
                    v = v.rotated(math.radians(rotate_deg))
                p.pos = center + v + Vec2(dx, dy)

        self._edit("Transform points", fn, layer_id, frame)

    def remove_point(self, point_id: int, *, layer_id: int | None = None,
                     frame: int | None = None) -> None:
        self._edit("Remove point", lambda s: s.remove_point(point_id), layer_id, frame)

    def remove_connection(self, conn_id: int, *, layer_id: int | None = None,
                          frame: int | None = None) -> None:
        self._edit("Remove connection", lambda s: s.remove_connection(conn_id),
                   layer_id, frame)

    def remove_fill(self, fill_id: int, *, layer_id: int | None = None,
                    frame: int | None = None) -> None:
        self._edit("Remove fill", lambda s: s.remove_fill(fill_id), layer_id, frame)

    def fill_region(self, x: float, y: float, color: str | Color, *,
                    layer_id: int | None = None, frame: int | None = None) -> int | None:
        """Bucket fill: fill (or recolor) the enclosed region containing (x, y)."""
        col = _color(color, Color(255, 255, 255))
        pos = Vec2(x, y)

        def fn(shape: Shape) -> int | None:
            for f in shape.fills.values():  # recolor existing fill first
                if shape.fill_contains(f, pos):
                    f.color = col
                    return f.id
            loops = shape.detect_region(pos)
            if loops is None:
                return None
            return shape.add_fill(loops, col).id

        return self._edit("Fill region", fn, layer_id, frame)

    def set_connection_style(self, conn_id: int, *, width: float | None = None,
                             color: str | Color | None = None,
                             layer_id: int | None = None,
                             frame: int | None = None) -> None:
        def fn(shape: Shape) -> None:
            conn = shape.connections[conn_id]
            if width is not None:
                conn.width = width
            if color is not None:
                conn.color = _color(color)

        self._edit("Line style", fn, layer_id, frame)

    def cut_connection_at(self, x: float, y: float, *, max_dist: float = SNAP_RADIUS,
                          layer_id: int | None = None,
                          frame: int | None = None) -> int | None:
        """Split the nearest connection at (x, y); returns the new point id."""
        pos = Vec2(x, y)

        def fn(shape: Shape) -> int | None:
            conn = shape.nearest_connection(pos, max_dist=max_dist)
            if conn is None:
                return None
            mid, _, _ = shape.split_connection(conn.id, pos)
            return mid.id

        return self._edit("Cut connection", fn, layer_id, frame)

    def erase_at(self, x: float, y: float, radius: float, *,
                 layer_id: int | None = None, frame: int | None = None) -> int:
        """Delete all anchor points within radius (v1 eraser). Returns count."""
        pos = Vec2(x, y)

        def fn(shape: Shape) -> int:
            doomed = [p.id for p in shape.anchor_points()
                      if p.pos.distance_to(pos) <= radius]
            for pid in doomed:
                shape.remove_point(pid)
            return len(doomed)

        return self._edit("Erase", fn, layer_id, frame)

    # ------------------------------------------------------------ raster
    def paint_stroke(self, points: Iterable[tuple[float, float]], *,
                     width: float = 8.0, color: str | Color | None = None,
                     erase: bool = False, layer_id: int | None = None,
                     frame: int | None = None) -> None:
        """Paint (or erase) a polyline stroke into a raster layer's image."""
        from animengine.render import ensure_gui_app, qcolor, qimage_from_raster, raster_from_qimage

        layer = self._resolve_layer(layer_id)
        if not isinstance(layer, RasterLayer):
            raise TypeError("paint_stroke needs a raster layer")
        frame = self.current_frame if frame is None else frame
        kf = layer.ensure_keyframe(frame)
        if kf is None:
            raise ValueError("raster layer has no image to paint on")
        image = self.doc.images[kf.image_id]
        before = image.pixels.copy()
        pts = [Vec2(x, y) for x, y in points]
        col = _color(color)

        def do() -> None:
            ensure_gui_app()
            from PySide6.QtCore import QPointF, Qt
            from PySide6.QtGui import QPainter, QPen

            qimg = qimage_from_raster(image)
            painter = QPainter(qimg)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                if erase:
                    painter.setCompositionMode(
                        QPainter.CompositionMode.CompositionMode_Clear)
                # map document coords into image space (inverse placement)
                pl = kf.placement
                painter.translate(-pl.pos.x / pl.scale.x, -pl.pos.y / pl.scale.y)
                painter.scale(1 / pl.scale.x, 1 / pl.scale.y)
                pen = QPen(qcolor(col), width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                if len(pts) == 1:
                    painter.drawPoint(QPointF(pts[0].x, pts[0].y))
                for a, b in zip(pts, pts[1:], strict=False):
                    painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
            finally:
                painter.end()
            image.pixels = raster_from_qimage(qimg)

        def undo() -> None:
            image.pixels = before.copy()

        self.doc.run("Erase stroke" if erase else "Paint stroke", do, undo)

    def move_raster(self, *, dx: float = 0.0, dy: float = 0.0,
                    scale_x: float | None = None, scale_y: float | None = None,
                    rotate_deg: float | None = None, opacity: float | None = None,
                    layer_id: int | None = None, frame: int | None = None) -> None:
        layer = self._resolve_layer(layer_id)
        if not isinstance(layer, RasterLayer):
            raise TypeError("move_raster needs a raster layer")
        frame = self.current_frame if frame is None else frame
        kf = layer.ensure_keyframe(frame)
        if kf is None:
            raise ValueError("raster layer has no keyframe")
        old = kf.placement.copy()
        new = Placement(
            old.pos + Vec2(dx, dy),
            Vec2(scale_x if scale_x is not None else old.scale.x,
                 scale_y if scale_y is not None else old.scale.y),
            rotate_deg if rotate_deg is not None else old.rotation_deg,
            opacity if opacity is not None else old.opacity,
        )
        self.doc.run("Transform raster",
                     lambda: setattr(kf, "placement", new),
                     lambda: setattr(kf, "placement", old))

    def import_image(self, path: str | Path, *, x: float = 0.0, y: float = 0.0) -> Layer:
        import numpy as np
        from PIL import Image as PILImage

        from animengine.core import RasterImage

        path = Path(path)
        rgba = np.asarray(PILImage.open(path).convert("RGBA"), np.uint8).copy()
        img = self.doc.register_image(RasterImage(0, path.stem, rgba, str(path)))
        layer = self.doc.add_raster_layer(path.stem, image=img,
                                          placement=Placement(pos=Vec2(x, y)))
        self.active_layer_id = layer.id
        return layer

    def new_raster_layer(self, name: str | None = None, *, width: int | None = None,
                         height: int | None = None) -> Layer:
        img = self.doc.new_image(name or "paint",
                                 width or self.doc.width, height or self.doc.height)
        layer = self.doc.add_raster_layer(name, image=img)
        self.active_layer_id = layer.id
        return layer

    # ------------------------------------------------------------- audio
    def add_audio(self, path: str | Path, *, start_frame: int = 0,
                  gain: float = 1.0):
        return load_audio_clip(self.doc, path, start_frame=start_frame, gain=gain)

    # ------------------------------------------------------- render/export
    def render_png(self, frame: int | None = None, *, scale: float = 1.0,
                   transparent: bool = False) -> bytes:
        from animengine.render import render_frame_png

        frame = self.current_frame if frame is None else frame
        return render_frame_png(self.doc, frame, scale=scale, transparent=transparent)

    def export(self, path: str | Path, *, kind: str | None = None, **kwargs) -> Path:
        """Export by kind or file extension: png/sequence/gif/mp4/webm/svg/spritesheet."""
        path = Path(path)
        kind = kind or path.suffix.lstrip(".").lower()
        match kind:
            case "png" | "image":
                return export_image(self.doc, kwargs.pop("frame", self.current_frame),
                                    path, **kwargs)
            case "sequence" | "pngseq":
                export_png_sequence(self.doc, path, **kwargs)
                return path
            case "gif":
                return export_gif(self.doc, path, **kwargs)
            case "mp4" | "webm" | "video":
                return export_video(self.doc, path, **kwargs)
            case "svg":
                return export_svg(self.doc, kwargs.pop("frame", self.current_frame), path)
            case "spritesheet" | "sheet":
                return export_sprite_sheet(self.doc, path, **kwargs)
            case _:
                raise ValueError(f"unknown export kind {kind!r}")

    # -------------------------------------------------------- inspection
    def scene_info(self, layer_id: int | None = None,
                   frame: int | None = None) -> dict:
        """Full geometry of one layer at a frame — the LLM's 'eyes' besides renders."""
        layer = self._resolve_layer(layer_id)
        frame = self.current_frame if frame is None else frame
        info: dict[str, Any] = {
            "layer_id": layer.id,
            "layer_name": layer.name,
            "kind": layer.kind.value,
            "frame": frame,
            "is_keyframe": frame in layer.keyframes,
            "keyframes": layer.key_frames_sorted(),
        }
        if isinstance(layer, VectorLayer):
            shape = layer.shape_at(frame)
            info["shape"] = shape_to_dict(shape) if shape is not None else None
        elif isinstance(layer, RasterLayer):
            state = layer.state_at(frame)
            if state:
                image = self.doc.images.get(state[0])
                info["image"] = {
                    "id": state[0],
                    "name": image.name if image else None,
                    "size": [image.width, image.height] if image else None,
                }
                pl = state[1]
                info["placement"] = {"x": pl.pos.x, "y": pl.pos.y, "sx": pl.scale.x,
                                     "sy": pl.scale.y, "rot": pl.rotation_deg,
                                     "opacity": pl.opacity}
        return info

    def summary(self) -> dict:
        s = self.doc.summary()
        s["current_frame"] = self.current_frame
        s["active_layer_id"] = self.active_layer_id
        s["undo_depth"] = self.doc.commands.depth
        return s
