"""Phase 2 单元测试：对话历史存储（不依赖 Ollama）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pka.agents.history import HistoryStore  # noqa: E402
from pka.config import Settings  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = Settings(
        model_provider="ollama",
        embedding_provider="hash",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    s.ensure_dirs()
    return HistoryStore(s)


def test_create_and_list_sessions(store):
    sid1 = store.create_session("关于装饰器")
    sid2 = store.create_session("关于异步")
    sessions = store.list_sessions()
    assert {s["id"] for s in sessions} >= {sid1, sid2}
    # 最新更新在前
    assert sessions[0]["id"] == sid2


def test_add_and_get_messages(store):
    sid = store.create_session()
    store.add_message(sid, "user", "装饰器怎么写？")
    store.add_message(sid, "assistant", "用 functools.wraps", citations=[{"index": 1, "source": "a.md"}])

    msgs = store.get_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["citations"][0]["source"] == "a.md"

    sessions = store.list_sessions()
    assert sessions[0]["msg_count"] == 2


def test_add_turn_persists_citations(store):
    class FakeCitation:
        def to_dict(self):
            return {"index": 1, "source": "notes.md", "page": 0, "version": "v1.0", "topic": "t", "score": 0.9}

    class FakeResult:
        answer = "答案"
        citations = [FakeCitation()]
        provider = "ollama"
        elapsed_sec = 1.5

    sid = store.create_session()
    store.add_turn(sid, "问题?", FakeResult())
    msgs = store.get_messages(sid)
    assert len(msgs) == 2
    assert msgs[0]["content"] == "问题?"
    assert msgs[1]["citations"][0]["source"] == "notes.md"
    assert msgs[1]["elapsed_sec"] == 1.5


def test_rename_and_delete_session(store):
    sid = store.create_session("旧标题")
    store.rename_session(sid, "新标题")
    assert store.list_sessions()[0]["title"] == "新标题"
    store.add_message(sid, "user", "hi")
    store.delete_session(sid)
    assert sid not in {s["id"] for s in store.list_sessions()}
    assert store.get_messages(sid) == []


def test_persist_across_instances(tmp_path):
    s = Settings(embedding_provider="hash", data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    s.ensure_dirs()
    a = HistoryStore(s)
    sid = a.create_session("持久化")
    a.add_message(sid, "user", "重启后还在吗")
    b = HistoryStore(s)
    assert b.get_messages(sid)[0]["content"] == "重启后还在吗"


def test_purge_empty_sessions(store):
    """空会话（未提问就落库）应被清理，有消息的会话必须保留。"""
    kept = store.create_session("有内容")
    store.add_message(kept, "user", "你好")
    store.create_session("空会话1")
    store.create_session("空会话2")

    assert store.purge_empty_sessions() == 2
    sessions = store.list_sessions()
    assert [s["id"] for s in sessions] == [kept]
    assert sessions[0]["msg_count"] == 1
