"""PKA · Streamlit 前端入口。

启动：streamlit run app.py

页面（侧栏切换，一次只渲染一页）：
- 智能问答（PRD 3.2.2）：检索 + 生成 + 引用来源 + 对话历史落库，检索范围可跟随当前文件夹
- 知识库（PRD 3.2.1 + P1，用户补充「多知识库文件夹」）：文件夹树 + 上传入库 + 文件清单 + 更迭记录
- 日志（PRD 3.2.5）：operation / update / error 日志查看
侧栏：检索范围、Top-K、会话管理、模型源切换（PRD 3.2.4，无需重启）。
"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from pka.agents.history import get_history_store  # noqa: E402
from pka.agents.ingestion import SUPPORTED_EXTS, ingest_file  # noqa: E402
from pka.agents.library import get_library_store  # noqa: E402
from pka.agents.qa_agent import QAAgent  # noqa: E402
from pka.agents.update_agent import (  # noqa: E402
    DECISION_INGEST,
    DECISION_KEEP,
    DECISION_REPLACE,
    evaluate_file,
    read_records,
)
from pka.config import get_settings  # noqa: E402
from pka.core import vectorstore  # noqa: E402
from pka.core.model_factory import probe_ollama  # noqa: E402
from pka.logger import list_log_files, tail_log  # noqa: E402
from pka.ui import components as ui  # noqa: E402
from pka.ui.theme import inject as inject_theme  # noqa: E402

PROVIDER_LABELS = {
    "ollama": "本地 Ollama",
    "dashscope": "阿里云 DashScope",
    "deepseek": "DeepSeek",
}

PAGES: list[tuple[str, str, str]] = [
    ("qa", "智能问答", ":material/forum:"),
    ("library", "知识库", ":material/folder_open:"),
    ("logs", "日志", ":material/receipt_long:"),
]

# 虚拟节点：未分类（folder_id 为空串的资料）
UNFILED = "__unfiled__"

EXAMPLES: list[tuple[str, str]] = [
    ("这批资料的核心结论是什么？", "先看整体，适合刚上传完"),
    ("帮我梳理当前文件夹的知识脉络", "只查选中的知识库"),
    ("哪些内容最近被新技术替换了？", "回答依赖更迭记录"),
    ("Python 装饰器怎么实现？", "要一个能跑的最简例子"),
]

ASSISTANT_AVATAR = ROOT / "docs" / "assets" / "avatar.png"

st.set_page_config(page_title="PKA · 个人知识问答助手", page_icon="📚", layout="wide")


def _settings():
    """配置单例（get_settings 本身即进程级单例）；模型源切换通过 session_state 覆盖。"""
    return get_settings()


def _active_settings():
    s = _settings()
    provider = st.session_state.get("provider") or s.model_provider
    return s if provider == s.model_provider else s.with_provider(provider)


def _library():
    return get_library_store(_settings())


def _init_state() -> None:
    """会话按需创建：只有真正提问过才落库，避免每次刷新堆出空的「新会话」。"""
    s = _settings()
    st.session_state.setdefault("page", "qa")
    st.session_state.setdefault("provider", s.model_provider)
    st.session_state.setdefault("top_k", s.top_k)
    st.session_state.setdefault("session_id", None)  # None = 尚未提问的新会话
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending_question", None)
    st.session_state.setdefault("folder_id", None)  # None = 全部文件
    st.session_state.setdefault("open_folders", [])  # 树上已展开的文件夹（IDE 风格的折叠状态）
    st.session_state.setdefault("sel_doc", None)  # 右侧当前查看的文档（None = 文件夹视图）
    st.session_state.setdefault("scope_all", False)
    store = get_history_store(s)
    if not st.session_state.get("_empties_purged"):
        store.purge_empty_sessions()
        st.session_state._empties_purged = True


def _switch_session(sid: str | None) -> None:
    """切换到历史会话；sid 为 None 时清空为「新会话」。"""
    st.session_state["_pills_sync"] = sid
    st.session_state.session_id = sid
    if not sid:
        st.session_state.messages = []
        return
    store = get_history_store(_settings())
    st.session_state.messages = [
        {"role": m["role"], "content": m["content"], "citations": m["citations"]}
        for m in store.get_messages(sid)
    ]


def _toggle_folder(fid: str | None) -> None:
    """点文件夹 = 选中它 + 展开/收起子节点（像 IDE 的项目树）。"""
    st.session_state.folder_id = fid
    st.session_state.sel_doc = None
    key = fid or "__root__"
    opened = set(st.session_state.get("open_folders") or [])
    opened.symmetric_difference_update({key})
    st.session_state.open_folders = sorted(opened)


def _select_doc(doc: dict) -> None:
    """点文件节点 = 右侧切换到文件详情。"""
    st.session_state.sel_doc = {
        "source": doc["source"],
        "version": doc["version"],
        "folder_id": doc.get("folder_id") or "",
        "folder_path": doc.get("folder_path") or "",
        "topic": doc.get("topic") or "",
        "chunk_count": doc.get("chunk_count") or 0,
        "updated_at": doc.get("updated_at") or "",
    }


def collection_name_short(s) -> str:
    """集合名去掉 pka_ 前缀，侧栏一行放得下。"""
    return vectorstore.collection_name(s).removeprefix("pka_")


def _scope_label(lib) -> str:
    if st.session_state.get("scope_all"):
        return "全库"
    fid = st.session_state.get("folder_id")
    if fid is None:
        return "全库"
    if fid == UNFILED:
        return "未分类"
    return lib.path(fid)


def _scope_folder_ids(lib) -> list[str] | None:
    """当前检索范围对应的 folder_id 列表；None 表示不限（全库）。"""
    if st.session_state.get("scope_all"):
        return None
    fid = st.session_state.get("folder_id")
    if fid is None:
        return None
    if fid == UNFILED:
        return [""]
    return lib.descendant_ids(fid)


def _provider_status(picked: str, s) -> None:
    """模型源状态 chip：就绪/未配置 + Ollama 在线状态。"""
    chips: list[str] = []
    ok, detail = s.provider_ready(picked)
    chips.append(ui.chip(PROVIDER_LABELS[picked], "", dot="ok" if ok else "warn"))
    if picked == "ollama":
        online, _msg = probe_ollama(s)
        chips.append(ui.chip("在线" if online else "离线", "", dot="ok" if online else "err"))
    else:
        chips.append(ui.chip("Key", "已配置" if ok else "缺失", dot="ok" if ok else "warn"))
    st.html(
        f'<div class="pka-chips" style="justify-content:flex-start;gap:6px;">{"".join(chips)}</div>'
        f'<div style="color:#64748B;font-size:.72rem;margin:6px 0 2px;">{detail}</div>'
    )


def _sidebar() -> None:
    s = _settings()
    lib = _library()
    store = get_history_store(s)
    cur_page = st.session_state.get("page", "qa")
    with st.sidebar:
        ui.brand()
        with st.container(key="pka_nav"):
            for key, label, icon in PAGES:
                if st.button(
                    label,
                    key=f"nav_{key}",
                    icon=icon,
                    width="stretch",
                    type="primary" if key == cur_page else "secondary",
                ):
                    st.session_state.page = key
                    st.rerun()

        ui.side_label("检索")
        st.slider("Top-K 召回条数", min_value=1, max_value=10, key="top_k")
        mode = st.pills(
            "检索范围",
            ["跟随文件夹", "全库"],
            default="全库" if st.session_state.get("scope_all") else "跟随文件夹",
            label_visibility="collapsed",
            key="scope_pills",
        )
        st.session_state.scope_all = mode == "全库"
        st.caption(f"当前：{_scope_label(lib)}")

        ui.side_label("会话")
        cur = st.session_state.get("session_id")
        if st.button("新建会话", icon=":material/add:", width="stretch"):
            _switch_session(None)
            st.rerun()
        sessions = store.list_sessions(20)
        if sessions:
            ids = [x["id"] for x in sessions]
            labels = {x["id"]: f"{x['title']}（{x['msg_count']}）" for x in sessions}
            if "_pills_sync" in st.session_state:
                st.session_state.sess_pills = st.session_state.pop("_pills_sync")
            picked_sid = st.pills(
                "历史会话",
                ids,
                default=cur if cur in ids else None,
                format_func=lambda i: labels.get(i, i),
                label_visibility="collapsed",
                key="sess_pills",
            )
            if picked_sid != cur:
                _switch_session(picked_sid)
                st.rerun()
        else:
            st.caption("还没有历史会话，提第一个问题就会自动保存。")

        active = _active_settings()
        scoped = vectorstore.count(active, _scope_folder_ids(lib))
        st.caption(f"当前范围 {scoped} 块 · 全库 {vectorstore.count(active)} 块")

        # 模型源放在侧栏最下方：低频操作，避免每次都占用视线
        ui.side_label("模型源")
        providers = list(PROVIDER_LABELS)
        idx = providers.index(st.session_state.provider) if st.session_state.provider in providers else 0
        picked = st.radio(
            "选择模型源（切换后立即生效，无需重启）",
            providers,
            index=idx,
            format_func=lambda p: PROVIDER_LABELS[p],
            label_visibility="collapsed",
        )
        if picked != st.session_state.provider:
            st.session_state.provider = picked
            st.rerun()
        _provider_status(picked, s)


def _render_citations(citations: list) -> None:
    if not citations:
        return
    with st.expander(f"引用来源 · {len(citations)} 条", icon=":material/link:"):
        st.html(ui.citations_html(citations))


def _example_cards() -> None:
    """空态示例问题：2×2 卡片，点击即提问。第二行小字是说明，由 CSS ::after 注入。"""
    rules = "".join(
        f'.st-key-ex_{i} button::after {{ content: "{hint}"; }}' for i, (_q, hint) in enumerate(EXAMPLES)
    )
    st.html(f"<style>{rules}</style>")
    for row_start in (0, 2):
        cols = st.columns(2, gap="small")
        for offset, col in enumerate(cols):
            i = row_start + offset
            if i >= len(EXAMPLES):
                break
            q, hint = EXAMPLES[i]
            with col:
                if st.button(q, key=f"ex_{i}", width="stretch", help=hint):
                    st.session_state.pending_question = q
                    st.rerun()


def _question_input() -> str:
    """底部提问条：回车与按钮都能提交（chat_input 不能在 tabs 内工作，故用表单）。"""
    with st.form("qa_form", clear_on_submit=True, border=False):
        col_q, col_btn = st.columns([6.2, 1], vertical_alignment="bottom")
        with col_q:
            raw = st.text_input(
                "提问",
                placeholder="就你的资料提个问题，回车发送…",
                label_visibility="collapsed",
            )
        with col_btn:
            submitted = st.form_submit_button(
                "发送", type="primary", icon=":material/send:", width="stretch"
            )
    question = (raw or "").strip()
    if submitted and question:
        return question
    pending = st.session_state.get("pending_question")
    if pending:
        st.session_state.pending_question = None
        return pending
    return ""


@st.dialog("删除当前会话", icon=":material/delete_forever:")
def _confirm_delete_session(sid: str) -> None:
    """删除前二次确认：会话记录不可恢复，知识库内容不受影响。"""
    store = get_history_store(_settings())
    n = len(store.get_messages(sid))
    st.write(f"将删除这个会话的 **{n}** 条对话记录。")
    st.caption("知识库内容不受影响；对话记录删除后无法恢复。")
    col_cancel, col_ok = st.columns(2)
    if col_cancel.button("取消", width="stretch"):
        st.rerun()
    if col_ok.button("确认删除", type="primary", width="stretch", icon=":material/delete:"):
        store.delete_session(sid)
        _switch_session(None)
        st.rerun()


def page_qa() -> None:
    s = _active_settings()
    lib = _library()
    cur = st.session_state.get("session_id")
    folder_ids = _scope_folder_ids(lib)
    with st.container(key="qa_page"):
        with st.container(horizontal=True, vertical_alignment="center", key="qa_head"):
            st.html(
                ui.hero_text(
                    "智能问答",
                    "先在知识库中检索 Top-K 片段，再由当前模型基于片段作答，并标注引用出处。",
                )
            )
            st.html(
                ui.chips_html(
                    [
                        ui.chip("模型", PROVIDER_LABELS.get(st.session_state.provider, ""), dot="ok"),
                        ui.chip("范围", _scope_label(lib)),
                        ui.chip("向量块", str(vectorstore.count(s, folder_ids))),
                        ui.chip("会话", "新会话" if not cur else "已保存", dot="idle"),
                    ]
                )
            )
            if cur and st.button(
                "",
                key="del_session",
                icon=":material/delete:",
                help="删除这个会话（需确认）",
            ):
                _confirm_delete_session(cur)

        if not st.session_state.messages:
            ui.empty_state(
                "今天想从知识库里挖点什么？",
                f"当前检索范围：{_scope_label(lib)}。问题会先检索相关片段，再由模型作答并标注来源。",
                glyph="✦",
            )
            _example_cards()

        for msg in st.session_state.messages:
            avatar = (
                str(ASSISTANT_AVATAR)
                if msg["role"] == "assistant" and ASSISTANT_AVATAR.exists()
                else None
            )
            with st.chat_message(msg["role"], avatar=avatar):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    _render_citations(msg.get("citations") or [])

        question = _question_input()
    if not question:
        return

    agent = QAAgent(s)
    k = int(st.session_state.top_k)

    store = get_history_store(_settings())
    sid = st.session_state.get("session_id")
    if not sid:
        sid = store.create_session(question[:20], st.session_state.provider)
        st.session_state.session_id = sid
        st.session_state["_pills_sync"] = sid
    elif not store.get_messages(sid):
        store.rename_session(sid, question[:20])

    st.session_state.messages.append({"role": "user", "content": question, "citations": []})
    with st.spinner("检索并生成中…"):
        result = agent.ask(question, k=k, folder_ids=folder_ids)
    cites = [c.to_dict() for c in result.citations]
    st.session_state.messages.append(
        {"role": "assistant", "content": result.answer, "citations": cites}
    )
    store.add_turn(sid, question, result)
    st.rerun()

@st.dialog("新建知识库文件夹", icon=":material/create_new_folder:")
def _dialog_new_folder(parent_id: str | None) -> None:
    lib = _library()
    parent = lib.get(parent_id)
    st.caption(f"上级文件夹：{lib.path(parent.id) if parent else '根目录'}")
    name = st.text_input("名称", placeholder="如 Python / 深度学习 / 七日系列")
    category = st.text_input("分类（可选）", placeholder="如 课程笔记 / 小说设定")
    desc = st.text_area("简介（可选）", placeholder="一句话说明这个知识库放什么", height=90)
    if st.button("创建", type="primary", width="stretch", icon=":material/check:"):
        try:
            f = lib.create(name, parent_id=parent_id, description=desc, category=category)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state.folder_id = f.id
        st.session_state.sel_doc = None
        # 建完立刻展开父节点，否则新文件夹在收起的父节点里看不见
        opened = set(st.session_state.get("open_folders") or [])
        opened.update({parent_id or "__root__", f.id})
        st.session_state.open_folders = sorted(opened)
        st.rerun()


@st.dialog("编辑知识库信息", icon=":material/edit:")
def _dialog_edit_folder(fid: str) -> None:
    lib = _library()
    f = lib.get(fid)
    if not f:
        st.rerun()
    st.caption(f"路径：{lib.path(fid)}")
    name = st.text_input("名称", value=f.name)
    category = st.text_input("分类", value=f.category, placeholder="如 课程笔记 / 小说设定")
    desc = st.text_area("简介", value=f.description, height=120)
    if st.button("保存", type="primary", width="stretch", icon=":material/save:"):
        try:
            lib.update(fid, name=name, description=desc, category=category)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.rerun()


@st.dialog("删除知识库文件夹", icon=":material/folder_delete:")
def _dialog_delete_folder(fid: str) -> None:
    s = _active_settings()
    lib = _library()
    f = lib.get(fid)
    if not f:
        st.rerun()
    kids = lib.children(fid)
    blocks = vectorstore.count(s, lib.descendant_ids(fid))
    st.write(f"「{lib.path(fid)}」下有 **{len(kids)}** 个子文件夹、**{blocks}** 个文本块。")
    if kids or blocks:
        st.warning("为避免误删，只有空文件夹可以直接删除。请先删除其中的文档与子文件夹。")
        if st.button("知道了", width="stretch"):
            st.rerun()
        return
    st.caption("删除后不可恢复；此处只删文件夹本身，不涉及向量库内容（已确认为空）。")
    col_cancel, col_ok = st.columns(2)
    if col_cancel.button("取消", width="stretch"):
        st.rerun()
    if col_ok.button("确认删除", type="primary", width="stretch", icon=":material/delete:"):
        lib.delete(fid)
        st.session_state.folder_id = None
        st.rerun()


def _render_ingest(s, lib, folder_id: str, folder_path: str) -> None:
    """入库区：当前文件夹即上传目标，勾选更迭评估时先做 REPLACE/KEEP_OLD 判断。"""
    ui.section("上传入库")
    target = folder_path or "未分类"
    with st.container(border=True):
        st.caption(f"上传目标：{target}（支持 {' / '.join(sorted(e.lstrip('.') for e in SUPPORTED_EXTS))}）")
        col_ver, col_topic = st.columns([1, 2.4])
        with col_ver:
            version = st.text_input("版本号", value="v1.0", help="PRD 元数据字段；配合技术更迭评估使用")
        with col_topic:
            topic = st.text_input("主题（可选，留空自动提取）", value="")
        eval_enabled = st.checkbox(
            "启用技术更迭评估（PRD 3.2.3）",
            value=False,
            help="开启后先抽取新技术点，并与**同一文件夹内**同主题的旧内容对比；决策 REPLACE 才替换旧版本并把版本号 +1，"
                 "决策 KEEP_OLD 只记录拦截原因、知识库保持不变。",
        )
        files = st.file_uploader(
            "拖入或选择文件（可多选）",
            type=[e.lstrip(".") for e in sorted(SUPPORTED_EXTS)],
            accept_multiple_files=True,
            key=f"up_{folder_id or 'root'}",
        )
        go = st.button(
            "开始入库", type="primary", icon=":material/cloud_upload:",
            disabled=not files, key=f"go_{folder_id or 'root'}",
        )

    if not (go and files):
        return

    upload_dir = Path(s.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    cards: list[dict] = []
    progress = st.progress(0.0, text="入库中…")
    for i, f in enumerate(files):
        dest = upload_dir / f.name
        dest.write_bytes(f.getbuffer())
        if eval_enabled:
            dec = evaluate_file(
                s, dest, version=version, topic=topic or None,
                folder_id=folder_id, folder_path=folder_path,
            )
            label = {
                DECISION_REPLACE: "🔁 已替换",
                DECISION_KEEP: "🛡 已拦截",
                DECISION_INGEST: "📥 新增",
            }.get(dec.decision, dec.decision)
            cards.append(
                {
                    "decision": dec.decision,
                    "topic": dec.topic,
                    "source": dec.source,
                    "old_version": dec.old_version,
                    "new_version": dec.new_version,
                    "reason": dec.reason,
                    "stability_score": dec.stability_score,
                    "performance_score": dec.performance_score,
                    "folder_path": folder_path,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            rows.append(
                {
                    "文件": dec.source,
                    "状态": label if not dec.errors else "❌ 出错",
                    "版本": f"{dec.old_version or '-'} → {dec.new_version or '-'}",
                    "稳定/性能": f"{dec.stability_score}/{dec.performance_score}",
                    "决策理由": dec.reason,
                    "耗时(s)": round(dec.elapsed_sec, 2),
                    "备注": "; ".join(dec.errors) or "-",
                }
            )
        else:
            res = ingest_file(
                s, dest, version=version, topic=topic or None,
                folder_id=folder_id, folder_path=folder_path,
            )
            rows.append(
                {
                    "文件": res.source,
                    "状态": "✅ 成功" if res.ok else "❌ 失败",
                    "块数": res.chunks,
                    "字符": res.chars,
                    "主题": res.topic,
                    "耗时(s)": round(res.elapsed_sec, 2),
                    "备注": "; ".join(res.errors + res.warnings) or "-",
                }
            )
        progress.progress((i + 1) / len(files), text=f"已处理 {i + 1}/{len(files)}")
    progress.empty()
    vectorstore.reset_client()
    if cards:
        ui.section("更迭决策")
        for rec in cards:
            st.html(ui.decision_card(rec))
        with st.expander("入库明细表", icon=":material/table:"):
            st.dataframe(rows, width="stretch")
    else:
        ui.section("入库结果")
        st.dataframe(rows, width="stretch")
    if any(r["状态"].startswith(("✅", "🔁", "📥")) for r in rows):
        st.success("入库完成，可到「智能问答」提问。", icon=":material/check_circle:")

def _render_update_records(s, folder_id: str | None = None, limit: int = 12) -> None:
    """技术更迭记录（PRD 5.2）。folder_id 给定时只看该文件夹的评估结果。"""
    records = read_records(s)
    if folder_id is not None:
        records = [r for r in records if (r.get("folder_id") or "") == folder_id]
    ui.section(f"技术更迭记录 · {len(records)}")
    if not records:
        st.caption("暂无更迭记录。勾选「启用技术更迭评估」上传新文档即可产生。")
        return
    for rec in reversed(records[:limit]):
        st.html(ui.decision_card(rec))
    if len(records) > limit:
        st.caption(f"仅显示最近 {limit} 条，共 {len(records)} 条。")


DOC_PREVIEW_LIMIT = 1600  # 文件详情只预览开头这么多字，避免整篇渲染


def _docs_by_folder(s) -> dict[str, list[dict]]:
    """folder_id -> 该文件夹自己的文档列表（不含子文件夹）。"""
    out: dict[str, list[dict]] = {}
    for d in vectorstore.list_sources(s):
        out.setdefault(d.get("folder_id") or "", []).append(d)
    return out


def _render_tree(s, lib) -> None:
    """IDE 风格项目树：文件夹可展开/收起，展开后先列自己的文件、再列子文件夹。"""
    opened = set(st.session_state.get("open_folders") or [])
    cur = st.session_state.get("folder_id")
    sel = st.session_state.get("sel_doc") or {}
    counts = vectorstore.counts_by_folder(s)
    docs_by_folder = _docs_by_folder(s)

    def doc_row(doc: dict, depth: int) -> None:
        is_sel = (
            sel.get("source") == doc["source"]
            and sel.get("version") == doc["version"]
            and (sel.get("folder_id") or "") == (doc.get("folder_id") or "")
        )
        st.button(
            "\u3000\u3000" * depth + doc["source"],
            key=f"doc_{doc.get('folder_id') or 'root'}_{doc['source']}_{doc['version']}",
            width="stretch",
            icon=":material/description:",
            type="primary" if is_sel else "secondary",
            on_click=_select_doc,
            args=(doc,),
        )

    def folder_row(fid: str | None, name: str, depth: int, n: int) -> None:
        key = fid or "__root__"
        is_open = key in opened
        label = "\u3000\u3000" * depth + ("▾ " if is_open else "▸ ") + name
        if n:
            label += f"  · {n}"
        st.button(
            label,
            key=f"tree_{key}",
            width="stretch",
            icon=":material/folder_open:" if is_open else ":material/folder:",
            type="primary" if (cur == fid and not sel) else "secondary",
            on_click=_toggle_folder,
            args=(fid,),
        )
        if not is_open:
            return
        for doc in docs_by_folder.get(fid or "", []):
            doc_row(doc, depth + 1)
        if fid is None:
            return
        for child in lib.children(fid):
            folder_row(child.id, child.name, depth + 1, counts.get(child.id, 0))

    folder_row(None, "全部文件", 0, vectorstore.count(s))
    seen_roots: set[str] = set()
    for depth, f in lib.tree():
        if depth != 0:
            continue  # 子文件夹交给父节点的展开逻辑递归渲染
        seen_roots.add(f.id)
        folder_row(f.id, f.name, depth, counts.get(f.id, 0))


def _render_file_detail(s, sel: dict) -> None:
    """右侧文件详情：元信息 + 前 N 字预览（全文仍留在向量库里）。"""
    path = sel.get("folder_path") or "未分类"
    if st.button("← 返回文件夹", icon=":material/arrow_back:", key="doc_back"):
        st.session_state.sel_doc = None
        st.rerun()
    with st.container(horizontal=True, vertical_alignment="center", key="doc_head"):
        st.html(ui.hero_text(sel["source"], f"{path} · {sel['version']}"))
        st.html(
            ui.chips_html(
                [
                    ui.chip("文本块", str(sel.get("chunk_count") or 0)),
                    ui.chip("主题", sel.get("topic") or "-"),
                    ui.chip("更新", (sel.get("updated_at") or "-")[:19], dot="idle"),
                ]
            )
        )
    ui.section("文件内容预览")
    text, total = vectorstore.get_document_text(
        s, sel["source"], sel["version"], sel.get("folder_id") or "", limit=DOC_PREVIEW_LIMIT
    )
    if not text:
        st.caption("这个版本读不到文本块，可能已被删除。")
        return
    # Markdown / 文本可以直接渲染看排版；渲染是把截断后的片段当 md 解析，长文档可能被切在代码块中间
    if Path(sel["source"]).suffix.lower() in {".md", ".markdown", ".txt"}:
        if st.toggle("渲染 Markdown 排版", value=False, key="doc_render"):
            st.markdown(text)
        else:
            st.html(f'<pre class="pka-doc">{html.escape(text)}</pre>')
    else:
        st.html(f'<pre class="pka-doc">{html.escape(text)}</pre>')
    st.caption(
        f"仅预览前 {len(text)} 字（全文约 {total} 字）；"
        f"完整内容已分 {sel.get('chunk_count') or 0} 块入库，提问时用于检索。"
    )
    with st.expander("删除这份文档", icon=":material/delete:"):
        st.caption("只删除该文档的这个版本，其它版本与其它知识库不受影响。")
        if st.button("确认删除", key="doc_del", icon=":material/delete:"):
            n = vectorstore.delete_by_source(
                s, sel["source"], sel["version"], folder_id=sel.get("folder_id") or ""
            )
            vectorstore.reset_client()
            st.session_state.sel_doc = None
            st.success(f"已删除 {n} 个文本块。", icon=":material/check_circle:")
            st.rerun()


def _render_docs(s, docs: list[dict]) -> None:
    """文档清单 + 删除（删除范围包含文件夹，避免同名文件跨库误删）。"""
    ui.section(f"文档清单 · {len(docs)}")
    if not docs:
        st.caption("这个范围还没有文档，先在上面的「上传入库」里添加资料。")
        return
    st.dataframe(
        [
            {
                "文件名": x["source"],
                "位置": x["folder_path"] or "未分类",
                "版本": x["version"],
                "主题": x["topic"],
                "块数": x["chunk_count"],
                "更新时间": x["updated_at"],
            }
            for x in docs
        ],
        width="stretch",
        height=min(420, 45 + 36 * len(docs)),
    )
    with st.expander("删除文档", icon=":material/delete:"):
        labels = {f"{(x['folder_path'] or '未分类')} / {x['source']} · {x['version']}": x for x in docs}
        pick = st.selectbox("选择要删除的文档", list(labels))
        st.caption("只删除所选文档的这一个版本；同名的其它版本与其它文件夹不受影响。")
        if st.button("确认删除", icon=":material/delete:"):
            item = labels[pick]
            n = vectorstore.delete_by_source(
                s, item["source"], item["version"], folder_id=item["folder_id"]
            )
            vectorstore.reset_client()
            st.success(f"已删除 {n} 个文本块。", icon=":material/check_circle:")
            st.rerun()


def page_library() -> None:
    s = _active_settings()
    lib = _library()
    fid = st.session_state.get("folder_id")
    folder = lib.get(fid) if fid and fid != UNFILED else None
    counts = vectorstore.counts_by_folder(s)

    col_tree, col_main = st.columns([1, 2.55], gap="medium")
    with col_tree:
        ui.section("知识库文件夹")
        if st.button(
            "新建知识库文件夹", icon=":material/create_new_folder:",
            width="stretch", type="primary" if not lib.tree() else "secondary",
        ):
            _dialog_new_folder(None)
        _render_tree(s, lib)
        st.caption("点文件夹展开 / 收起；点文件名在右侧看内容预览。只删空文件夹，避免误删成批资料。")

    with col_main:
        sel = st.session_state.get("sel_doc")
        if sel:
            _render_file_detail(s, sel)
            return
        if folder:
            title, desc = lib.path(folder.id), folder.description or "还没有简介，点「编辑信息」补一句。"
            scope_ids: list[str] | None = lib.descendant_ids(folder.id)
            target_id, target_path = folder.id, lib.path(folder.id)
        elif fid == UNFILED:
            title, desc = "未分类", "直接上传、未归入任何文件夹的资料。"
            scope_ids, target_id, target_path = [""], "", ""
        else:
            title, desc = "全部文件", "所有知识库文件夹里的资料汇总。上传到未分类，或先选一个文件夹。"
            scope_ids, target_id, target_path = None, "", ""

        docs = vectorstore.list_sources(s, scope_ids)
        with st.container(horizontal=True, vertical_alignment="center", key="lib_head"):
            st.html(ui.hero_text(title, desc))
            st.html(
                ui.chips_html(
                    [
                        ui.chip("文档", str(len(docs))),
                        ui.chip("文本块", str(vectorstore.count(s, scope_ids))),
                        ui.chip("分类", (folder.category if folder else "-") or "-", dot="idle"),
                    ]
                )
            )

        with st.container(horizontal=True, key="lib_actions"):
            if st.button("新建子文件夹", icon=":material/create_new_folder:", key="new_sub"):
                _dialog_new_folder(folder.id if folder else None)
            if folder and st.button("编辑信息", icon=":material/edit:", key="edit_folder"):
                _dialog_edit_folder(folder.id)
            if folder and st.button("删除文件夹", icon=":material/folder_delete:", key="del_folder"):
                _dialog_delete_folder(folder.id)

        _render_ingest(s, lib, target_id, target_path)
        _render_docs(s, docs)
        _render_update_records(s, folder.id if folder else None)


def page_logs() -> None:
    # 只看 PRD 定义的三类日志；logs/ 下还可能有测试与工具产生的其它文件
    family = ("operation", "update", "error")
    logs = [f for f in list_log_files() if f.name.split(".")[0] in family]
    ui.hero(
        "日志",
        "按 PRD 3.2.5 记录：操作 / 更迭 / 错误三类，按日期滚动保留 30 天。",
        chips=[ui.chip("日志文件", str(len(logs)))],
    )
    if not logs:
        ui.empty_state("暂无日志", "运行一次入库或问答后自动生成。", glyph="≡")
        return
    names = [f.name for f in logs]
    default_idx = next((i for i, n in enumerate(names) if n.startswith("operation.log")), 0)
    col_f, col_n = st.columns([2, 1.6])
    with col_f:
        picked = st.selectbox("日志文件", names, index=default_idx)
    with col_n:
        lines_n = st.slider("显示行数", 20, 1000, 200, step=20)
    content = tail_log(picked, lines_n)
    body = html.escape("\n".join(content)) if content else "（空）"
    st.html(f'<pre class="pka-log">{body}</pre>')


def main() -> None:
    inject_theme()
    _init_state()
    _sidebar()
    page = st.session_state.get("page", "qa")
    {"qa": page_qa, "library": page_library, "logs": page_logs}.get(page, page_qa)()


main()
