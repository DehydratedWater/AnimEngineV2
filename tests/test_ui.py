"""GUI smoke tests (offscreen): window construction + tool behaviours driven
through the same ToolEvent path the canvas uses."""

import pytest

from animengine.core import Vec2


@pytest.fixture(scope="module")
def qapp():
    from animengine.render import ensure_gui_app

    yield ensure_gui_app()


@pytest.fixture
def window(qapp):
    from animengine.ui.app import MainWindow

    win = MainWindow()
    yield win
    win.close()


def ev(x, y, **kw):
    from animengine.ui.tools import ToolEvent

    return ToolEvent(pos=Vec2(x, y), **kw)


def active_shape(win, frame=None):
    layer = win.state.project.active_layer
    f = win.state.frame if frame is None else frame
    return layer.keyframes[f].shape


def test_window_builds(window):
    assert window.canvas.tool is not None
    assert window.canvas.tool.name == "select"
    assert len(window.tools) == 15


def test_line_tool(window):
    window._select_tool("line")
    t = window.canvas.tool
    t.press(ev(10, 10))
    t.move(ev(150, 90))
    t.release(ev(150, 90))
    shape = active_shape(window)
    assert len(shape.connections) == 1
    assert window.state.doc.commands.can_undo


def test_rect_and_fill(window):
    window._select_tool("rect")
    t = window.canvas.tool
    t.press(ev(20, 20))
    t.move(ev(220, 170))
    t.release(ev(220, 170))
    assert len(active_shape(window).connections) == 4
    window._select_tool("fill")
    window.canvas.tool.press(ev(120, 95))
    shape = active_shape(window)
    assert len(shape.fills) == 1
    # right-click removes
    window.canvas.tool.right_press(ev(120, 95))
    assert len(active_shape(window).fills) == 0


def test_curve_tool_stepback(window):
    window._select_tool("curve")
    t = window.canvas.tool
    t.press(ev(10, 100))
    t.press(ev(200, 100))
    t.right_press(ev(0, 0))  # step back one
    assert len(t.pts) == 1
    t.press(ev(200, 100))
    t.press(ev(60, 20))
    t.press(ev(140, 20))  # 4th click commits
    shape = active_shape(window)
    curves = [c for c in shape.connections.values() if c.kind.value == "cubic"]
    assert len(curves) == 1


def test_freehand_pen_closes(window):
    window._select_tool("pen")
    t = window.canvas.tool
    t.press(ev(50, 50))
    for p in [(150, 60), (160, 150), (60, 160), (52, 55)]:
        t.move(ev(*p))
    t.release(ev(52, 55))
    shape = active_shape(window)
    # closed loop -> region fillable
    assert shape.detect_region(Vec2(100, 100)) is not None


def test_select_marquee_and_move(window):
    window._select_tool("line")
    t = window.canvas.tool
    t.press(ev(10, 10))
    t.move(ev(100, 10))
    t.release(ev(100, 10))
    window._select_tool("select")
    s = window.canvas.tool
    s.press(ev(-40, -40))
    s.move(ev(120, 30))
    s.release(ev(120, 30))
    assert len(window.state.selected_points) == 2
    assert window.state.selection_box is not None
    # drag inside box to move
    box = window.state.selection_box
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    s.press(ev(cx, cy))
    s.move(ev(cx + 50, cy + 40))
    s.release(ev(cx + 50, cy + 40))
    shape = active_shape(window)
    ys = {round(p.pos.y) for p in shape.anchor_points()}
    assert 50 in ys


def test_select_point_drag_merge(window):
    p = window.state.project
    p.add_line(0, 0, 100, 0, snap=False)
    p.add_line(200, 200, 300, 200, snap=False)
    window._select_tool("select")
    s = window.canvas.tool
    shape = active_shape(window)
    src = next(pt for pt in shape.anchor_points() if pt.pos == Vec2(100, 0))
    s.press(ev(100, 0))
    s.move(ev(198, 199))
    s.release(ev(198, 199))
    shape = active_shape(window)
    assert src.id not in shape.points or len(shape.anchor_points()) == 3


def test_eraser(window):
    p = window.state.project
    p.add_line(10, 10, 60, 10, snap=False)
    window._select_tool("eraser")
    window.state.eraser_radius = 100
    t = window.canvas.tool
    t.press(ev(30, 10))
    t.release(ev(30, 10))
    assert len(active_shape(window).connections) == 0


def test_raster_brush(window):
    p = window.state.project
    p.new_raster_layer("paint")
    window._select_tool("brush")
    t = window.canvas.tool
    t.press(ev(50, 50))
    t.move(ev(120, 120))
    t.release(ev(120, 120))
    layer = p.active_layer
    img = p.doc.images[layer.keyframes[0].image_id]
    assert img.pixels[..., 3].sum() > 0
    p.undo()
    assert img.pixels[..., 3].sum() == 0


def test_raster_move(window):
    p = window.state.project
    p.new_raster_layer("m")
    window._select_tool("rmove")
    t = window.canvas.tool
    t.press(ev(10, 10))
    t.move(ev(60, 40))
    t.release(ev(60, 40))
    kf = p.active_layer.keyframes[0]
    assert (kf.placement.pos.x, kf.placement.pos.y) == (50, 30)


def test_timeline_copy_forward(window):
    p = window.state.project
    p.add_line(0, 0, 40, 40)
    window.timeline._copy_forward()
    assert p.current_frame == 1
    layer = p.doc.layers[0]
    assert 1 in layer.keyframes


def test_timeline_playback_tick(window):
    window.state.doc.length = 3
    window.timeline.toggle_play()
    assert window.state.playing
    window.timeline._tick()
    assert window.state.frame in (1, 2, 0)
    window.timeline.toggle_play()
    assert not window.state.playing


def test_picker_and_style(window):
    p = window.state.project
    p.add_line(0, 0, 80, 0, width=7.5, color="#123456", snap=False)
    window._select_tool("picker")
    window.canvas.tool.press(ev(40, 0))
    assert window.state.stroke_width == 7.5
    assert window.state.stroke_color.to_hex() == "#123456"


def test_scissors(window):
    p = window.state.project
    p.add_line(0, 50, 100, 50, snap=False)
    window._select_tool("cut")
    window.canvas.tool.press(ev(50, 50))
    assert len(active_shape(window).connections) == 2


def test_undo_shortcut_path(window):
    p = window.state.project
    p.add_line(0, 0, 10, 10)
    depth = p.doc.commands.depth
    window._undo()
    assert p.doc.commands.depth == depth - 1
    window._redo()
    assert p.doc.commands.depth == depth
