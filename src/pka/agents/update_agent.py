"""Update Agent（PRD 3.2.3 技术更迭评估）。

流程：
1. 抽取新文档的关键技术点（LLM）
2. 在知识库中检索同主题旧内容
3. 用「技术评审专家」提示词对比评估，输出决策：REPLACE / KEEP_OLD
   附理由（100 字以内）、稳定性评分 1-5、性能评分 1-5
4. REPLACE → 删除旧向量、写入新内容、版本号 +1、记录更迭日志
   KEEP_OLD → 仅记录拦截原因，知识库不变

更迭记录同时写入：
- `data/update_history.jsonl`（结构化，供知识库版本追溯，PRD 5.2）
- `logs/update.log`（人读日志）
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings, get_settings
from ..core import vectorstore
from ..core.model_factory import get_chat_model
from ..core.versions import bump_version, parse_version
from ..logger import error_logger, update_logger
from .ingestion import SUPPORTED_EXTS, clean_text, extract_topic, ingest_file, parse_file

DECISION_REPLACE = "REPLACE"
DECISION_KEEP = "KEEP_OLD"
DECISION_INGEST = "INGEST"  # 库中无同主题旧内容，直接入库（无对比基线）

EXTRACT_PROMPT = """请从下面的技术文档中抽取关键技术点。

要求：
1. 只抽取可判定的技术结论（如"采用 async/await"、"使用协程替代回调"、"内存占用降低 30%"）。
2. 每条不超过 30 字，最多 {max_points} 条。
3. 只输出 JSON 数组，不要任何解释：["要点1", "要点2"]

【文档】
{text}
"""

COMPARE_PROMPT = """你是一位资深技术评审专家，从稳定性与性能两维度评估。

【旧内容（知识库现有版本 {old_version}）】
{old_context}

【新内容（待评估，版本 {new_version}）】
{new_text}

【新技术点】
{key_points}

请判断新内容是否应当替换旧内容：
- 若新技术明显更优（稳定性更高、性能更好，或修复了旧内容的缺陷）→ 决策 REPLACE
- 若两者等价、新内容更激进未经验证、或旧内容更可靠 → 决策 KEEP_OLD

严格只输出一个 JSON 对象，不要 markdown 代码块、不要多余文字：
{{"decision": "REPLACE 或 KEEP_OLD",
  "reason": "100 字以内的中文理由",
  "stability_score": 1到5的整数（新内容稳定性）,
  "performance_score": 1到5的整数（新内容性能）}}
"""


@dataclass
class UpdateDecision:
    decision: str
    reason: str = ""
    stability_score: int = 0
    performance_score: int = 0
    topic: str = ""
    source: str = ""
    old_version: str = ""
    new_version: str = ""
    old_sources: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    raw: str = ""
    applied: bool = False
    errors: list[str] = field(default_factory=list)
    elapsed_sec: float = 0.0
    folder_id: str = ""
    folder_path: str = ""

    def to_record(self) -> dict:
        """PRD 5.2 更迭日志字段。"""
        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "topic": self.topic,
            "source": self.source,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "decision": self.decision,
            "reason": self.reason,
            "stability_score": self.stability_score,
            "performance_score": self.performance_score,
            "old_sources": self.old_sources,
            "key_points": self.key_points,
            "folder_id": self.folder_id,
            "folder_path": self.folder_path,
        }


def _invoke(model, prompt: str) -> str:
    from langchain_core.messages import HumanMessage

    resp = model.invoke([HumanMessage(content=prompt)])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    return content.strip()


def _extract_json_block(text: str) -> str:
    """从模型输出中取出第一个 JSON 对象/数组（容忍 ```json 包裹与前后废话）。"""
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return text.strip()
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def extract_key_points(
    settings: Settings | None = None,
    text: str = "",
    max_points: int = 8,
    model=None,
) -> list[str]:
    """抽取关键技术点；失败返回空列表（不阻断更迭流程）。"""
    s = settings or get_settings()
    if not text.strip():
        return []
    m = model or get_chat_model(s)[0]
    prompt = EXTRACT_PROMPT.format(max_points=max_points, text=text[:6000])
    try:
        raw = _invoke(m, prompt)
        data = json.loads(_extract_json_block(raw))
        if isinstance(data, dict):
            data = data.get("points") or data.get("key_points") or []
        return [str(x).strip() for x in data if str(x).strip()][:max_points]
    except Exception as exc:  # noqa: BLE001 - 抽取失败不应中断入库
        error_logger.warning("关键技术点抽取失败: %s: %s", type(exc).__name__, exc,
                             extra={"module_name": "update_agent"})
        return []

def _parse_decision(raw: str) -> tuple[str, str, int, int]:
    """解析模型输出的决策 JSON，非法值一律按 KEEP_OLD 保守处理。"""
    data = json.loads(_extract_json_block(raw))
    if not isinstance(data, dict):
        raise ValueError("决策不是 JSON 对象")

    decision = str(data.get("decision", "")).strip().upper()
    if decision not in (DECISION_REPLACE, DECISION_KEEP):
        # 容忍 "替换" / "keep" 等写法
        if "REPLACE" in decision or "替换" in decision:
            decision = DECISION_REPLACE
        else:
            decision = DECISION_KEEP

    reason = str(data.get("reason", "")).strip()
    if len(reason) > 200:
        reason = reason[:200]

    def _score(key: str) -> int:
        try:
            v = int(round(float(data.get(key, 0))))
        except (TypeError, ValueError):
            return 0
        return max(0, min(5, v))

    return decision, reason, _score("stability_score"), _score("performance_score")


def evaluate_change(
    settings: Settings | None = None,
    new_text: str = "",
    old_context: str = "",
    old_version: str = "",
    new_version: str = "",
    key_points: list[str] | None = None,
    model=None,
) -> tuple[str, str, int, int, str]:
    """对比评估，返回 (decision, reason, stability, performance, raw)。"""
    s = settings or get_settings()
    m = model or get_chat_model(s)[0]
    prompt = COMPARE_PROMPT.format(
        old_version=old_version or "?",
        new_version=new_version or "?",
        old_context=old_context[:6000] or "（无）",
        new_text=new_text[:6000],
        key_points="\n".join(f"- {p}" for p in (key_points or [])) or "（未抽取到）",
    )
    raw = _invoke(m, prompt)
    decision, reason, stab, perf = _parse_decision(raw)
    return decision, reason, stab, perf, raw


def _append_record(s: Settings, record: dict) -> None:
    path = Path(s.update_log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_records(settings: Settings | None = None, limit: int = 100) -> list[dict]:
    """读取更迭记录（新的在后）。前端知识库浏览页使用。"""
    s = settings or get_settings()
    path = Path(s.update_log_file)
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[-limit:]


def _norm_topic(topic: str) -> str:
    """主题归一化：忽略大小写、空白与常见分隔符，避免「Python 异步」与「python_异步」判为不同主题。"""
    return re.sub(r"[\s_\-—·]+", "", (topic or "").strip().lower())


def _old_context_and_sources(
    s: Settings,
    text: str,
    source_name: str,
    topic: str = "",
    k: int = 6,
    folder_id: str = "",
) -> tuple[str, list[dict]]:
    """检索"同文件夹 + 同主题"的旧内容。

    只有 topic 相同、且同属一个知识库文件夹的来源才算旧版本，才允许被 REPLACE 删除；
    检索到的其他文档只作为上下文参考，绝不进入删除列表——
    否则一次更迭会把别的文件夹里的无关资料一起删掉。
    """
    probe = text[:1500] if text.strip() else source_name
    hits = vectorstore.search(s, probe, k=k, where=vectorstore.folder_where([folder_id]))
    hits = [h for h in hits if h.metadata.get("source") != source_name]
    hits = [h for h in hits if h.metadata.get("folder_id", "") == folder_id]
    if topic:
        want = _norm_topic(topic)
        hits = [h for h in hits if _norm_topic(h.metadata.get("topic") or "") == want]
    blocks: list[str] = []
    seen: dict[tuple[str, str], dict] = {}
    for i, h in enumerate(hits, start=1):
        meta = h.metadata
        blocks.append(
            f"[{i}] {meta.get('source', '?')} v{meta.get('version', '?')}"
            f"（相关度 {h.score:.2f}）\n{h.content.strip()}"
        )
        key = (meta.get("source", ""), meta.get("version", ""))
        seen.setdefault(
            key,
            {"source": meta.get("source", ""), "version": meta.get("version", ""), "detail": {}},
        )
    return "\n\n".join(blocks), list(seen.values())


def _highest_version(sources: list[dict]) -> str:
    best = "v1.0"
    best_key = parse_version(best)
    for item in sources:
        v = item.get("version") or ""
        if not v:
            continue
        try:
            key = parse_version(v)
        except ValueError:
            continue
        if key > best_key:
            best, best_key = v, key
    return best

def evaluate_file(
    settings: Settings | None = None,
    file_path: str | Path = "",
    version: str = "v1.0",
    topic: str | None = None,
    apply: bool = True,
    model=None,
    folder_id: str = "",
    folder_path: str = "",
) -> UpdateDecision:
    """技术更迭评估主流程（PRD 3.2.3）。

    apply=False 时只做评估不落库（前端"仅评估"按钮用）。
    对比基线限定在同一知识库文件夹内（folder_id），避免跨库误删。
    """
    s = settings or get_settings()
    path = Path(file_path)
    t0 = time.time()
    result = UpdateDecision(
        decision=DECISION_KEEP, source=path.name, folder_id=folder_id, folder_path=folder_path
    )

    if path.suffix.lower() not in SUPPORTED_EXTS:
        result.errors.append(f"不支持的文件格式: {path.suffix}")
        result.reason = "文件格式不受支持"
        result.elapsed_sec = time.time() - t0
        return result

    try:
        full_text, _pages = parse_file(path)
    except Exception as exc:  # noqa: BLE001 - 解析失败需返回而非抛出
        result.errors.append(f"解析失败: {type(exc).__name__}: {exc}")
        result.reason = "文档解析失败，未做更迭评估"
        error_logger.error("更迭评估解析失败 %s: %s", path.name, exc,
                           extra={"module_name": "update_agent"})
        result.elapsed_sec = time.time() - t0
        return result

    text = clean_text(full_text)
    result.topic = topic or extract_topic(path.name, text)
    result.key_points = extract_key_points(s, text, model=model)

    old_context, old_sources = _old_context_and_sources(
        s, text, path.name, topic=result.topic, folder_id=folder_id
    )
    result.old_sources = [f"{x['source']} {x['version']}" for x in old_sources]

    # 无对比基线：直接入库，不做 REPLACE/KEEP_OLD 判断
    if not old_sources:
        result.decision = DECISION_INGEST
        result.reason = "知识库中无同主题旧内容，直接入库"
        if apply:
            ing = ingest_file(
                s, path, version=version, topic=result.topic,
                folder_id=folder_id, folder_path=folder_path,
            )
            result.new_version = version
            result.errors.extend(ing.errors)
            result.applied = ing.ok
        _record(s, result)
        result.elapsed_sec = time.time() - t0
        return result

    result.old_version = _highest_version(old_sources)
    result.new_version = bump_version(result.old_version)

    try:
        decision, reason, stab, perf, raw = evaluate_change(
            s,
            new_text=text,
            old_context=old_context,
            old_version=result.old_version,
            new_version=result.new_version,
            key_points=result.key_points,
            model=model,
        )
        result.decision, result.reason = decision, reason
        result.stability_score, result.performance_score = stab, perf
        result.raw = raw
    except Exception as exc:  # noqa: BLE001 - 评估失败保守拦截
        result.decision = DECISION_KEEP
        result.reason = f"评估调用失败（{type(exc).__name__}），保守拦截"
        result.errors.append(str(exc))
        error_logger.error("更迭评估失败 %s: %s", path.name, exc,
                           extra={"module_name": "update_agent"})
        _record(s, result)
        result.elapsed_sec = time.time() - t0
        return result

    if apply and result.decision == DECISION_REPLACE:
        try:
            removed = 0
            for item in old_sources:
                # 只删同主题旧版本（_old_context_and_sources 已按 topic 过滤）
                removed += vectorstore.delete_by_source(
                    s, item["source"], item["version"] or None, folder_id=folder_id
                )
            ing = ingest_file(
                s, path, version=result.new_version, topic=result.topic,
                folder_id=folder_id, folder_path=folder_path,
            )
            result.errors.extend(ing.errors)
            result.applied = ing.ok
            update_logger.info(
                "更迭执行 REPLACE: %s %s -> %s，删除旧块 %d，写入新块 %d",
                result.topic, result.old_version, result.new_version, removed, ing.chunks,
                extra={"module_name": "update_agent"},
            )
        except Exception as exc:  # noqa: BLE001 - 落库失败需记录
            result.applied = False
            result.errors.append(f"更迭执行失败: {type(exc).__name__}: {exc}")
            error_logger.error("更迭执行失败: %s", exc, extra={"module_name": "update_agent"})
    elif result.decision == DECISION_KEEP:
        update_logger.info(
            "更迭拦截 KEEP_OLD: %s %s -> %s，原因: %s",
            result.topic, result.old_version, result.new_version, result.reason,
            extra={"module_name": "update_agent"},
        )

    _record(s, result)
    result.elapsed_sec = time.time() - t0
    return result


def _record(s: Settings, result: UpdateDecision) -> None:
    """写结构化更迭记录 + update.log。"""
    try:
        _append_record(s, result.to_record())
    except Exception as exc:  # noqa: BLE001 - 记录失败不影响主流程
        error_logger.error("更迭记录写入失败: %s", exc, extra={"module_name": "update_agent"})
    update_logger.info(
        "更迭评估: topic=%s decision=%s old=%s new=%s stability=%s performance=%s applied=%s",
        result.topic or "-", result.decision, result.old_version or "-", result.new_version or "-",
        result.stability_score, result.performance_score, result.applied,
        extra={"module_name": "update_agent"},
    )