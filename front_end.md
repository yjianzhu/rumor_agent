# Rumor Agent 前端方案

## 1. 结论

本项目当前阶段不建议上 `Next.js`。

原因很直接：
- 现有后端已经是 Python 为主，核心价值在数据导入、分析、查询，不在复杂前端交互
- 页面类型很清晰：列表、筛选、详情、统计
- 如果引入 `Next.js`，会额外带来 Node 工具链、前后端分层、部署和联调成本
- 对当前项目体量，这个成本不划算

因此，前端采用：

`FastAPI + Jinja2 + htmx + Tailwind CSS`

这是一个偏服务端驱动的方案：
- 页面由 FastAPI + Jinja2 渲染
- 局部筛选、搜索、分页由 `htmx` 请求 HTML 片段更新
- 不单独维护一个前端应用
- 不做 SPA，不做前后端双工程

---

## 2. 目标

构建一个轻量、清晰、可维护的谣言浏览界面，用于：
- 浏览谣言列表
- 按状态、标签、关键词筛选
- 查看单条谣言详情和分析结果
- 查看基础统计信息

设计优先级：
1. 可查
2. 可筛
3. 可读
4. 易维护

不追求：
- Pinterest / 抖音式信息流
- 复杂客户端状态管理
- 花哨动画
- 前后端分离式大前端架构

---

## 3. 技术栈

后端：
- `fastapi`
- `jinja2`
- `uvicorn[standard]`

前端增强：
- `htmx`
- `tailwindcss` CDN

说明：
- `htmx` 负责局部刷新，不直接返回 JSON 给前端拼 DOM
- `Tailwind` 仅用于快速搭界面，不引入构建链
- 页面主逻辑放在服务端模板，不写成手搓 SPA

---

## 4. 架构原则

### 4.1 服务端优先

- 首屏 HTML 由服务端直接输出
- 搜索、筛选、分页请求返回 HTML 片段
- 详情页单独服务端渲染

### 4.2 避免双份模板

不要做这种混合模式：
- 页面初始靠 Jinja2
- 列表刷新靠 JSON API + JS 手搓重绘

这会造成：
- 模板重复
- 状态分裂
- 行为不一致

统一原则：
- 页面路由返回完整 HTML
- 片段路由返回局部 HTML
- JSON API 只保留给真正需要程序消费的接口

### 4.3 不误导用户

`truthfulness_score` 在前端不应展示为“真实性概率”或“真假百分比”。

它更接近：
- 模型对当前提取结论的把握度

因此前端文案统一写成：
- `模型置信度`

并加说明：
- `仅表示模型对当前结论的把握，不代表客观真实概率`

---

## 5. 页面设计

### 5.1 首页

首页由三部分组成：

1. 顶部工具栏
- 关键词搜索框
- 状态筛选
- 标签筛选
- 排序方式

2. 统计栏
- 总条数
- 各状态数量
- 已发布数量
- 最近 7 天新增数量

3. 列表区
- 默认使用纵向列表或紧凑卡片列表
- 每条记录突出：状态、标题、摘要、标签、模型置信度、更新时间

不建议默认做瀑布流。

原因：
- 本项目内容是文本密集型，不是视觉素材流
- 用户主要任务是定位和判断，不是闲逛
- 瀑布流不利于比较、扫描和批量处理

### 5.2 列表项信息

每条谣言卡片/列表项建议包含：
- 状态 badge：`FAKE / TRUE / DUBIOUS / OUTDATED`
- 标题
- 摘要，若无则截断 `rumor_content`
- 标签
- 模型置信度
- 更新时间

可选显示：
- 来源数量
- 是否发布

不建议首页直接塞入大段 evidence。

### 5.3 详情页

详情页重点展示：
- 标题
- 状态
- 谣言内容
- 真相内容
- AI 分析摘要
- 模型置信度
- evidence
- source_urls
- tags
- 时间信息

详情页应该可读，不要继续卡片化过度包装。

---

## 6. 路由设计

页面路由：

- `GET /`
  - 首页
  - 返回完整 HTML

- `GET /rumors/{slug}`
  - 详情页
  - 返回完整 HTML

片段路由：

- `GET /partials/rumors`
  - 返回列表区域 HTML 片段
  - 给搜索、筛选、分页使用

- `GET /partials/stats`
  - 返回统计栏 HTML 片段
  - 给首页局部刷新使用

JSON API：

- `GET /api/rumors/{slug}`
- `GET /api/stats`
- `GET /api/tags`

说明：
- JSON API 保留，但前端页面主交互不依赖它
- 页面主交互优先走 HTML partials

---

## 7. 数据交互

### 7.1 搜索

搜索框使用 `htmx`：
- 输入后防抖 300ms
- 请求 `/partials/rumors?q=...`
- 只替换列表区域

### 7.2 筛选

状态和标签切换时：
- 请求同一个 `/partials/rumors`
- 将筛选条件作为 query params 带上

### 7.3 分页

当前阶段建议：
- 先做“加载更多”按钮

不建议第一版就上无限滚动。

原因：
- 可控性差
- 调试成本高
- 对文本型后台工具收益有限

后端分页先保留：
- `offset`
- `limit`

但需要固定排序字段，例如：
- `created_at desc`

如果后续数据量继续增长，再考虑 keyset pagination。

---

## 8. API / CRUD 扩展建议

现有 `crud.py` 需要补这些能力：

1. 列表查询支持 `q`
- 对 `title`
- 对 `summary`
- 对 `rumor_content`

2. 统计能力
- `count_rumors()`
- `count_by_status()`
- `count_published()`
- `count_recent(days=7)`

3. 标签聚合
- `list_tags()`

4. 详情查询
- 根据 `slug` 查单条 rumor
- 预加载 analysis

注意：
- 如果继续使用数据库模糊搜索，当前规模可以接受
- 一旦数据明显增大，应升级到全文检索，而不是长期依赖裸 `ILIKE`

---

## 9. Schema 扩展建议

建议新增：

```python
class RumorDetailOut(RumorOut):
    analysis: AnalysisResultOut | None = None


class StatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    published: int
    recent_7d: int
```

如果后续还保留 JSON 列表接口，再补：

```python
class PaginatedRumorOut(BaseModel):
    items: list[RumorOut]
    total: int
    offset: int
    limit: int
```

---

## 10. 目录结构

建议目录：

```text
src/api/
├── __init__.py
├── app.py
├── deps.py
├── page_routes.py
├── partial_routes.py
├── api_routes.py
└── templates/
    ├── base.html
    ├── index.html
    ├── detail.html
    └── partials/
        ├── rumor_list.html
        ├── rumor_card.html
        └── stats_bar.html
```

拆分理由：
- 页面路由
- 片段路由
- JSON API

三者职责分开，避免一个 `routes.py` 越写越脏。

---

## 11. UI 建议

视觉方向：
- 干净、偏信息系统
- 不做社交媒体风
- 强调状态区分和可读性

颜色建议：
- `FAKE`: 红
- `TRUE`: 绿
- `DUBIOUS`: 黄
- `OUTDATED`: 灰

但要克制：
- badge 用于标记，不要整页高饱和度

首页布局建议：
- 顶部工具栏固定
- 中间统计栏
- 下方列表
- 桌面端 2 列紧凑卡片或 1 列列表
- 移动端 1 列

说明：
- 这里不追求“看起来酷”
- 追求“看起来可信、稳定、像工具”

---

## 12. 启动方式

依赖安装：

```bash
uv pip install fastapi "uvicorn[standard]" jinja2
```

前端资源：
- `htmx` 用 CDN
- `tailwindcss` 用 CDN

启动：

```bash
python scripts/run_server.py
```

---

## 13. 实施顺序

### Phase A

- 建 `src/api/app.py`
- 建基础模板 `base.html`
- 完成首页和详情页的服务端渲染

### Phase B

- 增加 `/partials/rumors`
- 接入 `htmx` 搜索和筛选

### Phase C

- 增加统计栏
- 增加 tags 下拉
- 完善空状态、错误状态、加载状态

### Phase D

- 如有必要，再补 JSON API 对外使用
- 再决定是否需要更强的前端框架

---

## 14. 最终判断

当前项目最合适的方案不是 `Next.js`，而是：

`FastAPI + Jinja2 + htmx + Tailwind`

理由：
- 足够轻
- 和现有 Python 后端一致
- 开发速度快
- 维护成本低
- 足以支撑当前的谣言列表、筛选、详情、统计需求

如果未来出现这些条件，再考虑上 `Next.js`：
- 前端交互显著复杂
- 需要独立前端团队维护
- 需要更完整的前端路由、状态、组件体系
- 项目从后台工具升级为正式产品站
