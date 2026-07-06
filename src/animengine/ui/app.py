"""AnimEngine 2 desktop application."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QToolBar,
)

from animengine.api import AnimProject

from .canvas import CanvasView
from .panels import LayersPanel, ToolOptionsPanel
from .state import EditorState
from .timeline import TimelinePanel
from .tools import ALL_TOOLS, SelectTool

AUTOSAVE_MINUTES = 3


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = EditorState()
        self.setWindowTitle("AnimEngine 2")
        self.resize(1500, 950)

        self.canvas = CanvasView(self.state)
        self.setCentralWidget(self.canvas)

        self.timeline = TimelinePanel(self.state)
        dock_tl = QDockWidget("Timeline", self)
        dock_tl.setWidget(self.timeline)
        dock_tl.setObjectName("timeline")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock_tl)

        self.layers_panel = LayersPanel(self.state)
        dock_layers = QDockWidget("Layers", self)
        dock_layers.setWidget(self.layers_panel)
        dock_layers.setObjectName("layers")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_layers)

        self.options_panel = ToolOptionsPanel(self.state)
        dock_opts = QDockWidget("Tool options", self)
        dock_opts.setWidget(self.options_panel)
        dock_opts.setObjectName("options")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_opts)

        self.tools = {}
        self._build_toolbar()
        self._build_menus()
        self._select_tool("select")

        self.state.add_listener(self._sync_title)
        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self._do_autosave)
        self._autosave.start(AUTOSAVE_MINUTES * 60 * 1000)

        self.statusBar().showMessage("Ready")
        QTimer.singleShot(0, self.canvas.fit_view)

    # ------------------------------------------------------------ toolbar
    def _build_toolbar(self) -> None:
        bar = QToolBar("Tools", self)
        bar.setObjectName("tools")
        bar.setOrientation(Qt.Orientation.Vertical)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, bar)
        group = QActionGroup(self)
        group.setExclusive(True)
        for tool_cls in ALL_TOOLS:
            tool = tool_cls(self.state)
            self.tools[tool.name] = tool
            action = QAction(tool.label, self)
            action.setCheckable(True)
            if tool.shortcut:
                action.setShortcut(tool.shortcut)
                action.setToolTip(f"{tool.label} ({tool.shortcut})\n{tool.status_hint}")
            action.setData(tool.name)
            action.triggered.connect(
                lambda checked, name=tool.name: self._select_tool(name))
            group.addAction(action)
            bar.addAction(action)
        self._tool_actions = group.actions()

    def _select_tool(self, name: str) -> None:
        if self.canvas.tool is not None:
            self.canvas.tool.deactivate()
        tool = self.tools[name]
        self.canvas.tool = tool
        tool.activate()
        for action in self._tool_actions:
            action.setChecked(action.data() == name)
        self.options_panel.set_hint(tool.status_hint)
        self.statusBar().showMessage(f"{tool.label}: {tool.status_hint}")
        self.canvas.update()

    # -------------------------------------------------------------- menus
    def _build_menus(self) -> None:
        menu = self.menuBar()

        # File
        file_menu = menu.addMenu("&File")
        self._act(file_menu, "New project…", "Ctrl+N", self._new_project)
        self._act(file_menu, "Open…", "Ctrl+O", self._open)
        file_menu.addSeparator()
        self._act(file_menu, "Save", "Ctrl+S", self._save)
        self._act(file_menu, "Save as…", "Ctrl+Shift+S", self._save_as)
        file_menu.addSeparator()
        import_menu = file_menu.addMenu("Import")
        self._act(import_menu, "Legacy AnimEngine (.ae)…", None,
                  lambda: self._open_filtered("AnimEngine 1 (*.ae *.txt *)"))
        self._act(import_menu, "SVG…", None,
                  lambda: self._open_filtered("SVG (*.svg)"))
        self._act(import_menu, "Lottie JSON…", None,
                  lambda: self._open_filtered("Lottie (*.json)"))
        self._act(import_menu, "GIF…", None,
                  lambda: self._open_filtered("GIF (*.gif)"))
        self._act(import_menu, "Audio…", None, self._import_audio)
        export_menu = file_menu.addMenu("Export")
        for label, kind in [("PNG (current frame)…", "png"),
                            ("PNG sequence…", "sequence"), ("GIF…", "gif"),
                            ("MP4 video…", "mp4"), ("WebM video…", "webm"),
                            ("SVG (current frame)…", "svg"),
                            ("Sprite sheet…", "spritesheet")]:
            self._act(export_menu, label, None,
                      lambda checked=False, k=kind: self._export(k))
        file_menu.addSeparator()
        self._act(file_menu, "Quit", "Ctrl+Q", self.close)

        # Edit
        edit_menu = menu.addMenu("&Edit")
        self.undo_action = self._act(edit_menu, "Undo", QKeySequence.StandardKey.Undo,
                                     self._undo)
        self.redo_action = self._act(edit_menu, "Redo", QKeySequence.StandardKey.Redo,
                                     self._redo)
        edit_menu.addSeparator()
        self._act(edit_menu, "Delete selection", "Del", self._delete_selection)
        self._act(edit_menu, "Select none", "Ctrl+Shift+A", self._select_none)

        # View
        view_menu = menu.addMenu("&View")
        self._act(view_menu, "Fit view", "0", self.canvas.fit_view)
        self._act(view_menu, "Zoom in", "+",
                  lambda: self._zoom(1.25))
        self._act(view_menu, "Zoom out", "-",
                  lambda: self._zoom(0.8))
        view_menu.addSeparator()
        self._toggle(view_menu, "Show points", "F2", "show_points", True)
        self._toggle(view_menu, "Onion skin", "F3", "onion_skin", False)
        self._toggle(view_menu, "Grid", "F4", "show_grid", False)

        # Timeline
        tl_menu = menu.addMenu("&Timeline")
        self._act(tl_menu, "Play / Pause", "Space", self.timeline.toggle_play)
        self._act(tl_menu, "Previous frame", "Left", self.timeline._prev)
        self._act(tl_menu, "Next frame", "Right", self.timeline._next)
        self._act(tl_menu, "Copy frame forward (c→)", "F6", self.timeline._copy_forward)
        self._act(tl_menu, "Add keyframe", "F5",
                  lambda: (self.state.project.add_keyframe(), self.state.notify()))
        self._act(tl_menu, "Set animation length…", None, self._set_length)
        self._act(tl_menu, "Set canvas size…", None, self._set_size)

        menu.addMenu("&Help").addAction(
            "About", lambda: QMessageBox.about(
                self, "AnimEngine 2",
                "AnimEngine 2 — a modern reimplementation of AnimEngine BETA 1.3.\n"
                "Vector + raster keyframe animation with tweening, audio, "
                "importers/exporters, and an MCP server for LLM control."))

        self.state.add_listener(self._sync_undo_labels)

    def _act(self, menu, label, shortcut, fn) -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(fn)
        menu.addAction(action)
        return action

    def _toggle(self, menu, label, shortcut, attr, default) -> None:
        action = QAction(label, self)
        action.setCheckable(True)
        action.setChecked(default)
        if shortcut:
            action.setShortcut(shortcut)
        action.toggled.connect(
            lambda v: (setattr(self.state, attr, v), self.canvas.update()))
        menu.addAction(action)

    # ------------------------------------------------------------ actions
    def _zoom(self, factor: float) -> None:
        self.canvas.zoom = max(self.canvas.MIN_ZOOM,
                               min(self.canvas.zoom * factor, self.canvas.MAX_ZOOM))
        self.canvas.update()

    def _undo(self) -> None:
        label = self.state.project.undo()
        self.statusBar().showMessage(f"Undid: {label}" if label else "Nothing to undo")

    def _redo(self) -> None:
        label = self.state.project.redo()
        self.statusBar().showMessage(f"Redid: {label}" if label else "Nothing to redo")

    def _sync_undo_labels(self) -> None:
        cmds = self.state.doc.commands
        self.undo_action.setText(f"Undo {cmds.undo_label}" if cmds.undo_label else "Undo")
        self.redo_action.setText(f"Redo {cmds.redo_label}" if cmds.redo_label else "Redo")
        self.undo_action.setEnabled(cmds.can_undo)
        self.redo_action.setEnabled(cmds.can_redo)

    def _delete_selection(self) -> None:
        tool = self.tools.get("select")
        if isinstance(tool, SelectTool):
            tool.delete_selection()

    def _select_none(self) -> None:
        self.state.clear_selection()
        self.state.notify()

    def _new_project(self) -> None:
        w, ok = QInputDialog.getInt(self, "New project", "Width:", 1280, 16, 8192)
        if not ok:
            return
        h, ok = QInputDialog.getInt(self, "New project", "Height:", 720, 16, 8192)
        if not ok:
            return
        fps, ok = QInputDialog.getDouble(self, "New project", "FPS:", 30.0, 1, 360, 1)
        if not ok:
            return
        self.state.replace_project(AnimProject(w, h, fps))
        self.canvas.fit_view()

    def _open(self) -> None:
        self._open_filtered(
            "All supported (*.aep2 *.ae *.svg *.json *.gif *.txt);;"
            "AnimEngine 2 (*.aep2);;AnimEngine 1 (*.ae *.txt);;SVG (*.svg);;"
            "Lottie (*.json);;GIF (*.gif)")

    def _open_filtered(self, filter_str: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", filter_str)
        if not path:
            return
        try:
            self.state.replace_project(AnimProject.open(path))
            self.canvas.fit_view()
            self.statusBar().showMessage(f"Opened {path}")
        except Exception as exc:  # noqa: BLE001 - surface to the user
            QMessageBox.critical(self, "Open failed", str(exc))

    def _save(self) -> None:
        if self.state.project.path is None:
            self._save_as()
        else:
            self.state.project.save()
            self.statusBar().showMessage(f"Saved {self.state.project.path}")

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "",
                                              "AnimEngine 2 (*.aep2)")
        if path:
            saved = self.state.project.save(path)
            self.statusBar().showMessage(f"Saved {saved}")
            self._sync_title()

    def _import_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import audio", "",
            "Audio (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.opus)")
        if not path:
            return
        clip = self.state.project.add_audio(path, start_frame=self.state.frame)
        self.state.notify()
        self.statusBar().showMessage(
            f"Added audio {clip.name} ({clip.duration_sec or 0:.1f}s)")

    def _export(self, kind: str) -> None:
        p = self.state.project
        if kind == "sequence":
            path = QFileDialog.getExistingDirectory(self, "Export PNG sequence to…")
        else:
            ext = {"png": "png", "gif": "gif", "mp4": "mp4", "webm": "webm",
                   "svg": "svg", "spritesheet": "png"}[kind]
            path, _ = QFileDialog.getSaveFileName(self, "Export", "",
                                                  f"{kind} (*.{ext})")
        if not path:
            return
        try:
            out = p.export(path, kind=kind)
            self.statusBar().showMessage(f"Exported {out}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export failed", str(exc))

    def _set_length(self) -> None:
        n, ok = QInputDialog.getInt(self, "Animation length", "Frames:",
                                    self.state.doc.length, 1, 100000)
        if ok:
            self.state.project.set_length(n)
            self.state.notify()

    def _set_size(self) -> None:
        doc = self.state.doc
        w, ok = QInputDialog.getInt(self, "Canvas size", "Width:", doc.width, 16, 8192)
        if not ok:
            return
        h, ok = QInputDialog.getInt(self, "Canvas size", "Height:", doc.height, 16, 8192)
        if not ok:
            return
        doc.width, doc.height = w, h
        self.canvas.fit_view()
        self.state.notify()

    def _sync_title(self) -> None:
        name = self.state.project.path.name if self.state.project.path else "Untitled"
        self.setWindowTitle(f"AnimEngine 2 — {name}")

    def _do_autosave(self) -> None:
        p = self.state.project
        if p.doc.commands.depth == 0:
            return
        autosave_dir = Path.home() / ".animengine" / "autosave"
        autosave_dir.mkdir(parents=True, exist_ok=True)
        name = p.path.stem if p.path else "untitled"
        try:
            from animengine.io import save_project
            save_project(p.doc, autosave_dir / f"{name}-autosave")
            self.statusBar().showMessage("Autosaved", 2000)
        except Exception:  # noqa: BLE001 - autosave must never crash the app
            pass


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("AnimEngine 2")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
