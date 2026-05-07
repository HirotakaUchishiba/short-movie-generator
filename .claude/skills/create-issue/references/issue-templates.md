# Issue テンプレート

## Bug Report

```markdown
## 概要

[バグの簡潔な説明]

## 再現手順

1. [手順 1: 例) 台本 `19_xxx.json` で `python3 main.py 19_xxx`]
2. [手順 2: 例) Stage 4 (Kling) まで進む]
3. [手順 3: 例) UI から「再生成」を押す]

## 期待される動作

[正しい動作の説明]

## 実際の動作

[発生している問題の説明]

## 影響を受けるファイル

- `path/to/file.py`
- `frontend/src/.../X.tsx`

## 環境

- OS: [macOS 14 / Ubuntu 22 等]
- Python: [3.12.x]
- ffmpeg: [`ffmpeg -version` の出力 1 行]
- Node: [Node 20 / npm のバージョン] (frontend に関連する場合)
- 関連モデル / プロバイダ: [Kling V3 / lipsync-2 / eleven_v3 等]

## ログ / スクリーンショット

[該当する場合]

## 対応内容

- [ ] タスク 1
- [ ] タスク 2

## 備考

[追加情報があれば]
```

## Enhancement Request

```markdown
## 概要

[機能の簡潔な説明]

## 背景・動機

[なぜこの機能が必要か]

## 提案する解決策

[どのように実現するか]

## 代替案

[検討した他のアプローチ]

## 影響を受けるファイル

- `path/to/file.py`
- `frontend/src/.../X.tsx`

## 対応内容

- [ ] 設計
- [ ] 実装
- [ ] テスト

## 備考

[追加情報があれば]
```

## Refactoring

```markdown
## 概要

[リファクタリングの簡潔な説明]

## 現状の問題

[現在のコードの問題点]

## 提案する改善

[どのように改善するか]

## 影響を受けるファイル

- `path/to/file.py`

## 対応内容

- [ ] タスク 1
- [ ] タスク 2

## リスク

[考えられるリスクと対策]

## 備考

[追加情報があれば]
```

## gh コマンド例

### Bug (Medium)

```bash
gh issue create \
  --title "🟡 [Stage 4 Kling] 429 が連続するとリトライ枯渇する" \
  --body "$(cat <<'EOF'
## 概要
Kling V3 の同時実行制限に当たると 5 回の backoff retry 後に FalClientError で停止する。

## 再現手順
1. 台本 `19_xxx.json` で `python3 main.py 19_xxx --resume 20260507_120000`
2. Stage 4 (Kling) を生成
3. 同時に他の Kling job が 2 件走っている状態にする

## 期待される動作
backoff 上限を超えても、後続シーンは別バッチでリトライする。

## 実際の動作
1 シーンの retry 枯渇でジョブ全体が失敗。

## 影響を受けるファイル
- `fal_video_client.py`
- `scene_gen.py`

## 環境
- macOS 14
- Python 3.12.4
- ffmpeg 7.x

## 対応内容
- [ ] 原因調査
- [ ] 修正実装 (= シーン単位のリトライキュー)
- [ ] テスト追加
EOF
)" \
  --label "🟡 Medium" \
  --label "scope:pipeline"
```

### Enhancement (Low)

```bash
gh issue create \
  --title "🟢 [analytics] hook_type 別 dashboard カードを追加" \
  --body "$(cat <<'EOF'
## 概要
v_performance を hook_type で集計した直近 14 日のカード表示を dashboard に足す。

## 背景・動機
台本タグから「どの型が伸びるか」を一覧化したい。closed-loop の前段。

## 提案する解決策
- `analytics.db` の v_performance に group by hook_type の view を追加
- `scripts/dashboard.py` でカードコンポーネント

## 対応内容
- [ ] 設計
- [ ] 実装
- [ ] テスト
EOF
)" \
  --label "🟢 Low" \
  --label "scope:analytics"
```

### Critical Bug (High)

```bash
gh issue create \
  --title "🔴 [緊急] YouTube refresh token が auto loop で expire しサイレント失敗" \
  --body "$(cat <<'EOF'
## 概要
auto loop の publish が refresh token expire 時に warning で続行してしまい、未公開のまま。

## 影響範囲
- `auto_loop.py` 経由の自動公開全件
- Stage 8 (publish) の YouTube ルート

## 再現手順
1. refresh token を意図的に invalidate する
2. cron で auto_loop.py を回す

## 対応内容
- [ ] 緊急対応 (= refresh 失敗で fail-fast + Slack 通知)
- [ ] 恒久対応 (= refresh token rotation 手順を `docs/plannings/` に)
EOF
)" \
  --label "🔴 High" \
  --label "scope:publish"
```
