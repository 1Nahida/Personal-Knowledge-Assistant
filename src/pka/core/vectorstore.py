"""ChromaDB 向量库封装（PRD 5.1 元数据结构）。

- 持久化存储于 ``data/chroma/``，纯本地，无需额外部署；
- 余弦距离（hnsw:space=cosine），检索分数 = 1 - distance，范围 [-1, 1]，越大越相关；
- 集合名 ``pka_<embedding_model>``：更换嵌入模型即使用新集合，避免向量空间不一致。

元数据字段（PRD 5.1）：
    source / version / topic / created_at / updated_at / status / page
    folder_id / folder_path —— 用户补充需求：知识库文件夹树（见 agents/library.py）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from ..config import Settings, get_settings

_client_cache: dict[str, object] = {}


def get_client(settings: Settings | None = None):
    """获取（并缓存）指向指定数据目录的 Chroma 持久化客户端。"""
    s = settings or get_settings()
    s.ensure_dirs()
    import chromadb

    key = str(s.chroma_dir)
    if key not in _client_cache:
        # 显式关掉遥测：chromadb 0.6.3 与新 posthog 不兼容，会往 stderr 刷
        # "Failed to send telemetry event ... capture() takes 1 positional argument"
        _client_cache[key] = chromadb.PersistentClient(
            path=str(s.chroma_dir), settings=chromadb.Settings(anonymized_telemetry=False)
        )
    return _client_cache[key]


def reset_client() -> None:
    """清空客户端缓存（测试用：换临时目录前必须调用）。"""
    _client_cache.clear()


def collection_name(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return f"pka_{s.embedding_model.replace(' ', '_')}"


def get_collection(settings: Settings | None = None):
    s = settings or get_settings()
    return get_client(s).get_or_create_collection(
        name=collection_name(s), metadata={"hnsw:space": "cosine"}
    )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _coerce(value):
    """Chroma 元数据只接受 str/int/float/bool，None 一律转空串。"""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass
class SearchHit:
    content: str
    metadata: dict
    score: float  # 1 - cosine_distance


def add_chunks(settings: Settings | None, chunks: list[dict]) -> list[str]:
    """批量写入块。

    每个 chunk: ``{"content": str, "source": str, "version": str, "topic": str,
    "page": int | None, "folder_id": str, "folder_path": str}``，返回写入的 id 列表。
    created_at/updated_at/status 自动补齐。
    """
    s = settings or get_settings()
    if not chunks:
        return []
    from .embeddings import get_embeddings

    col = get_collection(s)
    ts = _now()
    ids, documents, metadatas = [], [], []
    for c in chunks:
        cid = str(uuid.uuid4())
        ids.append(cid)
        documents.append(c["content"])
        metadatas.append(
            {
                "source": _coerce(c.get("source")),
                "version": _coerce(c.get("version", "v1.0")),
                "topic": _coerce(c.get("topic")),
                "created_at": ts,
                "updated_at": ts,
                "status": "active",
                "page": int(c.get("page") or 0),
                # 块在文档中的顺序，供「文件详情」按原顺序拼接预览；
                # 该字段之前入库的旧数据为 0，预览时退化为按页码排序
                "chunk_index": int(c.get("idx") or 0),
                # 空串代表「未分类」（根目录），便于用 $in 统一过滤
                "folder_id": _coerce(c.get("folder_id")),
                "folder_path": _coerce(c.get("folder_path")),
            }
        )
    # 显式计算向量再写入：绝不依赖 Chroma 默认 ONNX 嵌入
    # （默认函数首次使用需联网下载模型，离线/被墙时会永久阻塞）。
    embeddings = get_embeddings(s).embed_documents(documents)
    # Chroma 单次写入上限较保守，分批
    for i in range(0, len(ids), 500):
        col.add(
            ids=ids[i : i + 500],
            documents=documents[i : i + 500],
            metadatas=metadatas[i : i + 500],
            embeddings=embeddings[i : i + 500],
        )
    return ids


def search(
    settings: Settings | None,
    query: str,
    k: int | None = None,
    where: dict | None = None,
) -> list[SearchHit]:
    """向量检索 Top-K，按相关度降序返回。低于 SCORE_THRESHOLD 的结果被过滤。"""
    s = settings or get_settings()
    from .embeddings import get_embeddings

    k = k or s.top_k
    col = get_collection(s)
    if col.count() == 0:
        return []
    qv = get_embeddings(s).embed_query(query)
    res = col.query(
        query_embeddings=[qv],
        n_results=min(k, col.count()),
        include=["documents", "metadatas", "distances"],
        where=where or None,
    )
    hits: list[SearchHit] = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        score = 1.0 - float(dist)
        if score < s.score_threshold:
            continue
        hits.append(SearchHit(content=doc or "", metadata=meta or {}, score=score))
    return hits



def folder_where(folder_ids: list[str] | None) -> dict | None:
    """把文件夹 id 列表转成 Chroma where 条件；None/空表示不限（全库）。"""
    if not folder_ids:
        return None
    if len(folder_ids) == 1:
        return {"folder_id": folder_ids[0]}
    return {"folder_id": {"$in": list(folder_ids)}}


def _merge_where(*conds: dict | None) -> dict | None:
    """合并多个 where：单条直接用，多条走 $and（Chroma 顶层只认 $and/$or）。"""
    parts = [c for c in conds if c]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def delete_by_source(
    settings: Settings | None,
    source: str,
    version: str | None = None,
    folder_id: str | None = None,
) -> int:
    """按来源文件删除全部块；version / folder_id 给了就再限定。返回删除数量。

    folder_id 必须传：同一份笔记可能同时存在于 Python 与深度学习两个文件夹，
    只按文件名删会把另一个文件夹里的同名文件一起删掉。
    """
    s = settings or get_settings()
    col = get_collection(s)
    where = _merge_where(
        {"source": source},
        {"version": version} if version else None,
        {"folder_id": folder_id or ""} if folder_id is not None else None,
    )
    existing = col.get(where=where, include=[])
    ids = existing.get("ids") or []
    if not ids:
        return 0
    for i in range(0, len(ids), 500):
        col.delete(ids=ids[i : i + 500])
    return len(ids)


def delete_folder(settings: Settings | None, folder_ids: list[str]) -> int:
    """删除一组文件夹（含子孙）下的全部块，返回删除数量。"""
    s = settings or get_settings()
    col = get_collection(s)
    where = folder_where(folder_ids)
    if not where:
        return 0
    existing = col.get(where=where, include=[])
    ids = existing.get("ids") or []
    if not ids:
        return 0
    for i in range(0, len(ids), 500):
        col.delete(ids=ids[i : i + 500])
    return len(ids)


def delete_all(settings: Settings | None) -> int:
    s = settings or get_settings()
    col = get_collection(s)
    n = col.count()
    if n:
        existing = col.get(include=[])
        ids = existing.get("ids") or []
        if ids:
            for i in range(0, len(ids), 500):
                col.delete(ids=ids[i : i + 500])
    return n



def get_document_text(
    settings: Settings | None,
    source: str,
    version: str,
    folder_id: str = "",
    limit: int = 1600,
) -> tuple[str, int]:
    """取一份文档的块并按页码/块序拼起来，用于「文件详情」预览。

    返回 ``(预览文本, 全文长度)``。预览文本被截断到 ``limit`` 字符，
    只用于展示——检索与问答仍然用原始块。
    """
    s = settings or get_settings()
    col = get_collection(s)
    where = _merge_where({
        "$and": [
            {"source": source},
            {"version": version},
            {"folder_id": folder_id or ""},
        ]
    })
    res = col.get(where=where, include=["documents", "metadatas"])
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    if not docs:
        return "", 0
    pairs = list(zip(docs, metas))
    pairs.sort(key=lambda p: (int(p[1].get("page") or 0), int(p[1].get("chunk_index") or 0)))
    full = "\n\n".join(d or "" for d, _m in pairs)
    return full[:limit], len(full)

def count(settings: Settings | None, folder_ids: list[str] | None = None) -> int:
    """块数；给了 folder_ids 就只数这些文件夹（含子孙）。"""
    col = get_collection(settings)
    where = folder_where(folder_ids)
    if not where:
        return col.count()
    return len(col.get(where=where, include=[]).get("ids") or [])


def counts_by_folder(settings: Settings | None) -> dict[str, int]:
    """每个文件夹（folder_id，空串=未分类）的块数，一次读全部元数据算出来。"""
    col = get_collection(settings)
    out: dict[str, int] = {}
    for meta in col.get(include=["metadatas"]).get("metadatas") or []:
        if not meta:
            continue
        out[meta.get("folder_id", "")] = out.get(meta.get("folder_id", ""), 0) + 1
    return out


def list_sources(
    settings: Settings | None, folder_ids: list[str] | None = None
) -> list[dict]:
    """按 (source, version, folder) 聚合的已入库文档列表（知识库浏览用，PRD P1）。"""
    s = settings or get_settings()
    col = get_collection(s)
    where = folder_where(folder_ids)
    res = col.get(where=where, include=["metadatas"]) if where else col.get(include=["metadatas"])
    agg: dict[tuple[str, str, str], dict] = {}
    for meta in res.get("metadatas") or []:
        if not meta:
            continue
        key = (meta.get("source", ""), meta.get("version", ""), meta.get("folder_id", ""))
        item = agg.setdefault(
            key,
            {
                "source": meta.get("source", ""),
                "version": meta.get("version", ""),
                "topic": meta.get("topic", ""),
                "folder_id": meta.get("folder_id", ""),
                "folder_path": meta.get("folder_path", ""),
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
                "status": meta.get("status", ""),
                "chunk_count": 0,
            },
        )
        item["chunk_count"] += 1
        # updated_at 取最大值（同批次写入时间相同，覆盖无妨）
        if meta.get("updated_at", "") > item["updated_at"]:
            item["updated_at"] = meta.get("updated_at", "")
    return sorted(agg.values(), key=lambda x: x["created_at"], reverse=True)