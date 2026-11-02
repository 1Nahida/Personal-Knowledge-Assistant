r"""清空 PKA 的测试数据与日志，回到干净可用状态（正式启用前执行一次）。

清空范围：
  data/chroma/*            向量集合（全部）
  data/uploads/*           上传原件
  data/history.db          对话历史（SQLite）
  data/update_history.jsonl 技术更迭记录（含 .bak）
  logs/*                   全部日志、截图目录与一次性的探针输出

保留：docs/（开发日志与 PRD 摘要）、examples/（仓库自带示例）、.env、源码。

用法：先停掉 Streamlit，再执行
  & ".\.venv\Scripts\python.exe" scripts\reset_data.py --yes
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pka.config import get_settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402


def _count_rows(db: Path, table: str) -> int:
    if not db.exists():
        return 0
    con = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return -1
    finally:
        # sqlite3 的 with 块只提交事务、不关连接；不 close 会一直占着文件导致后面删不掉
        if con is not None:
            con.close()


def summary(s) -> dict[str, object]:
    client = vectorstore.get_client(s)
    # chromadb 0.6.x 的 list_collections() 直接返回集合名
    collections = list(client.list_collections())
    chunks = 0
    for name in collections:
        chunks += client.get_collection(name).count()
    db = Path(s.history_db)
    logs = [p for p in Path(s.log_dir).iterdir()]
    return {
        "collections": collections,
        "chunks": chunks,
        "sessions": _count_rows(db, "sessions"),
        "messages": _count_rows(db, "messages"),
        "uploads": [p.name for p in Path(s.upload_dir).glob("*") if p.is_file()],
        "update_records": sum(
            1 for p in Path(s.data_dir).glob("update_history.jsonl*") if p.exists() for _ in p.open("r", encoding="utf-8")
        ),
        "log_entries": [p.name for p in logs],
    }


def wipe(s) -> None:
    client = vectorstore.get_client(s)
    for name in client.list_collections():
        client.delete_collection(name)
    vectorstore.reset_client()
    # delete_collection 只删元数据，HNSW 段文件仍留在磁盘上（几 MB 的孤儿文件）→ 整目录重建
    shutil.rmtree(s.chroma_dir, ignore_errors=True)

    for p in Path(s.data_dir).glob("update_history.jsonl*"):
        p.unlink(missing_ok=True)

    db = Path(s.history_db)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)

    for p in Path(s.upload_dir).glob("*"):
        p.unlink() if p.is_file() else shutil.rmtree(p, ignore_errors=True)

    log_dir = Path(s.log_dir)
    for p in log_dir.iterdir():
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

    Path(s.chroma_dir).mkdir(parents=True, exist_ok=True)
    s.ensure_dirs()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="确认真删（不加则只打印将清空的内容）")
    args = ap.parse_args()
    s = get_settings()

    before = summary(s)
    print("== 清空前 ==")
    for k, v in before.items():
        print(f"  {k}: {v}")
    if not args.yes:
        print("\n未加 --yes，仅预览，未删除任何文件。")
        return 0

    wipe(s)

    after = summary(s)
    print("\n== 清空后 ==")
    for k, v in after.items():
        print(f"  {k}: {v}")
    clean = not after["collections"] and not after["chunks"] and not after["uploads"] and not after["log_entries"]
    print("\nRESET_OK" if clean else "\nRESET_INCOMPLETE")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
