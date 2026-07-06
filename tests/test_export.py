import math
import struct
import wave
from io import BytesIO

import pytest
from PIL import Image

from animengine.audio import have_ffmpeg, probe_duration
from animengine.core import Color, Document, Vec2
from animengine.io.export import (
    export_gif,
    export_image,
    export_png_sequence,
    export_sprite_sheet,
    export_svg,
    export_video,
)


def make_wav(seconds: float = 0.5, freq: float = 440.0) -> bytes:
    buf = BytesIO()
    rate = 22050
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(rate * seconds)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
                for i in range(n)
            )
        )
    return buf.getvalue()


@pytest.fixture
def doc() -> Document:
    d = Document(120, 80, fps=10)
    d.name = "anim"
    d.length = 5
    layer = d.add_vector_layer()
    shape = layer.keyframes[0].shape
    a = shape.add_point(Vec2(20, 20))
    b = shape.add_point(Vec2(100, 20))
    c = shape.add_point(Vec2(100, 60))
    e = shape.add_point(Vec2(20, 60))
    for p, q in [(a, b), (b, c), (c, e), (e, a)]:
        shape.add_connection(p.id, q.id, width=2)
    shape.add_fill(shape.detect_region(Vec2(60, 40)), Color(0, 128, 255))
    d.copy_keyframe_forward(layer.id, 0, 4)
    for p in layer.keyframes[4].shape.points.values():
        p.pos = p.pos + Vec2(0, 10)
    return d


def test_export_image(doc, tmp_path):
    p = export_image(doc, 0, tmp_path / "still.png")
    img = Image.open(p)
    assert img.size == (120, 80)
    assert img.getpixel((60, 40))[:3] == (0, 128, 255)


def test_export_png_sequence(doc, tmp_path):
    calls = []
    paths = export_png_sequence(doc, tmp_path / "seq",
                                progress=lambda i, n: calls.append((i, n)))
    assert len(paths) == 5
    assert paths[0].name == "anim0000.png"
    assert all(p.exists() for p in paths)
    assert calls[-1] == (5, 5)


def test_export_gif(doc, tmp_path):
    p = export_gif(doc, tmp_path / "anim")
    img = Image.open(p)
    assert img.format == "GIF"
    img.seek(4)  # 5 frames present
    with pytest.raises(EOFError):
        img.seek(5)


def test_export_sprite_sheet(doc, tmp_path):
    p = export_sprite_sheet(doc, tmp_path / "sheet", columns=3)
    img = Image.open(p)
    assert img.size == (3 * 120, 2 * 80)


def test_export_svg(doc, tmp_path):
    p = export_svg(doc, 0, tmp_path / "frame")
    text = p.read_text()
    assert text.startswith("<?xml") and "<svg" in text


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg unavailable")
def test_export_mp4_with_audio(doc, tmp_path):
    doc.add_audio_clip("tone", make_wav(0.4), "wav", start_frame=1, gain=0.8)
    p = export_video(doc, tmp_path / "out.mp4")
    assert p.exists() and p.stat().st_size > 1000
    # container should contain an audio stream
    import subprocess

    from animengine.audio.mixing import FFPROBE
    out = subprocess.run([FFPROBE, "-v", "quiet", "-show_streams", str(p)],
                         capture_output=True, text=True)
    assert "codec_type=audio" in out.stdout and "codec_type=video" in out.stdout


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg unavailable")
def test_export_webm(doc, tmp_path):
    p = export_video(doc, tmp_path / "out.webm", include_audio=False)
    assert p.exists() and p.stat().st_size > 500


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg unavailable")
def test_probe_duration():
    d = probe_duration(make_wav(0.5), "wav")
    assert d is not None and abs(d - 0.5) < 0.05
