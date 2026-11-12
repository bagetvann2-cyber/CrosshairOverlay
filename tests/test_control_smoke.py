from PyQt5.QtWidgets import QApplication, QMessageBox

import storage
from control import ControlPanel


def make(tmp_path):
    cfg = storage.AppConfig()
    saved = []
    panel = ControlPanel(cfg, save_fn=lambda c: saved.append(1),
                         custom_dir_fn=lambda: str(tmp_path / "custom"))
    return cfg, panel, saved


def test_smoke(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    cfg, panel, saved = make(tmp_path)
    images = []
    panel.overlay_update.connect(lambda img, x, y, m: images.append((img.width(), x, y, m)))
    panel.show()
    for i in range(panel._tabs.count()):
        panel._tabs.setCurrentIndex(i)
        qapp.processEvents()

    gw = panel._gw
    gw["line_length"].valueChanged.emit(12)
    gw["circle"].setChecked(True)
    gw["center_dot"].setChecked(True)
    assert cfg.current.gen.line_length == 12 and cfg.current.gen.circle
    panel.nudge(1, 0)
    panel.nudge(0, -1)
    assert (cfg.current.offset_x, cfg.current.offset_y) == (1, -1)
    panel._scale.valueChanged.emit(200)
    assert cfg.current.scale == 2.0
    panel._rotation.valueChanged.emit(45)
    assert images and images[-1][1:] == (1, -1, 0)

    panel.add_profile()
    panel.duplicate_profile()
    panel.rename_profile(cfg.active, "Новый")
    panel.move_profile(-1)
    panel.next_profile()
    panel.prev_profile()
    assert len(cfg.profiles) == 3
    panel.delete_profile()
    assert len(cfg.profiles) == 2

    # библиотека
    panel._tabs.setCurrentIndex(2)
    assert panel._lib.count() >= 30
    panel._on_lib_click(panel._lib.item(5))
    panel.add_library_selection()
    legacy = [i for i, e in enumerate(panel._lib_entries) if e.kind == "image"]
    assert legacy
    panel._on_lib_click(panel._lib.item(legacy[0]))
    assert cfg.current.kind == "image"
    panel._tabs.setCurrentIndex(0)
    assert panel._gen_stack.currentIndex() == 1
    panel.convert_to_generated()
    assert cfg.current.kind == "generated"

    # редактор -> новый профиль
    n = len(cfg.profiles)
    panel._editor.begin_stroke((3, 3))
    path = panel._editor.save_as_crosshair()
    assert path and len(cfg.profiles) == n + 1 and cfg.current.kind == "image"

    # код прицела туда-обратно через буфер обмена
    panel.copy_share_code()
    before = len(cfg.profiles)
    panel.paste_share_code()
    assert len(cfg.profiles) == before + 1
    QApplication.clipboard().setText("мусор")
    panel.paste_share_code()
    assert len(cfg.profiles) == before + 1

    panel.toggle_overlay()
    assert cfg.overlay_on is False
    panel.flush_save()
    assert saved
    panel.close()
