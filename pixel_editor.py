"""Пиксельный редактор прицелов."""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QKeySequence, QPainter, QPen
from PyQt5.QtWidgets import (
    QGridLayout, QSizePolicy,
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QShortcut, QToolButton, QVBoxLayout, QWidget,
)

UNDO_LIMIT = 60
CANVAS_PX = 448


class _Canvas(QWidget):
    """Полотно: рисует сетку и принимает мышь."""
    stroke_started = pyqtSignal()

    def __init__(self, editor: "PixelEditor") -> None:
        super().__init__()
        self._ed = editor
        self._last: Optional[tuple[int, int]] = None
        self.setMouseTracking(False)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    @property
    def cell(self) -> int:
        return max(1, min(self.width(), self.height()) // self._ed.grid)

    def _origin(self) -> tuple[int, int]:
        side = self.cell * self._ed.grid
        return (self.width() - side) // 2, (self.height() - side) // 2

    def _cell_at(self, pos: QPoint) -> Optional[tuple[int, int]]:
        c = self.cell
        ox, oy = self._origin()
        x, y = (pos.x() - ox) // c, (pos.y() - oy) // c
        if pos.x() < ox or pos.y() < oy:
            return None
        n = self._ed.grid
        return (x, y) if 0 <= x < n and 0 <= y < n else None

    def mousePressEvent(self, ev) -> None:
        if ev.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        pt = self._cell_at(ev.pos())
        if pt is None:
            return
        erase = ev.button() == Qt.RightButton
        self._ed.begin_stroke(pt, erase)
        self._last = pt
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        if self._last is None:
            return
        pt = self._cell_at(ev.pos())
        if pt is None or pt == self._last:
            return
        self._ed.continue_stroke(self._last, pt)
        self._last = pt
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        self._last = None

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        n, c = self._ed.grid, self.cell
        side = n * c
        ox, oy = self._origin()
        p.translate(ox, oy)
        # шахматный фон, чтобы видеть прозрачность
        for y in range(n):
            for x in range(n):
                p.fillRect(x * c, y * c, c, c, QColor("#3a3d42" if (x + y) % 2 else "#2e3136"))
        p.drawImage(QRect(0, 0, side, side), self._ed.image)
        p.setPen(QPen(QColor(255, 255, 255, 28)))
        for i in range(n + 1):
            p.drawLine(i * c, 0, i * c, side)
            p.drawLine(0, i * c, side, i * c)
        # центр холста
        p.setPen(QPen(QColor(61, 220, 132, 190), 1, Qt.DashLine))
        p.drawLine(side // 2, 0, side // 2, side)
        p.drawLine(0, side // 2, side, side // 2)
        p.end()


class PixelEditor(QWidget):
    """Редактор. Сигнал crosshair_saved(путь, имя) — PNG сохранён в папку custom."""
    crosshair_saved = pyqtSignal(str, str)

    def __init__(self, custom_dir: Callable[[], str]) -> None:
        super().__init__()
        self._custom_dir = custom_dir
        self.grid = 32
        self.color = QColor("#00FF00")
        self.tool = "pencil"
        self.sym_x = False
        self.sym_y = False
        self.image = self._blank(self.grid)
        self._undo: list[QImage] = []

        root = QHBoxLayout(self)
        self._canvas = _Canvas(self)
        root.addWidget(self._canvas, 1)

        side_w = QWidget()
        side_w.setFixedWidth(200)
        side = QVBoxLayout(side_w)
        side.setContentsMargins(0, 0, 0, 0)
        root.addWidget(side_w, 0)

        row = QHBoxLayout()
        row.addWidget(QLabel("Сетка:"))
        self._grid_combo = QComboBox()
        for n in (16, 32, 64):
            self._grid_combo.addItem(f"{n}×{n}", n)
        self._grid_combo.setCurrentIndex(1)
        self._grid_combo.currentIndexChanged.connect(self._on_grid)
        row.addWidget(self._grid_combo)
        row.addStretch()
        side.addLayout(row)

        side.addWidget(QLabel("Инструмент:"))
        tools = QGridLayout()
        self._tool_group = QButtonGroup(self)
        self._tool_buttons: dict[str, QToolButton] = {}
        for key, text in (("pencil", "Карандаш"), ("eraser", "Ластик"),
                          ("fill", "Заливка"), ("picker", "Пипетка")):
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setMinimumWidth(92)
            b.setChecked(key == "pencil")
            b.clicked.connect(lambda _c=False, k=key: self._set_tool(k))
            self._tool_group.addButton(b)
            self._tool_buttons[key] = b
            n_t = len(self._tool_buttons) - 1
            tools.addWidget(b, n_t // 2, n_t % 2)
        side.addLayout(tools)

        crow = QHBoxLayout()
        crow.addWidget(QLabel("Цвет:"))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(60, 26)
        self._color_btn.clicked.connect(self._pick_color)
        crow.addWidget(self._color_btn)
        crow.addStretch()
        side.addLayout(crow)
        self._refresh_color_btn()

        self._sym_x_cb = QCheckBox("Симметрия по X")
        self._sym_y_cb = QCheckBox("Симметрия по Y")
        self._sym_x_cb.toggled.connect(lambda v: setattr(self, "sym_x", v))
        self._sym_y_cb.toggled.connect(lambda v: setattr(self, "sym_y", v))
        side.addWidget(self._sym_x_cb)
        side.addWidget(self._sym_y_cb)

        self._undo_btn = QPushButton("Отменить (Ctrl+Z)")
        self._undo_btn.clicked.connect(self.undo)
        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self.clear)
        load_btn = QPushButton("Загрузить PNG…")
        load_btn.clicked.connect(self._load_dialog)
        save_btn = QPushButton("Сохранить как прицел")
        save_btn.setObjectName("accent")
        save_btn.clicked.connect(self.save_as_crosshair)
        for b in (self._undo_btn, clear_btn, load_btn, save_btn):
            side.addWidget(b)
        hint = QLabel("ЛКМ — рисовать, ПКМ — стирать. Зелёные пунктиры — центр холста.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        side.addWidget(hint)
        side.addStretch()

        sc = QShortcut(QKeySequence("Ctrl+Z"), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.undo)

    # --- служебное ---

    @staticmethod
    def _blank(n: int) -> QImage:
        img = QImage(n, n, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        return img

    def _refresh_color_btn(self) -> None:
        self._color_btn.setStyleSheet(
            f"background-color: {self.color.name()}; border: 1px solid #777; border-radius: 4px;"
        )

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self.color, self, "Цвет пикселя")
        if c.isValid():
            self.set_color(c)

    def set_color(self, c: QColor) -> None:
        self.color = QColor(c)
        self.color.setAlpha(255)
        self._refresh_color_btn()

    def _set_tool(self, key: str) -> None:
        self.tool = key

    def _push_undo(self) -> None:
        self._undo.append(self.image.copy())
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)

    def undo(self) -> None:
        if self._undo:
            self.image = self._undo.pop()
            if self.image.width() != self.grid:   # на случай смены сетки
                self.grid = self.image.width()
            self._canvas.update()

    def clear(self) -> None:
        self._push_undo()
        self.image.fill(Qt.transparent)
        self._canvas.update()

    def _on_grid(self) -> None:
        n = self._grid_combo.currentData()
        if n == self.grid:
            return
        self._push_undo()
        old = self.image
        self.grid = n
        self.image = self._blank(n)
        # перенос старого рисунка по центру (если влезает)
        p = QPainter(self.image)
        p.drawImage((n - old.width()) // 2, (n - old.height()) // 2, old)
        p.end()
        self._canvas.update()

    # --- рисование ---

    def _mirror_points(self, x: int, y: int) -> set[tuple[int, int]]:
        n = self.grid
        pts = {(x, y)}
        if self.sym_x:
            pts |= {(n - 1 - px, py) for px, py in pts}
        if self.sym_y:
            pts |= {(px, n - 1 - py) for px, py in pts}
        return pts

    def _paint_pixel(self, x: int, y: int, erase: bool) -> None:
        for px, py in self._mirror_points(x, y):
            self.image.setPixelColor(px, py, QColor(0, 0, 0, 0) if erase else self.color)

    def begin_stroke(self, pt: tuple[int, int], erase_override: bool = False) -> None:
        x, y = pt
        tool = "eraser" if erase_override else self.tool
        if tool == "picker":
            c = self.image.pixelColor(x, y)
            if c.alpha() > 0:
                self.set_color(c)
            return
        self._push_undo()
        if tool == "fill":
            self._flood_fill(x, y)
        else:
            self._paint_pixel(x, y, tool == "eraser")

    def continue_stroke(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        if self.tool in ("fill", "picker"):
            return
        erase = self.tool == "eraser"
        # линия Брезенхэма между соседними событиями мыши
        x0, y0 = a
        x1, y1 = b
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self._paint_pixel(x0, y0, erase)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _flood_fill(self, x: int, y: int) -> None:
        target = self.image.pixel(x, y)
        new = self.color.rgba()
        if target == new:
            return
        n = self.grid
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if not (0 <= cx < n and 0 <= cy < n) or self.image.pixel(cx, cy) != target:
                continue
            self.image.setPixel(cx, cy, new)
            stack.extend(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))

    # --- файлы ---

    def load_image(self, path: str) -> bool:
        src = QImage(path)
        if src.isNull():
            return False
        self._push_undo()
        n = self.grid
        if src.width() > n or src.height() > n:
            src = src.scaled(n, n, Qt.KeepAspectRatio, Qt.FastTransformation)
        self.image = self._blank(n)
        p = QPainter(self.image)
        p.drawImage((n - src.width()) // 2, (n - src.height()) // 2, src)
        p.end()
        self._canvas.update()
        return True

    def _load_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить PNG", "", "Картинки (*.png)")
        if path and not self.load_image(path):
            QMessageBox.warning(self, "Редактор", "Не удалось открыть файл.")

    def save_as_crosshair(self) -> Optional[str]:
        """Сохраняет PNG в папку custom и сообщает о новом прицеле."""
        folder = self._custom_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, f"pixel_{stamp}.png")
        i = 1
        while os.path.exists(path):
            path = os.path.join(folder, f"pixel_{stamp}_{i}.png")
            i += 1
        if not self.image.save(path, "PNG"):
            QMessageBox.warning(self, "Редактор", "Не удалось сохранить файл.")
            return None
        self.crosshair_saved.emit(path, "Пиксельный прицел")
        return path
