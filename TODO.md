# Rumor Agent - 项目开发 TODO

> 更新时间：2026-04-06
>
> **项目目标**：构建一个智能辟谣 Agent 系统，能够自动爬取网络谣言案例、存入数据库，并通过 LLM Agent 完成事实核查、分类与分析，最终输出结构化的辟谣结果。

---

## 阶段总览

| 阶段 | 描述 | 状态 |
|------|------|------|
| Phase 0 | 基础设施 & 数据库 | ✅ 已完成 |
| Phase 1 | 数据库接入层（CRUD） | ✅ 已完成 |
| Phase 2 | 多平台采集（XHS + Bilibili） | ✅ 已完成（持续优化） |
| Phase 3 | 主程序流程串联 | ✅ 已完成 |
| Phase 4 | LLM 分析核心 | ✅ 基本完成（批量分析待实现） |

---

## Phase 0：基础设施 & 数据库 ✅

- [x] 初始化 Python 项目结构（`src/`, `scripts/`）
- [x] 配置 `.env` 环境变量（`DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`）
- [x] 实现 `src/config.py` — 读取配置，生成 `DATABASE_URL`
- [x] 实现 `src/db/base.py` — SQLAlchemy Engine、Session、`get_db()` 依赖
- [x] 实现 `src/db/models.py` — `Rumor` 表 & `AnalysisResult` 表 ORM 模型
- [x] 实现 `init_db.py` — 启用 `uuid-ossp` 扩展，`create_all()` 建表
- [x] 验证数据库连接（`scripts/check_database.py`）

---

## Phase 1：数据库接入层（CRUD Repository）✅

> **目标**：封装对数据库的增删改查操作，供爬虫模块和主程序调用，避免业务逻辑直接操作 Session。

### 1.1 `src/db/crud.py`
- [x] `create_rumor(db, data: RumorCreate) -> Rumor` — slug 唯一性校验
- [x] `get_rumor_by_slug(db, slug: str) -> Rumor | None`
- [x] `get_rumor_by_id(db, rumor_id: UUID) -> Rumor | None`
- [x] `list_rumors(db, status, tag, is_published, offset, limit)` — 支持状态/标签/发布过滤 + 分页
- [x] `count_rumors(db) -> int`
- [x] `update_rumor(db, rumor_id, data: RumorUpdate)` — 任意字段更新
- [x] `delete_rumor(db, rumor_id: UUID) -> bool`
- [x] `create_analysis_result(db, data: AnalysisResultCreate) -> AnalysisResult`
- [x] `get_analysis_by_rumor_id(db, rumor_id: UUID) -> AnalysisResult | None`

### 1.2 `src/db/schemas.py`
- [x] `RumorCreate` / `RumorUpdate` / `RumorOut` — 谣言增改查 Schema
- [x] `RumorDirectIn` — JSONL 直接导入 Schema（含可选 analysis 字段）
- [x] `_RumorSampleIn` — 内部 MD → LLM 输入包装
- [x] `StructuredRumorAnalysis` — LLM 结构化输出 Schema
- [x] `AnalysisResultCreate` / `AnalysisResultOut`

### 1.3 测试
- [x] `tests/test_import_pipeline.py` — 13 个测试覆盖 JSONL/MD 导入 + DB 集成

---

## Phase 2：多平台采集（XHS + Bilibili）✅

> **目标**：从社媒平台采集候选内容（当前已接入 Bilibili / 小红书），产出统一 raw JSONL 供后续 triage/fusion/import 使用。

### 2.1 已完成能力
- [x] Bilibili 采集器：`src/ingest/bilibili_collector.py`
  - 关键词检索、排序、分页、日期范围（CLI 默认“昨天到今天”）
  - 输出 `data/staging/raw/bili_*.jsonl`
- [x] 小红书采集器：`src/ingest/xhs_collector.py`
  - MCP 登录检查、搜索、详情补全（description）
  - 支持 `sort_by / publish_time / note_type` 过滤
  - 输出 `data/staging/raw/xhs_*.jsonl`
- [x] Stage 1 CLI 接入：`src/main.py`
  - `--collect-bili KEYWORD`
  - `--collect-xhs KEYWORD`
- [x] 测试覆盖
  - `tests/test_bili_collector.py`
  - `tests/test_xhs_collector.py`
- [ ] 添加评论获取功能，可能正文和视频描述都没有关键信息，从评论区可以获取TODO

### 2.2 现状约定（raw 文件）
- [x] `raw` 每行不再重复写 `platform` / `fetched_at`
- [x] 平台与时间由文件名表达（如 `bili_20260406_222916.jsonl`）
- [x] 规则文档：`docs/collector_search_defaults.md`

### 2.3 下一步优化（Phase 2 持续项）
- [ ] 去重与清洗增强（空标题/空作者/重复 note_id、bvid）
- [ ] 主题相关性粗筛（降低低相关噪声）
- [ ] 采集质量指标（空内容率、可研判率、去重后留存率）
- [ ] 增加更多平台适配器（在 `src/ingest/` 扩展）

---

## Phase 3：主程序流程串联 ✅

> **目标**：整合分析流水线与数据库接入层，提供统一的命令行入口。

### 3.1 `src/main.py` CLI
- [x] `--import-jsonl FILE` — JSONL 直接导入（无需 LLM）
- [x] `--import-md FILE` — Markdown 经 LLM 分析后导入
- [x] `--limit N` — 限制处理条数
- [x] `--dry-run` — 预览模式，不写库
- [x] `--model MODEL` — 覆盖默认 LLM 模型
- [x] Slug 去重（base slug + hash suffix 回退）
- [x] 事务安全（失败时 `cleanup_rumor_bundle` 回滚）
- [x] 导入统计（processed / succeeded / failed / duplicates）

### 3.2 配置管理 `src/config.py`
- [x] `LLM_API_KEY` / `LLM_API_BASE` — LLM 凭据（通用，不锁定 OpenAI）
- [x] `LLM_MODEL` — 默认 `openai/gpt-4o-mini`
- [x] `LLM_TEMPERATURE` — 默认 0.0
- [ ] 爬虫相关配置（`CRAWL_DELAY`, `MAX_RETRIES`）— 待 Phase 2

### 3.3 日志系统 `src/logger.py`
- [x] Console + 文件日志（`logs/rumor_agent.log`）
- [x] 格式：`[TIMESTAMP] [LEVEL] module: message`

### 3.4 端到端测试
- [x] 13 个测试全部通过（JSONL 单元 + MD 单元 + DB 集成）
- [ ] 真实 LLM 端到端测试（需 API Key）

---

## Phase 4：LLM 分析核心 ✅（批量分析待实现）

> **目标**：基于 LLM 对谣言进行结构化提取、真假分类、可信度评分。

### 4.1 LLM 客户端 `src/llm/client.py`
- [x] `AdkLlmClient` — Google ADK + LiteLLM 封装
- [x] 支持多模型（OpenAI / Gemini 等，通过 LiteLLM 路由）
- [x] 结构化输出：`_RumorSampleIn` → `StructuredRumorAnalysis`
- [x] Prompt 内嵌于 client.py（规则：不声称外部核查、evidence 仅引用输入文本）

### 4.2 分析器 `src/analyzer/analyzer.py`
- [x] `analyze_sample(sample)` — LLM 分析入口
- [x] `analyze_markdown(path)` — 读取 MD 文件并分析
- [x] `normalize_structured_analysis()` — 后处理（去重 tags、合并 URLs、verdict signal 校验）
- [x] `has_explicit_verdict_signal()` — 中英文关键词匹配，无信号强制 DUBIOUS
- [x] `slugify()` / `hash_suffix()` / `to_rumor_create()` 等工具函数

### 4.3 批量分析
- [ ] 支持 `--analyze` 参数对未分析记录批量处理

---

## 目录结构（当前实际）

```
rumor_agent/
├── .env                        # 环境变量（不入 Git）
├── init_db.py                  # 数据库初始化脚本
├── requirements.txt            # 项目依赖
├── conftest.py                 # pytest 根配置
├── TODO.md / README.md / AGENTS.md
├── logs/                       # 日志输出目录
├── examples/
│   └── 小米景明汽车谣言.md     # 示例谣言 MD
├── scripts/
│   ├── check_database.py       # 数据库连接验证
│   ├── make_jsonl.py           # MD → JSONL 转换
│   └── verify_import.py        # 导入验证
├── tests/
│   └── test_import_pipeline.py # 导入流水线测试（13 个）
└── src/
    ├── config.py               # 配置管理 ✅
    ├── logger.py               # 日志系统 ✅
    ├── main.py                 # CLI 入口 ✅
    ├── db/
    │   ├── base.py             # SQLAlchemy 基础 ✅
    │   ├── models.py           # ORM 模型 ✅
    │   ├── schemas.py          # Pydantic Schema ✅
    │   └── crud.py             # CRUD 操作层 ✅
    ├── analyzer/
    │   └── analyzer.py         # 分析器 + 后处理 ✅
    └── llm/
        └── client.py           # ADK + LiteLLM 客户端 ✅
```

---

## 当前下一步行动

1. **采集质量优化**：完善 raw 清洗、去重、相关性评分
2. **批量分析**：实现 `--analyze` 参数对已入库但未分析的记录进行批量 LLM 处理
3. **小改进**：`src/db/base.py` 中 `declarative_base()` 迁移到 SQLAlchemy 2.0 `DeclarativeBase`
