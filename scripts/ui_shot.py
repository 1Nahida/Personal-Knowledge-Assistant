r"""UI 截图工具：用本机 Edge（Playwright channel=msedge，无需下载浏览器）给四个页面拍照。

用法：
    python scripts/ui_shot.py                 # 临时端口起一个应用实例，拍完自动关
    python scripts/ui_shot.py --port 8513 --out logs/shots
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"

NAV = ["智能问答", "知识库", "日志"]


def wait_health(port: int, timeout: float = 90.0) -> bool:
    url = f"http://127.0.0.1:{port}/_stcore/health"
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def ask_and_shoot(port: int, out: Path, question: str) -> Path:
    """真实提问一次，等回答渲染完再截图（用于校准消息气泡与引用样式）。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1480, "height": 950})
        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        box = page.get_by_placeholder("就你的资料提个问题，回车发送…")
        box.click()
        box.fill(question)
        box.press("Enter")
        try:
            page.wait_for_selector('[data-testid="stChatMessage"]', timeout=90000)
            page.wait_for_timeout(3000)
        except Exception as exc:
            print(f"  [warn] 等待回答超时: {type(exc).__name__}")
        f = out / "5_问答结果.png"
        page.screenshot(path=str(f), full_page=True)
        print(f"  shot -> {f.name}")
        browser.close()
    return f


def shoot(port: int, out: Path, click: str = "", doc: str = "") -> list[Path]:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1480, "height": 950}, device_scale_factor=1)
        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        for name in NAV:
            try:
                page.get_by_role("button", name=name, exact=True).first.click(timeout=8000)
                page.wait_for_timeout(1800)
            except Exception as exc:
                print(f"  [warn] 切换 {name} 失败: {type(exc).__name__}")
            f = out / f"{NAV.index(name) + 1}_{name}.png"
            page.screenshot(path=str(f), full_page=True)
            shots.append(f)
            print(f"  shot -> {f.name}")
            # 选中某个知识库文件夹，再拍一张（树上的缩进与选中态）
            if name == "知识库" and click:
                try:
                    page.get_by_role("button", name=click, exact=False).first.click(timeout=8000)
                    page.wait_for_timeout(1500)
                    f2 = out / f"{NAV.index(name) + 1}b_文件夹_{click}.png"
                    page.screenshot(path=str(f2), full_page=True)
                    shots.append(f2)
                    print(f"  shot -> {f2.name}")
                except Exception as exc:
                    print(f"  [warn] 选中文件夹 {click} 失败: {type(exc).__name__}")
            # 点开文件夹里的某个文件，拍文件详情（内容预览）
            if name == "知识库" and doc:
                try:
                    page.get_by_role("button", name=doc, exact=False).first.click(timeout=8000)
                    page.wait_for_timeout(1500)
                    f3 = out / f"{NAV.index(name) + 1}c_文件_{doc}.png"
                    page.screenshot(path=str(f3), full_page=True)
                    shots.append(f3)
                    print(f"  shot -> {f3.name}")
                except Exception as exc:
                    print(f"  [warn] 打开文件 {doc} 失败: {type(exc).__name__}")
        browser.close()
    return shots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8577)
    ap.add_argument("--out", default=str(ROOT / "logs" / "shots"))
    ap.add_argument("--url", default="", help="复用已在运行的应用，不再自己起进程")
    ap.add_argument("--ask", default="", help="额外真实提问一句并截图（会调用模型）")
    ap.add_argument("--click", default="", help="知识库页额外点选该文件夹再截一张")
    ap.add_argument("--doc", default="", help="再点开该文件，拍一张文件详情（内容预览）")
    ap.add_argument("--data-dir", default="", help="用独立数据目录起实例（预览/演示，不动真实库）")
    args = ap.parse_args()
    out = Path(args.out)

    proc = None
    if not args.url:
        log = open(ROOT / "logs" / "ui_shot_server.log", "w", encoding="utf-8", errors="replace")
        env = dict(**__import__("os").environ)
        if args.data_dir:
            env["PKA_DATA_DIR"] = str(ROOT / args.data_dir)
            env["PKA_LOG_DIR"] = str(ROOT / args.data_dir / "logs")
        proc = subprocess.Popen(
            [str(PY), "-m", "streamlit", "run", "app.py",
             "--server.headless=true", f"--server.port={args.port}",
             "--browser.gatherUsageStats=false", "--server.fileWatcherType=none"],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env,
        )
        if not wait_health(args.port):
            print("FAIL: 应用未能启动，见 logs\\ui_shot_server.log")
            proc.terminate()
            return 1
        port = args.port
    else:
        port = int(args.url.rstrip("/").rsplit(":", 1)[-1])

    try:
        shots = shoot(port, out, click=args.click, doc=args.doc)
        if args.ask:
            shots.append(ask_and_shoot(port, out, args.ask))
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
    print(f"OK: {len(shots)} 张 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
