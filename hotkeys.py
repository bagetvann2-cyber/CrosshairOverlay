"""Глобальные горячие клавиши (библиотека keyboard) и опрос правой кнопки мыши."""
from __future__ import annotations

import ctypes
from typing import Any, Optional

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal

VK_RBUTTON = 0x02
RMB_POLL_MS = 15

_SPECIAL_KEYS = {
    Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete",
    Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_End: "end",
    Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down", Qt.Key_Pause: "pause",
    Qt.Key_Minus: "-", Qt.Key_Equal: "=", Qt.Key_Comma: ",", Qt.Key_Period: ".",
}
_MODIFIER_KEYS = {
    Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr,
    Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_ScrollLock,
}


def qt_key_to_hotkey(key: int, modifiers: Any) -> Optional[str]:
    """Переводит нажатие Qt в строку для keyboard ('ctrl+alt+right').
    None — если нажат только модификатор или клавиша не поддерживается."""
    if key in _MODIFIER_KEYS or key == 0 or key == Qt.Key_unknown:
        return None
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        name = f"f{key - Qt.Key_F1 + 1}"
    elif key in _SPECIAL_KEYS:
        name = _SPECIAL_KEYS[key]
    elif Qt.Key_A <= key <= Qt.Key_Z:
        name = chr(ord("a") + key - Qt.Key_A)
    elif Qt.Key_0 <= key <= Qt.Key_9:
        name = chr(ord("0") + key - Qt.Key_0)
    else:
        return None
    parts = []
    if modifiers & Qt.ControlModifier:
        parts.append("ctrl")
    if modifiers & Qt.AltModifier:
        parts.append("alt")
    if modifiers & Qt.ShiftModifier:
        parts.append("shift")
    if modifiers & Qt.MetaModifier:
        parts.append("windows")
    parts.append(name)
    return "+".join(parts)


class HotkeyManager(QObject):
    """Регистрирует глобальные клавиши; колбэки из потока keyboard
    уходят в GUI-поток через сигналы."""
    toggle_pressed = pyqtSignal()
    next_pressed = pyqtSignal()
    prev_pressed = pyqtSignal()
    profile_pressed = pyqtSignal(int)

    def __init__(self, backend: Any = None) -> None:
        super().__init__()
        if backend is None:
            import keyboard as backend  # type: ignore
        self._kb = backend
        self._handles: list[Any] = []

    def clear(self) -> None:
        for h in self._handles:
            try:
                h() if callable(h) else self._kb.remove_hotkey(h)
            except Exception:
                pass
        self._handles.clear()

    def apply(self, toggle: str, nxt: str, prev: str,
              profile_keys: dict[int, str]) -> list[str]:
        """Перерегистрирует все клавиши. Возвращает список текстов ошибок (пустой — всё ок)."""
        self.clear()
        errors: list[str] = []
        entries: list[tuple[str, Any]] = [
            (toggle, lambda: self.toggle_pressed.emit()),
            (nxt, lambda: self.next_pressed.emit()),
            (prev, lambda: self.prev_pressed.emit()),
        ]
        for idx, combo in profile_keys.items():
            entries.append((combo, lambda i=idx: self.profile_pressed.emit(i)))
        seen: set[str] = set()
        for combo, cb in entries:
            combo = (combo or "").strip()
            if not combo:
                continue
            norm = combo.lower()
            if norm in seen:
                errors.append(f"Сочетание «{combo}» назначено дважды — второе пропущено.")
                continue
            seen.add(norm)
            try:
                self._handles.append(self._kb.add_hotkey(combo, cb))
            except Exception as e:
                errors.append(f"Не удалось назначить «{combo}»: {e}")
        return errors


class RmbWatcher(QObject):
    """Следит за правой кнопкой мыши через GetAsyncKeyState (без хуков)."""
    state_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._pressed = False
        self._timer = QTimer(self)
        self._timer.setInterval(RMB_POLL_MS)
        self._timer.timeout.connect(self._poll)

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()
            if self._pressed:
                self._pressed = False
                self.state_changed.emit(False)

    def _poll(self) -> None:
        down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
        if down != self._pressed:
            self._pressed = down
            self.state_changed.emit(down)
