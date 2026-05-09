# launchd jobs

ローカル Mac で動かす運用 cron 相当のジョブ定義。VPS には乗せない前提。

## ジョブ一覧

| plist                                           | 役割                                   | 周期       | 引数           |
| ----------------------------------------------- | -------------------------------------- | ---------- | -------------- |
| `com.short-movie-generator.fetch-metrics.plist` | YouTube/IG/TikTok の post_metrics 取得 | 1 時間ごと | なし           |
| `com.short-movie-generator.auto-loop.plist`     | auto_loop.py を queue 経由で実行       | 1 日 3 回  | queue 先頭 URL |

## セットアップ

各 plist の `<PROJECT_ROOT>` と `<PYTHON>` を置換してから配置する。

```bash
# 1. プロジェクト絶対パスと python 絶対パスを確認
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$(which python3)"

# 2. plist のプレースホルダを置換して LaunchAgents へ配置
for plist in com.short-movie-generator.fetch-metrics.plist \
             com.short-movie-generator.auto-loop.plist; do
  sed -e "s|<PROJECT_ROOT>|$PROJECT_ROOT|g" \
      -e "s|<PYTHON>|$PYTHON|g" \
      "ops/launchd/$plist" > "$HOME/Library/LaunchAgents/$plist"
done

# 3. 登録 (= load)
launchctl bootstrap gui/$UID \
  ~/Library/LaunchAgents/com.short-movie-generator.fetch-metrics.plist
launchctl bootstrap gui/$UID \
  ~/Library/LaunchAgents/com.short-movie-generator.auto-loop.plist

# 4. 動作確認 (= 即実行で 1 度走らせる)
launchctl kickstart gui/$UID/com.short-movie-generator.fetch-metrics

# 5. 状態確認
launchctl list | grep short-movie-generator
```

## auto_loop の queue 運用

`auto_loop.py` は 1 invocation = 1 URL で動くため、launchd plist は
`ops/launchd/auto_loop_queue.sh` を経由して `data/auto_loop_queue.txt` の
先頭から URL を取り出す。

```bash
# queue に追加 (= 1 行 1 URL)
echo "https://www.youtube.com/watch?v=xxxxx" >> data/auto_loop_queue.txt

# 確認
cat data/auto_loop_queue.txt
cat data/auto_loop_done.txt
```

queue が空なら exit 0 で即終了する (= 安全)。

## ログの場所

- `data/launchd_fetch-metrics.log` (= fetch_metrics の stdout/stderr)
- `data/launchd_auto-loop.log` (= auto_loop の stdout/stderr)

`tail -f` で監視する。`log_setup.py` で `LOG_FILE` を別途指定すれば
構造化ログも残せる。

## 停止 / アンロード

```bash
launchctl bootout gui/$UID \
  ~/Library/LaunchAgents/com.short-movie-generator.fetch-metrics.plist
launchctl bootout gui/$UID \
  ~/Library/LaunchAgents/com.short-movie-generator.auto-loop.plist
```

## トラブルシュート

- `launchctl list` に出てこない: `launchctl bootstrap` が失敗している。
  `launchctl print gui/$UID/<label>` でエラー内容確認。
- 走るが API key エラー: `.env` の DOTENV_PATH が正しいか / EnvironmentVariables
  に必要キーが入っているか。launchd は user shell の env を継承しないので、
  `.env` を auto_load する仕組み (= `python-dotenv` を main entry で `load_dotenv()`)
  が前提。
- 動くが何も書かれない: queue が空、または cap (`DAILY_COST_CAP_USD` 等) に
  当たって fail-fast している。launchd\_\*.log を確認。
