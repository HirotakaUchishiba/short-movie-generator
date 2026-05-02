import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

ANALYZER_MODEL = os.getenv("ANALYZE_MODEL", "claude-opus-4-7")
MAX_TOKENS = int(os.getenv("ANALYZE_MAX_TOKENS", "32000"))

SYSTEM_PROMPT = """あなたはショート動画の台本リバースエンジニアリングの専門家です。
与えられた動画フレーム画像・音声文字起こし・音響特徴から、以下のスキーマに厳密に従うJSON台本を生成してください。

# 出力スキーマ（必ずこの構造で返す）
{
  "caption": "SNS投稿用キャプション本文（ハッシュタグ含む、\\nで改行可）",
  "audio_mode": "voiced" | "silent",
  "wardrobe_continuity": {
    "<identifier>": "服装の自然言語記述（同じidentifierは複数シーンで同じ服装）"
  },
  "scenes": [
    {
      "label": "シーンの日本語ラベル（例 \"起床\"、省略可）",
      "duration": シーン秒数 (number >= 3),
      "background_prompt": "Imagen用の日本語背景プロンプト + 英語スタイル修飾",
      "animation_prompt": "Kling V3用の英語アニメーションプロンプト（シーン全体の動き）",
      "character_refs": ["characters/<name>.png のキー（単数キャラはこれだけ書く、多人数なら scene.characters[] と並用）"],
      "characters": [
        {
          "name": "主人公|相手|...",
          "role": "narrator|customer|boss|colleague など"
        }
      ],
      "wardrobe": {
        "identifier": "wardrobe_continuity に書いたID（実際の服装説明は continuity 側に1度だけ書く）"
      },
      "lines": [
        {
          "speaker": "scenes[].characters[].name と完全一致 (例: \"主人公\" / \"上司\")。複数キャラのシーンでは必ず指定、単一キャラのシーンでは省略可",
          "text": "セリフ（ASCII , . 禁止、全角OK）",
          "start": シーン内相対秒,
          "end": シーン内相対秒 (> start),
          "emotion": "驚き|喜び|焦り|落胆|中立|満足|困惑|怒り|恥ずかしさ など1語",
          "delivery": "話し方の描写（例 \"かすれ声で早口、語尾跳ね上がり\"）。短く具体的に",
          "acoustic": {
            "pitch_trend": "rising|falling|flat",
            "rms_peak": 0.0-1.0,
            "wpm": 数値
          },
          "rate": "TTS速度 (+N% or -N%、任意)",
          "pronunciation_hints": {"原文": "カタカナ読み"}
        }
      ]
    }
  ]
}

# 重要な制約
- scenes[].duration は最低3秒（Kling V3の最短尺）
- lines[].start/end はシーン内相対秒、end > start かつ end <= scene.duration
- lines[].text は ASCII の , と . を含めない（全角は可）
- background_prompt は **被写体 + 物理的な場所** だけを日本語で記述する。lighting / cinematic / style 修飾語 / "single moment in time" 等の制約文は **絶対に含めない** (composer が emotion から派生してこれらを後付けする。テキスト二重指定を避けるため)
- animation_prompt は英語で、そのシーンの動き全体を1文で表現 (lighting/camera 修飾は含めない、composer が emotion から付与)
- emotion は単語1つ。複合感情は主要なものを選ぶ
- 各シーンは1本のKlingクリップで生成される。ショット境界情報は scene 分割の参考にする
- background_prompt は **1瞬の静止画** として記述すること。動作の時系列（"wakes up then checks phone"）は含めない。Klingアニメーションは animation_prompt で別途扱う。Imagenがコマ割り（複数パネル）を出力するのを防ぐため、必ず "single moment in time" として書く
- pronunciation_hints は読み間違えやすい漢字・複合語・略語に対して必ず付ける（例: "納期間に"→"のうきまに", "IT"→"アイティー", "営業時間外"→"えいぎょうじかんがい"）。下記の既知辞書にあるものは省略可（同じ読みなら）
- **SSOT原則**: 同じ情報を複数フィールドに書かない。具体的に:
  - 服装: wardrobe_continuity[id] に1度だけ自然言語で書き、scenes[].wardrobe.identifier はその ID を参照するだけ。scenes[].wardrobe に top/bottom/accessories/hair などを書かない
  - キャラ参照画像: scenes[].character_refs にだけ書く。scenes[].characters[].ref は使わない
  - 表情: lines[].emotion で表現する。scenes[].facial_expression は廃止 (使わない)
  - 動き: lines[].emotion で表現する。scenes[].hand_gesture は廃止 (シーン固有の物理動作は animation_prompt 本文に書く)
  - 多人数キャラの服装: scene.characters[].outfit は廃止。各キャラごとに wardrobe_continuity を立てて scenes[].wardrobe.identifier で参照する
- **複数キャラの話者識別**: 1 つのシーンに 2 人以上の characters[] を置く場合、各 lines[] に speaker を必ず指定する (フレーム画像から「今このセリフは誰が口を動かして発しているか」を判定する)。単一キャラのシーンでは speaker を省略してよい (主人公の発言とみなす)。誰が話しているか不明な場合は speaker を省略する (推測で別キャラ名を入れない)
- 指示以外の説明・コメントは一切出力しない。純粋なJSONのみ返す（コードフェンス禁止）

# 参考情報の活用
各frame_Nの画像は動画の0秒目から0.5秒刻み (frame_0 = 0.0s, frame_1 = 0.5s, frame_2 = 1.0s, ...)。
Whisperのtranscriptはword単位タイムスタンプ付き。librosaの音響特徴は各transcript segmentに対応。
"""


def _encode_image(path: str) -> dict:
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("ascii")
    media_type = "image/jpeg"
    if path.lower().endswith(".png"):
        media_type = "image/png"
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": data,
        },
    }


def _format_transcript_block(transcript: dict, phrase_features: list[dict]) -> str:
    lines = ["# Whisper transcript (word-level timestamps)"]
    lines.append(f"全体テキスト: {transcript.get('text', '').strip()}")
    lines.append(f"動画尺: {transcript.get('duration', 0):.2f}秒")
    lines.append("")
    lines.append("## Segments")
    for i, seg in enumerate(transcript.get("segments", [])):
        feat = phrase_features[i] if i < len(phrase_features) else {}
        feat_str = (f" trend={feat.get('pitch_trend', 'flat')} "
                    f"rms_peak={feat.get('rms_peak', 0):.2f}") if feat else ""
        lines.append(f"- [{seg['start']:.2f}-{seg['end']:.2f}] {seg['text']}{feat_str}")
    lines.append("")
    lines.append("## Words")
    words_str = ", ".join(
        f"[{w['start']:.2f}] {w['word']}"
        for w in transcript.get("words", [])[:200]
    )
    lines.append(words_str)
    return "\n".join(lines)


def build_screenplay(
    *,
    frame_paths: list[str],
    transcript: dict,
    phrase_features: list[dict],
    source_video_path: str,
    api_key: str | None = None,
    extra_instructions: str | None = None,
    frame_interval_sec: float = 0.5,
    known_furigana: dict[str, str] | None = None,
) -> dict:
    """Claude Opus 4.7 を呼んでscreenplay JSONを生成する。"""
    import anthropic

    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY未設定")

    client = anthropic.Anthropic(api_key=key)

    content: list[dict] = []

    content.append({
        "type": "text",
        "text": (
            f"# 入力情報\n"
            f"- 動画ファイル: {os.path.basename(source_video_path)}\n"
            f"- フレーム数: {len(frame_paths)} ({frame_interval_sec:.2f}秒刻み、frame_0=0.0s)\n"
        ),
    })

    for i, path in enumerate(frame_paths):
        t = i * frame_interval_sec
        content.append({"type": "text", "text": f"frame_{i} (t={t:.2f}s):"})
        content.append(_encode_image(path))

    content.append({
        "type": "text",
        "text": _format_transcript_block(transcript, phrase_features),
    })

    extra_blocks: list[str] = []
    if known_furigana:
        sample = "\n".join(
            f'  "{k}": "{v}"'
            for k, v in list(known_furigana.items())[:200]
        )
        extra_blocks.append(
            f"# 既知のふりがな辞書（{len(known_furigana)}件）\n"
            f"以下の単語は既にシステムが読み方を知っているので、同じ読みであれば\n"
            f"pronunciation_hints に再度入れる必要はない。違う読みにしたい場合のみ追加。\n"
            f"```json\n{{\n{sample}\n}}\n```"
        )

    if extra_blocks:
        content.append({"type": "text", "text": "\n\n".join(extra_blocks)})

    extra = ""
    if extra_instructions:
        extra = f"\n\n# 追加の指示\n{extra_instructions}"

    content.append({
        "type": "text",
        "text": (
            "# タスク\n"
            "上記のフレーム画像とtranscript・音響特徴を統合的に解釈し、"
            "指定のJSONスキーマに従ったscreenplay JSONを1つだけ出力してください。\n"
            "- 映像の切り替わり目でシーンを分割する\n"
            "- 各lineの start/end は対応するシーンの開始からの相対秒\n"
            "- 各lineに emotion/delivery/acoustic を必ず埋める\n"
            "- JSON以外の文字は一切出力しない（前置き・コードフェンス・コメント禁止）"
            f"{extra}"
        ),
    })

    logger.info("Claude %s 呼び出し中 (frames=%d, max_tokens=%d, streaming)",
                ANALYZER_MODEL, len(frame_paths), MAX_TOKENS)

    text_chunks: list[str] = []
    usage_input: int | None = None
    usage_output: int | None = None

    with client.messages.stream(
        model=ANALYZER_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        for chunk in stream.text_stream:
            text_chunks.append(chunk)
        final = stream.get_final_message()
        usage = getattr(final, "usage", None)
        if usage:
            usage_input = getattr(usage, "input_tokens", None)
            usage_output = getattr(usage, "output_tokens", None)

    text = "".join(text_chunks).strip()

    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse error: %s\nresponse:\n%s", e, text[:2000])
        raise RuntimeError(f"Claude応答がJSON parse不能: {e}")

    if usage_input is not None or usage_output is not None:
        logger.info("Claude usage: input=%s output=%s", usage_input, usage_output)

    return parsed
