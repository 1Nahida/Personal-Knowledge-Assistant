"""Phase 3 单元测试：Update Agent（离线，用假模型）。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pka.agents import update_agent as ua  # noqa: E402
from pka.agents.ingestion import ingest_file  # noqa: E402
from pka.config import Settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402


@dataclass
class _Msg:
    content: str


class FakeModel:
    """按顺序返回预设内容，模拟 LLM 输出。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def invoke(self, messages):
        self.prompts.append(messages[-1].content)
        return _Msg(self.replies.pop(0) if self.replies else "{}")


@pytest.fixture
def env(tmp_path):
    s = Settings(
        model_provider="ollama",
        embedding_provider="hash",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    s.ensure_dirs()
    vectorstore.reset_client()
    yield s
    vectorstore.reset_client()


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


OLD_DOC = """# Python 异步编程

回调函数嵌套导致回调地狱，代码难以维护。
使用线程池处理并发，线程切换开销较大。
"""

NEW_DOC = """# Python 异步编程新方案

使用 async/await 原生协程，避免回调地狱。
相比线程池，协程切换开销显著更低，内存占用更小。
"""


def _seed_old(env, tmp_path):
    ingest_file(env, _write(tmp_path, "old_async.md", OLD_DOC), version="v1.0", topic="Python异步")


def test_extract_key_points_parses_fenced_json(env):
    model = FakeModel('```json\n["采用协程", "内存占用降低"]\n```')
    points = ua.extract_key_points(env, "正文", model=model)
    assert points == ["采用协程", "内存占用降低"]


def test_extract_key_points_bad_json_returns_empty(env):
    model = FakeModel("我无法抽取")
    assert ua.extract_key_points(env, "正文", model=model) == []


def test_parse_decision_normalises_values():
    d, r, s1, s2 = ua._parse_decision(
        '{"decision": "replace", "reason": "更快", "stability_score": 4, "performance_score": 9}'
    )
    assert d == "REPLACE" and r == "更快"
    assert s1 == 4 and s2 == 5  # 越界分数被裁剪


def test_parse_decision_unknown_falls_back_to_keep():
    d, *_ = ua._parse_decision('{"decision": "???"}')
    assert d == "KEEP_OLD"


def test_evaluate_file_without_baseline_ingests(env, tmp_path):
    r = ua.evaluate_file(env, _write(tmp_path, "a.md", OLD_DOC), topic="Python异步",
                         model=FakeModel('["回调嵌套"]'))
    assert r.decision == ua.DECISION_INGEST
    assert r.applied is True
    assert vectorstore.count(env) > 0


def test_evaluate_file_replace_swaps_version(env, tmp_path):
    _seed_old(env, tmp_path)
    before = vectorstore.count(env)

    model = FakeModel(
        '["async/await 原生协程"]',
        '{"decision": "REPLACE", "reason": "协程开销更低", "stability_score": 4, "performance_score": 5}',
    )
    r = ua.evaluate_file(env, _write(tmp_path, "new_async.md", NEW_DOC), topic="Python异步", model=model)

    assert r.decision == ua.DECISION_REPLACE
    assert r.applied is True
    assert r.old_version == "v1.0"
    assert r.new_version == "v2.0"

    sources = {(x["source"], x["version"]) for x in vectorstore.list_sources(env)}
    assert ("old_async.md", "v1.0") not in sources  # 旧向量已删除
    assert ("new_async.md", "v2.0") in sources
    assert len(model.prompts) == 2  # 一次抽取 + 一次评估
    assert "资深技术评审专家" in model.prompts[1]


def test_evaluate_file_keep_old_leaves_kb_untouched(env, tmp_path):
    _seed_old(env, tmp_path)
    before = vectorstore.count(env)

    model = FakeModel(
        '["使用了协程"]',
        '{"decision": "KEEP_OLD", "reason": "新方案未经生产验证", "stability_score": 2, "performance_score": 4}',
    )
    r = ua.evaluate_file(env, _write(tmp_path, "new_async.md", NEW_DOC), topic="Python异步", model=model)

    assert r.decision == ua.DECISION_KEEP
    assert r.applied is False
    assert vectorstore.count(env) == before  # 知识库不变
    assert "生产验证" in r.reason


def test_records_written_to_jsonl(env, tmp_path):
    _seed_old(env, tmp_path)
    model = FakeModel(
        '["协程"]',
        '{"decision": "KEEP_OLD", "reason": "等价", "stability_score": 3, "performance_score": 3}',
    )
    ua.evaluate_file(env, _write(tmp_path, "new_async.md", NEW_DOC), topic="Python异步", model=model)

    records = ua.read_records(env)
    assert records, "未写入更迭记录"
    rec = records[-1]
    for key in ("timestamp", "topic", "old_version", "new_version", "decision", "reason",
                "stability_score", "performance_score"):
        assert key in rec
    assert rec["decision"] == "KEEP_OLD"
    assert Path(env.update_log_file).exists()


def test_apply_false_does_not_touch_kb(env, tmp_path):
    _seed_old(env, tmp_path)
    before = vectorstore.count(env)
    model = FakeModel(
        '["协程"]',
        '{"decision": "REPLACE", "reason": "更好", "stability_score": 5, "performance_score": 5}',
    )
    r = ua.evaluate_file(env, _write(tmp_path, "new_async.md", NEW_DOC), topic="Python异步",
                         apply=False, model=model)
    assert r.decision == ua.DECISION_REPLACE
    assert r.applied is False
    assert vectorstore.count(env) == before

def test_replace_never_deletes_unrelated_topic(env, tmp_path):
    """回归：REPLACE 只能删同主题旧版本，不能误删其他主题的资料。"""
    _seed_old(env, tmp_path)
    other = _write(tmp_path, "unrelated.md", "# 做菜笔记\n\n红烧肉要先焯水，再小火慢炖四十分钟。")
    assert ingest_file(env, other, version="v1.0", topic="烹饪").ok

    model = FakeModel(
        '["协程"]',
        '{"decision": "REPLACE", "reason": "更好", "stability_score": 5, "performance_score": 5}',
    )
    r = ua.evaluate_file(env, _write(tmp_path, "new_async.md", NEW_DOC), topic="Python异步", model=model)
    assert r.decision == ua.DECISION_REPLACE

    names = {(x["source"], x["version"]) for x in vectorstore.list_sources(env)}
    assert ("unrelated.md", "v1.0") in names, "无关主题文档被误删"
    assert ("old_async.md", "v1.0") not in names


def test_topic_normalisation_matches(env, tmp_path):
    """「Python 异步」与「python_异步」视为同主题。"""
    ingest_file(env, _write(tmp_path, "old2.md", OLD_DOC), version="v1.0", topic="python_异步")
    model = FakeModel(
        '["协程"]',
        '{"decision": "REPLACE", "reason": "更好", "stability_score": 5, "performance_score": 5}',
    )
    r = ua.evaluate_file(env, _write(tmp_path, "new2.md", NEW_DOC), topic="Python 异步", model=model)
    assert r.old_version == "v1.0"
    assert r.decision == ua.DECISION_REPLACE