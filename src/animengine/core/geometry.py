"""Geometry primitives shared across the engine.

Pure Python + math only — no Qt imports here, so the core stays usable
headless (API, MCP server, tests) without a GUI stack.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def __add__(self, o: Vec2) -> Vec2:
        return Vec2(self.x + o.x, self.y + o.y)

    def __sub__(self, o: Vec2) -> Vec2:
        return Vec2(self.x - o.x, self.y - o.y)

    def __mul__(self, k: float) -> Vec2:
        return Vec2(self.x * k, self.y * k)

    __rmul__ = __mul__

    def __truediv__(self, k: float) -> Vec2:
        return Vec2(self.x / k, self.y / k)

    def __neg__(self) -> Vec2:
        return Vec2(-self.x, -self.y)

    def __iter__(self) -> Iterator[float]:
        yield self.x
        yield self.y

    def dot(self, o: Vec2) -> float:
        return self.x * o.x + self.y * o.y

    def cross(self, o: Vec2) -> float:
        return self.x * o.y - self.y * o.x

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def distance_to(self, o: Vec2) -> float:
        return math.hypot(self.x - o.x, self.y - o.y)

    def normalized(self) -> Vec2:
        n = self.length()
        return Vec2(self.x / n, self.y / n) if n > 1e-12 else Vec2()

    def perpendicular(self) -> Vec2:
        return Vec2(-self.y, self.x)

    def rotated(self, angle_rad: float, around: Vec2 | None = None) -> Vec2:
        c, s = math.cos(angle_rad), math.sin(angle_rad)
        p = self if around is None else self - around
        r = Vec2(p.x * c - p.y * s, p.x * s + p.y * c)
        return r if around is None else r + around

    def lerp(self, o: Vec2, t: float) -> Vec2:
        return Vec2(self.x + (o.x - self.x) * t, self.y + (o.y - self.y) * t)


@dataclass(frozen=True, slots=True)
class Color:
    """RGBA color, 0-255 channels."""

    r: int = 0
    g: int = 0
    b: int = 0
    a: int = 255

    def lerp(self, o: Color, t: float) -> Color:
        return Color(
            round(self.r + (o.r - self.r) * t),
            round(self.g + (o.g - self.g) * t),
            round(self.b + (o.b - self.b) * t),
            round(self.a + (o.a - self.a) * t),
        )

    def to_hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}" + (
            f"{self.a:02x}" if self.a != 255 else ""
        )

    @classmethod
    def from_hex(cls, s: str) -> Color:
        s = s.lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        a = int(s[6:8], 16) if len(s) >= 8 else 255
        return cls(r, g, b, a)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.a)


BLACK = Color(0, 0, 0)
WHITE = Color(255, 255, 255)
TRANSPARENT = Color(0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned rectangle (x, y = top-left)."""

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_points(cls, pts: Iterable[Vec2]) -> Rect | None:
        it = iter(pts)
        try:
            first = next(it)
        except StopIteration:
            return None
        minx = maxx = first.x
        miny = maxy = first.y
        for p in it:
            minx, maxx = min(minx, p.x), max(maxx, p.x)
            miny, maxy = min(miny, p.y), max(maxy, p.y)
        return cls(minx, miny, maxx - minx, maxy - miny)

    @property
    def center(self) -> Vec2:
        return Vec2(self.x + self.w / 2, self.y + self.h / 2)

    def contains(self, p: Vec2) -> bool:
        return self.x <= p.x <= self.x + self.w and self.y <= p.y <= self.y + self.h

    def expanded(self, m: float) -> Rect:
        return Rect(self.x - m, self.y - m, self.w + 2 * m, self.h + 2 * m)

    def united(self, o: Rect) -> Rect:
        x0, y0 = min(self.x, o.x), min(self.y, o.y)
        x1 = max(self.x + self.w, o.x + o.w)
        y1 = max(self.y + self.h, o.y + o.h)
        return Rect(x0, y0, x1 - x0, y1 - y0)


@dataclass(frozen=True, slots=True)
class Transform2D:
    """2x3 affine transform matrix: [a c e; b d f]."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @classmethod
    def translation(cls, dx: float, dy: float) -> Transform2D:
        return cls(e=dx, f=dy)

    @classmethod
    def scaling(cls, sx: float, sy: float, around: Vec2 | None = None) -> Transform2D:
        t = cls(a=sx, d=sy)
        return t if around is None else t.around(around)

    @classmethod
    def rotation(cls, angle_rad: float, around: Vec2 | None = None) -> Transform2D:
        c, s = math.cos(angle_rad), math.sin(angle_rad)
        t = cls(a=c, b=s, c=-s, d=c)
        return t if around is None else t.around(around)

    def around(self, pivot: Vec2) -> Transform2D:
        return (
            Transform2D.translation(pivot.x, pivot.y)
            @ self
            @ Transform2D.translation(-pivot.x, -pivot.y)
        )

    def __matmul__(self, o: Transform2D) -> Transform2D:
        return Transform2D(
            a=self.a * o.a + self.c * o.b,
            b=self.b * o.a + self.d * o.b,
            c=self.a * o.c + self.c * o.d,
            d=self.b * o.c + self.d * o.d,
            e=self.a * o.e + self.c * o.f + self.e,
            f=self.b * o.e + self.d * o.f + self.f,
        )

    def apply(self, p: Vec2) -> Vec2:
        return Vec2(self.a * p.x + self.c * p.y + self.e, self.b * p.x + self.d * p.y + self.f)


def quadratic_bezier(p0: Vec2, ctrl: Vec2, p1: Vec2, t: float) -> Vec2:
    """Point on a quadratic Bezier at parameter t in [0, 1]."""
    u = 1.0 - t
    return p0 * (u * u) + ctrl * (2 * u * t) + p1 * (t * t)


def cubic_bezier(p0: Vec2, c0: Vec2, c1: Vec2, p1: Vec2, t: float) -> Vec2:
    u = 1.0 - t
    return p0 * (u**3) + c0 * (3 * u * u * t) + c1 * (3 * u * t * t) + p1 * (t**3)


def sample_quadratic(p0: Vec2, ctrl: Vec2, p1: Vec2, segments: int = 16) -> list[Vec2]:
    return [quadratic_bezier(p0, ctrl, p1, i / segments) for i in range(segments + 1)]


def segment_intersection(
    a1: Vec2, a2: Vec2, b1: Vec2, b2: Vec2, eps: float = 1e-9
) -> Vec2 | None:
    """Intersection point of segments a1-a2 and b1-b2, or None.

    Endpoint touches count as intersections; collinear overlaps return None.
    """
    d1 = a2 - a1
    d2 = b2 - b1
    denom = d1.cross(d2)
    if abs(denom) < eps:
        return None
    t = (b1 - a1).cross(d2) / denom
    u = (b1 - a1).cross(d1) / denom
    if -eps <= t <= 1 + eps and -eps <= u <= 1 + eps:
        return a1 + d1 * t
    return None


def point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    ab = b - a
    denom = ab.length_sq()
    if denom < 1e-12:
        return p.distance_to(a)
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return p.distance_to(a + ab * t)


def point_in_polygon(p: Vec2, poly: Sequence[Vec2]) -> bool:
    """Even-odd rule point-in-polygon test."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        pi, pj = poly[i], poly[j]
        if (pi.y > p.y) != (pj.y > p.y):
            x_cross = pi.x + (p.y - pi.y) / (pj.y - pi.y) * (pj.x - pi.x)
            if p.x < x_cross:
                inside = not inside
        j = i
    return inside


def polygon_area(poly: Sequence[Vec2]) -> float:
    """Signed area (positive = counter-clockwise in y-down coordinates: clockwise visually)."""
    s = 0.0
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        s += a.cross(b)
    return s / 2.0
