import math

from animengine.core.geometry import (
    Color,
    Rect,
    Transform2D,
    Vec2,
    point_in_polygon,
    point_segment_distance,
    polygon_area,
    quadratic_bezier,
    sample_quadratic,
    segment_intersection,
)


def test_vec_ops():
    a, b = Vec2(1, 2), Vec2(3, -1)
    assert a + b == Vec2(4, 1)
    assert a - b == Vec2(-2, 3)
    assert a * 2 == Vec2(2, 4)
    assert (b - b).length() == 0
    assert Vec2(3, 4).length() == 5
    assert a.lerp(b, 0.5) == Vec2(2.0, 0.5)


def test_vec_rotation():
    p = Vec2(1, 0).rotated(math.pi / 2)
    assert abs(p.x) < 1e-9 and abs(p.y - 1) < 1e-9
    q = Vec2(2, 0).rotated(math.pi, around=Vec2(1, 0))
    assert abs(q.x) < 1e-9 and abs(q.y) < 1e-9


def test_color():
    c = Color(255, 0, 0)
    assert c.to_hex() == "#ff0000"
    assert Color.from_hex("#ff0000") == c
    assert Color.from_hex("#11223344") == Color(0x11, 0x22, 0x33, 0x44)
    assert Color(0, 0, 0).lerp(Color(255, 255, 255), 0.5) == Color(128, 128, 128)


def test_rect_from_points():
    r = Rect.from_points([Vec2(1, 2), Vec2(5, -1), Vec2(3, 3)])
    assert (r.x, r.y, r.w, r.h) == (1, -1, 4, 4)
    assert r.contains(Vec2(3, 0))
    assert not r.contains(Vec2(0, 0))
    assert Rect.from_points([]) is None


def test_transform_compose():
    t = Transform2D.rotation(math.pi / 2, around=Vec2(1, 1))
    p = t.apply(Vec2(2, 1))
    assert abs(p.x - 1) < 1e-9 and abs(p.y - 2) < 1e-9
    st = Transform2D.scaling(2, 2, around=Vec2(1, 1))
    assert st.apply(Vec2(2, 1)) == Vec2(3, 1)


def test_bezier():
    p0, c, p1 = Vec2(0, 0), Vec2(1, 2), Vec2(2, 0)
    assert quadratic_bezier(p0, c, p1, 0) == p0
    assert quadratic_bezier(p0, c, p1, 1) == p1
    mid = quadratic_bezier(p0, c, p1, 0.5)
    assert mid == Vec2(1, 1)
    pts = sample_quadratic(p0, c, p1, 8)
    assert len(pts) == 9


def test_segment_intersection():
    assert segment_intersection(Vec2(0, 0), Vec2(2, 2), Vec2(0, 2), Vec2(2, 0)) == Vec2(1, 1)
    assert segment_intersection(Vec2(0, 0), Vec2(1, 0), Vec2(0, 1), Vec2(1, 1)) is None
    assert segment_intersection(Vec2(0, 0), Vec2(1, 1), Vec2(2, 2), Vec2(3, 3)) is None


def test_point_segment_distance():
    assert point_segment_distance(Vec2(0, 1), Vec2(-1, 0), Vec2(1, 0)) == 1
    assert point_segment_distance(Vec2(3, 0), Vec2(-1, 0), Vec2(1, 0)) == 2


def test_point_in_polygon():
    square = [Vec2(0, 0), Vec2(4, 0), Vec2(4, 4), Vec2(0, 4)]
    assert point_in_polygon(Vec2(2, 2), square)
    assert not point_in_polygon(Vec2(5, 2), square)
    assert abs(polygon_area(square)) == 16
