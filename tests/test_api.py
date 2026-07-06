import pytest

from animengine.api import AnimProject
from animengine.core import Color, Vec2


@pytest.fixture
def proj() -> AnimProject:
    return AnimProject(200, 200, fps=12)


def shape_of(proj: AnimProject, frame: int = 0):
    return proj.active_layer.keyframes[frame].shape


def test_draw_square_and_fill(proj):
    proj.add_rect(50, 50, 100, 100)
    result = proj.fill_region(100, 100, "#ff0000")
    assert result is not None
    s = shape_of(proj)
    assert len(s.fills) == 1
    assert next(iter(s.fills.values())).color == Color(255, 0, 0)


def test_lines_snap_and_intersect(proj):
    a = proj.add_line(0, 100, 200, 100)
    proj.add_line(100, 0, 100, 200)
    s = shape_of(proj)
    assert len(s.connections) == 4  # cross split into 4
    assert a["connection_id"] not in s.connections  # original was split
    # fill one quadrant after closing it
    proj.add_polyline([(0, 100), (0, 0), (100, 0)], close=False)
    assert proj.fill_region(50, 50, "#00ff00") is not None


def test_undo_redo_roundtrip(proj):
    proj.add_line(10, 10, 90, 90)
    assert len(shape_of(proj).connections) == 1
    proj.undo()
    kf = proj.active_layer.keyframes[0]
    assert len(kf.shape.connections) == 0
    proj.redo()
    assert len(proj.active_layer.keyframes[0].shape.connections) == 1


def test_move_point_with_merge(proj):
    proj.add_line(10, 10, 90, 10)
    proj.add_line(10, 50, 90, 50)
    s = shape_of(proj)
    ids = [p.id for p in s.anchor_points()]
    assert len(ids) == 4
    # move one endpoint onto another -> weld
    moving = next(p for p in s.anchor_points() if p.pos == Vec2(90, 50))
    target = next(p for p in s.anchor_points() if p.pos == Vec2(90, 10))
    proj.move_point(moving.id, 92, 12)
    s = shape_of(proj)
    assert len(s.anchor_points()) == 3
    assert target.id in s.points


def test_transform_points_rotate(proj):
    proj.add_rect(0, 0, 100, 100)
    ids = [p.id for p in shape_of(proj).anchor_points()]
    proj.transform_points(ids, rotate_deg=90)
    s = shape_of(proj)
    xs = sorted(round(p.pos.x) for p in s.anchor_points())
    assert xs == [0, 0, 100, 100]  # square rotated about centroid stays a square


def test_keyframe_workflow(proj):
    proj.add_line(0, 0, 50, 50)
    frame = proj.copy_frame_forward()
    assert frame == 1
    assert 1 in proj.active_layer.keyframes
    proj.undo()
    assert 1 not in proj.active_layer.keyframes
    assert proj.current_frame == 0
    proj.redo()
    assert 1 in proj.active_layer.keyframes


def test_edit_on_tweened_frame_creates_keyframe(proj):
    proj.add_line(0, 0, 50, 0)
    proj.add_keyframe(frame=10)
    proj.set_frame(5)
    proj.add_line(0, 20, 50, 20)
    assert 5 in proj.active_layer.keyframes
    assert len(proj.active_layer.keyframes[5].shape.connections) == 2


def test_cut_and_style(proj):
    r = proj.add_line(0, 0, 100, 0)
    pid = proj.cut_connection_at(50, 0)
    assert pid is not None
    s = shape_of(proj)
    assert len(s.connections) == 2
    cid = next(iter(s.connections))
    proj.set_connection_style(cid, width=9, color="#00ff00")
    assert s.connections[cid].width == 9  # same object mutated
    assert r["connection_id"] not in s.connections


def test_erase(proj):
    proj.add_line(0, 0, 10, 0)
    proj.add_line(100, 100, 150, 150)
    n = proj.erase_at(5, 0, 20)
    assert n == 2
    assert len(shape_of(proj).connections) == 1


def test_raster_paint_and_undo(proj):
    layer = proj.new_raster_layer("paint")
    proj.paint_stroke([(10, 10), (50, 50)], width=6, color="#0000ff")
    kf = layer.keyframes[0]
    img = proj.doc.images[kf.image_id]
    assert img.pixels[..., 3].sum() > 0  # something painted
    proj.undo()
    assert img.pixels[..., 3].sum() == 0


def test_locked_layer_rejects_edit(proj):
    proj.set_layer_props(proj.active_layer_id, locked=True)
    with pytest.raises(PermissionError):
        proj.add_line(0, 0, 10, 10)


def test_scene_info_and_summary(proj):
    proj.add_line(1, 2, 3, 4, snap=False)
    info = proj.scene_info()
    assert info["kind"] == "vector"
    assert len(info["shape"]["points"]) == 2
    s = proj.summary()
    assert s["current_frame"] == 0
    assert s["undo_depth"] == 1


def test_render_png_bytes(proj):
    proj.add_rect(10, 10, 50, 50)
    data = proj.render_png(scale=0.5)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_save_open_roundtrip(proj, tmp_path):
    proj.add_rect(10, 10, 100, 100)
    proj.fill_region(60, 60, "#123456")
    p = proj.save(tmp_path / "demo")
    loaded = AnimProject.open(p)
    s = loaded.active_layer.keyframes[0].shape
    assert len(s.fills) == 1
