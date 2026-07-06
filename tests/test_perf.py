"""Performance guards for huge hand-drawn scenes.

The original Java app coped with very large freehand drawings; these tests
keep the Python port honest. Budgets are generous (CI variance) but fail
loudly on O(n) editing or O(n^2) planarization regressions.
"""

import math
import time

import pytest

from animengine.core import Color, Document, Shape, Vec2
from animengine.render import render_frame


def build_freehand_scene(n_strokes: int, pts_per_stroke: int) -> Shape:
    """Simulated hand-drawn scene: wobbly polyline+bezier strokes."""
    s = Shape()
    for k in range(n_strokes):
        y0 = (k * 37) % 4000
        x0 = (k * 61) % 4000
        prev = s.add_point(Vec2(x0, y0))
        for i in range(1, pts_per_stroke):
            x = x0 + i * 6
            y = y0 + 40 * math.sin(i * 0.3 + k)
            nxt = s.add_point(Vec2(x, y))
            if i % 4 == 0:  # every 4th segment is a curve
                c1 = s.add_point(Vec2(x - 4, y - 8), is_control=True, anchor=prev.id)
                c2 = s.add_point(Vec2(x - 2, y + 8), is_control=True, anchor=nxt.id)
                s.add_connection(prev.id, nxt.id, kind="cubic", c1=c1.id, c2=c2.id)
            else:
                s.add_connection(prev.id, nxt.id)
            prev = nxt
    return s


@pytest.fixture(scope="module")
def big_shape() -> Shape:
    # ~200k points, ~160k connections (module-scoped: built once)
    shape = build_freehand_scene(n_strokes=800, pts_per_stroke=200)
    assert len(shape.points) > 190_000
    return shape


def timed(fn, *args, **kw):
    t0 = time.perf_counter()
    result = fn(*args, **kw)
    return result, time.perf_counter() - t0


def test_index_build_and_queries(big_shape):
    _, build_t = timed(big_shape.index)
    assert build_t < 5.0, f"index build too slow: {build_t:.2f}s"

    # snap query (every mouse press does this)
    _, q = timed(big_shape.nearest_point, Vec2(2000, 2000), 15.0)
    assert q < 0.01, f"nearest_point too slow: {q * 1000:.1f}ms"

    _, q = timed(big_shape.nearest_connection, Vec2(2000, 2000), 15.0)
    assert q < 0.05, f"nearest_connection too slow: {q * 1000:.1f}ms"

    pts, q = timed(big_shape.points_in_rect, 1000, 1000, 1400, 1400)
    assert q < 0.2, f"marquee query too slow: {q * 1000:.1f}ms"


def test_add_stroke_with_planarization(big_shape):
    conn, t = timed(big_shape.add_line, Vec2(100, 100), Vec2(700, 700),
                    snap_radius=15.0)
    _, t2 = timed(big_shape.insert_intersections, [conn.id])
    total = t + t2
    assert total < 1.0, f"stroke commit too slow: {total:.2f}s"


def test_incremental_move_and_merge(big_shape):
    idx = big_shape.index()
    some_point = next(p for p in big_shape.points.values() if not p.is_control)
    _, t = timed(big_shape.move_point, some_point.id,
                 some_point.pos + Vec2(300, 300))
    assert t < 0.01, f"move_point too slow: {t * 1000:.1f}ms"

    # merging two points must not scan the whole scene
    other = big_shape.add_point(some_point.pos + Vec2(1, 1))
    big_shape.add_connection(other.id, big_shape.add_point(Vec2(0, 0)).id)
    _, t = timed(big_shape.merge_points, some_point.id, other.id)
    assert t < 0.01, f"merge_points too slow: {t * 1000:.1f}ms"
    assert idx is big_shape.index()  # index survived incrementally


def test_render_and_cache_behaviour(big_shape):
    doc = Document(width=1280, height=720)
    layer = doc.add_vector_layer("big")
    layer.set_keyframe(0, big_shape)
    _, t_first = timed(render_frame, doc, 0, scale=0.5)
    assert t_first < 15.0, f"first render too slow: {t_first:.2f}s"
    # shape_at must not clone (that used to cost seconds per repaint)
    shape, t = timed(layer.shape_at, 0)
    assert shape is big_shape
    assert t < 0.001


def test_keyframe_copy_budget(big_shape):
    doc = Document()
    layer = doc.add_vector_layer("big")
    layer.set_keyframe(0, big_shape)
    _, t = timed(doc.copy_keyframe_forward, layer.id, 0, 1)
    assert t < 5.0, f"keyframe clone too slow: {t:.2f}s"
    assert 1 in layer.keyframes


def test_fill_still_works_after_scaling_changes():
    # regression: fills + region detection on a normal-size scene
    s = Shape()
    a = s.add_point(Vec2(0, 0))
    b = s.add_point(Vec2(100, 0))
    c = s.add_point(Vec2(100, 100))
    d = s.add_point(Vec2(0, 100))
    for p, q in [(a, b), (b, c), (c, d), (d, a)]:
        s.add_connection(p.id, q.id)
    loops = s.detect_region(Vec2(50, 50))
    assert loops is not None
    s.add_fill(loops, Color(255, 0, 0))
    assert len(s.fills) == 1
