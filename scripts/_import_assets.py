
import sys, shutil, os
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = Path(r"<桌面>\课程笔记\PKA个人项目开发\images")
print("images dir exists:", src.exists())
files = sorted([p for p in src.glob("*.png")]) if src.exists() else []
print("png count:", len(files))
for p in files:
    print("  ", p.name, round(p.stat().st_size/1024), "KB")

dst = Path(r"<项目根>\docs\design-refs")
dst.mkdir(parents=True, exist_ok=True)
n = 0
for p in files:
    shutil.copy2(p, dst / p.name)
    n += 1
print("copied:", n, "->", dst)

avatar = Path(r"<桌面>\课程笔记\demo素材\image_demo\dafeiyu (1).jpg")
print("avatar exists:", avatar.exists())
if avatar.exists():
    from PIL import Image
    im = Image.open(avatar)
    print("  avatar size:", im.size, im.mode)
    adir = Path(r"<项目根>\docs\assets")
    adir.mkdir(parents=True, exist_ok=True)
    # 居中裁成正方形再缩到 512，作为圆形图标底图
    w, h = im.size
    s = min(w, h)
    im2 = im.crop(((w-s)//2, (h-s)//2, (w-s)//2+s, (h-s)//2+s)).convert("RGBA").resize((512, 512), Image.LANCZOS)
    out = adir / "avatar.png"
    im2.save(out)
    print("  saved:", out, round(out.stat().st_size/1024), "KB")
