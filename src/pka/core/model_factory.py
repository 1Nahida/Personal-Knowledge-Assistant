"""模型工厂（PRD 4.3 / 3.2.4）。

根据 MODEL_PROVIDER 路由到对应客户端，业务模块只依赖 LangChain 的
BaseChatModel 抽象接口，切换模型源无需修改业务逻辑：

- ``ollama``    -> ChatOllama（本地，默认，数据不出本地）
- ``dashscope`` -> ChatOpenAI（阿里云百炼 OpenAI 兼容接口）
- ``deepseek``  -> ChatOpenAI（DeepSeek OpenAI 兼容接口）

降级策略（PRD 3.2.4）：
- 云端 API 不可用（未配 Key / 构建失败）且开启 ENABLE_FALLBACK 时，
  自动降级到本地 Ollama，并写 operation 日志；
- 本地 Ollama 服务不可用时，抛出带操作指引的异常（ollama serve / ollama list）。
"""

from __future__ import annotations

import urllib.request

from ..config import Settings, get_settings
from ..logger import op_logger

DEFAULT_TIMEOUT = 3


class ProviderNotReadyError(RuntimeError):
    """模型源不可用（缺 Key / 配置错误 / 服务未启动）。"""


def probe_ollama(settings: Settings | None = None) -> tuple[bool, str]:
    """探测本地 Ollama 服务是否在线（GET /api/version）。"""
    s = settings or get_settings()
    try:
        req = urllib.request.Request(s.ollama_base_url.rstrip("/") + "/api/version")
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            if resp.status == 200:
                return True, f"Ollama 在线: {s.ollama_base_url}"
        return False, f"Ollama 响应异常: HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001 - 探测需吞掉一切网络异常
        return False, f"Ollama 不可达: {exc}"


def _build_ollama(s: Settings):
    ok, msg = probe_ollama(s)
    if not ok:
        raise ProviderNotReadyError(
            f"{msg}。请确认 Ollama 已启动（命令行执行 `ollama serve`，"
            f"或检查 Windows 托盘中的 Ollama），并确认模型已安装（`ollama list`，"
            f"需要 {s.ollama_model}）。"
        )
    from langchain_ollama import ChatOllama

    return ChatOllama(
        base_url=s.ollama_base_url,
        model=s.ollama_model,
        num_ctx=s.ollama_num_ctx,
        temperature=s.ollama_temperature,
        client_kwargs={"timeout": s.request_timeout},
    )


def _build_openai_compatible(s: Settings, provider: str):
    api_key = s.dashscope_api_key if provider == "dashscope" else s.deepseek_api_key
    if not api_key:
        env_name = "DASHSCOPE_API_KEY" if provider == "dashscope" else "DEEPSEEK_API_KEY"
        raise ProviderNotReadyError(f"未配置 {env_name}，请在 .env 中填入 API Key 后再切换到 {provider}")
    from langchain_openai import ChatOpenAI

    base_url = s.dashscope_base_url if provider == "dashscope" else s.deepseek_base_url
    model = s.dashscope_model if provider == "dashscope" else s.deepseek_model
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.1,
        timeout=s.request_timeout,
    )


def build_chat_model(settings: Settings | None = None, provider: str | None = None):
    """构建指定模型源对应的 BaseChatModel。不可用时抛 ProviderNotReadyError。"""
    s = settings or get_settings()
    p = provider or s.model_provider
    if p == "ollama":
        return _build_ollama(s)
    if p in ("dashscope", "deepseek"):
        return _build_openai_compatible(s, p)
    raise ProviderNotReadyError(f"未知模型源: {p}")


def get_chat_model(settings: Settings | None = None):
    """业务入口：返回 ``(model, provider)``。

    优先使用配置的 MODEL_PROVIDER；云端不可用且 ENABLE_FALLBACK 时
    自动降级到本地 Ollama 并记录日志。Ollama 也不可用则抛异常。
    """
    s = settings or get_settings()
    p = s.model_provider
    try:
        return build_chat_model(s, p), p
    except ProviderNotReadyError as exc:
        if s.enable_fallback and p != "ollama":
            op_logger.warning(
                "模型源 %s 不可用（%s），自动降级到本地 Ollama", p, exc,
                extra={"module_name": "model_factory"},
            )
            return build_chat_model(s, "ollama"), "ollama"
        raise
