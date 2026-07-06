"""Audio helpers: probing and building ffmpeg mix graphs for export."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from animengine.core import AudioClip, Document

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def have_ffmpeg() -> bool:
    return FFMPEG is not None


def probe_duration(data: bytes, fmt: str) -> float | None:
    """Duration in seconds of an audio blob, via ffprobe (None if unknown)."""
    if FFPROBE is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=f".{fmt}") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            out = subprocess.run(
                [FFPROBE, "-v", "quiet", "-print_format", "json",
                 "-show_format", tmp.name],
                capture_output=True, text=True, timeout=30, check=True,
            )
            return float(json.loads(out.stdout)["format"]["duration"])
        except (subprocess.SubprocessError, KeyError, ValueError):
            return None


def clip_duration(clip: AudioClip) -> float | None:
    if clip.duration_sec is not None:
        return clip.duration_sec
    natural = probe_duration(clip.data, clip.format)
    if natural is None:
        return None
    return max(0.0, natural - clip.offset_sec)


class AudioMix:
    """ffmpeg CLI fragments that mix a document's audio clips into one track.

    Writes clip bytes to temp files (kept alive by this object); use as:
        mix = AudioMix.build(doc)
        cmd += mix.input_args
        cmd += ["-filter_complex", mix.filter_complex, "-map", mix.map_ref]
    """

    def __init__(self, input_args: list[str], filter_complex: str, map_ref: str,
                 tmpdir: tempfile.TemporaryDirectory):
        self.input_args = input_args
        self.filter_complex = filter_complex
        self.map_ref = map_ref
        self._tmpdir = tmpdir

    @classmethod
    def build(cls, doc: Document, *, first_input_index: int = 1) -> AudioMix | None:
        clips = [c for c in doc.audio_clips if c.data and not c.muted]
        if not clips:
            return None
        tmpdir = tempfile.TemporaryDirectory(prefix="animengine-audio-")
        input_args: list[str] = []
        chains: list[str] = []
        labels: list[str] = []
        for n, clip in enumerate(clips):
            path = Path(tmpdir.name) / f"clip{clip.id}.{clip.format}"
            path.write_bytes(clip.data)
            input_args += ["-i", str(path)]
            idx = first_input_index + n
            steps = []
            if clip.offset_sec > 0:
                steps.append(f"atrim=start={clip.offset_sec}")
                steps.append("asetpts=PTS-STARTPTS")
            if clip.duration_sec is not None:
                steps.append(f"atrim=duration={clip.duration_sec}")
            if clip.gain != 1.0:
                steps.append(f"volume={clip.gain}")
            delay_ms = round(clip.start_frame / doc.fps * 1000)
            if delay_ms > 0:
                steps.append(f"adelay={delay_ms}:all=1")
            steps.append("aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo")
            label = f"a{n}"
            chains.append(f"[{idx}:a]{','.join(steps)}[{label}]")
            labels.append(f"[{label}]")
        if len(labels) == 1:
            filter_complex = f"{chains[0]}"
            map_ref = labels[0]
        else:
            mix = f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[mix]"
            filter_complex = ";".join([*chains, mix])
            map_ref = "[mix]"
        return cls(input_args, filter_complex, map_ref, tmpdir)
