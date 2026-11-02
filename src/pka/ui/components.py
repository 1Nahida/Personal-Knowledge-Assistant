"""PKA 页面组件：把重复的 HTML 片段收在一处，保证四个页面视觉一致。"""

from __future__ import annotations

import html as _html
from pathlib import Path

import streamlit as st

from .theme import TOKENS

ASSETS = Path(__file__).resolve().parents[3] / "docs" / "assets"


def _esc(text: object) -> str:
    return _html.escape(str(text), quote=False)


def hero(title: str, sub: str = "", chips: list[str] | None = None) -> None:
    """页面头：左侧标题+说明，右侧状态 chip。"""
    chip_html = "".join(chips or [])
    st.html(
        f'<div class="pka-hero"><div>'
        f'<div class="pka-hero-title">{_esc(title)}</div>'
        f'{f"<div class=pka-hero-sub>{sub}</div>" if sub else ""}'
        f'</div><div class="pka-chips">{chip_html}</div></div>'
    )


def chip(label: str, value: str = "", dot: str = "") -> str:
    """状态 chip 的 HTML 片段；dot 取 ok / warn / err / idle。"""
    dot_html = f'<span class="pka-dot pka-dot-{dot}"></span>' if dot else ""
    val = f"<b>{_esc(value)}</b>" if value else ""
    return f'<span class="pka-chip">{dot_html}{_esc(label)}{val}</span>'


def side_label(text: str) -> None:
    """侧栏分组小标题（全大写小字号，避免和正文字重混淆）。"""
    st.html(f'<div class="pka-side-label">{_esc(text)}</div>')


def section(title: str) -> None:
    st.html(
        f'<div class="pka-section"><span class="pka-section-title">{_esc(title)}</span>'
        f'<span class="pka-section-line"></span></div>'
    )


def empty_state(title: str, sub: str = "", glyph: str = "◎") -> None:
    st.html(
        f'<div class="pka-empty"><div class="pka-empty-mark">'
        f'<span style="font-size:1.5rem;color:{TOKENS["accent"]}">{_esc(glyph)}</span></div>'
        f"<h2>{_esc(title)}</h2>"
        f"{f'<p>{sub}</p>' if sub else ''}</div>"
    )


def avatar_data_uri() -> str:
    """品牌头像（docs/assets/avatar.png）转成 data URI，避免额外静态路由。"""
    avatar = ASSETS / "avatar.png"
    if not avatar.exists():
        return ""
    import base64

    return "data:image/png;base64," + base64.b64encode(avatar.read_bytes()).decode()


def brand(name: str = "PKA", sub: str = "个人知识问答助手") -> None:
    uri = avatar_data_uri()
    mark = (
        f'<img class="pka-brand-avatar" src="{uri}" alt="" />'
        if uri
        else f'<div class="pka-brand-mark">PK</div>'
    )
    st.html(
        f'<div class="pka-brand">{mark}'
        f'<div><div class="pka-brand-name">{_esc(name)}</div>'
        f'<div class="pka-brand-sub">{_esc(sub)}</div></div></div>'
    )


def hero_text(title: str, sub: str = "") -> str:
    """页面头左半部分（标题+说明）的 HTML，用于横向容器里和右侧操作并排。"""
    return (
        f'<div class="pka-hero-text"><div class="pka-hero-title">{_esc(title)}</div>'
        f'{f"<div class=pka-hero-sub>{sub}</div>" if sub else ""}</div>'
    )


def chips_html(chips: list[str] | None) -> str:
    """状态 chip 行的 HTML，配合 hero_text() 使用。"""
    return f'<div class="pka-chips">{"".join(chips or [])}</div>'


TONES: dict[str, str] = {
    "ok": TOKENS["ok"],
    "warn": TOKENS["warn"],
    "err": TOKENS["err"],
    "accent": TOKENS["accent"],
}


DECISION_META: dict[str, tuple[str, str]] = {
    "REPLACE": ("已替换", "ok"),
    "KEEP_OLD": ("已拦截", "warn"),
    "INGEST": ("新增入库", "accent"),
}


def _bar(value: object, tone: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    pct = max(0.0, min(100.0, v / 5.0 * 100.0))
    return (
        f'<div class="pka-bar"><div class="pka-bar-fill" '
        f'style="width:{pct:.0f}%;background:{TONES[tone]}"></div></div>'
    )


def decision_card(record: dict) -> str:
    """技术更迭决策卡（PRD 3.2.3 / 5.2）：决策标签 + 版本迁移 + 理由 + 双维评分。"""
    decision = str(record.get("decision") or "").upper()
    label, tone = DECISION_META.get(decision, (decision or "未知", "accent"))
    color = TONES[tone]
    old_v = record.get("old_version") or "-"
    new_v = record.get("new_version") or "-"
    topic = record.get("topic") or record.get("source") or ""
    source = record.get("source") or ""
    reason = record.get("reason") or ""
    when = record.get("timestamp") or ""
    stab = record.get("stability_score")
    perf = record.get("performance_score")
    return (
        f'<div class="pka-dec" style="border-left-color:{color}">'
        f'<div class="pka-dec-head">'
        f'<span class="pka-tag" style="color:{color};background:{color}1F;'
        f'border:1px solid {color}55">{_esc(label)}</span>'
        f'<span class="pka-dec-title">{_esc(topic)}</span>'
        f'<span class="pka-dec-ver">v{_esc(old_v).lstrip("v")} → v{_esc(new_v).lstrip("v")}</span>'
        f'<span class="pka-dec-time">{_esc(when)}</span>'
        f"</div>"
        f'<div class="pka-dec-reason">{_esc(reason)}</div>'
        f'<div class="pka-scores">'
        f'<div class="pka-score"><div class="pka-score-label"><span>稳定性</span>'
        f"<span>{_esc(stab)} / 5</span></div>{_bar(stab, 'ok')}</div>"
        f'<div class="pka-score"><div class="pka-score-label"><span>性能</span>'
        f"<span>{_esc(perf)} / 5</span></div>{_bar(perf, 'accent')}</div>"
        f"</div>"
        f'<div class="pka-dec-src">{_esc(source)}</div>'
        f"</div>"
    )


def citations_html(citations: list) -> str:
    """引用来源块：编号 + 文件名(页码) + 版本 + 相关度 + 摘录。"""
    rows: list[str] = []
    for c in citations:
        page = c.get("page") or 0
        loc = f"第{page}页" if page else "段落"
        score = c.get("score")
        rows.append(
            f'<div class="pka-cite">'
            f'<div class="pka-cite-head">'
            f'<span class="pka-cite-idx">[{c.get("index")}]</span>'
            f"<span>{_esc(c.get('source'))}</span>"
            f'<span class="pka-cite-meta">{_esc(loc)} · v{_esc(c.get("version"))}'
            f'{" · 相关度 " + str(score) if score is not None else ""}</span>'
            f"</div>"
            f'<div class="pka-cite-body">{_esc(c.get("snippet", ""))}</div>'
            f"</div>"
        )
    return "".join(rows)
