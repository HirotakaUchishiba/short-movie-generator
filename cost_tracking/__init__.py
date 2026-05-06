"""コスト記録 + 動的見積もりモジュール。

ソースコードに単価ハードコードを置かない。すべての単価は ``data/pricebook.json``
(運用者管理の外部データ) から読み込む。動的見積もりは ``data/cost_records.jsonl``
の実コスト履歴のみを参照し、履歴が不足するときは catalog にフォールバックせず
``insufficient`` を返す。

責務分離:
  - ``pricebook``  単価データ (公式料金準拠) の読み込み
  - ``records``    CostRecord の永続化 (JSONL)
  - ``pricing``    units → USD の純粋計算関数
  - ``recorder``   各 stage 用の記録 facade
  - ``estimator``  履歴ベースの動的見積もり
  - ``report``     プロジェクト / 全体の集計レポート
"""
from cost_tracking import (  # noqa: F401
    estimator,
    pricebook,
    pricing,
    recorder,
    records,
    report,
)
