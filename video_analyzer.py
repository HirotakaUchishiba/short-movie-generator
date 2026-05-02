import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

ANALYZER_MODEL = os.getenv("ANALYZE_MODEL", "claude-opus-4-7")
MAX_TOKENS = int(os.getenv("ANALYZE_MAX_TOKENS", "32000"))

SYSTEM_PROMPT = """あなたはショート動画の台本リバースエンジニアリングの専門家です。
与えられた動画フレーム画像・音声文字起こし・音響特徴から、**動画の中身 (構成・セリフ・感情・話し方) だけを抽出した「抽象台本 JSON」** を生成してください。

ビジュアル要素 (背景・体勢・服装・キャラクター名・場所・カメラ距離・動き) は **絶対に出力しないでください**。これらはユーザーが別途 VideoStyle テンプレで定義し、後段の合成フェーズで自動的に注入されます。あなたのタスクはあくまで「中身」の抽象化です。

# 出力スキーマ (これだけが許容)
{
  "caption": "SNS投稿用キャプション本文 (\\nで改行可、ハッシュタグ含む)",
  "scenes": [
    {
      "duration": シーン秒数 (number >= 3),
      "lines": [
        {
          "speaker": "発話者名 (例: \"主人公\" / \"上司\")。複数キャラのシーンのみ。単一キャラなら省略",
          "text": "セリフ (ASCII , . 禁止、全角OK)",
          "start": シーン内相対秒,
          "end": シーン内相対秒 (> start),
          "emotion": "驚き|喜び|焦り|落胆|中立|満足|困惑|怒り|恥ずかしさ など1語",
          "emotion_intensity": "soft|normal|strong (任意)",
          "delivery": "話し方の自然言語記述 (例: \"早口で語尾跳ね上がり\")",
          "acoustic": {
            "pitch_trend": "rising|falling|flat",
            "rms_peak": 0.0-1.0,
            "wpm": 数値
          },
          "pronunciation_hints": {"原文": "カタカナ読み"}
        }
      ]
    }
  ]
}

# 絶対に出力しないフィールド (ビジュアル/環境系)
**以下のフィールドは出力スキーマに含めない**:
- scene 内: background_prompt / animation_prompt / characters / character_refs / wardrobe / location_ref / tags / label / lipsync / facial_expression / hand_gesture / emotion_cue_overrides
- root 内: wardrobe_continuity / location_continuity / scoped_augmentations / audio_mode / bgm_path / bgm_volume_db / title_overlay / subtitle_y_from_bottom / _analysis

これらは VideoStyle と Phase 3 の合成ロジックが担当します。あなたが推測で書くと「元動画の構図に縛られた台本」になり自由度が失われるので、必ず空白のままにしてください。

# 重要な制約
- scenes[].duration は最低 3 秒 (Kling V3 の最短尺)
- lines[].start/end はシーン内相対秒、end > start かつ end <= scene.duration
- lines[].text は ASCII の , と . を含めない (全角は可)
- emotion は単語 1 つ。複合感情は主要なものを選ぶ
- pronunciation_hints は読み間違えやすい漢字・複合語・略語に対して必ず付ける (例: "納期間に"→"のうきまに", "IT"→"アイティー")。下記の既知辞書にあるものは省略可
- **pronunciation_hints は必ず lines[].pronunciation_hints の位置に書く** (scene 直下に scene.pronunciation_hints と書かない)。同じ読みを複数の line で繰り返してよい
- **複数キャラの speaker 識別**: フレーム画像から「誰が口を動かしているか」「誰が画面に映っているか」で判別し、各 lines[] に speaker を文字列で指定 (例: "主人公" / "上司")。単一キャラの動画なら speaker は完全に省略する。誰が話しているか不明なら推測で別キャラ名を入れず省略する
- 指示以外の説明・コメントは一切出力しない。純粋な JSON のみ返す (コードフェンス禁止)

# 参考情報の活用
各 frame_N の画像は動画の 0 秒目から 0.5 秒刻み (frame_0 = 0.0s, frame_1 = 0.5s, ...)。
Whisper transcript は word 単位タイムスタンプ付き。librosa の音響特徴は各 transcript segment に対応。
これらを統合的に判断して、台本の **中身だけ** を抽出する (絵作り・構図・服装は無視)。
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
