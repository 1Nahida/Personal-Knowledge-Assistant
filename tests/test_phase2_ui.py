"""Phase 2 无头 UI 测试：用 Streamlit AppTest 跑真实前端脚本（不启动浏览器）。

覆盖：页面能渲染、侧栏模型源切换、知识库空态、日志页。
不覆盖真实问答（需 Ollama，由 scripts/e2e_phase2.py 负责）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(ROOT / "app.py")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把数据与日志目录指向临时目录，避免污染真实知识库。"""
    monkeypatch.setenv("PKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PKA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    # 配置单例与 Chroma 客户端都是进程级缓存，必须逐用例重置，否则会沿用上一个临时目录
    from pka.config import reset_settings
    from pka.core import vectorstore

    reset_settings()
    vectorstore.reset_client()
    yield tmp_path
    reset_settings()
    vectorstore.reset_client()


def _run(sandbox):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def _goto(at, page: str):
    """点侧栏导航切页（改造后各页面按需渲染，不再用 st.tabs）。"""
    for b in at.sidebar.button:
        if (b.label or "").strip() == page:
            b.click()
            at.run()
            assert not at.exception, list(at.exception)
            return at
    labels = [(b.label or "") for b in at.sidebar.button]
    raise AssertionError(f"侧栏找不到导航「{page}」：{labels}")


def _html_blob(at) -> str:
    try:
        return " ".join(str(e.value) for e in at.get("html"))
    except Exception:
        return ""


def test_app_renders_without_exception(sandbox):
    at = _run(sandbox)
    assert not at.exception, at.exception
    labels = [(b.label or "").strip() for b in at.sidebar.button]
    for page in ("智能问答", "知识库", "日志"):
        assert page in labels, labels


def test_sidebar_provider_options(sandbox):
    at = _run(sandbox)
    assert not at.exception
    radios = at.sidebar.radio
    assert len(radios) >= 1
    # Streamlit 暴露的是 format_func 渲染后的标签
    assert len(radios[0].options) == 3
    blob = " ".join(radios[0].options)
    assert "Ollama" in blob and "DashScope" in blob and "DeepSeek" in blob


def test_empty_knowledge_base_shows_hint(sandbox):
    at = _goto(_run(sandbox), "知识库")
    text_blob = " ".join(m.value for m in at.caption) + _html_blob(at)
    assert "还没有文档" in text_blob


def test_session_pills_switch_session(sandbox):
    """侧栏历史会话改为 pills 列表后，选中即切换会话并载入历史消息。"""
    from pka.agents.history import get_history_store
    from pka.config import get_settings

    at = _run(sandbox)
    store = get_history_store(get_settings())
    sid = store.create_session("旧会话", "ollama")
    store.add_message(sid, "user", "装饰器是什么")
    store.add_message(sid, "assistant", "一种高阶函数")

    at.run()
    at.session_state["sess_pills"] = sid
    at.run()
    assert not at.exception, list(at.exception)
    assert at.session_state["session_id"] == sid
    assert len(at.session_state["messages"]) == 2


def test_history_sqlite_created(sandbox):
    _run(sandbox)
    db = Path(os.environ["PKA_DATA_DIR"]) / "history.db"
    assert db.exists(), f"未生成 {db}"


def _by_label(elements, label_part):
    for e in elements:
        if label_part in (e.label or ""):
            return e
    raise AssertionError(f"未找到标签含「{label_part}」的元素")


def _session_rows(sandbox):
    import sqlite3

    db = Path(os.environ["PKA_DATA_DIR"]) / "history.db"
    with sqlite3.connect(str(db)) as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def test_reload_does_not_create_empty_sessions(sandbox):
    """回归：早期版本每次页面加载都建一个空会话，刷新几次就堆出十几条「新会话（0 条）」。"""
    at = _run(sandbox)
    at.run()
    at.run()
    assert not at.exception, at.exception
    assert _session_rows(sandbox) == 0


def test_submit_question_creates_session_and_messages(sandbox):
    """表单提交路径可用（原 st.chat_input 在 tabs 内不触发提交）。空库时走 no-hit 分支，无需 Ollama。"""
    at = _run(sandbox)
    _by_label(at.text_input, "提问").set_value("装饰器是什么")
    _by_label(at.button, "发送").click()
    at.run()
    assert not at.exception, at.exception

    import sqlite3

    db = Path(os.environ["PKA_DATA_DIR"]) / "history.db"
    with sqlite3.connect(str(db)) as conn:
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert sessions == 1, "提问后应创建 1 个会话"
    assert messages == 2, "一轮问答应落 2 条消息（user + assistant）"
