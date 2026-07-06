from pathlib import Path

import pytest

from animengine.core import Color, Document, Interp, Placement, Vec2
from animengine.io import load_legacy_ae, load_project, save_project
from animengine.render import render_frame

LEGACY_DIR = Path("/home/dw/programing/AnimEngine/AnimEngine")


def build_doc() -> Document:
    doc = Document(320, 240, fps=12)
    doc.length = 24
    layer = doc.add_vector_layer("art")
    shape = layer.keyframes[0].shape
    shape.add_line(Vec2(10, 10), Vec2(100, 10), width=5, color=Color(255, 0, 0))
    shape.add_quad_curve(Vec2(10, 50), Vec2(60, 100), Vec2(110, 50))
    doc.copy_keyframe_forward(layer.id, 0, 12)
    layer.keyframes[12].interp = Interp.EASE_IN_OUT
    img = doc.new_image("paint", 64, 64)
    img.pixels[10:20, 10:20] = [1, 2, 3, 255]
    doc.add_raster_layer("bmp", image=img, placement=Placement(pos=Vec2(5, 6)))
    doc.add_audio_clip("beep", b"RIFFfake", "wav", start_frame=3, gain=0.7)
    return doc


def test_native_roundtrip(tmp_path):
    doc = build_doc()
    p = save_project(doc, tmp_path / "proj")
    assert p.suffix == ".aep2"
    loaded = load_project(p)
    assert (loaded.width, loaded.height, loaded.fps) == (320, 240, 12)
    assert loaded.length == 24
    assert len(loaded.layers) == 2
    vec = loaded.layers[0]
    assert vec.key_frames_sorted() == [0, 12]
    assert vec.keyframes[12].interp is Interp.EASE_IN_OUT
    shape = vec.keyframes[0].shape
    assert len(shape.connections) == 2
    conn = next(iter(shape.connections.values()))
    assert conn.color == Color(255, 0, 0) and conn.width == 5
    ras = loaded.layers[1]
    image_id, placement = ras.state_at(0)
    assert placement.pos == Vec2(5, 6)
    img = loaded.images[image_id]
    assert (img.pixels[15, 15] == [1, 2, 3, 255]).all()
    clip = loaded.audio_clips[0]
    assert clip.data == b"RIFFfake" and clip.start_frame == 3 and clip.gain == 0.7
    # renders identically-shaped output
    assert render_frame(loaded, 0).width() == 320


def test_native_roundtrip_preserves_ids_for_interp(tmp_path):
    doc = build_doc()
    loaded = load_project(save_project(doc, tmp_path / "p2"))
    vec = loaded.layers[0]
    mid = vec.shape_at(6)
    assert mid is not None and len(mid.connections) == 2


@pytest.mark.skipif(not LEGACY_DIR.exists(), reason="legacy samples not available")
class TestLegacyImport:
    def test_null_ae(self):
        doc = load_legacy_ae(LEGACY_DIR / "null.ae")
        assert (doc.width, doc.height) == (1280, 720)
        assert doc.length == 1
        assert len(doc.layers) == 1
        assert doc.layers[0].keyframes[0].shape.is_empty()

    def test_ttt_polygons(self):
        doc = load_legacy_ae(LEGACY_DIR / "ttt")
        shape = doc.layers[0].keyframes[0].shape
        assert len(shape.points) == 8
        assert len(shape.connections) == 8
        assert len(shape.fills) == 1
        fill = next(iter(shape.fills.values()))
        assert fill.color == Color(0, 0, 255, 255)
        assert len(fill.loops) == 2  # outer square + hole
        assert len(fill.loops[0]) == 4 and len(fill.loops[1]) == 4
        # blue between squares, hole white
        assert shape.fill_contains(fill, Vec2(400, 200))
        assert not shape.fill_contains(fill, Vec2(550, 300))
        img = render_frame(doc, 0)
        assert img.pixelColor(400, 200).blue() == 255
        assert img.pixelColor(400, 200).red() == 0
        assert img.pixelColor(550, 300).red() == 255  # hole shows white bg

    def test_old_format_animacja(self):
        doc = load_legacy_ae(LEGACY_DIR / "ANIMACJA.txt")
        assert (doc.width, doc.height) == (720, 480)
        shape = doc.layers[0].keyframes[0].shape
        assert len(shape.points) == 9
        assert len(shape.connections) == 9
        conn = next(iter(shape.connections.values()))
        assert conn.width == 3.0

    def test_dd_sample(self):
        doc = load_legacy_ae(LEGACY_DIR / "dd")
        assert doc.length >= 1
        render_frame(doc, 0)  # must not crash
