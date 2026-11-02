"""临时取证：打印 Chroma 库里指定来源的原始块文本，用于判断解析质量。"""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from pka.config import get_settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402


def main() -> int:
    s = get_settings()
    print("collection:", vectorstore.collection_name(s), "| total:", vectorstore.count(s))
    col = vectorstore.get_collection(s)
    for source in ("_e2e_sample.pdf", "_e2e_sample.docx"):
        res = col.get(where={"source": source}, include=["documents", "metadatas"])
        print(f"\n== {source}: {len(res['ids'])} chunks ==")
        for i, (doc, meta) in enumerate(zip(res["documents"], res["metadatas"]), 1):
            print(f"[{i}] page={meta.get('page')} len={len(doc)}")
            print("    repr:", repr(doc[:300]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
