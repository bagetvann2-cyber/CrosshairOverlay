"""Модель прицела: параметры, профили, рендер в QImage, коды для обмена."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sys
import zlib
from dataclasses import dataclass, field, fields
from typing import Any, Optional

import numpy as np
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen

SHARE_PREFIX = "XH1-"
MAX_SHARE_BYTES = 16 * 1024 * 1024  # защита от «бомбы» при распаковке кода

# Допустимые диапазоны (используются и при чтении, и в интерфейсе)
GEN_LIMITS: dict[str, tuple[int, int]] = {
    "opacity": (0, 100),
    "line_length": (0, 100),
    "line_thickness": (1, 20),
    "gap": (0, 60),
    "dot_size": (1, 30),
    "circle_radius": (2, 120),
    "circle_thickness": (1, 12),
    "outline_thickness": (1, 6),
}
SIZE_LIMITS = (8, 512)
SCALE_LIMITS = (0.25, 4.0)
ROTATION_LIMITS = (-180, 180)
OFFSET_LIMITS = (-500, 500)
OPACITY_LIMITS = (0, 100)


def app_base_dir() -> str:
    """Папка рядом с exe (в сборке) или со скриптом."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def builtin_crosshairs_dir() -> str:
    return os.path.join(app_base_dir(), "crosshairs")


def is_builtin_path(path: str) -> bool:
    """Картинка лежит во встроенной папке crosshairs (или задана относительным путём)."""
    if not path:
        return True
    if not os.path.isabs(path):
        return True
    a = os.path.normcase(os.path.abspath(os.path.dirname(path)))
    b = os.path.normcase(os.path.abspath(builtin_crosshairs_dir()))
    return a == b


def resolve_image_path(path: str) -> str:
    """Абсолютный путь к картинке прицела (относительный — от встроенной папки)."""
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.join(builtin_crosshairs_dir(), path)


# ----------------------------------------------------------------------
# Вспомогательные функции приведения типов
# ----------------------------------------------------------------------

def norm_hex(value: Any, default: str) -> str:
    """Приводит строку к виду #RRGGBB, иначе возвращает default."""
    try:
        c = QColor(str(value).strip())
        if c.isValid():
            return c.name().upper()
    except Exception:
        pass
    return default


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    if math.isnan(v):
        v = default
    return max(lo, min(hi, v))


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "да")
    return default


# ----------------------------------------------------------------------
# Данные
# ----------------------------------------------------------------------

@dataclass
class GenParams:
    """Параметры генерируемого прицела (всё в пикселях)."""
    color: str = "#00FF00"
    opacity: int = 100
    line_length: int = 6
    line_thickness: int = 2
    gap: int = 3
    top: bool = True
    bottom: bool = True
    left: bool = True
    right: bool = True
    center_dot: bool = False
    dot_size: int = 2
    circle: bool = False
    circle_radius: int = 10
    circle_thickness: int = 1
    outline: bool = True
    outline_color: str = "#000000"
    outline_thickness: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @staticmethod
    def from_dict(d: Any) -> "GenParams":
        base = GenParams()
        if not isinstance(d, dict):
            return base
        for f in fields(GenParams):
            if f.name not in d:
                continue
            raw = d[f.name]
            cur = getattr(base, f.name)
            if f.name in ("color", "outline_color"):
                setattr(base, f.name, norm_hex(raw, cur))
            elif isinstance(cur, bool):
                setattr(base, f.name, _to_bool(raw, cur))
            elif isinstance(cur, int):
                lo, hi = GEN_LIMITS.get(f.name, (0, 1000))
                setattr(base, f.name, _clamp_int(raw, lo, hi, cur))
        return base


@dataclass
class Profile:
    """Профиль прицела: генерируемый или картинка + общие параметры."""
    name: str = "Новый прицел"
    kind: str = "generated"          # "generated" | "image"
    gen: GenParams = field(default_factory=GenParams)
    image_path: str = ""
    tint: str = "#FFFFFF"
    size: int = 64
    scale: float = 1.0
    rotation: int = 0
    offset_x: int = 0
    offset_y: int = 0
    opacity: int = 100
    hotkey: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "gen": self.gen.to_dict(),
            "image_path": self.image_path,
            "tint": self.tint,
            "size": self.size,
            "scale": self.scale,
            "rotation": self.rotation,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "opacity": self.opacity,
            "hotkey": self.hotkey,
        }

    @staticmethod
    def from_dict(d: Any) -> "Profile":
        p = Profile()
        if not isinstance(d, dict):
            return p
        p.name = str(d.get("name", p.name)) or p.name
        kind = d.get("kind", p.kind)
        p.kind = kind if kind in ("generated", "image") else "generated"
        p.gen = GenParams.from_dict(d.get("gen"))
        p.image_path = str(d.get("image_path", "") or "")
        p.tint = norm_hex(d.get("tint", p.tint), "#FFFFFF")
        p.size = _clamp_int(d.get("size", p.size), *SIZE_LIMITS, p.size)
        p.scale = _clamp_float(d.get("scale", p.scale), *SCALE_LIMITS, p.scale)
        p.rotation = _clamp_int(d.get("rotation", p.rotation), *ROTATION_LIMITS, 0)
        p.offset_x = _clamp_int(d.get("offset_x", 0), *OFFSET_LIMITS, 0)
        p.offset_y = _clamp_int(d.get("offset_y", 0), *OFFSET_LIMITS, 0)
        p.opacity = _clamp_int(d.get("opacity", p.opacity), *OPACITY_LIMITS, 100)
        p.hotkey = str(d.get("hotkey", "") or "")
        return p

    def copy(self) -> "Profile":
        return Profile.from_dict(self.to_dict())


# ----------------------------------------------------------------------
# Рендер
# ----------------------------------------------------------------------

def _new_canvas(side: int) -> QImage:
    img = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def _apply_opacity(img: QImage, percent: int) -> None:
    """Домножает альфу всего изображения на percent/100."""
    if percent >= 100:
        return
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.fillRect(img.rect(), QColor(0, 0, 0, int(round(255 * max(0, percent) / 100))))
    p.end()


def _alpha_view(img: QImage) -> np.ndarray:
    """Массив альфа-канала (h, w) из ARGB32 (premultiplied)."""
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine())
    return arr[:, : w * 4].reshape(h, w, 4)[:, :, 3]


def _crop_centered(img: QImage) -> QImage:
    """Обрезает холст до минимального квадрата вокруг центра, сохраняя чётность стороны
    (чтобы центр остался на той же пиксельной позиции)."""
    side = img.width()
    alpha = _alpha_view(img)
    ys, xs = np.nonzero(alpha)
    if xs.size == 0:
        return _new_canvas(2)
    c = side / 2.0
    half = max(c - xs.min(), xs.max() + 1 - c, c - ys.min(), ys.max() + 1 - c)
    new = int(math.ceil(half * 2))
    if (new - side) % 2:
        new += 1
    new = max(new, 2 if side % 2 == 0 else 1)
    if new >= side:
        return img
    off = (side - new) // 2
    return img.copy(off, off, new, new)


def _render_generated(p: Profile) -> QImage:
    g = p.gen
    k = p.scale

    def sc(v: int) -> int:
        return 0 if v <= 0 else max(1, int(round(v * k)))

    thick = max(1, sc(g.line_thickness))
    length = sc(g.line_length)
    gap = int(round(g.gap * k))
    odd = thick % 2 == 1
    half = 0.5 if odd else 0.0
    inner = gap + half
    arms = [g.top, g.bottom, g.left, g.right]
    has_arms = length > 0 and any(arms)

    dot = 0
    if g.center_dot:
        dot = sc(g.dot_size)
        if dot % 2 != thick % 2:   # точка по чётности как линии — чтобы не было размытия
            dot += 1
    r = ct = 0
    if g.circle:
        r = sc(g.circle_radius)
        ct = sc(g.circle_thickness)
    o = sc(g.outline_thickness) if g.outline else 0

    # Максимальный вылет от центра
    ext = 0.0
    if has_arms:
        ext = max(ext, inner + length + o, thick / 2 + o)
    if dot:
        ext = max(ext, dot / 2 + o)
    if r:
        ext = max(ext, r + ct / 2 + o)
    if ext <= 0:
        return _new_canvas(2)

    if p.rotation % 360 != 0:
        ext *= math.sqrt(2)
    side = int(math.ceil(ext * 2)) + 4
    if (side % 2 == 1) != odd:
        side += 1
    c = side / 2.0

    img = _new_canvas(side)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(c, c)
    if p.rotation:
        painter.rotate(p.rotation)
    painter.setPen(Qt.NoPen)

    def draw_all(color: QColor, grow: int) -> None:
        painter.setBrush(color)
        if has_arms:
            t2 = thick / 2.0
            L = length
            if g.right:
                painter.drawRect(QRectF(inner - grow, -t2 - grow, L + 2 * grow, thick + 2 * grow))
            if g.left:
                painter.drawRect(QRectF(-inner - L - grow, -t2 - grow, L + 2 * grow, thick + 2 * grow))
            if g.bottom:
                painter.drawRect(QRectF(-t2 - grow, inner - grow, thick + 2 * grow, L + 2 * grow))
            if g.top:
                painter.drawRect(QRectF(-t2 - grow, -inner - L - grow, thick + 2 * grow, L + 2 * grow))
        if dot:
            painter.drawRect(QRectF(-dot / 2.0 - grow, -dot / 2.0 - grow, dot + 2 * grow, dot + 2 * grow))
        if r:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, ct + 2 * grow))
            painter.drawEllipse(QPointF(0, 0), float(r), float(r))
            painter.setPen(Qt.NoPen)

    if o > 0:
        draw_all(QColor(norm_hex(g.outline_color, "#000000")), o)
    draw_all(QColor(norm_hex(g.color, "#00FF00")), 0)
    painter.end()

    _apply_opacity(img, g.opacity)
    return img


def _tinted(img: QImage, tint: str) -> QImage:
    """Умножает цвет на тон (как в старой версии); альфа не меняется."""
    c = QColor(norm_hex(tint, "#FFFFFF"))
    if (c.red(), c.green(), c.blue()) == (255, 255, 255):
        return img.convertToFormat(QImage.Format_ARGB32)
    src = img.convertToFormat(QImage.Format_ARGB32)
    w, h = src.width(), src.height()
    ptr = src.constBits()
    ptr.setsize(src.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, src.bytesPerLine())[:, : w * 4]
    arr = arr.reshape(h, w, 4).astype(np.float32)
    arr[:, :, 0] *= c.blue() / 255.0
    arr[:, :, 1] *= c.green() / 255.0
    arr[:, :, 2] *= c.red() / 255.0
    out = np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
    return QImage(out.data, w, h, w * 4, QImage.Format_ARGB32).copy()


def _render_image(p: Profile) -> QImage:
    src = QImage(resolve_image_path(p.image_path))
    if src.isNull():
        return _new_canvas(2)
    target = max(1, int(round(p.size * p.scale)))
    scaled = src.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    scaled = _tinted(scaled, p.tint)
    w, h = scaled.width(), scaled.height()
    rotated = p.rotation % 360 != 0
    side = max(w, h)
    if rotated:
        side = int(math.ceil(math.hypot(w, h))) + 2
    if side % 2:
        side += 1
    img = _new_canvas(side)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    if rotated:
        painter.translate(side / 2.0, side / 2.0)
        painter.rotate(p.rotation)
        painter.drawImage(QPointF(-w / 2.0, -h / 2.0), scaled)
    else:
        painter.drawImage((side - w) // 2, (side - h) // 2, scaled)
    painter.end()
    return img


def render_profile(profile: Profile) -> QImage:
    """Рисует прицел в минимальный квадрат (центр прицела = центр холста)."""
    img = _render_generated(profile) if profile.kind == "generated" else _render_image(profile)
    if img.width() > 2:
        _apply_opacity(img, profile.opacity)
        img = _crop_centered(img)
    return img.convertToFormat(QImage.Format_ARGB32_Premultiplied)


# ----------------------------------------------------------------------
# Код прицела для обмена
# ----------------------------------------------------------------------

def encode_share_code(profile: Profile) -> str:
    d = profile.to_dict()
    d["hotkey"] = ""
    payload: dict[str, Any] = {"v": 1, "profile": d}
    if profile.kind == "image":
        path = resolve_image_path(profile.image_path)
        d["image_path"] = os.path.basename(path)
        if not is_builtin_path(profile.image_path):
            try:
                with open(path, "rb") as f:
                    payload["png"] = base64.b64encode(f.read()).decode("ascii")
            except OSError:
                raise ValueError("Не удалось прочитать файл картинки прицела.")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
    return SHARE_PREFIX + token


def decode_share_code(code: str, custom_dir: Optional[str] = None) -> Profile:
    """Разбирает код прицела. При ошибке — ValueError с понятным текстом.
    Вшитую картинку сохраняет в custom_dir (по умолчанию — папка custom в AppData)."""
    text = "".join(str(code).split())
    if not text.startswith(SHARE_PREFIX):
        raise ValueError("Это не код прицела: он должен начинаться с «XH1-».")
    token = text[len(SHARE_PREFIX):]
    try:
        packed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        d = zlib.decompressobj()
        raw = d.decompress(packed, MAX_SHARE_BYTES)
        if d.unconsumed_tail:
            raise ValueError("слишком большой")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("profile"), dict):
            raise ValueError("нет профиля")
    except Exception:
        raise ValueError("Код прицела повреждён или неполный. Скопируйте его целиком.")

    profile = Profile.from_dict(payload["profile"])
    profile.hotkey = ""

    png_b64 = payload.get("png")
    if profile.kind == "image":
        if png_b64:
            try:
                data = base64.b64decode(png_b64)
            except Exception:
                raise ValueError("Картинка внутри кода повреждена.")
            probe = QImage()
            if not probe.loadFromData(data):
                raise ValueError("Картинка внутри кода повреждена.")
            if custom_dir is None:
                import storage
                custom_dir = storage.custom_dir()
            os.makedirs(custom_dir, exist_ok=True)
            fname = "shared_" + hashlib.sha1(data).hexdigest()[:10] + ".png"
            target = os.path.join(custom_dir, fname)
            if not os.path.exists(target):
                with open(target, "wb") as f:
                    f.write(data)
            profile.image_path = target
        else:
            name = os.path.basename(profile.image_path)
            if not name or not os.path.exists(os.path.join(builtin_crosshairs_dir(), name)):
                raise ValueError("В коде нет картинки, а встроенного прицела с таким именем нет.")
            profile.image_path = name
    return profile


def image_to_png_bytes(img: QImage) -> bytes:
    """Вспомогательное: QImage -> байты PNG."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)
