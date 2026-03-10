# Codex Review (2026-03-10 Recheck)

## Findings

1. High: “加载更多” 不是追加，而是整块替换列表，并且第一次点击后会把 `#rumor-list` 容器一起替掉，后续 HTMX 交互会失效。
   - 位置：`src/api/templates/partials/rumor_list.html:16-19`, `src/api/templates/index.html:59-60`
   - 现在按钮请求的是下一页 `/partials/rumors?offset=...`，但 swap 策略是 `hx-target="#rumor-list"` + `hx-swap="outerHTML"`。
   - 初始页里 `#rumor-list` 这个 id 只存在于 `index.html` 的外层包装；`partials/rumor_list.html` 返回的只是内部片段，没有同名包装节点。
   - 结果是第一次点“加载更多”后，前 20 条会被第 2 页内容整块替掉，而不是追加；同时 DOM 里的 `#rumor-list` 也没了，后续搜索、筛选、再次加载更多都还在指向一个不存在的 target。

2. Medium: `--dry-run` 仍然不是“真实落库预演”，因为它绕过了数据库状态相关的判重分支。
   - 位置：`src/main.py:129-140`, `src/main.py:155-166`, `src/main.py:255-269`, `src/main.py:310-322`
   - JSONL dry-run 直接使用 `record.slug or slugify(record.title)`，不会调用 `_resolve_slug_direct()`。
   - Markdown dry-run 也不会走 `_resolve_slug_md()` 的查库与语义去重逻辑。
   - 所以 preview 里显示的 `slug`、`succeeded` 和真实导入结果仍可能不一致：真实执行时可能改名、判重、或直接跳过，但 dry-run 看不出来。

3. Medium: `save_image()` 直接信任传入的 `filename`，可以写出 `media/<slug>/` 目录之外。
   - 位置：`src/media.py:15-20`
   - 当前实现直接拼 `Path(settings.MEDIA_DIR) / slug / filename` 后写盘，没有做 basename 归一化、绝对路径拦截或 `..` 校验。
   - 这意味着只要调用方把 `filename` 传成 `../x.png` 或绝对路径，写入位置就可能逃逸出预期目录。`save_image_from_url()` 自己做了 `Path(...).name`，但底层 `save_image()` 这个工具函数本身仍然不安全。

## Verification Notes

- 结论 1、2、3 主要来自静态检查当前代码路径与模板拼装逻辑。
- 我重新运行了 `pytest`，结果是 `23 passed, 4 failed`。
- 4 个失败都在导入集成测试，直接原因是数据库实际 schema 缺少 `rumors.embedding` 列；这说明模型变更已经落到代码，但当前测试库还没完成对应迁移。
