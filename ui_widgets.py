"""Общие виджеты интерфейса и тёмная тема (QSS)."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import (
    QColorDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider,
    QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from crosshair_model import norm_hex
from hotkeys import qt_key_to_hotkey

ACCENT = "#3ddc84"

DARK_QSS = f"""
QWidget {{ background-color: #1e2024; color: #e4e6ea; font-size: 13px; }}
QLabel {{ background: transparent; }}
QLabel#hint {{ color: #9aa0a8; }}
QLabel#title {{ font-size: 15px; font-weight: bold; color: {ACCENT}; }}
QTabWidget::pane {{ border: 1px solid #33373d; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: #262a30; padding: 7px 14px; border: 1px solid #33373d;
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 2px; }}
QTabBar::tab:selected {{ background: #1e2024; color: {ACCENT}; }}
QTabBar::tab:hover {{ background: #2e333a; }}
QPushButton, QToolButton {{ background-color: #2b3037; border: 1px solid #3a3f47;
    border-radius: 5px; padding: 6px 12px; }}
QPushButton:hover, QToolButton:hover {{ background-color: #343a42; border-color: {ACCENT}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: #3b424b; }}
QPushButton:checked, QToolButton:checked {{ background-color: #24523a; border-color: {ACCENT}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #6a7078; background-color: #24272c; }}
QPushButton#accent {{ background-color: {ACCENT}; color: #0e1a13; font-weight: bold;
    border: none; }}
QPushButton#accent:hover {{ background-color: #5ae89b; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background-color: #14161a;
    border: 1px solid #3a3f47; border-radius: 4px; padding: 4px 6px;
    selection-background-color: {ACCENT}; selection-color: #0e1a13; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: #14161a; selection-background-color: #24523a; }}
QListWidget {{ background-color: #14161a; border: 1px solid #33373d; border-radius: 6px;
    outline: none; padding: 3px; }}
QListWidget::item {{ padding: 4px; border-radius: 4px; }}
QListWidget::item:selected {{ background-color: #24523a; color: #ffffff; }}
QListWidget::item:hover {{ background-color: #2a2f36; }}
QSlider::groove:horizontal {{ height: 4px; background: #3a3f47; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0;
    background: #f2f4f7; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #4a5059;
    border-radius: 4px; background: #14161a; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QScrollArea {{ border: none; background-color: #1e2024; }}
QAbstractScrollArea::corner {{ background-color: #1e2024; border: none; }}
QScrollBar:horizontal {{ background: #1e2024; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #3a3f47; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: #1e2024; }}
QScrollBar:vertical {{ background: #1e2024; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3a3f47; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: #14161a; color: #e4e6ea; border: 1px solid {ACCENT}; }}
QMenu {{ background: #1e2024; border: 1px solid #3a3f47; }}
QMenu::item:selected {{ background: #24523a; }}
"""


class LabeledSlider(QWidget):
    """Подпись + слайдер + спинбокс. valueChanged — только от действий пользователя."""
    valueChanged = pyqtSignal(int)

    def __init__(self, text: str, lo: int, hi: int, value: int, suffix: str = "") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(text)
        self._label.setMinimumWidth(140)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(lo, hi)
        self._spin = QSpinBox()
        self._spin.setRange(lo, hi)
        self._spin.setFixedWidth(72)
        if suffix:
            self._spin.setSuffix(suffix)
        self._slider.valueChanged.connect(self._spin.setValue)
        self._spin.valueChanged.connect(self._slider.setValue)
        self._spin.valueChanged.connect(self.valueChanged)
        lay.addWidget(self._label)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._spin)
        self.set_value(value)

    def value(self) -> int:
        return self._spin.value()

    def set_value(self, v: int) -> None:
        """Выставляет значение без излучения сигнала."""
        for w in (self._slider, self._spin):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)


class ColorPicker(QWidget):
    """Кнопка-превью + HEX + пресеты + RGB. Сигнал colorChanged(hex)."""
    colorChanged = pyqtSignal(str)

    PRESETS = [
        ("Зелёный", "#00FF00"), ("Циан", "#00FFFF"), ("Розовый", "#FF00FF"),
        ("Жёлтый", "#FFFF00"), ("Красный", "#FF0000"), ("Белый", "#FFFFFF"),
        ("Чёрный", "#000000"), ("Оранжевый", "#FF8000"),
    ]

    def __init__(self, color: str = "#FFFFFF") -> None:
        super().__init__()
        self._color = QColor(norm_hex(color, "#FFFFFF"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        top = QHBoxLayout()
        self._btn = QPushButton()
        self._btn.setFixedHeight(30)
        self._btn.setToolTip("Нажмите, чтобы выбрать цвет")
        self._btn.clicked.connect(self._open_dialog)
        self._hex = QLineEdit()
        self._hex.setPlaceholderText("#FFFFFF")
        self._hex.setFixedWidth(90)
        self._hex.editingFinished.connect(self._apply_hex)
        self._rgb_btn = QToolButton()
        self._rgb_btn.setText("RGB")
        self._rgb_btn.setCheckable(True)
        top.addWidget(self._btn, 1)
        top.addWidget(QLabel("HEX:"))
        top.addWidget(self._hex)
        top.addWidget(self._rgb_btn)
        lay.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(4)
        for name, hx in self.PRESETS:
            b = QPushButton()
            b.setFixedSize(24, 24)
            b.setToolTip(name)
            b.setStyleSheet(f"background-color: {hx}; border: 1px solid #555; border-radius: 3px; padding: 0;")
            b.clicked.connect(lambda _c=False, h=hx: self._user_set(QColor(h)))
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        self._rgb_widget = QWidget()
        rl = QHBoxLayout(self._rgb_widget)
        rl.setContentsMargins(0, 0, 0, 0)
        self._spins = []
        for t in "RGB":
            s = QSpinBox()
            s.setRange(0, 255)
            s.setFixedWidth(64)
            s.valueChanged.connect(self._on_rgb)
            rl.addWidget(QLabel(t))
            rl.addWidget(s)
            self._spins.append(s)
        rl.addStretch()
        self._rgb_widget.setVisible(False)
        self._rgb_btn.toggled.connect(self._rgb_widget.setVisible)
        lay.addWidget(self._rgb_widget)
        self._refresh()

    def color(self) -> str:
        return self._color.name().upper()

    def set_color(self, hx: str) -> None:
        """Тихо выставляет цвет (без сигнала)."""
        self._color = QColor(norm_hex(hx, self.color()))
        self._refresh()

    def _refresh(self) -> None:
        self._btn.setStyleSheet(
            f"background-color: {self._color.name()}; border: 1px solid #555; border-radius: 4px;"
        )
        self._hex.setText(self._color.name().upper())
        for s, v in zip(self._spins, (self._color.red(), self._color.green(), self._color.blue())):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)

    def _user_set(self, c: QColor) -> None:
        if not c.isValid():
            return
        self._color = c
        self._refresh()
        self.colorChanged.emit(self.color())

    def _open_dialog(self) -> None:
        c = QColorDialog.getColor(self._color, self, "Выберите цвет")
        self._user_set(c)

    def _apply_hex(self) -> None:
        t = self._hex.text().strip()
        if t and not t.startswith("#"):
            t = "#" + t
        c = QColor(t)
        if c.isValid():
            if c.name().upper() != self.color():
                self._user_set(c)
        else:
            self._refresh()

    def _on_rgb(self) -> None:
        self._user_set(QColor(*(s.value() for s in self._spins)))


class HotkeyEdit(QWidget):
    """Поле записи сочетания: «Назначить» ждёт нажатия, Esc — отмена."""
    changed = pyqtSignal(str)

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._value = text
        self._recording = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit()
        self._edit.setReadOnly(True)
        self._edit.setPlaceholderText("не назначено")
        self._assign = QPushButton("Назначить")
        self._clear = QPushButton("Сбросить")
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._assign)
        lay.addWidget(self._clear)
        self._assign.clicked.connect(self.start_recording)
        self._clear.clicked.connect(lambda: self._set(""))
        self._edit.setText(text)
        self.setFocusPolicy(Qt.StrongFocus)

    def value(self) -> str:
        return self._value

    def set_value(self, v: str) -> None:
        self._value = v
        self._edit.setText(v)

    def _set(self, v: str) -> None:
        self.set_value(v)
        self.changed.emit(v)

    def start_recording(self) -> None:
        self._recording = True
        self._assign.setText("Нажмите клавишу… (Esc — отмена)")
        self.setFocus()
        self.grabKeyboard()

    def _stop(self) -> None:
        self._recording = False
        self._assign.setText("Назначить")
        self.releaseKeyboard()

    def keyPressEvent(self, ev) -> None:
        if not self._recording:
            super().keyPressEvent(ev)
            return
        if ev.key() == Qt.Key_Escape:
            self._stop()
            return
        combo = qt_key_to_hotkey(ev.key(), ev.modifiers())
        if combo is None:
            return  # просто модификатор — ждём основную клавишу
        self._stop()
        self._set(combo)

    def focusOutEvent(self, ev) -> None:
        if self._recording:
            self._stop()
        super().focusOutEvent(ev)


class PreviewWidget(QWidget):
    """Крупный предпросмотр прицела на тёмном или светлом фоне."""

    def __init__(self) -> None:
        super().__init__()
        self._img: QImage | None = None
        self._dark = True
        self.setMinimumHeight(170)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def set_image(self, img: QImage) -> None:
        self._img = img
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#2b2b2b" if self._dark else "#e8e8e8"))
        p.setPen(QColor("#3c3c3c" if self._dark else "#d0d0d0"))
        cx, cy = self.width() // 2, self.height() // 2
        p.drawLine(cx, 0, cx, self.height())   # тонкие направляющие через центр
        p.drawLine(0, cy, self.width(), cy)
        if self._img is not None and not self._img.isNull():
            w, h = self._img.width(), self._img.height()
            k = max(1, min(6, (self.width() - 20) // max(1, w), (self.height() - 20) // max(1, h)))
            tw, th = w * k, h * k
            p.drawImage(QRect(cx - tw // 2, cy - th // 2, tw, th), self._img)
        p.end()
