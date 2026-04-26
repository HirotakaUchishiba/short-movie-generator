import os

import config


def generate_post_captions(screenplay: dict, screenplay_name: str, output_path: str) -> str:
    os.makedirs(config.POST_CAPTIONS_DIR, exist_ok=True)

    title = os.path.splitext(os.path.basename(screenplay_name))[0]
    caption = screenplay.get("caption", "").strip()

    body = f"""# {title}

{caption}

## 動画ファイル

- `{output_path}`
"""

    caption_path = os.path.join(config.POST_CAPTIONS_DIR, f"{title}.md")
    with open(caption_path, "w") as f:
        f.write(body)

    return caption_path
