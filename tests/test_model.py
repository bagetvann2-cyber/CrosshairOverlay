import numpy as np
import pytest
from PyQt5.QtGui import QImage, QColor

import crosshair_model as cm
from crosshair_model import GenParams, Profile, render_profile


def alpha(img):
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    a = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine())[:, : w * 4]
    return a.reshape(h, w, 4)[:, :, 3]


def test_cross_not_empty_and_symmetric(qapp):
    img = render_profile(Profile())
    a = alpha(img)
    assert a.max() > 0
    assert img.width() == img.height()
    assert np.array_equal(a, a[:, ::-1])
    assert np.array_equal(a, a[::-1, :])


def test_odd_thickness_symmetric(qapp):
    p = Profile(gen=GenParams(line_thickness=3, gap=2, center_dot=True, dot_size=2))
    img = render_profile(p)
    a = alpha(img)
    assert np.array_equal(a, a[:, ::-1]) and np.array_equal(a, a[::-1, :])
    assert img.width() % 2 == 1


def test_t_shape_no_top(qapp):
    p = Profile(gen=GenParams(top=False, outline=False))
    img = render_profile(p)
    a = alpha(img)
    c = img.width() // 2
    assert a[: c - 1, :].max() == 0          # выше центра пусто
    assert a[c + 1:, :].max() > 0            # нижний луч есть


def test_scale_changes_size(qapp):
    base = render_profile(Profile()).width()
    assert render_profile(Profile(scale=2.0)).width() == base * 2
    assert render_profile(Profile(scale=0.5)).width() < base


def test_rotation_changes_size(qapp):
    gen = GenParams(top=False, bottom=False, outline=False, line_length=20)
    w0 = render_profile(Profile(gen=gen)).width()
    assert render_profile(Profile(gen=gen, rotation=90)).width() == w0
    assert render_profile(Profile(gen=gen, rotation=45)).width() != w0


def test_opacity_and_dict_roundtrip(qapp):
    p = Profile(name="Тест", opacity=50, offset_x=7, rotation=-30, scale=1.5,
                gen=GenParams(color="#123456", circle=True))
    q = Profile.from_dict(p.to_dict())
    assert q == p
    assert alpha(render_profile(Profile(opacity=50))).max() <= 128


def test_from_dict_tolerant(qapp):
    p = Profile.from_dict({"name": "x", "scale": "bad", "gen": {"gap": 9999, "color": "zzz"}})
    assert p.scale == 1.0 and p.gen.gap == cm.GEN_LIMITS["gap"][1]
    assert p.gen.color == "#00FF00"
    assert isinstance(Profile.from_dict(None), Profile)


def test_share_generated(qapp):
    p = Profile(name="Мой", hotkey="f5", gen=GenParams(color="#FF0000", circle=True))
    code = cm.encode_share_code(p)
    assert code.startswith("XH1-")
    q = cm.decode_share_code(code)
    p.hotkey = ""
    assert q == p


def test_share_image_embedded(qapp, tmp_path):
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(QColor(255, 0, 0, 255))
    src = tmp_path / "mine.png"
    img.save(str(src), "PNG")
    p = Profile(name="Картинка", kind="image", image_path=str(src), size=16)
    code = cm.encode_share_code(p)
    out = tmp_path / "custom"
    q = cm.decode_share_code(code, str(out))
    assert q.kind == "image"
    assert q.image_path.startswith(str(out))
    assert QImage(q.image_path).width() == 8
    assert render_profile(q).width() > 2


@pytest.mark.parametrize("bad", ["", "hello", "XH1-", "XH1-!!!!", "XH1-AAAA", "XH2-abc"])
def test_bad_code(qapp, bad):
    with pytest.raises(ValueError):
        cm.decode_share_code(bad)
