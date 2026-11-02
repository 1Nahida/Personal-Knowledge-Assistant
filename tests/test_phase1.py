"""Phase 1 单元测试 + 离线集成测试。

不依赖 Ollama / 网络：嵌入用 hash 模式，模型用 fake 对象。
运行：.venv\\Scripts\\python.exe -m pytest tests/ -v
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pka.agents import ingestion, qa_agent  # noqa: E402
from pka.config import Settings  # noqa: E402
from pka.core import versions, vectorstore  # noqa: E402
from pka.core.embeddings import HashEmbeddings  # noqa: E402

SAMPLE_MD = ROOT / "examples" / "python_装饰器与生成器笔记.md"


@pytest.fixture()
def settings(tmp_path):
    vectorstore.reset_client()
    s = Settings(
        model_provider="ollama",
        embedding_provider="hash",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    yield s
    vectorstore.reset_client()


# ---------- 清洗 / 分块 ----------

def test_clean_text():
    raw = "abc\x00def\r\n\r\n\r\n\r\n中文\ufffd文本   \n"
    out = ingestion.clean_text(raw)
    assert "\x00" not in out and "\ufffd" not in out
    assert "\r" not in out
    assert "\n\n\n" not in out
    assert out == "abcdef\n\n中文文本"


def test_chunk_text_basic():
    assert ingestion.chunk_text("") == []
    short = ingestion.chunk_text("很短的一段话。", chunk_size=700)
    assert len(short) == 1

    long_text = "\n\n".join(f"第{i}段。" * 40 for i in range(30))
    chunks = ingestion.chunk_text(long_text, chunk_size=700, overlap=120)
    assert len(chunks) >= 3
    for c in chunks:
        # 允许因段落边界略超，但不允许失控
        assert len(c) <= 700 + 200


# ---------- hash 嵌入 ----------

def test_hash_embeddings_deterministic_and_normalized():
    emb = HashEmbeddings(dim=256)
    v1 = emb.embed_query("装饰器")
    v2 = emb.embed_query("装饰器")
    assert v1 == v2
    assert len(v1) == 256
    assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-9)
    assert emb.embed_query("装饰器") != emb.embed_query("生成器")
    docs = emb.embed_documents(["a", "b"])
    assert len(docs) == 2 and all(len(d) == 256 for d in docs)


# ---------- 版本工具 ----------

def test_versions():
    assert versions.parse_version("v1.0") == (1, 0)
    assert versions.parse_version("1.0") == (1, 0)
    assert versions.bump_version("v1.0") == "v2.0"
    assert versions.bump_version("v3.2") == "v4.2"
    assert versions.compare_versions("v1.0", "v2.0") == -1
    assert versions.compare_versions("v2.0", "v2.0") == 0


# ---------- 入库 + 检索（离线集成） ----------

def test_ingest_and_search(settings):
    r = ingestion.ingest_file(settings, SAMPLE_MD)
    assert r.ok, r.errors
    assert r.chunks >= 3
    assert r.topic  # 自动提取主题

    n = vectorstore.count(settings)
    assert n == r.chunks

    hits = vectorstore.search(settings, "装饰器怎么实现 functools.wraps", k=3)
    assert hits, "应检索到装饰器相关内容"
    assert "装饰器" in hits[0].content
    assert hits[0].metadata["source"] == SAMPLE_MD.name
    assert hits[0].metadata["version"] == "v1.0"
    assert hits[0].score <= 1.0


def test_reingest_replaces(settings):
    r1 = ingestion.ingest_file(settings, SAMPLE_MD)
    r2 = ingestion.ingest_file(settings, SAMPLE_MD)
    assert vectorstore.count(settings) == r1.chunks  # 覆盖而非追加
    assert r2.chunks == r1.chunks


def test_list_sources(settings):
    ingestion.ingest_file(settings, SAMPLE_MD)
    rows = vectorstore.list_sources(settings)
    assert len(rows) == 1
    assert rows[0]["source"] == SAMPLE_MD.name
    assert rows[0]["chunk_count"] >= 3


def test_unsupported_format(settings, tmp_path):
    bad = tmp_path / "x.bin"
    bad.write_bytes(b"\x00\x01")
    r = ingestion.ingest_file(settings, bad)
    assert not r.ok
    assert "不支持" in r.errors[0]


# ---------- QA Agent（fake 模型） ----------

class _FakeResp:
    content = "装饰器是接受函数并返回新函数的高阶函数。引用：[1] python_装饰器与生成器笔记.md(段落) v1.0"


class _FakeModel:
    model = "fake-model"

    def invoke(self, messages):
        assert any("装饰器" in str(m.content) for m in messages)
        return _FakeResp()


def test_qa_agent_with_fake_model(settings, monkeypatch):
    ingestion.ingest_file(settings, SAMPLE_MD)
    monkeypatch.setattr(
        qa_agent, "get_chat_model", lambda s: (_FakeModel(), "ollama")
    )
    agent = qa_agent.QAAgent(settings)
    res = agent.ask("Python 装饰器怎么实现？")
    assert res.used_llm
    assert res.answer.startswith("装饰器是接受函数")
    assert res.citations
    assert res.citations[0].source == SAMPLE_MD.name
    assert res.provider == "ollama"
    assert res.elapsed_sec >= 0


def test_qa_agent_no_hit(settings, monkeypatch):
    called = {}

    def _boom(s):
        called["yes"] = True
        return _FakeModel(), "ollama"

    monkeypatch.setattr(qa_agent, "get_chat_model", _boom)
    res = qa_agent.QAAgent(settings).ask("量子纠缠怎么实现？")
    assert not res.used_llm
    assert "暂未收录" in res.answer
    assert not res.citations
    assert "yes" not in called  # 未命中时不应调用模型


# ---------- 静默损坏检测（字体缺字 / 扫描件无文字层） ----------

def test_detect_text_damage():
    bad, ratio = ingestion.detect_text_damage("ChromaDB " + "·" * 30)
    assert bad == 30
    assert ratio > ingestion._DAMAGE_MIN_RATIO

    normal = "装饰器本质是一个接受函数作为参数并返回新函数的高阶函数。" * 3
    assert ingestion.detect_text_damage(normal) == (0, 0.0)

    # 合法间隔号不应误报：占比低于阈值
    legit = "阿·托尔斯泰" + "很长的中文正文内容用来稀释占位符的比例" * 5
    assert ingestion.detect_text_damage(legit)[1] < ingestion._DAMAGE_MIN_RATIO

    # 纯 ASCII 文档无可判定的非 ASCII 字符
    assert ingestion.detect_text_damage("pure ascii text") == (0, 0.0)


def test_ingest_warns_on_damaged_pdf(settings, tmp_path):
    """PyMuPDF 默认字体无汉字字形，写入的中文会静默变成 '·'，入库阶段必须发现。"""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "damaged.pdf"
    doc = pymupdf.open()
    for line in (
        "ChromaDB 是一个纯本地的嵌入式向量数据库，无需额外部署，",
        "适合个人知识库场景。本段落用于验证字体缺字导致的静默损坏。",
    ):
        page = doc.new_page()
        page.insert_text((72, 100), line, fontsize=14)  # 故意不传 fontname
    doc.save(str(path))
    doc.close()

    res = ingestion.ingest_file(settings, path)
    assert res.ok, "质量警告不应阻断入库"
    assert res.warnings, "字体缺字导致的静默损坏应被检出"
    assert "损坏" in res.warnings[0]
