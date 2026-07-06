"""Static SVG importer: paths, basic shapes, groups with transforms.

Produces one vector layer. Supported: <path> (M L H V C S Q T A Z, absolute +
relative), <rect> <circle> <ellipse> <line> <polyline> <polygon>, nested <g>
transforms (translate/scale/rotate/matrix), fill/stroke/stroke-width via
attributes or inline style. Elliptical arcs are flattened to short lines.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from animengine.core import Color, ConnKind, Document, FillEdge, Shape, Transform2D, Vec2

_NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "cyan": "#00ffff", "magenta": "#ff00ff",
    "gray": "#808080", "grey": "#808080", "orange": "#ffa500", "purple": "#800080",
    "brown": "#a52a2a", "pink": "#ffc0cb", "lime": "#00ff00", "navy": "#000080",
}


def parse_color(s: str | None) -> Color | None:
    if not s or s.strip() in ("none", "transparent"):
        return None
    s = s.strip().lower()
    s = _NAMED_COLORS.get(s, s)
    if s.startswith("#"):
        return Color.from_hex(s)
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        vals = []
        for p in parts[:3]:
            vals.append(round(float(p[:-1]) * 2.55) if p.endswith("%") else round(float(p)))
        a = round(float(parts[3]) * 255) if len(parts) > 3 else 255
        return Color(*vals, a)
    return Color(0, 0, 0)


def _parse_transform(s: str | None) -> Transform2D:
    t = Transform2D()
    if not s:
        return t
    for name, args_s in re.findall(r"(\w+)\s*\(([^)]*)\)", s):
        args = [float(v) for v in re.split(r"[\s,]+", args_s.strip()) if v]
        if name == "translate":
            t = t @ Transform2D.translation(args[0], args[1] if len(args) > 1 else 0)
        elif name == "scale":
            t = t @ Transform2D.scaling(args[0], args[1] if len(args) > 1 else args[0])
        elif name == "rotate":
            pivot = Vec2(args[1], args[2]) if len(args) > 2 else None
            t = t @ Transform2D.rotation(math.radians(args[0]), around=pivot)
        elif name == "matrix" and len(args) == 6:
            a, b, c, d, e, f = args
            t = t @ Transform2D(a, b, c, d, e, f)
    return t


_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


class _StyleCtx:
    def __init__(self, fill: Color | None, stroke: Color | None, stroke_w: float,
                 transform: Transform2D):
        self.fill = fill
        self.stroke = stroke
        self.stroke_w = stroke_w
        self.transform = transform

    def child(self, el: ET.Element) -> _StyleCtx:
        style = dict(
            item.split(":", 1)
            for item in (el.get("style") or "").split(";")
            if ":" in item
        )
        style = {k.strip(): v.strip() for k, v in style.items()}

        def attr(name: str) -> str | None:
            return style.get(name, el.get(name))

        fill = self.fill
        if attr("fill") is not None:
            fill = parse_color(attr("fill"))
        stroke = self.stroke
        if attr("stroke") is not None:
            stroke = parse_color(attr("stroke"))
        sw = self.stroke_w
        if attr("stroke-width") is not None:
            sw = float(re.sub(r"[a-z%]+$", "", attr("stroke-width")))
        return _StyleCtx(fill, stroke, sw, self.transform @ _parse_transform(el.get("transform")))


def import_svg(path: str | Path, doc: Document | None = None) -> Document:
    path = Path(path)
    root = ET.parse(path).getroot()
    vb = root.get("viewBox")
    if vb:
        _, _, w, h = (float(v) for v in re.split(r"[\s,]+", vb.strip()))
    else:
        w = float(re.sub(r"[a-z%]+$", "", root.get("width", "1280")))
        h = float(re.sub(r"[a-z%]+$", "", root.get("height", "720")))
    if doc is None:
        doc = Document(width=round(w), height=round(h))
        doc.name = path.stem
    layer = doc.add_vector_layer(path.stem)
    shape = layer.keyframes[0].shape
    ctx = _StyleCtx(Color(0, 0, 0), None, 1.0, Transform2D())  # SVG default fill = black
    _walk(root, ctx, shape)
    return doc


def _walk(el: ET.Element, ctx: _StyleCtx, shape: Shape) -> None:
    tag = el.tag.split("}")[-1]
    ctx = ctx.child(el)
    if tag in ("svg", "g"):
        for child in el:
            _walk(child, ctx, shape)
        return
    subpaths: list[tuple[list[tuple[str, list[Vec2]]], bool]] = []
    if tag == "path":
        subpaths = _parse_path(el.get("d") or "")
    elif tag == "rect":
        x, y = float(el.get("x", 0)), float(el.get("y", 0))
        rw, rh = float(el.get("width", 0)), float(el.get("height", 0))
        pts = [Vec2(x, y), Vec2(x + rw, y), Vec2(x + rw, y + rh), Vec2(x, y + rh)]
        subpaths = [([("L", [a, b]) for a, b in zip(pts, pts[1:] + pts[:1], strict=True)], True)]
    elif tag in ("circle", "ellipse"):
        cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
        rx = float(el.get("r", el.get("rx", 0)))
        ry = float(el.get("r", el.get("ry", 0)))
        k = 0.5522847498  # cubic circle approximation constant
        p = [Vec2(cx + rx, cy), Vec2(cx, cy + ry), Vec2(cx - rx, cy), Vec2(cx, cy - ry)]
        segs = []
        for i in range(4):
            a, b = p[i], p[(i + 1) % 4]
            da = (Vec2(-(a.y - cy), a.x - cx)) * k
            db = (Vec2(-(b.y - cy), b.x - cx)) * k
            segs.append(("C", [a, a + da, b - db, b]))
        subpaths = [(segs, True)]
    elif tag == "line":
        a = Vec2(float(el.get("x1", 0)), float(el.get("y1", 0)))
        b = Vec2(float(el.get("x2", 0)), float(el.get("y2", 0)))
        subpaths = [([("L", [a, b])], False)]
    elif tag in ("polyline", "polygon"):
        nums = [float(v) for v in re.split(r"[\s,]+", (el.get("points") or "").strip()) if v]
        pts = [Vec2(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
        closed = tag == "polygon"
        pairs = list(zip(pts, pts[1:] + (pts[:1] if closed else []), strict=False))
        subpaths = [([("L", [a, b]) for a, b in pairs], closed)]
    else:
        return
    for segs, closed in subpaths:
        _emit(shape, segs, closed, ctx)


def _parse_path(d: str) -> list[tuple[list[tuple[str, list[Vec2]]], bool]]:
    toks = _TOKEN.findall(d)
    i = 0
    cur = Vec2()
    start = Vec2()
    prev_ctrl: Vec2 | None = None
    prev_cmd = ""
    segs: list[tuple[str, list[Vec2]]] = []
    out: list[tuple[list[tuple[str, list[Vec2]]], bool]] = []
    cmd = ""

    def num() -> float:
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    def flush(closed: bool) -> None:
        nonlocal segs
        if segs:
            out.append((segs, closed))
        segs = []

    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        o = cur if rel else Vec2()
        if c == "M":
            flush(False)
            cur = o + Vec2(num(), num())
            start = cur
            cmd = "l" if rel else "L"  # subsequent pairs are implicit lineto
        elif c == "L":
            nxt = o + Vec2(num(), num())
            segs.append(("L", [cur, nxt]))
            cur = nxt
        elif c == "H":
            nxt = Vec2((cur.x if rel else 0) + num(), cur.y)
            segs.append(("L", [cur, nxt]))
            cur = nxt
        elif c == "V":
            nxt = Vec2(cur.x, (cur.y if rel else 0) + num())
            segs.append(("L", [cur, nxt]))
            cur = nxt
        elif c in ("C", "S"):
            if c == "C":
                c1 = o + Vec2(num(), num())
            elif prev_cmd.upper() in ("C", "S") and prev_ctrl is not None:
                c1 = cur * 2 - prev_ctrl
            else:
                c1 = cur
            c2 = o + Vec2(num(), num())
            nxt = o + Vec2(num(), num())
            segs.append(("C", [cur, c1, c2, nxt]))
            prev_ctrl = c2
            cur = nxt
        elif c in ("Q", "T"):
            if c == "Q":
                q = o + Vec2(num(), num())
            elif prev_cmd.upper() in ("Q", "T") and prev_ctrl is not None:
                q = cur * 2 - prev_ctrl
            else:
                q = cur
            nxt = o + Vec2(num(), num())
            segs.append(("Q", [cur, q, nxt]))
            prev_ctrl = q
            cur = nxt
        elif c == "A":
            rx, ry, _rot, _laf, _sf = num(), num(), num(), num(), num()
            nxt = o + Vec2(num(), num())
            # flatten the arc as a few straight segments (approximation)
            steps = max(2, round(max(rx, ry) / 8))
            last = cur
            for s_i in range(1, steps + 1):
                p = cur.lerp(nxt, s_i / steps)
                segs.append(("L", [last, p]))
                last = p
            cur = nxt
        elif c == "Z":
            if cur.distance_to(start) > 1e-9:
                segs.append(("L", [cur, start]))
            cur = start
            flush(True)
        prev_cmd = cmd
        if c not in ("C", "S", "Q", "T"):
            prev_ctrl = None
    flush(False)
    return out


def _emit(shape: Shape, segs: list[tuple[str, list[Vec2]]], closed: bool,
          ctx: _StyleCtx) -> None:
    if not segs:
        return
    t = ctx.transform
    stroke = ctx.stroke
    width = ctx.stroke_w
    conn_ids: list[int] = []
    point_cache: dict[tuple[float, float], int] = {}

    def pid(p: Vec2) -> int:
        tp = t.apply(p)
        key = (round(tp.x, 4), round(tp.y, 4))
        if key not in point_cache:
            point_cache[key] = shape.add_point(tp).id
        return point_cache[key]

    color = stroke if stroke is not None else Color(0, 0, 0)
    only_shape = stroke is None  # fill-only shapes keep geometry but no visible stroke
    for kind, pts in segs:
        if kind == "L":
            a, b = pid(pts[0]), pid(pts[1])
            if a == b:
                continue
            conn = shape.add_connection(a, b, width=width, color=color,
                                        only_shape=only_shape)
        elif kind == "Q":
            a, b = pid(pts[0]), pid(pts[2])
            cp = shape.add_point(t.apply(pts[1]), is_control=True, anchor=a)
            conn = shape.add_connection(a, b, kind=ConnKind.QUAD, c1=cp.id,
                                        width=width, color=color, only_shape=only_shape)
        else:  # C
            a, b = pid(pts[0]), pid(pts[3])
            cp1 = shape.add_point(t.apply(pts[1]), is_control=True, anchor=a)
            cp2 = shape.add_point(t.apply(pts[2]), is_control=True, anchor=b)
            conn = shape.add_connection(a, b, kind=ConnKind.CUBIC, c1=cp1.id, c2=cp2.id,
                                        width=width, color=color, only_shape=only_shape)
        conn_ids.append(conn.id)
    if closed and ctx.fill is not None and len(conn_ids) >= 2:
        loop = [FillEdge(cid, False) for cid in conn_ids]
        shape.add_fill([loop], ctx.fill)
