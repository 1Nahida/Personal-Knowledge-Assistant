"""知识库文件夹（多知识库）注册表。

用户补充需求：把知识库组织成文件夹树，可新建/重命名/写简介与分类：
    Python/            深度学习/          novel/
      week01.md          day01.md            七日系列/
                                                   设定.md

设计要点
- 任意层级：folders.parent_id 指向上级，根文件夹为 NULL；
- 文件夹本身**不进向量库**，只存在 SQLite（data/library.db），纯本地无服务；
- 文件归属靠向量块元数据 folder_id / folder_path；删除文件夹前先查块数，
  避免「删了文件夹但向量还在库里」的孤儿数据；
- 同级不允许同名（忽略大小写），跨级可以重名。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import Settings, get_settings

ROOT_LABEL = "全部文件"


def _now() -> str:
    # 带微秒，保证同一秒内连续新建的文件夹排序稳定
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


@dataclass
class Folder:
    id: str
    parent_id: str | None = None
    name: str = ""
    description: str = ""
    category: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


class LibraryStore:
    """文件夹注册表的读写（每次操作独立建连接，Streamlit 多线程下安全）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db_path = Path(self.settings.library_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def _init_schema(self) -> None:
        with self._conn() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS folders (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id)")

    # ---- 查询 ----
    def get(self, folder_id: str | None) -> Folder | None:
        if not folder_id:
            return None
        with self._conn() as con:
            row = con.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        return Folder(**dict(row)) if row else None

    def all(self) -> list[Folder]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM folders ORDER BY created_at").fetchall()
        return [Folder(**dict(r)) for r in rows]

    def children(self, parent_id: str | None) -> list[Folder]:
        with self._conn() as con:
            if parent_id:
                rows = con.execute(
                    "SELECT * FROM folders WHERE parent_id = ? ORDER BY name", (parent_id,)
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM folders WHERE parent_id IS NULL ORDER BY name"
                ).fetchall()
        return [Folder(**dict(r)) for r in rows]

    def tree(self) -> list[tuple[int, Folder]]:
        """深度优先展开成 (层级, 文件夹) 列表，供页面画缩进树。"""
        by_parent: dict[str | None, list[Folder]] = {}
        for f in self.all():
            by_parent.setdefault(f.parent_id, []).append(f)
        for group in by_parent.values():
            group.sort(key=lambda x: x.name)

        out: list[tuple[int, Folder]] = []

        def walk(pid: str | None, depth: int) -> None:
            for f in by_parent.get(pid, []):
                out.append((depth, f))
                walk(f.id, depth + 1)

        walk(None, 0)
        return out

    def path(self, folder_id: str | None) -> str:
        """人类可读路径，如 Python/基础语法；根返回「全部文件」。"""
        if not folder_id:
            return ROOT_LABEL
        parts: list[str] = []
        cur = self.get(folder_id)
        guard = 0
        while cur and guard < 64:
            parts.append(cur.name)
            cur = self.get(cur.parent_id)
            guard += 1
        return "/".join(reversed(parts)) or ROOT_LABEL

    def descendant_ids(self, folder_id: str | None) -> list[str]:
        """自身 + 全部子孙（递归 CTE）；folder_id 为空返回全部文件夹 id。"""
        if not folder_id:
            return [f.id for f in self.all()]
        with self._conn() as con:
            rows = con.execute(
                """
                WITH RECURSIVE sub(id) AS (
                    SELECT id FROM folders WHERE id = ?
                    UNION ALL
                    SELECT f.id FROM folders f JOIN sub ON f.parent_id = sub.id
                )
                SELECT id FROM sub
                """,
                (folder_id,),
            ).fetchall()
        return [r["id"] for r in rows]

    def depth(self, folder_id: str | None) -> int:
        return self.path(folder_id).count("/") if folder_id else 0

    # ---- 写入 ----
    def create(
        self,
        name: str,
        parent_id: str | None = None,
        description: str = "",
        category: str = "",
    ) -> Folder:
        name = (name or "").strip()
        if not name:
            raise ValueError("文件夹名称不能为空")
        if "/" in name or "\\" in name:
            raise ValueError("文件夹名称不能包含斜杠")
        if self._sibling_exists(name, parent_id):
            raise ValueError(f"同级下已有同名文件夹「{name}」")
        folder = Folder(
            id=uuid.uuid4().hex[:12],
            parent_id=parent_id or None,
            name=name,
            description=(description or "").strip(),
            category=(category or "").strip(),
        )
        with self._conn() as con:
            con.execute(
                "INSERT INTO folders (id, parent_id, name, description, category, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    folder.id,
                    folder.parent_id,
                    folder.name,
                    folder.description,
                    folder.category,
                    folder.created_at,
                    folder.updated_at,
                ),
            )
        return folder

    def update(
        self,
        folder_id: str,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
    ) -> Folder:
        folder = self.get(folder_id)
        if not folder:
            raise ValueError("文件夹不存在")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("文件夹名称不能为空")
            if name != folder.name and self._sibling_exists(name, folder.parent_id):
                raise ValueError(f"同级下已有同名文件夹「{name}」")
            folder.name = name
        if description is not None:
            folder.description = description.strip()
        if category is not None:
            folder.category = category.strip()
        folder.updated_at = _now()
        with self._conn() as con:
            con.execute(
                "UPDATE folders SET name = ?, description = ?, category = ?, updated_at = ? WHERE id = ?",
                (folder.name, folder.description, folder.category, folder.updated_at, folder.id),
            )
        return folder

    def delete(self, folder_id: str) -> None:
        """只删注册表记录；调用方须先确认文件夹内没有子文件夹与文件。"""
        with self._conn() as con:
            con.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

    def has_children(self, folder_id: str) -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM folders WHERE parent_id = ? LIMIT 1", (folder_id,)
            ).fetchone()
        return row is not None

    def _sibling_exists(self, name: str, parent_id: str | None) -> bool:
        with self._conn() as con:
            if parent_id:
                row = con.execute(
                    "SELECT 1 FROM folders WHERE parent_id = ? AND lower(name) = lower(?) LIMIT 1",
                    (parent_id, name),
                ).fetchone()
            else:
                row = con.execute(
                    "SELECT 1 FROM folders WHERE parent_id IS NULL AND lower(name) = lower(?) LIMIT 1",
                    (name,),
                ).fetchone()
        return row is not None


_store_cache: dict[str, LibraryStore] = {}


def get_library_store(settings: Settings | None = None) -> LibraryStore:
    s = settings or get_settings()
    key = str(s.library_db)
    if key not in _store_cache:
        _store_cache[key] = LibraryStore(s)
    return _store_cache[key]


def reset_library_store() -> None:
    """换数据库路径（测试）时清缓存。"""
    _store_cache.clear()
