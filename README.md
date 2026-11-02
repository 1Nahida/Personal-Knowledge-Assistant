# PKA · 基于本地知识库的知识问答助手

本地优先的 RAG 知识问答助手：把 PDF / Markdown / TXT / DOCX 资料入库，用自然语言提问，
回答附带**文件名 + 页码 + 版本号**的引用来源；支持**技术更迭评估**——新资料与库中旧内容对比后，
自动决定「替换旧版本」还是「拦截新内容」。全部推理可在本地 Ollama 完成，断网可用。

**当前版本：v1.2.0** · Python 3.10+ · Streamlit 1.66 · ChromaDB 0.6 · LangChain · Ollama

## 功能对照 PRD

| PRD 条目 | 实现位置 | 状态 |
| --- | --- | --- |
| 3.2.1 知识库管理（多格式入库、语义分块、向量化、元数据） | `src/pka/agents/ingestion.py`、`src/pka/core/vectorstore.py` | ✅ |
| 3.2.2 智能问答（Top-K 检索 + 生成 + 引用来源） | `src/pka/agents/qa_agent.py` | ✅ |
| 3.2.3 技术更迭（REPLACE / KEEP_OLD + 评分 + 更迭日志） | `src/pka/agents/update_agent.py` | ✅ |
| 3.2.4 模型切换（Ollama / DashScope / DeepSeek，无需重启，云端失败自动降级） | `src/pka/core/model_factory.py` | ✅（云端需 API Key） |
| 3.2.5 日志（operation / update / error，按天滚动） | `src/pka/logger.py` | ✅ |
| 对话历史（P1） | `src/pka/agents/history.py`（SQLite） | ✅ |
| 知识库浏览（P1） | `app.py` 的「知识库」页 | ✅ |
| 多知识库文件夹（用户补充需求） | `src/pka/agents/library.py`（SQLite 文件夹树 + 分库入库/检索） | ✅ |

## 快速开始

```powershell
# 1. 依赖（Python 3.10+，本仓库使用 .venv / Python 3.11.3）
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

# 2. 本地模型（Ollama）
ollama serve                      # 若未随桌面版启动
ollama pull qwen2.5:7b            # 对话模型（PRD 默认）
ollama pull bge-m3                # 嵌入模型（1024 维，PRD 指定；拉不动可临时用 nomic-embed-text）

# 3. 配置
Copy-Item .env.example .env       # 然后按需修改

# 4. 启动前端
& ".\.venv\Scripts\python.exe" -m streamlit run app.py
# 浏览器打开 http://localhost:8501
```

或直接双击 / 运行 `scripts\start_app.ps1`。

## 环境变量（`.env`）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `MODEL_PROVIDER` | 对话模型源：`ollama` / `dashscope` / `deepseek` | `ollama` |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | 本地 Ollama 地址与模型 | `http://localhost:11434` / `qwen2.5:7b` |
| `DASHSCOPE_API_KEY` / `DASHSCOPE_MODEL` | 阿里云百炼 | 空 / `qwen-plus` |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | DeepSeek | 空 / `deepseek-chat` |
| `EMBEDDING_MODEL` | 嵌入模型（**改它会换 Chroma 集合，需重新入库**） | `bge-m3` |
| `TOP_K` | 召回条数 | `5` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块大小与重叠（字符） | `700` / `120` |
| `ENABLE_FALLBACK` | 云端失败时自动降级本地 Ollama | `true` |

## 使用说明

前端三个页面（侧栏切换）：

1. **智能问答**：直接提问，回答下方展开「引用来源」看命中片段与相关度。
   侧栏的「检索范围」可切 **跟随文件夹**（只查当前选中的知识库）或 **全库**。
2. **知识库**：左侧是 IDE 风格的项目树，右侧随选中对象切换内容。
   - 树：点文件夹**展开 / 收起**子节点（默认收起），展开后先列该文件夹自己的文件、再列子文件夹；
     点**文件名**右侧切到「文件详情」——版本 / 主题 / 块数 + 前 1600 字内容预览（md/txt 可选择渲染排版），可在此删除该版本；
     点文件夹本身右侧显示上传入库 / 文档清单 / 更迭记录。左侧顶部的「全部文件」汇总全库，展开时列出未分类的文件。
   - 可建任意层级的文件夹（如 `Python`、`深度学习`、`novel/七日系列`），名称、分类、简介都能改；
   - 上传即入当前文件夹；勾选「启用技术更迭评估」后，系统抽新技术点 → 与**同一文件夹内**同主题旧内容对比
     → 输出 `REPLACE`（替换并版本 +1）或 `KEEP_OLD`（仅记录拦截原因）；
   - 删除文档时带文件夹范围，同名文件在其它知识库不会被误删；文件夹只允许删空的。
3. **日志**：查看 `operation.log` / `update.log` / `error.log`（含按天滚动出的历史文件）。

## 技术更迭评估是怎么判定的

```
新文档 → 解析清洗 → LLM 抽取关键技术点
                  ↓
     检索**同一文件夹内**同主题旧内容（不跨知识库，排除同名文件）
                  ↓
   「资深技术评审专家」提示词对比稳定性 / 性能
                  ↓
   REPLACE：删旧向量 → 写新内容 → 版本号 +1 → 记录 update.log + update_history.jsonl
   KEEP_OLD：只记录拦截原因，知识库不变
```

更迭记录字段（PRD 5.2）：`timestamp` / `topic` / `source` / `old_version` / `new_version` /
`decision` / `reason` / `stability_score` / `performance_score`。

## 目录结构

```
PKA/
├── app.py                     # Streamlit 入口（三页面：智能问答 / 知识库 / 日志）
├── src/pka/
│   ├── config.py              # Settings：三模型源 / embedding / 分块 / 路径
│   ├── logger.py              # operation / update / error / app 四类日志
│   ├── agents/
│   │   ├── ingestion.py       # 解析 → 清洗 → 分块 → 入库（含文本损坏检测）
│   │   ├── qa_agent.py        # 检索 + 生成 + 引用
│   │   ├── update_agent.py    # 技术更迭评估与执行（限定同一文件夹）
│   │   ├── library.py         # 知识库文件夹树（SQLite：名称/分类/简介/层级）
│   │   └── history.py         # 对话历史（SQLite）
│   ├── ui/
│   │   ├── theme.py           # 设计 token + 全站 CSS（暗色科技风）
│   │   └── components.py      # hero / chips / 决策卡 / 引用列表等纯 HTML 组件
│   └── core/
│       ├── model_factory.py   # ChatModel 构建 / 探测 / 降级
│       ├── embeddings.py      # ollama 嵌入 + 离线 hash 嵌入（测试用）
│       ├── vectorstore.py     # Chroma 封装
│       └── versions.py        # 版本号解析与 +1
├── data/                      # chroma 向量库、uploads、history.db、library.db、update_history.jsonl
├── logs/                      # 运行日志
├── examples/                  # 示例资料（含一组"旧方案 → 新方案"更迭素材）
├── scripts/                   # e2e 与运维脚本
└── tests/                     # pytest 用例
```

## 测试

```powershell
# 单元 + 无头 UI 测试（不需要 Ollama，用 hash 嵌入）
& ".\.venv\Scripts\python.exe" -m pytest tests/ -q

# 端到端（需要 Ollama：qwen2.5:7b + bge-m3）
.\scripts\run_all_e2e.ps1      # 一次跑完三条，数据目录隔离到 logs\_e2e_data，不污染真实库

# 或单独跑
& ".\.venv\Scripts\python.exe" scripts\e2e_phase1.py   # 入库 + 检索 + 问答
& ".\.venv\Scripts\python.exe" scripts\e2e_phase2.py   # Streamlit 前端 + 对话历史 + 模型源
& ".\.venv\Scripts\python.exe" scripts\e2e_phase3.py   # 技术更迭 REPLACE / KEEP_OLD
```

## 已知限制

- **首字响应 5~9 秒**（本地 qwen2.5:7b，PRD 目标 <5s）；换更小模型或云端源可改善。
- **云端源未做真实调用验证**：需要 `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` 才能验证；
  缺 Key 时会明确报错并按 `ENABLE_FALLBACK` 降级到本地。
- **换嵌入模型必须重新入库**：Chroma 集合名带模型标识（`pka_<embedding_model>`），旧集合不会被新模型复用。
- 扫描版 PDF（无文字层）无法提取文本；PDF 字体缺字会被检测并以 WARNING 提示，但不会自动 OCR。
- `chromadb` 0.6.3 与新版 `posthog` 不兼容，会打印 `Failed to send telemetry event ...` 噪点日志，不影响功能。

## 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 提问提示「模型调用失败」 | Ollama 未启动或模型未下载：`ollama serve`、`ollama list` |
| 入库成功但检索不到 | 换了 `EMBEDDING_MODEL` 但没重新入库；或 `TOP_K` 太小 |
| `ollama pull` 超时 | 到 `registry.ollama.ai` 网络不通，换镜像 / 代理，或改用已装模型 |
| 更迭评估总是 KEEP_OLD | 库中无同主题旧内容时会走 `INGEST`；有旧内容但模型判定新方案风险高时会拦截，可换更强模型 |

## 文档

- `docs/开发日志.md`：分阶段完成记录、测试证据、踩坑与修复。
- `docs/_prd_extracted.txt`：PRD 原文提取（便于比对需求）。
