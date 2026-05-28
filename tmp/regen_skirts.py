"""f2, f3 の casual / suit をスカート版で再生成する ad-hoc script。

base.png を reference に渡して顔・髪・体型の一貫性を維持。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import imagen_client  # noqa: E402

# tmp/regenerate_characters.py と同じ CHARS 仕様を import
from regenerate_characters import CHARS, STYLE_PROMPT  # noqa: E402

CHARACTERS_DIR = ROOT / "characters"

# スカート版 wardrobe prompts (= suit / casual 共に skirt 強制)
SKIRT_PROMPTS: dict[str, str] = {
    "suit": (
        "wearing a sharp formal business suit with a knee-length pencil skirt: "
        "well-tailored navy or charcoal blazer, crisp white tailored blouse, "
        "matching knee-length pencil skirt (not pants), sheer neutral stockings, "
        "polished low-heel pumps"
    ),
    "casual": (
        "wearing trendy Reiwa-era (2020s contemporary Japanese) casual fashion "
        "with a skirt: relaxed oversized knit or tucked T-shirt paired with a "
        "long pleated midi skirt (not pants) in neutral or earth-tone color, "
        "white sneakers or simple flats, minimal accessories, urban Tokyo "
        "street style"
    ),
}

TARGETS = [("f3", "casual")]

# f3/casual を mini skirt 版で上書き
SKIRT_PROMPTS["casual"] = (
    "wearing trendy Reiwa-era (2020s contemporary Japanese) casual fashion "
    "with a mini skirt: relaxed oversized knit or tucked T-shirt paired with "
    "a short above-the-knee mini skirt (pleated or A-line) in neutral or "
    "earth-tone color, white sneakers or simple flats, sheer tights or bare "
    "legs, minimal accessories, urban Tokyo street style"
)


def _build_prompt(spec, wardrobe_prompt: str) -> str:
    return (
        f"A {spec.age_range} Japanese {spec.gender} character, "
        f"{spec.personality}. "
        f"Face: {spec.face}. "
        f"Hair: {spec.hair}. "
        f"Body: {spec.body}. "
        f"Outfit: {wardrobe_prompt}. "
        f"{STYLE_PROMPT}"
    )


def main() -> int:
    char_by_id = {c.id: c for c in CHARS}
    t0 = time.time()
    for char_id, wardrobe in TARGETS:
        spec = char_by_id[char_id]
        base = CHARACTERS_DIR / char_id / "base.png"
        out = CHARACTERS_DIR / char_id / f"{wardrobe}.png"
        prompt = _build_prompt(spec, SKIRT_PROMPTS[wardrobe])
        print(f"  [{char_id}/{wardrobe}] regenerating with skirt... ",
              end="", flush=True)
        t_start = time.time()
        imagen_client.generate_image(
            prompt=prompt,
            output_path=str(out),
            aspect_ratio="9:16",
            reference_images=[str(base)],
        )
        print(f"done {time.time() - t_start:.1f}s")
    print(f"\n✅ 完了: {len(TARGETS)} images / {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
