"""Shared editor state: the open project, tool parameters, selection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from animengine.api import AnimProject
from animengine.core import Color


@dataclass
class ActiveDrag:
    """Marks a subset of a shape as 'in motion' during an interactive drag."""

    shape: Any  # the Shape being mutated live
    conns: set[int] = field(default_factory=set)  # connections that move
    token: object = field(default_factory=object)  # identity for cache keying


class EditorState:
    def __init__(self) -> None:
        self.project = AnimProject()
        # tool parameters (v1's ParameterBox)
        self.stroke_color = Color(0, 0, 0)
        self.stroke_width = 3.0
        self.fill_color = Color(255, 40, 40)
        self.brush_width = 12.0
        self.eraser_radius = 20.0
        self.snap = True
        self.cut_out_selection = False  # v1's default marquee mode (off = plain move)
        # selection (point/connection/fill ids on the active layer's current frame)
        self.selected_points: set[int] = set()
        self.selection_box: tuple[float, float, float, float] | None = None
        # live drag (set by tools): lets the canvas split the active layer
        # into a cached static picture + the few connections being dragged
        self.active_drag: ActiveDrag | None = None
        # view toggles
        self.show_points = True
        self.onion_skin = False
        self.show_grid = False
        self.playing = False
        # listeners
        self._listeners: list[Callable[[], None]] = []
        self.project.doc.commands.on_change.append(self.notify)

    # ------------------------------------------------------------ project
    def replace_project(self, project: AnimProject) -> None:
        self.project = project
        self.clear_selection()
        self.project.doc.commands.on_change.append(self.notify)
        self.notify()

    @property
    def doc(self):
        return self.project.doc

    @property
    def frame(self) -> int:
        return self.project.current_frame

    # ---------------------------------------------------------- selection
    def clear_selection(self) -> None:
        self.selected_points.clear()
        self.selection_box = None

    def recompute_selection_box(self, pad: float = 10.0) -> None:
        layer = self.project.active_layer
        kf = layer.keyframes.get(self.frame) if hasattr(layer, "keyframes") else None
        shape = getattr(kf, "shape", None)
        if shape is None or not self.selected_points:
            self.selection_box = None
            return
        pts = [shape.points[i].pos for i in self.selected_points if i in shape.points]
        if not pts:
            self.selection_box = None
            return
        min_x = min(p.x for p in pts) - pad
        min_y = min(p.y for p in pts) - pad
        max_x = max(p.x for p in pts) + pad
        max_y = max(p.y for p in pts) + pad
        self.selection_box = (min_x, min_y, max_x, max_y)

    # ---------------------------------------------------------- listeners
    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def notify(self) -> None:
        for fn in list(self._listeners):
            fn()
