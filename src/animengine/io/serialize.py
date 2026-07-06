"""Dict (JSON-ready) serialization of the core model.

Shared by the native project format, clipboard, and the MCP server's scene
inspection tools.
"""

from __future__ import annotations

from animengine.core import (
    AudioClip,
    Color,
    ConnKind,
    Document,
    FillEdge,
    Interp,
    Placement,
    RasterLayer,
    Shape,
    Vec2,
    VectorLayer,
)
from animengine.core.layers import Layer


def color_to_list(c: Color) -> list[int]:
    return [c.r, c.g, c.b, c.a]


def color_from_list(v: list[int]) -> Color:
    return Color(*v)


def shape_to_dict(shape: Shape) -> dict:
    return {
        "points": [
            {
                "id": p.id,
                "x": p.pos.x,
                "y": p.pos.y,
                **({"control": True} if p.is_control else {}),
                **({"anchor": p.anchor} if p.anchor is not None else {}),
            }
            for p in shape.points.values()
        ],
        "connections": [
            {
                "id": c.id,
                "p1": c.p1,
                "p2": c.p2,
                "kind": c.kind.value,
                **({"c1": c.c1} if c.c1 is not None else {}),
                **({"c2": c.c2} if c.c2 is not None else {}),
                "width": c.width,
                "color": color_to_list(c.color),
                **({"only_shape": True} if c.only_shape else {}),
            }
            for c in shape.connections.values()
        ],
        "fills": [
            {
                "id": f.id,
                "color": color_to_list(f.color),
                "loops": [[[e.conn_id, int(e.reversed)] for e in loop] for loop in f.loops],
            }
            for f in shape.fills.values()
        ],
    }


def shape_from_dict(d: dict) -> Shape:
    s = Shape()
    for p in d.get("points", []):
        s.add_point(
            Vec2(p["x"], p["y"]),
            is_control=p.get("control", False),
            anchor=p.get("anchor"),
            id=p["id"],
        )
    for c in d.get("connections", []):
        s.add_connection(
            c["p1"],
            c["p2"],
            kind=ConnKind(c.get("kind", "line")),
            c1=c.get("c1"),
            c2=c.get("c2"),
            width=c.get("width", 3.0),
            color=color_from_list(c.get("color", [0, 0, 0, 255])),
            only_shape=c.get("only_shape", False),
            id=c["id"],
        )
    for f in d.get("fills", []):
        loops = [[FillEdge(cid, bool(rev)) for cid, rev in loop] for loop in f["loops"]]
        s.add_fill(loops, color_from_list(f.get("color", [200, 200, 200, 255])), id=f["id"])
    return s


def placement_to_dict(pl: Placement) -> dict:
    return {
        "x": pl.pos.x,
        "y": pl.pos.y,
        "sx": pl.scale.x,
        "sy": pl.scale.y,
        "rot": pl.rotation_deg,
        "opacity": pl.opacity,
    }


def placement_from_dict(d: dict) -> Placement:
    return Placement(
        Vec2(d.get("x", 0.0), d.get("y", 0.0)),
        Vec2(d.get("sx", 1.0), d.get("sy", 1.0)),
        d.get("rot", 0.0),
        d.get("opacity", 1.0),
    )


def layer_to_dict(layer: Layer) -> dict:
    base = {
        "id": layer.id,
        "name": layer.name,
        "kind": layer.kind.value,
        "visible": layer.visible,
        "locked": layer.locked,
        "opacity": layer.opacity,
    }
    if isinstance(layer, VectorLayer):
        base["keyframes"] = [
            {"frame": kf.frame, "interp": kf.interp.value, "shape": shape_to_dict(kf.shape)}
            for kf in (layer.keyframes[f] for f in layer.key_frames_sorted())
        ]
    elif isinstance(layer, RasterLayer):
        base["keyframes"] = [
            {
                "frame": kf.frame,
                "interp": kf.interp.value,
                "image": kf.image_id,
                "placement": placement_to_dict(kf.placement),
            }
            for kf in (layer.keyframes[f] for f in layer.key_frames_sorted())
        ]
    return base


def layer_from_dict(d: dict) -> Layer:
    kind = d.get("kind", "vector")
    if kind == "vector":
        layer: Layer = VectorLayer(d["id"], d.get("name", "Layer"))
        for kf in d.get("keyframes", []):
            layer.set_keyframe(
                kf["frame"],
                shape_from_dict(kf.get("shape", {})),
                Interp(kf.get("interp", "linear")),
            )
    else:
        layer = RasterLayer(d["id"], d.get("name", "Raster"))
        for kf in d.get("keyframes", []):
            layer.set_keyframe(
                kf["frame"],
                kf["image"],
                placement_from_dict(kf.get("placement", {})),
                Interp(kf.get("interp", "linear")),
            )
    layer.visible = d.get("visible", True)
    layer.locked = d.get("locked", False)
    layer.opacity = d.get("opacity", 1.0)
    return layer


def document_to_dict(doc: Document) -> dict:
    """Full project dict, except raster pixels and audio bytes (stored beside it)."""
    return {
        "format": "animengine2",
        "version": 1,
        "name": doc.name,
        "width": doc.width,
        "height": doc.height,
        "fps": doc.fps,
        "length": doc.length,
        "background": color_to_list(doc.background) if doc.background else None,
        "layers": [layer_to_dict(la) for la in doc.layers],
        "images": [
            {
                "id": im.id,
                "name": im.name,
                "width": im.width,
                "height": im.height,
                **({"source_path": im.source_path} if im.source_path else {}),
            }
            for im in doc.images.values()
        ],
        "audio": [
            {
                "id": c.id,
                "name": c.name,
                "format": c.format,
                "start_frame": c.start_frame,
                "gain": c.gain,
                "offset_sec": c.offset_sec,
                "duration_sec": c.duration_sec,
                "muted": c.muted,
            }
            for c in doc.audio_clips
        ],
    }


def document_from_dict(d: dict) -> Document:
    doc = Document(d.get("width", 1280), d.get("height", 720), d.get("fps", 30.0))
    doc.name = d.get("name", "Untitled")
    doc.length = d.get("length", 1)
    bg = d.get("background")
    doc.background = color_from_list(bg) if bg else None
    for layer_d in d.get("layers", []):
        layer = layer_from_dict(layer_d)
        doc.layers.append(layer)
        doc._next_layer = max(doc._next_layer, layer.id + 1)
    for c in d.get("audio", []):
        clip = AudioClip(
            c["id"], c.get("name", "audio"), b"", c.get("format", "wav"),
            c.get("start_frame", 0), c.get("gain", 1.0), c.get("offset_sec", 0.0),
            c.get("duration_sec"), c.get("muted", False),
        )
        doc.audio_clips.append(clip)
        doc._next_audio = max(doc._next_audio, clip.id + 1)
    return doc
