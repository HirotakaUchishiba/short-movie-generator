# 自律自走 + 異種 cross-critique 運用 runbook

最終更新: 2026-05-27
関連設計: `docs/plannings/2026-05-26_verification-automation.md`
ステータス: ドラフト (Phase 1-2 validator 実装済み、自走インフラは手順整備段階)

検証 validator (Phase 1-2) の上で、人間レビューゼロの自律自走を回すための運用手順。

## 1. UI 生存確認 (Phase 3)

動画の中身検証は validator (`qa/validators/`) が担うため、UI は「壊れていないか」だけを確認する。

- **run / verify スキル**で preview UI の主要導線を確認:
  - `python3 preview_server.py` (= http://127.0.0.1:5555) + `cd frontend && npm run dev`
  - 確認項目: 各 Stage ページの表示、動画/音声プレイヤーの再生、承認/却下/再生成ボタンの動作
- **Playwright (将来、必要時のみ)**: `frontend/` に `@playwright/test` を入れ、Stage ごとの smoke test (プレイヤー要素の存在・ボタン押下) を組む。現状は run/verify で足りるため**実導入は見送り** (= 動画の正しさはファイル解析 validator が担保し、E2E は薄く保つ)。

## 2. 自走オーケストレーション (Phase 4)

- **`/goal` 完了条件の雛形** (= 会話出力で証明可能・副作用制約つき):

  ```
  /goal <タスク> を feature ブランチで実装し、pytest tests/ が全 pass、
  ruff check . がクリーン、overlay 再合成後に subtitle_timing validator が
  fail 0 件であることを各コマンド出力で示した上で squash マージせよ。
  main 直 push・動画/背景/TTS/リップシンク再生成・公開はしない。
  ```

- **Auto Mode** がターン内のツール承認を、`/goal` がターン間の手動操作を省く (= ユーザー設定)。
- **暴走防止 (任意)**: `--max-turns` / `--max-budget-usd`。完全無制限 (ユーザー決定 2026-05-26) では `/usage` の手動監視が唯一の歯止め。

## 3. 異種 cross-critique (Phase 4 / Codex 併用)

盲点共有を断つため、実装とレビューを**別基盤モデル**に分ける (= 設計書 §3.7、SLEAN 3 フェーズ)。

1. **independent**: Claude が `code-review` スキルで自己 diff をレビュー / Codex が同じ diff を独立レビュー
   - Codex 側: `codex review` (= 非対話コードレビュー)。`git diff main...HEAD` 相当を別モデル (GPT 系) が critique
2. **cross-critique**: 両者の指摘を突き合わせる
3. **arbitration**: `pytest` / `ruff` / 該当 validator の客観検証で決着 (= 主観合意でなく数値)
   - 合格条件: テスト緑 + validator fail 0 + 両レビューの重大指摘ゼロ

## 4. 権限設定 (完全無制限、ユーザー決定 2026-05-26)

- `.claude/settings.json` の `permissions` を全許可にし `deny` を設けない。
- **注意**: 全許可 / bypassPermissions は進行中セッションの安全性にも影響する重大設定。実際の有効化は**運用者の明示操作**で行う (= 本 runbook では方針記載に留める)。
- 唯一の歯止め: `/usage` 監視、`Escape` / `/goal clear`。

## 5. 自動マージ (Phase 4)

- feature ブランチ → `gh pr create` → cross-critique 合格 → `gh pr merge --squash` (= revert 容易)。
- 完全無制限では branch protection を設けない (ユーザー決定)。後から戻す場合は CI を required check 化 (= 人間を介在させない自動ブレーキ、設計書 §8)。

## 6. このセッションでの実演結果

(レビュー・マージ実行後に追記する)
