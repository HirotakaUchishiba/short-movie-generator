"""TTS 直前のテキスト整形ユーティリティ。

scene_gen.py から段階分割の第一歩として抽出。これらは pure function なので
単体テスト可能で、stage 別 module の前段で共有する。
"""
from __future__ import annotations

import re


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
