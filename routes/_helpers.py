"""routes/* で共有する純関数ヘルパ。preview_server からも import される。

Blueprint 分割の途中段階で `preview_server._validate_ts` 等が複数 module から
参照されるのを避けるため、シグネチャ stable な util をここに集約する。
"""
from __future__ import annotations

import os
import re

from flask import abort

import config


_TS_PATTERN = re.compile(r"^[\w\-]+$")


def validate_ts(ts: str) -> str:
    """TS 文字列が ``^[\\w\\-]+$`` に従うか検証し、そのまま返す。NG なら 400。"""
    if not _TS_PATTERN.match(ts):
        abort(400, "不正なタイムスタンプ")
    return ts


def ts_path(ts: str, *, temp_dir: str | None = None) -> str:
    """``temp/<ts>`` の絶対パスを返す。``temp_dir`` を渡すとそれを優先。"""
    base = temp_dir if temp_dir is not None else config.TEMP_DIR
    return os.path.join(base, ts)


def safe_join(base: str, *parts: str) -> str:
    """ディレクトリトラバーサル防止。base 配下を超える結果は abort 400。"""
    p = os.path.realpath(os.path.join(base, *parts))
    if (
        not p.startswith(os.path.realpath(base) + os.sep)
        and p != os.path.realpath(base)
    ):
        abort(400, "不正なパス")
    return p


def load_screenplay_for_project(
    ts: str, *, temp_dir: str | None = None,
) -> tuple[dict, str]:
    """temp_dir/<TS>/screenplay.json (= immutable snapshot) を読み込む。

    台本は project 作成時に temp/<TS>/screenplay.json にコピーされ、
    以後そのファイルだけが正となる。template (= screenplays/<name>.json)
    が外部で書き換わっても進行中 project には影響しない。

    Returns: (screenplay dict, original template name)
    """
    import staged_pipeline

    project_path = ts_path(ts, temp_dir=temp_dir)
    meta = staged_pipeline.read_metadata(project_path)
    if not meta:
        abort(404, "プロジェクトのmetadataがありません")
    name = meta.get("screenplay_template_name") or meta.get("screenplay_name")
    if not name:
        abort(404, "metadataにscreenplay_template_name/nameがありません")
    try:
        sp = staged_pipeline.load_project_screenplay(project_path)
    except FileNotFoundError:
        abort(404, "プロジェクトの screenplay.json snapshot が見つかりません")
    return sp, name
