"""stages/image_helpers.py の純粋 PIL 変換テスト。"""
from __future__ import annotations

from PIL import Image

import config
import scene_gen
from stages import image_helpers


def _make_test_png(path: str, w: int, h: int, color=(255, 0, 0)) -> None:
    img = Image.new("RGB", (w, h), color=color)
    img.save(path, "PNG")


def test_prepare_background_resizes_to_video_dims(tmp_path):
    src = tmp_path / "src.png"
    _make_test_png(str(src), 400, 600)
    dst = tmp_path / "dst.png"
    image_helpers.prepare_background(str(src), str(dst))
    out = Image.open(dst)
    assert out.size == (config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
    assert out.mode == "RGB"


def test_prepare_background_already_correct_size(tmp_path):
    src = tmp_path / "src.png"
    _make_test_png(str(src), config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
    dst = tmp_path / "dst.png"
    image_helpers.prepare_background(str(src), str(dst))
    out = Image.open(dst)
    assert out.size == (config.VIDEO_WIDTH, config.VIDEO_HEIGHT)


def test_scene_gen_shim_delegates(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake(*a, **kw):
        calls.append("prepare")

    monkeypatch.setattr(image_helpers, "prepare_background", fake)
    scene_gen._prepare_background("a", "b")
    assert calls == ["prepare"]
