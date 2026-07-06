# AnimEngine 2 — development notes

Python reimplementation of the Java AnimEngine (see ~/programing/AnimEngine).

## Commands
- `uv run pytest -q` — full suite (offscreen Qt is forced by tests/conftest.py)
- `uv run ruff check src tests` — lint (fix with `--fix`)
- `uv run animengine` — launch the editor
- `uv run animengine-mcp` — MCP stdio server
- `uv run python examples/make_windmill.py` — regenerate example assets

## Architecture rules
- `core/` must stay Qt-free. Rendering lives in `render/` (QPainter on
  QImage; `ensure_gui_app()` creates a full QApplication, offscreen if no
  display, so widgets and headless rendering share one instance).
- Every mutation goes through `api.AnimProject` (or a `Command`) so undo/redo
  works identically in GUI, API and MCP. Interactive drags use edit sessions
  (`api/sessions.py`): mutate live, single undo step on commit.
- `Shape` keeps a lazily-built, incrementally-maintained spatial grid
  (`Shape.index()`). Every geometry mutator must keep it consistent — add new
  mutations via the existing primitives (add_point/move_point/…) or update
  `_SpatialIndex` hooks. `shape.touch()` bumps `epoch`, which keys the
  canvas QPicture caches; direct attribute writes without touch() leave
  stale pixels.
- `VectorLayer.shape_at()` returns the *live* keyframe shape on exact/held
  frames (no clone!). Never mutate it directly — use `ensure_keyframe()` or a
  session. Interpolated frames return a fresh shape.
- Perf budgets are enforced in `tests/test_perf.py` (200k-point scene);
  don't add O(n) work per mouse event or O(n²) planarization.

## Legacy format
`io/legacy_ae.py` parses the original `.ae` (misspelled keywords LENGHT /
CONNECTIONES / QUENETAB are intentional). Test samples live in the old repo:
`~/programing/AnimEngine/AnimEngine/{null.ae,ttt,dd,ANIMACJA.txt}` — those
tests skip if the directory is missing.
