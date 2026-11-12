import os

from PyQt5.QtCore import QSettings

import storage
from crosshair_model import Profile


def ini(tmp_path, name="legacy.ini"):
    # отдельный INI-файл во временной папке — реальные настройки не трогаем
    return QSettings(str(tmp_path / name), QSettings.IniFormat)


def test_empty_gives_default(qapp, tmp_path):
    cfg = storage.load_config(ini(tmp_path))
    assert len(cfg.profiles) == 1
    assert cfg.profiles[0].name == "Классический крест"
    assert cfg.hotkeys["toggle"] == "F9"
    assert os.path.exists(storage.config_path())


def test_migration(qapp, tmp_path):
    s = ini(tmp_path)
    s.setValue("color/r", 255)
    s.setValue("color/g", 0)
    s.setValue("color/b", 128)
    s.setValue("size", 48)
    s.setValue("crosshair_path", r"C:\old\dist\crosshairs\cross.png")
    s.setValue("overlay_on", False)
    s.setValue("window/x", 100)
    s.setValue("window/y", 200)
    s.sync()
    cfg = storage.load_config(ini(tmp_path))
    p = cfg.profiles[0]
    assert p.kind == "image" and p.size == 48 and p.tint == "#FF0080"
    assert os.path.basename(p.image_path) == "cross.png"
    assert cfg.overlay_on is False
    assert (cfg.window_x, cfg.window_y) == (100, 200)
    assert ini(tmp_path).contains("crosshair_path")  # старые ключи на месте


def test_atomic_save_load(qapp, tmp_path):
    cfg = storage.AppConfig()
    cfg.profiles.append(Profile(name="Второй"))
    cfg.active = 1
    cfg.monitor_index = 2
    storage.save_config(cfg)
    folder = os.path.dirname(storage.config_path())
    assert [f for f in os.listdir(folder) if f.endswith(".tmp")] == []
    assert str(tmp_path) in storage.config_path()
    back = storage.load_config(ini(tmp_path))
    assert back.active == 1 and back.monitor_index == 2
    assert [p.name for p in back.profiles] == ["Классический крест", "Второй"]


def test_corrupt_config(qapp, tmp_path):
    os.makedirs(storage.data_dir())
    with open(storage.config_path(), "w") as f:
        f.write("{not json")
    cfg = storage.load_config(ini(tmp_path))
    assert len(cfg.profiles) == 1
    assert os.path.exists(storage.config_path() + ".bad")


def test_custom_dir_created(qapp):
    assert os.path.isdir(storage.custom_dir())
