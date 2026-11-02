"""全局配置：从 .env 读取模型源、路径、检索参数等。

设计原则（见 PRD 4.3）：业务代码只读这里的配置对象，不直接读环境变量，
这样前端侧边栏切换模型时只需重建 Settings 即可。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# 项目根目录（src/pka/config.py -> src/pka -> src -> 根）
ROOT_DIR = Path(__file__).resolve().parents[2]

# 加载 .env（不存在也不报错，走默认值）
load_dotenv(ROOT_DIR / ".env", override=False)

Provider = Literal["ollama", "dashscope", "deepseek"]

SUPPORTED_PROVIDERS: tuple[Provider, ...] = ("ollama", "dashscope", "deepseek")

PROVIDER_LABELS: dict[str, str] = {
    "ollama": "本地 Ollama（Qwen2.5）",
    "dashscope": "阿里云百炼 DashScope",
    "deepseek": "DeepSeek API",
}


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass
class Settings:
    """运行的完整配置快照。"""

    # ---- 模型源 ----
    model_provider: str = field(default_factory=lambda: _env("MODEL_PROVIDER", "ollama") or "ollama")

    # Ollama
    ollama_base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434") or "http://localhost:11434")
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:7b") or "qwen2.5:7b")
    ollama_num_ctx: int = field(default_factory=lambda: _env_int("OLLAMA_NUM_CTX", 8192))
    ollama_temperature: float = field(default_factory=lambda: _env_float("OLLAMA_TEMPERATURE", 0.1))

    # DashScope（阿里云百炼）
    dashscope_api_key: str = field(default_factory=lambda: _env("DASHSCOPE_API_KEY"))
    dashscope_model: str = field(default_factory=lambda: _env("DASHSCOPE_MODEL", "qwen-plus") or "qwen-plus")
    dashscope_base_url: str = field(
        default_factory=lambda: _env("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    # DeepSeek
    deepseek_api_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    deepseek_model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat")
    deepseek_base_url: str = field(
        default_factory=lambda: _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1") or "https://api.deepseek.com/v1"
    )

    # ---- Embedding ----
    # 默认走 Ollama 的 bge-m3；离线测试可切到 "hash"（内置确定性向量，仅用于单测/演示）
    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "ollama") or "ollama")
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "bge-m3") or "bge-m3")
    embedding_batch_size: int = field(default_factory=lambda: _env_int("EMBEDDING_BATCH_SIZE", 16))

    # ---- 检索 ----
    top_k: int = field(default_factory=lambda: _env_int("TOP_K", 5))
    # Chroma 使用余弦距离，分数 = 1 - distance
    score_threshold: float = field(default_factory=lambda: _env_float("SCORE_THRESHOLD", 0.0))

    # ---- 分块 ----
    chunk_size: int = field(default_factory=lambda: _env_int("CHUNK_SIZE", 700))
    chunk_overlap: int = field(default_factory=lambda: _env_int("CHUNK_OVERLAP", 120))

    # ---- 路径 ----
    root_dir: Path = field(default_factory=lambda: ROOT_DIR)
    data_dir: Path = field(default_factory=lambda: Path(_env("PKA_DATA_DIR") or str(ROOT_DIR / "data")))
    log_dir: Path = field(default_factory=lambda: Path(_env("PKA_LOG_DIR") or str(ROOT_DIR / "logs")))

    # ---- 运行时开关 ----
    # 云端失败时是否自动降级到本地 Ollama（PRD 3.2.4 降级策略）
    enable_fallback: bool = field(default_factory=lambda: _env("ENABLE_FALLBACK", "true").lower() != "false")
    request_timeout: int = field(default_factory=lambda: _env_int("REQUEST_TIMEOUT", 120))

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def history_db(self) -> Path:
        return self.data_dir / "history.db"

    @property
    def library_db(self) -> Path:
        """知识库文件夹（多知识库）注册表，见 agents/library.py。"""
        return self.data_dir / "library.db"

    @property
    def update_log_file(self) -> Path:
        # 结构化更迭记录（JSON Lines），供知识库版本追溯
        return self.data_dir / "update_history.jsonl"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.chroma_dir, self.upload_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 运行时切换 ----
    def with_provider(self, provider: str) -> "Settings":
        """返回一个切换了模型源的配置副本（不落盘，仅本次会话生效）。"""
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"不支持的模型源: {provider}")
        from dataclasses import replace

        return replace(self, model_provider=provider)

    def provider_ready(self, provider: str | None = None) -> tuple[bool, str]:
        """检查某个模型源是否可用（只做配置层校验，网络连通性由 Model Factory 探测）。"""
        p = provider or self.model_provider
        if p == "ollama":
            return True, f"{self.ollama_base_url} / {self.ollama_model}"
        if p == "dashscope":
            if not self.dashscope_api_key:
                return False, "未配置 DASHSCOPE_API_KEY"
            return True, self.dashscope_model
        if p == "deepseek":
            if not self.deepseek_api_key:
                return False, "未配置 DEEPSEEK_API_KEY"
            return True, self.deepseek_model
        return False, f"未知模型源: {p}"


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """获取全局配置单例。"""
    global _settings
    if _settings is None or reload:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def reset_settings() -> None:
    """清空单例（测试用）。"""
    global _settings
    _settings = None