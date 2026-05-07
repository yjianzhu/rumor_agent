# Rumor Agent

人工辅助辟谣平台。LLM 负责采集与归纳争议事件，最终的真假裁决（FAKE / TRUE / OUTDATED）由运营人员通过 Web 审核界面完成。

## 定位

**这不是自动事实核查系统**。LLM 仅做两件事：

- 把社媒内容归纳为「争议事件」（谁、说了什么、来源 URL）
- 对人工已写好的辟谣文档做结构化提取

真假判定、辟谣文撰写、是否发布都由人工通过 Web 界面完成。

## 数据流

```
[采集]                           [Triage LLM]                [入库]
collect-bili / collect-xhs  →  triage-jsonl          →    import-candidate-jsonl
  raw JSONL                      candidate JSONL            DB（status=DUBIOUS）
                                                                    ↓
                                                            [人工审核 Web UI]
                                                              status / truth_content / is_published
```

旁路：`import-md`（导入历史人工辟谣案例）、`import-jsonl`（结构化数据直接导入）。

## 数据模型

### `rumors`
`id (UUID)`, `title`, `slug` (unique), `summary`, `rumor_content`, `truth_content`,
`status` (FAKE / TRUE / DUBIOUS / OUTDATED), `tags TEXT[]`, `media_files JSONB`,
`source_urls TEXT[]`, `embedding vector(2560)` (deferred), `view_count`, `is_published`,
`created_at`, `updated_at`

### `analysis_results`
`id`, `rumor_id` (FK), `truthfulness_score` (0.0–1.0), `summary`, `evidence`, `model_name`, `created_at`

### `MediaItem`（在 `media_files` JSONB 里）
```json
{"type": "image|video", "path": "<slug>/xxx.jpg 或 URL", "label": "rumor|debunk|source", "caption": ""}
```
> `path` 对图片是「相对 `MEDIA_DIR`」的路径（无 `media/` 前缀），模板渲染为 `/media/{{ path }}`，由 FastAPI 静态挂载映射到磁盘 `MEDIA_DIR`。视频直接存完整 URL。

## 前置条件

- Python 3.11+
- PostgreSQL（启用 `uuid-ossp` + `pgvector`）
- `uv` 作为 Python 包/运行管理器

## 安装

```bash
uv sync
```

## 初始化数据库

PostgreSQL 扩展需要 superuser 权限装一次：

```bash
psql -U postgres -c "CREATE DATABASE rumor_agent_db OWNER rad_user;"
psql -U postgres -d rumor_agent_db -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"; CREATE EXTENSION IF NOT EXISTS vector;"
```

之后业务用户即可建表：

```bash
uv run python init_db.py
```

> 当前阶段不使用 Alembic。schema 变更走 drop & recreate 流程。

## 命令

### 采集（Stage 1）

```bash
# Bilibili: 默认昨天到今天，按总分排序，min_play=100（来自 config）
uv run python -m src.main --collect-bili 雷军
uv run python -m src.main --collect-bili        # 用 config.toml [collect].keywords 批量

# 小红书: 需要本地 xiaohongshu-mcp 已登录
uv run python -m src.main --collect-xhs 小米
```

输出：`data/staging/raw/{bili,xhs}_<timestamp>.jsonl`

### Triage 归纳争议事件（Stage 2）

```bash
uv run python -m src.main --triage-jsonl data/staging/raw/bili_*.jsonl
```

输出：`data/staging/candidates/candidate_<timestamp>.jsonl`

候选事件会保留通过白名单校验的 `source_urls`，并附带 `source_refs`（URL、平台、原始 bvid/note_id 等）用于回看 raw 记录。

### 入库（Stage 3）

```bash
uv run python -m src.main --import-candidate-jsonl data/staging/candidates/candidate_*.jsonl
```

每条争议事件 → 一行 `Rumor`，状态 DUBIOUS、未发布。

### 一键流水线（适合定时调度）

```bash
uv run python -m src.main --run-pipeline
```

按 `[collect].keywords` 逐个跑 `collect-bili + collect-xhs`，汇总 raw 文件后跑 triage，最后 import-candidate 入库。任一关键词的任一平台失败仅记 warning 不阻塞其他；triage 失败时不会 import。

#### Linux: crontab 每天 8 点跑

```cron
0 8 * * * cd /path/to/rumor_agent && /path/to/uv run python -m src.main --run-pipeline >> logs/pipeline.log 2>&1
```

#### Windows: Task Scheduler 每天 8 点跑

```powershell
schtasks /Create /TN "RumorAgentPipeline" /TR "cmd /c cd /d C:\path\to\rumor_agent && uv run python -m src.main --run-pipeline >> logs\pipeline.log 2>&1" /SC DAILY /ST 08:00
```

> XHS 采集依赖 `xiaohongshu-mcp` 服务在线且 cookie 有效。失败时整个 pipeline 不会终止，但当天的 XHS 数据会缺失——务必加监控告警观察 `logs/pipeline.log` 的 `Pipeline xhs: ... failed` 行。

### 旁路：直接导入

```bash
# 结构化 JSONL（含 status/tags/source_urls 等字段，无需 LLM）
uv run python -m src.main --import-jsonl data.jsonl

# Markdown 经 LLM 结构化（用于回填历史人工辟谣文档）
uv run python -m src.main --import-md path/to/rumor.md
```

通用 flag：`--limit N` `--dry-run`（与真实导入走同一去重路径，跳过 embedding 调用） `--model MODEL`

### Web 界面

```bash
uv run uvicorn src.api.app:app --reload
```

- `/` — 列表，默认「待审核」（`is_published=false`），可切换「已发布」/「全部」，支持搜索 / 状态筛选 / 标签筛选
- `/rumors/{slug}` — 详情，底部含审核表单：status、truth_content、is_published
- `/api/...` — JSON API（`GET /api/rumors/{slug}`、`PATCH /api/rumors/{slug}`、`GET /api/stats`、`GET /api/tags`）
- `/docs` — OpenAPI 交互文档

### 测试

```bash
uv run pytest                    # 全量（需要 DB）
uv run pytest -k "not db"        # 仅单元测试
```

## 配置

通过仓库根目录 `config.toml`：

```toml
[database]
user = "rad_user"
password = "..."
host = "localhost"
port = 5432
name = "rumor_agent_db"

[llm]
temperature = 0.0
max_retries = 3
max_input_chars = 30000

[[llm.endpoints]]                # 可配多组，按顺序 fallback
api_key = "..."
api_base = "https://api.example.com/v1"
model = "gpt-..."

[embedding]
model = "Qwen/Qwen3-Embedding-4B"
dim = 2560
dedup_similarity_threshold = 0.92

[[embedding.endpoints]]
api_key = "..."
api_base = "https://..."
model = "Qwen/Qwen3-Embedding-4B"

[collect]
keywords = ["小米", "雷军"]      # --collect-* 不带 KEYWORD 时使用
bili_min_play = 100

[general]
media_dir = "media"
import_batch_size = 50
```

## 目录结构

```
rumor_agent/
├── config.toml                # 配置
├── init_db.py                 # 建表脚本（drop & recreate 流程）
├── pyproject.toml             # 依赖 + pytest 配置（uv 管理）
├── src/
│   ├── main.py                # CLI 入口
│   ├── config.py              # config.toml 加载
│   ├── logger.py
│   ├── media.py               # 媒体文件存储（路径归一化）
│   ├── embedding.py           # 嵌入向量调用
│   ├── api/
│   │   ├── app.py             # FastAPI app
│   │   ├── page_routes.py     # 页面（/、/rumors/{slug}）
│   │   ├── partial_routes.py  # htmx 局部刷新
│   │   ├── api_routes.py      # JSON API（含 PATCH 审核）
│   │   ├── deps.py            # 共享依赖、view 解析
│   │   └── templates/         # Jinja2 模板
│   ├── ingest/
│   │   ├── bilibili_collector.py
│   │   ├── xhs_collector.py
│   │   ├── triage.py          # LLM 归纳争议事件
│   │   └── readers.py
│   ├── analyzer/
│   │   └── analyzer.py        # MD 结构化分析 + 后处理
│   ├── llm/
│   │   └── client.py          # 统一 LLM 调用：chat() + analyze_structured()
│   └── db/
│       ├── base.py            # SQLAlchemy Engine / Session
│       ├── models.py          # ORM
│       ├── schemas.py         # Pydantic（含 RumorReviewIn）
│       └── crud.py            # CRUD + 语义去重
├── tests/                     # pytest
├── docs/
└── data/staging/{raw,candidates}/
```
