import os
from pathlib import Path

import pytest

import post_captions_gen


@pytest.fixture(autouse=True)
def _isolate_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(post_captions_gen.config, "POST_CAPTIONS_DIR", str(tmp_path))


def test_writes_caption_verbatim() -> None:
    sp = {
        "caption": "会社選びが何より大切です\n\n#未経験 #転職",
        "scenes": [{"segments": [{"text": "foo"}]}],
    }
    path = post_captions_gen.generate_post_captions(sp, "01_test.json", "/tmp/out.mp4")

    content = Path(path).read_text()
    assert "会社選びが何より大切です" in content
    assert "#未経験" in content
    assert "#転職" in content
    assert "/tmp/out.mp4" in content


def test_uses_screenplay_name_as_filename(tmp_path: Path) -> None:
    sp = {
        "caption": "foo",
        "scenes": [{"segments": [{"text": "x"}]}],
    }
    path = post_captions_gen.generate_post_captions(sp, "my_video.json", "/tmp/out.mp4")
    assert os.path.basename(path) == "my_video.md"


def test_empty_caption_still_produces_file() -> None:
    sp = {
        "caption": "",
        "scenes": [{"segments": [{"text": "x"}]}],
    }
    path = post_captions_gen.generate_post_captions(sp, "empty.json", "/tmp/out.mp4")
    assert os.path.exists(path)
