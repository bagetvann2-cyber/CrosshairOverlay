"""Хранилище настроек в %APPDATA%\\CrosshairOverlay\\config.json."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

from PyQt5.QtCore import QSettings

from crosshair_model import (
    Profile, _clamp_int, _to_bool, builtin_crosshairs_dir, norm_hex,
)
import presets

SETTINGS_ORG = "CrosshairOverlay"
SETTINGS_APP = "Settings"

DEFAULT_HOTKEYS = {"toggle": "F9", "next": "ctrl+alt+right", "prev": "ctrl+alt+left"}


def data_dir() -> str:
    """Папка данных. APPDATA читается при каждом вызове (удобно для тестов)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "CrosshairOverlay")


def config_path() -> str:
    return os.path.join(data_dir(), "config.json")


def custom_dir() -> str:
    """Папка пользовательских PNG (создаётся при обращении)."""
    p = os.path.join(data_dir(), "custom")
    os.makedirs(p, exist_ok=True)
    return p


@dataclass
class AppConfig:
    profiles: list[Profile] = field(default_factory=lambda: [presets.default_profile()])
    active: int = 0
    overlay_on: bool = True
    monitor_index: int = 0
    hide_on_rmb: bool = False
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    window_x: Optional[int] = None
    window_y: Optional[int] = None

    def normalize(self) -> "AppConfig":
        if not self.profiles:
            self.profiles = [presets.default_profile()]
        self.active = max(0, min(len(self.profiles) - 1, self.active))
        for k, v in DEFAULT_HOTKEYS.items():
            self.hotkeys.setdefault(k, v)
        return self

    @property
    def current(self) -> Profile:
        return self.profiles[self.active]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "profiles": [p.to_dict() for p in self.profiles],
            "active": self.active,
            "overlay_on": self.overlay_on,
            "monitor_index": self.monitor_index,
            "hide_on_rmb": self.hide_on_rmb,
            "hotkeys": dict(self.hotkeys),
            "window": {"x": self.window_x, "y": self.window_y},
        }

    @staticmethod
    def from_dict(d: Any) -> "AppConfig":
        if not isinstance(d, dict):
            raise ValueError("config.json: ожидался объект")
        cfg = AppConfig()
        raw = d.get("profiles")
        if isinstance(raw, list):
            cfg.profiles = [Profile.from_dict(x) for x in raw]
        cfg.active = _clamp_int(d.get("active", 0), 0, 10_000, 0)
        cfg.overlay_on = _to_bool(d.get("overlay_on", True), True)
        cfg.monitor_index = _clamp_int(d.get("monitor_index", 0), 0, 64, 0)
        cfg.hide_on_rmb = _to_bool(d.get("hide_on_rmb", False), False)
        hk = d.get("hotkeys")
        cfg.hotkeys = dict(DEFAULT_HOTKEYS)
        if isinstance(hk, dict):
            for k in DEFAULT_HOTKEYS:
                if k in hk:
                    cfg.hotkeys[k] = str(hk[k] or "")
        win = d.get("window")
        if isinstance(win, dict):
            for key, attr in (("x", "window_x"), ("y", "window_y")):
                if win.get(key) is not None:
                    setattr(cfg, attr, _clamp_int(win[key], -100_000, 100_000, 0))
        return cfg.normalize()


def save_config(cfg: AppConfig) -> None:
    """Атомарная запись: временный файл рядом + os.replace."""
    folder = data_dir()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="config_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_path())
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def migrate_from_qsettings(s: QSettings) -> Optional[AppConfig]:
    """Строит конфиг из старых ключей QSettings. None — если старых ключей нет.
    Старые значения не удаляются."""
    keys = ("color/r", "color/g", "color/b", "size", "crosshair_path", "overlay_on", "window/x")
    if not any(s.contains(k) for k in keys):
        return None
    cfg = AppConfig()
    path = str(s.value("crosshair_path", "") or "")
    if path:
        r = _clamp_int(s.value("color/r", 255), 0, 255, 255)
        g = _clamp_int(s.value("color/g", 255), 0, 255, 255)
        b = _clamp_int(s.value("color/b", 255), 0, 255, 255)
        stem = os.path.splitext(os.path.basename(path))[0]
        base = os.path.basename(path)
        in_builtin = os.path.exists(os.path.join(builtin_crosshairs_dir(), base))
        prof = Profile(
            name=presets.legacy_name(stem) or "Мой прицел",
            kind="image",
            image_path=base if in_builtin else path,
            tint=norm_hex(f"#{r:02X}{g:02X}{b:02X}", "#FFFFFF"),
            size=_clamp_int(s.value("size", 64), 8, 512, 64),
        )
        cfg.profiles = [prof]
    cfg.overlay_on = _to_bool(s.value("overlay_on", True), True)
    x, y = s.value("window/x"), s.value("window/y")
    if x is not None and y is not None:
        cfg.window_x = _clamp_int(x, -100_000, 100_000, 0)
        cfg.window_y = _clamp_int(y, -100_000, 100_000, 0)
    return cfg.normalize()


def load_config(legacy: Optional[QSettings] = None) -> AppConfig:
    """Читает config.json; если его нет — миграция из QSettings или значения по умолчанию.
    legacy можно подставить (в тестах), иначе читаются реальные старые настройки."""
    path = config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return AppConfig.from_dict(json.load(f))
        except Exception:
            try:  # битый файл — сохраняем рядом и начинаем заново
                os.replace(path, path + ".bad")
            except OSError:
                pass
    if legacy is None:
        legacy = QSettings(SETTINGS_ORG, SETTINGS_APP)
    cfg = migrate_from_qsettings(legacy) or AppConfig()
    try:
        save_config(cfg)
    except OSError:
        pass
    return cfg
