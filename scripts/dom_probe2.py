r"""一次性 DOM 细节探针：看按钮内部结构与计算样式，用于精确定位 CSS 选择器。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_shot import PY, ROOT, wait_health  # noqa: E402


def main() -> int:
    port = 8592
    log = open(ROOT / "logs" / "dom_probe2.log", "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [str(PY), "-m", "streamlit", "run", "app.py", "--server.headless=true",
         f"--server.port={port}", "--server.fileWatcherType=none"],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    if not wait_health(port):
        print("FAIL")
        proc.terminate()
        return 1
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True)
            pg = b.new_page(viewport={"width": 1480, "height": 950})
            pg.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(2500)
            out = pg.evaluate(
                """() => {
                  const res = {};
                  const ex = document.querySelector('.st-key-ex_0');
                  res.exExists = !!ex;
                  res.exTag = ex ? ex.tagName + '.' + ex.className : null;
                  const exBtn = ex ? ex.querySelector('button') : null;
                  res.exBtnHTML = exBtn ? exBtn.outerHTML.slice(0, 420) : null;
                  res.exJustify = exBtn ? getComputedStyle(exBtn).justifyContent : null;
                  const nav = document.querySelector('.st-key-nav_qa');
                  res.navExists = !!nav;
                  const navBtn = nav ? nav.querySelector('button') : (document.querySelector('section[data-testid="stSidebar"] button') || null);
                  res.navBtnHTML = navBtn ? navBtn.outerHTML.slice(0, 420) : null;
                  res.navJustify = navBtn ? getComputedStyle(navBtn).justifyContent : null;
                  const navWrap = document.querySelector('.st-key-pka_nav [data-testid="stVerticalBlock"]');
                  res.navGap = navWrap ? getComputedStyle(navWrap).gap : null;
                  return res;
                }"""
            )
            for k, v in out.items():
                print(f"{k}: {v}")
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
