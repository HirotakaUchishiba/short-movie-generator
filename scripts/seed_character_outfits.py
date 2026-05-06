"""キャラ × 衣装の Cartesian で characters/<ref>__<wardrobe>.png を seed する。

VideoStyle.wardrobe_options に列挙された衣装タグごとに
characters/<base_ref>__<wardrobe_tag>.png を生成する。生成した画像は
Imagen の reference image として使われ、衣装の identity を再現する。

各 (base_ref, wardrobe_tag) について imagen_client.generate_image を呼んで
画像を生成する。既存ファイルは skip、--force で再生成。

Usage:
    python3 scripts/seed_character_outfits.py             # 全 style 全衣装
    python3 scripts/seed_character_outfits.py --style office_engineer
    python3 scripts/seed_character_outfits.py --force     # 既存も再生成
    python3 scripts/seed_character_outfits.py --dry-run   # 実行計画のみ表示
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(THIS_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config
import imagen_client
from analyze import style as analyze_style

logger = logging.getLogger("seed_character_outfits")


# 衣装タグごとの seed prompt テキスト。
# Imagen prompt の "wearing ..." 部分にそのまま渡す。
SEED_WARDROBE_TEXTS: dict[str, str] = {
    "office_outfit": "グレーのリブニット + ブラックパンツ + 眼鏡 + ロングヘア",
    "casual_apron": "白いリネンシャツ + ベージュのエプロン + ナチュラルメイク + ハーフアップ",
    "loungewear": "オフホワイトのオーバーサイズスウェット + ライトデニム + ナチュラルメイク + ロングヘア",
    "casual_outdoor": "ベージュのワイドパンツ + 白カーディガン + 薄手スカーフ + ライトメイク + ハーフアップ",
    "neutral_top": "オフホワイトのシンプルなTシャツ + ナチュラルメイク + ストレートヘア",
}


def _outfit_path(base_ref: str, wardrobe_tag: str) -> str:
    return os.path.join(
        config.CHARACTERS_DIR, f"{base_ref}__{wardrobe_tag}.png",
    )


def _base_ref_path(base_ref: str) -> str:
    return os.path.join(config.CHARACTERS_DIR, f"{base_ref}.png")


def _build_prompt(base_ref: str, wardrobe_text: str) -> str:
    """seed 画像の Imagen prompt。

    base_ref 画像を reference に渡し、その人物に衣装を着せた縦 9:16 portrait を
    要求する。背景は無地 (= 衣装の見やすさ優先)、表情はニュートラル。
    """
    return (
        f"portrait of the same person from the reference, "
        f"wearing {wardrobe_text}, neutral expression, neutral pose, "
        f"plain neutral background, soft even lighting, full upper body framing"
    )


def _collect_pairs(
    style_filter: str | None,
) -> list[tuple[str, str]]:
    """全 VideoStyle を読み込み、(base_ref, wardrobe_tag) のユニーク集合を返す。"""
    pairs: set[tuple[str, str]] = set()
    for name in analyze_style.list_styles():
        if style_filter and name != style_filter:
            continue
        try:
            sty = analyze_style.load_style(name)
        except Exception as e:
            logger.warning("style %s 読み込み失敗: %s", name, e)
            continue
        wardrobes = list(sty.wardrobe_options)
        for c in sty.characters:
            base = c.ref
            if not base:
                continue
            for w in wardrobes:
                pairs.add((base, w))
    return sorted(pairs)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--style", help="特定 style のみ対象 (default: 全 style)")
    p.add_argument("--force", action="store_true", help="既存ファイルも再生成")
    p.add_argument(
        "--dry-run", action="store_true",
        help="実行計画のみ表示 (Imagen 呼び出しなし)",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="DEBUG ログ",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    pairs = _collect_pairs(args.style)
    if not pairs:
        logger.error("対象なし (style=%s)", args.style)
        return 1

    print(f"対象: {len(pairs)} ペア")
    for base, w in pairs:
        out = _outfit_path(base, w)
        exists = os.path.exists(out)
        text = SEED_WARDROBE_TEXTS.get(w, "(未登録の衣装テキスト)")
        marker = "skip" if exists and not args.force else "GEN"
        print(f"  [{marker}] {base} × {w}")
        print(f"         → {out}")
        print(f"         text: {text}")

    if args.dry_run:
        print("\n--dry-run: 何も生成しません")
        return 0

    generated = 0
    skipped = 0
    failed: list[tuple[str, str, str]] = []
    for base, w in pairs:
        out = _outfit_path(base, w)
        if os.path.exists(out) and not args.force:
            skipped += 1
            continue
        text = SEED_WARDROBE_TEXTS.get(w)
        if not text:
            logger.warning(
                "衣装 '%s' の seed テキストが未登録 — SEED_WARDROBE_TEXTS に "
                "追加してから実行してください",
                w,
            )
            failed.append((base, w, "missing seed text"))
            continue
        ref = _base_ref_path(base)
        if not os.path.exists(ref):
            logger.warning(
                "ベースキャラ画像が見つかりません: %s — スキップ", ref,
            )
            failed.append((base, w, f"missing base ref: {ref}"))
            continue
        prompt = _build_prompt(base, text)
        logger.info("生成: %s × %s → %s", base, w, out)
        try:
            imagen_client.generate_image(
                prompt, out, aspect_ratio="9:16",
                reference_images=[ref],
            )
            generated += 1
        except Exception as e:
            logger.error("生成失敗 (%s × %s): %s", base, w, e)
            failed.append((base, w, str(e)))

    print(f"\n完了: 生成={generated} / skip={skipped} / 失敗={len(failed)}")
    if failed:
        for base, w, msg in failed:
            print(f"  FAIL: {base} × {w}: {msg}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
