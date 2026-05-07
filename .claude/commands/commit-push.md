# commit-push

Intelligently commit and push changes with appropriate granularity. ALWAYS use ultrathink when executing this command.

FORBIDDEN: NEVER use git reset, git clean, or any command that discards changes.

Execute the following steps:

1. ANALYZE all changes:

   ```bash
   git status --porcelain
   git diff --stat
   git diff --cached --stat
   ```

2. IDENTIFY logical groups:
   - Group by feature / fix
   - Group by module (= `pipeline core` / `frontend` / `analytics` / `final_import` / `platform_clients` / `scripts` / `tests` / `docs`)
   - Group by file type (= tests, docs, config)
   - Consider dependencies between changes

3. STAGE and COMMIT in logical units:
   - Use `git add -p` for partial staging when needed
   - Create atomic commits that represent single logical changes
   - Each commit should pass tests independently (= `pytest -k <related>` で当該領域だけでも回す)

4. COMMIT MESSAGE format (English, per global CLAUDE.md):

   ```
   <type>(<scope>): <description in English>

   <detailed explanation if needed>

   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   ```

   - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
   - Scopes (任意): `pipeline`, `analyze`, `analytics`, `final-import`, `publish`, `frontend`, `claude-code`, etc.

5. EXAMPLE workflow:

   ```bash
   # First commit: add new utility
   git add lipsync_client.py
   git commit -m "feat(pipeline): add Sync.so syncso-3 model option"

   # Second commit: documentation
   git add docs/developments/architecture.md
   git commit -m "docs: reflect new lipsync provider matrix"

   # Third commit: unrelated bug fix
   git add final_import/core.py
   git commit -m "fix(final-import): handle missing fingerprint gracefully"
   ```

6. VERIFY before push:
   - Review all commits: `git log --oneline -n 10`
   - Ensure no sensitive data (= API key / refresh token / `.env`)
   - Confirm branch is correct
   - Run `pytest --collect-only -q` to ensure no import-level breakage

7. PUSH to remote:

   ```bash
   git push origin <current-branch>
   ```

   - 初 push の場合は `-u` を付ける
   - protected branch (`main`) への直 push はしない

8. REPORT:
   - Number of commits created
   - Brief summary of each commit
   - Push confirmation with remote URL

IMPORTANT NOTES:

- Configuration changes should be separate from feature changes
- Test additions / modifications go with the code they test
- Never combine unrelated changes in one commit
- 「PR を作る」までは含まない (= 別途 `gh pr create`)
- destructive な操作 (= `git push --force`, `git rebase -i` でのコミット書き換え) は明示確認後のみ
