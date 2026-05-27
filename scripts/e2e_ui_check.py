"""Phase 6: preview_server + frontend/dist を起動し Playwright で UI を検証する E2E。

    python3 scripts/e2e_ui_check.py [--screenshot OUT.png] [--timeout 40] [--port 5555]

preview_server をサブプロセス起動 → chromium で開く → タイトル / ルート要素を確認 →
スクショ保存 → サーバ終了。動画の中身検証は validator が担うので、本 E2E は
「UI が壊れていないか (= 配信・描画される)」の生存確認に限定する。

CI 非対象 (= サーバ + ブラウザ起動が重い)。ローカル / 明示実行向け。playwright と
chromium が無ければ終了コード 2 で graceful に抜ける。
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _wait_port(host: str, port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.5)
    return False


def run(screenshot: str, timeout: int, port: int) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 未導入: pip install playwright && python3 -m playwright "
              "install chromium")
        return 2

    proc = subprocess.Popen(
        [sys.executable, "preview_server.py"],
        cwd=str(ROOT), env=dict(os.environ),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        if not _wait_port("127.0.0.1", port, timeout):
            out = b""
            if proc.stdout:
                out = proc.stdout.read1(2000) if hasattr(proc.stdout, "read1") else b""
            print(f"FAIL: server did not start on :{port}\n"
                  f"{out.decode(errors='replace')}")
            return 1
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 420, "height": 900})
                page.goto(f"http://127.0.0.1:{port}",
                          wait_until="networkidle", timeout=timeout * 1000)
                title = page.title()
                root_count = page.locator("#root").count()
                body_excerpt = page.inner_text("body")[:160].replace("\n", " ")
                page.screenshot(path=screenshot, full_page=False)
            finally:
                browser.close()
        print(f"OK title={title!r} root_elements={root_count} "
              f"screenshot={screenshot}")
        print(f"body_excerpt={body_excerpt!r}")
        return 0
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(prog="e2e_ui_check")
    parser.add_argument("--screenshot", default="/tmp/ui_e2e.png")
    parser.add_argument("--timeout", type=int, default=40)
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()
    return run(args.screenshot, args.timeout, args.port)


if __name__ == "__main__":
    sys.exit(main())
