# Rumor Agent — 项目 TODO

> 更新时间：2026-05-06
>
> **项目定位**：人工辅助辟谣平台。LLM 负责采集 + 归纳争议事件，真假裁决与辟谣文撰写由运营人员通过 Web 审核界面完成。

---

## 阶段总览

| 阶段 | 描述 | 状态 |
|------|------|------|
| Phase 0 | 基础设施 & 数据库 | ✅ 已完成 |
| Phase 1 | 数据库接入层（CRUD） | ✅ 已完成 |
| Phase 2 | 多平台采集（Bilibili / XHS） | ✅ 已完成（持续优化） |
| Phase 3 | 采集 → triage → 入库主流水线 | ✅ 已完成 |
| Phase 4 | LLM 客户端 & 结构化输出 | ✅ 已完成（统一 caller） |
| Phase 5 | Web 审核界面 + 框架硬故障修复 | ✅ 已完成（2026-05-05） |
| Phase 6 | 自动化流水线（OS 级调度） | ✅ 已完成（2026-05-06） |

**测试覆盖**：117 用例（11 个测试文件，覆盖 collector / triage / import / review API & UI / pipeline orchestration）

---

## Phase 0：基础设施 & 数据库 ✅

- [x] `src/config.py` 从 `config.toml` 加载配置（替代 `.env`）
- [x] SQLAlchemy 2.0 `DeclarativeBase`、Engine、Session
- [x] `init_db.py` 走 drop & recreate 流程，不再嵌迁移 DDL
- [x] `pgvector` + `uuid-ossp` 扩展的依赖关系明确（superuser 装一次）

## Phase 1：数据库接入层 ✅

- [x] `crud.py` 完整 CRUD + 语义去重（pgvector cosine_distance）
- [x] schemas：`RumorCreate / RumorUpdate / RumorReviewIn / StructuredRumorAnalysis`
- [x] `_resolve_slug` 两层去重：slug/hash + embedding 相似

## Phase 2：多平台采集 ✅

- [x] `bilibili_collector.py`：search API + min_play 过滤
- [x] `xhs_collector.py`：MCP login → search → detail
- [x] CLI `--collect-bili / --collect-xhs`（支持 `[collect].keywords` 批量）

### 2.x 持续优化（backlog）
- [ ] B 站正文/评论二次抓取（当前 description 几乎全为 `-`，triage 输入质量受限）
- [ ] raw 清洗（空标题、重复 bvid/note_id）
- [ ] 主题相关性粗筛（降噪声）
- [ ] 采集质量指标（空内容率、可研判率、留存率）

## Phase 3：主流水线 ✅

- [x] CLI 入口：`--collect-bili / --collect-xhs / --triage-jsonl / --import-candidate-jsonl`
- [x] 旁路：`--import-jsonl`（结构化）、`--import-md`（历史人工辟谣回填）
- [x] `--dry-run` 跟真实导入走同一 `_resolve_slug`（仅跳过 embedding API）
- [x] 删除已废弃的 `--fuse-jsonl / --import-fused-jsonl` 路径
- [x] 事务安全（savepoint + 批量 commit）
- [x] 导入统计（processed / succeeded / failed / duplicates）

## Phase 4：LLM 客户端 ✅

- [x] `src/llm/client.py` 统一两个入口：
  - `chat(system, user)` — 自由文本 chat（triage 用）
  - `analyze_structured(sample)` — 结构化输出（MD/analyzer 用）
- [x] 多 endpoint fallback + tenacity 重试 + curl_cffi（绕 WAF TLS 指纹）
- [x] Prompt 边界明确：不声称外部检索、evidence 仅引用输入文本、缺判定信号强制 DUBIOUS
- [x] `LLM_MAX_INPUT_CHARS` 字符级截断（避免上下文溢出）
- [x] `analyzer.has_explicit_verdict_signal` 中英文关键词校验

## Phase 5：Web 审核界面 + 框架修复 ✅（2026-05-05）

### 5.1 审核闭环
- [x] `RumorReviewIn` 窄 schema：`status / truth_content / is_published`，空 body 422
- [x] `PATCH /api/rumors/{slug}` JSON 接口
- [x] `POST /partials/rumors/{slug}/review` form-urlencoded 接口（htmx 局部刷新）
- [x] `detail.html` 拆出 `partials/rumor_detail.html` 含审核表单
- [x] 列表 view 切换：`pending` (`is_published=false`) / `published` / `all`，默认 pending

### 5.2 框架硬故障修复
- [x] `media.save_image` 双 basename 归一化（`Path(slug).name` + `Path(filename).name`），防路径逃逸
- [x] htmx 加载更多改真追加（按钮 `hx-target="this" hx-swap="outerHTML"`），删 stale `hx-select`
- [x] Starlette 1.0 `TemplateResponse` 签名升级（4 处）
- [x] 端到端测试 `tests/test_e2e_flow.py`：合成 raw → mock LLM triage → 入库 → 列表 → 详情 → 表单审核 → API 反向 toggle

## Phase 6：自动化流水线 ✅（2026-05-06）

- [x] CLI `--run-pipeline`：遍历 `[collect].keywords` 跑 `collect-bili + collect-xhs`，汇总 raw → `triage` → `import-candidate`
- [x] 失败策略：单个 keyword 单个平台失败仅记 warning 不阻塞；全部 collect 失败时跳过 triage/import；triage 失败时不调用 import
- [x] `PipelineSummary` 提供 `failed` 属性，CLI 据此设置退出码（0/1）
- [x] 测试覆盖：happy path、XHS 失败不阻塞 Bili、全部 collect 失败、triage 失败、空 keywords
- [x] README 给出 Linux crontab 与 Windows Task Scheduler 样例

---

## 当前下一步行动

按优先级：

1. **真实 LLM 端到端跑通**
   - 配置 `[llm.endpoints]` 与 `[embedding.endpoints]`，跑一次 `--run-pipeline` 看产出质量
   - 记录 triage prompt 在真实数据上的表现，迭代提示词
2. **B 站正文/评论补抓**
   - 现在 raw 里 description 基本空，triage 实际看不到正文
   - 需要 collector 二次拉评论 / AI 字幕，写回 raw 的 `description`
3. **批量分析 CLI**
   - `--analyze` 命令对已入库但无 `analysis_results` 的 rumor 批量调 `analyze_structured`
   - 限于 MD 风格的回填路径；triage 路径不需要二次 LLM 分析
4. **采集质量监控**
   - 加 `--collect-stats` 输出空内容率、去重前后留存率
5. **审核 UI 优化**（视使用情况决定）
   - 详情页加上一条 / 下一条快捷键
   - 列表页未审核计数显示在 tab 上
   - 可选：批量审核操作（多选 → 统一发布）
6. **流水线监控**（可选）
   - `--run-pipeline` 失败时通过 webhook 推 Slack / 飞书
   - 加 `--health-check` 子命令快速验证 DB / LLM / 嵌入 endpoints / XHS MCP 是否就绪

---

## 不在 roadmap 内（已确认的边界）

- **不引入 Alembic**：当前阶段数据量小，schema 变更走 drop & recreate
- **LLM 不做真假判定**：FAKE/TRUE/OUTDATED 状态只能由人工通过审核界面写入
- **不做事实核查 Agent**：项目定位是人工辅助平台，不计划接外部检索 / 跨源验证



## TODO0510
爬虫路径，llm提示词修改，要直接指出视频or帖子发布者
