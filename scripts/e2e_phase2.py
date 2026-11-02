"""Phase 2 端到端：真实 Ollama + 真实 Streamlit（AppTest）跑通问答与历史。

流程：
1. 用临时数据目录，避免污染真实知识库
2. 入库一篇 md
3. AppTest 加载 app.py，在侧栏切换 Top-K，提交问题
4. 断言：回答非空、含引用、sqlite 落库

退出码 0 = PASS。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="pka_e2e2_"))
    os.environ["PKA_DATA_DIR"] = str(tmp / "data")
    os.environ["PKA_LOG_DIR"] = str(tmp / "logs")
    os.environ["MODEL_PROVIDER"] = "ollama"

    from pka.agents.history import HistoryStore  # noqa: E402
    from pka.agents.ingestion import ingest_file  # noqa: E402
    from pka.config import get_settings  # noqa: E402
    from pka.core.model_factory import probe_ollama  # noqa: E402

    s = get_settings()
    s.ensure_dirs()
    print(f"数据目录: {s.data_dir}")

    online, msg = probe_ollama(s)
    print(f"Ollama: {msg}")
    if not online:
        print("PHASE2 E2E: FAIL（Ollama 不可用）")
        return 1

    print("\n== 1. 入库示例文档 ==")
    sample = ROOT / "examples" / "python_装饰器与生成器笔记.md"
    res = ingest_file(s, sample)
    print(f"  {res.source}: ok={res.ok} 块数={res.chunks} 字符={res.chars} 耗时={res.elapsed_sec:.1f}s")
    if not res.ok:
        print("PHASE2 E2E: FAIL（入库失败）", res.errors)
        return 1

    print("\n== 2. AppTest 加载前端 ==")
    from streamlit.testing.v1 import AppTest  # noqa: E402

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    if at.exception:
        print("PHASE2 E2E: FAIL（前端异常）", list(at.exception))
        return 1
    print(f"  标签页: {len(at.tabs)} · 侧栏 radio: {len(at.sidebar.radio)}")

    print("\n== 3. 提交问题（走真实 LLM）==")
    q = "Python 装饰器怎么实现？给一个最简例子。"
    at.chat_input[0].set_value(q).run()
    if at.exception:
        print("PHASE2 E2E: FAIL（提交后异常）", list(at.exception))
        return 1

    md_blobs = " ".join(m.value for m in at.markdown)
    print(f"  页面 markdown 元素: {len(at.markdown)}")
    if "装饰器" not in md_blobs:
        print("PHASE2 E2E: FAIL（回答中未见关键词）")
        print(md_blobs[:600])
        return 1
    print("  回答包含关键词 ✓")

    print("\n== 4. 对话历史落库 ==")
    store = HistoryStore(s)
    sessions = store.list_sessions()
    if not sessions:
        print("PHASE2 E2E: FAIL（无会话记录）")
        return 1
    sid = sessions[0]["id"]
    msgs = store.get_messages(sid)
    print(f"  会话 {sid}: {len(msgs)} 条消息")
    for m in msgs:
        print(f"    [{m['role']}] {m['content'][:50]}… 引用={len(m['citations'])}")
    if len(msgs) < 2:
        print("PHASE2 E2E: FAIL（消息数不足）")
        return 1
    if not msgs[-1]["citations"]:
        print("PHASE2 E2E: FAIL（引用未落库）")
        return 1

    print("\n== 5. 模型源切换（配置层）==")
    for p in ("ollama", "dashscope", "deepseek"):
        ok, detail = s.provider_ready(p)
        print(f"  {p}: {ok} — {detail}")
    swapped = s.with_provider("dashscope")
    print(f"  切换副本 provider={swapped.model_provider}（原配置未变: {s.model_provider}）")
    if swapped.model_provider != "dashscope" or s.model_provider != "ollama":
        print("PHASE2 E2E: FAIL（切换逻辑错误）")
        return 1

    print("\nPHASE2 E2E: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())