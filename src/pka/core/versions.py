"""版本号工具（PRD 3.2.3：REPLACE 时版本号 +1）。

版本号格式：``v<major>.<minor>``，默认 v1.0。
更迭替换时 minor 保持不变、major +1（如 v1.0 -> v2.0）。
"""

from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)$")


def parse_version(version: str) -> tuple[int, int]:
    """'v1.0' -> (1, 0)；非法格式按 (0, 0) 处理。"""
    m = _VERSION_RE.match((version or "").strip().lower())
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


def bump_version(version: str) -> str:
    """'v1.0' -> 'v2.0'（技术更迭替换旧版本时使用）。"""
    major, minor = parse_version(version)
    return f"v{major + 1}.{minor}"


def format_version(major: int, minor: int) -> str:
    return f"v{major}.{minor}"


def compare_versions(a: str, b: str) -> int:
    """a<b -> -1, a==b -> 0, a>b -> 1。"""
    pa, pb = parse_version(a), parse_version(b)
    return (pa[0] > pb[0]) - (pa[0] < pb[0]) or (pa[1] > pb[1]) - (pa[1] < pb[1])
