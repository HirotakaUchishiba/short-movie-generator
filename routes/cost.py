"""``/api/cost/*`` の Blueprint (= 単価 / 動的見積もり / レポート)。

`preview_server.py` から段階的に切り出した最初の Blueprint。caller (= フロント
の `api.cost.*`) には URL も response も変更なし。
"""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, request

from cost_tracking import estimator as cost_estimator
from cost_tracking import pricebook as cost_pricebook
from cost_tracking import report as cost_report

cost_bp = Blueprint("cost", __name__)


@cost_bp.route("/api/cost/pricebook", methods=["GET"])
def api_cost_pricebook():
    """単価カタログ (運用者管理) を JSON で返す。"""
    return jsonify({
        "pricebook": cost_pricebook.load(),
        "jpy_per_usd": cost_pricebook.jpy_per_usd(),
    })


def _estimate_for_stage(stage: str, args) -> tuple[dict, int]:
    """``/api/cost/estimate/<stage>`` の stage 別ロジック (純粋関数)。"""
    model = args.get("model")
    if not model:
        return {"error": "model required"}, 400
    try:
        if stage == "tts":
            est = cost_estimator.estimate_tts(
                characters=int(args.get("characters", 0)),
                model=model,
            )
        elif stage == "bg":
            est = cost_estimator.estimate_imagen(
                image_count=int(args.get("image_count", 1)),
                model=model,
            )
        elif stage == "kling":
            est = cost_estimator.estimate_kling(
                duration_sec=float(args.get("duration_sec", 0)),
                model=model,
            )
        elif stage == "lipsync":
            est = cost_estimator.estimate_lipsync(
                duration_sec=float(args.get("duration_sec", 0)),
                model=model,
            )
        elif stage == "analyze":
            est = cost_estimator.estimate_analyze(
                input_tokens=int(args.get("input_tokens", 0)),
                output_tokens=int(args.get("output_tokens", 0)),
                model=model,
            )
        else:
            return {"error": f"unknown stage: {stage}"}, 400
    except (ValueError, TypeError) as e:
        return {"error": str(e)}, 400
    return asdict(est), 200


@cost_bp.route("/api/cost/estimate/<stage>", methods=["GET"])
def api_cost_estimate(stage):
    """動的見積もり (履歴 only)。履歴が ``MIN_HISTORY_SAMPLES`` 未満なら ``confidence=insufficient``。"""
    payload, status = _estimate_for_stage(stage, request.args)
    return jsonify(payload), status


@cost_bp.route("/api/cost/median/<stage>", methods=["GET"])
def api_cost_median(stage):
    """履歴から per-unit cost の median を返す (frontend で rate × units 計算用)。"""
    model = request.args.get("model")
    if not model:
        return jsonify({"error": "model required"}), 400
    try:
        rate = cost_estimator.median_rate(stage, model)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(asdict(rate))


@cost_bp.route("/api/cost/report/project/<ts>", methods=["GET"])
def api_cost_report_project(ts):
    """プロジェクト別の実コストレポート。"""
    return jsonify(asdict(cost_report.report_for_project(ts)))


@cost_bp.route("/api/cost/report", methods=["GET"])
def api_cost_report_overall():
    """全体レポート。``?since=<ISO8601>`` で期間絞り込み可。"""
    since = request.args.get("since")
    return jsonify(asdict(cost_report.report_overall(since=since)))
