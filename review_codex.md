# Codex Review (2026-05-06)

当前代码框架已经形成完整闭环：采集 raw JSONL -> LLM triage 归纳争议事件 -> candidate 入库 -> Web 人工审核发布。项目定位也比较清楚：LLM 不做真假裁决，只负责归纳和结构化，最终 `FAKE / TRUE / DUBIOUS / OUTDATED` 由人工审核确认。

本次静态 review 后已运行：

```bash
uv run pytest -q
```

最新修复后已重新运行：

```bash
uv run pytest -q --basetemp J:\code_onedrive\rumor_agent\pytest_tmp -o cache_dir=J:\code_onedrive\rumor_agent\pytest_cache_tmp
```

结果：`106 passed`。测试创建的 `pytest_tmp` / `pytest_cache_tmp` 已清理。

## Findings

1. High: 媒体路径契约不一致，可能导致图片 URL 变成 `/media/media/...`。
   - 位置：`src/media.py:29`, `src/api/templates/partials/rumor_card.html:10`, `src/api/templates/partials/rumor_detail.html:39`
   - `save_image()` 返回 `media/<slug>/<filename>`，README/schema 也描述为存 `media/...`。
   - 但模板又拼接 `/media/{{ item.path }}`，如果 DB 中保存的是 `media/x.jpg`，实际页面会请求 `/media/media/x.jpg`。
   - 建议统一契约：DB 只存相对 media 根目录的路径，例如 `<slug>/<filename>`；模板负责加 `/media/` 前缀。

2. High: 审核接口没有权限边界，部署到可访问网络后风险较高。
   - 位置：`src/api/app.py:13-15`, `src/api/api_routes.py:31`, `src/api/partial_routes.py:86`
   - 当前 CORS 全开放，且 JSON API 与 htmx form 都能直接写 `status / truth_content / is_published`。
   - 本机单人使用可以接受；只要对多人或局域网开放，建议先加最小鉴权，例如简单 token、Basic Auth、反向代理鉴权或内网访问限制，并收紧 CORS。

3. Resolved: triage 输出缺少来源 URL 白名单校验。
   - 位置：`src/ingest/triage.py:136`, `src/ingest/triage.py:177-230`, `src/ingest/triage.py:291-295`
   - 已在 `_parse_events(..., allowed_urls=...)` 中过滤不在 raw 输入池里的 `source_urls`，并丢弃过滤后没有真实来源的事件。
   - 已新增 `source_refs`，把 candidate 事件映射回 raw 的 `url / platform / raw_id`（如 `bvid`、`note_id`），便于人工追溯。
   - 覆盖测试：`tests/test_triage_pipeline.py`。

4. Medium: 采集输入信息密度是下一阶段最大质量瓶颈。
   - 位置：`src/ingest/bilibili_collector.py:45-46`, `src/ingest/xhs_collector.py:177`, `src/ingest/triage.py:116-120`
   - B 站主要依赖 search result 的 title/description；TODO 里也提到 description 质量有限。
   - 小红书已取详情 desc，但暂未拉评论；B 站也还没有正文、评论、字幕补抓。
   - 建议优先补充：B 站简介/置顶评论/高赞评论/字幕，小红书评论抽样，并输出空内容率、可研判率、candidate 转化率。

5. Medium: embedding 去重目前是 best-effort，失败后会静默退化。
   - 位置：`src/main.py:679-683`, `src/embedding.py:13-22`, `src/db/crud.py:247-263`
   - `_safe_get_embedding()` 失败后返回 `None`，导入仍继续，语义去重会退化为 slug/hash 去重。
   - 建议在定时 pipeline 前加 `--health-check` 或 preflight，检查 DB、LLM、embedding、XHS MCP；embedding 不可用时明确中止，或给记录打 `embedding_pending` 便于后续回填。

6. Resolved: 配置文档出现 `api_style="responses"`，但代码只实现了 `/chat/completions`。
   - 位置：`src/config.py:11-14`, `config.example.toml:18-28`
   - 已删除 `ApiEndpoint.api_style` 字段和示例配置中的 `api_style` 说明，避免误配。
   - `rg api_style src config.example.toml config.toml README.md TODO.md docs tests` 已无结果。

7. Resolved: 列表页存在 N+1 查询空间，数据量增加后会拖慢。
   - 位置：`src/db/crud.py:80-87`, `src/api/page_routes.py:47-55`, `src/api/partial_routes.py:42-51`
   - 已新增 `list_rumors(..., include_analysis=True)`，由 CRUD 层通过 `joinedload(Rumor.analysis)` 一次加载列表卡片需要的 analysis。
   - 列表页和 htmx partial 列表已改用该参数，并移除逐条访问 `r.analysis` 的循环。
   - 覆盖测试：`tests/test_review_ui.py`。

8. Low: `view_count` 只展示未递增。
   - 位置：`src/db/models.py:45`, `src/api/templates/partials/rumor_detail.html:24`
   - 如果浏览量只是占位，可以暂时保留；如果要展示给运营看，详情页需要原子递增。

9. Low: 前端依赖外部 CDN，不适合离线或内网部署。
   - 位置：`src/api/templates/base.html:10`, `src/api/templates/base.html:22`
   - 当前 Tailwind 和 htmx 都从外网加载。
   - 如果目标是本机 demo，可以暂缓；如果要在内网稳定使用，建议改为本地静态资源。

## Recommended Next Steps

1. 先做稳定性收口。
   - 修媒体路径契约。
   - 增加 pipeline preflight / `--health-check`。
   - 明确鉴权与 CORS 边界。

2. 再做采集质量 sprint。
   - B 站二次抓取：简介、置顶评论、高赞评论、字幕。
   - 小红书评论抽样。
   - raw 去重：空标题、重复 bvid/note_id、重复 URL。
   - 输出采集质量指标：空内容率、去重留存率、可研判率、candidate 转化率。

3. 强化 triage 可控性。
   - 按 keyword/platform/chunk 分批，避免一次性塞入过多 raw records。
   - 对 LLM 输出做 schema 校验、空 content 过滤。
   - 已保存 raw -> candidate 的引用关系；后续可在审核页展示或增加复制入口。
   - 建一个小型黄金样本集，用于 prompt 迭代回归测试。

4. 提升人工审核效率。
   - 详情页上一条 / 下一条。
   - 待审核数量显示在 tab 上。
   - 来源预览和复制入口。
   - 视使用情况再做批量审核。

5. 数据沉淀后再讨论 schema 迁移。
   - 当前 README/TODO 明确不引入 Alembic，schema 变更走 drop & recreate。
   - 当线上数据开始有保留价值后，再决定是否引入迁移体系；这是结构性决策，建议单独确认。

## Current Assessment

框架方向是健康的：流水线薄而清楚，人工审核边界明确，测试覆盖已经比原型阶段充分。下一阶段不建议先做复杂架构，而应优先提升输入质量、输出可追溯性和最小生产安全边界。这样能最快暴露真实数据上的问题，也最能提高人工审核效率。
