# Rumor Agent

网络谣言检测、追踪与分析系统。利用 LLM 评估谣言真实性，聚合证据，提供自动化辟谣。

## 架构

| 层 | 说明 |
|---|------|
| **Ingestion** | JSONL 直接导入 / Markdown + LLM 分析导入 |
| **Data** | PostgreSQL + SQLAlchemy ORM，JSONB 存储 tags / media / urls |
| **Analysis** | LiteLLM 调用 LLM 做结构化谣言分析 |
| **Media** | 本地图片存储（`media/<slug>/`），视频以 URL 形式记录 |

## 数据模型

### rumors
`id` (UUID), `title`, `slug`, `summary`, `rumor_content`, `truth_content`,
`status` (FAKE / TRUE / DUBIOUS / OUTDATED), `tags`, `media_files` (JSONB → `MediaItem[]`),
`source_urls`, `view_count`, `is_published`, `created_at`, `updated_at`

### analysis_results
`id`, `rumor_id` (FK → rumors), `truthfulness_score` (0.0–1.0),
`summary`, `evidence`, `model_name`, `created_at`

### MediaItem 结构
```json
{"type": "image|video", "path": "media/<slug>/xxx.jpg 或 URL", "label": "rumor|debunk|source", "caption": ""}
```

## 目录结构
```
rumor_agent/
├── pyproject.toml        # 项目配置 & pytest 设置
├── requirements.txt
├── init_db.py            # 数据库建表
├── src/
│   ├── config.py         # 配置（DB / LLM / MEDIA_DIR）
│   ├── main.py           # CLI 入口（--import-jsonl / --import-md）
│   ├── media.py          # 图片存储工具
│   ├── logger.py         # 日志配置
│   ├── analyzer/
│   │   └── analyzer.py   # LLM 分析逻辑
│   ├── llm/
│   │   └── client.py     # LiteLLM 封装
│   └── db/
│       ├── base.py       # SQLAlchemy Engine & Session
│       ├── models.py     # ORM models
│       ├── schemas.py    # Pydantic schemas（含 MediaItem）
│       └── crud.py       # CRUD 操作
├── tests/
│   ├── conftest.py       # 共享 fixtures & helpers
│   ├── test_import_pipeline.py
│   └── test_media.py
├── scripts/
│   ├── make_jsonl.py
│   └── verify_import.py
└── examples/
```

## 使用

### 前置条件
- Python 3.11+
- PostgreSQL（启用 `uuid-ossp` 扩展）

### 安装
```bash
pip install -r requirements.txt
```

### 初始化数据库
```bash
python init_db.py
```

### 导入数据
```bash
# JSONL 直接导入（不需要 LLM）
python -m src.main --import-jsonl data.jsonl
python -m src.main --import-jsonl data.jsonl --dry-run   # 预览
python -m src.main --import-jsonl data.jsonl --limit 10  # 限制条数

# Markdown 通过 LLM 分析导入
python -m src.main --import-md rumor.md
python -m src.main --import-md rumor.md --model openai/gpt-4o
```

### 运行测试
```bash
python -m pytest                    # 全量（需要 DB）
python -m pytest -k "not db"        # 仅单元测试
```

## 配置

通过 `.env` 文件或环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_USER` | `postgres` | 数据库用户 |
| `DB_PASSWORD` | `password` | 数据库密码 |
| `DB_HOST` | `localhost` | 数据库地址 |
| `DB_PORT` | `5432` | 数据库端口 |
| `DB_NAME` | `rumor_agent` | 数据库名 |
| `LLM_API_KEY` | — | LLM API 密钥 |
| `LLM_API_BASE` | — | LLM API 地址 |
| `LLM_MODEL` | `openai/gpt-4o-mini` | 默认模型 |
| `MEDIA_DIR` | `media` | 媒体文件存储目录 |
