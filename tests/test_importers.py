import json

import numpy as np
from PIL import Image

from animengine.core import Vec2
from animengine.io.importers import (
    import_gif,
    import_image_sequence,
    import_lottie,
    import_sprite_sheet,
    import_svg,
)
from animengine.render import render_frame


def test_import_svg(tmp_path):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
      <g transform="translate(10,10)">
        <rect x="0" y="0" width="50" height="30" fill="#ff0000" stroke="black" stroke-width="2"/>
      </g>
      <circle cx="120" cy="40" r="20" fill="rgb(0,255,0)"/>
      <path d="M 10 60 L 60 60 Q 80 90 100 60 C 120 40 140 80 160 60" fill="none" stroke="#0000ff" stroke-width="3"/>
      <polygon points="170,10 190,10 180,30" fill="purple"/>
    </svg>"""
    p = tmp_path / "art.svg"
    p.write_text(svg)
    doc = import_svg(p)
    assert (doc.width, doc.height) == (200, 100)
    shape = doc.layers[0].keyframes[0].shape
    assert len(shape.fills) == 3  # rect, circle, polygon
    img = render_frame(doc, 0)
    assert img.pixelColor(35, 25).red() == 255  # rect fill (translated)
    assert img.pixelColor(120, 40).green() == 255  # circle fill
    assert img.pixelColor(180, 15).red() > 90  # purple polygon


def test_import_lottie_keyframes(tmp_path):
    lottie = {
        "w": 100, "h": 100, "fr": 30, "ip": 0, "op": 30,
        "layers": [
            {
                "ty": 4, "nm": "box", "ip": 0, "op": 30,
                "ks": {
                    "p": {"a": 1, "k": [
                        {"t": 0, "s": [20, 50], "e": [80, 50]},
                        {"t": 30, "s": [80, 50]},
                    ]},
                    "a": {"a": 0, "k": [0, 0]},
                    "s": {"a": 0, "k": [100, 100]},
                    "r": {"a": 0, "k": 0},
                    "o": {"a": 0, "k": 100},
                },
                "shapes": [
                    {"ty": "gr", "it": [
                        {"ty": "rc", "p": {"a": 0, "k": [0, 0]},
                         "s": {"a": 0, "k": [20, 20]}},
                        {"ty": "fl", "c": {"a": 0, "k": [1, 0, 0, 1]},
                         "o": {"a": 0, "k": 100}},
                        {"ty": "tr", "p": {"a": 0, "k": [0, 0]},
                         "a": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [100, 100]},
                         "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100}},
                    ]},
                ],
            }
        ],
    }
    p = tmp_path / "anim.json"
    p.write_text(json.dumps(lottie))
    doc = import_lottie(p)
    assert doc.fps == 30
    layer = doc.layers[0]
    assert set(layer.key_frames_sorted()) >= {0}
    img0 = render_frame(doc, 0)
    assert img0.pixelColor(20, 50).red() == 255  # box at x=20
    img29 = render_frame(doc, 29)
    assert img29.pixelColor(78, 50).red() == 255  # box near x=80
    # midway: interpolation between baked keyframes
    img15 = render_frame(doc, 15)
    assert img15.pixelColor(50, 50).red() == 255


def test_import_gif(tmp_path):
    frames = []
    for col in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]:
        frames.append(Image.new("RGB", (20, 20), col))
    p = tmp_path / "a.gif"
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=100, loop=0)
    doc = import_gif(p)
    assert len(doc.layers) == 1
    layer = doc.layers[0]
    assert len(layer.keyframes) == 3
    assert len(doc.images) == 3
    img = render_frame(doc, 0)
    assert img.pixelColor(10, 10).red() > 200


def test_import_image_sequence(tmp_path):
    paths = []
    for i, col in enumerate([(10, 0, 0), (0, 10, 0)]):
        p = tmp_path / f"f{i}.png"
        Image.new("RGBA", (16, 16), (*col, 255)).save(p)
        paths.append(p)
    doc = import_image_sequence(paths, fps=8)
    assert doc.fps == 8 and doc.length == 2
    assert doc.layers[0].key_frames_sorted() == [0, 1]


def test_import_sprite_sheet(tmp_path):
    sheet = np.zeros((16, 32, 4), np.uint8)
    sheet[:, :16] = [255, 0, 0, 255]
    sheet[:, 16:] = [0, 0, 255, 255]
    p = tmp_path / "sheet.png"
    Image.fromarray(sheet, "RGBA").save(p)
    doc = import_sprite_sheet(p, 16, 16)
    assert doc.length == 2
    assert render_frame(doc, 0).pixelColor(8, 8).red() == 255
    assert render_frame(doc, 1).pixelColor(8, 8).blue() == 255


def test_svg_open_path_has_no_fill(tmp_path):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">
      <path d="M 5 5 L 45 45" stroke="black" fill="none"/></svg>"""
    p = tmp_path / "line.svg"
    p.write_text(svg)
    doc = import_svg(p)
    shape = doc.layers[0].keyframes[0].shape
    assert len(shape.fills) == 0
    assert len(shape.connections) == 1
    assert shape.nearest_connection(Vec2(25, 25), max_dist=2) is not None
