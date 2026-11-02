"""探针：文件夹树 + 分库入库 + 分库检索。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pka.agents import library  # noqa: E402
from pka.agents.ingestion import ingest_file  # noqa: E402
from pka.agents.qa_agent import QAAgent  # noqa: E402
from pka.config import Settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    s = Settings(model_provider="ollama", embedding_provider="hash", data_dir=tmp / "data", log_dir=tmp / "logs")
    s.ensure_dirs()
    vectorstore.reset_client()
    library.reset_library_store()
    lib = library.get_library_store(s)

    py = lib.create("Python", description="课程笔记", category="编程")
    dl = lib.create("深度学习")
    novel = lib.create("novel")
    qi = lib.create("七日系列", parent_id=novel.id)
    print("tree:", [(d, f.name) for d, f in lib.tree()])
    print("path(qi):", lib.path(qi.id))
    print("descendant(novel):", lib.descendant_ids(novel.id) == [novel.id, qi.id])
    print("dup guard:", end=" ")
    try:
        lib.create("python", parent_id=None)
        print("FAIL 未拦住重名")
    except ValueError as exc:
        print("OK ->", exc)

    md1 = tmp / "week01.md"; md1.write_text("# Python week01\n\n装饰器与生成器笔记。", encoding="utf-8")
    md2 = tmp / "day01.md"; md2.write_text("# 深度学习 day01\n\n反向传播与梯度下降。", encoding="utf-8")
    md3 = tmp / "设定.md"; md3.write_text("# 七日系列设定\n\n深渊的回响，主角是潜水员。", encoding="utf-8")
    ingest_file(s, md1, topic="Python基础", folder_id=py.id, folder_path=lib.path(py.id))
    ingest_file(s, md2, topic="深度学习", folder_id=dl.id, folder_path=lib.path(dl.id))
    ingest_file(s, md3, topic="小说设定", folder_id=qi.id, folder_path=lib.path(qi.id))
    print("total chunks:", vectorstore.count(s))
    print("count(py):", vectorstore.count(s, [py.id]))
    print("count(novel subtree):", vectorstore.count(s, lib.descendant_ids(novel.id)))
    print("counts_by_folder:", vectorstore.counts_by_folder(s))

    agent = QAAgent(s)
    r_py = agent.ask("装饰器怎么实现？", folder_ids=[py.id])
    r_novel = agent.ask("主角是谁？", folder_ids=lib.descendant_ids(novel.id))
    print("py hit:", [c.label() for c in r_py.citations][:3])
    print("novel hit:", [c.label() for c in r_novel.citations][:3])
    print("novel 是否混入 Python:", any("Python" in c.label() for c in r_novel.citations))
    print("sources(py):", [(x["source"], x["folder_path"]) for x in vectorstore.list_sources(s, [py.id])])

    removed = vectorstore.delete_folder(s, lib.descendant_ids(novel.id))
    print("delete_folder removed:", removed, "left:", vectorstore.count(s))
    lib.delete(qi.id); lib.delete(novel.id)
    print("tree after:", [(d, f.name) for d, f in lib.tree()])
    print("PROBE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
