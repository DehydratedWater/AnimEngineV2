"""Importer for the original AnimEngine BETA 1.3 ``.ae`` text format.

The format is whitespace-tokenized with literal (misspelled) keywords:
ANIMATION / RESOLUTION / LENGHT / FRAME / QUENETAB / OBJTAB / OBJ / POINTS /
CONNECTIONES / POLYGONS / BITMAPTAB / BITMAPS. Every frame is a full scene
snapshot; we import each frame as HOLD keyframes so playback matches the
original exactly (no tweening is invented for old projects).

An older variant (no QUENETAB/BITMAPTAB/BITMAPS, COLORPOINTS instead of
POLYGONS) is also handled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from animengine.core import (
    Color,
    ConnKind,
    Document,
    FillEdge,
    Interp,
    Placement,
    RasterImage,
    Shape,
    Vec2,
)

_KEYWORDS = {
    "FRAME", "QUENETAB", "OBJTAB", "OBJ", "POINTS", "CONNECTIONES",
    "POLYGONS", "COLORPOINTS", "BITMAPTAB", "BITMAPS", "LENGHT", "AnimEngine",
}


class _Tokens:
    def __init__(self, text: str):
        self.toks = text.split()
        self.i = 0

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> str:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect(self, keyword: str) -> None:
        tok = self.next()
        if tok != keyword:
            raise ValueError(f"expected {keyword!r}, got {tok!r} at token {self.i}")

    def accept(self, keyword: str) -> bool:
        if self.peek() == keyword:
            self.i += 1
            return True
        return False

    def int(self) -> int:
        return int(self.next())

    def float(self) -> float:
        return float(self.next())

    def bool(self) -> bool:
        return self.next() == "true"

    def skip_until_keyword(self) -> None:
        while self.peek() is not None and self.peek() not in _KEYWORDS:
            self.i += 1


@dataclass
class _FrameObj:
    shape: Shape
    # v1 file index -> our stable id (identical numbering is used on purpose)
    point_ids: list[int] = field(default_factory=list)
    conn_ids: list[int] = field(default_factory=list)


@dataclass
class _FrameBitmap:
    texture_index: int
    placement: Placement


@dataclass
class _Frame:
    quene: list[tuple[bool, int]] = field(default_factory=list)  # (is_object, index)
    objs: list[_FrameObj] = field(default_factory=list)
    bitmaps: list[_FrameBitmap] = field(default_factory=list)


def load_legacy_ae(path: str | Path) -> Document:
    path = Path(path)
    t = _Tokens(path.read_text(errors="replace"))

    t.expect("ANIMATION")
    t.next()  # stored name (a single token in v1)
    t.expect("RESOLUTION")
    width, height = t.int(), t.int()
    t.expect("LENGHT")
    frame_count = t.int()

    frames = [_parse_frame(t) for _ in range(frame_count)]
    textures = _parse_textures(t)

    doc = Document(width=width, height=height, fps=30.0)
    doc.name = path.stem
    doc.length = max(1, frame_count)
    _build_layers(doc, frames, textures, base_dir=path.parent)
    return doc


def _parse_frame(t: _Tokens) -> _Frame:
    fr = _Frame()
    t.expect("FRAME")
    if t.accept("QUENETAB"):
        t.expect("LENGHT")
        n = t.int()
        for _ in range(n):
            t.expect("Q")
            fr.quene.append((t.bool(), t.int()))
    t.expect("OBJTAB")
    t.expect("LENGHT")
    obj_count = t.int()
    for _ in range(obj_count):
        fr.objs.append(_parse_obj(t))
    if t.accept("BITMAPTAB"):
        t.expect("LENGHT")
        n = t.int()
        for _ in range(n):
            t.expect("BITMAP")
            tex = t.int()
            x, y = t.float(), t.float()
            sx, sy = t.float(), t.float()
            angle = t.float()
            fr.bitmaps.append(
                _FrameBitmap(tex, Placement(Vec2(x, y), Vec2(sx, sy), angle))
            )
    if not fr.quene:  # old format: draw order = object order
        fr.quene = [(True, i) for i in range(len(fr.objs))]
        fr.quene += [(False, i) for i in range(len(fr.bitmaps))]
    return fr


def _parse_obj(t: _Tokens) -> _FrameObj:
    t.expect("OBJ")
    shape = Shape()
    out = _FrameObj(shape)

    t.expect("POINTS")
    n_points = t.int()
    for i in range(n_points):
        x, y = t.float(), t.float()
        out.point_ids.append(shape.add_point(Vec2(x, y), id=i + 1).id)

    t.expect("CONNECTIONES")
    n_conns = t.int()
    raw_conns = []
    for _ in range(n_conns):
        is_arc, is_double = t.bool(), t.bool()
        p1, p2, p3, p4 = t.int(), t.int(), t.int(), t.int()
        size = t.float()
        color_kw = t.next()
        if color_kw == "COLOR":
            color = Color(t.int(), t.int(), t.int(), t.int())
        else:  # NOCOLOR
            color = Color(0, 0, 0, 255)
        raw_conns.append((is_arc, is_double, p1, p2, p3, p4, size, color))

    def pid(idx: int) -> int:
        return out.point_ids[idx]

    for is_arc, is_double, p1, p2, p3, p4, size, color in raw_conns:
        kind = ConnKind.LINE
        c1 = c2 = None
        if is_double:
            # v1 cubic renders CubicCurve2D(P1, P4, P3, P2): P4 = ctrl near P1
            kind = ConnKind.CUBIC
            c1, c2 = pid(p4), pid(p3)
            shape.points[c1].is_control = True
            shape.points[c1].anchor = pid(p1)
            shape.points[c2].is_control = True
            shape.points[c2].anchor = pid(p2)
        elif is_arc:
            kind = ConnKind.QUAD
            c1 = pid(p3)
            shape.points[c1].is_control = True
            shape.points[c1].anchor = pid(p1)
        conn = shape.add_connection(pid(p1), pid(p2), kind=kind, c1=c1, c2=c2,
                                    width=size, color=color)
        out.conn_ids.append(conn.id)

    kw = t.next()
    if kw == "POLYGONS":
        n_polys = t.int()
        for _ in range(n_polys):
            _parse_polygon(t, out)
    elif kw == "COLORPOINTS":
        n = t.int()
        if n > 0:  # ancient fill-seed format we can't fully reconstruct
            t.skip_until_keyword()
    else:
        raise ValueError(f"expected POLYGONS/COLORPOINTS, got {kw!r}")
    return out


def _parse_polygon(t: _Tokens, out: _FrameObj) -> None:
    """Parse one fill. The shapeConnector records carry direction quirks that
    vary between loops in real v1 files, so we take the authoritative CONN
    boundary-index list and rebuild ordered loops from adjacency instead."""
    shape = out.shape
    t.expect("COLOR")
    color = Color(t.int(), t.int(), t.int(), t.int())
    t.expect("POLYGON")
    n_shape = t.int()
    for _ in range(n_shape):
        for _ in range(4):
            t.bool()  # isArc isDoubleArc fromLeft polygonEnd
        for _ in range(5):
            t.int()  # connIndex P1 P2 P3 P4
    t.expect("CONN")
    n_idx = t.int()
    conn_ids = []
    for _ in range(n_idx):
        idx = t.int()
        if 0 <= idx < len(out.conn_ids):
            conn_ids.append(out.conn_ids[idx])
    loops = _loops_from_connections(shape, conn_ids)
    if loops:
        shape.add_fill(loops, color)


def _loops_from_connections(shape: Shape, conn_ids: list[int]) -> list[list[FillEdge]]:
    """Order a set of boundary connections into closed directed loops.

    Loops are sorted by descending flattened area so the outline comes first
    and holes after (matching Fill's outline-first convention)."""
    unused = set(conn_ids)
    loops: list[list[FillEdge]] = []
    while unused:
        start = unused.pop()
        conn = shape.connections[start]
        loop = [FillEdge(start, False)]
        start_point, cursor = conn.p1, conn.p2
        for _ in range(len(conn_ids)):
            if cursor == start_point:
                break
            nxt = next(
                (cid for cid in unused
                 if cursor in shape.connections[cid].endpoints()),
                None,
            )
            if nxt is None:
                break
            unused.discard(nxt)
            nc = shape.connections[nxt]
            loop.append(FillEdge(nxt, reversed=nc.p2 == cursor))
            cursor = nc.other(cursor)
        if cursor == start_point and len(loop) >= 2:
            loops.append(loop)

    def loop_area(loop: list[FillEdge]) -> float:
        poly: list[Vec2] = []
        for e in loop:
            pts = shape.sample_connection(shape.connections[e.conn_id])
            poly.extend(reversed(pts[1:]) if e.reversed else pts[:-1])
        return abs(sum(a.cross(b) for a, b in zip(poly, poly[1:] + poly[:1], strict=True)) / 2)

    loops.sort(key=loop_area, reverse=True)
    return loops


def _parse_textures(t: _Tokens) -> list[tuple[str, str]]:
    textures: list[tuple[str, str]] = []
    if t.accept("BITMAPS"):
        t.expect("LENGHT")
        n = t.int()
        for _ in range(n):
            name = t.next()
            tex_path = t.next()
            textures.append((name, tex_path))
    return textures


def _load_texture(doc: Document, name: str, tex_path: str, base_dir: Path) -> RasterImage:
    candidates = [Path(tex_path), base_dir / Path(tex_path.replace("\\", "/")).name]
    for cand in candidates:
        try:
            if cand.is_file():
                pil = Image.open(cand).convert("RGBA")
                img = RasterImage(0, name, np.asarray(pil, np.uint8).copy(), str(cand))
                return doc.register_image(img)
        except OSError:
            continue
    # missing texture: checkered placeholder so the project still opens
    px = np.zeros((64, 64, 4), np.uint8)
    px[::2, ::2] = px[1::2, 1::2] = [200, 200, 200, 255]
    px[::2, 1::2] = px[1::2, ::2] = [120, 120, 120, 255]
    img = RasterImage(0, name, px, tex_path)
    return doc.register_image(img)


def _build_layers(doc: Document, frames: list[_Frame],
                  textures: list[tuple[str, str]], base_dir: Path) -> None:
    images = [_load_texture(doc, name, p, base_dir) for name, p in textures]

    # layer identity = (is_object, index); ordered by first appearance in queneTab
    order: list[tuple[bool, int]] = []
    for fr in frames:
        for key in fr.quene:
            if key not in order:
                order.append(key)

    layers = {}
    for is_object, idx in order:
        if is_object:
            layer = doc.add_vector_layer(f"Layer {len(doc.layers) + 1}")
            layer.keyframes.clear()
        else:
            layer = doc.add_raster_layer(f"Bitmap {len(doc.layers) + 1}")
        layers[(is_object, idx)] = layer

    for frame_no, fr in enumerate(frames):
        present = set(fr.quene)
        for key, layer in layers.items():
            is_object, idx = key
            if key in present:
                if is_object and idx < len(fr.objs):
                    layer.set_keyframe(frame_no, fr.objs[idx].shape, Interp.HOLD)
                elif not is_object and idx < len(fr.bitmaps):
                    bmp = fr.bitmaps[idx]
                    if 0 <= bmp.texture_index < len(images):
                        layer.set_keyframe(frame_no, images[bmp.texture_index].id,
                                           bmp.placement, Interp.HOLD)
            elif layer.keyframes and frame_no not in layer.keyframes:
                # layer disappears this frame: hide it (v1 simply had no entry)
                last = layer.prev_key_frame(frame_no)
                if last is not None:
                    kf = layer.keyframes[last]
                    if hasattr(kf, "shape"):
                        if not kf.shape.is_empty():
                            layer.set_keyframe(frame_no, Shape(), Interp.HOLD)
                    else:
                        hidden = Placement(kf.placement.pos, kf.placement.scale,
                                           kf.placement.rotation_deg, 0.0)
                        layer.set_keyframe(frame_no, kf.image_id, hidden, Interp.HOLD)
