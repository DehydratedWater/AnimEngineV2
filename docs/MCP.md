# AnimEngine MCP server

`animengine-mcp` exposes the whole editor to LLM agents over MCP (stdio):
project/layers/keyframes, drawing (lines, curves, rects, polylines, bucket
fill), point-level editing (move/connect/cut/erase/transform), raster brush
strokes, audio, plus *vision* tools — `render_frame`, `render_filmstrip`
(contact sheet) and `render_animation` (gif/mp4 file) — so a multimodal model
can see what it draws and iterate.

Start command (from the repo):

```sh
uv run animengine-mcp
```

## Claude Code

`.mcp.json` in your workspace:

```json
{
  "mcpServers": {
    "animengine": {
      "command": "uv",
      "args": ["run", "--project", "/home/dw/programing/AnimEngineV2", "animengine-mcp"]
    }
  }
}
```

## opencode + local qwen via vLLM

`opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "vllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "vLLM (local)",
      "options": { "baseURL": "http://localhost:8000/v1" },
      "models": {
        "qwen": { "name": "Qwen (local)" }
      }
    }
  },
  "model": "vllm/qwen",
  "mcp": {
    "animengine": {
      "type": "local",
      "command": ["uv", "run", "--project", "/home/dw/programing/AnimEngineV2", "animengine-mcp"],
      "enabled": true
    }
  }
}
```

Serve the model with vision enabled, e.g.:

```sh
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --port 8000
```

Since the qwen model is multimodal, `render_frame` / `render_filmstrip`
results (PNG images) land directly in its context — ask it e.g.:

> Create a 24-frame bouncing-ball animation: draw a circle with curves, fill
> it red, keyframe its position with ease_in_out, check your work with
> render_filmstrip, then export bounce.gif.

## Typical agent loop

1. `new_project` → `get_summary`
2. draw: `add_line` / `add_curve` / `add_rect` / `add_polyline` / `fill_region`
3. inspect: `get_scene` (ids + coordinates), `render_frame` (pixels)
4. animate: `copy_frame_forward` → `move_point` / `transform_points` → `set_keyframe_interp`
5. review: `render_filmstrip` / `render_animation`
6. `save_project` / `export_file`
