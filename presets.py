"""Встроенные прицелы: генерируемые пресеты и старые PNG из папки crosshairs."""
from __future__ import annotations

import glob
import os

from crosshair_model import GenParams, Profile, builtin_crosshairs_dir

# Русские названия для старых PNG
LEGACY_NAMES = {
    "circle": "Круг (PNG)",
    "circle_cross": "Круг с крестом (PNG)",
    "cross": "Крест (PNG)",
    "dot": "Точка (PNG)",
}


def _p(name: str, rotation: int = 0, **kw) -> Profile:
    return Profile(name=name, kind="generated", gen=GenParams(**kw), rotation=rotation)


def default_profile() -> Profile:
    return _p("Классический крест")


def builtin_presets() -> list[Profile]:
    """Около 30 генерируемых прицелов (новые объекты при каждом вызове)."""
    only = dict(top=False, bottom=False, left=False, right=False)
    return [
        default_profile(),
        _p("Крест без зазора", gap=0, line_length=7, color="#FFFFFF"),
        _p("Широкий крест", line_length=10, gap=7, color="#00FFFF"),
        _p("Микро-крест", line_length=3, gap=2, line_thickness=1, color="#FFFF00"),
        _p("Тонкий крест", line_length=9, gap=4, line_thickness=1, color="#00FF00"),
        _p("Толстый крест", line_length=8, gap=4, line_thickness=4, color="#FF00FF"),
        _p("Тактический крест", line_length=14, gap=8, line_thickness=1,
           center_dot=True, dot_size=1, color="#FFFFFF"),
        _p("Крест с точкой", center_dot=True, dot_size=2, color="#00FF00"),
        _p("Красный крест с точкой", center_dot=True, dot_size=2, color="#FF2020"),
        _p("Розовый крест", line_length=7, gap=3, color="#FF66CC"),
        _p("Точка", dot_size=3, center_dot=True, outline=False, color="#00FF00", **only),
        _p("Точка с обводкой", dot_size=4, center_dot=True, color="#FF2020", **only),
        _p("Малая точка", dot_size=2, center_dot=True, color="#FFFFFF", **only),
        _p("Большая точка", dot_size=8, center_dot=True, color="#FFFF00", **only),
        _p("T-образный", top=False, color="#00FF00"),
        _p("T-образный оранжевый", top=False, line_length=8, color="#FF8000"),
        _p("Перевёрнутый T", bottom=False, color="#00FFFF"),
        _p("Круг", circle=True, circle_radius=8, circle_thickness=2, outline=True,
           color="#FFFFFF", **only),
        _p("Круг с точкой", circle=True, circle_radius=9, circle_thickness=1,
           center_dot=True, dot_size=2, color="#00FF00", **only),
        _p("Крест с кругом", circle=True, circle_radius=12, circle_thickness=1,
           line_length=5, gap=3, color="#00FFFF"),
        _p("Малый круг с точкой", circle=True, circle_radius=5, center_dot=True,
           dot_size=1, color="#FF66CC", **only),
        _p("Большой круг", circle=True, circle_radius=40, circle_thickness=2,
           color="#FFFFFF", **only),
        _p("Снайперский круг", circle=True, circle_radius=26, circle_thickness=1,
           line_length=20, gap=3, line_thickness=1, center_dot=True, dot_size=1,
           color="#FF2020"),
        _p("X-образный", rotation=45, line_length=6, gap=3, color="#00FF00"),
        _p("X-образный с точкой", rotation=45, line_length=7, gap=3,
           center_dot=True, dot_size=2, color="#FFFF00"),
        _p("Только лучи вверх", bottom=False, left=False, right=False,
           line_length=8, gap=4, color="#00FF00"),
        _p("Только лучи вниз", top=False, left=False, right=False,
           line_length=8, gap=4, color="#00FFFF"),
        _p("Только горизонталь", top=False, bottom=False, line_length=8, gap=3,
           color="#FF8000"),
        _p("Только вертикаль", left=False, right=False, line_length=8, gap=3,
           color="#FF66CC"),
    ]


def legacy_image_presets() -> list[Profile]:
    """Старые PNG из встроенной папки crosshairs как image-прицелы."""
    out: list[Profile] = []
    for f in sorted(glob.glob(os.path.join(builtin_crosshairs_dir(), "*.png"))):
        stem = os.path.splitext(os.path.basename(f))[0]
        out.append(Profile(
            name=LEGACY_NAMES.get(stem, stem), kind="image",
            image_path=os.path.basename(f), tint="#00FF00", size=64,
        ))
    return out


def legacy_name(stem: str) -> str:
    return LEGACY_NAMES.get(stem, stem)
