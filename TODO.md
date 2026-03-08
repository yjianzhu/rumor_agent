# Rumor Agent - 项目开发 TODO

> 更新时间：2026-02-27
>
> **项目目标**：构建一个智能辟谣 Agent 系统，能够自动爬取网络谣言案例、存入数据库，并通过 LLM Agent 完成事实核查、分类与分析，最终输出结构化的辟谣结果。

---

## 阶段总览

| 阶段 | 描述 | 状态 |
|------|------|------|
| Phase 0 | 基础设施 & 数据库 | ✅ 已完成 |
| Phase 1 | 数据库接入层（CRUD） | 🚧 进行中 |
| Phase 2 | 爬虫 Agent（案例采集） | ⬜ 未开始 |
| Phase 3 | 主程序流程串联 | ⬜ 未开始 |
| Phase 4 | LLM 分析核心（可选扩展） | ⬜ 未开始 |

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

## Phase 1：数据库接入层（CRUD Repository）🚧

> **目标**：封装对数据库的增删改查操作，供爬虫模块和主程序调用，避免业务逻辑直接操作 Session。

### 1.1 创建 `src/db/crud.py`
- [ ] `create_rumor(db, rumor_data: dict) -> Rumor`
  - 插入一条谣言记录；若 `slug` 已存在则跳过（幂等写入）
- [ ] `get_rumor_by_slug(db, slug: str) -> Rumor | None`
  - 按 slug 查询，用于判断重复
- [ ] `get_rumor_by_id(db, rumor_id: UUID) -> Rumor | None`
- [ ] `list_rumors(db, status=None, limit=50, offset=0) -> list[Rumor]`
  - 支持按状态过滤、分页
- [ ] `update_rumor_status(db, rumor_id: UUID, status: RumorStatus) -> Rumor`
- [ ] `delete_rumor(db, rumor_id: UUID) -> bool`
- [ ] `create_analysis_result(db, rumor_id: UUID, result_data: dict) -> AnalysisResult`
- [ ] `get_analysis_by_rumor_id(db, rumor_id: UUID) -> AnalysisResult | None`

### 1.2 创建 `src/db/schemas.py`（数据验证 Schema）
- [ ] 定义 `RumorCreate` — 创建谣言时所需字段（title, summary, rumor_content, source_urls 等）
- [ ] 定义 `RumorOut` — 返回谣言时的展示字段
- [ ] 定义 `AnalysisResultCreate` — 创建分析结果所需字段
- [ ] 定义 `AnalysisResultOut` — 返回分析结果的展示字段

### 1.3 测试数据库接入
- [ ] 在 `scripts/test_crud.py` 中编写简单测试
  - 测试插入、查询、更新、去重逻辑

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

## Phase 3：主程序流程串联 ⬜

> **目标**：整合爬虫 Agent 与数据库接入层，提供统一的命令行入口，支持完整的"爬取 → 存储 → 查询"流程。

### 3.1 重构 `src/main.py`
- [ ] 添加命令行参数解析（使用 `argparse`）
  - `--crawl` — 执行爬虫采集流程
  - `--source [piyao|qq_fact|all]` — 指定数据源
  - `--limit N` — 每个数据源最多爬取条数
  - `--list` — 列出数据库中现有谣言记录
  - `--analyze` — 触发 LLM 分析（Phase 4 扩展）
- [ ] 集成日志模块（`logging`），统一输出格式

### 3.2 配置管理扩展 `src/config.py`
- [ ] 添加 LLM API Key 配置（`GEMINI_API_KEY` / `OPENAI_API_KEY`）
- [ ] 添加爬虫相关配置（`CRAWL_DELAY`, `MAX_RETRIES`）
- [ ] 更新 `.env.example` 文件

### 3.3 完善日志系统
- [ ] `src/logger.py` — 统一日志配置
  - 输出到控制台 + 日志文件（`logs/rumor_agent.log`）
  - 支持 DEBUG / INFO / WARNING / ERROR 等级

### 3.4 端到端测试
- [ ] 运行完整流程：`python -m src.main --crawl --source all --limit 20`
- [ ] 验证数据库记录数量增加、字段完整性

---

## Phase 4：LLM 分析核心（扩展）⬜

> **目标**：基于 LLM（Gemini / OpenAI）对已采集的谣言进行事实核查、真假分类、可信度评分。

### 4.1 LLM 客户端集成
- [ ] `src/llm/client.py` — 封装 LLM API 调用
  - 支持 Gemini Pro / GPT-4
- [ ] `src/llm/prompts.py` — Prompt 模板管理
  - 事实核查 Prompt
  - 分类与评分 Prompt

### 4.2 分析器模块
- [ ] `src/analyzer/analyzer.py`
  - `analyze_rumor(rumor: Rumor) -> AnalysisResultCreate`
  - 调用 LLM 获取 `truthfulness_score`, `evidence`, `summary`
  - 将结果写入 `analysis_results` 表

### 4.3 批量分析
- [ ] 支持主程序通过 `--analyze` 参数触发对未分析记录的批量处理

---

## 目录结构规划（最终）

```
rumor_agent/
├── .env                        # 环境变量（不入 Git）
├── .env.example                # 环境变量模板
├── init_db.py                  # 数据库初始化脚本（✅已完成）
├── requirements.txt            # 项目依赖
├── TODO.md                     # 本文件
├── README.md                   # 项目说明
├── logs/                       # 日志输出目录
├── scripts/
│   ├── check_database.py       # 数据库连接验证（✅已完成）
│   ├── test_crud.py            # CRUD 操作测试
│   └── run_crawler.py          # 爬虫独立运行脚本
└── src/
    ├── config.py               # 配置管理（✅已完成）
    ├── logger.py               # 日志配置
    ├── main.py                 # 主程序入口（⬜待重构）
    ├── db/
    │   ├── base.py             # SQLAlchemy 基础（✅已完成）
    │   ├── models.py           # ORM 模型（✅已完成）
    │   ├── crud.py             # CRUD 操作层（⬜待创建）
    │   └── schemas.py          # 数据 Schema（⬜待创建）
    ├── crawler/
    │   ├── __init__.py
    │   ├── base_crawler.py     # 基础爬虫抽象类（⬜待创建）
    │   ├── piyao_crawler.py    # 辟谣网爬虫（⬜待创建）
    │   ├── qq_fact_crawler.py  # 腾讯较真爬虫（⬜待创建）
    │   ├── agent.py            # 爬虫 Agent 控制器（⬜待创建）
    │   └── utils.py            # 工具函数（⬜待创建）
    ├── analyzer/
    │   └── analyzer.py         # LLM 分析器（⬜待创建，Phase 4）
    └── llm/
        ├── client.py           # LLM 客户端（⬜待创建，Phase 4）
        └── prompts.py          # Prompt 模板（⬜待创建，Phase 4）
```

---

## 当前下一步行动

1. **立即开始 Phase 1**：创建 `src/db/crud.py` 和 `src/db/schemas.py`
2. **调研爬虫目标**：访问辟谣相关网站，分析页面结构，确定 Phase 2 的数据源
3. **更新 `requirements.txt`**：添加 `httpx`, `beautifulsoup4`, `lxml` 等爬虫依赖
