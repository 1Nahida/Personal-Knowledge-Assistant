"""PKA 视觉系统：设计 token + 全局 CSS 注入。

设计依据 docs/design-refs/ 参考图与《PKA UI 优化》改造文档：
深色科技风底 + 活力青强调色，卡片圆角 12px、页边距 28px、模块间距 28px。

只改样式，不碰框架：所有规则都作用在 Streamlit 原生组件的 DOM 上，
页面结构仍用 st.* 原生 API 搭建，避免破坏重运行与会话状态机制。
"""

from __future__ import annotations

import streamlit as st

# ---- 设计 token（唯一来源，改色只改这里）----
TOKENS: dict[str, str] = {
    "bg": "#10141D",          # 主背景
    "bg_deep": "#0B0F16",     # 侧栏等更深一层
    "surface": "#1A2230",     # 卡片背景
    "surface_2": "#263345",   # 辅助背景 / hover
    "border": "#243043",      # 细边框
    "border_soft": "#1E2938",
    "accent": "#22C3D6",      # 主题强调色
    "accent_dim": "#1A8F9E",
    "accent_soft": "rgba(34,195,214,0.12)",
    "text": "#E6EAF2",
    "text_dim": "#93A1B5",
    "text_faint": "#64748B",
    "ok": "#22C55E",
    "warn": "#F59E0B",
    "err": "#EF4444",
    "radius_card": "12px",
    "radius_input": "10px",
}

FONT_STACK = (
    "-apple-system,'Segoe UI Variable Text','Segoe UI','Microsoft YaHei UI',"
    "'Microsoft YaHei','Noto Sans SC',sans-serif"
)
MONO_STACK = "'Cascadia Code','Consolas','DejaVu Sans Mono',monospace"


def _css() -> str:
    t = TOKENS
    return f"""
:root {{
  --pka-bg: {t['bg']};
  --pka-bg-deep: {t['bg_deep']};
  --pka-surface: {t['surface']};
  --pka-surface-2: {t['surface_2']};
  --pka-border: {t['border']};
  --pka-border-soft: {t['border_soft']};
  --pka-accent: {t['accent']};
  --pka-accent-dim: {t['accent_dim']};
  --pka-accent-soft: {t['accent_soft']};
  --pka-text: {t['text']};
  --pka-text-dim: {t['text_dim']};
  --pka-text-faint: {t['text_faint']};
  --pka-ok: {t['ok']};
  --pka-warn: {t['warn']};
  --pka-err: {t['err']};
  --pka-radius: {t['radius_card']};
  --pka-radius-input: {t['radius_input']};
}}

/* ---------- 基础 ---------- */
html, body, .stApp, [data-testid="stAppViewContainer"] {{
  background: var(--pka-bg);
  color: var(--pka-text);
  font-family: {FONT_STACK};
  -webkit-font-smoothing: antialiased;
}}
[data-testid="stAppViewContainer"] > .main {{ background: var(--pka-bg); }}
[data-testid="stMainBlockContainer"], .block-container {{
  padding: 28px 32px 48px 32px !important;
  max-width: 1180px;
}}
[data-testid="stHeader"] {{ background: transparent; height: 0; }}
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer {{ display: none !important; }}
[data-testid="stStatusWidget"] {{ display: none !important; }}

h1, h2, h3, h4 {{ color: var(--pka-text); font-weight: 600; letter-spacing: -0.01em; }}
h1 {{ font-size: 1.75rem; }}
h2 {{ font-size: 1.25rem; }}
h3 {{ font-size: 1.02rem; }}
p, li, .stMarkdown {{ color: var(--pka-text); line-height: 1.65; }}
a {{ color: var(--pka-accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
hr {{ border-color: var(--pka-border-soft); }}
code, pre, kbd {{ font-family: {MONO_STACK} !important; }}
[data-testid="stCodeBlock"] {{ border: 1px solid var(--pka-border); border-radius: var(--pka-radius); overflow: hidden; }}
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: #2A3A50; border-radius: 8px; }}
::-webkit-scrollbar-thumb:hover {{ background: #35496A; }}
::-webkit-scrollbar-track {{ background: transparent; }}

/* ---------- 侧栏 ---------- */
section[data-testid="stSidebar"] {{
  background: var(--pka-bg-deep);
  border-right: 1px solid var(--pka-border-soft);
  width: 288px !important;
}}
section[data-testid="stSidebar"] > div {{ padding-top: 18px; }}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{ padding: 0 14px 16px 14px; }}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{ font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--pka-text-faint); font-weight: 600; margin: 6px 0 8px; }}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{ color: var(--pka-text-faint); font-size: 0.78rem; }}

/* 侧栏导航按钮：整行、左对齐、选中态用主色底色 */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0.5rem; }}
.st-key-pka_nav {{ gap: 2px; }}
section[data-testid="stSidebar"] .stButton > button {{
  width: 100%;
  justify-content: flex-start !important;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  color: var(--pka-text-dim);
  font-size: 0.92rem;
  font-weight: 500;
  border-radius: var(--pka-radius-input);
  padding: 9px 12px;
  min-height: 40px;
  transition: background .15s ease, color .15s ease, border-color .15s ease;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
  background: var(--pka-surface);
  color: var(--pka-text);
  border-color: var(--pka-border-soft);
}}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
  background: var(--pka-accent-soft);
  border-color: rgba(34,195,214,0.35);
  color: var(--pka-accent);
  font-weight: 600;
}}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
  background: rgba(34,195,214,0.18);
  color: #7FE3EF;
}}
/* Streamlit 把按钮文字包在内层 flex div 里，只改 button 的 justify-content 不够 */
section[data-testid="stSidebar"] .stButton button > div,
section[data-testid="stSidebar"] .stButton button > div > span,
section[data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"] {{
  justify-content: flex-start !important;
  text-align: left !important;
  width: 100%;
}}
section[data-testid="stSidebar"] .stButton button p {{
  text-align: left !important;
  font-size: 0.9rem;
  width: 100%;
}}
section[data-testid="stSidebar"] .stButton > button [data-testid="stIconMaterial"] {{
  font-size: 18px; opacity: .9; margin-right: 2px;
}}
.pka-side-label {{
  margin: 12px 0 5px; font-size: 0.68rem; letter-spacing: 0.11em;
  text-transform: uppercase; color: var(--pka-text-faint); font-weight: 650;
}}
/* 空态示例卡：整块可点，左对齐两行 */
.st-key-ex_0 button, .st-key-ex_1 button, .st-key-ex_2 button, .st-key-ex_3 button {{
  min-height: 62px;
  justify-content: flex-start !important;
  text-align: left !important;
  background: var(--pka-surface) !important;
  border: 1px solid var(--pka-border-soft) !important;
  border-radius: var(--pka-radius) !important;
  padding: 10px 14px !important;
}}
.st-key-ex_0 button:hover, .st-key-ex_1 button:hover,
.st-key-ex_2 button:hover, .st-key-ex_3 button:hover {{
  border-color: rgba(34,195,214,0.45) !important;
  background: rgba(34,195,214,0.07) !important;
}}
.st-key-ex_0 button > div, .st-key-ex_1 button > div,
.st-key-ex_2 button > div, .st-key-ex_3 button > div,
.st-key-ex_0 button > div > span, .st-key-ex_1 button > div > span,
.st-key-ex_2 button > div > span, .st-key-ex_3 button > div > span,
.st-key-ex_0 button [data-testid="stMarkdownContainer"],
.st-key-ex_1 button [data-testid="stMarkdownContainer"],
.st-key-ex_2 button [data-testid="stMarkdownContainer"],
.st-key-ex_3 button [data-testid="stMarkdownContainer"] {{
  justify-content: flex-start !important; text-align: left !important; width: 100%;
}}
/* 示例卡第二行：类别小字（内容由 app.py 按卡片注入） */
[class*="st-key-ex_"] button {{
  flex-direction: column; align-items: flex-start;
  justify-content: center !important;
  min-height: 76px; row-gap: 3px;
}}
[class*="st-key-ex_"] button::after {{
  font-size: 0.72rem; font-weight: 450; color: var(--pka-text-faint);
}}

.st-key-ex_0 button p, .st-key-ex_1 button p, .st-key-ex_2 button p, .st-key-ex_3 button p {{
  font-size: 0.88rem !important; font-weight: 500; text-align: left !important;
  color: var(--pka-text) !important; margin: 0 !important;
}}

/* 日志：长行折行，避免横向滚动 */
[data-testid="stCode"] pre {{ white-space: pre-wrap !important; word-break: break-all; }}
[data-testid="stCode"] {{ max-height: 62vh; overflow: auto; }}

/* ---------- 主区按钮 / 输入 ---------- */
.stButton > button, .stFormSubmitButton > button {{
  border-radius: var(--pka-radius-input);
  border: 1px solid var(--pka-border);
  background: var(--pka-surface);
  color: var(--pka-text);
  font-weight: 500;
  transition: border-color .15s ease, background .15s ease, box-shadow .15s ease;
}}
.stButton > button:hover, .stFormSubmitButton > button:hover {{
  border-color: var(--pka-accent-dim);
  color: var(--pka-text);
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: linear-gradient(135deg, var(--pka-accent) 0%, #1FA9BA 100%);
  border: 1px solid transparent;
  color: #06222A;
  font-weight: 700;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
  box-shadow: 0 6px 18px rgba(34,195,214,0.28);
  color: #04191F;
}}
.stButton > button:focus:not(:active) {{ border-color: var(--pka-accent); color: var(--pka-text); }}

.stTextInput input, .stTextArea textarea, .stNumberInput input {{
  background: var(--pka-surface) !important;
  border: 1px solid var(--pka-border) !important;
  border-radius: var(--pka-radius-input) !important;
  color: var(--pka-text) !important;
  padding: 10px 14px !important;
  font-size: 0.94rem !important;
}}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {{ color: var(--pka-text-faint) !important; }}
.stTextInput input:focus, .stTextArea textarea:focus {{
  border-color: var(--pka-accent) !important;
  box-shadow: 0 0 0 3px var(--pka-accent-soft) !important;
}}
[data-baseweb="select"] > div, [data-baseweb="input"] > div {{
  background: var(--pka-surface) !important;
  border-color: var(--pka-border) !important;
  border-radius: var(--pka-radius-input) !important;
  color: var(--pka-text) !important;
}}
[data-baseweb="popover"] [role="listbox"] {{ background: var(--pka-surface) !important; border: 1px solid var(--pka-border) !important; }}
[data-baseweb="popover"] li:hover {{ background: var(--pka-surface-2) !important; }}

/* 单选 / 复选：改成卡片式 pill */
section[data-testid="stSidebar"] [data-testid="stRadio"] label,
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label {{
  color: var(--pka-text-dim); font-size: 0.88rem;
}}
section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {{ color: var(--pka-text); }}
[data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] {{ background: var(--pka-accent) !important; border-color: var(--pka-accent) !important; }}
[data-testid="stSlider"] [data-testid="stTickBar"] {{ display: none; }}
[data-testid="stSlider"] {{ padding-top: 0; }}

/* ---------- 卡片容器 ---------- */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--pka-surface);
  border: 1px solid var(--pka-border-soft) !important;
  border-radius: var(--pka-radius);
}}
[data-testid="stVerticalBlockBorderWrapper"] > div {{ padding: 4px 2px; }}
[data-testid="stExpander"] {{
  border: 1px solid var(--pka-border-soft) !important;
  border-radius: var(--pka-radius) !important;
  background: rgba(26,34,48,0.55) !important;
  overflow: hidden;
}}
[data-testid="stExpander"] summary {{ color: var(--pka-text-dim); font-size: 0.86rem; }}
[data-testid="stExpander"] summary:hover {{ color: var(--pka-accent); }}

/* 提示条：统一成低饱和信息卡，避免原生 success 绿块抢视线 */
[data-testid="stAlert"] {{
  border-radius: var(--pka-radius);
  border: 1px solid var(--pka-border) !important;
  background: var(--pka-surface) !important;
  color: var(--pka-text) !important;
  font-size: 0.86rem;
}}
[data-testid="stAlert"] p {{ color: var(--pka-text) !important; }}
[data-testid="stAlertContainer"] {{ border: none !important; }}

/* ---------- 聊天消息 ---------- */
[data-testid="stChatMessage"] {{
  background: var(--pka-surface);
  border: 1px solid var(--pka-border-soft);
  border-radius: var(--pka-radius);
  padding: 14px 18px;
  margin-bottom: 14px;
}}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{
  background: rgba(38,51,69,0.5);
}}
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {{
  background: var(--pka-accent-soft) !important;
  border: 1px solid rgba(34,195,214,0.3) !important;
}}

/* ---------- 数据表 ---------- */
[data-testid="stDataFrame"], [data-testid="stTable"] {{
  border: 1px solid var(--pka-border-soft);
  border-radius: var(--pka-radius);
  overflow: hidden;
}}
[data-testid="stFileUploaderDropzone"] {{
  background: var(--pka-surface) !important;
  border: 1.5px dashed var(--pka-border) !important;
  border-radius: var(--pka-radius) !important;
}}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color: var(--pka-accent-dim) !important; }}
[data-testid="stFileUploaderDropzone"] {{ padding: 16px 18px !important; }}
[data-testid="stFileUploaderDropzone"] button {{ border-radius: 8px; }}
[data-testid="stFileUploader"] {{ margin: 6px 0 4px; }}

/* 侧栏单选（模型源）：每行做成可点的 pill */
section[data-testid="stSidebar"] [data-testid="stRadioOption"] {{
  padding: 5px 8px; border-radius: 8px; margin: 0 0 2px;
  transition: background .12s ease;
}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {{ background: var(--pka-surface); }}
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] {{ gap: 0; }}

/* 侧栏历史会话：pills 竖排成列表，每行整宽左对齐 */
section[data-testid="stSidebar"] [data-testid="stPills"],
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] {{
  flex-direction: column; align-items: stretch; gap: 4px;
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button,
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button {{
  justify-content: flex-start; width: 100%;
  padding: 6px 10px; border-radius: 8px;
  font-size: 0.8rem; text-align: left;
  background: rgba(26,34,48,0.7); border: 1px solid var(--pka-border-soft);
  color: var(--pka-text-dim);
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button[aria-checked="true"],
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button[aria-checked="true"],
section[data-testid="stSidebar"] [data-testid="stPills"] button [data-testid="stMarkdownContainer"] p {{
  color: var(--pka-text);
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button[aria-checked="true"],
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button[aria-checked="true"] {{
  background: var(--pka-accent-soft); border-color: rgba(34,195,214,0.38);
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button:hover,
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button:hover {{
  background: var(--pka-surface); border-color: var(--pka-border-soft);
}}

/* 侧栏所有按钮与导航保持同一对齐方式 */
section[data-testid="stSidebar"] .stButton button,
section[data-testid="stSidebar"] .stButton button > div,
section[data-testid="stSidebar"] .stButton button > div > span,
section[data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"] {{
  justify-content: flex-start !important;
  text-align: left;
  width: 100%;
}}

/* ---------- 自定义组件 ---------- */
.pka-hero {{
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 20px; margin: 4px 0 22px;
}}
.pka-hero-title {{ font-size: 1.6rem; font-weight: 650; letter-spacing: -0.02em; color: var(--pka-text); margin: 0; }}
.pka-hero-sub {{ color: var(--pka-text-dim); font-size: 0.88rem; margin: 6px 0 0; }}

/* 问答页头：标题占满剩余宽度，chips 与删除按钮靠右同一行 */
.st-key-qa_head {{ align-items: center; gap: 10px; }}
.st-key-qa_head > [data-testid="stElementContainer"]:first-child {{ flex: 1 1 auto; min-width: 0; }}
.st-key-qa_head .pka-hero-title {{ font-size: 1.62rem; }}
.st-key-qa_head button[data-testid="stBaseButton-secondary"] {{
  min-height: 34px; padding: 0 10px; border-radius: 9px;
  border-color: var(--pka-border); color: var(--pka-text-dim);
}}
.st-key-qa_head button[data-testid="stBaseButton-secondary"]:hover {{
  color: var(--pka-err); border-color: rgba(239,68,68,0.45); background: rgba(239,68,68,0.08);
}}

/* 删除确认弹窗 */
[data-testid="stDialog"] > div {{
  background: var(--pka-surface); border: 1px solid var(--pka-border);
  border-radius: 16px;
}}
.pka-chips {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
.pka-chip {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 11px; border-radius: 999px;
  background: var(--pka-surface); border: 1px solid var(--pka-border-soft);
  color: var(--pka-text-dim); font-size: 0.76rem; white-space: nowrap;
}}
.pka-chip b {{ color: var(--pka-text); font-weight: 600; }}
.pka-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
.pka-dot-ok {{ background: var(--pka-ok); box-shadow: 0 0 0 3px rgba(34,197,94,0.14); }}
.pka-dot-warn {{ background: var(--pka-warn); box-shadow: 0 0 0 3px rgba(245,158,11,0.14); }}
.pka-dot-err {{ background: var(--pka-err); box-shadow: 0 0 0 3px rgba(239,68,68,0.14); }}
.pka-dot-idle {{ background: var(--pka-text-faint); }}

.pka-empty {{ text-align: center; padding: 42px 0 26px; }}
.pka-empty-mark {{
  width: 62px; height: 62px; margin: 0 auto 18px; border-radius: 18px;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle at 30% 25%, rgba(34,195,214,0.35), rgba(34,195,214,0.06) 70%);
  border: 1px solid rgba(34,195,214,0.28);
  box-shadow: 0 0 40px rgba(34,195,214,0.16);
}}
.pka-empty h2 {{ font-size: 1.5rem; margin: 0 0 10px; letter-spacing: -0.02em; }}
.pka-empty p {{ color: var(--pka-text-dim); font-size: 0.9rem; margin: 0; }}

.pka-section {{ display: flex; align-items: center; gap: 10px; margin: 4px 0 12px; }}
.pka-section-title {{ font-size: 0.95rem; font-weight: 600; color: var(--pka-text); }}
.pka-section-line {{ flex: 1; height: 1px; background: var(--pka-border-soft); }}

.pka-cite {{
  border-left: 2px solid rgba(34,195,214,0.45);
  padding: 8px 12px; margin: 8px 0;
  background: rgba(16,20,29,0.55);
  border-radius: 0 8px 8px 0;
}}
.pka-cite-head {{ font-size: 0.8rem; color: var(--pka-text); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
.pka-cite-idx {{ color: var(--pka-accent); font-weight: 700; }}
.pka-cite-meta {{ color: var(--pka-text-faint); font-size: 0.74rem; }}
.pka-cite-body {{ color: var(--pka-text-dim); font-size: 0.78rem; margin-top: 4px; line-height: 1.55; }}

/* 更迭决策卡 */
.pka-dec {{
  background: var(--pka-surface); border: 1px solid var(--pka-border-soft);
  border-left: 3px solid var(--pka-accent); border-radius: var(--pka-radius);
  padding: 14px 16px; margin-bottom: 12px;
}}
.pka-dec-head {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 9px; }}
.pka-tag {{ padding: 3px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 700; }}
.pka-dec-title {{ font-size: 0.95rem; font-weight: 600; color: var(--pka-text); }}
.pka-dec-ver {{ font-family: {MONO_STACK}; font-size: 0.78rem; color: var(--pka-text-dim); }}
.pka-dec-time {{ margin-left: auto; font-size: 0.72rem; color: var(--pka-text-faint); }}
.pka-dec-reason {{ font-size: 0.85rem; color: var(--pka-text-dim); line-height: 1.62; margin: 0 0 12px; }}
.pka-dec-src {{ margin-top: 9px; font-size: 0.72rem; color: var(--pka-text-faint); }}
.pka-scores {{ display: flex; gap: 26px; }}
.pka-score {{ flex: 1; }}
.pka-score-label {{ display: flex; justify-content: space-between; font-size: 0.74rem; color: var(--pka-text-faint); margin-bottom: 6px; }}
.pka-bar {{ height: 6px; border-radius: 999px; background: var(--pka-surface-2); overflow: hidden; }}
.pka-bar-fill {{ height: 100%; border-radius: 999px; }}

/* 用户消息靠右收窄，和助手卡片区分开 */
[data-testid="stChatMessage"]:not(:has(img)) {{
  background: rgba(34,195,214,0.07) !important;
  border-color: rgba(34,195,214,0.20) !important;
  margin-left: auto;
  width: fit-content;
  max-width: 78%;
}}

/* 问答页：内容不满一屏时把提问条压到页面底部 */
.st-key-qa_page {{
  display: flex; flex-direction: column;
  min-height: calc(100vh - 172px);
}}
/* 最后一个子元素（提问条所在的列容器）吃掉剩余高度 */
.st-key-qa_page > *:last-child {{ margin-top: auto; }}

/* 日志正文：等宽 + 自动换行，长行不再被裁掉 */
.pka-log {{
  white-space: pre-wrap;
  word-break: break-all;
  font-family: var(--pka-mono);
  font-size: 0.76rem;
  line-height: 1.55;
  color: var(--pka-text-dim);
  background: var(--pka-surface);
  border: 1px solid var(--pka-border-soft);
  border-radius: var(--pka-radius);
  padding: 14px 16px;
  margin: 0;
  max-height: 62vh;
  overflow: auto;
}}

/* 文件详情预览：正文用正文字体，保留换行，限定高度 */
.pka-doc {{
  white-space: pre-wrap;
  word-break: break-word;
  font-family: {FONT_STACK};
  font-size: 0.86rem;
  line-height: 1.72;
  color: var(--pka-text);
  background: var(--pka-surface);
  border: 1px solid var(--pka-border-soft);
  border-left: 3px solid var(--pka-accent-dim);
  border-radius: var(--pka-radius);
  padding: 16px 20px;
  margin: 0;
  max-height: 56vh;
  overflow: auto;
}}

.pka-brand {{ display: flex; align-items: center; gap: 11px; padding: 2px 4px 14px; }}
.pka-brand-avatar {{
  width: 36px; height: 36px; border-radius: 11px; flex: none;
  object-fit: cover; object-position: center 18%;
  border: 1px solid rgba(34,195,214,0.35);
  box-shadow: 0 0 0 3px rgba(34,195,214,0.10);
}}
.pka-brand-mark {{
  width: 34px; height: 34px; border-radius: 10px; flex: none;
  background: linear-gradient(135deg, rgba(34,195,214,0.95), rgba(34,195,214,0.35));
  display: flex; align-items: center; justify-content: center;
  color: #06222A; font-weight: 800; font-size: 0.9rem;
}}
.pka-brand-name {{ font-size: 0.98rem; font-weight: 650; color: var(--pka-text); line-height: 1.2; }}
.pka-brand-sub {{ font-size: 0.72rem; color: var(--pka-text-faint); }}

.pka-user {{
  display: flex; align-items: center; gap: 10px; margin-top: 6px;
  padding: 9px 10px; border-radius: var(--pka-radius);
  background: var(--pka-surface); border: 1px solid var(--pka-border-soft);
}}
.pka-user img {{ width: 30px; height: 30px; border-radius: 50%; object-fit: cover; }}
.pka-user-name {{ font-size: 0.82rem; color: var(--pka-text); font-weight: 550; line-height: 1.2; }}
.pka-user-role {{ font-size: 0.7rem; color: var(--pka-text-faint); }}
"""


def inject() -> None:
    """注入全局样式；每个页面开头调用一次（幂等，重复注入无副作用）。"""
    st.html(f"<style>{_css()}</style>")
