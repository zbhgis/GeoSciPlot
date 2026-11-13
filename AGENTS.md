# GeoSciPlot · 维护约定（对本项目工作的所有会话生效）

## Design principle（设计准则）

**Let the layout speak for itself.**

- Do not sprinkle small explanatory captions, helper paragraphs or meta
  commentary across the UI. If a screen needs small print to be understood,
  fix the layout instead of adding text.
- Explain behavior where the behavior lives: native tooltips (`title=`) on
  the controls themselves, visible labels on buttons. Visible prose is
  reserved for empty states and errors.
- One quiet accent, hairline borders, no glow, no gradient chrome; the
  gallery itself is the rich element on the page — keep the chrome quiet.

## 工程约定

- CSS 真源是 `assets_src/style.css`（含 `scripts/pages.py` 里的页面骨架），
  直接改 `site/` 下的产物会被下次构建覆盖
- 改 CSS/JS/页面后必须重跑 `python scripts/build_site.py`（资源带 `?v=` 哈希防缓存）
- `site/`、`raw/` 为构建产物/收件箱，不入库
- 管理后台：`python scripts/admin.py --no-open`（127.0.0.1:5199）
- 零第三方依赖：只用 Python 标准库（Pillow 仅 prepare/上传缩略图需要）
