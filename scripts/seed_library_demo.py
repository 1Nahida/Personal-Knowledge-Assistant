"""预置「多知识库文件夹」演示数据（幂等：重复执行会重建同名文件夹并覆盖同名文档）。

用法：
    python scripts/seed_library_demo.py                 # 写入真实 data/ 目录
    $env:PKA_DATA_DIR="logs/_preview_data"; python scripts/seed_library_demo.py   # 预览目录
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from pka.agents.ingestion import ingest_file  # noqa: E402
from pka.agents.library import get_library_store  # noqa: E402
from pka.config import get_settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402


def _ensure(lib, name: str, parent_id=None, description="", category=""):
    """同名同级则复用，否则新建。"""
    for f in lib.children(parent_id):
        if f.name.lower() == name.lower():
            return f
    return lib.create(name, parent_id=parent_id, description=description, category=category)


def main() -> int:
    s = get_settings()
    s.ensure_dirs()
    lib = get_library_store(s)
    ex = ROOT / "examples"

    py = _ensure(lib, "Python", description="语言基础与常用写法", category="课程笔记")
    dl = _ensure(lib, "深度学习", description="模型、训练与 NLP 笔记", category="课程笔记")
    novel = _ensure(lib, "novel", description="自己写的小说设定", category="创作")
    qi = _ensure(lib, "七日系列", parent_id=novel.id, description="七日系列的世界观与角色", category="小说设定")

    jobs = [
        (ex / "python_装饰器与生成器笔记.md", py, "Python装饰器与生成器"),
        (ex / "python_异步新语法.md", py, "Python异步"),
        (ex / "python_异步旧方案_回调与线程池.md", dl, "异步演进"),
    ]
    for path, folder, topic in jobs:
        r = ingest_file(
            s, path, version="v1.0", topic=topic,
            folder_id=folder.id, folder_path=lib.path(folder.id),
        )
        print(f"入库 {lib.path(folder.id)}/{r.source}: ok={r.ok} 块数={r.chunks}")

    print(f"\n文件夹树: {[(d, f.name) for d, f in lib.tree()]}")
    for x in vectorstore.list_sources(s):
        print(f"  {x['folder_path'] or '未分类'} / {x['source']} · {x['version']} · {x['chunk_count']} 块")
    print(f"总块数: {vectorstore.count(s)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
