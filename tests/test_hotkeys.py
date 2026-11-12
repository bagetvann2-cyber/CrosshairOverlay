from PyQt5.QtCore import Qt

from hotkeys import HotkeyManager, qt_key_to_hotkey


class FakeKb:
    def __init__(self):
        self.added, self.removed = [], 0

    def add_hotkey(self, combo, cb):
        if combo == "bad!!":
            raise ValueError("нет такой клавиши")
        self.added.append(combo)
        return lambda: setattr(self, "removed", self.removed + 1)

    def remove_hotkey(self, h):
        pass


def test_qt_key_conversion():
    assert qt_key_to_hotkey(Qt.Key_F9, Qt.NoModifier) == "f9"
    assert qt_key_to_hotkey(Qt.Key_Right, Qt.ControlModifier | Qt.AltModifier) == "ctrl+alt+right"
    assert qt_key_to_hotkey(Qt.Key_Control, Qt.ControlModifier) is None
    assert qt_key_to_hotkey(Qt.Key_A, Qt.ShiftModifier) == "shift+a"


def test_manager_errors_and_reregister(qapp):
    kb = FakeKb()
    m = HotkeyManager(kb)
    errs = m.apply("F9", "bad!!", "f9", {0: "f1"})
    assert kb.added == ["F9", "f1"]
    assert len(errs) == 2          # ошибка клавиши + дубликат
    m.apply("F9", "", "", {})
    assert kb.removed == 2
