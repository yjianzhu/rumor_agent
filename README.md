# Rumor Agent

人工辅助辟谣平台。LLM 负责采集线索归纳和历史案例结构化；新采集线索的真假裁决由运营人员审核，历史人工辟谣 Markdown 可在结构化后直接形成完整公开案例。

## 定位

**这不是自动事实核查系统**。LLM 仅做两件事：

- 把社媒内容归纳为「争议事件」（谁、说了什么、来源 URL）
- 对人工已写好的辟谣文档做结构化提取

新采集线索的真假判定、辟谣文撰写、是否发布由人工通过 Web 界面完成。历史 Markdown 导入只抽取人工已经写好的谣言与辟谣内容，不做新的事实核查；若文档内已有明确结论和辟谣内容，则自动发布为完整案例。

## 数据流

```
[采集]                           [Triage LLM]                [入库]
collect-bili / collect-xhs  →  triage-jsonl          →    import-candidate-jsonl
  raw JSONL                      candidate JSONL            DB（status=DUBIOUS）
                                                                    ↓
                                                            [人工审核 Web UI]
                                                              status / truth_content / is_published

[历史人工辟谣 Markdown]       [Structured LLM]             [入库]
import-md                 →  结构化案例 JSON       →    DB（有明确辟谣内容时自动发布）
```

旁路：`import-md`（导入历史人工辟谣案例）、`import-jsonl`（结构化数据直接导入）。

## LLM 处理格式

项目有两条 LLM 链路，输出格式不同，不能混用。

### 1. 爬虫数据 → 争议事件候选

`collect-bili` / `collect-xhs` 产出的 raw JSONL 是社交媒体搜索结果，包含 `title`、`description`、`url`、`author`、`rank_meta`、`comments` 等字段。`triage-jsonl` 会先做轻量噪声过滤，再把剩余记录交给 LLM 合并为“争议事件候选”。

LLM 在这条链路中只做归纳，不做真假裁决。它需要输出 JSON 数组，每个元素固定为：

```json
{
  "title": "争议点标题，短而具体",
  "content": "2-5句争议摘要，保留核心主张并尽量归因到平台和作者",
  "source_urls": ["只允许使用输入中出现过的URL"],
  "controversy_type": "安全|质量|性能|价格|营销宣传|合规法律|售后服务|其他"
}
```

后处理会过滤 LLM 编造的 URL，并把可追溯的 `source_refs` 附加到 candidate JSONL。随后 `import-candidate-jsonl` 把每条候选写入 `rumors`：`status=DUBIOUS`、`is_published=false`、`summary=content`、`rumor_content=content`。这类数据进入后台待审核。

### 2. 历史 Markdown → 完整谣言案例

`import-md` 用于导入人工已经写好的历史辟谣文档。推荐目录：

```text
data/import/markdown/
```

Markdown 中的谣言内容应已经包含时间、人物、事件等基本信息。LLM 在这条链路中只把文档整理成数据库结构，不做外部核查。它需要输出一个匹配 `StructuredRumorAnalysis` 的 JSON 对象：

```json
{
  "title": "短标题",
  "summary": "一句话概括",
  "rumor_content": "只包含原始传言主张，保留时间、人物、事件等关键信息",
  "truth_content": "如果原文包含辟谣、真相、事实核查或总结，则整理到这里；否则为null",
  "status": "FAKE|TRUE|OUTDATED|DUBIOUS",
  "tags": ["2-6个短标签"],
  "source_urls": ["只允许使用文档中已有URL"],
  "analysis_summary": "对文内核查逻辑的简短归纳",
  "truthfulness_score": 0.0,
  "evidence": "只能概括文档中可见的依据"
}
```

导入规则：

- `rumor_content` 使用 LLM 从 Markdown 中提取出的传言主张，不再保存整篇 Markdown 原文。
- `truth_content` 有内容且 `status != DUBIOUS` 时，导入后自动 `is_published=true`，直接成为公开案例。
- 没有明确辟谣内容或结论不明确时，仍以 `is_published=false` 进入后台。
- 图片仅支持 Markdown 本地图片引用 `![caption](path)`，会记录到 `media_files`。

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

## 数据迁移 / 备份恢复

迁移一套完整站点数据必须同时迁移两部分：

- PostgreSQL 数据库：`rumors`、`analysis_results`、embedding、JSONB 媒体引用等。
- 图片目录：默认是仓库根目录下的 `media/`，路径由 `config.toml` 的 `[general].media_dir` 控制。

数据库中不保存图片二进制，只保存相对 `MEDIA_DIR` 的路径，例如：

```json
{"type": "image", "path": "<slug>/xxx.jpg", "label": "rumor", "caption": "网传截图"}
```

前台访问时会渲染为 `/media/<slug>/xxx.jpg`，FastAPI 再映射到本机磁盘的 `MEDIA_DIR`。

### 1. 源机器备份

导出数据库：

```powershell
pg_dump -U rad_user -h localhost -p 5432 -d rumor_agent_db -Fc -f rumor_agent_db.dump
```

打包图片目录：

```powershell
Compress-Archive -Path media -DestinationPath media.zip
```

如果 `config.toml` 里改过 `media_dir`，请打包实际目录，而不是固定打包 `media/`。

### 2. 目标机器准备数据库

目标 PostgreSQL 必须具备两个扩展：

- `uuid-ossp`：生成 UUID 主键。
- `vector`：pgvector，用于 embedding 字段和语义去重。

先创建用户和数据库。若用户已存在，可跳过第一行：

```powershell
psql -U postgres -c "CREATE USER rad_user WITH PASSWORD 'your_password';"
psql -U postgres -c "CREATE DATABASE rumor_agent_db OWNER rad_user;"
```

再在目标库启用扩展：

```powershell
psql -U postgres -d rumor_agent_db -c "CREATE EXTENSION IF NOT EXISTS ""uuid-ossp""; CREATE EXTENSION IF NOT EXISTS vector;"
```

检查扩展是否齐全：

```powershell
psql -U postgres -d rumor_agent_db -c "SELECT extname FROM pg_extension WHERE extname IN ('uuid-ossp', 'vector');"
```

结果应同时包含 `uuid-ossp` 和 `vector`。如果 `vector` 报错不存在，需要先在目标 PostgreSQL 安装 pgvector，再执行 `CREATE EXTENSION`。

### 3. 目标机器恢复数据

恢复数据库：

```powershell
pg_restore -U rad_user -h localhost -p 5432 -d rumor_agent_db rumor_agent_db.dump
```

解压图片目录到项目根目录：

```powershell
Expand-Archive -Path media.zip -DestinationPath .
```

确保目标机器 `config.toml` 指向同一个图片根目录：

```toml
[general]
media_dir = "media"
```

如果图片放到独立磁盘，例如 `D:\rumor_media`，则配置：

```toml
[general]
media_dir = "D:\\rumor_media"
```

这种情况下，数据库里的 `media_files[].path` 不需要改；只要保持 `<slug>/<filename>` 这层相对路径在新的 `media_dir` 下存在即可。

### 4. 恢复后验证

检查数据库连接和记录数：

```powershell
uv run python -m src.main
```

启动 Web：

```powershell
uv run uvicorn src.api.app:app --reload
```

打开公开详情页，确认：

- 谣言记录能正常访问。
- `/media/<slug>/<filename>` 图片能打开。
- `config.toml` 的数据库账号、密码、库名和 `media_dir` 与目标环境一致。

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
