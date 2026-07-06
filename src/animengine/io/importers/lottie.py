"""Lottie / Bodymovin JSON importer with keyframe support.

Supported subset: shape layers (ty=4) with groups, bezier paths, fills,
strokes and animated transforms (position/scale/rotation/opacity/anchor)
plus animated path shapes. Property keyframes are *baked*: at every source
keyframe time we evaluate the layer and store a V2 keyframe; V2's linear
tween carries motion in between (Lottie easing curves are approximated).

Not supported (skipped): precomps, masks, mattes, trim paths, gradients,
expressions, image layers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from animengine.core import (
    Color,
    ConnKind,
    Document,
    FillEdge,
    Shape,
    Transform2D,
    Vec2,
)


def import_lottie(path: str | Path, doc: Document | None = None) -> Document:
    path = Path(path)
    data = json.loads(path.read_text())
    w, h = int(data.get("w", 512)), int(data.get("h", 512))
    fps = float(data.get("fr", 30))
    ip, op = int(data.get("ip", 0)), int(data.get("op", 1))
    if doc is None:
        doc = Document(width=w, height=h, fps=fps)
        doc.name = path.stem
    doc.extend_to(max(0, op - ip - 1))

    # lottie lists layers top-first; our layer list is bottom-first
    for lay in reversed(data.get("layers", [])):
        if lay.get("ty") != 4:  # shape layers only
            continue
        _import_shape_layer(doc, lay, ip, op)
    return doc


def _import_shape_layer(doc: Document, lay: dict, doc_ip: int, doc_op: int) -> None:
    layer = doc.add_vector_layer(lay.get("nm", "lottie"))
    layer.keyframes.clear()
    lay_ip = int(lay.get("ip", doc_ip))
    lay_op = int(lay.get("op", doc_op))

    times = {lay_ip}
    _collect_times(lay.get("ks", {}), times)
    for item in lay.get("shapes", []):
        _collect_times(item, times)
    times = sorted(t for t in times if lay_ip <= t < lay_op)
    if not times:
        times = [lay_ip]

    for t in times:
        frame = int(round(t)) - doc_ip
        if frame < 0:
            continue
        shape = _bake_shape(lay, t)
        layer.set_keyframe(frame, shape)
    if lay_op < doc_op:  # layer ends: hide it
        layer.set_keyframe(max(0, int(lay_op) - doc_ip), Shape())


def _collect_times(node, times: set) -> None:
    if isinstance(node, dict):
        k = node.get("k")
        if node.get("a") == 1 and isinstance(k, list):
            for kf in k:
                if isinstance(kf, dict) and "t" in kf:
                    times.add(int(round(kf["t"])))
        for v in node.values():
            _collect_times(v, times)
    elif isinstance(node, list):
        for v in node:
            _collect_times(v, times)


# ----------------------------------------------------------- evaluation
def _value(prop, t: float, default):
    """Evaluate a lottie animatable property at time t (linear interp)."""
    if prop is None:
        return default
    k = prop.get("k", default)
    animated = prop.get("a") == 1 or (
        isinstance(k, list) and k and isinstance(k[0], dict) and "t" in k[0]
    )
    if not animated:
        return k
    kfs = k
    if t <= kfs[0]["t"]:
        return _kf_start(kfs[0])
    for j in range(len(kfs) - 1):
        k0, k1 = kfs[j], kfs[j + 1]
        if k0["t"] <= t < k1["t"]:
            v0 = _kf_start(k0)
            v1 = k0.get("e", _kf_start(k1))
            if v1 is None:
                v1 = v0
            u = (t - k0["t"]) / (k1["t"] - k0["t"])
            return _lerp_value(v0, v1, u)
    return _kf_start(kfs[-1]) if _kf_start(kfs[-1]) is not None else default


def _kf_start(kf):
    s = kf.get("s")
    if isinstance(s, list) and len(s) == 1 and isinstance(s[0], dict):
        return s[0]  # path keyframes wrap the value in a list
    return s


def _lerp_value(a, b, u: float):
    if isinstance(a, dict):  # bezier path payload
        return _lerp_path(a, b, u)
    if isinstance(a, list):
        return [x + (y - x) * u for x, y in zip(a, b, strict=False)]
    return a + (b - a) * u


def _lerp_path(a: dict, b: dict, u: float) -> dict:
    def mix(key):
        av, bv = a.get(key, []), b.get(key, [])
        return [
            [p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u]
            for p, q in zip(av, bv, strict=False)
        ]

    return {"c": a.get("c", True), "v": mix("v"), "i": mix("i"), "o": mix("o")}


def _transform_at(ks: dict, t: float) -> tuple[Transform2D, float]:
    """(matrix, opacity 0..1) of a lottie transform at time t."""
    pos = _value(ks.get("p"), t, [0, 0])
    if isinstance(pos, dict):  # split x/y position
        pos = [_value(pos.get("x"), t, 0), _value(pos.get("y"), t, 0)]
    anchor = _value(ks.get("a"), t, [0, 0])
    scale = _value(ks.get("s"), t, [100, 100])
    rot = _value(ks.get("r"), t, 0)
    opacity = _value(ks.get("o"), t, 100)
    if isinstance(rot, list):
        rot = rot[0]
    if isinstance(opacity, list):
        opacity = opacity[0]
    m = (
        Transform2D.translation(pos[0], pos[1])
        @ Transform2D.rotation(math.radians(rot))
        @ Transform2D.scaling(scale[0] / 100, scale[1] / 100)
        @ Transform2D.translation(-anchor[0], -anchor[1])
    )
    return m, opacity / 100


# --------------------------------------------------------------- baking
def _bake_shape(lay: dict, t: float) -> Shape:
    shape = Shape()
    base, _op = _transform_at(lay.get("ks", {}), t)
    _bake_items(shape, lay.get("shapes", []), base, t)
    return shape


def _bake_items(shape: Shape, items: list, transform: Transform2D, t: float) -> None:
    # find group style (fill/stroke apply to paths in the same group)
    fill_color = None
    stroke: tuple[Color, float] | None = None
    for item in items:
        ty = item.get("ty")
        if ty == "fl":
            col = _value(item.get("c"), t, [0, 0, 0, 1])
            op = _value(item.get("o"), t, 100)
            if isinstance(op, list):
                op = op[0]
            fill_color = _lottie_color(col, op)
        elif ty == "st":
            col = _value(item.get("c"), t, [0, 0, 0, 1])
            op = _value(item.get("o"), t, 100)
            if isinstance(op, list):
                op = op[0]
            width = _value(item.get("w"), t, 1)
            if isinstance(width, list):
                width = width[0]
            stroke = (_lottie_color(col, op), float(width))

    for item in items:
        ty = item.get("ty")
        if ty == "gr":
            sub = item.get("it", [])
            tr = next((x for x in sub if x.get("ty") == "tr"), None)
            m = transform
            if tr:
                local, _ = _transform_at(tr, t)
                m = transform @ local
            _bake_items(shape, sub, m, t)
        elif ty == "sh":
            payload = _value(item.get("ks"), t, None)
            if isinstance(payload, dict):
                _emit_path(shape, payload, transform, fill_color, stroke)
        elif ty == "rc":
            _emit_rect(shape, item, transform, t, fill_color, stroke)
        elif ty == "el":
            _emit_ellipse(shape, item, transform, t, fill_color, stroke)


def _lottie_color(c, opacity: float) -> Color:
    vals = list(c) + [1.0] * (4 - len(c)) if len(c) < 4 else list(c)
    return Color(
        round(vals[0] * 255), round(vals[1] * 255), round(vals[2] * 255),
        round(min(vals[3], opacity / 100 if opacity > 1 else opacity) * 255)
        if opacity <= 100 else 255,
    )


def _emit_path(shape: Shape, path: dict, m: Transform2D,
               fill_color: Color | None, stroke: tuple[Color, float] | None) -> None:
    v = path.get("v", [])
    ins = path.get("i", [])
    outs = path.get("o", [])
    closed = path.get("c", False)
    n = len(v)
    if n < 2:
        return
    color, width = stroke if stroke else (Color(0, 0, 0), 1.0)
    only_shape = stroke is None
    pts = [shape.add_point(m.apply(Vec2(*p))) for p in v]
    conn_ids = []
    seg_count = n if closed else n - 1
    for j in range(seg_count):
        a, b = pts[j], pts[(j + 1) % n]
        o_t = Vec2(*outs[j]) if j < len(outs) else Vec2()
        i_t = Vec2(*ins[(j + 1) % n]) if (j + 1) % n < len(ins) else Vec2()
        if o_t.length() < 1e-9 and i_t.length() < 1e-9:
            conn = shape.add_connection(a.id, b.id, width=width, color=color,
                                        only_shape=only_shape)
        else:
            c1 = shape.add_point(m.apply(Vec2(*v[j]) + o_t), is_control=True, anchor=a.id)
            c2 = shape.add_point(m.apply(Vec2(*v[(j + 1) % n]) + i_t),
                                 is_control=True, anchor=b.id)
            conn = shape.add_connection(a.id, b.id, kind=ConnKind.CUBIC,
                                        c1=c1.id, c2=c2.id, width=width, color=color,
                                        only_shape=only_shape)
        conn_ids.append(conn.id)
    if closed and fill_color is not None and conn_ids:
        shape.add_fill([[FillEdge(cid, False) for cid in conn_ids]], fill_color)


def _emit_rect(shape: Shape, item: dict, m: Transform2D, t: float,
               fill_color: Color | None, stroke) -> None:
    pos = _value(item.get("p"), t, [0, 0])
    size = _value(item.get("s"), t, [0, 0])
    hw, hh = size[0] / 2, size[1] / 2
    corners = [
        [pos[0] - hw, pos[1] - hh], [pos[0] + hw, pos[1] - hh],
        [pos[0] + hw, pos[1] + hh], [pos[0] - hw, pos[1] + hh],
    ]
    payload = {"c": True, "v": corners,
               "i": [[0, 0]] * 4, "o": [[0, 0]] * 4}
    _emit_path(shape, payload, m, fill_color, stroke)


def _emit_ellipse(shape: Shape, item: dict, m: Transform2D, t: float,
                  fill_color: Color | None, stroke) -> None:
    pos = _value(item.get("p"), t, [0, 0])
    size = _value(item.get("s"), t, [0, 0])
    rx, ry = size[0] / 2, size[1] / 2
    k = 0.5522847498
    v = [[pos[0] + rx, pos[1]], [pos[0], pos[1] + ry],
         [pos[0] - rx, pos[1]], [pos[0], pos[1] - ry]]
    o = [[0, ry * k], [-rx * k, 0], [0, -ry * k], [rx * k, 0]]
    i = [[0, -ry * k], [rx * k, 0], [0, ry * k], [-rx * k, 0]]
    payload = {"c": True, "v": v, "i": i, "o": o}
    _emit_path(shape, payload, m, fill_color, stroke)
