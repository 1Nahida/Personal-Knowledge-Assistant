"""探针：PyMuPDF 生成含中文的 PDF，找出能正确往返（写入->提取）的字体写法。

候选：
  1. insert_text(fontname="china-s")          —— MuPDF 内置 CJK 简体 sans
  2. insert_text(fontname="china-ss")         —— 内置 CJK 简体 serif
  3. TextWriter + pymupdf.Font("cjk")         —— 官方 CJK 回退字体
  4. insert_textbox(fontname="china-s")       —— 内置 CJK + 自动换行
判据：提取文本与原文完全相等（去除行尾空白后）。结果写 docs/_probe_pdf_cjk_out.txt。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pymupdf  # noqa: E402

OUT = ROOT / "docs" / "_probe_pdf_cjk_out.txt"

SAMPLE = [
    "PKA 端到端测试文档（PDF）",
    "ChromaDB 是一个纯本地的嵌入式向量数据库，无需额外部署，",
    "适合个人知识库场景。",
    "本段落用于验证 PDF 解析与页码引用。",
]


def extract(path: Path) -> list[str]:
    with pymupdf.open(str(path)) as doc:
        return [p.get_text().strip() for p in doc]


def main() -> int:
    lines: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="pkapdfck"))

    def record(name: str, path: Path) -> None:
        try:
            got = extract(path)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"----- {name}: EXTRACT ERROR {type(exc).__name__}: {exc}")
            return
        joined = "\n".join(got)
        ok = all(any(seg in g for g in got) for seg in SAMPLE[:2])
        lines.append(f"----- {name} | pages={len(got)} | {'OK' if ok else 'BAD'}")
        for i, g in enumerate(got, 1):
            lines.append(f"  p{i}: {g!r}")
        lines.append("")

    # 1/2: 内置 CJK 字体名
    for fname in ("china-s", "china-ss", "japan", "korea"):
        path = tmp / f"builtin_{fname}.pdf"
        try:
            doc = pymupdf.open()
            for seg in SAMPLE:
                page = doc.new_page()
                page.insert_text((72, 100), seg, fontname=fname, fontsize=14)
            doc.save(str(path))
            doc.close()
        except Exception as exc:  # noqa: BLE001
            lines.append(f"----- builtin {fname}: BUILD ERROR {type(exc).__name__}: {exc}\n")
            continue
        record(f"builtin fontname={fname}", path)

    # 3: TextWriter + Font("cjk")
    path = tmp / "tw_cjk.pdf"
    try:
        doc = pymupdf.open()
        font = pymupdf.Font("cjk")
        for seg in SAMPLE:
            page = doc.new_page()
            tw = pymupdf.TextWriter(page.rect)
            tw.append((72, 100), seg, font=font, fontsize=14)
            tw.write_text(page)
        doc.save(str(path))
        doc.close()
        record('TextWriter + Font("cjk")', path)
    except Exception as exc:  # noqa: BLE001
        lines.append(f'----- TextWriter + Font("cjk"): ERROR {type(exc).__name__}: {exc}\n')

    # 4: insert_textbox 自动换行（更接近真实多行文档）
    path = tmp / "textbox_china_s.pdf"
    try:
        doc = pymupdf.open()
        page = doc.new_page()
        rect = pymupdf.Rect(50, 60, 545, 780)
        rv = page.insert_textbox(rect, "\n\n".join(SAMPLE), fontname="china-s", fontsize=12)
        doc.save(str(path))
        doc.close()
        lines.append(f"----- insert_textbox china-s rv={rv}")
        record("insert_textbox fontname=china-s", path)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"----- insert_textbox: ERROR {type(exc).__name__}: {exc}\n")

    # 5: 对照组 —— 默认字体（当前 e2e 用的写法）
    path = tmp / "default.pdf"
    doc = pymupdf.open()
    for seg in SAMPLE:
        page = doc.new_page()
        page.insert_text((72, 100), seg, fontsize=14)
    doc.save(str(path))
    doc.close()
    record("DEFAULT (no fontname) —— 现状写法", path)

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
