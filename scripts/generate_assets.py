"""キャラ / 背景 / カメラプレビューの参考画像を gemini-3-pro-image-preview で一括生成。

実行:
  python3 scripts/generate_assets.py                  # dry-run (= プロンプトだけ出す)
  python3 scripts/generate_assets.py --apply          # 実生成 (API 課金あり)
  python3 scripts/generate_assets.py --apply --only characters
  python3 scripts/generate_assets.py --apply --only locations
  python3 scripts/generate_assets.py --apply --only camera

ファイル方針:
  - characters/ は事前に削除して 1 から作り直す (= 一貫性のため)
  - locations/ は既存 JSON ベースで .preview.png を生成 (上書き)
  - frontend/public/camera-distance/ は close-up/medium-close/medium/wide.png
    を 1 枚の全身写真からクロップして生成、SVG は別途削除する

冪等性: <path> が既に存在する場合は再生成しない (--force で強制)。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from PIL import Image  # noqa: E402

# ─── 5 人 × 3 衣装 のキャラ定義 ──────────────────────────────

# キャラ ID → identity 記述 (= 全衣装で共通の顔・体・髪)
CHARACTER_IDENTITIES = {
    "f1": (
        "20代後半の日本人女性、肩より少し下のロングストレートのダークブラウンの髪、"
        "自然で親しみやすい笑顔、清潔感のある肌、平均身長(約160cm)、健康的でスレンダーな体型"
    ),
    "f2": (
        "30代前半の日本人女性、顎ラインのダークブラウンのボブヘア、薄い黒縁メガネ、"
        "知的で穏やかな表情、平均身長(約162cm)、すっきりした体型"
    ),
    "f3": (
        "20代前半の日本人女性、肩までのアッシュブラウンのゆるいウェーブヘア、"
        "ナチュラルメイク、柔らかく優しい表情、平均身長(約158cm)、スレンダーな体型"
    ),
    "m1": (
        "20代後半の日本人男性、黒髪のショートカット(清潔感のあるサイドパート)、"
        "爽やかで真面目な表情、髭なし、約175cmの引き締まった体型"
    ),
    "m2": (
        "30代前半の日本人男性、ダークブラウンの横分けの髪、銀フレームのメガネ、"
        "自信のある穏やかな表情、約180cmのしっかりした体型"
    ),
}

CHARACTER_GENDERS = {"f1": "f", "f2": "f", "f3": "f", "m1": "m", "m2": "m"}

WARDROBES = ["office", "casual", "loungewear"]

WARDROBE_DETAILS = {
    ("f", "office"): (
        "白いブラウス、ネイビーのテーラードジャケット、グレーのスラックス、"
        "ベージュのローヒールパンプス"
    ),
    ("f", "casual"): (
        "オフホワイトの長袖リブニット、ストレートデニム、白いスニーカー"
    ),
    ("f", "loungewear"): (
        "ベージュの長袖リブニット、ライトグレーのスウェットパンツ、白い靴下"
    ),
    ("m", "office"): (
        "白いオックスフォードシャツ、ネイビーのテーラードブレザー、"
        "ベージュのチノパン、茶色のレザーローファー"
    ),
    ("m", "casual"): (
        "ベージュの無地クルーネックTシャツ、ストレートデニム、白いスニーカー"
    ),
    ("m", "loungewear"): (
        "ライトグレーのスウェット上下、白い靴下"
    ),
}

# キャラの voice メタ (= 既存 voice_overrides を踏襲)
CHARACTER_VOICE = {
    "f1": {"stability": 0.45, "style": 0.35, "similarity_boost": 0.7},
    "f2": {"stability": 0.5, "style": 0.25, "similarity_boost": 0.7},
    "f3": {"stability": 0.4, "style": 0.4, "similarity_boost": 0.7},
    "m1": {"stability": 0.45, "style": 0.3, "similarity_boost": 0.7},
    "m2": {"stability": 0.5, "style": 0.25, "similarity_boost": 0.7},
}

# キャラ画像の共通描写 (= 全身、9:16、白背景、棒立ち)
CHAR_BG = (
    "シンプルなオフホワイトのグラデーション背景、装飾なし、被写体に集中させる構図、"
    "影は最小限"
)
CHAR_POSE = (
    "正面を向き、棒立ち、両手は体の横、自然な立ち姿、表情はうっすら微笑む程度の中立、"
    "全身がフレームに収まる構図、視線はカメラ"
)
CHAR_QUALITY = (
    "リアル写真風、自然光、9:16の縦長フルボディ、no text, no letters, no logos"
)


def build_character_prompt(char_id: str, wardrobe: str) -> str:
    identity = CHARACTER_IDENTITIES[char_id]
    gender = CHARACTER_GENDERS[char_id]
    clothing = WARDROBE_DETAILS[(gender, wardrobe)]
    return (
        f"被写体: {identity}\n"
        f"服装: {clothing}\n"
        f"ポーズ: {CHAR_POSE}\n"
        f"背景: {CHAR_BG}\n"
        f"画質: {CHAR_QUALITY}"
    )


# ─── ロケ参照プロンプト ──────────────────────────────────────


def build_location_prompt(loc) -> str:
    parts: list[str] = []
    if loc.decor:
        parts.append(loc.decor)
    if loc.props:
        parts.append(loc.props)
    if loc.color_palette:
        parts.append(f"color palette: {loc.color_palette}")
    if loc.lighting:
        parts.append(loc.lighting)
    body = "、".join(parts)
    distance_label = {
        "close-up": "close-up",
        "medium-close": "medium close-up",
        "medium": "medium",
        "wide": "wide",
    }.get(loc.camera_distance, "medium")
    return (
        f"{distance_label} shot of empty location, no people, scenery only, "
        f"{body}, single moment in time, no text, no letters, "
        f"vertical portrait composition"
    )


# ─── カメラプレビュー (= 4 framing) の元写真 ────────────────


CAMERA_BASE_PROMPT = (
    "20代の日本人男性、白い無地Tシャツとデニム、清潔感のあるショートカット、"
    "正面を向いて棒立ち、自然な表情、両手は体の横、"
    "オフホワイトのスタジオ背景、影は最小限、リアル写真風、"
    "9:16縦長フルボディ、no text, no letters"
)

# クロップ範囲 (top, bottom) を画像の高さの比率で指定。9:16 を維持するために幅も中央クロップ。
CAMERA_CROPS = {
    # close-up: 顔だけ ≒ 上 0%〜25%
    "close-up": (0.00, 0.22),
    # medium-close: 頭〜胸 ≒ 0%〜45%
    "medium-close": (0.00, 0.45),
    # medium: 頭〜膝近く ≒ 0%〜78%
    "medium": (0.00, 0.78),
    # wide: 全身 ≒ 0%〜100%
    "wide": (0.00, 1.00),
}


def crop_to_aspect_9_16(img: Image.Image, top_ratio: float, bottom_ratio: float) -> Image.Image:
    """画像を縦方向に [top_ratio, bottom_ratio] でクロップし、9:16 にリサイズ調整する。"""
    w, h = img.size
    top = int(h * top_ratio)
    bottom = int(h * bottom_ratio)
    cropped = img.crop((0, top, w, bottom))
    cw, ch = cropped.size
    target_w = int(ch * 9 / 16)
    if target_w <= cw:
        left = (cw - target_w) // 2
        cropped = cropped.crop((left, 0, left + target_w, ch))
    else:
        target_h = int(cw * 16 / 9)
        cropped = cropped.crop((0, 0, cw, min(ch, target_h)))
    return cropped


# ─── 実行ロジック ────────────────────────────────────────


def _gen(prompt: str, out_path: Path, refs: list[str] | None = None) -> None:
    import imagen_client
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  📸 generating: {out_path.relative_to(ROOT)}")
    t0 = time.time()
    imagen_client.generate_image(prompt, str(out_path), aspect_ratio="9:16",
                                 reference_images=refs)
    print(f"     ✓ done ({time.time() - t0:.1f}s)")


def cmd_characters(apply: bool, force: bool) -> None:
    chars_dir = Path(config.CHARACTERS_DIR)
    if apply:
        # 既存 PNG (= 旧キャラ画像) を全削除
        for png in chars_dir.rglob("*.png"):
            print(f"  🗑 remove {png.relative_to(ROOT)}")
            png.unlink()
        # 旧 base.png のためのキャラディレクトリ (空になったもの) も削除
        for child in chars_dir.iterdir():
            if child.is_dir() and not any(child.iterdir()):
                child.rmdir()
                print(f"  🗑 remove dir {child.relative_to(ROOT)}")

    print(f"\n== キャラ生成 ({len(CHARACTER_IDENTITIES)} 人 × {len(WARDROBES)} 衣装) ==")
    for char_id in CHARACTER_IDENTITIES:
        char_dir = chars_dir / char_id
        # voice.json を保存
        voice_path = char_dir / "voice.json"
        if apply:
            char_dir.mkdir(parents=True, exist_ok=True)
            with open(voice_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"id": char_id, "voice_overrides": CHARACTER_VOICE[char_id]},
                    f, ensure_ascii=False, indent=2,
                )
                f.write("\n")
            print(f"  ✓ wrote {voice_path.relative_to(ROOT)}")

        # 衣装画像
        prev_path: Path | None = None
        for w_idx, wardrobe in enumerate(WARDROBES):
            out = char_dir / f"{wardrobe}.png"
            prompt = build_character_prompt(char_id, wardrobe)
            print(f"\n--- {char_id} / {wardrobe} ---")
            print(prompt)
            if not apply:
                prev_path = out  # dry-run でも参照鎖を仮想的に表示
                continue
            if out.exists() and not force:
                print(f"  skip (既存): {out.relative_to(ROOT)}")
                prev_path = out
                continue
            refs = [str(prev_path)] if (prev_path and prev_path.exists() and w_idx > 0) else None
            _gen(prompt, out, refs=refs)
            prev_path = out

        # base.png は 1 枚目の衣装をコピーしてフォールバック用にする
        if apply:
            first = char_dir / f"{WARDROBES[0]}.png"
            base = char_dir / "base.png"
            if first.exists() and (not base.exists() or force):
                shutil.copyfile(first, base)
                print(f"  ✓ base.png ← {first.name} (fallback for bare ID)")


def cmd_locations(apply: bool, force: bool) -> None:
    from analyze import location as loc_mod
    print("\n== ロケプレビュー生成 ==")
    for loc_id in loc_mod.list_locations():
        loc = loc_mod.load_location(loc_id)
        out = loc_mod.preview_path(loc_id)
        prompt = build_location_prompt(loc)
        print(f"\n--- {loc_id} ---")
        print(prompt)
        if not apply:
            continue
        if out.exists() and not force:
            print(f"  skip (既存): {out.relative_to(ROOT)}")
            continue
        _gen(prompt, out)


def cmd_camera(apply: bool, force: bool) -> None:
    out_dir = ROOT / "frontend" / "public" / "camera-distance"
    base_path = out_dir / "_base.png"
    print("\n== カメラ距離プレビュー生成 ==")
    print("\n--- _base (元写真) ---")
    print(CAMERA_BASE_PROMPT)
    if apply and (not base_path.exists() or force):
        out_dir.mkdir(parents=True, exist_ok=True)
        _gen(CAMERA_BASE_PROMPT, base_path)
    elif apply:
        print(f"  skip (既存): {base_path.relative_to(ROOT)}")

    if not apply:
        for cid in CAMERA_CROPS:
            print(f"  → {cid}.png  (crop)")
        return

    img = Image.open(base_path)
    for cid, (top, bottom) in CAMERA_CROPS.items():
        out = out_dir / f"{cid}.png"
        if out.exists() and not force:
            print(f"  skip (既存): {out.relative_to(ROOT)}")
            continue
        cropped = crop_to_aspect_9_16(img, top, bottom)
        cropped.save(out)
        print(f"  ✓ {out.relative_to(ROOT)}  ({top:.2f}〜{bottom:.2f})")

    # 旧 SVG を削除
    for cid in CAMERA_CROPS:
        svg = out_dir / f"{cid}.svg"
        if svg.exists():
            svg.unlink()
            print(f"  🗑 remove {svg.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="実生成")
    ap.add_argument("--force", action="store_true", help="既存ファイルも上書き")
    ap.add_argument("--only", choices=["characters", "locations", "camera"],
                    help="一部だけ実行")
    args = ap.parse_args()

    targets = ["characters", "locations", "camera"] if not args.only else [args.only]
    if "characters" in targets:
        cmd_characters(args.apply, args.force)
    if "locations" in targets:
        cmd_locations(args.apply, args.force)
    if "camera" in targets:
        cmd_camera(args.apply, args.force)

    if not args.apply:
        print("\n--apply で実生成 (API 課金が発生します)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
