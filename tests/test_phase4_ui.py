"""Phase 4 前端测试：知识库浏览 + 日志页（AppTest，离线）。"""

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
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PKA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")

    from pka.config import reset_settings
    from pka.core import vectorstore

    reset_settings()
    vectorstore.reset_client()
    yield tmp_path
    reset_settings()
    vectorstore.reset_client()


def _run():
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    assert not at.exception, list(at.exception)
    return at


def _goto(at, page: str):
    """点侧栏导航切页（改造后各页面按需渲染，不再用 st.tabs）。"""
    for b in at.sidebar.button:
        if (b.label or "").strip() == page:
            b.click()
            at.run()
            assert not at.exception, list(at.exception)
            return at
    raise AssertionError(f"侧栏找不到导航「{page}」")


def _html_blob(at) -> str:
    try:
        return " ".join(str(e.value) for e in at.get("html"))
    except Exception:
        return ""


def test_browse_tab_shows_ingested_doc(env):
    from pka.agents.ingestion import ingest_file
    from pka.config import get_settings

    s = get_settings()
    doc = env / "浏览测试.md"
    doc.write_text("# 浏览测试\n\n这是一篇用于验证知识库浏览页的文档。", encoding="utf-8")
    assert ingest_file(s, doc, topic="浏览验证").ok

    at = _goto(_run(), "知识库")
    tables = at.dataframe
    assert tables, "浏览页未渲染表格"
    blob = " ".join(str(c) for t in tables for c in t.value.get("文件名", []))
    assert "浏览测试.md" in blob, blob


def test_browse_tab_shows_update_records(env):
    from pka.agents.update_agent import _append_record
    from pka.config import get_settings

    s = get_settings()
    _append_record(s, {
        "timestamp": "2026-11-02 12:00:00",
        "topic": "Python异步",
        "old_version": "v1.0",
        "new_version": "v2.0",
        "decision": "REPLACE",
        "reason": "测试记录",
        "stability_score": 4,
        "performance_score": 5,
    })

    at = _goto(_run(), "知识库")
    blob = " ".join(str(t.value) for t in at.dataframe) + _html_blob(at)
    assert "测试记录" in blob or "REPLACE" in blob


def test_logs_tab_lists_log_files(env):
    logs = Path(os.environ["PKA_LOG_DIR"])
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "operation.log").write_text("[2026-11-02 12:00:00] [INFO] [ingestion] 测试行\n", encoding="utf-8")

    at = _goto(_run(), "日志")
    picks = [s for s in at.selectbox if "日志文件" == s.label]
    assert picks, [s.label for s in at.selectbox]
    assert "operation.log" in picks[0].options


def test_logs_tab_renders_content(env):
    logs = Path(os.environ["PKA_LOG_DIR"])
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "operation.log").write_text("[2026-11-02 12:00:00] [INFO] [ingestion] 测试行\n", encoding="utf-8")

    at = _goto(_run(), "日志")
    blob = _html_blob(at)
    assert "测试行" in blob, blob[:300]