#!/usr/bin/env python3
"""GeoSciPlot 静态站生成器：读 meta/refs.json → 生成 site/ 纯静态站点。

用法：
    python scripts/build_site.py              # 生产构建（图片走 jsDelivr / GitHub raw 逐源降级）
    python scripts/build_site.py --preview    # 本地预览（把 images/ 复制进 site/，源改本地）

产出：
    site/index.html              画廊首页（缩略图网格 + 分页 + 搜索 + 多维筛选 + 排序）
    site/{id}/index.html         每图详情页（原图 + 元信息 + 上下张）
    site/search/index.html       全站搜索独立页（缩略图结果行，任意终端可用）
    site/color-lab/index.html    色彩实验独立页（框选取色 + 颜色替换调色 + 色觉模拟工具）
    site/assets/style.css        样式（源：assets_src/style.css，此处仅读取复制）
    site/assets/gallery.js       逐源降级加载 + 分页/筛选/排序 + 统计打点
                                 （源：assets_src/gallery.js；构建期在其头部注入 window.GALLERY 配置）
    site/assets/gallery-data.js  全量图元数据（首页网格与搜索页共用）

设计要点：
  · 图片没有标题，卡片只显示缩略图与 id
  · 筛选维度：期刊 / 论文发表年份 / 添加日期（= 上传日期，即 images 下的日期目录）
  · 分页：每页 30 张，只渲染当前页 → 只请求当前页的缩略图
  · 首页首屏的卡片由 Python 直接输出静态 HTML（对爬虫/AI 引擎友好），
    翻页与筛选时改由 JS 渲染
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import time
from pathlib import Path

from pages import (build_colorlab_page, build_detail, build_index,
                   build_search_page, build_stats_page, render_404,
                   render_about_page, render_guide_article, render_guide_list)
from site_common import BUILD_VER, PAGE_SIZE, ROOT, SITE_URL, doi_bare, esc

CFG_PATH = ROOT / "gallery.config.json"
REFS_JSON = ROOT / "meta" / "refs.json"
SITE = ROOT / "site"
IMAGES = ROOT / "images"
ASSETS_SRC = ROOT / "assets_src"

DEFAULT_CFG = {
    "title": "GeoSciPlot",
    "subtitle": "地学科研绘图参考图库",
    "lede": "收集公开发表的地学 / 科研图表，可搜索、可筛选、可翻页。",
    "repo": "GeoSciPlot",
    "branch": "main",
    "owner": "zbhgis",
    "activeSource": 1,
    "tracker": "/api/v1/track",
}


def load_cfg() -> dict:
    cfg = dict(DEFAULT_CFG)
    if CFG_PATH.exists():
        cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
    return cfg


def build_sources(cfg: dict, preview: bool = False) -> list[dict]:
    owner = cfg.get("owner") or "OWNER"
    repo = cfg["repo"]
    branch = cfg.get("branch", "main")
    # 图片一律走 GitHub 链接（jsDelivr CDN → raw 直链），
    # 本站不存图片不分发图片（服务器带宽留给站点本身）。
    sources = [
        {"id": "jsdelivr", "label": "jsDelivr", "base": f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/images"},
        {"id": "raw", "label": "GitHub raw", "base": f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/images"},
    ]
    if preview:
        # 本地预览：图片副本就在 site/images/，同源加载即可
        sources.insert(0, {"id": "local", "label": "本地（仅预览）", "base": "/images"})
    return sources


def haystack(item: dict) -> str:
    parts = [
        item.get("id", ""),
        item.get("doi") or "",
        str(item.get("added") or ""),
        " ".join(item.get("tags", [])),
    ]
    # 主色 hex 也进全文索引：文本框直接输 1F4E79 这类色号也能搜到
    hexes = [str(c.get("hex", "")).lstrip("#") for c in (item.get("colors") or [])]
    if hexes:
        parts.append(" ".join(hexes))
    return " ".join(parts).lower()


CSS = (ASSETS_SRC / "style.css").read_text(encoding="utf-8")

JS = (ASSETS_SRC / "gallery.js").read_text(encoding="utf-8")


def build_stats_data(cfg: dict, items: list[dict]) -> None:
    """全站统计数据 → site/assets/stats-data.js（仅 /stats/ 页注入）。
    只带统计所需的最小字段：id / 标签 / 上传日期 / 画幅 / 主色表；画幅分类在
    构建期按原图宽高算好（横图/竖图/方图），省去 JS 重复判断也保证口径唯一。
    另带 GSP_STATS_API（统计服务地址）：空串 = 同源反代，stats.js 不得当「未配置」。"""
    def ar(it: dict) -> str:
        w, h = it.get("width") or 0, it.get("height") or 0
        if not w or not h:
            return "未知"
        if w > h * 1.05:
            return "横图"
        if h > w * 1.05:
            return "竖图"
        return "方图"

    data = [{
        "id": it["id"],
        "tg": [str(t) for t in (it.get("tags") or [])],
        "ad": str(it.get("added") or ""),
        "ar": ar(it),
        # cs = 各图前 20 主色的 hex 列表（无 #，按占比降序）：主色构成卡取第一
        # 未屏蔽主色归族，高频颜色卡按「前 20 中出现该族即计一张」统计；
        # 校验同 gallery-data 的 cs —— 脏 hex 进 JS 会让 parseInt 产出 NaN（静默失效）
        "cs": [h for c in (it.get("colors") or [])
               for h in [str(c.get("hex", "")).lstrip("#")]
               if re.match(r"^[0-9A-Fa-f]{6}$", h)],
    } for it in items]
    # "<" 转义防标签文本里出现 </script> 提前截断内嵌 script
    (SITE / "assets" / "stats-data.js").write_text(
        "window.GSP_STATS_API = " + json.dumps(cfg.get("api", ""), ensure_ascii=False) + ";\n"
        + "window.GSP_STATS = "
        + json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        + ";\n", encoding="utf-8")


def build_about(cfg: dict) -> str:
    """关于本站页（/about/）：内容源 content/about.md（render_md 渲染，与 MacroBiodiv
    同款迷你渲染器），窄栏 prose 版式（.about-body，样式在 style.css）；
    缺文件 / 缺渲染器时只出标题不报错。"""
    src = ROOT / "content" / "about.md"
    doc = ""
    if src.exists():
        try:
            from render_md import parse_md
            _, doc, _, _ = parse_md(src.read_text(encoding="utf-8"))
        except ImportError:
            print("· 关于本站：缺 scripts/render_md.py，正文跳过")
    # 正文首个 `# ` 标题与页面大标题重复：剥离（MacroBiodiv build_weekly 同款处理）
    doc = re.sub(r'<h2 id="doc-1" class="md-h1">.*?</h2>\n*', "", doc, count=1)
    return render_about_page(cfg, doc)


def build_guide(cfg: dict) -> list[dict]:
    """制图经验（/guide/）：版式照搬 MacroBiodiv 每周速递。

    列表页 = header.site + 月份 chip + 按月分组条目；文章页 = 三栏骨架
    （250 文章导航 / 760 正文 / 180 目录）+ 上下篇。内容源 content/guide/*.md，
    文件名前缀日期决定排序与 slug（2026-03-02-map-projection-basics.md →
    /guide/map-projection-basics/）。
    """
    src_dir = ROOT / "content" / "guide"
    if not src_dir.is_dir():
        return []
    try:
        from render_md import parse_md
    except ImportError:
        print("· 制图经验：缺 scripts/render_md.py，跳过")
        return []

    posts = []
    for md in sorted(src_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        meta, doc, toc, plain = parse_md(text)
        # 文件名：日期前缀 + 语义 slug；日期同时用于排序与列表日期
        m_date = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", md.stem)
        date = (m_date.group(1) if m_date else str(meta.get("date") or "")[:10])
        slug = m_date.group(2) if m_date else md.stem
        title = str(meta.get("title") or "").strip()
        if not title:
            title = next((txt for lv, hid, txt in toc if hid == "doc-1"), md.stem)
        # 正文首个 `# ` 标题与页面标题重复：剥离（与 Macro 周报同款）
        doc = re.sub(r'<h2 id="doc-1" class="md-h1">.*?</h2>\n*', "", doc, count=1)
        toc = [t for t in toc if t[1] != "doc-1"]
        # 摘要：正文第一段非引导语（跳过公众号关注/星标提示），截 90 字
        summary = ""
        for p in re.findall(r"<p>(.*?)</p>", doc, re.S):
            t = re.sub(r"<[^>]+>", "", p).strip()
            if len(t) >= 30 and "点击上方" not in t and "关注并设为" not in t:
                summary = t[:90] + ("…" if len(t) > 90 else "")
                break
        words = len(plain)
        first_img = re.search(r'<p class="wk-img"><img src="([^"]+)"', doc)
        month = f"{date[:4]}年{int(date[5:7])}月" if re.match(r"^\d{4}-\d{2}", date) else "未分组"
        # llms-full.txt 用的可读纯文本：直接剥 HTML 标签，保留段落换行。
        # plain_text() 为字数统计服务，会把所有空白压掉，不能拿来当全文。
        full_text = html.unescape(re.sub(r"<[^>]+>", " ", doc))
        full_text = re.sub(r"[ \t]+", " ", full_text)
        full_text = re.sub(r"(?m)^[ \t]+", "", full_text)
        full_text = re.sub(r"(?m)[ \t]+$", "", full_text)
        full_text = re.sub(r"\n\s*\n\s*\n+", "\n\n", full_text).strip()
        posts.append({
            "slug": slug, "title": title, "date": date, "month": month,
            "doc": doc, "toc": toc, "words": words, "reading": max(1, -(-words // 200)),
            "summary": summary, "og_image": first_img.group(1) if first_img else "",
            "text": full_text,
        })
    if not posts:
        return []
    posts.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)

    for i, p in enumerate(posts):
        d = SITE / "guide" / p["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(render_guide_article(cfg, posts, i), encoding="utf-8")

    (SITE / "guide").mkdir(parents=True, exist_ok=True)
    (SITE / "guide" / "index.html").write_text(
        render_guide_list(cfg, posts), encoding="utf-8")

    # 过期文章目录 → 改名移入 site_trash（与周报/图库同一模式，绝不原地删除）
    trash = ROOT / "site_trash"
    live = {p["slug"] for p in posts}
    for d in (SITE / "guide").iterdir():
        if d.is_dir() and d.name not in live:
            trash.mkdir(parents=True, exist_ok=True)
            dest = trash / (d.name + "-" + str(int(time.time())))
            print(f"· 过期制图经验页 {d.name} → site_trash/（不删除）")
            try:
                d.rename(dest)
            except OSError:
                pass
    print(f"· 制图经验：列表页 + {len(posts)} 篇文章页 → guide/")
    return posts


# 标签中英对照：只用于 llms.txt 的英文检索词（让英文提问能命中这批图），站点界面仍是纯中文。
# 表里没有的标签原样输出中文——不臆造译名，加新标签时在这里补一行即可。
TAG_EN = {
    "复杂组图": "multi-panel composite figure",
    "单一组图": "single-panel figure",
    "矩形局部地图": "rectangular inset location map",
    "局部放大图": "zoomed-in detail inset",
    "样点分布图": "sampling-station map",
    "古地理": "paleogeography",
    "北极": "Arctic",
    "半球": "hemisphere",
    "半环形": "semi-annular panel layout",
}


def build_seo_files(cfg: dict, items: list[dict], sources: list[dict], active: int,
                    guide_posts: list[dict] | None = None) -> None:
    """生成 robots.txt / sitemap.xml / llms.txt —— 图库站的 SEO/GEO 三件套。"""
    nl = chr(10)
    # AI 爬虫白名单与 MacroBiodiv / 主站同一份清单（允许产出引用的 AI 引擎抓取），
    # 另补中文搜索引擎抓取端（本站受众在中文侧）
    ai_bots = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-Web",
               "Claude-SearchBot", "PerplexityBot", "Perplexity-User", "Google-Extended",
               "CCBot", "Meta-ExternalAgent", "FacebookBot", "Applebot", "Applebot-Extended",
               "Amazonbot", "DuckAssistBot", "Bytespider", "PetalBot",
               "Omgilibot", "YouBot", "Diffbot", "Bytedance"]
    cn_engines = ["Baiduspider", "360Spider", "YisouSpider"]
    parts = ["User-Agent: *", "Allow: /", "Disallow: /api/", ""]
    for b in ai_bots + cn_engines:
        parts += ["User-Agent: " + b, "Allow: /", "Disallow: /api/", ""]
    parts += ["Sitemap: " + SITE_URL + "/sitemap.xml", ""]
    (SITE / "robots.txt").write_text(nl.join(parts), encoding="utf-8")

    today = time.strftime("%Y-%m-%d")
    img_base = sources[active]["base"]
    # sitemap 的 image:loc 规范要求绝对 URL：生产本就是 jsdelivr 绝对地址，
    # --preview 的 img_base 是相对路径 /images（本地文件不部署，sitemap 不被消费，
    # 但保持良构免得校验器报错）——统一补全成绝对地址
    if not img_base.startswith("http"):
        img_base = SITE_URL + img_base
    # lastmod 用内容自身的真实时间，而不是构建时间——每次构建都写 "今天"，
    # 引擎会学会忽略这个字段。没有可靠时间的页面宁可不给 lastmod。
    item_lastmod = max((str(it.get("added") or "").strip() for it in items), default="") or today
    guide_lastmod = max((p.get("date") or "" for p in (guide_posts or [])), default="")
    about_src = ROOT / "content" / "about.md"
    about_lastmod = (time.strftime("%Y-%m-%d", time.localtime(about_src.stat().st_mtime))
                     if about_src.exists() else "")

    def url_entry(loc: str, lastmod: str = "") -> str:
        lm = ("<lastmod>" + lastmod + "</lastmod>") if lastmod else ""
        return "<url><loc>" + loc + "</loc>" + lm + "</url>"

    urls = [url_entry(SITE_URL + "/", item_lastmod),
            # /search/ 与 /color-lab/ 是交互工具页，内容不随数据变化，不给假 lastmod
            url_entry(SITE_URL + "/search/"),
            url_entry(SITE_URL + "/color-lab/"),
            url_entry(SITE_URL + "/guide/", guide_lastmod),
            # 统计页随收录量变化，与首页同源
            url_entry(SITE_URL + "/statistics/", item_lastmod),
            url_entry(SITE_URL + "/about/", about_lastmod)]
    for p in (guide_posts or []):
        urls.append(url_entry(SITE_URL + "/guide/" + p["slug"] + "/", p.get("date") or ""))
    for it in items:
        lm = str(it.get("added") or "").strip()
        # Google 图片扩展：把详情页与原图直链绑在一起，图片搜索才有可索引的地址
        # （<img src> 由 JS 赋值的页面，图片爬虫看不到 URL）。license 字段留空——
        # 版权归各原作者，本站无权声明许可
        full = str(it.get("full") or "")
        sem = " · ".join(str(t) for t in (it.get("tags") or []))
        img_block = ""
        if full:
            cap = " · ".join(x for x in [sem, str(it.get("added") or ""),
                                         ("DOI: " + doi_bare(it["doi"])) if it.get("doi") else ""] if x)
            img_block = ("<image:image><image:loc>" + esc(img_base + "/" + full) + "</image:loc>"
                         + "<image:title>" + esc(sem or ("图 " + it["id"])) + "</image:title>"
                         + "<image:caption>" + esc(cap or ("图 " + it["id"])) + "</image:caption></image:image>")
        urls.append("<url><loc>" + SITE_URL + "/" + it["id"] + "/</loc>"
                    + (("<lastmod>" + lm + "</lastmod>") if lm else "") + img_block + "</url>")
    sm = nl.join(["<?xml version=" + chr(34) + "1.0" + chr(34) + " encoding=" + chr(34) + "UTF-8" + chr(34) + "?>",
                  "<urlset xmlns=" + chr(34) + "http://www.sitemaps.org/schemas/sitemap/0.9" + chr(34)
                  + " xmlns:image=" + chr(34) + "http://www.google.com/schemas/sitemap-image/1.1" + chr(34) + ">"]
                 + urls + ["</urlset>"])
    (SITE / "sitemap.xml").write_text(sm, encoding="utf-8")

    lines = ["# " + cfg.get("title", "geosciplot"), "",
             cfg.get("subtitle", "") + "（" + SITE_URL + "）—— " + cfg.get("lede", ""),
             "", "## Overview (EN)", "",
             "GeoSciPlot is an open reference gallery of figures published in Earth-science",
             "literature — polar and paleogeographic maps, sampling-station maps, multi-panel",
             "composites and their colour palettes. It exists so researchers can reuse proven",
             "visual conventions when plotting their own data, not to redistribute the papers.",
             "",
             "- " + str(len(items)) + " figures, one page per figure at " + SITE_URL + "/<id>/ ;",
             "  each page lists its tags, the source paper DOI, the upload date, the pixel size",
             "  and the dominant colours extracted from the image.",
             "- Tags are Chinese; every entry below repeats them with an English gloss.",
             "- Browse: " + SITE_URL + "/ (filter by journal, paper year or upload date, 30 per page).",
             "- Search: " + SITE_URL + "/search/?q=<keyword> matches id / DOI / tag.",
             "- Colour lab: " + SITE_URL + "/color-lab/ — crop a region, rank its dominant colours",
             "  with HEX codes, replace one colour, preview the result under Protanopia /",
             "  Deuteranopia / Tritanopia / Achromatopsia simulation, and export a PNG.",
             "  Everything runs locally in the browser.",
             "- Statistics: " + SITE_URL + "/statistics/ — collection size, colour composition,",
             "  most-used colours, tag word cloud, most-viewed figures.",
             "- Mapping guide: " + SITE_URL + "/guide/ — practical notes on scientific map-making;",
             "  a five-part 'global map projections in top journals' series with Python code and figures.",
             "- Image files are served by jsDelivr / GitHub raw from the GitHub repository, not",
             "  from this server. Direct image URLs are in sitemap.xml (image:loc entries).",
             "", "## 核心页面", "",
             "- [图库首页](" + SITE_URL + "/)",
             "- [全站搜索](" + SITE_URL + "/search/)",
             "- [色彩实验](" + SITE_URL + "/color-lab/)（框选取色 + 颜色替换调色 + 色觉模拟工具）",
             "- [制图经验](" + SITE_URL + "/guide/)（科研制图经验；含「顶刊中的全球地图投影」系列）",
             "- [全站统计](" + SITE_URL + "/statistics/)（收录量、主色构成、高频颜色、标签词云、点击量榜）",
             "- [关于本站](" + SITE_URL + "/about/)（站点定位、数据来源与说明）",
             ""]
    if guide_posts:
        # 顶层声明全文入口：AI 引擎从 llms.txt 就能发现 llms-full.txt
        lines[4:4] = ["> 制图经验全文（纯文本，供整段引用）：" + SITE_URL + "/llms-full.txt", ""]
        lines += ["- [制图经验全文](" + SITE_URL + "/llms-full.txt)（"
                  + str(len(guide_posts)) + " 篇纯文本全文）", ""]
        lines += ["## 制图经验（共 " + str(len(guide_posts)) + " 篇）", ""]
        lines += ["- [" + p["title"] + "](" + SITE_URL + "/guide/" + p["slug"] + "/)"
                  + (" — " + p["summary"] if p.get("summary") else "")
                  + "（" + (p.get("date") or "") + "）" for p in guide_posts]
        lines += [""]
    lines += ["## 姊妹站点", "",
              "- [浩瀚地学主站](https://www.zbhgis.com) — 个人技术博客：遥感 / GIS / Python / 地学研究",
              "- [MacroBiodiv 文献库](https://macrobiodiv.zbhgis.com) — 宏观生态与生物多样性文献库：",
              "  Crossref / OpenAlex 元数据、AI 中文摘要、每周速递",
              "", "## 全部图片（共 " + str(len(items)) + " 张）", ""]
    for it in items:
        raw_tags = [str(t) for t in (it.get("tags") or [])]
        tags = " · ".join(raw_tags)
        en = " / ".join(TAG_EN[t] for t in raw_tags if t in TAG_EN)
        doi = doi_bare(it.get("doi"))
        added = str(it.get("added") or "")
        w, h = int(it.get("width") or 0), int(it.get("height") or 0)
        dims = f"{w}×{h}px" if w and h else ""
        top = " ".join(str(c.get("hex", "")) for c in (it.get("colors") or [])[:3]).strip()
        palette = ("palette " + top) if top else ""
        meta = " · ".join(x for x in [tags, en, dims, palette, doi, added] if x)
        line = "- [图 " + it["id"] + "](" + SITE_URL + "/" + it["id"] + "/)"
        lines.append(line + (" — " + meta if meta else ""))
    lines += ["", "## 说明", "",
              "- 图片本体由 jsDelivr / GitHub raw 分发，各详情页附原始论文 DOI 与上传日期",
              "- 图片元数据的机器可读版见 sitemap.xml（含 image:loc 图片直链与图注）",
              "- 英文主题词由维护者整理的标签对照表给出，未收录的标签保持中文原样",
              "- 引用本站内容时请注明作者「GeoSciPlot」并附原文链接；图片版权归原作者，",
              "  学术引用请同时引用原论文（DOI 见各详情页）"]
    (SITE / "llms.txt").write_text(nl.join(lines) + nl, encoding="utf-8")
    # llms-full.txt：制图经验全文。图库页本身只有图注与元数据，真正值得整段引用
    # 的中文长文在 guide/；与 MacroBiodiv 的 llms.txt / llms-full.txt 两层结构对齐。
    if guide_posts:
        full = ["# " + cfg.get("title", "GeoSciPlot") + " · 制图经验全文", "",
                "> 本文件是 " + SITE_URL + "/guide/ 栏目全部文章的纯文本全文，供 AI 引擎整段引用。",
                "> 索引文件：" + SITE_URL + "/llms.txt · 图片目录见 " + SITE_URL + "/sitemap.xml", ""]
        for p in guide_posts:
            full += ["## " + p["title"], "",
                     "- URL: " + SITE_URL + "/guide/" + p["slug"] + "/",
                     "- 日期: " + (p.get("date") or ""),
                     "- 摘要: " + (p.get("summary") or ""), "",
                     p.get("text") or "", "", "---", ""]
        (SITE / "llms-full.txt").write_text(nl.join(full) + nl, encoding="utf-8")
    # IndexNow key 文件：与主站 zbhgis.com 共用同一把 key（IndexNow 允许同一
    # 所有者在一个或多个站点托管同一 key 文件）。ping-search.sh 推送前探测本地址可达。
    key_file = ROOT / "deploy" / "indexnow.key"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        (SITE / (key + ".txt")).write_text(key, encoding="utf-8")
    print("· SEO/GEO 三件套已生成：robots.txt / sitemap.xml / llms.txt（" + str(len(items)) + " 张图）")


def main() -> int:
    ap = argparse.ArgumentParser(description="GeoSciPlot 静态站生成")
    ap.add_argument("--preview", action="store_true",
                    help="本地预览构建：把 images/ 复制进 site/，图片源切到本地")
    args = ap.parse_args()

    cfg = load_cfg()
    if not REFS_JSON.exists():
        print("! 找不到 meta/refs.json，请先运行 python scripts/prepare.py")
        return 1
    items = json.loads(REFS_JSON.read_text(encoding="utf-8")).get("items", [])
    if not items:
        print("! 索引为空")
        return 1

    sources = build_sources(cfg, preview=args.preview)
    active = 0 if args.preview else int(cfg.get("activeSource", 1))
    active = max(0, min(active, len(sources) - 1))

    # 过期的详情页目录 → 改名移入 site_trash/（绝不原地删除）。
    # 之前用 shutil.rmtree 清理，会触发 WorkBuddy 沙箱的批量删除保护
    # （SAFE_DELETE_BULK_CONFIRM_REQUIRED）导致构建失败；纯改名则无此问题。
    # site_trash/ 已 gitignore，偶尔手动清空即可。
    if SITE.exists():
        trash = ROOT / "site_trash"
        # 本轮仍要生成的详情页（SITE / it["id"]）必须留在原地——白名单只排除了
        # 固定栏目，漏了这条 live 比对会把全部详情页当"过期"搬进 site_trash
        # 再原样重建，site_trash 随每次构建增长。空库时 live 为空集，全部照搬。
        live = {it["id"] for it in items}
        for d in SITE.iterdir():
            if (d.is_dir() and d.name not in ("assets", "images", "search", "color-lab", "statistics", "about", "guide")
                    and d.name not in live
                    and (d / "index.html").exists()):
                trash.mkdir(parents=True, exist_ok=True)
                dest = trash / (d.name + "-" + str(int(time.time())))
                print(f"· 过期详情页 {d.name} → site_trash/（不删除）")
                try:
                    d.rename(dest)
                except OSError:
                    pass

    (SITE / "assets").mkdir(parents=True, exist_ok=True)
    GENERATED = {"style.css", "gallery.js", "gallery-data.js", "stats-data.js"}  # 由下方 write_text 生成，不做裸拷贝
    for f in (ROOT / "assets_src").glob("*"):
        if f.is_file() and f.name not in GENERATED:
            shutil.copyfile(f, SITE / "assets" / f.name)
    if args.preview:
        # 仅预览构建复制图片副本（生产走 GitHub 链接，本站不分发图片）
        dst = SITE / "images"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(IMAGES, dst)
        n = sum(1 for p in dst.rglob("*") if p.is_file())
        print(f"· 预览模式：images/ → site/images/（{n} 个文件）")
    else:
        # 生产构建：把预览模式遗留的 site/images/ 挪进 site_trash/。
        # 它有几十 MB（原图 + 缩略图副本），而生产站点图片全部走 jsDelivr/GitHub raw，
        # 留着会让每次「scp -r site/*」都把整包图片白白传上服务器。
        stale = SITE / "images"
        if stale.exists() and stale.is_dir():
            trash = ROOT / "site_trash"
            trash.mkdir(parents=True, exist_ok=True)
            dest = trash / ("images-" + str(int(time.time())))
            print("· 预览遗留 site/images/ → site_trash/（部署包不再携带，清空 site_trash 时一起走）")
            try:
                stale.rename(dest)
            except OSError:
                pass

    (SITE / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    inline = {
        "sources": [s["base"] for s in sources],
        "active": active,
        "labels": [s["label"] for s in sources],
        "tracker": cfg.get("tracker", ""),
        "api": cfg.get("api", ""),
    }
    (SITE / "assets" / "gallery.js").write_text(
        "window.GALLERY = " + json.dumps(inline, ensure_ascii=False) + ";\n" + JS, encoding="utf-8")

    # 全量元数据：首页网格与全站搜索浮层共用这一份数据（详情页没有内嵌数据，
    # 靠它实现跨页搜索）。se = 检索 haystack，构建期算好免去 JS 重复拼接。
    # fu = 原图相对路径（色彩实验页做像素级取色/替换需要 full 原图，缩略图不够）。
    data = [{
        "id": it["id"],
        "rel": it.get("thumb", ""),
        "fu": it.get("full", ""),
        "w": it.get("width") or 0,
        "h": it.get("height") or 0,
        "ad": it.get("added") or "",
        "tg": it.get("tags") or [],
        "doi": it.get("doi") or "",
        "sub": " · ".join(it.get("tags") or []),
        "se": haystack(it),
        # cs = 主色 [[hex无#, 占比], ...]，颜色筛选（容差匹配 + 相近排序）在客户端做；
        # 只收 6 位 hex，脏数据进 JS 会让 parseInt 产出 NaN（静默失效）
        "cs": [[h, c.get("pct", 0)]
               for c in (it.get("colors") or [])
               for h in [str(c.get("hex", "")).lstrip("#")]
               if re.match(r"^[0-9A-Fa-f]{6}$", h)],
    } for it in items]
    (SITE / "assets" / "gallery-data.js").write_text(
        # < 转义成 \u003c：与 stats-data.js 同一口径——数据若改为内联 <script>，
        # 原始 "</script>" 或标签文本会截断脚本
        "window.GALLERY_DATA = "
        + json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        + ";\n",
        encoding="utf-8")

    img_base = sources[active]["base"]   # 静态 HTML 里图片的绝对地址（与 gallery.js 的起始源一致）
    (SITE / "index.html").write_text(build_index(cfg, items, img_base), encoding="utf-8")
    search_dir = SITE / "search"
    search_dir.mkdir(parents=True, exist_ok=True)
    (search_dir / "index.html").write_text(build_search_page(cfg, items), encoding="utf-8")
    colorlab_dir = SITE / "color-lab"
    colorlab_dir.mkdir(parents=True, exist_ok=True)
    (colorlab_dir / "index.html").write_text(build_colorlab_page(cfg, items), encoding="utf-8")
    stats_dir = SITE / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "index.html").write_text(build_stats_page(cfg, items), encoding="utf-8")
    build_stats_data(cfg, items)
    about_dir = SITE / "about"
    about_dir.mkdir(parents=True, exist_ok=True)
    (about_dir / "index.html").write_text(build_about(cfg), encoding="utf-8")
    guide_dir = SITE / "guide"
    guide_dir.mkdir(parents=True, exist_ok=True)
    guide_posts = build_guide(cfg)
    for i, it in enumerate(items):
        d = SITE / it["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_detail(cfg, items, i, abs_base=sources[active]["base"]), encoding="utf-8")
    build_seo_files(cfg, items, sources, active, guide_posts)

    # 404 页：noindex + 回首页/搜索入口（nginx 需 error_page 404 /404.html 配合）
    (SITE / "404.html").write_text(render_404(cfg), encoding="utf-8")

    pages = max(1, -(-len(items) // PAGE_SIZE))
    index_kb = len((SITE / "index.html").read_bytes()) / 1024
    days = len({it.get("added") for it in items})
    mode = "预览（本地图片源）" if args.preview else f"生产（源 #{active} = {sources[active]['label']}）"
    print(f"· 生成 {len(items)} 张图 + {pages} 页（每页 {PAGE_SIZE}）+ {days} 个日期目录")
    print(f"· index.html {index_kb:.0f}KB（首屏静态输出 {min(len(items), PAGE_SIZE)} 个卡片）")
    print(f"· 模式：{mode}")
    print(f"· 输出目录：{SITE.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
