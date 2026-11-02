"""Phase 5（用户补充需求）：多知识库文件夹 —— 建库、分库入库、按库检索、更迭不跨库。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(ROOT / "app.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PKA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")

    from pka.agents import library
    from pka.config import reset_settings
    from pka.core import vectorstore

    reset_settings()
    vectorstore.reset_client()
    library.reset_library_store()
    yield tmp_path
    reset_settings()
    vectorstore.reset_client()
    library.reset_library_store()


def _store(env):
    from pka.agents.library import get_library_store
    from pka.config import get_settings

    return get_library_store(get_settings())


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_folder_tree_path_and_descendants(env):
    lib = _store(env)
    py = lib.create("Python", category="课程笔记", description="语言基础")
    novel = lib.create("novel")
    qi = lib.create("七日系列", parent_id=novel.id)
    df = lib.create("深度学习")

    assert lib.path(qi.id) == "novel/七日系列"
    assert lib.path(py.id) == "Python"
    assert lib.descendant_ids(novel.id) == [novel.id, qi.id]
    assert lib.descendant_ids(df.id) == [df.id]
    assert [f.name for _d, f in lib.tree()] == ["Python", "novel", "七日系列", "深度学习"]
    # 编辑简介与分类
    lib.update(py.id, description="装饰器/生成器", category="编程")
    again = lib.get(py.id)
    assert again.description == "装饰器/生成器" and again.category == "编程"


def test_duplicate_sibling_rejected(env):
    lib = _store(env)
    lib.create("Python")
    with pytest.raises(ValueError):
        lib.create("python")
    with pytest.raises(ValueError):
        lib.create("  ")
    # 跨级可以重名
    sub = lib.create("笔记", parent_id=None)
    assert lib.create("笔记", parent_id=sub.id).name == "笔记"


def test_ingest_and_scoped_search(env):
    from pka.agents.ingestion import ingest_file
    from pka.agents.qa_agent import QAAgent
    from pka.config import get_settings
    from pka.core import vectorstore

    s = get_settings()
    lib = _store(env)
    py = lib.create("Python")
    novel = lib.create("novel")
    qi = lib.create("七日系列", parent_id=novel.id)

    a = _write(env, "week01.md", "# Python week01\n\n装饰器本质是函数作为参数返回函数。")
    b = _write(env, "设定.md", "# 七日系列设定\n\n主角是潜水员，故事发生在深渊。")
    assert ingest_file(s, a, topic="Python基础", folder_id=py.id, folder_path=lib.path(py.id)).ok
    assert ingest_file(s, b, topic="小说设定", folder_id=qi.id, folder_path=lib.path(qi.id)).ok

    assert vectorstore.count(s) == 2
    assert vectorstore.count(s, [py.id]) == 1
    assert vectorstore.count(s, lib.descendant_ids(novel.id)) == 1

    agent = QAAgent(s)
    hits = agent.ask("装饰器是什么？", folder_ids=[py.id]).citations
    assert hits and hits[0].folder == "Python"
    # 在 novel 子树里问 Python 问题，不应命中 Python 文件夹的块
    assert not agent.ask("装饰器是什么？", folder_ids=lib.descendant_ids(novel.id)).citations


def test_same_name_two_folders_isolated(env):
    from pka.agents.ingestion import ingest_file
    from pka.config import get_settings
    from pka.core import vectorstore

    s = get_settings()
    lib = _store(env)
    f1 = lib.create("A")
    f2 = lib.create("B")
    doc = _write(env, "notes.md", "# 共同笔记\n\n同名文件在两个知识库里各存一份。")
    ingest_file(s, doc, topic="笔记", folder_id=f1.id, folder_path=lib.path(f1.id))
    ingest_file(s, doc, topic="笔记", folder_id=f2.id, folder_path=lib.path(f2.id))

    assert vectorstore.count(s) == 2
    removed = vectorstore.delete_by_source(s, "notes.md", "v1.0", folder_id=f1.id)
    assert removed == 1
    left = vectorstore.list_sources(s)
    assert len(left) == 1 and left[0]["folder_id"] == f2.id


def test_update_agent_does_not_cross_folders(env):
    """A 库里的旧文档不应被 B 库里同主题的新文档替换掉（跨库更迭边界）。"""
    from pka.agents import update_agent as ua
    from pka.agents.ingestion import ingest_file
    from pka.config import get_settings
    from pka.core import vectorstore

    s = get_settings()
    lib = _store(env)
    fa = lib.create("A")
    fb = lib.create("B")

    old = _write(env, "old.md", "# 异步旧方案\n\n回调与线程池的实现细节。")
    assert ingest_file(s, old, version="v1.0", topic="Python异步",
                       folder_id=fa.id, folder_path=lib.path(fa.id)).ok

    new = _write(env, "new.md", "# 异步新语法\n\nasync/await 更加简洁稳定。")
    r = ua.evaluate_file(s, new, topic="Python异步", folder_id=fb.id, folder_path=lib.path(fb.id))

    assert r.decision == ua.DECISION_INGEST, r.reason
    versions = {(x["source"], x["version"], x["folder_id"]) for x in vectorstore.list_sources(s)}
    assert ("old.md", "v1.0", fa.id) in versions
    assert ("new.md", "v1.0", fb.id) in versions


# ---- 前端 ----
def _run():
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    assert not at.exception, list(at.exception)
    return at


def _goto(at, page: str):
    for b in at.sidebar.button:
        if (b.label or "").strip() == page:
            b.click()
            at.run()
            assert not at.exception, list(at.exception)
            return at
    raise AssertionError(f"侧栏找不到导航「{page}」")


def _norm(label: str) -> str:
    """去掉缩进与展开箭头，只留名字（便于断言）。"""
    return (label or "").replace("\u3000", "").replace("▸ ", "").replace("▾ ", "").strip()


def _html_blob(at) -> str:
    try:
        return " ".join(str(e.value) for e in at.get("html"))
    except Exception:
        return ""


def _labels(at) -> list[str]:
    return [_norm(b.label) for b in list(at.button) + list(at.sidebar.button)]


def _click(at, text: str):
    for b in list(at.button) + list(at.sidebar.button):
        if text in (b.label or ""):
            b.click()
            at.run()
            assert not at.exception, list(at.exception)
            return at
    raise AssertionError(f"点不到「{text}」：{_labels(at)}")


def test_library_page_renders_folder_tree(env):
    lib = _store(env)
    lib.create("Python")
    novel = lib.create("novel")
    lib.create("七日系列", parent_id=novel.id)

    at = _goto(_run(), "知识库")
    labels = _labels(at)
    assert any("Python" in x for x in labels), labels
    assert any("全部文件" in x for x in labels), labels
    # 子文件夹默认收起（IDE 风格），展开父节点后才出现
    assert not any("七日系列" in x for x in labels), labels
    _click(at, "novel")
    assert any("七日系列" in x for x in _labels(at)), _labels(at)


def test_file_click_shows_content_preview(env):
    """点文件节点 → 右侧切到文件详情，只预览开头部分内容。"""
    from pka.agents.ingestion import ingest_file
    from pka.config import get_settings

    s = get_settings()
    lib = _store(env)
    py = lib.create("Python")
    long_body = "装饰器本质是把函数作为参数传入并返回新函数。" * 200  # 约 4800 字，远超预览上限
    doc = _write(env, "week01.md", f"# week01\n\n{long_body}")
    ingest_file(s, doc, topic="Python基础", folder_id=py.id, folder_path=lib.path(py.id))

    at = _goto(_run(), "知识库")
    _click(at, "Python")          # 展开文件夹，露出文件节点
    assert any("week01.md" in x for x in _labels(at)), _labels(at)
    _click(at, "week01.md")       # 点文件 → 详情

    blob = _html_blob(at)
    assert "pka-doc" in blob, blob[:300]
    assert "装饰器本质" in blob
    caps = " ".join(c.value for c in at.caption)
    assert "仅预览前 1600 字" in caps, caps
    # 预览被截断：正文重复片段的出现次数应远小于全文份数（200）
    assert blob.count("装饰器本质") < 100, blob.count("装饰器本质")


def test_library_page_shows_scoped_docs(env):
    from pka.agents.ingestion import ingest_file
    from pka.config import get_settings

    s = get_settings()
    lib = _store(env)
    py = lib.create("Python")
    doc = _write(env, "week01.md", "# week01\n\n装饰器笔记。")
    ingest_file(s, doc, topic="Python基础", folder_id=py.id, folder_path=lib.path(py.id))

    at = _goto(_run(), "知识库")
    blob = " ".join(str(t.value) for t in at.dataframe)
    assert "week01.md" in blob, blob
    # 全部文件视图也能看到它，并标注位置
    assert "Python" in blob


def test_scope_pills_switch(env):
    at = _run()
    pills = [p for p in at.sidebar.get("pills")]
    assert pills, "侧栏缺少检索范围 pills"
    at.session_state["scope_all"] = True
    at.run()
    caps = " ".join(c.value for c in at.sidebar.caption)
    assert "全库" in caps, caps
