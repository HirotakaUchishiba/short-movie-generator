"""fal_client の subscribe() を threading watchdog でラップしてタイムアウトを強制する。

fal_client.subscribe() は内部で完了まで永久にポーリングする (タイムアウトを
持たない) ため、fal.ai 側の stuck job (= 202 Accepted が長時間続く) や
キュー詰まりで Python プロセスが永久に待機してしまう問題があった。

このモジュールは fn() を別 thread で実行し、timeout_sec 内に返らなければ
FalJobTimeoutError を上げる。スレッド自体は daemon=True で main プロセス
終了時に消えるが、Python の制約上 thread 内の blocking I/O は中断できない
ため、タイムアウト後もしばらくはバックグラウンドでポーリングが続く可能性
がある (= 限定的なリソースリーク)。これは Python の限界。

呼出例:
    result = run_with_timeout(
        lambda: fal_client.subscribe(MODEL, arguments={...}),
        timeout_sec=600,
        name="kling-scene-2",
    )
"""

import logging
import threading

logger = logging.getLogger(__name__)


class FalJobTimeoutError(TimeoutError):
    """fal ジョブが指定タイムアウト内に完了しなかった。"""


def run_with_timeout(fn, timeout_sec: float, name: str = "fal-job"):
    """fn() を別 thread で動かし timeout_sec 内に終わらなければ raise する。

    Args:
        fn: 引数なしの呼出可能オブジェクト
        timeout_sec: 秒単位のタイムアウト
        name: ログ・スレッド名識別子

    Returns:
        fn() の戻り値

    Raises:
        FalJobTimeoutError: timeout_sec を超えても fn が完了しない
        BaseException: fn() が投げた例外をそのまま再送出
    """
    result_holder: dict = {}
    error_holder: dict = {}
    done_event = threading.Event()

    def runner():
        try:
            result_holder["value"] = fn()
        except BaseException as e:
            error_holder["error"] = e
        finally:
            done_event.set()

    t = threading.Thread(target=runner, daemon=True, name=f"fal-{name}")
    t.start()

    completed = done_event.wait(timeout=timeout_sec)
    if not completed:
        logger.warning(
            "[fal_runner] %s が %.0fs 以内に完了しないため打ち切り (stuck job 疑い)。"
            "バックグラウンド thread は daemon で残り、プロセス終了時に消える",
            name, timeout_sec,
        )
        raise FalJobTimeoutError(
            f"{name} が {timeout_sec:.0f}s 以内に完了しませんでした (fal stuck job 疑い)"
        )

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder.get("value")
