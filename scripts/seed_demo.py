"""向真实数据目录预置演示资料（幂等：重复执行会覆盖同名同版本）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from pka.agents import update_agent as ua  # noqa: E402
from pka.agents.ingestion import ingest_file  # noqa: E402
from pka.config import get_settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402


def main() -> int:
    s = get_settings()
    s.ensure_dirs()
    ex = ROOT / "examples"

    a = ingest_file(s, ex / "python_装饰器与生成器笔记.md", version="v1.0", topic="Python装饰器与生成器")
    print(f"入库 {a.source}: ok={a.ok} 块数={a.chunks}")

    b = ingest_file(s, ex / "python_异步旧方案_回调与线程池.md", version="v1.0", topic="Python异步")
    print(f"入库 {b.source}: ok={b.ok} 块数={b.chunks}")

    if ua.read_records(s):
        print("已存在更迭记录，跳过更迭演示")
    else:
        dec = ua.evaluate_file(s, ex / "python_异步新语法.md", version="v1.0", topic="Python异步")
        print(f"更迭演示: {dec.decision} {dec.old_version}->{dec.new_version} "
              f"稳定={dec.stability_score} 性能={dec.performance_score}")
        print(f"  理由: {dec.reason}")

    print(f"\n库内文档: {[(x['source'], x['version'], x['chunk_count']) for x in vectorstore.list_sources(s)]}")
    print(f"总块数: {vectorstore.count(s)} · 更迭记录: {len(ua.read_records(s))} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())