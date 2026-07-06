"""Build the bouncing-ball example entirely through the programmatic API.

Run:  uv run python examples/make_bounce.py
Creates examples/bounce.aep2 and examples/bounce.gif
"""

from pathlib import Path

from animengine.api import AnimProject

HERE = Path(__file__).parent


def main() -> None:
    p = AnimProject(480, 360, fps=24)
    doc = p.doc

    # ground
    ground = p.add_layer("vector", "ground")
    p.set_active_layer(ground.id)
    p.add_line(20, 320, 460, 320, width=5, color="#333333")

    # ball: circle out of 4 curves, filled
    ball = p.add_layer("vector", "ball")
    p.set_active_layer(ball.id)
    cx, cy, r = 80, 80, 36
    k = r * 0.5523
    p.add_curve(cx + r, cy, cx + r, cy + k, cx + k, cy + r, cx, cy + r, snap=False)
    p.add_curve(cx, cy + r, cx - k, cy + r, cx - r, cy + k, cx - r, cy, snap=True)
    p.add_curve(cx - r, cy, cx - r, cy - k, cx - k, cy - r, cx, cy - r, snap=True)
    p.add_curve(cx, cy - r, cx + k, cy - r, cx + r, cy - k, cx + r, cy, snap=True)
    p.fill_region(cx, cy, "#e63946")

    # keyframes: parabolic-ish bounce using eased tweens
    shape0 = ball.keyframes[0].shape
    ids = list(shape0.points.keys())

    def key(frame: int, dx: float, dy: float, interp: str) -> None:
        """New keyframe moved by (dx, dy) relative to the previous keyframe."""
        p.add_keyframe(ball.id, frame)
        p.set_frame(frame)
        p.transform_points(ids, dx=dx, dy=dy, layer_id=ball.id, frame=frame)
        p.set_keyframe_interp(interp, ball.id, frame)

    p.set_keyframe_interp("ease_in", ball.id, 0)
    key(12, 150, 204, "ease_out")    # falls to the ground (cy 80 -> 284)
    key(24, 100, -204, "ease_in")    # bounces back up, drifting right
    key(36, 100, 204, "hold")        # second landing
    p.set_length(40)

    out = p.save(HERE / "bounce")
    gif = p.export(HERE / "bounce.gif", kind="gif", scale=0.5)
    print(f"saved {out}\nrendered {gif}")


if __name__ == "__main__":
    main()
