import subprocess

import pytest


@pytest.fixture
def normal_image(tmp_path) -> str:
    pytest.importorskip("cv2")
    path = str(tmp_path / "normal.png")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=gray:size=540x960:d=1",
        "-frames:v", "1", path,
    ], capture_output=True, check=True)
    return path


@pytest.fixture
def storyboard_image(tmp_path) -> str:
    """3つのまったく異なる輝度の領域を縦に並べたコマ割り風画像。"""
    pytest.importorskip("cv2")
    path = str(tmp_path / "storyboard.png")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=white:size=540x320:d=1",
        "-f", "lavfi", "-i", "color=c=gray:size=540x320:d=1",
        "-f", "lavfi", "-i", "color=c=black:size=540x320:d=1",
        "-filter_complex", "[0:v][1:v][2:v]vstack=inputs=3[v]",
        "-map", "[v]", "-frames:v", "1", path,
    ], capture_output=True, check=True)
    return path


def test_detect_storyboard_on_normal_image(normal_image) -> None:
    import scene_gen
    assert scene_gen._detect_storyboard_image(normal_image) is False


def test_detect_storyboard_on_panel_image(storyboard_image) -> None:
    import scene_gen
    assert scene_gen._detect_storyboard_image(storyboard_image) is True


def test_detect_storyboard_on_missing_file_returns_false(tmp_path) -> None:
    import scene_gen
    assert scene_gen._detect_storyboard_image(str(tmp_path / "nope.png")) is False
