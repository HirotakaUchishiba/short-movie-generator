import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

ANALYZER_MODEL = os.getenv("ANALYZE_MODEL", "claude-opus-4-7")
MAX_TOKENS = int(os.getenv("ANALYZE_MAX_TOKENS", "32000"))

SYSTEM_PROMPT = """あなたはショート動画の台本リバースエンジニアリングの専門家です。
与えられた動画フレーム画像・音声文字起こし・音響特徴から、**動画の中身 (構成・セリフ・感情・話し方) だけを抽出した「抽象台本 JSON」** を生成してください。

自由記述のビジュアル要素 (背景プロンプト・体勢・服装・動き)、**プラットフォーム UI 要素** (TikTok / Instagram / YouTube Shorts のハンドル名・いいね・コメント・ウォーターマーク)、**キャスティングの意味づけ** (主人公/上司/先輩のような役割ラベル) は **絶対に出力しないでください**。character_selection / animation_style はユーザーが Stage 1 UI で per-scene に注入します。あなたのタスクは「中身」の抽象化に加えて、(1) "# 利用可能な location 集合" が提供されていれば各 scene の location_ref / camera_distance を選定し、(2) "# 利用可能な character 集合" が提供されていれば featured_characters と各 line の speaker (= resolved id) を割り当てることです (= 下記ルール参照)。提案系フィールドはユーザーが Stage 1 UI で訂正できます。プラットフォーム UI 要素は元動画固有の overlay で、生成動画には絶対に含めてはいけないため caption / text / 説明文のいずれにも反映しないでください。

# 出力スキーマ (これだけが許容)
{
  "caption": "SNS投稿用キャプション本文 (\\nで改行可、ハッシュタグ含む)",
  "hook_id": "(任意) 動画冒頭のフックパターン id。入力 user content に \"# 利用可能な atomic 集合\" が提供されている場合のみ出力。提供されていなければ完全に省略する",
  "arc_id": "(任意) シーン進行の感情変化テンプレ id。同上 (atomic 集合が提供されているときのみ)",
  "featured_characters": ["(任意) \"# 利用可能な character 集合\" が提供されている場合のみ出力。動画に登場させる resolved id の配列"],
  "scenes": [
    {
      "action_id": "(任意) 動作テンプレ id。atomic 集合が提供されている場合は必ず各 scene に指定する。提供されていなければ省略",
      "location_ref": "(任意) locations/ カタログのキー。入力に \"# 利用可能な location 集合\" が提供されている場合は必ず各 scene に指定する。提供されていなければ省略",
      "camera_distance": "(任意) close-up|medium-close|medium|wide のいずれか。location 集合が提供されている場合は必ず各 scene に指定する。提供されていなければ省略",
      "annotation": {
        "visual_intent_id": "(任意) intent catalog の id。入力 user content に \"# 利用可能な visual intent 集合\" が提供されている場合のみ出力。集合に無い id は禁止 (= 自動で null に降格される)。良い match が無いシーンは null を入れて novel intent 候補としてオペレータに提示する",
        "confidence": "(任意) visual_intent_id の確信度 0.0-1.0。記録用 (= 自動降格には使わない)。visual_intent_id を出した場合は必ず confidence も付ける",
        "duration_bucket": "(任意) シーン長のバケット。5 (= 短尺) または 10 (= 標準)。視聴尺の感覚で選ぶ",
        "motion_intensity": "(任意) 動きの強度。low / medium / high のいずれか。話しているだけ = low、ジェスチャ多い = medium、激しい身振り = high",
        "rationale": "(任意) visual_intent_id を選んだ理由 1 行。null の場合は「なぜ既存 catalog にマッチしないか」を書く"
      },
      "lines": [
        {
          "speaker": "(任意) character catalog から選んだ resolved id (= 例: 'f1__office' or 'f1')。character 集合が提供されない場合は省略",
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

# atomic id 出力ルール
入力 user content に "# 利用可能な atomic 集合" セクションが含まれている場合:
- hook_id / arc_id / scenes[].action_id は **その集合から必ず id を選んで出力すること**
- 新規 id を作らない (= ない id を出力するとパイプラインで reject される)
- arc_id の emotion_sequence と各 scene の lines emotion 列が概ね一致するよう scene 数と emotion を選ぶ
- hook_id の first_scene_action_id は 1 番目の scene の action_id の推奨値 (= 強制ではないが、合っていれば cache hit 率が上がる)
- 各 action は compatible_locations を持つ。元動画の場面と整合する location を許容する action を優先する
集合が提供されていない場合は、これら 3 フィールド (hook_id / arc_id / scenes[].action_id) を完全に省略する (= 旧挙動互換)。

# location 出力ルール
入力 user content に "# 利用可能な location 集合" セクションが含まれている場合:
- scenes[].location_ref は **その集合から必ず id を 1 つ選んで出力すること**
- 新規 id を作らない (= ない id を出力するとパイプラインで最近傍に矯正される)
- 元動画の各シーンの場面 (室内/屋外・家具・照明・雰囲気) に **最も近い** ロケを catalog の decor / lighting / color_palette / props から判断して選ぶ
- scenes[].camera_distance は被写体の寄り引き (顔のみ=close-up / 胸〜顔=medium-close / 腰〜顔=medium / 全身=wide) を元動画から判断して close-up|medium-close|medium|wide のいずれかを出力する
集合が提供されていない場合は、location_ref / camera_distance を完全に省略する (= 旧挙動互換)。

# casting (= line.speaker / featured_characters) 出力ルール
入力 user content に "# 利用可能な character 集合" セクションが含まれている場合のみ casting を割り当てる:
- **各 line の speaker は resolved id を直書きする** (= `"f1__office"` や `"f1"` 等)。匿名 `speaker_N` 形式は禁止 (= validator で reject される)
- catalog 内の base を **alphabetical 順に割当てる** (= 1 人目 → 1 番目の base、2 人目 → 2 番目の base、…)。参考動画の登場人物に寄せる必要は無い (= 台本作成時に Stage 1 UI で人間が自由に選び直す前提)
- **distinct character rule**: 異なる発話者には異なる **base** を割り当てる (= 同じ base を 2 人の speaker にマッピングしない)
- **wardrobe-by-location rule**: resolved id (= `<base>__<wardrobe>`) の wardrobe を選ぶときは、その speaker が登場する主要シーンの location の `recommended_wardrobes` から選ぶ。location 集合の各 entry に `recommended_wardrobes` がある場合に適用 (= 適合する wardrobe が character の refs に存在しないなら別の wardrobe で良い)
- featured_characters: 動画に登場させる resolved id の配列。全 line の speaker 値を含む和集合
- **catalog の refs に無い id は出力しない** (= パイプラインで drop される)
- 単一人物の動画 (= 全 line を同一人物が話している) では全 line に同じ speaker を割り当てる
character 集合が提供されていない場合は featured_characters と line.speaker を完全に省略する (= 旧挙動互換)。

# 絶対に出力しないフィールド (自由記述ビジュアル系・Stage 1 UI で注入 or compose で派生)
**以下のフィールドは出力スキーマに含めない**:
- scene 内: background_prompt / animation_prompt / animation_style / characters / character_refs / character_selection / tags / lipsync
- root 内: subtitle_y_from_bottom

これらは Stage 1 UI でユーザーがシーン別に注入するか、compose で派生されます。推測で書くと「元動画の構図に縛られた台本」になり自由度が失われるので、必ず空白のままにしてください。

# 重要な制約
- lines[].start/end はシーン内相対秒、end > start
- lines[].text は ASCII の , と . を含めない (全角は可)
- emotion は単語 1 つ。複合感情は主要なものを選ぶ
- pronunciation_hints は読み間違えやすい漢字・複合語・略語に対して必ず付ける (例: "納期間に"→"のうきまに", "IT"→"アイティー")。下記の既知辞書にあるものは省略可
- **pronunciation_hints は必ず lines[].pronunciation_hints の位置に書く** (scene 直下に scene.pronunciation_hints と書かない)。同じ読みを複数の line で繰り返してよい
- **複数人物の speaker 識別 (= resolved id 直書き方式)**:
  - フレーム画像から「誰が口を動かしているか」「誰が画面に映っているか」で人物を判別
  - 同じ人物には動画全体で同じ resolved id を一貫して振る (例: 服装・髪型・体型・声質が同じなら同一人物とみなす)
  - character 集合の base を alphabetical 順で使う (= 1 人目 = base[0]、2 人目 = base[1]、…)
  - **役割語彙 (主人公/上司/先輩/友人/通行人など) は使わない**。catalog の resolved id のみ
  - character 集合が提供されない、または誰が話しているか不明な line では speaker を完全に省略する
- 指示以外の説明・コメントは一切出力しない。純粋な JSON のみ返す (コードフェンス禁止)

# 参考情報の活用
各 frame_N の画像は動画の 0 秒目から 0.5 秒刻み (frame_0 = 0.0s, frame_1 = 0.5s, ...)。
Whisper transcript は word 単位タイムスタンプ付き。librosa の音響特徴は各 transcript segment に対応。
これらを統合的に判断して、台本の **中身だけ** を抽出する (絵作り・構図・服装・キャスティングは無視)。
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


class ScreenplayParseError(RuntimeError):
    """Claude 応答の JSON parse 失敗。``usage`` で課金分の input/output tokens を保持する。

    parse に失敗しても Claude 呼び出し自体は課金されているため、上位は
    例外を catch して ``usage`` を recorder に渡す責務を持つ。
    """

    def __init__(self, message: str, *, usage: dict | None = None) -> None:
        super().__init__(message)
        self.usage: dict = dict(usage or {})


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
    atomic_menu: dict | None = None,
    intent_catalog: list | None = None,
    location_catalog: list | None = None,
    character_catalog: list | None = None,
) -> tuple[dict, dict]:
    """Claude Opus 4.7 を呼んでscreenplay JSONを生成する。

    Args:
        atomic_menu: Phase X-2b で導入。``atomic_assets.build_prompt_menu()``
            の戻り値と同じ ``{"actions": [...], "hooks": [...], "arcs": [...]}``
            形式を渡すと、user content に "# 利用可能な atomic 集合" セクションが
            注入され Claude は hook_id / arc_id / scenes[].action_id を必ずその
            集合から選んで出力する。``None`` (既定) なら旧挙動 (= atomic id を
            出力させない)。
        location_catalog: ``analyze.location.build_location_catalog()`` の戻り値
            (= ロケ dict の list)。渡すと user content に "# 利用可能な location
            集合" セクションが注入され、Claude は scenes[].location_ref /
            camera_distance をその集合から選んで出力する。後処理で catalog に
            無い location_ref は最近傍に矯正、enum 外の camera_distance は
            drop する。``None`` / 空 list なら旧挙動 (= location を出力させない)。
        intent_catalog: Step 1 (analyze annotation 注入) で導入。
            ``intent_resolver.load_intent_catalog()`` の戻り値 (= IntentEntry の
            list) を渡すと user content に "# 利用可能な visual intent 集合"
            セクションが注入され、Claude は scenes[].annotation を出力する。
            出力された annotation は best-effort で populate される (= Phase 4):
            未知 id / enum 外の値は当該 field のみ None に降格し、annotation
            自体は残す。全 field が None になった場合のみ annotation key を削除。
            ``None`` (既定) なら annotation を要求しない (= 旧挙動互換)。
        character_catalog: ``character_meta.build_character_catalog()`` の戻り値
            (= ``{"id", "appearance", "refs"}`` dict の list)。渡すと user
            content に "# 利用可能な character 集合" セクションが注入され、Claude
            は catalog の base から順番に featured_characters / speaker_to_ref
            を **提案** する (= 参考動画に寄せない、Stage 1 UI で人間が選び直す
            前提。2026-05-17 方針変更)。後処理で catalog の refs に無い ref は
            drop され、欠落 speaker は alphabetical 順で補完される。
            ``None`` / 空 list なら casting 提案を要求しない (= speaker_profiles
            のみ出力、旧挙動互換)。

    Returns:
        (screenplay_dict, usage_dict)
        usage_dict は ``{"input_tokens": int | None, "output_tokens": int | None}``。
        コスト記録は呼び出し側 (analyze/runner) で recorder に渡す。
    """
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

    if atomic_menu and any(
        atomic_menu.get(k) for k in ("actions", "hooks", "arcs")
    ):
        actions_json = json.dumps(
            atomic_menu.get("actions") or [], ensure_ascii=False, indent=2,
        )
        hooks_json = json.dumps(
            atomic_menu.get("hooks") or [], ensure_ascii=False, indent=2,
        )
        arcs_json = json.dumps(
            atomic_menu.get("arcs") or [], ensure_ascii=False, indent=2,
        )
        extra_blocks.append(
            "# 利用可能な atomic 集合\n"
            "以下の id 集合から hook_id / arc_id / scenes[].action_id を必ず "
            "1 つずつ選んで出力すること。新規 id を生成すると pipeline で "
            "reject される。\n\n"
            f"## actions\n```json\n{actions_json}\n```\n\n"
            f"## hooks\n```json\n{hooks_json}\n```\n\n"
            f"## arcs\n```json\n{arcs_json}\n```"
        )

    if intent_catalog:
        # 遅延 import: intent_resolver は SSOT loader を経由するため、analyze
        # 関連 import を最小限に保ち module-level の循環を避ける。
        from analyze.intent_resolver import format_catalog_for_prompt

        catalog_text = format_catalog_for_prompt(intent_catalog)
        extra_blocks.append(
            "# 利用可能な visual intent 集合\n"
            "以下から scenes[].annotation.visual_intent_id を選んで出力する "
            "こと。良い match が無いシーンは null を入れる "
            "(= 新規 intent 候補としてオペレータレビューに回る)。\n\n"
            f"{catalog_text}"
        )

    if location_catalog:
        location_json = json.dumps(
            location_catalog, ensure_ascii=False, indent=2,
        )
        extra_blocks.append(
            "# 利用可能な location 集合\n"
            "以下の id 集合から scenes[].location_ref を必ず 1 つずつ選んで "
            "出力すること。元動画の各シーンの場面に最も近いロケを decor / "
            "lighting / color_palette / props から判断する。新規 id は作らない。"
            "あわせて scenes[].camera_distance も出力する。\n\n"
            f"```json\n{location_json}\n```"
        )

    if character_catalog:
        character_json = json.dumps(
            character_catalog, ensure_ascii=False, indent=2,
        )
        extra_blocks.append(
            "# 利用可能な character 集合\n"
            "この集合の base を alphabetical 順に使って各 line の speaker "
            "(= resolved id) と featured_characters (= 登場させる resolved id "
            "の配列) を割り当てること。id は各 entry の refs から選ぶ (= refs "
            "に無い id は drop される)。匿名 speaker_N 形式の出力は禁止 (= "
            "validator で reject される)。\n\n"
            f"```json\n{character_json}\n```"
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

    # Claude 呼び出しは parse 成否に関わらず課金される。usage を例外に
    # 同梱し、上位 (analyze/pipeline) が recorder に渡せるようにする。
    usage_dict = {"input_tokens": usage_input, "output_tokens": usage_output}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse error: %s\nresponse:\n%s", e, text[:2000])
        raise ScreenplayParseError(
            f"Claude応答がJSON parse不能: {e}", usage=usage_dict
        )

    if usage_input is not None or usage_output is not None:
        logger.info("Claude usage: input=%s output=%s", usage_input, usage_output)

    # ── annotation 正規化 (= intent_catalog が渡された時のみ) ──
    # Phase 4: annotation は **常時 best-effort populate**。confidence による
    # 全削除は廃止し、個別 field が invalid (= catalog に無い id / enum 外) の
    # ときだけその field を None にする。全 field が None になった場合のみ
    # annotation key を削除する (= 空 annotation は残さない)。
    if intent_catalog:
        valid_ids = {e.id for e in intent_catalog}

        for s_idx, scene in enumerate(parsed.get("scenes") or []):
            if not isinstance(scene, dict):
                continue
            raw_ann = scene.get("annotation")
            if not isinstance(raw_ann, dict):
                continue

            normalized: dict = {}

            intent_id = raw_ann.get("visual_intent_id")
            if isinstance(intent_id, str) and intent_id:
                if intent_id in valid_ids:
                    normalized["visual_intent_id"] = intent_id
                else:
                    logger.info(
                        "[annotation] scene %d: unknown visual_intent_id "
                        "'%s' demoted to None",
                        s_idx, intent_id,
                    )
                    normalized["visual_intent_id"] = None
            else:
                normalized["visual_intent_id"] = None

            dur = raw_ann.get("duration_bucket")
            if isinstance(dur, int) and not isinstance(dur, bool) and dur in (5, 10):
                normalized["duration_bucket"] = dur
            else:
                normalized["duration_bucket"] = None

            motion = raw_ann.get("motion_intensity")
            if isinstance(motion, str) and motion in ("low", "medium", "high"):
                normalized["motion_intensity"] = motion
            else:
                normalized["motion_intensity"] = None

            if all(v is None for v in normalized.values()):
                scene.pop("annotation", None)
                logger.info(
                    "[annotation] scene %d: all fields None, removed "
                    "annotation key",
                    s_idx,
                )
            else:
                scene["annotation"] = normalized

    # ── location_ref / camera_distance 正規化 (= location_catalog 提供時のみ) ──
    # analyze が SSOT として常に valid な location_ref を産出する責務を負う。
    # catalog に無い id は最近傍 (= 先頭) に矯正して compose の fail-fast を防ぐ。
    # camera_distance は enum 外なら drop し _derive_identity の fallback に委ねる。
    if location_catalog:
        valid_locs = [
            loc["id"] for loc in location_catalog
            if isinstance(loc, dict) and isinstance(loc.get("id"), str)
        ]
        valid_loc_set = set(valid_locs)
        fallback_loc = valid_locs[0] if valid_locs else None
        valid_cams = ("close-up", "medium-close", "medium", "wide")

        for s_idx, scene in enumerate(parsed.get("scenes") or []):
            if not isinstance(scene, dict):
                continue
            ref = scene.get("location_ref")
            if not (isinstance(ref, str) and ref in valid_loc_set):
                if fallback_loc is not None:
                    logger.info(
                        "[location] scene %d: location_ref '%s' を catalog "
                        "最近傍 '%s' に矯正", s_idx, ref, fallback_loc,
                    )
                    scene["location_ref"] = fallback_loc
                else:
                    scene.pop("location_ref", None)
            cam = scene.get("camera_distance")
            if not (isinstance(cam, str) and cam in valid_cams):
                scene.pop("camera_distance", None)

    # ── speaker_profiles / speaker_to_ref を撤廃 (= 2026-05-17 schema 撤廃) ──
    # 旧出力との後方互換のため、Claude が誤って出した場合は単に drop する。
    parsed.pop("speaker_profiles", None)
    parsed.pop("speaker_to_ref", None)

    # ── casting 正規化 (= character_catalog 提供時のみ) ──
    # line.speaker は resolved id を直書きさせ、catalog の refs に無い id は drop。
    # 旧 raw `speaker_N` 形式が紛れていれば drop する (= 後方互換)。
    if character_catalog:
        valid_refs: set[str] = set()
        for entry in character_catalog:
            if isinstance(entry, dict):
                for ref in entry.get("refs") or []:
                    if isinstance(ref, str):
                        valid_refs.add(ref)

        # 各 line.speaker を validate: resolved id でなければ drop
        dropped_count = 0
        used_refs: list[str] = []  # featured_characters 用 (= 出現順)
        for sc in parsed.get("scenes") or []:
            if not isinstance(sc, dict):
                continue
            for ln in sc.get("lines") or []:
                if not isinstance(ln, dict):
                    continue
                spk = ln.get("speaker")
                if spk is None:
                    continue
                if (isinstance(spk, str) and spk in valid_refs):
                    if spk not in used_refs:
                        used_refs.append(spk)
                else:
                    # raw speaker_N や未知 ref は drop して None に降格
                    if isinstance(spk, str):
                        logger.info(
                            "[casting] line.speaker '%s' は catalog refs に "
                            "無いため drop", spk,
                        )
                    ln["speaker"] = None
                    dropped_count += 1
        if dropped_count:
            logger.info(
                "[casting] %d line の speaker を drop (= catalog 外 / raw 形式)",
                dropped_count,
            )

        # featured_characters: line.speaker から集めた refs + Claude の raw_feat
        # を和集合化、catalog 外は drop、出現順を維持
        final_feat: list[str] = list(used_refs)
        raw_feat = parsed.get("featured_characters")
        if isinstance(raw_feat, list):
            for ref in raw_feat:
                if (isinstance(ref, str) and ref in valid_refs
                        and ref not in final_feat):
                    final_feat.append(ref)
        if final_feat:
            parsed["featured_characters"] = final_feat
        else:
            parsed.pop("featured_characters", None)

    return parsed, usage_dict
