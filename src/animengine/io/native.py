"""Native project format: .aep2 — a zip with JSON + embedded assets.

Layout:
    project.json          document, layers, keyframes, audio metadata
    images/<id>.png       raster image assets
    audio/<id>.<ext>      original audio file bytes
"""

from __future__ import annotations

import io as _io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from animengine.core import Document, RasterImage

from .serialize import document_from_dict, document_to_dict

EXTENSION = ".aep2"


def save_project(doc: Document, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix != EXTENSION:
        path = path.with_suffix(EXTENSION)
    doc.name = path.stem
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(document_to_dict(doc), indent=1))
        for img in doc.images.values():
            buf = _io.BytesIO()
            Image.fromarray(img.pixels, "RGBA").save(buf, "PNG")
            zf.writestr(f"images/{img.id}.png", buf.getvalue())
        for clip in doc.audio_clips:
            if clip.data:
                zf.writestr(f"audio/{clip.id}.{clip.format}", clip.data)
    return path


def load_project(path: str | Path) -> Document:
    path = Path(path)
    with zipfile.ZipFile(path, "r") as zf:
        meta = json.loads(zf.read("project.json"))
        doc = document_from_dict(meta)
        for img_meta in meta.get("images", []):
            img_id = img_meta["id"]
            name = f"images/{img_id}.png"
            try:
                raw = zf.read(name)
            except KeyError:
                pixels = np.zeros((img_meta["height"], img_meta["width"], 4), np.uint8)
            else:
                pil = Image.open(_io.BytesIO(raw)).convert("RGBA")
                pixels = np.asarray(pil, dtype=np.uint8).copy()
            image = RasterImage(img_id, img_meta.get("name", f"image{img_id}"),
                                pixels, img_meta.get("source_path"))
            doc.images[img_id] = image
            doc._next_image = max(doc._next_image, img_id + 1)
        for clip in doc.audio_clips:
            try:
                clip.data = zf.read(f"audio/{clip.id}.{clip.format}")
            except KeyError:
                clip.data = b""
    doc.name = path.stem
    return doc
