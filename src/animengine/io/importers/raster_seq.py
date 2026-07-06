"""Import raster animations: GIF / APNG / image sequences / sprite sheets."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence

from animengine.core import Document, Interp, Placement, RasterImage


def import_gif(path: str | Path, doc: Document | None = None) -> Document:
    """Import an animated GIF (or APNG) as a raster layer with HOLD keyframes."""
    path = Path(path)
    pil = Image.open(path)
    if doc is None:
        doc = Document(width=pil.width, height=pil.height,
                       fps=_gif_fps(pil))
        doc.name = path.stem
    layer = doc.add_raster_layer(path.stem)
    frame_no = 0
    elapsed_ms = 0.0
    for i, frame in enumerate(ImageSequence.Iterator(pil)):
        rgba = np.asarray(frame.convert("RGBA"), np.uint8).copy()
        img = doc.register_image(RasterImage(0, f"{path.stem}_{i}", rgba))
        layer.set_keyframe(frame_no, img.id, Placement(), Interp.HOLD)
        duration_ms = frame.info.get("duration", 100) or 100
        elapsed_ms += duration_ms
        frame_no = round(elapsed_ms / 1000 * doc.fps)
        if frame_no <= max(layer.keyframes):
            frame_no = max(layer.keyframes) + 1
    doc.extend_to(frame_no - 1 if frame_no > 0 else 0)
    return doc


def _gif_fps(pil: Image.Image) -> float:
    duration_ms = pil.info.get("duration", 100) or 100
    return max(1.0, min(60.0, round(1000 / duration_ms)))


def import_image_sequence(paths: list[str | Path], doc: Document | None = None,
                          *, fps: float | None = None) -> Document:
    """Import ordered image files as one raster layer, one keyframe per image."""
    if not paths:
        raise ValueError("no images given")
    paths = [Path(p) for p in sorted(paths)]
    first = Image.open(paths[0]).convert("RGBA")
    if doc is None:
        doc = Document(width=first.width, height=first.height, fps=fps or 12.0)
        doc.name = paths[0].stem.rstrip("0123456789_-") or "sequence"
    layer = doc.add_raster_layer(doc.name)
    for i, p in enumerate(paths):
        rgba = np.asarray(Image.open(p).convert("RGBA"), np.uint8).copy()
        img = doc.register_image(RasterImage(0, p.stem, rgba))
        layer.set_keyframe(i, img.id, Placement(), Interp.HOLD)
    doc.extend_to(len(paths) - 1)
    return doc


def import_sprite_sheet(path: str | Path, frame_width: int, frame_height: int,
                        *, count: int | None = None, fps: float = 12.0,
                        doc: Document | None = None) -> Document:
    """Slice a sprite-sheet grid into frames on a raster layer."""
    path = Path(path)
    sheet = np.asarray(Image.open(path).convert("RGBA"), np.uint8)
    rows = sheet.shape[0] // frame_height
    cols = sheet.shape[1] // frame_width
    total = rows * cols if count is None else min(count, rows * cols)
    if total == 0:
        raise ValueError("sheet smaller than one frame")
    if doc is None:
        doc = Document(width=frame_width, height=frame_height, fps=fps)
        doc.name = path.stem
    layer = doc.add_raster_layer(path.stem)
    for i in range(total):
        r, c = divmod(i, cols)
        tile = sheet[r * frame_height:(r + 1) * frame_height,
                     c * frame_width:(c + 1) * frame_width].copy()
        img = doc.register_image(RasterImage(0, f"{path.stem}_{i}", tile))
        layer.set_keyframe(i, img.id, Placement(), Interp.HOLD)
    doc.extend_to(total - 1)
    return doc
