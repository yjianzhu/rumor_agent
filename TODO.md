# Rumor Agent - 项目开发 TODO

> 更新时间：2026-03-10
>
> **项目目标**：构建一个智能辟谣 Agent 系统，能够自动爬取网络谣言案例、存入数据库，并通过 LLM Agent 完成事实核查、分类与分析，最终输出结构化的辟谣结果。

---

## 阶段总览

| 阶段 | 描述 | 状态 |
|------|------|------|
| Phase 0 | 基础设施 & 数据库 | ✅ 已完成 |
| Phase 1 | 数据库接入层（CRUD） | ✅ 已完成 |
| Phase 2 | 爬虫 Agent（案例采集） | ⬜ 未开始 |
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

## Phase 2：爬虫 Agent（案例采集）⬜

> **目标**：编写一个 Agent，能够从主流辟谣/事实核查网站自动爬取谣言案例，解析结构化字段，并调用 Phase 1 的 CRUD 层写入数据库。

### 2.1 确定目标数据源
- [ ] 整理可爬取的辟谣网站列表，例如：
  - [较真](https://vp.fact.qq.com/) — 腾讯事实核查平台
  - [谣言终结者](https://www.piyao.org.cn/) — 官方辟谣平台
  - 其他：微博超话、人民网辟谣专区等
- [ ] 分析目标网页结构，确定爬取策略（静态 HTML / 动态 JS 渲染 / API 接口）

### 2.2 项目依赖更新 `requirements.txt`
- [ ] 添加爬虫相关依赖：
  - `httpx` 或 `requests` — HTTP 请求
  - `playwright` 或 `selenium` — 动态页面渲染（如需）
  - `beautifulsoup4` + `lxml` — HTML 解析
  - `langchain` 或 `google-generativeai` — LLM 辅助解析（可选）

### 2.3 创建 `src/crawler/` 模块
- [ ] `src/crawler/__init__.py`
- [ ] `src/crawler/base_crawler.py` — 基础爬虫抽象类
  - 定义接口 `fetch_list()` → 获取案例列表页
  - 定义接口 `fetch_detail(url)` → 解析单条详情页
  - 定义接口 `parse_to_schema(raw_data) -> RumorCreate` → 转换为标准 Schema
- [ ] `src/crawler/piyao_crawler.py` — 官方辟谣平台爬虫（继承 `BaseCrawler`）
- [ ] `src/crawler/qq_fact_crawler.py` — 腾讯较真平台爬虫（继承 `BaseCrawler`）
- [ ] `src/crawler/utils.py` — 公共工具函数
  - `slugify(title: str) -> str` — 从标题生成 URL slug
  - `clean_html(html: str) -> str` — 清理 HTML 标签
  - `extract_source_urls(html) -> list[str]` — 提取来源链接

### 2.4 爬虫 Agent 主控制器
- [ ] `src/crawler/agent.py` — `CrawlerAgent` 类
  - `run(sources: list[str], max_per_source: int = 50)` — 批量运行爬虫
  - 调用 CRUD 层写入数据库（幂等，已存在则跳过）
  - 记录爬取进度与错误日志

### 2.5 测试爬虫
- [ ] `scripts/run_crawler.py` — 爬虫独立运行脚本（单次测试）
- [ ] 验证 5~10 条数据能正确写入数据库

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

1. **Phase 2 — 爬虫 Agent**：确定目标数据源，开始实现采集模块
2. **批量分析**：实现 `--analyze` 参数对已入库但未分析的记录进行批量 LLM 处理
3. **小改进**：`src/db/base.py` 中 `declarative_base()` 迁移到 SQLAlchemy 2.0 `DeclarativeBase`
