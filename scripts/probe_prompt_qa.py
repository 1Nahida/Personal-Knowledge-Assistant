"""Prompt 变体探针：同一个真实问题（Q2）用不同指令结构跑，找出 qwen2.5:7b 能稳定遵循的写法。

结果写入 docs/_probe_prompt_out.txt（UTF-8），避开 Windows 控制台 GBK 渲染问题。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from pka.agents.qa_agent import QAAgent  # noqa: E402
from pka.config import get_settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402
from pka.core.model_factory import get_chat_model  # noqa: E402

QUESTION = "ChromaDB 是什么？需要额外部署服务吗？"
OUT = ROOT / "docs" / "_probe_prompt_out.txt"

VARIANT_A = """你是一位个人知识助手，只依据下方【知识库摘录】回答用户问题。

规则：
1. 答案必须基于摘录；摘录中没有的内容，明确说明“知识库中暂未收录”，不要编造。
2. 答案末尾单列一行引用来源，格式：引用：[1] 文件名(第X页) v版本号；多条用分号隔开。
   只列出你实际用到的摘录编号。
3. 使用中文回答，简洁清晰；涉及代码时给出可运行的代码块。

【知识库摘录】
{context}
"""

VARIANT_B = """你是一位个人知识助手。下面【知识库摘录】是回答用户问题的唯一资料来源。

规则：
1. 先逐条阅读摘录，判断哪些摘录与问题相关。
2. 只要有一条摘录包含与问题相关的信息，就必须用摘录中的表述作答，禁止说“知识库中暂未收录”。
3. 仅当所有摘录都与问题无关时，才回答“知识库中暂未收录相关内容”。
4. 不要使用摘录之外的知识，不要编造。
5. 答案末尾单列一行引用来源，格式：引用：[1] 文件名(第X页) v版本号。
6. 使用中文，简洁清晰。

【知识库摘录】
{context}
"""

VARIANT_C = """请仅根据下面的【知识库摘录】回答问题。

【知识库摘录】
{context}

【问题】{question}

要求：摘录中有的内容必须拿来作答，不得声称“暂未收录”；摘录中确实没有的不要编造。
回答用中文、简洁，末尾单列一行“引用：[n] 文件名(第X页) v版本号”。
"""


def main() -> int:
    s = get_settings()
    agent = QAAgent(s)
    hits = vectorstore.search(s, QUESTION, k=s.top_k)
    context, citations = agent._build_context(hits)
    model, provider = get_chat_model(s)

    lines: list[str] = [f"provider={provider} model={getattr(model, 'model', '?')}",
                        f"hits={len(hits)}", "context follows:", context, "", "=" * 60, ""]

    def run(name: str, msgs: list) -> None:
        t0 = time.time()
        try:
            resp = model.invoke(msgs)
            ans = resp.content if isinstance(resp.content, str) else str(resp.content)
        except Exception as exc:  # noqa: BLE001
            ans = f"<ERROR {type(exc).__name__}: {exc}>"
        dt = time.time() - t0
        ok = ("暂未收录" not in ans) and ("ChromaDB" in ans)
        lines.append(f"----- {name} | {dt:.1f}s | {'PASS' if ok else 'FAIL'} -----")
        lines.append(ans.strip())
        lines.append("")

    for trial in (1, 2):
        lines.append(f"########## 第 {trial} 次 ##########")
        run(f"A/system t{trial}", [SystemMessage(content=VARIANT_A.format(context=context)),
                                   HumanMessage(content=QUESTION)])
        run(f"B/system t{trial}", [SystemMessage(content=VARIANT_B.format(context=context)),
                                   HumanMessage(content=QUESTION)])
        run(f"C/single t{trial}", [HumanMessage(content=VARIANT_C.format(context=context, question=QUESTION))])

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written:", OUT)
    print(json.dumps({"variants": "A/B/C x2", "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
