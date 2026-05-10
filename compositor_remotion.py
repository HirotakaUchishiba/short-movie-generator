"""Layer 3 (Composition Engine) Python backend.

`staged_pipeline.run_overlay` から `OVERLAY_BACKEND=remotion` 時に呼ばれ、
screenplay + scene_videos から `render_plan.json` を組み立てて
`npx remotion render` を起動する。

不変条件 (= 設計 doc §1.3):
- タイミング解決 (= subtitle chunk の絶対秒) は既存 compositor.py のロジックを
  そのまま流用する (= SSOT は Python 側、Remotion は表示するだけ)
- AI 課金は発生しない (= scene_videos / screenplay は既に存在前提)
- 既存 ffmpeg compositor は不変。本 module は完全に並列の path

詳細: docs/plannings/2026-05-10_compositional-architecture.md §5
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import config
from compositor import (
    _allocate_chunk_timings,
    _get_duration,
    _line_window,
    _resolve_subtitle_timings,
    _scene_offsets_from_videos,
    _split_into_chunks,
    _wrap_subtitle_text,
)

logger = logging.getLogger(__name__)


def _frontend_public_dir() -> Path:
    """`frontend/public/` の絶対パス。Remotion の staticFile() の解決元。"""

    return Path(config.BASE_DIR) / "frontend" / "public"


def _render_workspace_for(ts_path: str) -> tuple[Path, str]:
    """`frontend/public/_render_<TS>/` を作って (workspace_dir, public_relpath_prefix)
    を返す。scene_<S>.mp4 をここに symlink して staticFile から見える状態にする。"""

    ts = os.path.basename(ts_path.rstrip("/"))
    rel = f"_render_{ts}"
    workspace = _frontend_public_dir() / rel
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace, rel


def _link_scene_videos(
    scene_videos: list[str], workspace: Path, public_relpath: str
) -> list[str]:
    """scene_<S>.mp4 を workspace に symlink して、relative path のリストを返す。

    既に同サイズのファイルがあれば再利用する。Remotion 4 の webpack bundler が
    symlink を follow しない (= bundle 内 public/ への copy 時に symlink ターゲット
    を含めない) ため、本関数は **常に物理コピー** する。
    cache 容量を抑えたい場合は `_render_<TS>/` 単位で render 後に削除して回す。
    """

    rels: list[str] = []
    for idx, src in enumerate(scene_videos):
        # ソース basename を保つと debug しやすい (= scene_000.mp4 等)
        link_name = f"scene_{idx:03d}{Path(src).suffix}"
        dst = workspace / link_name
        src_path = Path(src)
        # 既存ファイルが同 size なら再利用 (= 連続呼び出し時の高速化)
        if dst.exists() and not dst.is_symlink():
            try:
                if dst.stat().st_size == src_path.stat().st_size:
                    rels.append(f"{public_relpath}/{link_name}")
                    continue
            except OSError:
                pass
        # 既存 symlink (= 旧版互換) は除去してから copy する
        if dst.exists() or dst.is_symlink():
            try:
                dst.unlink()
            except OSError:
                pass
        shutil.copyfile(os.fspath(src), str(dst))
        rels.append(f"{public_relpath}/{link_name}")
    return rels


def _resolve_subtitle_chunks_for_scene(
    scene: dict,
    next_scenes_offset_for_carry: float | None,
    scene_offset_abs: float,
    scene_duration_sp: float,
    scene_duration_real: float,
) -> list[dict[str, Any]]:
    """1 scene の subtitle_lines (= renderPlan の構造) を返す。

    既存 compositor._build_overlay_filter のロジックを構造化された値で再現する:
        - line.subtitles (= manual chunks) → _resolve_subtitle_timings
        - line.subtitles 無し + chunk_enabled → _split_into_chunks + _allocate_chunk_timings
        - line.subtitles 無し + chunk_disabled → 1 chunk (= line 全文を改行で wrap)
    """

    chunk_enabled = bool(getattr(config, "SUBTITLE_CHUNK_ENABLED", True))
    chunk_max_chars = int(getattr(config, "SUBTITLE_CHUNK_MAX_CHARS", 8))
    line_max_chars = int(getattr(config, "SUBTITLE_MAX_CHARS_PER_LINE", 17))

    out_lines: list[dict[str, Any]] = []
    scene_lines = scene.get("lines") or []
    for l_idx, line in enumerate(scene_lines):
        if line.get("hidden"):
            continue
        next_line = scene_lines[l_idx + 1] if l_idx + 1 < len(scene_lines) else None

        rel_start, rel_end = _line_window(
            line, next_line, scene_duration_sp, scene_duration_real
        )
        line_start_abs = scene_offset_abs + rel_start
        line_end_abs = scene_offset_abs + rel_end

        manual_subs = line.get("subtitles") or []
        if manual_subs:
            ratio = (
                scene_duration_real / scene_duration_sp
                if scene_duration_sp > 0
                else 1.0
            )
            resolver_items: list[dict] = []
            for sub in manual_subs:
                sub_text = (sub.get("text") or "").strip()
                if not sub_text:
                    continue
                item: dict = {"text": sub_text}
                if sub.get("start") is not None:
                    item["start"] = scene_offset_abs + float(sub["start"]) * ratio
                if sub.get("end") is not None:
                    item["end"] = scene_offset_abs + float(sub["end"]) * ratio
                resolver_items.append(item)
            if not resolver_items:
                continue
            resolved = _resolve_subtitle_timings(
                resolver_items, line_start_abs, line_end_abs
            )
            chunks_info = [
                {
                    "text": resolver_items[i]["text"],
                    "start_abs_sec": float(start),
                    "end_abs_sec": float(end),
                    "anchor_kind": (
                        "manual"
                        if (
                            resolver_items[i].get("start") is not None
                            or resolver_items[i].get("end") is not None
                        )
                        else "auto"
                    ),
                }
                for i, (start, end) in enumerate(resolved)
            ]
        else:
            text = (line.get("text") or "").strip()
            if not text:
                continue
            if chunk_enabled:
                chunks = _split_into_chunks(text, chunk_max_chars)
                timings = _allocate_chunk_timings(
                    chunks, line_start_abs, line_end_abs
                )
            else:
                chunks = [_wrap_subtitle_text(text, line_max_chars)]
                timings = [(line_start_abs, line_end_abs)]
            chunks_info = [
                {
                    "text": c,
                    "start_abs_sec": float(s),
                    "end_abs_sec": float(e),
                    "anchor_kind": "auto",
                }
                for c, (s, e) in zip(chunks, timings)
            ]

        if not chunks_info:
            continue
        out_lines.append(
            {
                "line_idx": l_idx,
                "emotion": line.get("emotion"),
                "chunks": chunks_info,
            }
        )
    return out_lines


def _scene_subtitle_style_part(scene: dict) -> dict[str, Any]:
    """scene.scene_parts.subtitle_style があればそれを、無ければ minimal default。"""

    sp = (scene.get("scene_parts") or {}).get("subtitle_style") or {}
    sub_id = sp.get("id") or "minimal"
    params = dict(sp.get("params") or {})
    return {"id": sub_id, "params": params}


def build_render_plan(
    screenplay: dict, scene_videos: list[str], public_relpath: str | None = None
) -> dict[str, Any]:
    """screenplay + scene_videos から RenderPlan dict を組み立てる。

    Args:
        screenplay: validate 済み screenplay。lines / scenes / subtitle_y_from_bottom 等
        scene_videos: 各 scene_<S>.mp4 の絶対パス (= scene と同順)
        public_relpath: scene_video_path を public 相対 (例 "_render_20260510_xxx") で
            出力する場合の prefix。None なら scene_videos の絶対パスを path に詰める。
    """

    scenes = screenplay.get("scenes") or []
    if len(scenes) != len(scene_videos):
        raise ValueError(
            f"scenes ({len(scenes)}) と scene_videos ({len(scene_videos)}) "
            "の本数が一致しません"
        )

    fps = int(config.FPS)
    width = int(config.VIDEO_WIDTH)
    height = int(config.VIDEO_HEIGHT)

    # 実 timeline ベースで offset を計算 (= 既存 compositor と同じ)
    offsets = _scene_offsets_from_videos(scene_videos)
    real_durations = [_get_duration(v) for v in scene_videos]
    total_duration = sum(real_durations)
    duration_frames = max(1, int(round(total_duration * fps)))

    sub_y_from_bottom = (
        int(screenplay["subtitle_y_from_bottom"])
        if screenplay.get("subtitle_y_from_bottom") is not None
        else int(config.SUBTITLE_Y_FROM_BOTTOM)
    )

    plan_scenes: list[dict[str, Any]] = []
    for s_idx, scene in enumerate(scenes):
        scene_real = real_durations[s_idx]
        scene_sp = float(scene.get("duration") or scene_real)
        scene_offset = offsets[s_idx]
        subtitle_lines = _resolve_subtitle_chunks_for_scene(
            scene,
            next_scenes_offset_for_carry=None,
            scene_offset_abs=scene_offset,
            scene_duration_sp=scene_sp,
            scene_duration_real=scene_real,
        )

        sv_abs = os.fspath(scene_videos[s_idx])
        if public_relpath is not None:
            link_name = f"scene_{s_idx:03d}{Path(sv_abs).suffix}"
            scene_video_path = f"{public_relpath}/{link_name}"
        else:
            scene_video_path = sv_abs

        scene_part = _scene_subtitle_style_part(scene)
        # 既定 params に subtitle_y_from_bottom を流し込む (component 側で吸収)
        scene_part["params"].setdefault("yFromBottom", sub_y_from_bottom)
        scene_part["params"].setdefault("fontSize", int(config.SUBTITLE_FONT_SIZE))
        scene_part["params"].setdefault("fontColor", config.TIME_TEXT_COLOR)
        scene_part["params"].setdefault("borderColor", config.TIME_BORDER_COLOR)
        scene_part["params"].setdefault("borderWidth", int(config.FONT_BORDER_WIDTH))

        # Phase 4-B: stickers (= scene_parts.stickers[]) を passthrough。
        # 各 entry は {id, at, duration?, params?}。at は scene 内相対秒。
        # validator 整合性チェックは Phase 4 末で part_registry yaml と突き合わせ予定。
        scene_parts_in = scene.get("scene_parts") or {}
        plan_parts: dict[str, Any] = {"subtitle_style": scene_part}
        if scene_parts_in.get("stickers"):
            stickers_out: list[dict[str, Any]] = []
            for s in scene_parts_in["stickers"]:
                if not isinstance(s, dict) or "id" not in s or "at" not in s:
                    continue
                item: dict[str, Any] = {
                    "id": str(s["id"]),
                    "at": float(s["at"]),
                    "params": dict(s.get("params") or {}),
                }
                if s.get("duration") is not None:
                    item["duration"] = float(s["duration"])
                stickers_out.append(item)
            if stickers_out:
                plan_parts["stickers"] = stickers_out

        # Phase 4-D: camera_move (= scene 動画への post-effect 動き) を passthrough。
        # {id, params?} を normalize。SceneSequence が OffthreadVideo を wrap する。
        cam = scene_parts_in.get("camera_move")
        if isinstance(cam, dict) and isinstance(cam.get("id"), str):
            plan_parts["camera_move"] = {
                "id": cam["id"],
                "params": dict(cam.get("params") or {}),
            }

        # Phase 4-E: lower_third (= 画面下 1/3 の名前バナー等) を passthrough。
        # {id, at, duration, params?}。1 scene につき 1 件のみ。
        lt = scene_parts_in.get("lower_third")
        if (
            isinstance(lt, dict)
            and isinstance(lt.get("id"), str)
            and lt.get("at") is not None
            and lt.get("duration") is not None
        ):
            plan_parts["lower_third"] = {
                "id": lt["id"],
                "at": float(lt["at"]),
                "duration": float(lt["duration"]),
                "params": dict(lt.get("params") or {}),
            }

        # Phase 4-G: transition_in / transition_out (= scene 境界 effect) を
        # passthrough。{id, params?} のみ正規化。`direction` と
        # `totalFrames` は SceneSequence 側で注入する (= Python 側で持つと
        # frame 数依存になるため UI 経由の編集が複雑になる)。
        for key in ("transition_in", "transition_out"):
            tr = scene_parts_in.get(key)
            if isinstance(tr, dict) and isinstance(tr.get("id"), str):
                plan_parts[key] = {
                    "id": tr["id"],
                    "params": dict(tr.get("params") or {}),
                }

        # Phase 4-H: frame_layout (= scene 動画の framing 戦略) を passthrough。
        # {id, params?}。1 scene につき 1 件。default は "full" だが書かないなら
        # frame_layout キー自体省略し SceneSequence 側で AbsoluteFill 直配置に。
        fl = scene_parts_in.get("frame_layout")
        if isinstance(fl, dict) and isinstance(fl.get("id"), str):
            plan_parts["frame_layout"] = {
                "id": fl["id"],
                "params": dict(fl.get("params") or {}),
            }

        # Phase 5-B: sfx (= scene 内の効果音) を passthrough。
        # 各 entry は {path, at, volume?}。path は Remotion の <Audio> が
        # 解決可能な http(s):// or staticFile-relative パス。
        if scene_parts_in.get("sfx"):
            sfx_out: list[dict[str, Any]] = []
            for s in scene_parts_in["sfx"]:
                if (
                    not isinstance(s, dict)
                    or "path" not in s
                    or "at" not in s
                ):
                    continue
                item: dict[str, Any] = {
                    "path": str(s["path"]),
                    "at": float(s["at"]),
                }
                if s.get("volume") is not None:
                    item["volume"] = float(s["volume"])
                sfx_out.append(item)
            if sfx_out:
                plan_parts["sfx"] = sfx_out

        plan_scenes.append(
            {
                "index": s_idx,
                "scene_video_path": scene_video_path,
                "offset_sec": float(scene_offset),
                "duration_sec": float(scene_real),
                "subtitle_lines": subtitle_lines,
                "parts": plan_parts,
            }
        )

    return {
        "video": {
            "width": width,
            "height": height,
            "fps": fps,
            "duration_frames": duration_frames,
        },
        "scenes": plan_scenes,
        "global_parts": _normalize_global_parts(screenplay.get("global_parts")),
        "template": "base",
    }


def _normalize_global_parts(raw: Any) -> dict[str, Any]:
    """screenplay.global_parts を render_plan が受ける形に正規化する。

    現状サポート:
      - filter_preset: {id, params}                       (Phase 4-C)
      - intro_card: {id, duration_sec, params}            (Phase 4-F)
      - outro_card: {id, duration_sec, params}            (Phase 4-F)
      - bgm: {path, ducking_curve}                         (Phase 5-B)

    未知のキーは静かにドロップ (= validator が事前 reject する想定だが defensive)。
    """

    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}

    fp = raw.get("filter_preset")
    if isinstance(fp, dict) and isinstance(fp.get("id"), str):
        out["filter_preset"] = {
            "id": fp["id"],
            "params": dict(fp.get("params") or {}),
        }

    for key in ("intro_card", "outro_card"):
        card = raw.get(key)
        if (
            isinstance(card, dict)
            and isinstance(card.get("id"), str)
            and card.get("duration_sec") is not None
        ):
            out[key] = {
                "id": card["id"],
                "duration_sec": float(card["duration_sec"]),
                "params": dict(card.get("params") or {}),
            }

    # Phase 5-B: bgm = {path, ducking_curve?}。
    # ducking_curve は数値 (= constant volume) または [[t,v], ...] 配列を許容。
    # 未指定なら 0.4 (= 控えめ) を default として ScreenplayBase 側で適用。
    bgm = raw.get("bgm")
    if isinstance(bgm, dict) and isinstance(bgm.get("path"), str):
        bgm_out: dict[str, Any] = {"path": bgm["path"]}
        curve = bgm.get("ducking_curve")
        if isinstance(curve, (int, float)):
            bgm_out["ducking_curve"] = float(curve)
        elif isinstance(curve, list):
            normalized_curve: list[list[float]] = []
            for entry in curve:
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and all(isinstance(v, (int, float)) for v in entry)
                ):
                    normalized_curve.append([float(entry[0]), float(entry[1])])
            if normalized_curve:
                bgm_out["ducking_curve"] = normalized_curve
        else:
            bgm_out["ducking_curve"] = 0.4
        out["bgm"] = bgm_out
    return out


def render_via_remotion(
    plan: dict[str, Any],
    output_path: str,
    composition_id: str = "ScreenplayBase",
    plan_path: str | None = None,
) -> str:
    """Remotion CLI を起動して plan を mp4 に焼く。

    Args:
        plan: build_render_plan の戻り値
        output_path: 出力 mp4 の絶対パス
        composition_id: Remotion Composition の id (= base / youtube / instagram / tiktok)
        plan_path: render_plan.json を書く場所。None なら output_path と同じディレクトリに
            ``<output basename>.render_plan.json`` で書く

    既知の制約への対応:
      Composition.calculateMetadata が --props 経由で十分に伝播しないため、
      ``--frames=0-{N-1}`` を CLI に明示渡しすることで durationInFrames を強制する。
    """

    if plan_path is None:
        plan_path = os.path.join(
            os.path.dirname(output_path),
            os.path.basename(output_path) + ".render_plan.json",
        )
    Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump({"plan": plan}, f, ensure_ascii=False)

    duration_frames = int(plan["video"]["duration_frames"])
    end_frame = max(0, duration_frames - 1)

    # frontend ディレクトリで実行 (= remotion.config.ts が相対パスで entry point を見る)
    cwd = os.path.join(config.BASE_DIR, "frontend")

    # `--public-dir` を絶対パスで明示する。
    # Remotion 4 は bundle 時に `public/` のスナップショットを作って cache する。
    # `_render_<TS>/` の symlink は compose_video_remotion 直前に作られるため、
    # 古い cache bundle にはまだ存在しない。--public-dir で実物を指定すると
    # bundle がスナップショットではなく実 dir を参照するようになり、
    # symlink を直接 resolve できる。
    public_dir = os.path.abspath(os.path.join(cwd, "public"))
    cmd = [
        "npx",
        "remotion",
        "render",
        composition_id,
        os.path.abspath(output_path),
        f"--props={os.path.abspath(plan_path)}",
        f"--frames=0-{end_frame}",
        f"--concurrency={int(getattr(config, 'REMOTION_CONCURRENCY', 4))}",
        f"--public-dir={public_dir}",
    ]
    logger.info("[remotion] render start: composition=%s frames=0-%d output=%s",
                composition_id, end_frame, output_path)
    t0 = time.monotonic()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=1800)
    elapsed = time.monotonic() - t0
    if r.returncode != 0:
        logger.error(
            "[remotion] render failed (exit=%d, %.1fs):\n%s",
            r.returncode, elapsed, r.stderr[-2000:],
        )
        raise RuntimeError(f"remotion render failed (exit={r.returncode})")
    logger.info("[remotion] render done in %.1fs → %s", elapsed, output_path)
    return output_path


_TEMPLATE_TO_COMPOSITION_ID: dict[str, str] = {
    "base": "ScreenplayBase",
    "youtube": "ScreenplayYoutube",
    "instagram": "ScreenplayInstagram",
    "tiktok": "ScreenplayTikTok",
}


def composition_id_for_template(template: str) -> str:
    """plan["template"] (= base / youtube / instagram / tiktok) を Remotion の
    Composition id (= ScreenplayBase / ScreenplayYoutube / ...) に変換。

    未知の template は base にフォールバック。
    """

    return _TEMPLATE_TO_COMPOSITION_ID.get(template, "ScreenplayBase")


def compose_video_remotion(
    scene_videos: list[str],
    screenplay: dict,
    temp_dir: str,
    output_path: str,
    composition_id: str | None = None,
    template: str = "base",
) -> str:
    """ffmpeg compositor.compose_video の Remotion 等価 entry point。

    `staged_pipeline.run_overlay` から OVERLAY_BACKEND=remotion 時に呼ばれる。

    Args:
        composition_id: 直接 Composition id を指定したい場合に使う (= 後方互換)
        template: "base" / "youtube" / "instagram" / "tiktok" (= Stage 8 publish
            から呼ばれた時に platform を渡す)。composition_id 未指定時に
            template から自動解決する。
    """

    workspace, public_rel = _render_workspace_for(temp_dir)
    _link_scene_videos(scene_videos, workspace, public_rel)
    plan = build_render_plan(screenplay, scene_videos, public_relpath=public_rel)
    # plan の template を上書き (= 呼び出し側からの指定を優先)
    plan["template"] = template
    if composition_id is None:
        composition_id = composition_id_for_template(template)
    plan_path = os.path.join(temp_dir, "render_plan.json")
    render_via_remotion(
        plan, output_path, composition_id=composition_id, plan_path=plan_path
    )
    return output_path
