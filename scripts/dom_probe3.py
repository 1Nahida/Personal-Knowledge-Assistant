r"""探针 3：看导航容器的 DOM 结构与间距来源。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_shot import PY, ROOT, wait_health  # noqa: E402


def main() -> int:
    port = 8593
    log = open(ROOT / "logs" / "dom_probe3.log", "w", encoding="utf-8", errors="replace")
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
                  const nav = document.querySelector('.st-key-pka_nav');
                  if (!nav) return {err: 'no nav'};
                  const cs = getComputedStyle(nav);
                  const kids = [...nav.children].map(c => ({
                    tag: c.tagName, testid: c.dataset.testid || null,
                    cls: c.className.slice(0, 80), gap: getComputedStyle(c).gap,
                    h: Math.round(c.getBoundingClientRect().height),
                  }));
                  const wrap = nav.parentElement;
                  return {
                    navTag: nav.tagName, navTestid: nav.dataset.testid,
                    navDisplay: cs.display, navGap: cs.gap, navH: Math.round(nav.getBoundingClientRect().height),
                    kids,
                    parentTestid: wrap ? wrap.dataset.testid : null,
                    parentGap: wrap ? getComputedStyle(wrap).gap : null,
                  };
                }"""
            )
            import json
            print(json.dumps(out, ensure_ascii=False, indent=1))
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
