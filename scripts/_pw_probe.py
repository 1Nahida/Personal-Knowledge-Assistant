
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    for ch in ("msedge", "chrome"):
        try:
            b = p.chromium.launch(channel=ch, headless=True)
            pg = b.new_page(viewport={"width": 800, "height": 400})
            pg.set_content("<h1 style='font-family:sans-serif'>PKA smoke</h1>")
            pg.screenshot(path=f"logs/_pw_{ch}.png")
            print(f"{ch}: OK, version={b.version}")
            b.close()
        except Exception as e:
            print(f"{ch}: FAIL {type(e).__name__}: {str(e).splitlines()[0][:150]}")
