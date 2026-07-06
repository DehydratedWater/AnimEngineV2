"""MCP server exposing AnimEngine to LLM agents.

Run with `animengine-mcp` (stdio transport). One project is live per server
session; every drawing tool works on the active layer + current frame unless
told otherwise, mirroring how a human uses the editor. `render_frame` /
`render_filmstrip` give the model eyes; `get_scene` gives exact geometry with
the ids needed by move/connect/remove tools.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from animengine.api import AnimProject

mcp = FastMCP(
    "animengine",
    instructions=(
        "AnimEngine 2: keyframe vector/raster animation editor. Typical flow: "
        "new_project -> draw with add_line/add_curve/add_rect/add_polyline/"
        "fill_region -> render_frame to check -> copy_frame_forward, edit with "
        "move_point/transform_points to animate -> render_filmstrip or "
        "render_animation to review -> export_file / save_project. Use "
        "get_scene to obtain point/connection ids. Coordinates are pixels, "
        "origin top-left, y grows downward. Colors are hex like #ff0000."
    ),
)

_project: AnimProject | None = None


def project() -> AnimProject:
    global _project
    if _project is None:
        _project = AnimProject()
    return _project


# ------------------------------------------------------------------ project
@mcp.tool()
def new_project(width: int = 1280, height: int = 720, fps: float = 30.0) -> dict:
    """Start a fresh project (replaces the current one). Returns its summary."""
    global _project
    _project = AnimProject(width, height, fps)
    return _project.summary()


@mcp.tool()
def open_file(path: str) -> dict:
    """Open a project or import a file by extension: .aep2 (native), .ae
    (legacy AnimEngine), .svg, .json (Lottie), .gif. Returns the summary."""
    global _project
    _project = AnimProject.open(path)
    return _project.summary()


@mcp.tool()
def save_project(path: str) -> str:
    """Save the project as native .aep2 (extension added automatically)."""
    return str(project().save(path))


@mcp.tool()
def get_summary() -> dict:
    """Project overview: size/fps/length, layers with ids + keyframe frames,
    images, audio clips, current frame and active layer."""
    return project().summary()


@mcp.tool()
def undo() -> str:
    """Undo the last operation. Returns what was undone."""
    label = project().undo()
    return f"undid: {label}" if label else "nothing to undo"


@mcp.tool()
def redo() -> str:
    """Redo the last undone operation."""
    label = project().redo()
    return f"redid: {label}" if label else "nothing to redo"


@mcp.tool()
def set_length(frames: int) -> str:
    """Set the animation length in frames."""
    project().set_length(frames)
    return f"length = {project().doc.length} frames"


# ------------------------------------------------------------------- layers
@mcp.tool()
def add_layer(kind: str = "vector", name: str = "") -> dict:
    """Add a layer ("vector" or "raster") on top; it becomes active.
    Raster layers get a canvas-sized paintable image."""
    p = project()
    if kind == "raster":
        layer = p.new_raster_layer(name or None)
    else:
        layer = p.add_layer("vector", name or None)
    return {"layer_id": layer.id, "name": layer.name, "kind": layer.kind.value}


@mcp.tool()
def remove_layer(layer_id: int) -> str:
    """Delete a layer entirely."""
    project().remove_layer(layer_id)
    return "removed"


@mcp.tool()
def rename_layer(layer_id: int, name: str) -> str:
    """Rename a layer."""
    project().rename_layer(layer_id, name)
    return "renamed"


@mcp.tool()
def set_layer_props(layer_id: int, visible: bool | None = None,
                    locked: bool | None = None, opacity: float | None = None) -> str:
    """Set layer visibility, lock state and/or opacity (0..1)."""
    project().set_layer_props(layer_id, visible=visible, locked=locked, opacity=opacity)
    return "updated"


@mcp.tool()
def move_layer(layer_id: int, new_index: int) -> str:
    """Reorder a layer; index 0 is the bottom (drawn first)."""
    project().move_layer(layer_id, new_index)
    return "moved"


@mcp.tool()
def set_active_layer(layer_id: int) -> str:
    """Choose which layer subsequent drawing tools target."""
    project().set_active_layer(layer_id)
    return f"active layer = {layer_id}"


# ------------------------------------------------------------------- frames
@mcp.tool()
def goto_frame(frame: int) -> str:
    """Jump the current-frame cursor (extends the animation if needed)."""
    return f"current frame = {project().set_frame(frame)}"


@mcp.tool()
def copy_frame_forward(layer_id: int | None = None) -> str:
    """Duplicate the current state onto the next frame as a new keyframe and
    move there (the classic frame-by-frame animation step). Omit layer_id to
    copy all layers."""
    p = project()
    frame = p.copy_frame_forward(layer_id)
    return f"copied to frame {frame}, now current"


@mcp.tool()
def add_keyframe(frame: int, layer_id: int | None = None) -> str:
    """Create a keyframe at *frame* capturing the layer's interpolated state."""
    p = project()
    p.add_keyframe(layer_id, frame)
    return f"keyframe at {frame}"


@mcp.tool()
def remove_keyframe(frame: int, layer_id: int | None = None) -> str:
    """Delete the keyframe at *frame* on the layer."""
    project().remove_keyframe(layer_id, frame)
    return "removed"


@mcp.tool()
def set_keyframe_interp(frame: int, interp: str, layer_id: int | None = None) -> str:
    """Set how a keyframe blends to the next: hold | linear | ease_in |
    ease_out | ease_in_out."""
    project().set_keyframe_interp(interp, layer_id, frame)
    return f"{interp} at frame {frame}"


# ------------------------------------------------------------------ drawing
@mcp.tool()
def add_line(x1: float, y1: float, x2: float, y2: float, width: float = 3.0,
             color: str = "#000000", snap: bool = True) -> dict:
    """Draw a straight line on the active layer at the current frame.
    Endpoints snap to nearby existing points (within 15px) unless snap=False;
    crossings with existing strokes are split into shared vertices."""
    return project().add_line(x1, y1, x2, y2, width=width, color=color, snap=snap)


@mcp.tool()
def add_curve(x1: float, y1: float, cx1: float, cy1: float, cx2: float, cy2: float,
              x2: float, y2: float, width: float = 3.0, color: str = "#000000",
              snap: bool = True) -> dict:
    """Draw a cubic Bezier: endpoints (x1,y1)->(x2,y2) with control points
    (cx1,cy1) near the start and (cx2,cy2) near the end."""
    return project().add_curve(x1, y1, cx1, cy1, cx2, cy2, x2, y2,
                               width=width, color=color, snap=snap)


@mcp.tool()
def add_rect(x: float, y: float, w: float, h: float, width: float = 3.0,
             color: str = "#000000") -> dict:
    """Draw an axis-aligned rectangle outline (4 points + 4 connections)."""
    return project().add_rect(x, y, w, h, width=width, color=color)


@mcp.tool()
def add_polyline(points: list[list[float]], close: bool = False, width: float = 3.0,
                 color: str = "#000000") -> dict:
    """Draw a connected polyline through [[x,y], ...]; close=True joins the
    last point back to the first (freehand/pen tool equivalent)."""
    return project().add_polyline([(p[0], p[1]) for p in points], close=close,
                                  width=width, color=color)


@mcp.tool()
def add_point(x: float, y: float) -> int:
    """Add a lone point (connect it later with connect_points). Returns its id."""
    return project().add_point(x, y)


@mcp.tool()
def connect_points(p1: int, p2: int, width: float = 3.0, color: str = "#000000") -> int:
    """Connect two existing points (ids from get_scene) with a line."""
    return project().connect_points(p1, p2, width=width, color=color)


@mcp.tool()
def move_point(point_id: int, x: float, y: float, merge: bool = True) -> str:
    """Move a point to (x, y); its curve handles follow. If it lands within
    15px of another point they weld together (merge=False disables)."""
    project().move_point(point_id, x, y, merge=merge)
    return "moved"


@mcp.tool()
def transform_points(point_ids: list[int], dx: float = 0.0, dy: float = 0.0,
                     scale_x: float = 1.0, scale_y: float = 1.0,
                     rotate_deg: float = 0.0) -> str:
    """Translate/scale/rotate a group of points about their centroid — the
    transform-box operation. Control handles of selected points follow."""
    project().transform_points(point_ids, dx=dx, dy=dy, scale_x=scale_x,
                               scale_y=scale_y, rotate_deg=rotate_deg)
    return f"transformed {len(point_ids)} points"


@mcp.tool()
def remove_point(point_id: int) -> str:
    """Delete a point and every connection using it."""
    project().remove_point(point_id)
    return "removed"


@mcp.tool()
def remove_connection(connection_id: int) -> str:
    """Delete a connection (fills using it disappear too)."""
    project().remove_connection(connection_id)
    return "removed"


@mcp.tool()
def remove_fill(fill_id: int) -> str:
    """Delete a fill."""
    project().remove_fill(fill_id)
    return "removed"


@mcp.tool()
def fill_region(x: float, y: float, color: str = "#ffffff") -> str:
    """Bucket-fill the enclosed region containing (x, y). Recolors if already
    filled. Fails if the point is not inside a closed outline."""
    fid = project().fill_region(x, y, color)
    return f"fill id {fid}" if fid is not None else "no enclosed region there"


@mcp.tool()
def set_connection_style(connection_id: int, width: float | None = None,
                         color: str | None = None) -> str:
    """Change a connection's stroke width and/or color."""
    project().set_connection_style(connection_id, width=width, color=color)
    return "styled"


@mcp.tool()
def cut_connection_at(x: float, y: float) -> str:
    """Split the connection nearest to (x, y) into two at that spot
    (scissors tool). Returns the new midpoint id."""
    pid = project().cut_connection_at(x, y)
    return f"new point {pid}" if pid is not None else "no connection within reach"


@mcp.tool()
def erase_at(x: float, y: float, radius: float = 15.0) -> str:
    """Eraser: delete all points within radius of (x, y) on the active layer."""
    n = project().erase_at(x, y, radius)
    return f"erased {n} points"


# ------------------------------------------------------------------- raster
@mcp.tool()
def paint_stroke(points: list[list[float]], width: float = 8.0,
                 color: str = "#000000", erase: bool = False) -> str:
    """Paint a brush stroke through [[x,y],...] into the active raster layer
    (erase=True clears pixels instead)."""
    project().paint_stroke([(p[0], p[1]) for p in points], width=width,
                           color=color, erase=erase)
    return "painted"


@mcp.tool()
def import_image(path: str, x: float = 0.0, y: float = 0.0) -> dict:
    """Load an image file as a new raster layer placed at (x, y)."""
    layer = project().import_image(path, x=x, y=y)
    return {"layer_id": layer.id, "name": layer.name}


@mcp.tool()
def move_raster(dx: float = 0.0, dy: float = 0.0, scale_x: float | None = None,
                scale_y: float | None = None, rotate_deg: float | None = None,
                opacity: float | None = None, layer_id: int | None = None) -> str:
    """Move/scale/rotate the active raster layer's image at the current frame
    (animate by setting different placements on different keyframes)."""
    project().move_raster(dx=dx, dy=dy, scale_x=scale_x, scale_y=scale_y,
                          rotate_deg=rotate_deg, opacity=opacity, layer_id=layer_id)
    return "placed"


# -------------------------------------------------------------------- audio
@mcp.tool()
def add_audio(path: str, start_frame: int = 0, gain: float = 1.0) -> dict:
    """Attach an audio file (wav/mp3/ogg/flac/...) starting at start_frame.
    It is embedded in the project and mixed into video exports."""
    clip = project().add_audio(path, start_frame=start_frame, gain=gain)
    return {"clip_id": clip.id, "name": clip.name, "duration_sec": clip.duration_sec}


# ------------------------------------------------------------ views/exports
@mcp.tool()
def get_scene(layer_id: int | None = None, frame: int | None = None) -> dict:
    """Exact geometry of a layer at a frame: every point (id, x, y, control?),
    connection (id, endpoints, kind, width, color) and fill. Use these ids
    with move_point / connect_points / remove_* / set_connection_style."""
    return project().scene_info(layer_id, frame)


@mcp.tool()
def render_frame(frame: int | None = None, scale: float = 0.5) -> Image:
    """Render one frame as PNG (default half resolution to save tokens).
    Omit frame for the current frame."""
    data = project().render_png(frame, scale=scale)
    return Image(data=data, format="png")


@mcp.tool()
def render_filmstrip(start: int = 0, end: int | None = None, step: int = 1,
                     scale: float = 0.25, columns: int = 4) -> Image:
    """Render several frames tiled into one contact-sheet image — the quickest
    way to review motion. Defaults to the whole animation at quarter size."""
    import math as _math

    from PIL import Image as PILImage

    from animengine.render import raster_from_qimage
    from animengine.render import render_frame as _render

    p = project()
    end = p.doc.length - 1 if end is None else min(end, p.doc.length - 1)
    frames = list(range(start, end + 1, max(1, step)))[:64]
    cols = min(columns, len(frames)) or 1
    rows = _math.ceil(len(frames) / cols)
    fw = max(1, round(p.doc.width * scale))
    fh = max(1, round(p.doc.height * scale))
    pad = 2
    sheet = PILImage.new("RGB", (cols * (fw + pad), rows * (fh + pad)), (40, 40, 40))
    for i, f in enumerate(frames):
        tile = PILImage.fromarray(raster_from_qimage(_render(p.doc, f, scale=scale)), "RGBA")
        sheet.paste(tile.convert("RGB"),
                    ((i % cols) * (fw + pad), (i // cols) * (fh + pad)))
    import io as _io

    buf = _io.BytesIO()
    sheet.save(buf, "PNG")
    return Image(data=buf.getvalue(), format="png")


@mcp.tool()
def render_animation(path: str = "", format: str = "gif", scale: float = 0.5,
                     fps: float | None = None) -> str:
    """Render the full animation to a gif/mp4/webm file and return its path.
    Leave path empty for a temp file. Video formats include the audio track."""
    p = project()
    if not path:
        path = tempfile.mktemp(prefix="animengine-", suffix=f".{format}")
    out = p.export(Path(path).with_suffix(f".{format}"), kind=format,
                   scale=scale, fps=fps)
    return str(out)


@mcp.tool()
def export_file(path: str, kind: str = "", frame: int | None = None) -> str:
    """Export by extension or explicit kind: png (single frame), sequence
    (PNG per frame into a directory), gif, mp4, webm, svg, spritesheet."""
    kwargs = {}
    if frame is not None:
        kwargs["frame"] = frame
    out = project().export(path, kind=kind or None, **kwargs)
    return str(out)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
