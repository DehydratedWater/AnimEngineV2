"""Vector scene model: points, connections (lines/curves), fills.

Design notes vs. the original Java AnimEngine:
- Entities use *stable integer IDs* instead of list indices, so deleting a
  point no longer requires renumbering every connection and polygon.
- A Connection is a line, quadratic or cubic Bezier discriminated by `kind`;
  Bezier control points are ordinary Points flagged `is_control` and linked
  to an anchor, exactly like the original's TechPoints, so selection
  transforms apply to them uniformly.
- Fills store directed references to boundary connections and rebuild their
  outline path from live geometry at render time, so moving points keeps
  fills attached (the original re-cut polygons on every edit instead).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .geometry import (
    BLACK,
    Color,
    Rect,
    Vec2,
    cubic_bezier,
    point_in_polygon,
    point_segment_distance,
    polygon_area,
    quadratic_bezier,
    segment_intersection,
)

CURVE_SAMPLES = 24  # samples used when flattening beziers for geometry tests


class ConnKind(StrEnum):
    LINE = "line"
    QUAD = "quad"  # one control point (c1)
    CUBIC = "cubic"  # two control points (c1, c2)


@dataclass(slots=True)
class Point:
    id: int
    pos: Vec2
    is_control: bool = False  # Bezier control handle ("TechPoint" in v1)
    anchor: int | None = None  # point id this control handle belongs to
    selected: bool = False

    def clone(self) -> Point:
        return Point(self.id, self.pos, self.is_control, self.anchor, False)


@dataclass(slots=True)
class Connection:
    id: int
    p1: int
    p2: int
    kind: ConnKind = ConnKind.LINE
    c1: int | None = None  # control point id (quad + cubic)
    c2: int | None = None  # second control point id (cubic)
    width: float = 3.0
    color: Color = BLACK
    only_shape: bool = False  # participates in fills but is not stroked
    selected: bool = False

    def clone(self) -> Connection:
        return Connection(
            self.id, self.p1, self.p2, self.kind, self.c1, self.c2,
            self.width, self.color, self.only_shape, False,
        )

    def endpoints(self) -> tuple[int, int]:
        return self.p1, self.p2

    def control_ids(self) -> list[int]:
        ids = []
        if self.kind in (ConnKind.QUAD, ConnKind.CUBIC) and self.c1 is not None:
            ids.append(self.c1)
        if self.kind is ConnKind.CUBIC and self.c2 is not None:
            ids.append(self.c2)
        return ids

    def other(self, point_id: int) -> int:
        return self.p2 if point_id == self.p1 else self.p1


@dataclass(slots=True)
class FillEdge:
    """One directed step along a fill boundary."""

    conn_id: int
    reversed: bool = False


@dataclass(slots=True)
class Fill:
    """A filled region bounded by connection loops (first loop = outline, rest = holes)."""

    id: int
    loops: list[list[FillEdge]]
    color: Color = Color(200, 200, 200)
    selected: bool = False

    def clone(self) -> Fill:
        return Fill(
            self.id,
            [[FillEdge(e.conn_id, e.reversed) for e in loop] for loop in self.loops],
            self.color,
            False,
        )

    def connection_ids(self) -> set[int]:
        return {e.conn_id for loop in self.loops for e in loop}


class Shape:
    """The vector content of one layer keyframe: a planar drawing.

    Owns points, connections and fills keyed by stable IDs. ID counters are
    per-shape; cloned shapes keep IDs so keyframe interpolation can match
    entities across keyframes.
    """

    def __init__(self) -> None:
        self.points: dict[int, Point] = {}
        self.connections: dict[int, Connection] = {}
        self.fills: dict[int, Fill] = {}
        self._next_point = 1
        self._next_conn = 1
        self._next_fill = 1

    # ------------------------------------------------------------- basics
    def clone(self) -> Shape:
        s = Shape()
        s.points = {i: p.clone() for i, p in self.points.items()}
        s.connections = {i: c.clone() for i, c in self.connections.items()}
        s.fills = {i: f.clone() for i, f in self.fills.items()}
        s._next_point = self._next_point
        s._next_conn = self._next_conn
        s._next_fill = self._next_fill
        return s

    def is_empty(self) -> bool:
        return not self.points and not self.connections and not self.fills

    def pos(self, point_id: int) -> Vec2:
        return self.points[point_id].pos

    # ------------------------------------------------------------ create
    def add_point(
        self,
        pos: Vec2,
        *,
        is_control: bool = False,
        anchor: int | None = None,
        id: int | None = None,
    ) -> Point:
        pid = id if id is not None else self._next_point
        self._next_point = max(self._next_point, pid + 1)
        p = Point(pid, pos, is_control, anchor)
        self.points[pid] = p
        return p

    def add_connection(
        self,
        p1: int,
        p2: int,
        *,
        kind: ConnKind = ConnKind.LINE,
        c1: int | None = None,
        c2: int | None = None,
        width: float = 3.0,
        color: Color = BLACK,
        only_shape: bool = False,
        id: int | None = None,
    ) -> Connection:
        if p1 not in self.points or p2 not in self.points:
            raise KeyError(f"unknown point id {p1 if p1 not in self.points else p2}")
        cid = id if id is not None else self._next_conn
        self._next_conn = max(self._next_conn, cid + 1)
        c = Connection(cid, p1, p2, kind, c1, c2, width, color, only_shape)
        self.connections[cid] = c
        return c

    def add_line(self, a: Vec2, b: Vec2, *, width: float = 3.0, color: Color = BLACK,
                 snap_radius: float = 0.0) -> Connection:
        """Convenience: create a line between two positions, snapping to existing points."""
        p1 = self.find_or_add_point(a, snap_radius)
        p2 = self.find_or_add_point(b, snap_radius)
        return self.add_connection(p1.id, p2.id, width=width, color=color)

    def add_quad_curve(self, a: Vec2, ctrl: Vec2, b: Vec2, *, width: float = 3.0,
                       color: Color = BLACK, snap_radius: float = 0.0) -> Connection:
        p1 = self.find_or_add_point(a, snap_radius)
        p2 = self.find_or_add_point(b, snap_radius)
        cp = self.add_point(ctrl, is_control=True, anchor=p1.id)
        return self.add_connection(p1.id, p2.id, kind=ConnKind.QUAD, c1=cp.id,
                                   width=width, color=color)

    def add_cubic_curve(self, a: Vec2, ctrl1: Vec2, ctrl2: Vec2, b: Vec2, *,
                        width: float = 3.0, color: Color = BLACK,
                        snap_radius: float = 0.0) -> Connection:
        p1 = self.find_or_add_point(a, snap_radius)
        p2 = self.find_or_add_point(b, snap_radius)
        cp1 = self.add_point(ctrl1, is_control=True, anchor=p1.id)
        cp2 = self.add_point(ctrl2, is_control=True, anchor=p2.id)
        return self.add_connection(p1.id, p2.id, kind=ConnKind.CUBIC, c1=cp1.id, c2=cp2.id,
                                   width=width, color=color)

    def add_fill(self, loops: list[list[FillEdge]], color: Color,
                 id: int | None = None) -> Fill:
        fid = id if id is not None else self._next_fill
        self._next_fill = max(self._next_fill, fid + 1)
        f = Fill(fid, loops, color)
        self.fills[fid] = f
        return f

    def find_or_add_point(self, pos: Vec2, snap_radius: float = 0.0) -> Point:
        if snap_radius > 0:
            hit = self.nearest_point(pos, max_dist=snap_radius, include_controls=False)
            if hit is not None:
                return hit
        return self.add_point(pos)

    # ------------------------------------------------------------ delete
    def remove_connection(self, conn_id: int, *, prune_points: bool = True) -> None:
        conn = self.connections.pop(conn_id, None)
        if conn is None:
            return
        for fid in [f.id for f in self.fills.values() if conn_id in f.connection_ids()]:
            del self.fills[fid]
        if prune_points:
            for pid in [conn.p1, conn.p2]:
                if pid in self.points and not self._point_used(pid):
                    del self.points[pid]
            for pid in conn.control_ids():
                self.points.pop(pid, None)

    def remove_point(self, point_id: int) -> None:
        """Remove a point and every connection using it (fills referencing those die too)."""
        p = self.points.get(point_id)
        if p is None:
            return
        for cid in [c.id for c in self.connections.values()
                    if point_id in (c.p1, c.p2) or point_id in c.control_ids()]:
            self.remove_connection(cid)
        self.points.pop(point_id, None)

    def remove_fill(self, fill_id: int) -> None:
        self.fills.pop(fill_id, None)

    def _point_used(self, point_id: int) -> bool:
        return any(
            point_id in (c.p1, c.p2) or point_id in c.control_ids()
            for c in self.connections.values()
        )

    # ------------------------------------------------------------ edit
    def move_point(self, point_id: int, pos: Vec2) -> None:
        self.points[point_id].pos = pos

    def merge_points(self, keep_id: int, remove_id: int) -> None:
        """Weld remove_id into keep_id, rewiring all connections."""
        if keep_id == remove_id or remove_id not in self.points:
            return
        for c in self.connections.values():
            if c.p1 == remove_id:
                c.p1 = keep_id
            if c.p2 == remove_id:
                c.p2 = keep_id
            if c.c1 == remove_id:
                c.c1 = keep_id
            if c.c2 == remove_id:
                c.c2 = keep_id
        for p in self.points.values():
            if p.anchor == remove_id:
                p.anchor = keep_id
        # degenerate connections (both ends welded together) die
        for cid in [c.id for c in self.connections.values() if c.p1 == c.p2]:
            self.remove_connection(cid, prune_points=False)
        del self.points[remove_id]

    def split_connection(self, conn_id: int, pos: Vec2) -> tuple[Point, Connection, Connection]:
        """Split a connection at (approximately) pos; returns (new point, part1, part2).

        Curves are split by parameter t of the nearest sample; control handles
        are re-fit so the two halves follow the original curve (de Casteljau).
        """
        conn = self.connections[conn_id]
        a, b = self.pos(conn.p1), self.pos(conn.p2)
        style = {"width": conn.width, "color": conn.color, "only_shape": conn.only_shape}

        if conn.kind is ConnKind.LINE:
            mid = self.add_point(pos)
            n1 = self.add_connection(conn.p1, mid.id, **style)
            n2 = self.add_connection(mid.id, conn.p2, **style)
        else:
            t = self._nearest_t(conn, pos)
            if conn.kind is ConnKind.QUAD:
                c = self.pos(conn.c1)
                # de Casteljau split of quadratic
                q0, q1 = a.lerp(c, t), c.lerp(b, t)
                m = q0.lerp(q1, t)
                mid = self.add_point(m)
                cp1 = self.add_point(q0, is_control=True, anchor=conn.p1)
                cp2 = self.add_point(q1, is_control=True, anchor=mid.id)
                n1 = self.add_connection(conn.p1, mid.id, kind=ConnKind.QUAD, c1=cp1.id, **style)
                n2 = self.add_connection(mid.id, conn.p2, kind=ConnKind.QUAD, c1=cp2.id, **style)
            else:
                c1p, c2p = self.pos(conn.c1), self.pos(conn.c2)
                p01, p12, p23 = a.lerp(c1p, t), c1p.lerp(c2p, t), c2p.lerp(b, t)
                p012, p123 = p01.lerp(p12, t), p12.lerp(p23, t)
                m = p012.lerp(p123, t)
                mid = self.add_point(m)
                ca = self.add_point(p01, is_control=True, anchor=conn.p1)
                cb = self.add_point(p012, is_control=True, anchor=mid.id)
                cc = self.add_point(p123, is_control=True, anchor=mid.id)
                cd = self.add_point(p23, is_control=True, anchor=conn.p2)
                n1 = self.add_connection(conn.p1, mid.id, kind=ConnKind.CUBIC,
                                         c1=ca.id, c2=cb.id, **style)
                n2 = self.add_connection(mid.id, conn.p2, kind=ConnKind.CUBIC,
                                         c1=cc.id, c2=cd.id, **style)
        self._replace_in_fills(conn_id, [n1, n2])
        # old control points of the split connection are gone
        old_controls = conn.control_ids()
        del self.connections[conn.id]
        for pid in old_controls:
            self.points.pop(pid, None)
        return mid, n1, n2

    def _replace_in_fills(self, conn_id: int, parts: list[Connection]) -> None:
        """Keep fills valid when a boundary connection is split into parts."""
        for f in self.fills.values():
            for loop in f.loops:
                for i, e in enumerate(loop):
                    if e.conn_id == conn_id:
                        repl = [FillEdge(p.id, e.reversed) for p in parts]
                        if e.reversed:
                            repl.reverse()
                        loop[i : i + 1] = repl
                        break

    def _nearest_t(self, conn: Connection, pos: Vec2) -> float:
        pts = self.sample_connection(conn)
        best_i = min(range(len(pts)), key=lambda i: pts[i].distance_to(pos))
        return best_i / (len(pts) - 1)

    # --------------------------------------------------------- geometry
    def sample_connection(self, conn: Connection, samples: int = CURVE_SAMPLES) -> list[Vec2]:
        """Flatten a connection into a polyline from p1 to p2."""
        a, b = self.pos(conn.p1), self.pos(conn.p2)
        if conn.kind is ConnKind.LINE:
            return [a, b]
        if conn.kind is ConnKind.QUAD:
            c = self.pos(conn.c1)
            return [quadratic_bezier(a, c, b, i / samples) for i in range(samples + 1)]
        c1p, c2p = self.pos(conn.c1), self.pos(conn.c2)
        return [cubic_bezier(a, c1p, c2p, b, i / samples) for i in range(samples + 1)]

    def nearest_point(self, pos: Vec2, max_dist: float = math.inf,
                      include_controls: bool = True) -> Point | None:
        best, best_d = None, max_dist
        for p in self.points.values():
            if not include_controls and p.is_control:
                continue
            d = p.pos.distance_to(pos)
            if d < best_d:
                best, best_d = p, d
        return best

    def nearest_connection(self, pos: Vec2, max_dist: float = math.inf) -> Connection | None:
        best, best_d = None, max_dist
        for c in self.connections.values():
            pts = self.sample_connection(c)
            for i in range(len(pts) - 1):
                d = point_segment_distance(pos, pts[i], pts[i + 1])
                if d < best_d:
                    best, best_d = c, d
        return best

    def bounding_rect(self) -> Rect | None:
        return Rect.from_points([p.pos for p in self.points.values()])

    def fill_polygon(self, f: Fill) -> list[list[Vec2]]:
        """Flattened outline polygons for a fill (one list per loop)."""
        out = []
        for loop in f.loops:
            poly: list[Vec2] = []
            for e in loop:
                conn = self.connections.get(e.conn_id)
                if conn is None:
                    return []  # boundary edge was deleted -> fill is dead
                pts = self.sample_connection(conn)
                if e.reversed:
                    pts = pts[::-1]
                poly.extend(pts[:-1])
            out.append(poly)
        return out

    def fill_contains(self, f: Fill, pos: Vec2) -> bool:
        loops = self.fill_polygon(f)
        if not loops:
            return False
        crossings = sum(point_in_polygon(pos, loop) for loop in loops if len(loop) >= 3)
        return crossings % 2 == 1

    # --------------------------------------------------- planarization
    def insert_intersections(self, new_conn_ids: list[int] | None = None) -> int:
        """Split connections at mutual crossings so the drawing stays planar.

        If new_conn_ids is given, only crossings involving those connections
        are resolved (the per-stroke behaviour of the original); otherwise all
        pairs are checked. Returns the number of intersection points inserted.
        """
        inserted = 0
        # iterate until stable; splits create new connections that may cross others
        for _ in range(256):
            pair = self._find_one_crossing(new_conn_ids)
            if pair is None:
                break
            (ca, cb, pos) = pair
            tip_a = self._tip_point_at(ca, pos)
            tip_b = self._tip_point_at(cb, pos)
            if tip_a is not None and tip_b is not None:
                # two strokes touching tip-to-tip: weld into one shared vertex
                self.merge_points(tip_a, tip_b)
            elif tip_a is not None:
                # tip of A lands mid-way on B: split B and weld
                _, b1, b2 = self.split_connection(cb, pos)
                self.merge_points(tip_a, b1.p2)
                if new_conn_ids is not None and cb in new_conn_ids:
                    new_conn_ids = [i for i in new_conn_ids if i != cb] + [b1.id, b2.id]
            elif tip_b is not None:
                _, a1, a2 = self.split_connection(ca, pos)
                self.merge_points(tip_b, a1.p2)
                if new_conn_ids is not None and ca in new_conn_ids:
                    new_conn_ids = [i for i in new_conn_ids if i != ca] + [a1.id, a2.id]
            else:
                _, a1, a2 = self.split_connection(ca, pos)
                mid_id = a1.p2  # shared midpoint of the two halves
                _, b1, b2 = self.split_connection(cb, pos)
                self.merge_points(mid_id, b1.p2)
                if new_conn_ids is not None:
                    new_conn_ids = [i for i in new_conn_ids if i not in (ca, cb)]
                    new_conn_ids += [a1.id, a2.id, b1.id, b2.id]
            inserted += 1
        return inserted

    def _tip_point_at(self, conn_id: int, pos: Vec2, tol: float = 1e-3) -> int | None:
        """Endpoint id of the connection if pos coincides with one of its tips."""
        c = self.connections[conn_id]
        if self.pos(c.p1).distance_to(pos) < tol:
            return c.p1
        if self.pos(c.p2).distance_to(pos) < tol:
            return c.p2
        return None

    def _find_one_crossing(
        self, restrict: list[int] | None
    ) -> tuple[int, int, Vec2] | None:
        conns = list(self.connections.values())
        restrict_set = set(restrict) if restrict is not None else None
        for i, ca in enumerate(conns):
            for cb in conns[i + 1 :]:
                if restrict_set is not None and ca.id not in restrict_set and cb.id not in restrict_set:
                    continue
                if set(ca.endpoints()) & set(cb.endpoints()):
                    continue  # sharing an endpoint is not a crossing
                hit = self._connections_cross(ca, cb)
                if hit is not None:
                    return ca.id, cb.id, hit
        return None

    def _connections_cross(self, ca: Connection, cb: Connection) -> Vec2 | None:
        pa = self.sample_connection(ca)
        pb = self.sample_connection(cb)
        tol = 1e-3
        for i in range(len(pa) - 1):
            for j in range(len(pb) - 1):
                hit = segment_intersection(pa[i], pa[i + 1], pb[j], pb[j + 1])
                if hit is None:
                    continue
                # a tip-to-tip touch between distinct points is a weld request;
                # but if it is not resolvable (would merge nothing) skip it
                at_a_tip = hit.distance_to(pa[0]) < tol or hit.distance_to(pa[-1]) < tol
                at_b_tip = hit.distance_to(pb[0]) < tol or hit.distance_to(pb[-1]) < tol
                if at_a_tip and at_b_tip:
                    continue  # tips already coincide -> handled by point snapping
                return hit
        return None

    # ------------------------------------------------------- fill trace
    def detect_region(self, pos: Vec2) -> list[list[FillEdge]] | None:
        """Find the enclosed region containing pos (bucket-fill target).

        Builds directed half-edges over anchor points, traces face cycles by
        always taking the most-clockwise outgoing edge, then picks the
        smallest-area face containing pos. Returns boundary loops (outline
        first, then any hole loops), or None if pos is not enclosed.
        """
        faces = self._trace_faces()
        best: tuple[float, list[FillEdge], list[Vec2]] | None = None
        for cycle in faces:
            poly = self._cycle_polygon(cycle)
            if len(poly) < 3:
                continue
            area = polygon_area(poly)
            if area <= 1e-9:  # only interior (CCW-in-screen) faces
                continue
            if point_in_polygon(pos, poly) and (best is None or area < best[0]):
                best = (area, cycle, poly)
        if best is None:
            return None
        _, outline, outline_poly = best
        loops = [outline]
        # holes: smallest containing faces of separate components inside the outline
        outline_conns = {e.conn_id for e in outline}
        for cycle in faces:
            poly = self._cycle_polygon(cycle)
            if len(poly) < 3 or polygon_area(poly) >= -1e-9:
                continue  # want exterior (negative-area) cycles of other components
            if {e.conn_id for e in cycle} & outline_conns:
                continue
            if all(point_in_polygon(p, outline_poly) for p in poly[:3]):
                loops.append(cycle)
        return loops

    def _cycle_polygon(self, cycle: list[FillEdge]) -> list[Vec2]:
        poly: list[Vec2] = []
        for e in cycle:
            pts = self.sample_connection(self.connections[e.conn_id])
            if e.reversed:
                pts = pts[::-1]
            poly.extend(pts[:-1])
        return poly

    def _trace_faces(self) -> list[list[FillEdge]]:
        # outgoing directed edges per point: (angle, conn_id, reversed)
        outgoing: dict[int, list[tuple[float, int, bool]]] = {}
        for c in self.connections.values():
            pts = self.sample_connection(c)
            if len(pts) < 2 or pts[0].distance_to(pts[-1]) < 1e-12 and len(pts) == 2:
                continue
            a_dir = pts[1] - pts[0]
            b_dir = pts[-2] - pts[-1]
            outgoing.setdefault(c.p1, []).append(
                (math.atan2(a_dir.y, a_dir.x), c.id, False)
            )
            outgoing.setdefault(c.p2, []).append(
                (math.atan2(b_dir.y, b_dir.x), c.id, True)
            )
        for lst in outgoing.values():
            lst.sort()

        visited: set[tuple[int, bool]] = set()
        faces: list[list[FillEdge]] = []
        for c in self.connections.values():
            for rev in (False, True):
                if (c.id, rev) in visited:
                    continue
                cycle: list[FillEdge] = []
                cur_id, cur_rev = c.id, rev
                for _ in range(len(self.connections) * 2 + 1):
                    if (cur_id, cur_rev) in visited:
                        cycle = []
                        break
                    visited.add((cur_id, cur_rev))
                    cycle.append(FillEdge(cur_id, cur_rev))
                    conn = self.connections[cur_id]
                    end = conn.p1 if cur_rev else conn.p2
                    # incoming direction angle (pointing back along the edge)
                    pts = self.sample_connection(conn)
                    if cur_rev:
                        back = pts[1] - pts[0]
                    else:
                        back = pts[-2] - pts[-1]
                    in_angle = math.atan2(back.y, back.x)
                    nxt = self._next_cw(outgoing.get(end, []), in_angle, cur_id, cur_rev)
                    if nxt is None:
                        cycle = []
                        break
                    cur_id, cur_rev = nxt
                    if cur_id == c.id and cur_rev == rev:
                        break
                if cycle:
                    faces.append(cycle)
        return faces

    @staticmethod
    def _next_cw(
        cands: list[tuple[float, int, bool]], in_angle: float, cur_id: int, cur_rev: bool
    ) -> tuple[int, bool] | None:
        """Next outgoing edge, first strictly clockwise from the incoming direction."""
        if not cands:
            return None
        best = None
        best_delta = math.inf
        for angle, cid, rev in cands:
            if cid == cur_id and rev != cur_rev and len(cands) > 1:
                # avoid immediately doubling back unless it's a dead end
                continue
            delta = (in_angle - angle) % (2 * math.pi)
            if delta < 1e-12:
                delta = 2 * math.pi
            if delta < best_delta:
                best_delta = delta
                best = (cid, rev)
        if best is None:
            # dead end: go back the way we came
            angle, cid, rev = cands[0]
            best = (cid, rev)
        return best

    # ---------------------------------------------------------- queries
    def anchor_points(self) -> list[Point]:
        return [p for p in self.points.values() if not p.is_control]

    def controls_of(self, point_id: int) -> list[Point]:
        return [p for p in self.points.values() if p.is_control and p.anchor == point_id]

    def stats(self) -> dict[str, int]:
        return {
            "points": len(self.points),
            "connections": len(self.connections),
            "fills": len(self.fills),
        }
