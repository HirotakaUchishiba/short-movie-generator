import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(autouse=True)
def _stub_character_images(request, monkeypatch):
    """validator / diagnose_abstract の character ref 物理存在検証は
    既定スキップ (= 開発機の characters/ に依存しない)。

    存在検証を働かせたいテストは個別に
    `monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: [...])`
    で上書きする。``@pytest.mark.real_characters_dir`` を付けた test では
    skip され、character_meta 本体の挙動を直接テストできる。
    """
    if request.node.get_closest_marker("real_characters_dir"):
        return
    from analyze import character_meta as cmeta_mod
    monkeypatch.setattr(cmeta_mod, "list_character_images", lambda: [])
