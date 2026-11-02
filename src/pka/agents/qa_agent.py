"""QA Agent（PRD 3.2.2）。

流程：问题 -> ChromaDB 检索 Top-K（默认 K=5）-> 组装 Prompt -> 当前模型生成回答
     -> 回答附引用来源（文件名 + 页码/段落 + 版本）。

模型来源由 MODEL_PROVIDER 决定（见 model_factory），业务代码只依赖
BaseChatModel 接口。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings, get_settings
from ..core import vectorstore
from ..core.model_factory import build_chat_model, get_chat_model
from ..logger import error_logger, op_logger

SYSTEM_PROMPT_TEMPLATE = """你是一位个人知识助手，只依据下方【知识库摘录】回答用户问题。

规则：
1. 答案必须基于摘录；摘录中没有的内容，明确说明“知识库中暂未收录”，不要编造。
2. 答案末尾单列一行引用来源，格式：引用：[1] 文件名(第X页) v版本号；多条用分号隔开。
   只列出你实际用到的摘录编号。
3. 使用中文回答，简洁清晰；涉及代码时给出可运行的代码块。

【知识库摘录】
{context}
"""


@dataclass
class Citation:
    index: int
    source: str
    page: int  # 0 表示非分页文档（整篇/段落）
    version: str
    topic: str
    score: float
    snippet: str
    folder: str = ""  # 所属知识库文件夹路径，如 Python/基础语法

    def label(self) -> str:
        loc = f"第{self.page}页" if self.page else "段落"
        prefix = f"{self.folder} · " if self.folder else ""
        return f"{prefix}{self.source}({loc}) {self.version}"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "source": self.source,
            "page": self.page,
            "version": self.version,
            "topic": self.topic,
            "score": round(self.score, 4),
            "snippet": self.snippet,
            "folder": self.folder,
        }


@dataclass
class QAResult:
    question: str
    answer: str
    citations: list[Citation] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    elapsed_sec: float = 0.0
    used_llm: bool = True


class QAAgent:
    """RAG 问答 Agent。settings 可注入以便运行时切换模型源。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _build_context(self, hits: list[vectorstore.SearchHit]) -> tuple[str, list[Citation]]:
        blocks: list[str] = []
        citations: list[Citation] = []
        for i, h in enumerate(hits, start=1):
            meta = h.metadata
            page = int(meta.get("page") or 0)
            loc = f"第{page}页" if page else "段落"
            blocks.append(
                f"[{i}] 来源: {meta.get('source', '?')} | {loc} | "
                f"版本: {meta.get('version', '?')} | 主题: {meta.get('topic', '-')}\n"
                f"{h.content.strip()}"
            )
            citations.append(
                Citation(
                    index=i,
                    source=meta.get("source", "?"),
                    page=page,
                    version=meta.get("version", "?"),
                    topic=meta.get("topic", ""),
                    score=h.score,
                    snippet=h.content.strip()[:120],
                    folder=meta.get("folder_path", ""),
                )
            )
        return "\n\n".join(blocks), citations

    @staticmethod
    def _invoke(model, prompt: str, question: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = model.invoke([SystemMessage(content=prompt), HumanMessage(content=question)])
        return (resp.content if isinstance(resp.content, str) else str(resp.content)).strip()

    def ask(
        self,
        question: str,
        k: int | None = None,
        context_limit: int = 600,
        folder_ids: list[str] | None = None,
    ) -> QAResult:
        """folder_ids 限定检索范围（当前文件夹及其子孙）；None/空 = 全库。"""
        s = self.settings
        t0 = time.time()
        question = (question or "").strip()
        if not question:
            return QAResult(question="", answer="（空问题）", used_llm=False)

        k = k or s.top_k
        hits = vectorstore.search(s, question, k=k, where=vectorstore.folder_where(folder_ids))

        if not hits:
            result = QAResult(
                question=question,
                answer="知识库中暂未收录相关内容。请先上传学习资料（PDF/MD/TXT/DOCX），或换个问法再试。",
                used_llm=False,
                provider=s.model_provider,
                elapsed_sec=time.time() - t0,
            )
            op_logger.info("QA 未命中: %s", question[:80], extra={"module_name": "qa_agent"})
            return result

        context, citations = self._build_context(hits)
        # 控制上下文长度，避免超出模型窗口
        context = context[: context_limit * max(k, 1)]
        prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)

        model, provider = get_chat_model(s)
        answer = ""
        try:
            answer = self._invoke(model, prompt, question)
        except Exception as exc:  # noqa: BLE001 - 模型调用失败需兜底，不能让问答直接崩
            error_logger.error("QA 模型调用失败: %s", exc, exc_info=exc,
                               extra={"module_name": "qa_agent"})
            # 构建期失败已在 get_chat_model 内降级；调用期失败（额度耗尽/超时/网络）在这里补降级
            if s.enable_fallback and provider != "ollama":
                try:
                    model = build_chat_model(s, "ollama")
                    provider = "ollama"
                    answer = self._invoke(model, prompt, question)
                    answer += (
                        "\n\n> 提示：云端模型调用失败，已自动降级本地 Ollama（原因见 logs\\error.log）。"
                    )
                    op_logger.warning("QA 云端调用失败，已降级本地 Ollama: %s", exc,
                                      extra={"module_name": "qa_agent"})
                except Exception as exc2:  # noqa: BLE001
                    error_logger.error("QA 降级本地模型同样失败: %s", exc2, exc_info=exc2,
                                       extra={"module_name": "qa_agent"})
            if not answer:
                fallback = "\n\n".join(f"[{c.index}] {c.label()}: {c.snippet}" for c in citations)
                answer = (
                    f"模型调用失败（{type(exc).__name__}: {exc}），以下为检索到的相关内容：\n\n{fallback}"
                )

        result = QAResult(
            question=question,
            answer=answer,
            citations=citations,
            provider=provider,
            model=str(getattr(model, "model", s.ollama_model) or ""),
            elapsed_sec=time.time() - t0,
        )
        op_logger.info(
            "QA 完成: %s | 命中=%d 模型=%s 耗时=%.1fs",
            question[:80], len(hits), provider, result.elapsed_sec,
            extra={"module_name": "qa_agent"},
        )
        return result
