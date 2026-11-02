r"""探针 4：检查问答页容器 flex/min-height 是否生效。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_shot import PY, ROOT, wait_health  # noqa: E402


def main() -> int:
    port = 8594
    log = open(ROOT / "logs" / "dom_probe4.log", "w", encoding="utf-8", errors="replace")
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
                  const el = document.querySelector('.st-key-qa_page');
                  if (!el) return {err: 'no qa_page'};
                  const cs = getComputedStyle(el);
                  const kids = [...el.children].map((c, i) => ({
                    i, testid: c.dataset.testid || null,
                    cls: (c.className || '').toString().slice(0, 60),
                    h: Math.round(c.getBoundingClientRect().height),
                    mt: getComputedStyle(c).marginTop,
                  }));
                  return {display: cs.display, minHeight: cs.minHeight, h: Math.round(el.getBoundingClientRect().height),
                          flexDir: cs.flexDirection, kids};
                }"""
            )
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
