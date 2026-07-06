"""The Document: settings, layers, assets, audio, undo — the whole project."""

from __future__ import annotations

from dataclasses import dataclass

from .commands import CommandStack, FunctionCommand
from .layers import Layer, LayerKind, RasterLayer, VectorLayer
from .raster import Placement, RasterImage


@dataclass(slots=True)
class AudioClip:
    """An audio file placed on the timeline."""

    id: int
    name: str
    data: bytes  # original file bytes (wav/mp3/ogg/flac), embedded in the project
    format: str  # file extension, e.g. "wav"
    start_frame: int = 0
    gain: float = 1.0
    #: trim inside the source file, in seconds
    offset_sec: float = 0.0
    duration_sec: float | None = None  # None = natural length
    muted: bool = False


class Document:
    """A project: canvas settings + ordered layers (index 0 = bottom) + assets."""

    def __init__(self, width: int = 1280, height: int = 720, fps: float = 30.0):
        self.width = width
        self.height = height
        self.fps = fps
        self.name = "Untitled"
        #: explicit animation length in frames; rendering/playback clamps to this
        self.length = 1
        self.layers: list[Layer] = []
        self.images: dict[int, RasterImage] = {}
        self.audio_clips: list[AudioClip] = []
        self.background = None  # None = white; set a Color for custom
        self.commands = CommandStack()
        self._next_layer = 1
        self._next_image = 1
        self._next_audio = 1

    # ----------------------------------------------------------- layers
    def add_vector_layer(self, name: str | None = None, index: int | None = None) -> VectorLayer:
        layer = VectorLayer(self._next_layer, name or f"Layer {self._next_layer}")
        self._next_layer += 1
        layer.set_keyframe(0)
        self._insert_layer(layer, index)
        return layer

    def add_raster_layer(self, name: str | None = None, image: RasterImage | None = None,
                         index: int | None = None,
                         placement: Placement | None = None) -> RasterLayer:
        layer = RasterLayer(self._next_layer, name or f"Raster {self._next_layer}")
        self._next_layer += 1
        if image is not None:
            if image.id not in self.images:
                self.images[image.id] = image
            layer.set_keyframe(0, image.id, placement or Placement())
        self._insert_layer(layer, index)
        return layer

    def _insert_layer(self, layer: Layer, index: int | None) -> None:
        if index is None:
            self.layers.append(layer)
        else:
            self.layers.insert(index, layer)

    def remove_layer(self, layer_id: int) -> Layer | None:
        for i, layer in enumerate(self.layers):
            if layer.id == layer_id:
                return self.layers.pop(i)
        return None

    def move_layer(self, layer_id: int, new_index: int) -> None:
        layer = self.remove_layer(layer_id)
        if layer is not None:
            new_index = max(0, min(new_index, len(self.layers)))
            self.layers.insert(new_index, layer)

    def layer(self, layer_id: int) -> Layer:
        for lyr in self.layers:
            if lyr.id == layer_id:
                return lyr
        raise KeyError(f"no layer with id {layer_id}")

    def layer_index(self, layer_id: int) -> int:
        for i, lyr in enumerate(self.layers):
            if lyr.id == layer_id:
                return i
        raise KeyError(f"no layer with id {layer_id}")

    # ----------------------------------------------------------- assets
    def new_image(self, name: str, width: int, height: int) -> RasterImage:
        img = RasterImage.blank(self._next_image, name, width, height)
        self._next_image += 1
        self.images[img.id] = img
        return img

    def register_image(self, image: RasterImage) -> RasterImage:
        image.id = self._next_image
        self._next_image += 1
        self.images[image.id] = image
        return image

    def add_audio_clip(self, name: str, data: bytes, format: str,
                       start_frame: int = 0, gain: float = 1.0) -> AudioClip:
        clip = AudioClip(self._next_audio, name, data, format, start_frame, gain)
        self._next_audio += 1
        self.audio_clips.append(clip)
        return clip

    def remove_audio_clip(self, clip_id: int) -> AudioClip | None:
        for i, c in enumerate(self.audio_clips):
            if c.id == clip_id:
                return self.audio_clips.pop(i)
        return None

    # --------------------------------------------------------- timeline
    def clamp_frame(self, frame: int) -> int:
        return max(0, min(frame, self.length - 1))

    def extend_to(self, frame: int) -> None:
        """Grow the animation so *frame* exists."""
        self.length = max(self.length, frame + 1)

    def used_length(self) -> int:
        """Frames actually holding content (last keyframe / audio end)."""
        last = 0
        for layer in self.layers:
            lk = layer.last_key_frame()
            if lk is not None:
                last = max(last, lk)
        for clip in self.audio_clips:
            if clip.duration_sec:
                last = max(last, clip.start_frame + int(clip.duration_sec * self.fps))
        return max(self.length, last + 1)

    def copy_keyframe_forward(self, layer_id: int, from_frame: int, to_frame: int) -> None:
        """The original's `c-->`: duplicate a layer's state onto a new keyframe."""
        layer = self.layer(layer_id)
        if isinstance(layer, VectorLayer):
            shape = layer.shape_at(from_frame)
            if shape is not None:
                layer.set_keyframe(to_frame, shape.clone())
        elif isinstance(layer, RasterLayer):
            state = layer.state_at(from_frame)
            if state is not None:
                layer.set_keyframe(to_frame, state[0], state[1].copy())
        self.extend_to(to_frame)

    # ------------------------------------------------------------ undo
    def run(self, label: str, do, undo) -> object:
        """Push an undoable mutation onto the shared command stack."""
        return self.commands.push(FunctionCommand(label, do, undo))

    # ------------------------------------------------------- inspection
    def summary(self) -> dict:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "length": self.length,
            "layers": [
                {
                    "id": la.id,
                    "name": la.name,
                    "kind": la.kind.value,
                    "visible": la.visible,
                    "locked": la.locked,
                    "opacity": la.opacity,
                    "keyframes": la.key_frames_sorted(),
                }
                for la in self.layers
            ],
            "images": [
                {"id": im.id, "name": im.name, "size": [im.width, im.height]}
                for im in self.images.values()
            ],
            "audio": [
                {
                    "id": c.id,
                    "name": c.name,
                    "start_frame": c.start_frame,
                    "gain": c.gain,
                    "muted": c.muted,
                }
                for c in self.audio_clips
            ],
        }


__all__ = [
    "AudioClip",
    "Document",
    "Layer",
    "LayerKind",
    "RasterLayer",
    "VectorLayer",
]
