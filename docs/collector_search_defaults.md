# 爬虫默认搜索参数（Bilibili / 小红书）

本文档汇总 Stage 1 两个采集器的**默认搜索参数**，用于快速确认当前运行行为。

## 1) Bilibili（`--collect-bili`）

### CLI 默认参数（`src/main.py`，XHS）

- `--bili-order`: `totalrank`
- `--bili-pages`: `1`
- `--bili-time-start`: 默认注入为“昨天”（`YYYY-MM-DD`）
- `--bili-time-end`: 默认注入为“今天”（`YYYY-MM-DD`）

说明：在通过 CLI 执行 `--collect-bili` 时，如果你不手动传 `--bili-time-start/--bili-time-end`，程序会自动注入日期范围（昨天到今天）。

### 采集器函数默认参数（`src/ingest/bilibili_collector.py`）

- `order`: `"totalrank"`
- `time_start`: `None`
- `time_end`: `None`
- `max_pages`: `1`
- `page_size`: `42`

说明：函数本身不强制日期；“日期注入”发生在 CLI 层（`src/main.py`）。

## 2) 小红书（`--collect-xhs`）

### CLI 默认参数（`src/main.py`）

- `--xhs-sort-by`: `最多评论`
- `--xhs-publish-time`: `一天内`
- `--xhs-note-type`: `不限`
- `--xhs-max-items`: 默认不传（由配置文件控制）

说明：CLI 默认目标是"最近一天内 + 评论最多"。`sort_by`、`publish_time`、`note_type` 全部直接透传到 MCP 的 `search_feeds.filters`，由 MCP 端去 UI 上完成排序与筛选；本地不再做二次过滤或排序。

### 采集器函数默认参数（`src/ingest/xhs_collector.py`）

- `filters`: `None`（由 CLI 传入）
- `max_items`: `None`（最终回退到 `settings.XHS_MAX_ITEMS`）

## 3) 你关心的两个判断

### 小红书是否默认"一天内最多评论"？

是。当前默认通过 MCP `search_feeds.filters` 传入：

- 时间：`一天内`
- 排序：`最多评论`

如果要改为综合排序，可显式传 `--xhs-sort-by 综合`；时间仍默认保持 `一天内`。

### Bilibili 是否注入了搜索日期？

是（在 CLI 路径下）。默认会自动注入：

- `time_start = 昨天`
- `time_end = 今天`

如果你绕过 CLI 直接调用 `collect_bilibili()` 且不传时间参数，则不会自动注入日期。

## 4) Raw JSONL 字段策略（当前实现）

为避免每行重复信息，Stage 1 写入 `data/staging/raw/` 时：

- 不再在每条记录里写 `platform`
- 不再在每条记录里写 `fetched_at`

原因：

- 同一文件内抓取时间一致，已由文件名时间戳表达（如 `xhs_20260406_223626.jsonl`）
- 平台信息已由文件名前缀表达（如 `xhs_` / `bili_`）
