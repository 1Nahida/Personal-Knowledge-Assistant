"""Phase 1 端到端冒烟测试（真实 Ollama：qwen2.5:7b + bge-m3）。

流程：服务探测 -> 入库（md + 生成的 pdf + 生成的 docx）-> 真实问答 x2 -> 校验。
运行：.venv\\Scripts\\python.exe scripts/e2e_phase1.py
退出码 0 = PASS。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pka.agents.ingestion import ingest_file  # noqa: E402
from pka.agents.qa_agent import QAAgent  # noqa: E402
from pka.config import get_settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402
from pka.core.model_factory import get_chat_model, probe_ollama  # noqa: E402

# Windows 控制台/重定向默认 GBK，中文日志会乱码：统一切到 UTF-8
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def make_sample_pdf(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    for i, line in enumerate(
        [
            "PKA 端到端测试文档（PDF）。",
            "ChromaDB 是一个纯本地的嵌入式向量数据库，无需额外部署，",
            "适合个人知识库场景。",
            "本段落用于验证 PDF 解析与页码引用。",
        ]
    ):
        page = doc.new_page()
        # fontname 必须是内置 CJK 字体：默认 Helvetica 无汉字字形，
        # 写入的中文会被替换成 '·' 占位符且提取时静默损坏（见 scripts/probe_pdf_cjk.py）
        page.insert_text((72, 100 + i * 20), line, fontname="china-s", fontsize=14)
    doc.save(str(path))
    doc.close()


def make_sample_docx(path: Path) -> None:
    from docx import Document

    d = Document()
    d.add_heading("PKA 端到端测试文档（DOCX）", level=1)
    d.add_paragraph(
        "本段用于验证 DOCX 解析入库：Ollama 在 Windows 上默认监听 11434 端口，"
        "qwen2.5:7b 是本项目默认问答模型。"
    )
    d.save(str(path))


def main() -> int:
    s = get_settings()
    failures: list[str] = []

    print("== 1. 服务与模型检查 ==")
    ok, msg = probe_ollama(s)
    print("  Ollama:", msg)
    if not ok:
        print("FAIL: Ollama 未就绪")
        return 1

    emb = None
    from pka.core.embeddings import get_embeddings

    emb = get_embeddings(s)
    v = emb.embed_query("中文嵌入测试")
    print(f"  Embedding: {s.embedding_model} dim={len(v)}")
    assert len(v) > 0

    model, provider = get_chat_model(s)
    print(f"  ChatModel: {getattr(model, 'model', '?')} ({provider})")

    print("\n== 2. 入库（3 种格式） ==")
    pdf_path = ROOT / "examples" / "_e2e_sample.pdf"
    docx_path = ROOT / "examples" / "_e2e_sample.docx"
    make_sample_pdf(pdf_path)
    make_sample_docx(docx_path)

    for f in (ROOT / "examples" / "python_装饰器与生成器笔记.md", pdf_path, docx_path):
        r = ingest_file(s, f)
        status = "OK" if r.ok else "FAIL"
        print(f"  [{status}] {f.name}: 块={r.chunks} 字符={r.chars} 耗时={r.elapsed_sec:.1f}s 主题={r.topic}")
        for w in r.warnings:
            print(f"      WARN: {w}")
        if not r.ok:
            failures.append(f"入库失败 {f.name}: {r.errors}")

    print(f"\n  库内总块数: {vectorstore.count(s)}")

    print("\n== 2.5 解析完整性（回读库内文本） ==")
    col = vectorstore.get_collection(s)
    for source, expect in (("_e2e_sample.pdf", "向量数据库"), ("_e2e_sample.docx", "11434")):
        got = "\n".join(col.get(where={"source": source}, include=["documents"])["documents"])
        garbled = got.count("···")
        good = expect in got and garbled == 0
        print(f"  {source}: 字符={len(got)} 缺字占位串={garbled} 期望片段={expect!r} -> {'OK' if good else 'BAD'}")
        if not good:
            failures.append(f"{source} 解析静默损坏（缺 {expect!r} 或含 '···' 占位符）")

    print("\n== 3. 真实问答 ==")
    agent = QAAgent(s)

    q1 = "Python 装饰器怎么实现？给一个最简例子。"
    t0 = time.time()
    res1 = agent.ask(q1)
    total1 = time.time() - t0
    print(f"\n  Q1: {q1}\n  回答:\n{res1.answer}")
    for c in res1.citations:
        print(f"  引用[{c.index}] {c.label()} score={c.score:.3f}")
    print(f"  耗时: LLM={res1.elapsed_sec:.1f}s 总={total1:.1f}s 模型={res1.provider}")
    if not res1.answer or len(res1.answer) < 20:
        failures.append("Q1 回答为空或过短")
    if not res1.citations:
        failures.append("Q1 无引用来源")

    q2 = "ChromaDB 是什么？需要额外部署服务吗？"
    t0 = time.time()
    res2 = agent.ask(q2)
    total2 = time.time() - t0
    print(f"\n  Q2: {q2}\n  回答:\n{res2.answer}")
    for c in res2.citations:
        print(f"  引用[{c.index}] {c.label()} score={c.score:.3f}")
    print(f"  耗时: LLM={res2.elapsed_sec:.1f}s 总={total2:.1f}s 模型={res2.provider}")
    if not res2.answer:
        failures.append("Q2 回答为空")
    if not any("ChromaDB" in c.snippet or "ChromaDB" in c.source for c in res2.citations):
        failures.append("Q2 未检索到 PDF 内容")
    # 回答质量：摘录里有明确定义，模型不得宣称“暂未收录”，且需复述关键结论
    if "暂未收录" in res2.answer:
        failures.append("Q2 回答错误宣称暂未收录（摘录[1] 含 ChromaDB 定义）")
    if not any(k in res2.answer for k in ("本地", "嵌入式", "无需")):
        failures.append("Q2 回答未复述 PDF 中的关键结论（本地/嵌入式/无需额外部署）")

    print("\n== 4. 结论 ==")
    if failures:
        for f in failures:
            print("  FAIL:", f)
        print("PHASE1 E2E: FAIL")
        return 1
    print("PHASE1 E2E: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
