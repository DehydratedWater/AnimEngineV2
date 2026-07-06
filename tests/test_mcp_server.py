"""End-to-end test of the MCP server over real stdio transport."""

import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _drive(tmp_path) -> dict:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "animengine.mcp.server"], env=env
    )
    results: dict = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            results["tools"] = [t.name for t in tools.tools]

            async def call(name, **args):
                res = await session.call_tool(name, args)
                assert not res.isError, f"{name} failed: {res.content}"
                return res

            await call("new_project", width=160, height=120, fps=10)
            await call("add_rect", x=30, y=30, w=60, h=60)
            await call("fill_region", x=60, y=60, color="#ff0000")
            scene = await call("get_scene")
            payload = json.loads(scene.content[0].text)
            results["points"] = len(payload["shape"]["points"])
            results["fills"] = len(payload["shape"]["fills"])

            # animate: copy frame, move all points right
            await call("copy_frame_forward")
            ids = [p["id"] for p in payload["shape"]["points"]]
            await call("transform_points", point_ids=ids, dx=40)
            await call("set_keyframe_interp", frame=0, interp="ease_in_out")

            img = await call("render_frame", frame=0, scale=1.0)
            results["image_mime"] = img.content[0].mimeType
            strip = await call("render_filmstrip", start=0, end=1)
            results["strip_mime"] = strip.content[0].mimeType

            out = await call("render_animation", format="gif",
                             path=str(tmp_path / "preview.gif"))
            results["gif"] = out.content[0].text

            saved = await call("save_project", path=str(tmp_path / "proj"))
            results["saved"] = saved.content[0].text

            und = await call("undo")
            results["undo"] = und.content[0].text
    return results


@pytest.mark.timeout(60)
def test_mcp_end_to_end(tmp_path):
    r = asyncio.run(_drive(tmp_path))
    assert {"new_project", "add_line", "add_curve", "move_point", "connect_points",
            "fill_region", "render_frame", "render_filmstrip", "copy_frame_forward",
            "get_scene", "paint_stroke", "undo", "redo"} <= set(r["tools"])
    assert r["points"] == 4
    assert r["fills"] == 1
    assert r["image_mime"] == "image/png"
    assert r["strip_mime"] == "image/png"
    assert r["gif"].endswith(".gif") and os.path.exists(r["gif"])
    assert r["saved"].endswith(".aep2") and os.path.exists(r["saved"])
    assert "undid" in r["undo"]
