"""characters/ を全て Pixar 風 + 令和の日本の登場人物で作り直す。

実行: python3 tmp/regenerate_characters.py [--char <id>] [--wardrobe <name>]

設計:
  1. 5 キャラ (f1, f2, f3, m1, m2) を Pixar 3D 風で生成
  2. 各キャラ最初に base.png (= 衣装 = office casual) を text-only で生成
  3. その base.png を reference に渡して残り 4 wardrobes (suit / casual /
     loungewear / office) を生成。顔・体型・髪型の一貫性を担保
  4. 全画像 9:16 縦長、白〜薄グレー単色背景、全身、棒立ち / 自然な立ち姿

voice.json は触らない。
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# project root を import path に追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import imagen_client  # noqa: E402

CHARACTERS_DIR = ROOT / "characters"


@dataclass(frozen=True)
class CharSpec:
    """1 キャラの基本属性。base / wardrobe 生成時に prompt に焼き込む。"""

    id: str
    gender: str          # "female" / "male"
    age_range: str       # "early 20s" など
    face: str            # 顔の特徴 (= 一貫性の核)
    hair: str            # 髪型・髪色 (= 一貫性の核)
    body: str            # 体型・身長感
    personality: str     # 印象 (= 表情の中立寄り方向)


# ─── 5 キャラの仕様 (= 顔・髪・体型は全 wardrobe で固定) ────────────
CHARS: list[CharSpec] = [
    CharSpec(
        id="f1",
        gender="female",
        age_range="early 20s",
        face="round face, large bright almond eyes, small nose, soft cheeks, warm friendly expression, healthy skin tone",
        hair="shoulder-length straight black hair with subtle bangs, glossy texture",
        body="petite slender build, around 158cm, natural posture",
        personality="energetic and approachable young woman",
    ),
    CharSpec(
        id="f2",
        gender="female",
        age_range="late 20s",
        face="oval face, almond eyes with calm intelligent gaze, defined cheekbones, gentle smile, fair skin",
        hair="long straight dark brown hair reaching mid-back, side-parted",
        body="average slim build, around 165cm, poised stance",
        personality="composed, intellectual professional woman",
    ),
    CharSpec(
        id="f3",
        gender="female",
        age_range="early 30s",
        face="soft heart-shaped face, warm brown eyes, kind expression, light freckles, natural skin tone",
        hair="chin-length bob cut, slightly wavy, dark brown with subtle highlights",
        body="average build, around 160cm, relaxed natural posture",
        personality="warm, caring woman with a gentle motherly air",
    ),
    CharSpec(
        id="m1",
        gender="male",
        age_range="mid 20s",
        face="clean-shaven, defined jawline, dark eyes, friendly open expression, healthy skin",
        hair="short black hair with a casual modern cut, slightly tousled on top",
        body="lean athletic build, around 175cm, relaxed confident posture",
        personality="approachable young man with cheerful sportsmanship",
    ),
    CharSpec(
        id="m2",
        gender="male",
        age_range="early 30s",
        face="slim oval face with subtle stubble, thoughtful eyes behind thin black-framed glasses, calm expression",
        hair="short black hair, neatly side-parted, professional",
        body="slim build, around 178cm, slightly reserved posture",
        personality="intellectual quiet man with a scholarly demeanor",
    ),
]


# ─── 服装 4 + base のプロンプト ────────────────────────────────────
# base = office casual (デフォルト参照、`<id>` 単独参照時に使われる)
WARDROBE_PROMPTS: dict[str, str] = {
    "base": (
        "wearing a casual office outfit appropriate for a modern Japanese "
        "workplace: smart neutral-toned knit top or shirt with comfortable "
        "tailored pants, simple sneakers or loafers"
    ),
    "suit": (
        "wearing a sharp formal business suit: well-tailored navy or charcoal "
        "two-piece suit, crisp white shirt, simple necktie (for men) or "
        "tailored blouse (for women), polished leather shoes"
    ),
    "casual": (
        "wearing trendy Reiwa-era (2020s contemporary Japanese) casual fashion: "
        "modern relaxed silhouette, neutral or earth-tone palette, oversized "
        "T-shirt or knit with wide-leg pants or pleated skirt, white sneakers, "
        "minimal accessories, urban Tokyo street style"
    ),
    "loungewear": (
        "wearing comfortable home loungewear: soft cotton or fleece pullover "
        "and matching loose pants in muted pastel or beige tones, plain "
        "house slippers, relaxed at-home look"
    ),
    "office": (
        "wearing smart business casual office attire: neat collared shirt or "
        "blouse with chinos or knee-length skirt, light cardigan or blazer, "
        "clean leather loafers, polished but not formal"
    ),
}


# ─── 共通スタイル指示 ────────────────────────────────────────────
STYLE_PROMPT = (
    "Pixar-style 3D animated character, high-quality computer graphics, "
    "soft cinematic lighting, smooth subsurface skin shading, "
    "expressive but neutral facial expression, "
    "full body shot from head to toe, facing camera directly, "
    "standing upright in a natural relaxed pose with arms at sides, "
    "plain solid pale gray background (#EDEDED), studio portrait composition, "
    "vertical 9:16 portrait aspect ratio, no text, no logo, no watermark"
)


def _build_prompt(spec: CharSpec, wardrobe_prompt: str) -> str:
    """1 キャラ × 1 wardrobe の prompt を組み立てる。"""

    return (
        f"A {spec.age_range} Japanese {spec.gender} character, "
        f"{spec.personality}. "
        f"Face: {spec.face}. "
        f"Hair: {spec.hair}. "
        f"Body: {spec.body}. "
        f"Outfit: {wardrobe_prompt}. "
        f"{STYLE_PROMPT}"
    )


def _generate_one(
    spec: CharSpec, wardrobe: str, *, reference: Path | None
) -> Path:
    """1 枚生成して characters/<id>/<wardrobe>.png に保存。"""

    out = CHARACTERS_DIR / spec.id / f"{wardrobe}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    prompt = _build_prompt(spec, WARDROBE_PROMPTS[wardrobe])
    refs = [str(reference)] if reference else None

    t0 = time.time()
    print(f"  [{spec.id}/{wardrobe}] generating "
          f"(ref={'yes' if refs else 'no'})... ", end="", flush=True)
    imagen_client.generate_image(
        prompt=prompt,
        output_path=str(out),
        aspect_ratio="9:16",
        reference_images=refs,
    )
    dt = time.time() - t0
    print(f"done {dt:.1f}s → {out.relative_to(ROOT)}")
    return out


def regenerate_character(spec: CharSpec, *, only_wardrobe: str | None) -> None:
    """1 キャラの全 wardrobe (or 指定 1 つ) を再生成。"""

    print(f"\n=== {spec.id} ({spec.gender}, {spec.age_range}) ===")

    # base.png を先に生成 (= reference 無し、text-only)。残り wardrobes の
    # face/hair/body の anchor になる
    base_path = CHARACTERS_DIR / spec.id / "base.png"
    if only_wardrobe is None or only_wardrobe == "base":
        _generate_one(spec, "base", reference=None)

    if not base_path.exists():
        # 部分再生成で base 無しの場合 fail-fast
        raise RuntimeError(
            f"{base_path} が存在しません。先に --wardrobe base で生成してください。"
        )

    for wardrobe in ("suit", "casual", "loungewear", "office"):
        if only_wardrobe is not None and only_wardrobe != wardrobe:
            continue
        _generate_one(spec, wardrobe, reference=base_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", choices=[c.id for c in CHARS],
                    help="1 キャラだけ再生成 (= debug 用)")
    ap.add_argument("--wardrobe",
                    choices=["base", "suit", "casual", "loungewear", "office"],
                    help="1 wardrobe だけ再生成 (= debug 用)")
    args = ap.parse_args()

    targets = [c for c in CHARS if args.char is None or c.id == args.char]
    total = len(targets) * (5 if args.wardrobe is None else 1)
    print(f"target: {len(targets)} chars × {total // len(targets)} wardrobes "
          f"= {total} images")

    t0 = time.time()
    for spec in targets:
        regenerate_character(spec, only_wardrobe=args.wardrobe)
    print(f"\n✅ 完了: {total} images / {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
