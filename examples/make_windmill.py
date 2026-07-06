"""A complex multi-layer animation built through the programmatic API.

Five layers animated independently over 48 frames:
  1. backdrop  — sky + ground fills (static)
  2. sun       — rays rotating via keyframed point transforms
  3. cloud     — smooth-pen blob drifting with ease-in-out
  4. tower     — static windmill body
  5. blades    — spinning 360° via dense rotation keyframes

Run:  uv run python examples/make_windmill.py
Creates examples/windmill.aep2, windmill.gif and (if ffmpeg) windmill.mp4
"""

import math
from pathlib import Path

from animengine.api import AnimProject

HERE = Path(__file__).parent
W, H, FRAMES = 640, 400, 48


def rotate_layer(p: AnimProject, layer, cx: float, cy: float, *,
                 total_deg: float, steps: int, interp: str = "linear") -> None:
    """Keyframe a full rotation of all the layer's points about (cx, cy)."""
    ids = [pt.id for pt in layer.keyframes[0].shape.points.values()]
    step_deg = total_deg / steps
    for i in range(1, steps + 1):
        frame = round(i * FRAMES / steps)
        p.add_keyframe(layer.id, frame)
        p.transform_points(ids, rotate_deg=step_deg, pivot=(cx, cy),
                           layer_id=layer.id, frame=frame)
        p.set_keyframe_interp(interp, layer.id,
                              round((i - 1) * FRAMES / steps))


def main() -> None:
    p = AnimProject(W, H, fps=24)

    # 1. backdrop ---------------------------------------------------------
    backdrop = p.doc.layers[0]
    p.rename_layer(backdrop.id, "backdrop")
    p.add_rect(2, 2, W - 4, 296, width=2, color="#8888aa")
    p.fill_region(W / 2, 150, "#aee3ff")           # sky
    p.add_rect(2, 298, W - 4, H - 300, width=2, color="#557755")
    p.fill_region(W / 2, 350, "#7ccf6e")           # ground

    # 2. sun with rotating rays ------------------------------------------
    sun = p.add_layer("vector", "sun")
    sx, sy, r = 540, 70, 28
    k = r * 0.5523
    p.add_curve(sx + r, sy, sx + r, sy + k, sx + k, sy + r, sx, sy + r, snap=False)
    p.add_curve(sx, sy + r, sx - k, sy + r, sx - r, sy + k, sx - r, sy, snap=True)
    p.add_curve(sx - r, sy, sx - r, sy - k, sx - k, sy - r, sx, sy - r, snap=True)
    p.add_curve(sx, sy - r, sx + k, sy - r, sx + r, sy - k, sx + r, sy, snap=True)
    p.fill_region(sx, sy, "#ffd23f")
    for i in range(8):
        a = i * math.pi / 4
        p.add_line(sx + math.cos(a) * (r + 8), sy + math.sin(a) * (r + 8),
                   sx + math.cos(a) * (r + 20), sy + math.sin(a) * (r + 20),
                   width=3, color="#ffb703", snap=False)
    rotate_layer(p, sun, sx, sy, total_deg=90, steps=4)

    # 3. drifting cloud ---------------------------------------------------
    cloud = p.add_layer("vector", "cloud")
    blob = [(60, 70), (95, 52), (140, 48), (180, 60), (196, 80),
            (168, 96), (120, 100), (78, 92)]
    p.add_smooth_curve(blob, close=True, width=2, color="#cccccc")
    p.fill_region(120, 75, "#ffffff")
    ids = [pt.id for pt in cloud.keyframes[0].shape.points.values()]
    p.add_keyframe(cloud.id, FRAMES)
    p.transform_points(ids, dx=320, layer_id=cloud.id, frame=FRAMES)
    p.set_keyframe_interp("ease_in_out", cloud.id, 0)

    # 4. windmill tower ---------------------------------------------------
    p.add_layer("vector", "tower")
    p.add_polyline([(285, 300), (300, 170), (340, 170), (355, 300)], close=True,
                   width=3, color="#5b3a29")
    p.fill_region(320, 250, "#b08968")

    # 5. spinning blades --------------------------------------------------
    blades = p.add_layer("vector", "blades")
    bx, by = 320, 165
    for i in range(4):
        a = i * math.pi / 2 + 0.3
        tip_x = bx + math.cos(a) * 85
        tip_y = by + math.sin(a) * 85
        off = (a + math.pi / 2)
        p.add_polyline(
            [(bx, by),
             (tip_x + math.cos(off) * 10, tip_y + math.sin(off) * 10),
             (tip_x - math.cos(off) * 10, tip_y - math.sin(off) * 10)],
            close=True, width=2, color="#333333")
    for i in range(4):
        a = i * math.pi / 2 + 0.3
        mx = bx + math.cos(a) * 55
        my = by + math.sin(a) * 55
        p.fill_region(mx, my, "#eeeeee")
    rotate_layer(p, blades, bx, by, total_deg=360, steps=12)

    p.set_length(FRAMES + 1)
    out = p.save(HERE / "windmill")
    gif = p.export(HERE / "windmill.gif", kind="gif", scale=0.5)
    print(f"saved {out}\nrendered {gif}")
    try:
        mp4 = p.export(HERE / "windmill.mp4", kind="mp4")
        print(f"rendered {mp4}")
    except RuntimeError as exc:
        print(f"mp4 skipped: {exc}")


if __name__ == "__main__":
    main()
