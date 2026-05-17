## Summary

<!-- 何を変えたか、なぜ変えたか を 1-3 行で -->

## Design doc 更新確認

実装が以下の領域に該当する場合、対応する設計 doc も同じ PR で更新してください
(= `docs/plannings/2026-05-17_comprehensive-refactoring-plan.md` §3.10 で要請)。
該当なしの場合はそのまま check 不要。

- [ ] `docs/developments/architecture.md` — レイヤ / 依存方向 / Stage × 外部 API マトリクスに変更がある
- [ ] `docs/developments/ubiquitous-language.md` — 新用語追加 / 既存用語の撤廃がある
- [ ] `CLAUDE.md` — Stage 仕様 / 操作フロー / 主要スキーマに変更がある
- [ ] `docs/abstract-screenplay-design.md` — analyze / compose スキーマに変更がある
- [ ] `docs/developments/coding-rules.md` — 新規規約・禁止パターンが追加された

doc 更新で「歴史的記録」型の半端注釈を残さない。旧情報は git history に任せて削除する。

## Test plan

- [ ] 関連テスト pass
- [ ] 既存テスト 80+ ファイル無傷
- [ ] 必要に応じて手動検証

🤖 Generated with [Claude Code](https://claude.com/claude-code)
