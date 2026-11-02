r"""探针：验证「会话右上角删除按钮 → 确认弹窗」的完整交互。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_shot import PY, ROOT, wait_health  # noqa: E402

OUT = ROOT / "logs" / "shots_dialog"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    port = 8596
    log = open(ROOT / "logs" / "ui_probe_delete.log", "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [str(PY), "-m", "streamlit", "run", "app.py", "--server.headless=true",
         f"--server.port={port}", "--server.fileWatcherType=none"],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    if not wait_health(port):
        print("FAIL: server not healthy")
        proc.terminate()
        return 1
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True)
            pg = b.new_page(viewport={"width": 1480, "height": 950})
            pg.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(2500)

            print(
                "candidates:",
                pg.locator('[data-testid="stPills"] button').count(),
                pg.locator('[data-testid="stButtonGroup"] button').count(),
            )
            pills = pg.locator(
                'section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button, '
                'section[data-testid="stSidebar"] [data-testid="stPills"] button'
            )
            print("pills:", pills.count())
            if pills.count():
                pills.first.click()
                pg.wait_for_timeout(2500)
            pg.screenshot(path=str(OUT / "1_会话页头.png"))

            info = pg.evaluate(
                """() => {
                  const head = document.querySelector('.st-key-qa_head');
                  const all = [...document.querySelectorAll('button')].map(b => (b.getAttribute('aria-label')||b.innerText||'').slice(0,20));
                  return {
                    headFound: !!head,
                    headTag: head ? head.dataset.testid || head.className : null,
                    headButtons: head ? head.querySelectorAll('button').length : -1,
                    sampleButtons: all.slice(0, 14),
                  };
                }"""
            )
            print("head info:", info)
            detail = pg.evaluate(
                """() => [...document.querySelectorAll('.st-key-qa_head button')].map(b => {
                  const r = b.getBoundingClientRect();
                  return {text: (b.innerText||'').slice(0,20), w: Math.round(r.width), h: Math.round(r.height),
                          x: Math.round(r.x), y: Math.round(r.y), cls: b.className.slice(0,60)};
                })"""
            )
            print("head buttons:", detail)
            btn = pg.locator('.st-key-qa_head button').first
            print("delete button visible:", btn.is_visible())
            btn.click()
            pg.wait_for_timeout(1500)
            dialog = pg.locator('[data-testid="stDialog"]')
            print("dialog count:", dialog.count())
            pg.screenshot(path=str(OUT / "2_确认弹窗.png"))

            print("dialog text:", dialog.inner_text()[:120].replace("\n", " / "))
            buttons = dialog.locator("button")
            print("dialog buttons:", buttons.count())
            for i in range(buttons.count()):
                print("  ", i, buttons.nth(i).inner_text().strip()[:12])
            buttons.nth(2).click()  # 0/1 是弹窗右上角关闭，2 是「取消」
            pg.wait_for_timeout(1500)
            print("dialog after cancel:", pg.locator('[data-testid="stDialog"]').count())
            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())