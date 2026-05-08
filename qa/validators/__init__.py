"""Phase 2 validator スイート。

各 validator は ``qa.validators.base.Validator`` のシグネチャに従う。
shared インターフェース:

    def check_<name>(ts_path: str, *, screenplay: dict | None = None,
                    **kwargs) -> list[ValidationResult]

返り値は per-scene / per-line で生成された ``ValidationResult`` の list。
fail = ``passed=False`` の要素だけ retry / qa_failures 記録の対象になる。

stage 別の発火マッピングは ``qa.registry.VALIDATORS_BY_STAGE``。
"""
from qa.validators.base import ValidationResult

__all__ = ["ValidationResult"]
