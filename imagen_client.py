import logging
import time

from PIL import Image
from google import genai
from google.genai import types

import config
import io_utils

logger = logging.getLogger(__name__)

MODEL = "gemini-3-pro-image-preview"
REQUEST_TIMEOUT_SEC = 120
MAX_RETRIES = 2
BACKOFF_SECONDS = (5, 15)


def _is_portrait(image_path: str) -> bool:
    img = Image.open(image_path)
    return img.size[0] <= img.size[1]


def _read_reference_parts(reference_images: list[str] | None) -> list:
    if not reference_images:
        return []
    parts = []
    for ref_path in reference_images:
        with open(ref_path, "rb") as f:
            data = f.read()
        mime = "image/png" if ref_path.lower().endswith(".png") else "image/jpeg"
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    return parts


def generate_image(prompt: str, output_path: str, aspect_ratio: str = "9:16",
                   reference_images: list[str] | None = None) -> None:
    client = genai.Client(api_key=config.GOOGLE_API_KEY)

    ref_parts = _read_reference_parts(reference_images)
    if ref_parts:
        instruction = (
            "Generate a vertical portrait image (taller than wide, 9:16 ratio) "
            "using the attached reference image(s) as the character appearance. "
            "Preserve the characters' faces and clothing from the references. "
            f"Scene: {prompt}"
        )
        contents = ref_parts + [instruction]
    else:
        contents = f"Generate a vertical portrait image (taller than wide, 9:16 ratio): {prompt}"

    response = None
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    imageConfig=types.ImageConfig(
                        aspectRatio=aspect_ratio,
                    ),
                    http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_SEC * 1000),
                ),
            )
            break
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = io_utils.next_backoff_seconds(attempt, list(BACKOFF_SECONDS))
                logger.warning(
                    "imagen API失敗 (attempt %d): %s → %.1f秒後 retry",
                    attempt + 1, str(e)[:120], wait,
                )
                time.sleep(wait)
            else:
                raise RuntimeError(f"imagen API failed after {MAX_RETRIES + 1} attempts: {e}") from e

    candidates = response.candidates or []
    if not candidates or not candidates[0].content or not candidates[0].content.parts:
        raise RuntimeError("画像が生成されませんでした（コンテンツポリシー等）")

    for part in candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
            io_utils.atomic_write_bytes(output_path, part.inline_data.data)

            if _is_portrait(output_path):
                return

            img = Image.open(output_path)
            w, h = img.size
            crop_w = int(h * 9 / 16)
            left = (w - crop_w) // 2
            cropped = img.crop((left, 0, left + crop_w, h))
            tmp = output_path + ".crop.tmp"
            cropped.save(tmp)
            import os as _os
            _os.replace(tmp, output_path)
            return

    raise RuntimeError("画像が生成されませんでした")
