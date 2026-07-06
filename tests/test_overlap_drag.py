"""Regression tests: dragging filled shapes onto each other must cut lines
at the crossings, and fills must render solid (nonzero winding) like v1."""

import pytest

from animengine.api import AnimProject
from animengine.core import Color, Shape, Vec2
from animengine.render import render_frame


def make_two_squares(p: AnimProject) -> tuple[list[int], list[int]]:
    """Two filled squares far apart on one layer; returns their point ids."""
    p.add_rect(0, 0, 100, 100)
    p.fill_region(50, 50, "#00cc66")
    shape = p.active_layer.keyframes[0].shape
    a_ids = [pt.id for pt in shape.anchor_points()]
    p.add_rect(300, 20, 100, 100)
    p.fill_region(350, 70, "#e63946")
    b_ids = [pt.id for pt in shape.anchor_points() if pt.id not in a_ids]
    return a_ids, b_ids


def crossing_points(shape: Shape) -> list:
    """Anchor points of degree >= 3 (shared vertices created by cutting)."""
    idx = shape.index()
    return [p for p in shape.anchor_points()
            if len(idx.adjacency.get(p.id, ())) >= 3]


def test_api_transform_points_cuts_overlaps():
    p = AnimProject(600, 300)
    a_ids, b_ids = make_two_squares(p)
    shape = p.active_layer.keyframes[0].shape
    before_conns = len(shape.connections)
    # drag square B onto square A -> edges must be split at crossings
    p.transform_points(b_ids, dx=-250)
    shape = p.active_layer.keyframes[0].shape
    assert len(shape.connections) > before_conns, "no lines were cut at crossings"
    assert len(crossing_points(shape)) >= 2
    # both fills survive and follow their (re-cut) boundaries
    assert len(shape.fills) == 2


def test_select_tool_box_drag_cuts_overlaps():
    from animengine.ui.state import EditorState
    from animengine.ui.tools import SelectTool, ToolEvent

    state = EditorState()
    p = state.project
    a_ids, b_ids = make_two_squares(p)
    tool = SelectTool(state)

    def ev(x, y, **kw):
        return ToolEvent(pos=Vec2(x, y), **kw)

    # marquee-select square B, then drag it onto square A via the box
    tool.press(ev(280, -20))
    tool.move(ev(420, 140))
    tool.release(ev(420, 140))
    assert set(state.selected_points) == set(b_ids)
    box = state.selection_box
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    shape = p.active_layer.keyframes[0].shape
    before = len(shape.connections)
    tool.press(ev(cx, cy))
    tool.move(ev(cx - 250, cy + 30))
    tool.release(ev(cx - 250, cy + 30))
    shape = p.active_layer.keyframes[0].shape
    assert len(shape.connections) > before, "box drag did not cut crossing lines"
    assert len(crossing_points(shape)) >= 2


def test_fill_drag_detaches_from_welded_geometry():
    """Flash semantics: grabbing a fill rips its boundary free of geometry
    welded onto it — the outside curve stays put, the fill moves whole."""
    from animengine.ui.state import EditorState
    from animengine.ui.tools import SelectTool, ToolEvent

    state = EditorState()
    p = state.project
    p.add_rect(0, 0, 100, 100)
    p.fill_region(50, 50, "#00cc66")
    # attach an outside curve to the square's corner (0,0) (welded endpoint)
    p.add_curve(0, 0, -40, -40, -80, -10, -120, 0, snap=True)
    shape = p.active_layer.keyframes[0].shape
    ctrl = next(pt for pt in shape.points.values()
                if pt.is_control and shape.pos(pt.anchor) == Vec2(0, 0))
    old_ctrl_pos = ctrl.pos

    tool = SelectTool(state)

    def ev(x, y, **kw):
        return ToolEvent(pos=Vec2(x, y), **kw)

    tool.press(ev(50, 50))       # grab the fill
    tool.move(ev(80, 90))        # drag by (30, 40)
    tool.release(ev(80, 90))
    shape = p.active_layer.keyframes[0].shape
    # the outside curve and its handle did NOT move
    kept_ctrl = shape.points[ctrl.id]
    assert kept_ctrl.pos.distance_to(old_ctrl_pos) < 1e-6
    assert shape.nearest_point(Vec2(-120, 0), max_dist=1.0) is not None
    # the fill moved rigidly
    fill = next(iter(shape.fills.values()))
    assert shape.fill_contains(fill, Vec2(80, 90))
    assert not shape.fill_contains(fill, Vec2(10, 10))


@pytest.mark.parametrize("probe", [(60, 40), (60, 80)])
def test_self_crossing_fill_renders_solid(probe):
    """v1 used nonzero winding: a bowtie loop fills both lobes, no slivers."""
    from animengine.core import Document, FillEdge

    doc = Document(120, 120)
    layer = doc.add_vector_layer()
    s = layer.keyframes[0].shape
    a = s.add_point(Vec2(10, 10))
    b = s.add_point(Vec2(110, 10))
    c = s.add_point(Vec2(10, 110))
    d = s.add_point(Vec2(110, 110))
    ids = [s.add_connection(x, y).id
           for x, y in [(a.id, b.id), (b.id, c.id), (c.id, d.id), (d.id, a.id)]]
    s.add_fill([[FillEdge(i) for i in ids]], Color(255, 0, 0))
    img = render_frame(doc, 0)
    x, y = probe
    assert img.pixelColor(x, y).red() == 255, f"sliver at {probe}"


def test_hole_fill_still_has_hole():
    """Nonzero winding must not break holes (opposite orientation)."""
    from animengine.core import Document

    doc = Document(220, 220)
    layer = doc.add_vector_layer()
    s = layer.keyframes[0].shape
    for x0, y0, size in [(10, 10, 200), (80, 80, 60)]:
        pts = [s.add_point(Vec2(x0, y0)), s.add_point(Vec2(x0 + size, y0)),
               s.add_point(Vec2(x0 + size, y0 + size)), s.add_point(Vec2(x0, y0 + size))]
        for i in range(4):
            s.add_connection(pts[i].id, pts[(i + 1) % 4].id)
    loops = s.detect_region(Vec2(40, 40))
    assert loops is not None and len(loops) == 2
    s.add_fill(loops, Color(0, 0, 255))
    img = render_frame(doc, 0)
    ring = img.pixelColor(40, 40)
    hole = img.pixelColor(110, 110)
    assert ring.blue() == 255 and ring.red() == 0    # ring filled blue
    assert hole.red() == 255                          # hole stays white


def test_fill_outer_ring_skips_island_inside_hole():
    """User report: filling the outer shape must not fill a small disjoint
    shape sitting inside the hole."""
    from animengine.core import Document

    doc = Document(300, 300)
    layer = doc.add_vector_layer()
    s = layer.keyframes[0].shape
    for x0, y0, size in [(10, 10, 280), (60, 60, 180), (120, 120, 40)]:
        pts = [s.add_point(Vec2(x0, y0)), s.add_point(Vec2(x0 + size, y0)),
               s.add_point(Vec2(x0 + size, y0 + size)), s.add_point(Vec2(x0, y0 + size))]
        for i in range(4):
            s.add_connection(pts[i].id, pts[(i + 1) % 4].id)
    loops = s.detect_region(Vec2(30, 30))  # click the outer ring
    assert loops is not None
    assert len(loops) == 2  # outline + the big hole; NOT the island
    s.add_fill(loops, Color(255, 0, 0))
    img = render_frame(doc, 0)
    assert img.pixelColor(30, 30).red() == 255      # ring red
    assert img.pixelColor(90, 90).green() == 255    # hole white
    assert img.pixelColor(140, 140).green() == 255  # island interior stays white


def _drag_fill(state, frm, to):
    from animengine.ui.tools import SelectTool, ToolEvent

    tool = SelectTool(state)

    def ev(x, y, **kw):
        return ToolEvent(pos=Vec2(x, y), **kw)

    tool.press(ev(*frm))
    tool.move(ev(*to))
    tool.release(ev(*to))
    return tool


def test_drop_merge_consumes_hidden_corner():
    """User report: green dropped over red must destroy red's covered corner
    point/edges; red keeps only its visible remainder (Flash semantics)."""
    from animengine.ui.state import EditorState

    state = EditorState()
    p = state.project
    # red first (below), green second
    p.add_rect(200, 150, 300, 200)
    p.fill_region(350, 250, "#e63946")
    p.add_rect(600, 150, 240, 160)
    p.fill_region(700, 230, "#57cc7a")
    shape = p.active_layer.keyframes[0].shape
    # drag green fill so it covers red's top-right corner region
    _drag_fill(state, (700, 230), (450, 120))  # green now spans ~(350,40)-(590,200)
    shape = p.active_layer.keyframes[0].shape
    # red's original top-right corner (500,150) is covered -> the point is gone
    covered_corner = [pt for pt in shape.anchor_points()
                      if pt.pos.distance_to(Vec2(500, 150)) < 1.0]
    assert covered_corner == [], "hidden corner point survived the drop"
    # both fills exist; green is on top of the draw order
    assert len(shape.fills) == 2
    fills = list(shape.fills.values())
    green = fills[-1]
    assert green.color == Color(0x57, 0xCC, 0x7A)
    red = fills[0]
    # red no longer covers the overlap; still covers its remaining body
    assert not shape.fill_contains(red, Vec2(480, 170))
    assert shape.fill_contains(red, Vec2(300, 250))
    assert shape.fill_contains(green, Vec2(480, 170))


def test_drop_merge_spares_preexisting_decorations():
    """Reshaping a fill must NOT eat strokes that were already inside it."""
    from animengine.ui.state import EditorState

    state = EditorState()
    p = state.project
    p.add_rect(100, 100, 200, 200)
    p.fill_region(200, 200, "#ffcc00")
    p.add_line(150, 180, 250, 180, snap=False)  # an "eye" inside the fill
    shape = p.active_layer.keyframes[0].shape
    before = len(shape.connections)
    _drag_fill(state, (200, 260), (208, 266))  # nudge the fill slightly
    shape = p.active_layer.keyframes[0].shape
    assert len(shape.connections) == before, "decoration stroke was eaten"


def test_collinear_overlap_produces_no_duplicate_edges():
    """User report: shapes touching along a collinear edge created duplicate
    coincident connections that corrupted face tracing and fill colors."""
    p = AnimProject(700, 500)
    p.add_rect(30, 90, 240, 210)    # green right edge at x=270, y 90..300
    p.fill_region(150, 200, "#57cc7a")
    p.add_rect(270, 210, 300, 200)  # red left edge at x=270, y 210..410
    p.fill_region(420, 310, "#e63946")
    shape = p.active_layer.keyframes[0].shape
    # no two straight connections may share the same endpoint pair
    pairs = [frozenset((c.p1, c.p2)) for c in shape.connections.values()]
    assert len(pairs) == len(set(pairs)), "duplicate coincident edges exist"
    # both fills still hit-test correctly on their own side
    green = next(f for f in shape.fills.values() if f.color.to_hex() == "#57cc7a")
    red = next(f for f in shape.fills.values() if f.color.to_hex() == "#e63946")
    assert shape.fill_contains(green, Vec2(150, 200))
    assert shape.fill_contains(red, Vec2(420, 310))


def test_stick_drop_splits_both_shapes_with_colors():
    """A thin bar dropped across two shapes must cut both, keep every piece
    filled with its original color, and not deform either shape."""
    from animengine.ui.state import EditorState
    from animengine.ui.tools import SelectTool, ToolEvent

    state = EditorState()
    p = state.project
    p.add_rect(30, 90, 240, 210)
    p.fill_region(150, 200, "#57cc7a")
    p.add_rect(270, 210, 300, 200)
    p.fill_region(420, 310, "#e63946")
    p.add_polyline([(430, 40), (460, 60), (300, 170), (270, 150)], close=True)
    p.fill_region(370, 100, "#8b5a2b")

    tool = SelectTool(state)

    def ev(x, y):
        return ToolEvent(pos=Vec2(x, y))

    tool.press(ev(370, 100))
    for i in range(1, 7):
        t = i / 6
        tool.move(ev(370 + (280 - 370) * t, 100 + (260 - 100) * t))
    tool.release(ev(280, 260))

    shape = p.active_layer.keyframes[0].shape
    colors = sorted(f.color.to_hex() for f in shape.fills.values())
    # stick + at least one green and one red piece; pieces on both sides
    assert "#8b5a2b" in colors
    assert colors.count("#57cc7a") >= 1 and colors.count("#e63946") >= 2
    # green body is intact (not deformed): its interior still green
    greens = [f for f in shape.fills.values() if f.color.to_hex() == "#57cc7a"]
    assert any(shape.fill_contains(g, Vec2(100, 150)) for g in greens)
    assert any(shape.fill_contains(g, Vec2(60, 280)) for g in greens)
    # red main body + its cut-off corner piece both red
    reds = [f for f in shape.fills.values() if f.color.to_hex() == "#e63946"]
    assert any(shape.fill_contains(r, Vec2(500, 300)) for r in reds)
