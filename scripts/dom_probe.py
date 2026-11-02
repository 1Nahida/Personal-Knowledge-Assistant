r"""DOM 探针：起一个应用实例，导出关键元素的 testid / st-key- 类名，供写 CSS 选择器用。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_shot import PY, ROOT, wait_health  # noqa: E402

import subprocess  # noqa: E402


def main() -> int:
    port = 8591
    log = open(ROOT / "logs" / "dom_probe_server.log", "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [str(PY), "-m", "streamlit", "run", "app.py", "--server.headless=true",
         f"--server.port={port}", "--server.fileWatcherType=none"],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    if not wait_health(port):
        print("FAIL: server not up")
        proc.terminate()
        return 1
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True)
            pg = b.new_page(viewport={"width": 1480, "height": 950})
            pg.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(3000)
            info = pg.evaluate(
                """() => {
                  const keys = new Set(), tids = new Set();
                  document.querySelectorAll('*').forEach(el => {
                    (el.classList || []).forEach(c => { if (c.startsWith('st-key-')) keys.add(c); });
                    if (el.dataset && el.dataset.testid) tids.add(el.dataset.testid);
                  });
                  const btns = [...document.querySelectorAll('section[data-testid="stSidebar"] button')]
                    .slice(0, 6).map(b => ({
                      text: b.innerText.slice(0, 20),
                      parentCls: b.closest('[class*="st-key-"]')?.className || '(none)',
                      kind: b.getAttribute('kind'),
                    }));
                  return {keys: [...keys], tids: [...tids].sort(), btns};
                }"""
            )
            print("ST-KEY CLASSES:", info["keys"])
            print("TESTIDS:", info["tids"])
            for x in info["btns"]:
                print("BTN:", x)
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
