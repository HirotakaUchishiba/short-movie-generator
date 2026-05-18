# routes パッケージ — preview_server.py から段階分割された Blueprint 群。
#
# 進行状況 (= 2026-05-19 時点):
#   ✓ routes/_helpers.py             — shared util (api_error / validate_ts / ...)
#   ✓ routes/analyze.py              — /api/screenplay/analyze/*
#                                     (job GET / confirm / events SSE / cancel)
#   ✓ routes/assets.py               — /asset/* (TTS/BG/Kling/scene/overlay/
#                                     character/reference-video/location preview)
#   ✓ routes/catalogs.py             — /api/characters + /api/presets
#                                     (frontend dropdown 用 static catalog)
#   ✓ routes/character_metas.py      — /api/character-metas/* (voice メタ CRUD)
#   ✓ routes/clip_library.py         — /api/clip-library/*
#   ✓ routes/config.py               — /api/config + /api/config/{model,speed,...}
#   ✓ routes/cost.py                 — /api/cost/* (pricebook / estimate / median /
#                                     report)
#   ✓ routes/final_publish.py        — /api/projects/<ts>/{final*,publish*}
#                                     (Stage 7 final import + Stage 8 publish)
#   ✓ routes/intent_catalog.py       — /api/intent-catalog
#   ✓ routes/intent_suggestions.py   — /api/intent-suggestions
#   ✓ routes/jobs.py                 — /api/jobs/<job_id> (job 進捗参照)
#   ✓ routes/locations.py            — /api/locations/* (ロケ JSON CRUD)
#   ✓ routes/project_queries.py      — /api/projects/<ts>/{tts-source / progress /
#                                     scenes/<i>/composed-prompts / bg-cache-info}
#                                     (read-only 派生情報)
#   ✓ routes/projects.py             — /api/projects (一覧 + 作成 + 詳細)
#   ✓ routes/reference_videos.py     — /api/reference_videos/* (analyze 用素材)
#   ✓ routes/screenplay.py           — /api/projects/<ts>/{screenplay,abstract,
#                                     lines/<s>/<l>,screenplay-meta,scene-boundaries}
#                                     (screenplay 編集系。screenplay_lock 必須)
#   ✓ routes/stages.py               — /api/projects/<ts>/{run-next,approve,reject,
#                                     regen} (Stage 進行 / QA failure 記録)
#   ✓ routes/stage_cache.py          — /api/projects/<ts>/stages/{bg,kling}/* +
#                                     /api/{bg,kling}-cache/* (Stage 3 / 4 cache)
#
# preview_server.py に残るのは Flask app 初期化 / bootstrap / middleware /
# static frontend 配信 / startup recovery hook と、test が直接 import している
# shim 関数 (_validate_ts / _ts_path / _spawn_job / _job_to_dict 等) のみ。
#
# 全 endpoint で api_error() による error_code 統一が完了 (= §3.1.2-b)。
# intent_suggestions の 200-path のみ `{"ok": True, "record": ...}` の独自
# success contract を維持 (= frontend IntentCatalogPage の依存先)。
#
# 移行は 1 Blueprint = 1 PR を目安に、その都度全テスト pass を保つ運用。
