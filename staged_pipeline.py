import hashlib
import json
import logging
import os
import shutil
import threading
from datetime import datetime

import config
import io_utils
import preflight
import progress_store
import scene_gen
from compositor import compose_video, _apply_overlays, _merge_scenes
from post_captions_gen import generate_post_captions
from screenplay_validator import validate_screenplay

logger = logging.getLogger(__name__)


PROJECT_SCREENPLAY_FILENAME = "screenplay.json"
TTS_META_FILENAME = "tts_meta.json"

# snapshot に書き込まないフィールド (= TTS 派生で tts_meta.json が SSOT)
_TTS_DERIVED_SCENE_FIELDS = ("duration",)
_TTS_DERIVED_LINE_FIELDS = ("start", "end")


# project snapshot への書き込みを直列化する per-ts Lock。
# preview_server (REST patch) と scene_gen (TTS regen 後の duration 永続化) の
# 両方から取得して共有する。同時アクセスで disk 上の書き込みが混ざらないように。
_screenplay_locks: dict[str, threading.Lock] = {}
_screenplay_locks_guard = threading.Lock()


def screenplay_lock(name: str) -> threading.Lock:
    """per-key の書き込みロックを返す (テンプレ名 or ts_path どちらでも可)。"""
    with _screenplay_locks_guard:
        lk = _screenplay_locks.get(name)
        if lk is None:
            lk = threading.Lock()
            _screenplay_locks[name] = lk
        return lk


# ───────────────── テンプレ (新規 project 作成の素材) ─────────────────
# screenplays/<name>.json が **唯一の真実**。

def template_path(name: str) -> str:
    """`screenplays/<name>(.json)` を返す。拡張子省略可。"""
    base = config.SCREENPLAYS_DIR
    p = os.path.join(base, name)
    if os.path.exists(p):
        return p
    if not name.endswith(".json"):
        p2 = os.path.join(base, name + ".json")
        if os.path.exists(p2):
            return p2
    raise FileNotFoundError(
        f"台本テンプレが見つかりません: {os.path.join(base, name)}",
    )


def load_template(name: str) -> dict:
    """テンプレートを読み出す (= 新規 project 作成時の素材取得)。"""
    with open(template_path(name)) as f:
        return json.load(f)


def list_templates() -> list[str]:
    if not os.path.isdir(config.SCREENPLAYS_DIR):
        return []
    return sorted(
        f for f in os.listdir(config.SCREENPLAYS_DIR)
        if f.endswith(".json") and os.path.isfile(
            os.path.join(config.SCREENPLAYS_DIR, f),
        )
    )


# ───────────────── project snapshot (per-project immutable copy) ─────
# project 作成時に template から temp/<TS>/screenplay.json にコピーされる。
# 以後すべての stage / UI 編集 / 再合成は **このファイルだけ** を読み書きする。
# 別 project や別 analyze ジョブの操作からは隔離される。

def project_screenplay_path(ts_path: str) -> str:
    return os.path.join(ts_path, PROJECT_SCREENPLAY_FILENAME)


def tts_meta_path(ts_path: str) -> str:
    """Stage 2 (TTS) の派生 timing を保存する補助 SSOT のパス。
    フォーマット: ``{"scenes": [{"duration": float, "lines": [{"start": float,
    "end": float?}, ...]}, ...]}``。snapshot は完全 abstract に保つため、
    duration / start / end はここに分離する。"""
    return os.path.join(ts_path, TTS_META_FILENAME)


def load_tts_meta(ts_path: str) -> dict | None:
    """tts_meta.json を読み込む。無ければ None。"""
    p = tts_meta_path(ts_path)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_tts_meta(ts_path: str, meta: dict) -> None:
    """tts_meta.json を atomic に書き込む。"""
    os.makedirs(ts_path, exist_ok=True)
    p = tts_meta_path(ts_path)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _strip_tts_derived(abstract: dict) -> dict:
    """abstract dict から TTS 派生 timing (= scene.duration / line.start / line.end)
    を取り除いた deep copy を返す。snapshot に焼かないための filter。"""
    out: dict = {k: v for k, v in abstract.items() if k != "scenes"}
    new_scenes: list[dict] = []
    for scene in abstract.get("scenes") or []:
        if not isinstance(scene, dict):
            new_scenes.append(scene)
            continue
        next_scene = {
            k: v for k, v in scene.items()
            if k != "lines" and k not in _TTS_DERIVED_SCENE_FIELDS
        }
        new_lines: list[dict] = []
        for line in scene.get("lines") or []:
            if not isinstance(line, dict):
                new_lines.append(line)
                continue
            new_lines.append({
                k: v for k, v in line.items()
                if k not in _TTS_DERIVED_LINE_FIELDS
            })
        if "lines" in scene:
            next_scene["lines"] = new_lines
        new_scenes.append(next_scene)
    out["scenes"] = new_scenes
    return out


def _hydrate_tts_meta(screenplay: dict, meta: dict | None) -> dict:
    """compose 出力 (= TTS 派生 timing 抜き) に tts_meta.json の duration /
    start / end を notify-merge する。meta が無ければ screenplay をそのまま返す。
    """
    if not meta:
        return screenplay
    meta_scenes = meta.get("scenes") or []
    for s_idx, scene in enumerate(screenplay.get("scenes") or []):
        if s_idx >= len(meta_scenes):
            break
        m_scene = meta_scenes[s_idx] or {}
        if "duration" in m_scene:
            scene["duration"] = m_scene["duration"]
        m_lines = m_scene.get("lines") or []
        for l_idx, line in enumerate(scene.get("lines") or []):
            if l_idx >= len(m_lines):
                break
            m_line = m_lines[l_idx] or {}
            if "start" in m_line:
                line["start"] = m_line["start"]
            if "end" in m_line:
                line["end"] = m_line["end"]
    return screenplay


def load_project_abstract(ts_path: str) -> dict:
    """snapshot を生のまま読み込む (= 抽象台本)。UI 編集対象。
    snapshot は完全 abstract で TTS 派生 timing を含まない。"""
    with open(project_screenplay_path(ts_path)) as f:
        return json.load(f)


def load_project_screenplay(ts_path: str) -> dict:
    """完全 screenplay を返す。snapshot (= abstract) を読み、compose で派生
    フィールド (background_prompt / animation_prompt / character_refs /
    voice_overrides 等) を生成し、さらに tts_meta.json があれば
    duration / line.start / line.end を hydrate する。Stage 2 以降が読む。

    compose の出力が composed 形式 (= background_prompt 必須) を満たすかは
    呼び出し側で `validate_screenplay(..., require_composed=True)` で確認する。
    """
    abstract = load_project_abstract(ts_path)
    from analyze.compose import compose_screenplay
    composed = compose_screenplay(abstract)
    meta = load_tts_meta(ts_path)
    return _hydrate_tts_meta(composed, meta)


def save_project_screenplay(ts_path: str, screenplay: dict) -> None:
    """project の snapshot を atomic に上書き保存する。snapshot は完全 abstract で、
    TTS 派生 timing (= scene.duration / line.start / line.end) は含めない
    (= tts_meta.json が SSOT)。

    metadata.json の screenplay_sha256 もここで更新する。
    """
    cleaned = _strip_tts_derived(screenplay)
    os.makedirs(ts_path, exist_ok=True)
    raw = json.dumps(cleaned, ensure_ascii=False, indent=2)
    p = project_screenplay_path(ts_path)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(raw)
    os.replace(tmp, p)
    _refresh_metadata_sha(ts_path, hashlib.sha256(raw.encode("utf-8")).hexdigest())


def _refresh_metadata_sha(ts_path: str, sha256: str) -> None:
    meta = read_metadata(ts_path) or {}
    meta["screenplay_sha256"] = sha256
    io_utils.atomic_write_json(
        os.path.join(ts_path, "metadata.json"), meta,
    )


# ───────────────── metadata ─────────────────

def write_metadata(temp_dir: str, screenplay_name: str,
                    analyze_job_id: str | None = None,
                    sha256: str | None = None) -> None:
    """project 作成時の metadata.json を書く。

    screenplay_path は **project snapshot 相対パス** ("screenplay.json")。
    template (= 元 source) の名前は screenplay_template_name に分けて記録する。
    """
    if sha256 is None:
        snap = project_screenplay_path(temp_dir)
        if os.path.exists(snap):
            with open(snap, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
    meta: dict = {
        "screenplay_name": screenplay_name,
        "screenplay_template_name": screenplay_name,
        "screenplay_path": PROJECT_SCREENPLAY_FILENAME,
        "screenplay_sha256": sha256 or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if analyze_job_id:
        # analyze pipeline 経由で作られたプロジェクトのみ。Stage 1「素材編集」
        # セクションで抽象台本 + VideoStyle を編集して再合成するためのキー。
        meta["analyze_job_id"] = analyze_job_id
    os.makedirs(temp_dir, exist_ok=True)
    io_utils.atomic_write_json(
        os.path.join(temp_dir, "metadata.json"), meta,
    )


def read_metadata(temp_dir: str) -> dict | None:
    p = os.path.join(temp_dir, "metadata.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _ensure_prev_approved(prev_stage: str | None, ts_path: str) -> None:
    if prev_stage and not progress_store.is_approved(ts_path, prev_stage):
        raise RuntimeError(
            f"前ステージ '{prev_stage}' が未承認のため実行できません。"
            "UIで先に承認してください。"
        )


# ───────────────── stage runners ─────────────────

def run_script(screenplay: dict, screenplay_name: str, ts_path: str,
               analyze_job_id: str | None = None) -> None:
    """Stage 1: project 作成 → snapshot 保存 → 検証 → メタデータ書き出し。

    呼出元が template から読んだ screenplay dict を渡す。ここで:
      1. abstract 形式での検証 (= background_prompt は未生成でも可)
      2. temp/<TS>/screenplay.json に immutable snapshot として書き込み
      3. metadata.json に template 名 + snapshot sha256 を記録
    以降の stage は load_project_screenplay 経由で compose 済みを読む。
    composed 形式 (= background_prompt 必須) のチェックは Stage 2 直前で行う。
    """
    validate_screenplay(screenplay, require_composed=False)
    raw = json.dumps(screenplay, ensure_ascii=False, indent=2)
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    os.makedirs(ts_path, exist_ok=True)
    with open(project_screenplay_path(ts_path), "w") as f:
        f.write(raw)
    write_metadata(
        ts_path, screenplay_name,
        analyze_job_id=analyze_job_id, sha256=sha,
    )
    progress_store.mark_generated(ts_path, "script")
    logger.info(
        "[台本] 検証完了 — %dシーン (snapshot=%s, sha=%s)",
        len(screenplay["scenes"]),
        project_screenplay_path(ts_path),
        sha[:12],
    )


def run_tts(screenplay: dict, ts_path: str) -> None:
    """Stage 2: TTS生成。"""
    _ensure_prev_approved("script", ts_path)
    preflight.check_stage("tts")
    scene_gen.generate_tts_for_screenplay(screenplay, ts_path)
    progress_store.mark_generated(ts_path, "tts")
    logger.info("[TTS] 生成完了")


def run_bg(screenplay: dict, ts_path: str) -> None:
    """Stage 3: 背景画像生成。

    UI 経由で scene_decisions が確定済みなら、それに従って commit/fresh
    を分岐する (= cache 採用シーンは copy のみ、fresh は Imagen 呼出)。
    scene_decisions が空 (= 旧 UI / CLI) なら全シーン自動 cache lookup +
    miss は fresh 生成にフォールバック。
    """
    _ensure_prev_approved("tts", ts_path)
    preflight.check_stage("bg")
    decisions_state = progress_store.get_decisions(ts_path, "bg")
    decisions = decisions_state.get("scene_decisions") or {}
    bg_paths = scene_gen.generate_backgrounds(
        screenplay, ts_path, scene_decisions=decisions or None)
    progress_store.mark_generated(ts_path, "bg")
    logger.info("[背景] 生成完了 — %d枚", len(bg_paths))


def run_kling(screenplay: dict, ts_path: str) -> None:
    """Stage 4: Klingクリップ生成 + trim。

    UI 経由で scene_decisions が確定済みなら、それに従って commit/fresh
    を分岐する (= cache 採用シーンは copy のみ、fresh は FAL 呼出)。
    scene_decisions が空 (= 旧 UI / CLI) なら全シーン自動 cache lookup +
    miss は fresh 生成にフォールバック。
    """
    _ensure_prev_approved("bg", ts_path)
    preflight.check_stage("kling")
    decisions_state = progress_store.get_kling_decisions(ts_path)
    decisions = decisions_state.get("scene_decisions") or {}
    scene_gen.generate_kling_for_screenplay(
        screenplay, ts_path, scene_decisions=decisions or None)
    progress_store.mark_generated(ts_path, "kling")
    logger.info("[Kling] 生成完了")


def run_scene(screenplay: dict, ts_path: str) -> None:
    """Stage 5: 音声合成 + リップシンクで scene_<i>.mp4 を作成。"""
    _ensure_prev_approved("kling", ts_path)
    preflight.check_stage("scene")
    paths = scene_gen.assemble_scene_videos(screenplay, ts_path)
    progress_store.mark_generated(ts_path, "scene")
    logger.info("[音声/リップシンク合成] 完了 — %d本", len(paths))


def run_overlay(screenplay: dict, screenplay_name: str, ts_path: str) -> None:
    """Stage 6: シーン連結 + 字幕焼き込み + 最終出力配置。

    pipeline raw である ``output/reels_<TS>.mp4`` と SNS 投稿キャプション、
    Stage 7 (final_import) 用の drop folder までこの stage で生成する。

    古い snapshot を resume する経路では UI の保存時 validator を通過していない
    ことがあるため、Stage 6 直前で composed 形式 + subtitle anchor 順序を
    再検証して silent overwrite (= 字幕が消える) を防ぐ。
    途中で失敗した場合は merged.mp4 / overlaid.mp4 を削除し、再実行で
    古い中間ファイルが流用されないようにする。
    """
    _ensure_prev_approved("scene", ts_path)
    validate_screenplay(screenplay, require_composed=True)

    scene_videos = scene_gen.collect_scene_videos(screenplay, ts_path)
    scene_durations = [float(s["duration"]) for s in screenplay["scenes"]]
    merged = os.path.join(ts_path, "merged.mp4")
    overlaid = os.path.join(ts_path, "overlaid.mp4")
    ts = os.path.basename(ts_path)
    output_path = os.path.join(config.OUTPUT_DIR, f"reels_{ts}.mp4")

    if os.path.exists(overlaid):
        os.remove(overlaid)

    is_overlay_success = False
    try:
        merged_path = _merge_scenes(scene_videos, scene_durations, ts_path)
        _apply_overlays(merged_path, screenplay, ts_path, overlaid,
                          scene_videos=scene_videos)

        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        shutil.copyfile(overlaid, output_path)
        caption_path = generate_post_captions(
            screenplay, screenplay_name, output_path)
        is_overlay_success = True
    finally:
        if not is_overlay_success:
            # 部分書き込み artifact を掃除して、再実行が old merged を流用しない
            for p in (merged, overlaid, output_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError as e:
                        logger.warning(
                            "[overlay-cleanup] %s 削除失敗: %s", p, e,
                        )

    # Stage 7 (final_import) 用の drop folder を用意。CapCut 出力をここに置く。
    os.makedirs(os.path.join(ts_path, "final"), exist_ok=True)

    # cache promote: pipeline raw まで生成完了 = 高信頼な素材として将来の hit
    # 候補に格上げする (L3#2)。bg / kling 両方。失敗しても本流は進める。
    for stage_name, module in (("bg", "bg_cache"), ("kling", "kling_cache")):
        try:
            _promote_cache_entries(ts_path, stage_name, module)
        except Exception as e:
            logger.warning("%s promote failed: %s", module, e)

    progress_store.mark_generated(ts_path, "overlay")
    logger.info("[字幕] 焼き込み完了 — %s", output_path)
    logger.info("SNS投稿キャプション: %s", caption_path)


def _promote_cache_entries(ts_path: str, stage: str, module_name: str) -> None:
    """指定 stage の cache key を L3 で promote する (= bg / kling 共通)。

    cache hit で copy したものに加え、scan 時点で記録された cache_key も対象。
    """
    import importlib
    cache_mod = importlib.import_module(module_name)
    decisions_state = progress_store.get_decisions(ts_path, stage)
    decisions = decisions_state.get("scene_decisions") or {}
    seen: set[str] = set()
    for rec in decisions.values():
        k = rec.get("decided_key")
        if k:
            seen.add(k)
        ck = rec.get("cache_key")
        if ck:
            seen.add(ck)
    for key in seen:
        try:
            cache_mod.promote(key)
            cache_mod.mark_origin_approved(key)
        except Exception as e:
            logger.debug("%s.promote(%s) failed: %s", module_name, key, e)


STAGE_RUNNERS = {
    "script": run_script,
    "tts": run_tts,
    "bg": run_bg,
    "kling": run_kling,
    "scene": run_scene,
    "overlay": run_overlay,
}


def run_next_stage(screenplay: dict, screenplay_name: str, ts_path: str) -> str | None:
    """次に実行すべきstageを1つだけ実行する。

    - final_import / publish はユーザの外部アクション (CapCut 取り込み /
      プラットフォーム公開) で発火するため、ここでは実行せず None を返す
    - すでに全完了なら None
    """
    nxt = progress_store.next_stage(ts_path)
    if nxt is None:
        return None

    if nxt in progress_store.EXTERNAL_ACTION_STAGES:
        return None

    runner = STAGE_RUNNERS.get(nxt)
    if not runner:
        raise RuntimeError(f"unknown stage: {nxt}")
    if nxt in ("script", "overlay"):
        runner(screenplay, screenplay_name, ts_path)
    else:
        runner(screenplay, ts_path)
    return nxt


def apply_scene_boundaries(ts_path: str, line_boundaries: list[int]) -> dict:
    """全 lines を flat 順に保ったまま、scene 境界だけを再定義する。

    `line_boundaries` は「scene 開始 line index (flat)」の昇順 list で、必ず
    `0` から始まる。例えば line が 12 個ある時:
        [0, 3, 7]  → scene0=lines[0..3), scene1=lines[3..7), scene2=lines[7..12)

    line のテキスト・順序は変えない (= TTS 音声は再 API 呼び出し不要)。
    既存の per-line / per-scene file (tts_<S>_<L>.mp3, audio_<S>.m4a, bg/kling/scene)
    は scene index を含むので全削除し、`tts_full.mp3` から新しい index で再構築する。
    bg 以降の progress / approval は reset される (= 後段は再生成必要)。

    Returns: {"scenes": int, "lines": int, "subtitles_reset_lines": int}
        subtitles_reset_lines: subtitles[].start/end が auto に戻された line 数
    """
    sp = load_project_screenplay(ts_path)
    flat_lines: list[dict] = []
    for s in sp.get("scenes") or []:
        for line in s.get("lines") or []:
            flat_lines.append(dict(line))
    n_lines = len(flat_lines)
    if n_lines == 0:
        raise ValueError("snapshot に line が 1 つもありません")

    # scene 再分割で line が別 scene に移動すると元 scene 基準だった
    # subtitles[].start/end (= シーン内相対秒) は意味が壊れる。完全な migration は
    # scene duration が変わる以上不可能なので、保守的に「auto に戻す」(= text のみ保持)。
    subtitles_reset_lines = 0
    subtitles_reset_chunks = 0
    for ln in flat_lines:
        subs = ln.get("subtitles")
        if not isinstance(subs, list) or not subs:
            continue
        is_line_reset = False
        new_subs: list[dict] = []
        for sub in subs:
            if not isinstance(sub, dict):
                new_subs.append(sub)
                continue
            if "start" in sub or "end" in sub:
                stripped = {k: v for k, v in sub.items() if k not in ("start", "end")}
                new_subs.append(stripped)
                subtitles_reset_chunks += 1
                is_line_reset = True
            else:
                new_subs.append(sub)
        if is_line_reset:
            ln["subtitles"] = new_subs
            subtitles_reset_lines += 1
    if subtitles_reset_lines > 0:
        logger.info(
            "[scene-boundaries] subtitle 時刻を auto に戻しました: "
            "%d line / %d chunk",
            subtitles_reset_lines,
            subtitles_reset_chunks,
        )

    if not line_boundaries:
        raise ValueError("line_boundaries が空です")
    if line_boundaries[0] != 0:
        raise ValueError("line_boundaries は 0 から始める必要があります")
    if list(line_boundaries) != sorted(set(line_boundaries)):
        raise ValueError("line_boundaries は重複なしの昇順である必要があります")
    if any(b < 0 or b >= n_lines for b in line_boundaries):
        raise ValueError(
            f"line_boundaries が範囲外 (有効: 0..{n_lines - 1})",
        )

    # regroup
    boundaries_with_end = list(line_boundaries) + [n_lines]
    new_scenes: list[dict] = []
    for i in range(len(line_boundaries)):
        scene_lines = flat_lines[boundaries_with_end[i]:boundaries_with_end[i + 1]]
        if not scene_lines:
            continue
        # scene 内相対秒に正規化 (= 各 scene の先頭 line を 0 起点)
        offset = float(scene_lines[0].get("start", 0) or 0)
        for ln in scene_lines:
            if "start" in ln:
                ln["start"] = max(0.0, float(ln["start"]) - offset)
            if "end" in ln:
                ln["end"] = max(0.0, float(ln["end"]) - offset)
        # duration は計算しない。直後の _build_audios_from_full が
        # 実 TTS 累積長から書き戻す (= Stage 2 が SSOT)
        new_scenes.append({
            "lines": scene_lines,
            # ビジュアル系フィールドは敢えて空のまま (= 再 compose で埋める)。
            # 古い scene-index 由来のままだと scene が分割/合体した時に整合しない。
        })

    new_sp = dict(sp)
    new_sp["scenes"] = new_scenes
    # snapshot は abstract のまま保存 (= save が _strip_tts_derived で除去)
    save_project_screenplay(ts_path, new_sp)

    # tts_meta.json も新 group に対応した timing で書き直す (= SSOT 一貫性)
    new_meta_scenes: list[dict] = []
    for scene in new_scenes:
        scene_meta: dict = {}
        if "duration" in scene:
            scene_meta["duration"] = scene["duration"]
        line_metas: list[dict] = []
        for line in scene.get("lines") or []:
            lm: dict = {}
            if "start" in line:
                lm["start"] = line["start"]
            if "end" in line:
                lm["end"] = line["end"]
            line_metas.append(lm)
        scene_meta["lines"] = line_metas
        new_meta_scenes.append(scene_meta)
    save_tts_meta(ts_path, {"scenes": new_meta_scenes})

    # 古い scene-indexed file を全 cleanup (新 index で再構築するため)
    import glob
    patterns = [
        "tts_*_*.mp3",
        "audio_*.m4a", "audio_*.wav",
        "bg_*.png", "composite_*.png",
        "kling_*.mp4",
        "scene_*.mp4", "scene_*.trim.mp4", "scene_*.extended.mp4",
    ]
    for pat in patterns:
        for p in glob.glob(os.path.join(ts_path, pat)):
            try:
                os.remove(p)
            except OSError:
                logger.warning("delete 失敗: %s", p)

    # tts_full.mp3 が残っていれば per-line / per-scene を再分割
    full_mp3 = os.path.join(ts_path, "tts_full.mp3")
    if os.path.exists(full_mp3):
        scene_gen._build_audios_from_full(new_sp, ts_path)
        logger.info(
            "[scene-boundaries] tts_full.mp3 から %d scene を再分割しました",
            len(new_scenes),
        )
    else:
        logger.warning(
            "[scene-boundaries] tts_full.mp3 が無いので audio 再分割はスキップ。"
            "Stage 2 を再実行してください",
        )

    # progress reset: bg 以降を完全クリア。tts は audio が新 scene 構造で
    # 揃うので generated は維持し approved だけ解除 (再確認させる)。
    progress_store.reset_stage(ts_path, "bg")
    pg = progress_store.load(ts_path)
    if pg["stages"]["tts"]["generated_at"]:
        pg["stages"]["tts"]["approved_at"] = None
        progress_store.save(ts_path, pg)

    return {
        "scenes": len(new_scenes),
        "lines": n_lines,
        "subtitles_reset_lines": subtitles_reset_lines,
    }


def regen(stage: str, screenplay: dict, ts_path: str,
          scene_idx: int | None = None, line_idx: int | None = None,
          force: bool = True, screenplay_name: str | None = None) -> None:
    """指定stage・scene・lineの単独再生成。承認をリセット。

    force=False (TTSのみ): text_hash不変ならAPIスキップでaudio再構築のみ。
    bg / kling / scene で scene_idx=None の場合は全シーン一括再生成。
    overlay は screenplay_name 必須 (= post caption ファイル名に使う)。
    """
    n_scenes = len(screenplay.get("scenes") or [])
    if stage == "tts":
        scene_gen.regen_tts_full(screenplay, ts_path, force=force)
    elif stage == "bg":
        if scene_idx is None:
            for i in range(n_scenes):
                scene_gen.regen_background_scene(i, screenplay, ts_path)
        else:
            scene_gen.regen_background_scene(scene_idx, screenplay, ts_path)
    elif stage == "kling":
        if scene_idx is None:
            for i in range(n_scenes):
                scene_gen.regen_kling_scene(i, screenplay, ts_path)
        else:
            scene_gen.regen_kling_scene(scene_idx, screenplay, ts_path)
    elif stage == "scene":
        if scene_idx is None:
            for i in range(n_scenes):
                scene_gen.regen_scene_video(i, screenplay, ts_path)
        else:
            scene_gen.regen_scene_video(scene_idx, screenplay, ts_path)
    elif stage == "overlay":
        if screenplay_name is None:
            raise ValueError("overlay 再生成には screenplay_name が必要です")
        run_overlay(screenplay, screenplay_name, ts_path)
    else:
        raise ValueError(f"このstageは個別再生成に対応していません: {stage}")
    progress_store.increment_regen(ts_path, stage)
    # 古い素材ベースで承認済みになった後続 stage を連鎖 reset (artifact は保持)。
    reset_stages = progress_store.cascade_reset_after(ts_path, stage)
    if reset_stages:
        logger.info(
            "stage %s 再生成 → 後続 stage %s の承認をリセットしました (再確認が必要)",
            stage, reset_stages,
        )
