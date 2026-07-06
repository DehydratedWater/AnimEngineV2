"""Raster image assets and placement transforms."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .geometry import Vec2


@dataclass(slots=True)
class RasterImage:
    """A shared texture: RGBA uint8 pixel buffer (H, W, 4).

    Like the original textureManager, pixels live once and can be referenced
    by many keyframes/layers; painting affects every reference.
    """

    id: int
    name: str
    pixels: np.ndarray  # (h, w, 4) uint8
    source_path: str | None = None

    @classmethod
    def blank(cls, id: int, name: str, width: int, height: int) -> RasterImage:
        return cls(id, name, np.zeros((height, width, 4), dtype=np.uint8))

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    def copy(self, new_id: int | None = None, name: str | None = None) -> RasterImage:
        return RasterImage(
            new_id if new_id is not None else self.id,
            name if name is not None else self.name,
            self.pixels.copy(),
            self.source_path,
        )


@dataclass(slots=True)
class Placement:
    """Position/scale/rotation of a raster image on the canvas.

    Matches the original bitmapEngine.Bitmap transform: translate to position,
    rotate (degrees) about the image center, scale.
    """

    pos: Vec2 = field(default_factory=Vec2)
    scale: Vec2 = field(default_factory=lambda: Vec2(1.0, 1.0))
    rotation_deg: float = 0.0
    opacity: float = 1.0

    def lerp(self, other: Placement, t: float) -> Placement:
        return Placement(
            self.pos.lerp(other.pos, t),
            self.scale.lerp(other.scale, t),
            self.rotation_deg + (other.rotation_deg - self.rotation_deg) * t,
            self.opacity + (other.opacity - self.opacity) * t,
        )

    def copy(self) -> Placement:
        return Placement(self.pos, self.scale, self.rotation_deg, self.opacity)
