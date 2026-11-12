"""Окно настроек: профили, генератор, положение, библиотека, редактор, клавиши, настройки."""
from __future__ import annotations

import glob
import os
import shutil
from typing import Callable, Optional

from PyQt5.QtCore import QPointF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QPolygonF
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout,
    QWidget,
)

import presets
import storage
from crosshair_model import (
    GEN_LIMITS, OFFSET_LIMITS, Profile, SIZE_LIMITS, decode_share_code,
    encode_share_code, render_profile,
)
from overlay import list_monitors
from pixel_editor import PixelEditor
from storage import AppConfig
from ui_widgets import (
    DARK_QSS, ColorPicker, HotkeyEdit, LabeledSlider, PreviewWidget,
)

AUTOSAVE_MS = 300


def make_thumb(img: QImage, px: int, bg: str = "#2b2b2b") -> QPixmap:
    """Квадратная иконка с прицелом по центру."""
    pm = QPixmap(px, px)
    pm.fill(QColor(bg))
    if img.isNull():
        return pm
    w, h = img.width(), img.height()
    p = QPainter(pm)
    p.setRenderHint(QPainter.SmoothPixmapTransform, w > px - 4 or h > px - 4)
    inner = px - 4
    if w > inner or h > inner:
        img = img.scaled(inner, inner, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        w, h = img.width(), img.height()
    else:
        k = max(1, min(3, inner // max(w, h)))
        if k > 1:
            img = img.scaled(w * k, h * k, Qt.KeepAspectRatio, Qt.FastTransformation)
            w, h = img.width(), img.height()
    p.drawImage((px - w) // 2, (px - h) // 2, img)
    p.end()
    return pm


def arrow_icon(direction: str, px: int = 24) -> QIcon:
    """Стрелка, нарисованная через QPainter (не зависит от шрифта)."""
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#e4e6ea"))
    m, c = 1, px / 2
    pts = {
        "left": [(m, c), (px - m, m), (px - m, px - m)],
        "right": [(px - m, c), (m, m), (m, px - m)],
        "up": [(c, m), (m, px - m), (px - m, px - m)],
        "down": [(c, px - m), (m, m), (px - m, m)],
    }[direction]
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    p.end()
    return QIcon(pm)


class ControlPanel(QWidget):
    # image, offset_x, offset_y, monitor_index
    overlay_update = pyqtSignal(object, int, int, int)
    visibility_changed = pyqtSignal(bool)
    hide_on_rmb_changed = pyqtSignal(bool)
    hotkeys_changed = pyqtSignal()
    profiles_changed = pyqtSignal()

    def __init__(self, cfg: AppConfig,
                 save_fn: Callable[[AppConfig], None] = storage.save_config,
                 custom_dir_fn: Callable[[], str] = storage.custom_dir) -> None:
        super().__init__()
        self.cfg = cfg
        self._save_fn = save_fn
        self._custom_dir = custom_dir_fn
        self._loading = False
        self._lib_selected: Optional[Profile] = None

        self.setWindowTitle("Crosshair Overlay")
        self.setStyleSheet(DARK_QSS)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setMinimumSize(900, 700)
        self.resize(1000, 780)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_MS)
        self._save_timer.timeout.connect(self.flush_save)

        self._build_ui()
        self._refill_list()
        self._load_controls()
        self._update_toggle_ui()

        if cfg.window_x is not None and cfg.window_y is not None:
            self._restore_position(cfg.window_x, cfg.window_y)

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(12)
        outer.addLayout(top, 1)

        # --- слева: список профилей ---
        left = QVBoxLayout()
        title = QLabel("Прицелы")
        title.setObjectName("title")
        left.addWidget(title)
        self._list = QListWidget()
        self._list.setIconSize(QSize(36, 36))
        self._list.setFixedWidth(230)
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list, 1)
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (text, tip, slot) in enumerate([
            ("Добавить", "Новый прицел", self.add_profile),
            ("Дублировать", "Копия выбранного", self.duplicate_profile),
            ("Переименовать", "Изменить название", self._rename_dialog),
            ("Удалить", "Удалить выбранный", self.delete_profile),
            ("Вверх", "Поднять в списке", lambda: self.move_profile(-1)),
            ("Вниз", "Опустить в списке", lambda: self.move_profile(1)),
        ]):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, s=slot: s())
            grid.addWidget(b, i // 2, i % 2)
        left.addLayout(grid)
        top.addLayout(left)

        # --- справа: предпросмотр + вкладки ---
        right = QVBoxLayout()
        prev_row = QHBoxLayout()
        prev_row.addWidget(QLabel("Предпросмотр:"))
        prev_row.addStretch()
        self._bg_dark = QToolButton()
        self._bg_dark.setText("Тёмный фон")
        self._bg_dark.setCheckable(True)
        self._bg_dark.setChecked(True)
        self._bg_light = QToolButton()
        self._bg_light.setText("Светлый фон")
        self._bg_light.setCheckable(True)
        self._bg_dark.clicked.connect(lambda: self._set_bg(True))
        self._bg_light.clicked.connect(lambda: self._set_bg(False))
        prev_row.addWidget(self._bg_dark)
        prev_row.addWidget(self._bg_light)
        right.addLayout(prev_row)
        self._preview = PreviewWidget()
        self._preview.setFixedHeight(150)
        right.addWidget(self._preview)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_generator_tab(), "Генератор")
        self._tabs.addTab(self._build_position_tab(), "Положение")
        self._tabs.addTab(self._build_library_tab(), "Библиотека")
        self._tabs.addTab(self._build_editor_tab(), "Редактор")
        self._tabs.addTab(self._build_hotkeys_tab(), "Клавиши")
        self._tabs.addTab(self._build_settings_tab(), "Настройки")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        right.addWidget(self._tabs, 1)
        top.addLayout(right, 1)

        # --- низ ---
        bottom = QHBoxLayout()
        self._toggle_btn = QPushButton()
        self._toggle_btn.setObjectName("accent")
        self._toggle_btn.setMinimumHeight(34)
        self._toggle_btn.clicked.connect(self.toggle_overlay)
        self._status = QLabel()
        self._status.setObjectName("hint")
        bottom.addWidget(self._toggle_btn, 1)
        bottom.addWidget(self._status, 1)
        outer.addLayout(bottom)

    def _scroll(self, inner: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.viewport().setAutoFillBackground(True)
        sa.viewport().setStyleSheet("background-color: #1e2024;")
        inner.setObjectName("scrollInner")
        inner.setStyleSheet("#scrollInner { background-color: #1e2024; }")
        sa.setWidget(inner)
        return sa

    # --- Генератор ---
    def _build_generator_tab(self) -> QWidget:
        self._gen_stack = QStackedWidget()
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(8)
        self._gw: dict[str, QWidget] = {}

        def slider(attr: str, text: str, suffix: str = " px") -> None:
            lo, hi = GEN_LIMITS[attr]
            w = LabeledSlider(text, lo, hi, lo, suffix)
            w.valueChanged.connect(lambda v, a=attr: self._set_gen(a, v))
            self._gw[attr] = w
            lay.addWidget(w)

        def check(attr: str, text: str) -> QCheckBox:
            c = QCheckBox(text)
            c.toggled.connect(lambda v, a=attr: self._set_gen(a, v))
            self._gw[attr] = c
            return c

        lay.addWidget(QLabel("Цвет:"))
        cp = ColorPicker()
        cp.colorChanged.connect(lambda v: self._set_gen("color", v))
        self._gw["color"] = cp
        lay.addWidget(cp)
        slider("opacity", "Непрозрачность", " %")
        slider("line_length", "Длина линии")
        slider("line_thickness", "Толщина линии")
        slider("gap", "Зазор в центре")

        arms = QHBoxLayout()
        arms.addWidget(QLabel("Лучи:"))
        for attr, text in (("top", "Сверху"), ("bottom", "Снизу"),
                           ("left", "Слева"), ("right", "Справа")):
            arms.addWidget(check(attr, text))
        arms.addStretch()
        lay.addLayout(arms)

        lay.addWidget(check("center_dot", "Центральная точка"))
        slider("dot_size", "Размер точки")
        lay.addWidget(check("circle", "Круг"))
        slider("circle_radius", "Радиус круга")
        slider("circle_thickness", "Толщина круга")
        lay.addWidget(check("outline", "Обводка"))
        oc = ColorPicker("#000000")
        oc.colorChanged.connect(lambda v: self._set_gen("outline_color", v))
        self._gw["outline_color"] = oc
        lay.addWidget(oc)
        slider("outline_thickness", "Толщина обводки")
        lay.addStretch()
        self._gen_stack.addWidget(self._scroll(inner))

        hint = QWidget()
        hl = QVBoxLayout(hint)
        hl.addStretch()
        lbl = QLabel("Это прицел-картинка")
        lbl.setObjectName("title")
        lbl.setAlignment(Qt.AlignCenter)
        sub = QLabel("У картинки нет параметров генератора. Можно превратить её\n"
                     "в генерируемый прицел и настраивать линии, круг и обводку.")
        sub.setObjectName("hint")
        sub.setAlignment(Qt.AlignCenter)
        btn = QPushButton("Превратить в генерируемый")
        btn.clicked.connect(self.convert_to_generated)
        hl.addWidget(lbl)
        hl.addWidget(sub)
        hl.addWidget(btn, 0, Qt.AlignCenter)
        hl.addStretch()
        self._gen_stack.addWidget(hint)
        return self._gen_stack

    # --- Положение ---
    def _build_position_tab(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)

        lay.addWidget(QLabel("Смещение от центра экрана (пиксели):"))
        row = QHBoxLayout()
        self._ox = QSpinBox()
        self._oy = QSpinBox()
        for s in (self._ox, self._oy):
            s.setRange(*OFFSET_LIMITS)
            s.setFixedWidth(80)
        self._ox.valueChanged.connect(lambda v: self._set_prof("offset_x", v))
        self._oy.valueChanged.connect(lambda v: self._set_prof("offset_y", v))
        row.addWidget(QLabel("X:"))
        row.addWidget(self._ox)
        row.addWidget(QLabel("Y:"))
        row.addWidget(self._oy)
        row.addSpacing(12)
        for name, dx, dy, tip in (
                ("left", -1, 0, "Сдвиг на 1 px влево"), ("right", 1, 0, "Сдвиг на 1 px вправо"),
                ("up", 0, -1, "Сдвиг на 1 px вверх"), ("down", 0, 1, "Сдвиг на 1 px вниз")):
            b = QToolButton()
            b.setIcon(arrow_icon(name))
            b.setIconSize(QSize(24, 24))
            b.setToolTip(tip)
            b.setFixedSize(34, 30)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _c=False, a=dx, c=dy: self.nudge(a, c))
            row.addWidget(b)
        center = QPushButton("По центру")
        center.clicked.connect(lambda: self.set_offset(0, 0))
        row.addWidget(center)
        row.addStretch()
        lay.addLayout(row)

        self._scale = LabeledSlider("Масштаб", 25, 400, 100, " %")
        self._scale.valueChanged.connect(lambda v: self._set_prof("scale", v / 100.0))
        self._rotation = LabeledSlider("Поворот", -180, 180, 0, " °")
        self._rotation.valueChanged.connect(lambda v: self._set_prof("rotation", v))
        self._opacity = LabeledSlider("Общая прозрачность", 0, 100, 100, " %")
        self._opacity.valueChanged.connect(lambda v: self._set_prof("opacity", v))
        for w in (self._scale, self._rotation, self._opacity):
            lay.addWidget(w)

        self._image_box = QWidget()
        il = QVBoxLayout(self._image_box)
        il.setContentsMargins(0, 0, 0, 0)
        self._img_size = LabeledSlider("Размер картинки", SIZE_LIMITS[0], SIZE_LIMITS[1], 64, " px")
        self._img_size.valueChanged.connect(lambda v: self._set_prof("size", v))
        self._tint = ColorPicker("#FFFFFF")
        self._tint.colorChanged.connect(lambda v: self._set_prof("tint", v))
        il.addWidget(self._img_size)
        il.addWidget(QLabel("Тон картинки (белый — без изменений):"))
        il.addWidget(self._tint)
        lay.addWidget(self._image_box)
        lay.addStretch()
        return self._scroll(inner)

    # --- Библиотека ---
    def _build_library_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel("Нажмите на плитку, чтобы применить прицел к выбранному профилю.")
        info.setObjectName("hint")
        lay.addWidget(info)
        self._lib = QListWidget()
        self._lib.setViewMode(QListWidget.IconMode)
        self._lib.setIconSize(QSize(64, 64))
        self._lib.setGridSize(QSize(104, 100))
        self._lib.setResizeMode(QListWidget.Adjust)
        self._lib.setMovement(QListWidget.Static)
        self._lib.setWordWrap(True)
        self._lib.setUniformItemSizes(True)
        self._lib.itemClicked.connect(self._on_lib_click)
        lay.addWidget(self._lib, 1)
        row = QHBoxLayout()
        self._lib_add = QPushButton("Добавить как новый профиль")
        self._lib_add.setEnabled(False)
        self._lib_add.clicked.connect(self.add_library_selection)
        imp = QPushButton("Импорт PNG…")
        imp.clicked.connect(self._import_dialog)
        row.addWidget(self._lib_add)
        row.addWidget(imp)
        row.addStretch()
        lay.addLayout(row)
        self._lib_entries: list[Profile] = []
        self._rebuild_library()
        return w

    def _library_entries(self) -> list[Profile]:
        entries = presets.builtin_presets() + presets.legacy_image_presets()
        for f in sorted(glob.glob(os.path.join(self._custom_dir(), "*.png"))):
            img = QImage(f)
            size = max(SIZE_LIMITS[0], min(SIZE_LIMITS[1], max(img.width(), img.height()) or 64))
            entries.append(Profile(
                name=os.path.splitext(os.path.basename(f))[0], kind="image",
                image_path=f, size=size,
            ))
        return entries

    def _rebuild_library(self) -> None:
        self._lib.clear()
        self._lib_entries = self._library_entries()
        for e in self._lib_entries:
            it = QListWidgetItem(QIcon(make_thumb(render_profile(e), 64)), e.name)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            it.setToolTip(e.name)
            self._lib.addItem(it)

    # --- Редактор ---
    def _build_editor_tab(self) -> QWidget:
        self._editor = PixelEditor(self._custom_dir)
        self._editor.crosshair_saved.connect(self._on_editor_saved)
        return self._editor

    # --- Клавиши ---
    def _build_hotkeys_tab(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)
        self._hk_edits: dict[str, HotkeyEdit] = {}
        for key, text in (("toggle", "Скрыть / показать прицел:"),
                          ("next", "Следующий прицел:"),
                          ("prev", "Предыдущий прицел:")):
            lay.addWidget(QLabel(text))
            e = HotkeyEdit(self.cfg.hotkeys.get(key, ""))
            e.changed.connect(lambda v, k=key: self._set_global_hotkey(k, v))
            self._hk_edits[key] = e
            lay.addWidget(e)
        self._hk_profile_label = QLabel()
        lay.addWidget(self._hk_profile_label)
        self._hk_profile = HotkeyEdit()
        self._hk_profile.changed.connect(self._set_profile_hotkey)
        lay.addWidget(self._hk_profile)
        self._rmb = QCheckBox("Скрывать прицел при зажатой правой кнопке мыши")
        self._rmb.setChecked(self.cfg.hide_on_rmb)
        self._rmb.toggled.connect(self._on_rmb)
        lay.addWidget(self._rmb)
        self._hk_errors = QLabel()
        self._hk_errors.setWordWrap(True)
        self._hk_errors.setStyleSheet("color: #ff7a7a;")
        lay.addWidget(self._hk_errors)
        lay.addStretch()
        return self._scroll(inner)

    # --- Настройки ---
    def _build_settings_tab(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Монитор для прицела:"))
        self._monitor_combo = QComboBox()
        try:
            mons = list_monitors()
        except Exception:
            mons = []
        for m in mons:
            self._monitor_combo.addItem(m.label, m.index)
        if self.cfg.monitor_index < self._monitor_combo.count():
            self._monitor_combo.setCurrentIndex(self.cfg.monitor_index)
        self._monitor_combo.currentIndexChanged.connect(self._on_monitor)
        lay.addWidget(self._monitor_combo)

        lay.addWidget(QLabel("Обмен прицелами:"))
        row = QHBoxLayout()
        cp = QPushButton("Копировать код прицела")
        cp.clicked.connect(self.copy_share_code)
        ps = QPushButton("Вставить код прицела")
        ps.clicked.connect(self.paste_share_code)
        row.addWidget(cp)
        row.addWidget(ps)
        row.addStretch()
        lay.addLayout(row)
        op = QPushButton("Открыть папку пользовательских прицелов")
        op.clicked.connect(self._open_custom_folder)
        lay.addWidget(op, 0, Qt.AlignLeft)
        lay.addStretch()
        return self._scroll(inner)

    # ------------------------------------------------------------------
    # Список профилей
    # ------------------------------------------------------------------

    def _icon_for(self, p: Profile) -> QIcon:
        return QIcon(make_thumb(render_profile(p), 36))

    def _item_text(self, p: Profile) -> str:
        return p.name + (f"   [{p.hotkey}]" if p.hotkey else "")

    def _refill_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for p in self.cfg.profiles:
            self._list.addItem(QListWidgetItem(self._icon_for(p), self._item_text(p)))
        self._list.setCurrentRow(self.cfg.active)
        self._list.blockSignals(False)

    def _update_current_item(self) -> None:
        it = self._list.item(self.cfg.active)
        if it is not None:
            p = self.cfg.current
            it.setIcon(self._icon_for(p))
            it.setText(self._item_text(p))

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.cfg.profiles) or row == self.cfg.active:
            return
        self.cfg.active = row
        self._after_selection()

    def _after_selection(self) -> None:
        self._load_controls()
        self._emit_overlay()
        self._schedule_save()
        self.profiles_changed.emit()

    def _structure_changed(self) -> None:
        """Изменился состав/порядок профилей."""
        self._refill_list()
        self._load_controls()
        self._emit_overlay()
        self._schedule_save()
        self.hotkeys_changed.emit()
        self.profiles_changed.emit()

    def add_profile(self) -> None:
        self.cfg.profiles.append(presets.default_profile())
        self.cfg.active = len(self.cfg.profiles) - 1
        self._structure_changed()

    def duplicate_profile(self) -> None:
        p = self.cfg.current.copy()
        p.name += " (копия)"
        p.hotkey = ""
        self.cfg.profiles.insert(self.cfg.active + 1, p)
        self.cfg.active += 1
        self._structure_changed()

    def rename_profile(self, idx: int, name: str) -> None:
        name = name.strip()
        if name and 0 <= idx < len(self.cfg.profiles):
            self.cfg.profiles[idx].name = name
            self._update_current_item() if idx == self.cfg.active else self._refill_list()
            self._schedule_save()
            self.profiles_changed.emit()

    def _rename_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "Переименовать", "Название прицела:",
                                        text=self.cfg.current.name)
        if ok:
            self.rename_profile(self.cfg.active, name)

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Подтверждение", text) == QMessageBox.Yes

    def delete_profile(self) -> None:
        if len(self.cfg.profiles) <= 1:
            self._status.setText("Нельзя удалить последний прицел.")
            return
        if not self._confirm(f"Удалить прицел «{self.cfg.current.name}»?"):
            return
        del self.cfg.profiles[self.cfg.active]
        self.cfg.active = max(0, min(self.cfg.active, len(self.cfg.profiles) - 1))
        self._structure_changed()

    def move_profile(self, delta: int) -> None:
        i, j = self.cfg.active, self.cfg.active + delta
        if 0 <= j < len(self.cfg.profiles):
            ps = self.cfg.profiles
            ps[i], ps[j] = ps[j], ps[i]
            self.cfg.active = j
            self._structure_changed()

    def select_profile(self, idx: int) -> None:
        if 0 <= idx < len(self.cfg.profiles):
            self._list.setCurrentRow(idx)

    def next_profile(self) -> None:
        self.select_profile((self.cfg.active + 1) % len(self.cfg.profiles))

    def prev_profile(self) -> None:
        self.select_profile((self.cfg.active - 1) % len(self.cfg.profiles))

    # ------------------------------------------------------------------
    # Загрузка значений в элементы управления
    # ------------------------------------------------------------------

    def _load_controls(self) -> None:
        p = self.cfg.current
        self._loading = True
        try:
            g = p.gen
            for attr, w in self._gw.items():
                v = getattr(g, attr)
                if isinstance(w, LabeledSlider):
                    w.set_value(v)
                elif isinstance(w, ColorPicker):
                    w.set_color(v)
                elif isinstance(w, QCheckBox):
                    w.blockSignals(True)
                    w.setChecked(v)
                    w.blockSignals(False)
            self._gen_stack.setCurrentIndex(0 if p.kind == "generated" else 1)
            self._update_gen_enabled()

            for s, v in ((self._ox, p.offset_x), (self._oy, p.offset_y)):
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
            self._scale.set_value(int(round(p.scale * 100)))
            self._rotation.set_value(p.rotation)
            self._opacity.set_value(p.opacity)
            self._img_size.set_value(p.size)
            self._tint.set_color(p.tint)
            self._image_box.setVisible(p.kind == "image")
            self._hk_profile.set_value(p.hotkey)
            self._hk_profile_label.setText(f"Клавиша выбора прицела «{p.name}»:")
        finally:
            self._loading = False
        self._update_preview()

    def _update_gen_enabled(self) -> None:
        g = self.cfg.current.gen
        self._gw["dot_size"].setEnabled(g.center_dot)
        self._gw["circle_radius"].setEnabled(g.circle)
        self._gw["circle_thickness"].setEnabled(g.circle)
        self._gw["outline_color"].setEnabled(g.outline)
        self._gw["outline_thickness"].setEnabled(g.outline)

    # ------------------------------------------------------------------
    # Изменения параметров
    # ------------------------------------------------------------------

    def _set_gen(self, attr: str, value) -> None:
        if self._loading:
            return
        setattr(self.cfg.current.gen, attr, value)
        self._update_gen_enabled()
        self._commit()

    def _set_prof(self, attr: str, value) -> None:
        if self._loading:
            return
        setattr(self.cfg.current, attr, value)
        self._commit()

    def nudge(self, dx: int, dy: int) -> None:
        self.set_offset(self.cfg.current.offset_x + dx, self.cfg.current.offset_y + dy)

    def set_offset(self, x: int, y: int) -> None:
        lo, hi = OFFSET_LIMITS
        p = self.cfg.current
        p.offset_x = max(lo, min(hi, x))
        p.offset_y = max(lo, min(hi, y))
        for s, v in ((self._ox, p.offset_x), (self._oy, p.offset_y)):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)
        self._commit()

    def convert_to_generated(self) -> None:
        self.cfg.current.kind = "generated"
        self._load_controls()
        self._commit()

    def _commit(self) -> None:
        """Любое изменение: рендер -> предпросмотр, иконка, оверлей, отложенное сохранение."""
        self._update_preview()
        self._update_current_item()
        self._emit_overlay()
        self._schedule_save()

    def _render_current(self) -> QImage:
        return render_profile(self.cfg.current)

    def _update_preview(self) -> None:
        self._preview.set_image(self._render_current())

    def _emit_overlay(self) -> None:
        p = self.cfg.current
        self.overlay_update.emit(self._render_current(), p.offset_x, p.offset_y,
                                 self.cfg.monitor_index)

    def _set_bg(self, dark: bool) -> None:
        self._bg_dark.setChecked(dark)
        self._bg_light.setChecked(not dark)
        self._preview.set_dark(dark)

    # ------------------------------------------------------------------
    # Библиотека / импорт / редактор
    # ------------------------------------------------------------------

    def _on_tab_changed(self, idx: int) -> None:
        if self._tabs.tabText(idx) == "Библиотека":
            self._rebuild_library()

    def _on_lib_click(self, item: QListWidgetItem) -> None:
        row = self._lib.row(item)
        if 0 <= row < len(self._lib_entries):
            self._lib_selected = self._lib_entries[row]
            self._lib_add.setEnabled(True)
            self.apply_entry(self._lib_selected)

    def apply_entry(self, entry: Profile) -> None:
        """Применяет прицел из библиотеки к активному профилю (клавиша и смещение сохраняются)."""
        cur = self.cfg.current
        new = entry.copy()
        new.hotkey = cur.hotkey
        new.offset_x, new.offset_y = cur.offset_x, cur.offset_y
        self.cfg.profiles[self.cfg.active] = new
        self._load_controls()
        self._commit()
        self.profiles_changed.emit()

    def add_library_selection(self) -> None:
        if self._lib_selected is None:
            return
        p = self._lib_selected.copy()
        p.hotkey = ""
        self.cfg.profiles.append(p)
        self.cfg.active = len(self.cfg.profiles) - 1
        self._structure_changed()

    def import_png(self, path: str) -> Optional[str]:
        """Копирует PNG в папку custom. Возвращает новый путь или None."""
        if QImage(path).isNull():
            QMessageBox.warning(self, "Импорт PNG", "Не удалось открыть файл как картинку.")
            return None
        folder = self._custom_dir()
        base, ext = os.path.splitext(os.path.basename(path))
        target = os.path.join(folder, base + ".png")
        i = 1
        while os.path.exists(target):
            target = os.path.join(folder, f"{base}_{i}.png")
            i += 1
        img = QImage(path)
        if not img.save(target, "PNG"):
            shutil.copy2(path, target)
        self._rebuild_library()
        return target

    def _import_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Импорт PNG", "", "Картинки (*.png)")
        for f in files:
            self.import_png(f)

    def _on_editor_saved(self, path: str, name: str) -> None:
        img = QImage(path)
        size = max(SIZE_LIMITS[0], min(SIZE_LIMITS[1], max(img.width(), img.height()) or 32))
        self.cfg.profiles.append(Profile(name=name, kind="image", image_path=path, size=size))
        self.cfg.active = len(self.cfg.profiles) - 1
        self._structure_changed()
        self._status.setText("Прицел из редактора сохранён и выбран.")

    # ------------------------------------------------------------------
    # Клавиши
    # ------------------------------------------------------------------

    def _set_global_hotkey(self, key: str, value: str) -> None:
        self.cfg.hotkeys[key] = value
        self._update_toggle_ui()
        self._schedule_save()
        self.hotkeys_changed.emit()

    def _set_profile_hotkey(self, value: str) -> None:
        if self._loading:
            return
        self.cfg.current.hotkey = value
        self._update_current_item()
        self._schedule_save()
        self.hotkeys_changed.emit()

    def _on_rmb(self, v: bool) -> None:
        self.cfg.hide_on_rmb = v
        self._schedule_save()
        self.hide_on_rmb_changed.emit(v)

    def set_hotkey_errors(self, errors: list[str]) -> None:
        self._hk_errors.setText("\n".join(errors))
        if errors:
            self._status.setText("Не все горячие клавиши удалось назначить — см. вкладку «Клавиши».")

    # ------------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------------

    def _on_monitor(self) -> None:
        idx = self._monitor_combo.currentData()
        if idx is None:
            return
        self.cfg.monitor_index = int(idx)
        self._emit_overlay()
        self._schedule_save()

    def copy_share_code(self) -> None:
        try:
            code = encode_share_code(self.cfg.current)
        except ValueError as e:
            QMessageBox.warning(self, "Код прицела", str(e))
            return
        QApplication.clipboard().setText(code)
        self._status.setText("Код прицела скопирован в буфер обмена.")

    def paste_share_code(self) -> None:
        text = QApplication.clipboard().text()
        try:
            p = decode_share_code(text, self._custom_dir())
        except ValueError as e:
            QMessageBox.warning(self, "Код прицела", str(e))
            return
        self.cfg.profiles.append(p)
        self.cfg.active = len(self.cfg.profiles) - 1
        self._structure_changed()
        self._status.setText("Прицел из кода добавлен.")

    def _open_custom_folder(self) -> None:
        try:
            os.startfile(self._custom_dir())
        except Exception as e:
            QMessageBox.warning(self, "Папка", f"Не удалось открыть папку: {e}")

    # ------------------------------------------------------------------
    # Показ / скрытие прицела
    # ------------------------------------------------------------------

    def _update_toggle_ui(self) -> None:
        key = self.cfg.hotkeys.get("toggle", "")
        suffix = f"  [{key.upper()}]" if key else ""
        self._toggle_btn.setText(("Скрыть прицел" if self.cfg.overlay_on else "Показать прицел") + suffix)
        self._status.setText("Прицел: включён" if self.cfg.overlay_on else "Прицел: выключен")

    def toggle_overlay(self) -> None:
        self.cfg.overlay_on = not self.cfg.overlay_on
        self._update_toggle_ui()
        self._schedule_save()
        self.visibility_changed.emit(self.cfg.overlay_on)

    def refresh_all(self) -> None:
        """Отправляет в оверлей и менеджер клавиш актуальное состояние (при старте)."""
        self._emit_overlay()
        self.visibility_changed.emit(self.cfg.overlay_on)
        self.hide_on_rmb_changed.emit(self.cfg.hide_on_rmb)
        self.hotkeys_changed.emit()
        self.profiles_changed.emit()

    # ------------------------------------------------------------------
    # Сохранение и события окна
    # ------------------------------------------------------------------

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def flush_save(self) -> None:
        self._save_timer.stop()
        try:
            self._save_fn(self.cfg)
        except Exception as e:
            self._status.setText(f"Не удалось сохранить настройки: {e}")

    def _restore_position(self, x: int, y: int) -> None:
        for s in QApplication.screens():
            if s.availableGeometry().contains(x + 40, y + 20):
                self.move(x, y)
                return

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def moveEvent(self, ev) -> None:
        super().moveEvent(ev)
        if self.isVisible():
            self.cfg.window_x, self.cfg.window_y = self.x(), self.y()
            self._schedule_save()

    def closeEvent(self, ev) -> None:
        # Крестик прячет окно в трей
        self.cfg.window_x, self.cfg.window_y = self.x(), self.y()
        self.flush_save()
        ev.ignore()
        self.hide()
