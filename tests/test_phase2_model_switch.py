"""Phase 2 单元测试：模型源切换与降级（不依赖网络）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pka.config import Settings  # noqa: E402
from pka.core import model_factory  # noqa: E402
from pka.core.model_factory import ProviderNotReadyError, get_chat_model  # noqa: E402


@pytest.fixture
def base(tmp_path):
    # 显式清空云端 Key：本机 .env 可能已填真实 Key，测试必须与外部环境隔离
    return Settings(
        embedding_provider="hash",
        dashscope_api_key="",
        deepseek_api_key="",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )


def test_dashscope_without_key_raises(base):
    s = base.with_provider("dashscope")
    with pytest.raises(ProviderNotReadyError, match="DASHSCOPE_API_KEY"):
        model_factory.build_chat_model(s)


def test_deepseek_without_key_raises(base):
    s = base.with_provider("deepseek")
    with pytest.raises(ProviderNotReadyError, match="DEEPSEEK_API_KEY"):
        model_factory.build_chat_model(s)


def test_cloud_failure_falls_back_to_ollama(base, monkeypatch):
    """PRD 3.2.4：云端不可用时自动降级本地 Ollama。"""
    s = base.with_provider("dashscope")
    monkeypatch.setattr(model_factory, "_build_ollama", lambda _s: "FAKE_OLLAMA")
    model, provider = get_chat_model(s)
    assert model == "FAKE_OLLAMA"
    assert provider == "ollama"


def test_cloud_failure_raises_when_fallback_disabled(base, monkeypatch):
    s = base.with_provider("dashscope")
    s = type(s)(**{**s.__dict__, "enable_fallback": False})
    with pytest.raises(ProviderNotReadyError):
        get_chat_model(s)


def test_unsupported_provider_rejected(base):
    with pytest.raises(ValueError, match="不支持的模型源"):
        base.with_provider("openai")


def test_provider_ready_reports_missing_keys(base):
    ok, detail = base.provider_ready("dashscope")
    assert ok is False and "DASHSCOPE_API_KEY" in detail
    ok, detail = base.provider_ready("deepseek")
    assert ok is False and "DEEPSEEK_API_KEY" in detail
    ok, detail = base.provider_ready("ollama")
    assert ok is True

class _BoomModel:
    """调用即失败，模拟云端额度耗尽这类“构建成功但调用失败”。"""

    model = "boom-model"

    def invoke(self, _messages):
        raise RuntimeError("403 Free quota exhausted")


class _OkModel:
    model = "fake-ollama"

    def __init__(self):
        self.seen = ""

    def invoke(self, messages):
        self.seen = "\n".join(str(m.content) for m in messages)

        class _R:
            content = "装饰器是用函数包装函数的语法糖。"

        return _R()


def test_runtime_failure_falls_back_to_local(base, monkeypatch, tmp_path):
    """构建成功但调用失败（如云端额度耗尽）时，也应降级本地并给出提示。"""
    from pka.agents import qa_agent
    from pka.agents.ingestion import ingest_file
    from pka.core import vectorstore

    vectorstore.reset_client()
    s = base.with_provider("dashscope")
    sample = tmp_path / "note.md"
    sample.write_text("# 装饰器\n\n装饰器是用函数包装函数的语法糖。", encoding="utf-8")
    ingest_file(s, sample)

    fake = _OkModel()
    monkeypatch.setattr(qa_agent, "get_chat_model", lambda _s: (_BoomModel(), "dashscope"))
    monkeypatch.setattr(qa_agent, "build_chat_model", lambda _s, _p=None: fake)

    res = qa_agent.QAAgent(s).ask("装饰器是什么？")
    assert "语法糖" in res.answer
    assert "已自动降级本地 Ollama" in res.answer
    assert res.provider == "ollama"
    assert "语法糖" in fake.seen  # 本地模型确实拿到了检索上下文
