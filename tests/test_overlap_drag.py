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


def test_fill_drag_moves_foreign_control_handles():
    """A curve handle anchored to a fill's shared vertex must follow the drag."""
    from animengine.ui.state import EditorState
    from animengine.ui.tools import SelectTool, ToolEvent

    state = EditorState()
    p = state.project
    p.add_rect(0, 0, 100, 100)
    p.fill_region(50, 50, "#00cc66")
    # attach an outside curve to the square's corner (0,0): its start control
    # is anchored to the shared corner point
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
    moved_ctrl = shape.points[ctrl.id]
    assert moved_ctrl.pos.distance_to(old_ctrl_pos + Vec2(30, 40)) < 1e-6


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
