"""AnimEngine 2 — keyframe vector/raster animation editor.

Packages:
    core    — pure-Python scene model, keyframes, interpolation, commands/undo
    render  — headless QPainter frame renderer
    io      — native project format, legacy .ae import, other importers
    audio   — audio tracks and mixing
    api     — high-level programmatic API (headless)
    mcp     — MCP server exposing the API to LLM agents
    ui      — PySide6 desktop application
"""

__version__ = "2.0.0"
