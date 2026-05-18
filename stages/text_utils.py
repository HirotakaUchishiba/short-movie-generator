"""TTS 直前のテキスト整形ユーティリティ。

scene_gen.py から段階分割の第一歩として抽出。これらは pure function なので
単体テスト可能で、stage 別 module の前段で共有する。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """TTS にそのまま渡せる形にテキストを整形する。

    - 連番接頭 (= "1. " "2) " 等) を除去
    - 全角丸括弧で囲まれた注釈を除去
    - ASCII / 全角の不要句読点を除去 (v3 が `,` `.` を読み上げトリガーにするため)
    - 一部記号を v3 が解釈しやすい一般形に正規化
    """
    text = re.sub(r"^\d+[\.\)）]\s*", "", text)
    text = re.sub(r"[（(][^）)]*[）)]\s*", "", text)
    text = re.sub(r"[,.、。「」『』]", "", text)
    text = text.replace("⁉", "!?").replace("‼", "!!").replace("⁇", "??")
    text = text.replace("〜", "ー").replace("~", "ー")
    text = re.sub(r"[…―—]", "", text)
    return text.strip()


def apply_pronunciation_hints(
    text: str,
    hints: dict | None,
    global_dict: dict | None = None,
) -> str:
    """global furigana dict + line.pronunciation_hints を merge してテキスト置換。

    line.hints が同じ key を持つ場合は line.hints が優先 (= line 別オーバーライド)。
    長い key 優先で置換するため、"AI" と "AI モデル" のような prefix 一致時に
    後者が先に置換される。
    """
    effective: dict[str, str] = {}
    if global_dict:
        effective.update(global_dict)
    if hints:
        effective.update(hints)
    if not effective:
        return text
    for src in sorted(effective.keys(), key=len, reverse=True):
        dst = effective[src]
        if src:
            text = text.replace(src, dst)
    return text


def load_global_furigana_dict() -> dict[str, str]:
    """``furigana_store`` から global furigana 辞書を読み込む (= 失敗時は空 dict)。

    failed-open: 読み込みに失敗しても呼び出し側を止めないため、warning ログを
    残して空 dict を返す (= per-line hints だけは引き続き効く)。
    """
    try:
        import furigana_store

        return furigana_store.load()
    except Exception as e:
        logger.warning("furigana_store ロード失敗: %s", e)
        return {}


def neighbor_line_text(
    screenplay: dict | None,
    scene_idx: int,
    line_idx: int,
    direction: str,
) -> str | None:
    """指定 line の前/後の line.text を取得。シーン境界を跨いで隣接シーンも探索。

    Args:
        direction: ``"prev"`` または ``"next"``。

    Returns:
        該当 line.text。見つからなければ ``None``。
    """
    if not screenplay:
        return None
    scenes = screenplay.get("scenes", [])
    if scene_idx >= len(scenes):
        return None
    cur_lines = scenes[scene_idx].get("lines") or []

    if direction == "prev":
        if line_idx > 0:
            return cur_lines[line_idx - 1].get("text")
        for s in range(scene_idx - 1, -1, -1):
            prev_lines = scenes[s].get("lines") or []
            if prev_lines:
                return prev_lines[-1].get("text")
        return None

    if direction == "next":
        if line_idx + 1 < len(cur_lines):
            return cur_lines[line_idx + 1].get("text")
        for s in range(scene_idx + 1, len(scenes)):
            next_lines = scenes[s].get("lines") or []
            if next_lines:
                return next_lines[0].get("text")
        return None

    return None
