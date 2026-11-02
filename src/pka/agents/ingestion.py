"""知识库入库流水线（PRD 3.2.1）。

流程：上传文件 -> 解析文本 -> 清洗 -> 语义分块（~700 字符/块，120 重叠）
     -> 向量化 -> Chroma 写入（附带 PRD 5.1 元数据）。

支持格式：.pdf / .md(.markdown) / .txt / .docx。
PDF 按页解析，块携带 page 元数据，问答引用可定位到页码。
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import Settings, get_settings
from ..core import vectorstore
from ..logger import error_logger, op_logger

SUPPORTED_EXTS = {".pdf", ".md", ".markdown", ".txt", ".docx"}

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_NL_RE = re.compile(r"\n{3,}")
# 乱码/不可见字符兜底：替换符、私用区、零宽字符
_GARBLED_RE = re.compile(r"[\ufffd\ufeff\u200b-\u200f\ue000-\uf8ff]")

# 静默损坏征兆字符：PDF 字体缺字时每个汉字会被替换成这类符号（· • ● ▪ □ ■ 等）。
# 它们本身是合法标点（中文间隔号、列表项目符号），因此不能进 clean_text 删除表，
# 只能按占比判定。实测 PyMuPDF 用默认 Helvetica 写中文即产生此形态。
_DAMAGE_CHARS = frozenset("\u00b7\u2022\u2027\u2219\u25cf\u25aa\u25a0\u25a1\u25af\ufffd")
_DAMAGE_MIN_COUNT = 10
_DAMAGE_MIN_RATIO = 0.30


@dataclass
class IngestResult:
    source: str
    version: str
    topic: str
    chunks: int = 0
    chars: int = 0
    elapsed_sec: float = 0.0
    pages: int | None = None  # PDF 页数
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # 不阻断入库的质量告警（ok 不受影响）

    @property
    def ok(self) -> bool:
        return self.chunks > 0 and not self.errors


def clean_text(text: str) -> str:
    """文本清洗（PRD 3.2.1：去除乱码、多余空白）。"""
    text = text or ""
    text = _GARBLED_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def detect_text_damage(text: str) -> tuple[int, float]:
    """检测字体缺字型的静默损坏。返回 ``(可疑字符数, 占非 ASCII 字符的比例)``。

    这类文本长度看似正常，实则每个汉字被替换成一个点，向量化后只会污染检索，
    所以在入库阶段就要暴露出来，而不是等到问答才发现「知识库里没有内容」。
    """
    t = text or ""
    non_ascii = [ch for ch in t if ord(ch) > 127 and not ch.isspace()]
    if not non_ascii:
        return 0, 0.0
    bad = sum(1 for ch in non_ascii if ch in _DAMAGE_CHARS)
    return bad, bad / len(non_ascii)


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[str]:
    """按段落/标题边界合并分块，块长约 chunk_size 字符，相邻块重叠 overlap 字符。

    中文场景下 1 字符 ≈ 1 token，700 落在 PRD 的 500-800 token 区间。
    段落边界优先，避免把句子拦腰截断；超长单段按字符硬切。
    """
    text = clean_text(text)
    if not text:
        return []
    if overlap >= chunk_size:
        overlap = chunk_size // 5

    # 拆成自然段（空行分隔）
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        # 单段超长：先收尾当前 buf，再对长段硬切
        if len(para) > chunk_size:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(para), chunk_size - overlap):
                seg = para[i : i + chunk_size]
                if len(seg) > 40:  # 过短的尾巴并入下一块
                    chunks.append(seg)
                else:
                    buf = seg
                if i + chunk_size >= len(para):
                    break
            continue
        if len(buf) + len(para) + 2 > chunk_size and buf:
            chunks.append(buf)
            # 重叠：取上一块尾部 overlap 字符作为新块前缀
            tail = buf[-overlap:] if overlap else ""
            buf = (tail + "\n\n" + para).strip()
        else:
            buf = f"{buf}\n\n{para}".strip() if buf else para
    if buf and len(buf) > 40 or (buf and not chunks):
        chunks.append(buf)
    return [c for c in (clean_text(c) for c in chunks) if c]


def parse_file(path: Path) -> tuple[str, list[str] | None]:
    """解析文件为文本。

    返回 ``(整篇文本, 按页文本列表)``；非 PDF 的页列表为 None。
    """
    ext = path.suffix.lower()
    if ext == ".pdf":
        import pymupdf

        doc = pymupdf.open(path)
        try:
            pages = [page.get_text("text") for page in doc]
        finally:
            doc.close()
        full = "\n\n".join(pages)
        return full, pages
    if ext == ".docx":
        from docx import Document as DocxDocument

        d = DocxDocument(path)
        parts = []
        for para in d.paragraphs:
            t = para.text.strip()
            if not t:
                continue
            style = para.style.name if para.style is not None else ""
            if style.lower().startswith("heading"):
                t = "# " + t  # 标题补 Markdown 记号，便于分块识别
            parts.append(t)
        return clean_text("\n\n".join(parts)), None
    # .md / .markdown / .txt
    raw = path.read_text(encoding="utf-8", errors="replace")
    return clean_text(raw), None


def slugify(text: str) -> str:
    """生成 topic 标签：保留中英文数字，其余转下划线。"""
    t = unicodedata.normalize("NFKC", text or "").strip()
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "_", t, flags=re.UNICODE)
    return t.strip("_")[:40] or "unknown"


def extract_topic(source_name: str, text: str) -> str:
    """自动提取主题标签：优先取首个 Markdown 标题 / 首行，回退文件名。"""
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        heading = re.sub(r"^#{1,6}\s*", "", line).strip()
        if len(heading) >= 2 and len(heading) <= 40:
            return slugify(heading)
        break
    return slugify(Path(source_name).stem)


def ingest_file(
    settings: Settings | None,
    file_path: str | Path,
    version: str = "v1.0",
    topic: str | None = None,
    folder_id: str = "",
    folder_path: str = "",
) -> IngestResult:
    """完整入库流程。同一 (文件夹, source, version) 重复入库会先清除旧块再写入。

    folder_id/folder_path 来自知识库文件夹树（agents/library.py）；空串表示「未分类」。
    """
    s = settings or get_settings()
    path = Path(file_path)
    t0 = time.time()

    if path.suffix.lower() not in SUPPORTED_EXTS:
        result = IngestResult(source=path.name, version=version, topic="", errors=[
            f"不支持的文件格式: {path.suffix}（支持: {', '.join(sorted(SUPPORTED_EXTS))}）"
        ])
        error_logger.error("入库失败 %s: %s", path.name, result.errors[0],
                           extra={"module_name": "ingestion"})
        return result

    result = IngestResult(source=path.name, version=version, topic="")
    try:
        full_text, pages = parse_file(path)
    except Exception as exc:  # noqa: BLE001 - 解析失败需记录后返回
        result.errors.append(f"解析失败: {type(exc).__name__}: {exc}")
        result.elapsed_sec = time.time() - t0
        error_logger.error("入库解析失败 %s: %s", path.name, exc, exc_info=exc,
                           extra={"module_name": "ingestion"})
        return result

    result.topic = topic or extract_topic(path.name, full_text)

    # 静默损坏检测（字体缺字 / 无文字层的扫描件）：不阻断入库，但必须暴露
    bad, ratio = detect_text_damage(full_text)
    if bad >= _DAMAGE_MIN_COUNT and ratio >= _DAMAGE_MIN_RATIO:
        result.warnings.append(
            f"提取文本疑似损坏：{bad} 个占位符字符（占非 ASCII 的 {ratio:.0%}），"
            f"疑似 PDF 字体缺字或扫描件无文字层，检索质量会受影响"
        )
        error_logger.warning("入库质量警告 %s: %s", path.name, result.warnings[-1],
                             extra={"module_name": "ingestion"})

    # 组装待入库块（PDF 带页码）
    chunk_records: list[dict] = []
    if pages is not None:
        result.pages = len(pages)
        for pno, page_text in enumerate(pages, start=1):
            for c in chunk_text(page_text, s.chunk_size, s.chunk_overlap):
                chunk_records.append({"content": c, "page": pno})
    else:
        for c in chunk_text(full_text, s.chunk_size, s.chunk_overlap):
            chunk_records.append({"content": c, "page": None})

    if not chunk_records:
        result.errors.append("解析后无有效文本内容")
        result.elapsed_sec = time.time() - t0
        error_logger.error("入库内容为空: %s", path.name,
                           extra={"module_name": "ingestion"})
        return result

    # 覆盖写入：先删同 (folder, source, version) 旧块
    removed = vectorstore.delete_by_source(s, path.name, version, folder_id=folder_id)
    for idx, r in enumerate(chunk_records):
        r["idx"] = idx
        r.update(
            source=path.name,
            version=version,
            topic=result.topic,
            folder_id=folder_id,
            folder_path=folder_path,
        )
    vectorstore.add_chunks(s, chunk_records)

    result.chunks = len(chunk_records)
    result.chars = len(full_text)
    result.elapsed_sec = time.time() - t0
    op_logger.info(
        "入库成功: %s [%s] 文件夹=%s 主题=%s 块数=%d 字符=%d 页数=%s 耗时=%.1fs（覆盖旧块 %d）",
        path.name, version, folder_path or "-", result.topic, result.chunks, result.chars,
        result.pages if result.pages is not None else "-", result.elapsed_sec, removed,
        extra={"module_name": "ingestion"},
    )
    return result
