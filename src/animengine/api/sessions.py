"""Interactive edit sessions: live mutation during a drag, one undo step on
release. Used by GUI tools; also handy for scripted multi-step edits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from animengine.core import RasterImage, Shape, VectorLayer
from animengine.core.commands import FunctionCommand
from animengine.core.layers import RasterKeyframe, RasterLayer

if TYPE_CHECKING:
    from .project import AnimProject


class ShapeEditSession:
    """Mutate a vector keyframe's shape freely, then commit() or cancel()."""

    def __init__(self, proj: AnimProject, layer: VectorLayer, frame: int):
        self._proj = proj
        self._layer = layer
        self._frame = frame
        self._had_kf = frame in layer.keyframes
        self._before = layer.keyframes[frame].shape.clone() if self._had_kf else None
        self.keyframe = layer.ensure_keyframe(frame)
        self._done = False

    @property
    def shape(self) -> Shape:
        return self.keyframe.shape

    @property
    def before_shape(self) -> Shape | None:
        """The shape as it was when the session started (None if new keyframe)."""
        return self._before

    def commit(self, label: str) -> None:
        if self._done:
            return
        self._done = True
        layer, frame = self._layer, self._frame
        before, had_kf = self._before, self._had_kf
        after = self.keyframe.shape.clone()

        def do() -> None:
            layer.ensure_keyframe(frame).shape = after.clone()

        def undo() -> None:
            if not had_kf:
                layer.keyframes.pop(frame, None)
            elif before is not None:
                layer.keyframes[frame].shape = before.clone()

        self._proj.doc.commands.push(FunctionCommand(label, do, undo))

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        if not self._had_kf:
            self._layer.keyframes.pop(self._frame, None)
        elif self._before is not None:
            self._layer.keyframes[self._frame].shape = self._before


class RasterPaintSession:
    """Live pixel painting with undo on commit."""

    def __init__(self, proj: AnimProject, image: RasterImage):
        self._proj = proj
        self.image = image
        self._before = image.pixels.copy()
        self._done = False

    def commit(self, label: str) -> None:
        if self._done:
            return
        self._done = True
        image, before = self.image, self._before
        after = image.pixels.copy()

        def do() -> None:
            image.pixels = after.copy()

        def undo() -> None:
            image.pixels = before.copy()

        self._proj.doc.commands.push(FunctionCommand(label, do, undo))

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self.image.pixels = self._before


class PlacementEditSession:
    """Live raster placement drag with undo on commit."""

    def __init__(self, proj: AnimProject, layer: RasterLayer, frame: int):
        self._proj = proj
        kf = layer.ensure_keyframe(frame)
        if kf is None:
            raise ValueError("raster layer has no keyframe here")
        self.keyframe: RasterKeyframe = kf
        self._before = kf.placement.copy()
        self._done = False

    def commit(self, label: str) -> None:
        if self._done:
            return
        self._done = True
        kf, before = self.keyframe, self._before
        after = kf.placement.copy()
        self._proj.doc.run(label,
                           lambda: setattr(kf, "placement", after.copy()),
                           lambda: setattr(kf, "placement", before.copy()))

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self.keyframe.placement = self._before
