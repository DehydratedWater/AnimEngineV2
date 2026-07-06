"""Loading audio files into a Document."""

from __future__ import annotations

from pathlib import Path

from animengine.core import AudioClip, Document

from .mixing import probe_duration

SUPPORTED = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus"}


def load_audio_clip(doc: Document, path: str | Path, *, start_frame: int = 0,
                    gain: float = 1.0) -> AudioClip:
    """Read an audio file, embed its bytes in the document and probe duration."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"unsupported audio format {path.suffix!r} "
                         f"(supported: {', '.join(sorted(SUPPORTED))})")
    data = path.read_bytes()
    fmt = path.suffix.lstrip(".").lower()
    clip = doc.add_audio_clip(path.stem, data, fmt, start_frame=start_frame, gain=gain)
    clip.duration_sec = probe_duration(data, fmt)
    if clip.duration_sec is not None:
        doc.extend_to(start_frame + int(clip.duration_sec * doc.fps))
    return clip
