from animengine.core import Color, ConnKind, Shape, Vec2


def square_shape(size: float = 100.0) -> Shape:
    s = Shape()
    a = s.add_point(Vec2(0, 0))
    b = s.add_point(Vec2(size, 0))
    c = s.add_point(Vec2(size, size))
    d = s.add_point(Vec2(0, size))
    s.add_connection(a.id, b.id)
    s.add_connection(b.id, c.id)
    s.add_connection(c.id, d.id)
    s.add_connection(d.id, a.id)
    return s


def test_add_line_snaps_to_existing_point():
    s = Shape()
    s.add_line(Vec2(0, 0), Vec2(100, 0))
    s.add_line(Vec2(3, 1), Vec2(50, 80), snap_radius=15)
    assert len(s.points) == 3  # start snapped onto (0,0)
    assert len(s.connections) == 2


def test_curves_have_control_points():
    s = Shape()
    c = s.add_cubic_curve(Vec2(0, 0), Vec2(10, 50), Vec2(90, 50), Vec2(100, 0))
    assert c.kind is ConnKind.CUBIC
    controls = [p for p in s.points.values() if p.is_control]
    assert len(controls) == 2
    pts = s.sample_connection(c)
    assert pts[0] == Vec2(0, 0) and pts[-1] == Vec2(100, 0)
    assert all(p.y >= 0 for p in pts)


def test_remove_point_removes_connections_and_fills():
    s = square_shape()
    region = s.detect_region(Vec2(50, 50))
    assert region is not None
    s.add_fill(region, Color(255, 0, 0))
    assert len(s.fills) == 1
    pid = next(iter(s.points))
    s.remove_point(pid)
    assert len(s.fills) == 0
    assert len(s.connections) == 2


def test_merge_points_rewires():
    s = Shape()
    a = s.add_point(Vec2(0, 0))
    b = s.add_point(Vec2(100, 0))
    b2 = s.add_point(Vec2(101, 1))
    c = s.add_point(Vec2(200, 0))
    s.add_connection(a.id, b.id)
    s.add_connection(b2.id, c.id)
    s.merge_points(b.id, b2.id)
    assert len(s.points) == 3
    conns = list(s.connections.values())
    assert {conns[0].p1, conns[0].p2} == {a.id, b.id}
    assert {conns[1].p1, conns[1].p2} == {b.id, c.id}


def test_split_line_preserves_fill():
    s = square_shape()
    s.add_fill(s.detect_region(Vec2(50, 50)), Color(0, 255, 0))
    cid = next(iter(s.connections))
    mid, n1, n2 = s.split_connection(cid, Vec2(50, 0))
    assert cid not in s.connections
    fill = next(iter(s.fills.values()))
    assert len(fill.loops[0]) == 5  # 4 edges -> 5 after split
    assert n1.id in fill.connection_ids() and n2.id in fill.connection_ids()


def test_split_quad_curve_midpoint_stays_on_curve():
    s = Shape()
    c = s.add_quad_curve(Vec2(0, 0), Vec2(50, 100), Vec2(100, 0))
    before = s.sample_connection(c, samples=64)
    mid, n1, n2 = s.split_connection(c.id, Vec2(50, 50))
    # midpoint of split must lie on the original curve (t=0.5 -> (50, 50))
    assert abs(mid.pos.x - 50) < 1.0 and abs(mid.pos.y - 50) < 1.0
    after = s.sample_connection(n1, 32) + s.sample_connection(n2, 32)
    for p in after[:: 8]:
        assert min(p.distance_to(q) for q in before) < 1.5


def test_insert_intersections_splits_cross():
    s = Shape()
    s.add_line(Vec2(0, 50), Vec2(100, 50))
    c2 = s.add_line(Vec2(50, 0), Vec2(50, 100))
    n = s.insert_intersections([c2.id])
    assert n == 1
    assert len(s.connections) == 4
    # exactly one shared point at (50,50) with degree 4
    center = [p for p in s.points.values() if p.pos.distance_to(Vec2(50, 50)) < 1e-6]
    assert len(center) == 1
    deg = sum(1 for c in s.connections.values() if center[0].id in (c.p1, c.p2))
    assert deg == 4


def test_detect_region_square():
    s = square_shape()
    loops = s.detect_region(Vec2(50, 50))
    assert loops is not None
    assert len(loops) == 1
    assert len(loops[0]) == 4
    assert s.detect_region(Vec2(150, 50)) is None


def test_detect_region_with_hole():
    s = square_shape(200)
    inner = square_shape(50)
    # embed inner square shifted to (75,75)..(125,125)
    id_map = {}
    for p in inner.points.values():
        id_map[p.id] = s.add_point(p.pos + Vec2(75, 75)).id
    for c in inner.connections.values():
        s.add_connection(id_map[c.p1], id_map[c.p2])
    loops = s.detect_region(Vec2(60, 60))  # between outer and inner
    assert loops is not None
    assert len(loops) == 2  # outline + hole
    fill = s.add_fill(loops, Color(0, 0, 255))
    assert s.fill_contains(fill, Vec2(60, 60))
    assert not s.fill_contains(fill, Vec2(100, 100))  # inside the hole
    # clicking inside the inner square finds just the small region
    inner_loops = s.detect_region(Vec2(100, 100))
    assert inner_loops is not None and len(inner_loops) == 1
    assert len(inner_loops[0]) == 4


def test_detect_region_two_rooms():
    # a square with a vertical wall through the middle -> two rooms
    s = square_shape(100)
    wall = s.add_line(Vec2(50, 0), Vec2(50, 100), snap_radius=0)
    s.insert_intersections([wall.id])
    left = s.detect_region(Vec2(25, 50))
    right = s.detect_region(Vec2(75, 50))
    assert left is not None and right is not None
    left_ids = {e.conn_id for e in left[0]}
    right_ids = {e.conn_id for e in right[0]}
    assert left_ids != right_ids


def test_nearest_queries():
    s = square_shape()
    p = s.nearest_point(Vec2(2, 3), max_dist=10)
    assert p is not None and p.pos == Vec2(0, 0)
    c = s.nearest_connection(Vec2(50, -4), max_dist=10)
    assert c is not None
    assert s.nearest_point(Vec2(500, 500), max_dist=10) is None
