# scripts/\_archive/

一度実行されたら役目を終える migration scripts の保管庫。本ディレクトリの
script は **再実行不要 / 削除予定** だが、git history からの参照のために
保持している。

## 移動済み (2026-05-17 / 計画書 §4.3)

| Script                           | 目的                                                              | 実行済みバージョン |
| -------------------------------- | ----------------------------------------------------------------- | ------------------ |
| `migrate_screenplay_v2.py`       | screenplay v1 → v2 (= 旧 scene_parts schema 廃止)                 | 全 project         |
| `migrate_screenplay_v3.py`       | screenplay v2 → v3 (= identity/annotation flat → nested)          | 全 project         |
| `migrate_to_project_snapshot.py` | template-only 経路から project snapshot 経路へ                    | 全 project         |
| `migrate_intent_suggestions.py`  | per-screenplay `<stem>.suggested_intents.json` → aggregated inbox | 全 project         |
| `migrate_speaker_schema.py`      | speaker_profiles schema 修正                                      | 全 project         |
| `migrate_speaker_to_ref.py`      | line.speaker raw `speaker_N` → resolved id (= #209)               | 全 project         |
| `migrate_characters_layout.py`   | flat `characters/<base>.png` → nested `characters/<base>/...`     | 全 project         |

## 新規 migration 追加時の運用

- 一度きりの schema migration は `scripts/` 直下に作成し、実行後に `_archive/` へ移動
- 移動は本ディレクトリの README に追記すること
- scripts/**init**.py の `_cli_base` import は `_archive/` 配下にも適用される
  ため、archive 後も `python3 scripts/_archive/migrate_xxx.py` で動作する
  (= 緊急時の re-run を支援、ただし再実行は idempotent と確認したものに限る)
