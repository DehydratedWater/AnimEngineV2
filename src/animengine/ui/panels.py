"""Dock panels: layer manager and tool options."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from animengine.core import Color

from .state import EditorState


class LayersPanel(QWidget):
    """v1's LayerManager, plus everything it was missing: remove, reorder,
    visibility, lock, opacity, rename."""

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["👁", "🔒", "Name", "Type"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setColumnWidth(0, 28)
        self.table.setColumnWidth(1, 28)
        self.table.setColumnWidth(2, 120)
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(self._cell_double_clicked)

        buttons = QHBoxLayout()
        for text, tip, fn in [
            ("+V", "Add vector layer", self._add_vector),
            ("+R", "Add paintable raster layer", self._add_raster),
            ("+Img", "Import image as layer", self._add_image),
            ("🗑", "Remove selected layer", self._remove),
            ("↑", "Move layer up (drawn later)", lambda: self._reorder(+1)),
            ("↓", "Move layer down (drawn earlier)", lambda: self._reorder(-1)),
        ]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(42)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addStretch(1)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        self.opacity.valueChanged.connect(self._set_opacity)
        form = QHBoxLayout()
        form.addWidget(QLabel("Opacity:"))
        form.addWidget(self.opacity)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addLayout(form)
        state.add_listener(self.refresh)
        self.refresh()

    # display top layer first
    def _row_layer(self, row: int):
        layers = self.state.doc.layers
        return layers[len(layers) - 1 - row]

    def refresh(self) -> None:
        doc = self.state.doc
        self.table.blockSignals(True)
        self.table.setRowCount(len(doc.layers))
        for row in range(len(doc.layers)):
            layer = self._row_layer(row)
            eye = QTableWidgetItem("👁" if layer.visible else "–")
            lock = QTableWidgetItem("🔒" if layer.locked else "·")
            name = QTableWidgetItem(layer.name)
            kind = QTableWidgetItem(layer.kind.value)
            for item in (eye, lock, kind):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, eye)
            self.table.setItem(row, 1, lock)
            self.table.setItem(row, 2, name)
            self.table.setItem(row, 3, kind)
            if layer.id == self.state.project.active_layer_id:
                self.table.selectRow(row)
                self.opacity.blockSignals(True)
                self.opacity.setValue(round(layer.opacity * 100))
                self.opacity.blockSignals(False)
        self.table.blockSignals(False)

    def _cell_clicked(self, row: int, col: int) -> None:
        layer = self._row_layer(row)
        p = self.state.project
        if col == 0:
            p.set_layer_props(layer.id, visible=not layer.visible)
        elif col == 1:
            p.set_layer_props(layer.id, locked=not layer.locked)
        p.set_active_layer(layer.id)
        self.state.notify()

    def _cell_double_clicked(self, row: int, col: int) -> None:
        if col != 2:
            return
        layer = self._row_layer(row)
        name, ok = QInputDialog.getText(self, "Rename layer", "Name:", text=layer.name)
        if ok and name:
            self.state.project.rename_layer(layer.id, name)
            self.state.notify()

    def _add_vector(self) -> None:
        self.state.project.add_layer("vector")
        self.state.notify()

    def _add_raster(self) -> None:
        self.state.project.new_raster_layer()
        self.state.notify()

    def _add_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.state.project.import_image(path, x=50, y=50)
            self.state.notify()

    def _remove(self) -> None:
        p = self.state.project
        if len(p.doc.layers) <= 1:
            return
        p.remove_layer(p.active_layer_id)
        self.state.notify()

    def _reorder(self, delta: int) -> None:
        p = self.state.project
        idx = p.doc.layer_index(p.active_layer_id)
        p.move_layer(p.active_layer_id, idx + delta)
        self.state.notify()

    def _set_opacity(self, value: int) -> None:
        p = self.state.project
        p.set_layer_props(p.active_layer_id, opacity=value / 100)
        self.state.notify()


class _ColorButton(QPushButton):
    def __init__(self, get_color, set_color, title: str):
        super().__init__()
        self._get = get_color
        self._set = set_color
        self._title = title
        self.setFixedSize(60, 24)
        self.clicked.connect(self._pick)
        self.refresh()

    def refresh(self) -> None:
        c = self._get()
        self.setStyleSheet(
            f"background-color: rgba({c.r},{c.g},{c.b},{c.a}); border: 1px solid #333;")

    def _pick(self) -> None:
        c = self._get()
        chosen = QColorDialog.getColor(
            QColor(c.r, c.g, c.b, c.a), self, self._title,
            QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if chosen.isValid():
            self._set(Color(chosen.red(), chosen.green(), chosen.blue(), chosen.alpha()))
            self.refresh()


class ToolOptionsPanel(QWidget):
    """v1's ToolAssistant: stroke/fill colors, sizes, snapping — shared by all tools."""

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        form = QFormLayout(self)

        self.stroke_btn = _ColorButton(lambda: state.stroke_color,
                                       self._set_stroke_color, "Stroke color")
        form.addRow("Stroke color", self.stroke_btn)

        self.fill_btn = _ColorButton(lambda: state.fill_color,
                                     self._set_fill_color, "Fill color")
        form.addRow("Fill color", self.fill_btn)

        self.width_box = QDoubleSpinBox()
        self.width_box.setRange(0.1, 100)
        self.width_box.setValue(state.stroke_width)
        self.width_box.valueChanged.connect(lambda v: setattr(state, "stroke_width", v))
        form.addRow("Stroke width", self.width_box)

        self.brush_box = QDoubleSpinBox()
        self.brush_box.setRange(1, 300)
        self.brush_box.setValue(state.brush_width)
        self.brush_box.valueChanged.connect(lambda v: setattr(state, "brush_width", v))
        form.addRow("Brush size", self.brush_box)

        self.eraser_box = QDoubleSpinBox()
        self.eraser_box.setRange(1, 300)
        self.eraser_box.setValue(state.eraser_radius)
        self.eraser_box.valueChanged.connect(lambda v: setattr(state, "eraser_radius", v))
        form.addRow("Eraser radius", self.eraser_box)

        self.snap_box = QCheckBox("Snap to points/lines (Ctrl to bypass)")
        self.snap_box.setChecked(state.snap)
        self.snap_box.toggled.connect(lambda v: setattr(state, "snap", v))
        form.addRow(self.snap_box)

        self.cutout_box = QCheckBox("Cut-out selection (slice strokes at box edge)")
        self.cutout_box.setChecked(state.cut_out_selection)
        self.cutout_box.toggled.connect(lambda v: setattr(state, "cut_out_selection", v))
        form.addRow(self.cutout_box)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #888;")
        form.addRow(self.hint)

        state.add_listener(self._sync)

    def _set_stroke_color(self, c: Color) -> None:
        self.state.stroke_color = c

    def _set_fill_color(self, c: Color) -> None:
        self.state.fill_color = c

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)

    def _sync(self) -> None:
        # picker tool may have changed params
        if abs(self.width_box.value() - self.state.stroke_width) > 1e-9:
            self.width_box.blockSignals(True)
            self.width_box.setValue(self.state.stroke_width)
            self.width_box.blockSignals(False)
        self.stroke_btn.refresh()
        self.fill_btn.refresh()
