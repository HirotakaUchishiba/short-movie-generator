"""``data/pricebook.json`` (運用者管理の単価データ) の読み込み。

ソースコードに単価ハードコードを置かない方針のため、すべての単価情報は
このモジュール経由で外部 JSON から読み込む。

環境変数:
    PRICEBOOK_PATH  pricebook.json の path 上書き (test / 運用切替用)
    JPY_PER_USD     為替レート上書き (= pricebook.json の jpy_per_usd より優先)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "pricebook.json"


def _path() -> Path:
    return Path(os.environ.get("PRICEBOOK_PATH", _DEFAULT_PATH))


def load() -> dict[str, Any]:
    """pricebook.json 全体を辞書として返す。"""
    path = _path()
    if not path.exists():
        raise FileNotFoundError(f"pricebook not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_unit_prices(provider: str, model: str) -> dict[str, float]:
    """``provider × model`` の単価辞書を返す (メタ情報 ``source`` は除去済み)。

    未登録なら ``KeyError``。
    """
    book = load()
    providers = book.get("providers", {})
    if provider not in providers:
        raise KeyError(f"unknown provider: {provider}")
    models = providers[provider]
    if model not in models:
        raise KeyError(f"unknown model: {provider}/{model}")
    entry = dict(models[model])
    entry.pop("source", None)
    return {k: float(v) if isinstance(v, (int, float)) else v for k, v in entry.items()}


def jpy_per_usd() -> float:
    """為替レート。環境変数 ``JPY_PER_USD`` > ``pricebook.jpy_per_usd``。"""
    env = os.environ.get("JPY_PER_USD")
    if env is not None:
        return float(env)
    book = load()
    return float(book.get("jpy_per_usd", 150.0))


def list_models(provider: str) -> list[str]:
    """指定 provider の登録モデル名一覧。未登録 provider なら空リスト。"""
    providers = load().get("providers", {})
    return list(providers.get(provider, {}).keys())
