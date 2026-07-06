import numpy as np

from animengine.core import Color, Document, Placement, Vec2
from animengine.render import (
    qimage_from_raster,
    raster_from_qimage,
    render_frame,
    render_frame_png,
)


def make_square_doc() -> Document:
    doc = Document(width=200, height=200, fps=24)
    layer = doc.add_vector_layer("shapes")
    shape = layer.keyframes[0].shape
    a = shape.add_point(Vec2(50, 50))
    b = shape.add_point(Vec2(150, 50))
    c = shape.add_point(Vec2(150, 150))
    d = shape.add_point(Vec2(50, 150))
    for p, q in [(a, b), (b, c), (c, d), (d, a)]:
        shape.add_connection(p.id, q.id, width=3, color=Color(0, 0, 0))
    loops = shape.detect_region(Vec2(100, 100))
    shape.add_fill(loops, Color(255, 0, 0))
    return doc


def pixel(img, x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue(), c.alpha())


def test_render_filled_square():
    doc = make_square_doc()
    img = render_frame(doc, 0)
    assert img.width() == 200 and img.height() == 200
    assert pixel(img, 100, 100) == (255, 0, 0, 255)  # fill
    assert pixel(img, 10, 10) == (255, 255, 255, 255)  # background
    r, g, b, a = pixel(img, 100, 50)  # stroke on top edge
    assert r < 80 and g < 80 and b < 80


def test_render_scale_and_transparency():
    doc = make_square_doc()
    img = render_frame(doc, 0, scale=0.5, transparent=True)
    assert img.width() == 100
    assert pixel(img, 50, 50) == (255, 0, 0, 255)
    assert pixel(img, 5, 5)[3] == 0  # transparent background


def test_render_interpolated_motion():
    doc = make_square_doc()
    layer = doc.layers[0]
    doc.copy_keyframe_forward(layer.id, 0, 10)
    for p in layer.keyframes[10].shape.points.values():
        p.pos = p.pos + Vec2(0, -40)
    img5 = render_frame(doc, 5)
    # at frame 5 the square is shifted up by 20: center of fill still red
    assert pixel(img5, 100, 80) == (255, 0, 0, 255)
    # old bottom rows no longer covered
    assert pixel(img5, 100, 140) == (255, 255, 255, 255)


def test_render_raster_layer():
    doc = Document(width=100, height=100)
    img_asset = doc.new_image("tex", 20, 20)
    img_asset.pixels[:, :] = [0, 0, 255, 255]
    doc.add_raster_layer("R", image=img_asset,
                         placement=Placement(pos=Vec2(40, 40)))
    out = render_frame(doc, 0)
    assert pixel(out, 50, 50) == (0, 0, 255, 255)
    assert pixel(out, 10, 10) == (255, 255, 255, 255)


def test_raster_roundtrip():
    doc = Document()
    asset = doc.new_image("t", 8, 4)
    asset.pixels[1, 2] = [10, 20, 30, 255]
    qimg = qimage_from_raster(asset)
    back = raster_from_qimage(qimg)
    assert back.shape == (4, 8, 4)
    assert np.array_equal(back, asset.pixels)


def test_render_png_bytes():
    doc = make_square_doc()
    data = render_frame_png(doc, 0)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_hidden_layer_not_rendered():
    doc = make_square_doc()
    doc.layers[0].visible = False
    img = render_frame(doc, 0)
    assert pixel(img, 100, 100) == (255, 255, 255, 255)
