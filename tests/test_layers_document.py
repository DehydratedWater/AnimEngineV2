import numpy as np

from animengine.core import (
    Color,
    Document,
    Interp,
    Placement,
    RasterImage,
    Vec2,
)


def test_vector_layer_interpolation():
    doc = Document()
    layer = doc.add_vector_layer("L")
    k0 = layer.keyframes[0]
    conn = k0.shape.add_line(Vec2(0, 0), Vec2(100, 0))
    # keyframe at 10: copy and move the whole line up
    doc.copy_keyframe_forward(layer.id, 0, 10)
    k10 = layer.keyframes[10]
    for p in k10.shape.points.values():
        p.pos = p.pos + Vec2(0, 100)
    k10.shape.connections[conn.id].width = 13.0

    mid = layer.shape_at(5)
    ys = sorted(p.pos.y for p in mid.points.values())
    assert ys == [50.0, 50.0]
    assert abs(mid.connections[conn.id].width - 8.0) < 1e-9
    # exact keyframes returned verbatim
    assert all(p.pos.y == 0 for p in layer.shape_at(0).points.values())
    assert all(p.pos.y == 100 for p in layer.shape_at(10).points.values())
    # holding past the last keyframe
    assert all(p.pos.y == 100 for p in layer.shape_at(20).points.values())


def test_hold_interpolation():
    doc = Document()
    layer = doc.add_vector_layer()
    layer.keyframes[0].interp = Interp.HOLD
    layer.keyframes[0].shape.add_line(Vec2(0, 0), Vec2(10, 0))
    doc.copy_keyframe_forward(layer.id, 0, 10)
    for p in layer.keyframes[10].shape.points.values():
        p.pos = p.pos + Vec2(0, 100)
    mid = layer.shape_at(9)
    assert all(p.pos.y == 0 for p in mid.points.values())


def test_color_interpolation():
    doc = Document()
    layer = doc.add_vector_layer()
    c = layer.keyframes[0].shape.add_line(Vec2(0, 0), Vec2(10, 0), color=Color(0, 0, 0))
    doc.copy_keyframe_forward(layer.id, 0, 4)
    layer.keyframes[4].shape.connections[c.id].color = Color(200, 100, 0)
    mid = layer.shape_at(2)
    assert mid.connections[c.id].color == Color(100, 50, 0)


def test_raster_layer_placement_tween():
    doc = Document()
    img = doc.new_image("tex", 32, 32)
    layer = doc.add_raster_layer("R", image=img)
    layer.set_keyframe(10, img.id, Placement(pos=Vec2(100, 0), rotation_deg=90))
    image_id, placement = layer.state_at(5)
    assert image_id == img.id
    assert placement.pos == Vec2(50, 0)
    assert placement.rotation_deg == 45
    assert layer.state_at(20)[1].rotation_deg == 90


def test_layer_before_first_keyframe_absent():
    doc = Document()
    layer = doc.add_vector_layer()
    layer.move_keyframe(0, 5)
    assert layer.shape_at(2) is None
    assert layer.shape_at(5) is not None


def test_document_layers_and_undo():
    doc = Document()
    a = doc.add_vector_layer("A")
    b = doc.add_vector_layer("B")
    assert [la.name for la in doc.layers] == ["A", "B"]
    doc.move_layer(b.id, 0)
    assert [la.name for la in doc.layers] == ["B", "A"]

    removed = []
    doc.run("Remove layer", lambda: removed.append(doc.remove_layer(a.id)),
            lambda: doc.layers.append(removed.pop()))
    assert len(doc.layers) == 1
    assert doc.commands.can_undo
    assert doc.commands.undo() == "Remove layer"
    assert len(doc.layers) == 2
    assert doc.commands.can_redo
    doc.commands.redo()
    assert len(doc.layers) == 1


def test_ensure_keyframe_creates_snapshot():
    doc = Document()
    layer = doc.add_vector_layer()
    layer.keyframes[0].shape.add_line(Vec2(0, 0), Vec2(10, 0))
    doc.copy_keyframe_forward(layer.id, 0, 10)
    for p in layer.keyframes[10].shape.points.values():
        p.pos = p.pos + Vec2(0, 10)
    kf = layer.ensure_keyframe(5)
    assert 5 in layer.keyframes
    assert all(p.pos.y == 5 for p in kf.shape.points.values())


def test_raster_image_assets():
    doc = Document()
    img = doc.new_image("canvas", 64, 48)
    assert img.width == 64 and img.height == 48
    assert img.pixels.shape == (48, 64, 4)
    ext = RasterImage(0, "ext", np.zeros((8, 8, 4), np.uint8))
    reg = doc.register_image(ext)
    assert reg.id != 0 and reg.id in doc.images


def test_summary_shape():
    doc = Document()
    doc.add_vector_layer("V")
    info = doc.summary()
    assert info["layers"][0]["kind"] == "vector"
    assert info["layers"][0]["keyframes"] == [0]
