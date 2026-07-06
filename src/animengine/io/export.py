"""Exporters: still image, PNG sequence, GIF, MP4/WebM video, SVG, sprite sheet.

The original could only dump a PNG sequence. All exporters here run headless.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRect, QSize

from animengine.audio.mixing import FFMPEG, AudioMix
from animengine.core import Document
from animengine.render import ensure_gui_app, paint_document, raster_from_qimage, render_frame

ProgressFn = Callable[[int, int], None]


def _frames(doc: Document, frames: Iterable[int] | None) -> list[int]:
    return list(frames) if frames is not None else list(range(doc.length))


def export_image(doc: Document, frame: int, path: str | Path, *, scale: float = 1.0,
                 transparent: bool = False) -> Path:
    path = Path(path)
    img = render_frame(doc, frame, scale=scale, transparent=transparent)
    img.save(str(path))
    return path


def export_png_sequence(doc: Document, directory: str | Path, *, name: str | None = None,
                        frames: Iterable[int] | None = None, scale: float = 1.0,
                        transparent: bool = False,
                        progress: ProgressFn | None = None) -> list[Path]:
    """Writes <name>0000.png, <name>0001.png, ... like the original (but zero-padded)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = name or doc.name or "frame"
    todo = _frames(doc, frames)
    out = []
    for i, f in enumerate(todo):
        p = directory / f"{name}{f:04d}.png"
        export_image(doc, f, p, scale=scale, transparent=transparent)
        out.append(p)
        if progress:
            progress(i + 1, len(todo))
    return out


def _pil_frames(doc: Document, frames: Iterable[int] | None, scale: float,
                progress: ProgressFn | None = None) -> list[Image.Image]:
    todo = _frames(doc, frames)
    images = []
    for i, f in enumerate(todo):
        qimg = render_frame(doc, f, scale=scale)
        images.append(Image.fromarray(raster_from_qimage(qimg), "RGBA").convert("RGB"))
        if progress:
            progress(i + 1, len(todo))
    return images


def export_gif(doc: Document, path: str | Path, *, frames: Iterable[int] | None = None,
               scale: float = 1.0, fps: float | None = None, loop: int = 0,
               progress: ProgressFn | None = None) -> Path:
    path = Path(path).with_suffix(".gif")
    images = _pil_frames(doc, frames, scale, progress)
    duration_ms = round(1000 / (fps or doc.fps))
    images[0].save(
        path, save_all=True, append_images=images[1:],
        duration=duration_ms, loop=loop, optimize=True,
    )
    return path


def export_video(doc: Document, path: str | Path, *, frames: Iterable[int] | None = None,
                 scale: float = 1.0, fps: float | None = None, include_audio: bool = True,
                 progress: ProgressFn | None = None) -> Path:
    """Export MP4 (H.264) or WebM (VP9) chosen by file extension, muxing audio clips."""
    if FFMPEG is None:
        raise RuntimeError("ffmpeg not found on PATH — required for video export")
    path = Path(path)
    if path.suffix.lower() not in (".mp4", ".webm"):
        path = path.with_suffix(".mp4")
    fps = fps or doc.fps
    todo = _frames(doc, frames)

    w = max(2, round(doc.width * scale) // 2 * 2)  # codecs want even sizes
    h = max(2, round(doc.height * scale) // 2 * 2)

    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-"]
    mix = AudioMix.build(doc) if include_audio else None
    if mix is not None:
        cmd += mix.input_args
        cmd += ["-filter_complex", mix.filter_complex]
    if path.suffix.lower() == ".webm":
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "2M", "-pix_fmt", "yuv420p"]
        audio_codec = ["-c:a", "libopus"]
    else:
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-pix_fmt", "yuv420p"]
        audio_codec = ["-c:a", "aac"]
    cmd += ["-map", "0:v"]
    if mix is not None:
        cmd += ["-map", mix.map_ref, *audio_codec]
        cmd += ["-t", f"{len(todo) / fps:.6f}"]  # cap audio at animation end
    cmd += [str(path)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i, f in enumerate(todo):
            qimg = render_frame(doc, f, scale=scale)
            if (qimg.width(), qimg.height()) != (w, h):
                qimg = qimg.scaled(QSize(w, h))
            arr = raster_from_qimage(qimg)
            proc.stdin.write(arr.tobytes())
            if progress:
                progress(i + 1, len(todo))
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err.strip()}")
    finally:
        if proc.poll() is None:
            proc.kill()
    return path


def export_svg(doc: Document, frame: int, path: str | Path) -> Path:
    """Export one frame as SVG (vector layers stay resolution-independent)."""
    from PySide6.QtGui import QPainter
    from PySide6.QtSvg import QSvgGenerator

    ensure_gui_app()
    path = Path(path).with_suffix(".svg")
    gen = QSvgGenerator()
    gen.setFileName(str(path))
    gen.setSize(QSize(doc.width, doc.height))
    gen.setViewBox(QRect(0, 0, doc.width, doc.height))
    gen.setTitle(doc.name)
    painter = QPainter(gen)
    try:
        paint_document(painter, doc, frame)
    finally:
        painter.end()
    return path


def export_sprite_sheet(doc: Document, path: str | Path, *,
                        frames: Iterable[int] | None = None, columns: int = 0,
                        scale: float = 1.0,
                        progress: ProgressFn | None = None) -> Path:
    """Pack frames into a grid PNG (game-engine friendly)."""
    import math

    path = Path(path).with_suffix(".png")
    todo = _frames(doc, frames)
    if columns <= 0:
        columns = math.ceil(math.sqrt(len(todo)))
    rows = math.ceil(len(todo) / columns)
    fw = max(1, round(doc.width * scale))
    fh = max(1, round(doc.height * scale))
    sheet = Image.new("RGBA", (columns * fw, rows * fh), (0, 0, 0, 0))
    for i, f in enumerate(todo):
        qimg = render_frame(doc, f, scale=scale, transparent=True)
        tile = Image.fromarray(raster_from_qimage(qimg), "RGBA")
        sheet.paste(tile, ((i % columns) * fw, (i // columns) * fh))
        if progress:
            progress(i + 1, len(todo))
    sheet.save(path)
    return path
