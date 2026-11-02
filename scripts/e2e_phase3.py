"""Phase 3 端到端：真实 Ollama 跑技术更迭评估（PRD 3.2.3）。

场景：先入库"异步旧方案（回调+线程池）"，再评估"异步新语法（async/await）"。
期望：模型给出 REPLACE 或 KEEP_OLD 的明确决策 + 理由 + 两项 1-5 评分 + 落更迭记录；
      REPLACE 时旧版本向量被删除、新文档以 v2.0 入库。

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
    tmp = Path(tempfile.mkdtemp(prefix="pka_e2e3_"))
    os.environ["PKA_DATA_DIR"] = str(tmp / "data")
    os.environ["PKA_LOG_DIR"] = str(tmp / "logs")
    os.environ["MODEL_PROVIDER"] = "ollama"

    from pka.agents import update_agent as ua  # noqa: E402
    from pka.agents.ingestion import ingest_file  # noqa: E402
    from pka.agents.qa_agent import QAAgent  # noqa: E402
    from pka.config import get_settings  # noqa: E402
    from pka.core import vectorstore  # noqa: E402
    from pka.core.model_factory import probe_ollama  # noqa: E402

    s = get_settings()
    s.ensure_dirs()
    failures: list[str] = []

    online, msg = probe_ollama(s)
    print(f"Ollama: {msg}")
    if not online:
        print("PHASE3 E2E: FAIL（Ollama 不可用）")
        return 1

    print("\n== 1. 入库旧方案 ==")
    old_path = ROOT / "examples" / "python_异步旧方案_回调与线程池.md"
    old_res = ingest_file(s, old_path, version="v1.0", topic="Python异步")
    print(f"  {old_res.source}: ok={old_res.ok} 块数={old_res.chunks} 字符={old_res.chars} 耗时={old_res.elapsed_sec:.1f}s")
    if not old_res.ok:
        print("PHASE3 E2E: FAIL（旧文档入库失败）", old_res.errors)
        return 1

    print("\n== 2. 更迭评估（新方案）==")
    new_path = ROOT / "examples" / "python_异步新语法.md"
    dec = ua.evaluate_file(s, new_path, version="v1.0", topic="Python异步")
    print(f"  关键技术点: {dec.key_points}")
    print(f"  决策: {dec.decision}")
    print(f"  理由: {dec.reason}")
    print(f"  稳定性评分: {dec.stability_score}/5 · 性能评分: {dec.performance_score}/5")
    print(f"  版本: {dec.old_version} -> {dec.new_version} · applied={dec.applied} · 耗时={dec.elapsed_sec:.1f}s")
    if dec.errors:
        print(f"  errors: {dec.errors}")

    if dec.decision not in (ua.DECISION_REPLACE, ua.DECISION_KEEP):
        failures.append(f"决策值非法: {dec.decision}")
    if not dec.reason:
        failures.append("缺少决策理由")
    if not (1 <= dec.stability_score <= 5):
        failures.append(f"稳定性评分越界: {dec.stability_score}")
    if not (1 <= dec.performance_score <= 5):
        failures.append(f"性能评分越界: {dec.performance_score}")
    if not dec.key_points:
        failures.append("未抽取出关键技术点")

    print("\n== 3. 更迭记录 ==")
    records = ua.read_records(s)
    print(f"  记录条数: {len(records)}")
    if records:
        r = records[-1]
        print(f"  {r.get('timestamp')} | {r.get('decision')} | {r.get('old_version')}->{r.get('new_version')} | {r.get('reason')}")
    if not records:
        failures.append("未写入更迭记录")

    print("\n== 4. 知识库状态 ==")
    sources = vectorstore.list_sources(s)
    for x in sources:
        print(f"  {x['source']} {x['version']} 块数={x['chunk_count']} 主题={x['topic']}")
    names = {(x["source"], x["version"]) for x in sources}
    if dec.decision == ua.DECISION_REPLACE:
        if ("python_异步旧方案_回调与线程池.md", "v1.0") in names:
            failures.append("REPLACE 后旧版本仍存在")
        if ("python_异步新语法.md", dec.new_version) not in names:
            failures.append("REPLACE 后新版本未入库")

    print("\n== 5. 检索验证 ==")
    qa = QAAgent(s)
    ans = qa.ask("异步编程为什么优于回调和线程池？")
    print(f"  回答: {ans.answer[:160]}…")
    print(f"  引用: {[c.label() for c in ans.citations]}")
    if not ans.answer:
        failures.append("问答无回答")
    if not ans.citations:
        failures.append("问答无引用")

    print("\n== 6. 结论 ==")
    if failures:
        for f in failures:
            print("  FAIL:", f)
        print("PHASE3 E2E: FAIL")
        return 1
    print("PHASE3 E2E: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())