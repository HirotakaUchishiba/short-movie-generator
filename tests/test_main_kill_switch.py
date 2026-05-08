"""Phase 0: main.py の DISABLE_AUTO_LOOP kill-switch のテスト。

cron / auto_loop からの呼び出しを env で即停止できることを契約として固定する。
手動運用 (= env 未設定) では従来通り動く。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_disable_auto_loop_exits_with_nonzero(tmp_path) -> None:
    env = os.environ.copy()
    env["DISABLE_AUTO_LOOP"] = "1"
    env["TEMP_DIR"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "main.py")],
        env=env, cwd=ROOT, capture_output=True, text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    combined = proc.stdout + proc.stderr
    assert "DISABLE_AUTO_LOOP" in combined


def test_no_env_falls_through_to_help(tmp_path) -> None:
    """env 未設定なら従来通り (= help を出して exit 1)。kill-switch は発火しない。"""
    env = {k: v for k, v in os.environ.items()
           if k != "DISABLE_AUTO_LOOP"}
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "main.py")],
        env=env, cwd=ROOT, capture_output=True, text=True,
        timeout=30,
    )
    # 引数無しの場合は parser.print_help() + sys.exit(1)
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "DISABLE_AUTO_LOOP" not in combined


def test_disable_auto_loop_accepts_truthy_variants(tmp_path) -> None:
    """DISABLE_AUTO_LOOP=true / yes でも kill-switch が発火する。

    config.AUTO_LOOP_ALLOW_PUBLIC など他 env と真偽値解釈を統一するための gate。
    """
    for value in ("true", "True", "yes", " 1 "):
        env = os.environ.copy()
        env["DISABLE_AUTO_LOOP"] = value
        env["TEMP_DIR"] = str(tmp_path)
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "main.py")],
            env=env, cwd=ROOT, capture_output=True, text=True,
            timeout=30,
        )
        assert proc.returncode == 2, f"value={value!r} should trigger kill-switch"
        combined = proc.stdout + proc.stderr
        assert "DISABLE_AUTO_LOOP" in combined


def test_disable_auto_loop_falsy_values_do_not_block(tmp_path) -> None:
    """DISABLE_AUTO_LOOP=0 / false / 空文字 は kill-switch 発火しない。"""
    for value in ("", "0", "false", "no"):
        env = os.environ.copy()
        env["DISABLE_AUTO_LOOP"] = value
        env["TEMP_DIR"] = str(tmp_path)
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "main.py")],
            env=env, cwd=ROOT, capture_output=True, text=True,
            timeout=30,
        )
        # kill-switch は通って、引数無しなので help + exit 1
        assert proc.returncode == 1, f"value={value!r} should NOT trigger kill-switch"
