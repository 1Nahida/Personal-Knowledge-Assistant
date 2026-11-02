"""对话历史持久化（PRD P1：对话历史）。

SQLite 存储，默认落在 Settings.history_db（data/history.db）。
会话（session）维度组织：一个会话包含多条消息，消息可携带引用来源 JSON。
仅使用标准库 sqlite3，避免引入额外依赖。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..config import Settings, get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    provider    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    citations   TEXT NOT NULL DEFAULT '[]',
    provider    TEXT NOT NULL DEFAULT '',
    elapsed_sec REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _now() -> str:
    # 精确到微秒：同一秒内创建/更新的多条记录也要能稳定排序
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


class HistoryStore:
    """对话历史读写。每次操作独立建连，避免 Streamlit 多线程复用同一连接。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db_path = Path(self.settings.history_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ---- sessions ----

    def create_session(self, title: str = "", provider: str = "") -> str:
        sid = uuid.uuid4().hex[:12]
        ts = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, provider, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (sid, title or f"会话 {ts}", provider, ts, ts),
            )
        return sid

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS msg_count
                FROM sessions s ORDER BY s.updated_at DESC, s.created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def purge_empty_sessions(self) -> int:
        """删除没有消息的空会话并返回删除数量。

        会话按需创建（首次提问时才落库），此方法用于清理历史遗留的空会话——
        早期版本每次页面加载都会新建一个空会话，刷新几次就会堆出十几条「新会话（0 条）」。
        """
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM messages)"
            )
            return int(cur.rowcount or 0)

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def rename_session(self, session_id: str, title: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now(), session_id),
            )

    # ---- messages ----

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: list[dict] | None = None,
        provider: str = "",
        elapsed_sec: float = 0.0,
    ) -> int:
        ts = _now()
        payload = json.dumps(citations or [], ensure_ascii=False)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, citations, provider, elapsed_sec, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, role, content, payload, provider, float(elapsed_sec), ts),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (ts, session_id))
            return int(cur.lastrowid or 0)

    def get_messages(self, session_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            item = dict(r)
            try:
                item["citations"] = json.loads(item.get("citations") or "[]")
            except (TypeError, ValueError):
                item["citations"] = []
            out.append(item)
        return out

    def add_turn(self, session_id: str, question: str, result, provider: str = "") -> None:
        """一次性写入一轮问答（用户问题 + 助手回答）。result 为 QAResult。"""
        self.add_message(session_id, "user", question)
        self.add_message(
            session_id,
            "assistant",
            getattr(result, "answer", ""),
            citations=[c.to_dict() for c in getattr(result, "citations", []) or []],
            provider=provider or getattr(result, "provider", ""),
            elapsed_sec=float(getattr(result, "elapsed_sec", 0.0)),
        )


_store_cache: dict[str, HistoryStore] = {}


def get_history_store(settings: Settings | None = None) -> HistoryStore:
    """按 db 路径缓存实例，避免每次调用重复建表。"""
    s = settings or get_settings()
    key = str(s.history_db)
    if key not in _store_cache:
        _store_cache[key] = HistoryStore(s)
    return _store_cache[key]
