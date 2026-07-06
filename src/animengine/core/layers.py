"""Layers and keyframes with interpolation.

The original stored a full scene snapshot per frame with no tweening. V2
keeps that workflow (copy-keyframe-and-edit) but stores *sparse* keyframes
per layer and interpolates between them:

- Vector layers tween point positions, stroke widths and colors between
  keyframes whose entities share stable IDs (which they do naturally when a
  keyframe is created by copying the previous one). Topology (which
  connections/fills exist) always comes from the left keyframe.
- Raster layers tween the image placement (position/scale/rotation/opacity);
  pixels switch at keyframes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .raster import Placement
from .scene import Shape


class Interp(StrEnum):
    HOLD = "hold"
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"

    def apply(self, t: float) -> float:
        if self is Interp.HOLD:
            return 0.0
        if self is Interp.EASE_IN:
            return t * t
        if self is Interp.EASE_OUT:
            return 1 - (1 - t) * (1 - t)
        if self is Interp.EASE_IN_OUT:
            return t * t * (3 - 2 * t)
        return t


@dataclass(slots=True)
class VectorKeyframe:
    frame: int
    shape: Shape
    interp: Interp = Interp.LINEAR


@dataclass(slots=True)
class RasterKeyframe:
    frame: int
    image_id: int  # RasterImage asset id
    placement: Placement = field(default_factory=Placement)
    interp: Interp = Interp.LINEAR


class LayerKind(StrEnum):
    VECTOR = "vector"
    RASTER = "raster"


class Layer:
    """Common layer behaviour: sparse keyframes on an integer frame axis."""

    kind: LayerKind

    def __init__(self, id: int, name: str):
        self.id = id
        self.name = name
        self.visible = True
        self.locked = False
        self.opacity = 1.0
        self.keyframes: dict[int, VectorKeyframe | RasterKeyframe] = {}

    # -------------------------------------------------- keyframe access
    def key_frames_sorted(self) -> list[int]:
        return sorted(self.keyframes)

    def key_at(self, frame: int):
        return self.keyframes.get(frame)

    def prev_key_frame(self, frame: int) -> int | None:
        candidates = [f for f in self.keyframes if f <= frame]
        return max(candidates) if candidates else None

    def next_key_frame(self, frame: int) -> int | None:
        candidates = [f for f in self.keyframes if f > frame]
        return min(candidates) if candidates else None

    def last_key_frame(self) -> int | None:
        return max(self.keyframes) if self.keyframes else None

    def remove_keyframe(self, frame: int) -> None:
        self.keyframes.pop(frame, None)

    def move_keyframe(self, src: int, dst: int) -> None:
        if src in self.keyframes and dst not in self.keyframes:
            kf = self.keyframes.pop(src)
            kf.frame = dst
            self.keyframes[dst] = kf

    def _segment(self, frame: int):
        """(left key, right key or None, eased t) for an interpolation query."""
        f0 = self.prev_key_frame(frame)
        if f0 is None:
            return None, None, 0.0
        k0 = self.keyframes[f0]
        f1 = self.next_key_frame(frame)
        if f1 is None or f0 == frame:
            return k0, None, 0.0
        t = (frame - f0) / (f1 - f0)
        return k0, self.keyframes[f1], k0.interp.apply(t)


class VectorLayer(Layer):
    kind = LayerKind.VECTOR

    def set_keyframe(self, frame: int, shape: Shape | None = None,
                     interp: Interp = Interp.LINEAR) -> VectorKeyframe:
        kf = VectorKeyframe(frame, shape if shape is not None else Shape(), interp)
        self.keyframes[frame] = kf
        return kf

    def ensure_keyframe(self, frame: int) -> VectorKeyframe:
        """Get the keyframe at *frame*, creating one from the current
        interpolated state if none exists (edit-anywhere QoL)."""
        kf = self.keyframes.get(frame)
        if kf is not None:
            return kf
        shape = self.shape_at(frame)
        return self.set_keyframe(frame, shape if shape is not None else Shape())

    def shape_at(self, frame: int) -> Shape | None:
        """Interpolated shape shown at *frame* (None = layer not present yet).

        Always returns a private clone safe to mutate for preview; edits must
        go through ensure_keyframe().shape.
        """
        k0, k1, t = self._segment(frame)
        if k0 is None:
            return None
        if k1 is None or t <= 0.0:
            return k0.shape.clone()
        return interpolate_shapes(k0.shape, k1.shape, t)


class RasterLayer(Layer):
    kind = LayerKind.RASTER

    def set_keyframe(self, frame: int, image_id: int,
                     placement: Placement | None = None,
                     interp: Interp = Interp.LINEAR) -> RasterKeyframe:
        kf = RasterKeyframe(frame, image_id,
                            placement if placement is not None else Placement(), interp)
        self.keyframes[frame] = kf
        return kf

    def ensure_keyframe(self, frame: int) -> RasterKeyframe | None:
        kf = self.keyframes.get(frame)
        if kf is not None:
            return kf
        state = self.state_at(frame)
        if state is None:
            return None
        image_id, placement = state
        return self.set_keyframe(frame, image_id, placement)

    def state_at(self, frame: int) -> tuple[int, Placement] | None:
        """(image_id, interpolated placement) at *frame*."""
        k0, k1, t = self._segment(frame)
        if k0 is None:
            return None
        if k1 is None or t <= 0.0:
            return k0.image_id, k0.placement.copy()
        return k0.image_id, k0.placement.lerp(k1.placement, t)


def interpolate_shapes(s0: Shape, s1: Shape, t: float) -> Shape:
    """Tween between two shapes: topology of s0, values lerped where IDs match."""
    out = s0.clone()
    for pid, p in out.points.items():
        q = s1.points.get(pid)
        if q is not None:
            p.pos = p.pos.lerp(q.pos, t)
    for cid, c in out.connections.items():
        d = s1.connections.get(cid)
        if d is not None:
            c.width = c.width + (d.width - c.width) * t
            c.color = c.color.lerp(d.color, t)
    for fid, f in out.fills.items():
        g = s1.fills.get(fid)
        if g is not None:
            f.color = f.color.lerp(g.color, t)
    return out
