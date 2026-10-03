#!/usr/bin/env python3
"""GeoSciPlot 静态站生成器：读 meta/refs.json → 生成 site/ 纯静态站点。

用法：
    python scripts/build_site.py              # 生产构建（图片走 jsDelivr/raw/OSS 三源）
    python scripts/build_site.py --preview    # 本地预览（把 images/ 复制进 site/，源改本地）

产出：
    site/index.html              画廊首页（缩略图网格 + 分页 + 搜索 + 多维筛选 + 排序）
    site/{id}/index.html         每图详情页（原图 + 元信息 + 上下张）
    site/search/index.html       全站搜索独立页（缩略图结果行，任意终端可用）
    site/color-lab/index.html    色彩实验独立页（框选取色 + 颜色替换调色工具）
    site/assets/style.css        样式（源：assets_src/style.css，此处仅读取复制）
    site/assets/gallery.js       三源降级加载 + 分页/筛选/排序 + 统计打点
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
from collections import Counter
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "gallery.config.json"
REFS_JSON = ROOT / "meta" / "refs.json"
SITE = ROOT / "site"
IMAGES = ROOT / "images"
ASSETS_SRC = ROOT / "assets_src"

PAGE_SIZE = 30
# 资源版本号（构建时间戳）：CSS/JS 引用统一带 ?v=，部署后老访客的浏览器
# 不会再用缓存的旧脚本配新页面（本次搜索改版就踩过：旧 gallery.js 读不到新数据源）
BUILD_VER = str(int(time.time()))
SITE_URL = "https://geosciplot.zbhgis.com"

DEFAULT_CFG = {
    "title": "GeoSciPlot",
    "subtitle": "地学科研绘图参考图库",
    "lede": "收集公开发表的地学 / 科研图表，可搜索、可筛选、可翻页。",
    "repo": "GeoSciPlot",
    "branch": "main",
    "owner": "zbhgis",
    "activeSource": 1,
    "oss": {"bucket": "", "region": "oss-cn-hangzhou"},
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
    oss = cfg.get("oss", {})
    bucket = oss.get("bucket") or "BUCKET"
    region = oss.get("region", "oss-cn-hangzhou")
    # 图片一律走 GitHub 链接（jsDelivr CDN → raw 直链 → OSS 兜底），
    # 本站不存图片不分发图片（服务器带宽留给站点本身）。
    sources = [
        {"id": "jsdelivr", "label": "jsDelivr", "base": f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/images"},
        {"id": "raw", "label": "GitHub raw", "base": f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/images"},
        {"id": "oss", "label": "OSS 兜底", "base": f"https://{bucket}.{region}.aliyuncs.com/{repo.lower()}/images"},
    ]
    if preview:
        # 本地预览：图片副本就在 site/images/，同源加载即可
        sources.insert(0, {"id": "local", "label": "本地（仅预览）", "base": "/images"})
    return sources


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


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

# 调色板图标（lucide palette）：导航菜单「色彩实验」与详情页「转到色彩实验」共用
ICO_PALETTE = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
               'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
               '<path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 '
               '0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996'
               'c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>'
               '<circle cx="13.5" cy="6.5" r=".5" fill="currentColor" stroke="none"/>'
               '<circle cx="17.5" cy="10.5" r=".5" fill="currentColor" stroke="none"/>'
               '<circle cx="8.5" cy="7.5" r=".5" fill="currentColor" stroke="none"/>'
               '<circle cx="6.5" cy="12.5" r=".5" fill="currentColor" stroke="none"/></svg>')


def nav_html(cfg: dict, up: str = "") -> str:
    """顶部菜单栏：整体移植自 MacroBiodiv 站点的 .mnav（样式同源）。
    「色彩实验」已实装（/color-lab/）；其余按钮的跳转链接暂未实现，一律以 # 占位。"""
    ico_stat = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 20V10M12 20V4M6 20v-4"/></svg>')
    ico_caret = ('<svg class="mnav-more-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>')
    ico_globe = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/>'
                 '<path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>')
    # MacroBiodiv 的图标与链接同主站 zbhgis.com「更多」下拉（lucide globe + 子域名直达）
    ico_mb = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<circle cx="12" cy="12" r="10"/>'
              '<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
              '<path d="M2 12h20"/></svg>')
    ico_menu = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>')
    brand = esc(cfg.get("title") or "GeoSciPlot")
    brand_href = up if up else "./"   # 首页 = 当前页（./），子页 = 上一级（../），都回到图库首页
    return f"""<header class="mnav">
<nav class="mnav-in">
<a class="mnav-brand" href="{brand_href}" title="返回图库首页" aria-label="返回图库首页"><img src="{up}assets/favicon.png?v={BUILD_VER}" alt="" width="26" height="26">{brand}</a>
<ul class="mnav-links">
<li><a class="mnav-link" data-active="false" href="{up}color-lab/">{ICO_PALETTE}色彩实验</a></li>
<li><a class="mnav-link" href="#" title="建设中（预留）">{ico_stat}全站统计</a></li>
<li class="mnav-more"><button type="button" class="mnav-link mnav-more-trigger" aria-haspopup="true" title="更多站点">更多{ico_caret}</button>
<ul class="mnav-dd">
<li><a href="https://www.zbhgis.com" target="_blank" rel="noopener noreferrer">{ico_globe}zbhgis</a></li>
<li><a href="https://macrobiodiv.zbhgis.com" target="_blank" rel="noopener noreferrer">{ico_mb}MacroBiodiv</a></li>
</ul></li>
</ul>
<details class="mnav-m">
<summary class="mnav-icon" title="菜单" aria-label="打开菜单">{ico_menu}</summary>
<ul class="mnav-dd">
<li><a href="{up}color-lab/">{ICO_PALETTE}色彩实验</a></li>
<li><a href="#" title="建设中（预留）">{ico_stat}全站统计</a></li>
<li class="mnav-dd-sep"></li>
<li><a href="https://www.zbhgis.com" target="_blank" rel="noopener noreferrer">{ico_globe}zbhgis</a></li>
<li><a href="https://macrobiodiv.zbhgis.com" target="_blank" rel="noopener noreferrer">{ico_mb}MacroBiodiv</a></li>
</ul>
</details>
</nav>
</header>"""


def page_shell(
    cfg: dict,
    title: str,
    body: str,
    depth: int = 0,
    gh_url: str = "",
    meta_desc: str = "",
    head_extra: str = "",
    og_type: str = "website",
    og_image: str = "",
    og_url: str = "",
) -> str:
    up = "../" if depth else ""
    gh = gh_url or "https://github.com/{}/{}".format(
        cfg.get("owner") or "OWNER", cfg["repo"])
    desc = meta_desc or f"{cfg['subtitle']} —— {cfg['lede']}"
    og_url = og_url or (SITE_URL + ("/" if not depth else ""))
    og_img = f'\n<meta property="og:image" content="{esc(og_image)}">' if og_image else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | geosciplot</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{og_url}">
<meta property="og:site_name" content="geosciplot">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{og_url}">{og_img}
{head_extra}<link rel="stylesheet" href="{up}assets/style.css?v={BUILD_VER}">
<link rel="icon" type="image/png" href="{up}assets/favicon.png">
<script>try{{var t=localStorage.getItem("gsp-theme");if(t)document.documentElement.setAttribute("data-theme",t);var f=localStorage.getItem("gsp-fs");if(f)document.documentElement.setAttribute("data-fs",f)}}catch(e){{}}</script>
</head>
<body>
{nav_html(cfg, up)}
<div class="wrap">
<div class="fab"><a class="tbtn" href="{up}search/" title="全站搜索" aria-label="全站搜索"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.2"/><path d="M10.2 10.2 14 14"/></svg></a><a class="tbtn" href="/" title="返回 Home（图库首页）" aria-label="返回 Home"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 8 8 3l5.5 5M4 7v6h8V7"/></svg></a><a class="tbtn" href="{gh}" rel="noopener" target="_blank" title="在 GitHub 查看（详情页直达当前图片）"><svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg></a><button type="button" class="tbtn tbtn-fs" id="fsBtn" title="字号：标准" aria-label="字号：标准">A</button><button type="button" class="tbtn" id="themeBtn" title="切换明暗主题" aria-label="切换明暗主题"><svg class="ic-sun" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1"/></svg><svg class="ic-moon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.5 9.5A6 6 0 0 1 6.5 2.5a6 6 0 1 0 7 7z"/></svg></button><button type="button" class="tbtn" id="topBtn" title="回到顶部" aria-label="回到顶部"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13.5v-9M4.5 8 8 4.5 11.5 8"/></svg></button></div>
{body}
<footer class="site">
  <span>{esc(cfg['title'])} · {esc(cfg['subtitle'])}</span>
  <span><a href="https://github.com/{esc(cfg.get('owner') or 'OWNER')}/{esc(cfg['repo'])}" rel="noopener">GitHub 仓库</a> · 图表版权归各原作者</span>
</footer>
</div>
<!-- 图片灯箱（编译自 lib/image-lightbox.ts）：挂到 body 统一接管，
     链接内的图（首页卡片/搜索行/菜单品牌）默认不劫持、维持跳转，
     只有详情页 .shot 大图等无链接图片参与；h1 的 logo 装饰图排除 -->
<script src="{up}assets/image-lightbox.js?v={BUILD_VER}"></script>
<script src="{up}assets/gallery-data.js?v={BUILD_VER}"></script>
<script src="{up}assets/gallery.js?v={BUILD_VER}"></script>
<script>try{{if(window.ImageLightbox)window.ImageLightbox.attachImageLightbox(document.body,{{exclude:".logo"}})}}catch(e){{}}</script>
</body>
</html>
"""


def flat(values, default: str = "—") -> Counter:
    return Counter([str(v) if v else default for v in values])


def chips(values: Counter, key: str, all_label: str) -> str:
    items = [f'<button data-v="*" aria-pressed="true">{esc(all_label)}</button>']
    for name, n in sorted(values.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        items.append(f'<button data-v="{esc(name)}" aria-pressed="false">{esc(name)} <span style="opacity:.55">{n}</span></button>')
    return f'<div class="chips" data-key="{key}">\n  ' + "\n  ".join(items) + "\n</div>"


def filter_row(label: str, inner: str) -> str:
    return f'<div class="fgroup"><span class="flabel">{esc(label)}</span>{inner}</div>'


def card_html(item: dict) -> str:
    tags = item.get("tags") or []
    cap = " · ".join(tags) if tags else "—"
    return f"""  <a class="card" href="{esc(item['id'])}/" data-id="{esc(item['id'])}" title="{esc(' · '.join(tags))}">
    <img data-rel="{esc(item.get('thumb'))}" alt="图 {esc(item['id'])}" loading="lazy">
    <span class="cap"><span class="tags">{esc(cap)}</span></span>
  </a>"""


def build_index(cfg: dict, items: list[dict]) -> str:
    addeds = flat([it.get("added") for it in items])
    tag_counter: Counter = Counter()
    for it in items:
        for t in it.get("tags", []):
            tag_counter[str(t)] += 1

    # 首屏静态渲染，其余交给 JS（1000 张时也只输出 48 个卡片节点）
    first_page = items[:PAGE_SIZE]

    ghsvg = ('<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">'
            '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>')
    # 分页条的内联箭头：尺寸/颜色/位移全交给 .ico 系列 CSS，这里只出几何形状
    pg_ico_l = ('<svg class="ico ico-l" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
                'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<path d="M10 3 5 8l5 5"/></svg>')
    pg_ico_r = ('<svg class="ico ico-r" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
                'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<path d="M6 3l5 5-5 5"/></svg>')
    body = f"""<header class="site">
  <h1><img class="logo" src="assets/logo.png" alt="GeoSciPlot logo">{esc(cfg['title'])}</h1>
  <a class="gh-note" href="https://github.com/{esc(cfg.get('owner') or 'OWNER')}/{esc(cfg['repo'])}" rel="noopener" target="_blank" title="在 GitHub 查看图片源文件">{ghsvg}<span>图片存储于 <b>GitHub</b>，访问需具备 GitHub 访问能力（点此查看仓库）</span></a>
  <p class="lede">{esc(cfg['lede'])}</p>
  <div class="meta-row"><span id="count">共 {len(items)} 张</span> · {len(tag_counter)} 个标签 · {len(addeds)} 个上传日期 · 点击查看原图</div>
</header>

<div class="toolbar">
  <span class="searchbox"><svg class="sic" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.2"/><path d="M10.2 10.2 14 14"/></svg><input id="q" class="search" type="search" placeholder="搜索 id / DOI / 标签关键词…" autocomplete="off"><button id="qBtn" type="button" title="搜索" aria-label="搜索">搜索</button></span>
  <select id="perpage" aria-label="每页数量">
    <option value="20">每页 20</option>
    <option value="30" selected>每页 30</option>
    <option value="50">每页 50</option>
  </select>
  <button id="filterBtn" class="reset" aria-expanded="true" aria-controls="filters">筛选 ▴</button>
  <button id="reset" class="reset">重置筛选</button>
</div>

<div id="filters">
{filter_row("颜色",
  '<span class="colorbox">'
  + '<input type="color" id="f-color" value="#ffffff" aria-label="选取筛选颜色" title="选取筛选颜色">'
  + '<input id="f-colorhex" class="hexinp" placeholder="hex 如 1F4E79" maxlength="7" spellcheck="false" autocomplete="off">'
  + '<button id="f-colorclear" class="reset" type="button" title="清除颜色筛选" hidden>×</button>'
  + '</span> <span class="flabel" style="min-width:auto">容差</span>'
  + '<input type="range" id="f-tol" class="tolrange" min="0" max="150" value="60" aria-label="颜色容差（RGB 距离）">'
  + '<span id="f-tolval">60</span>'
  + ' <span class="flabel" style="min-width:auto">占比≥</span>'
  + '<input type="range" id="f-minpct" class="tolrange" min="0" max="100" value="0" aria-label="命中主色的最小占比">'
  + '<span id="f-minpctval">0%</span>')}
{filter_row("标签", chips(tag_counter, "tag", "全部"))}
{filter_row("上传", '<input type="date" id="f-from" class="dateinp">\n'
  + ' <span class="flabel" style="min-width:auto">至</span>\n'
  + '<input type="date" id="f-to" class="dateinp">\n'
  + ' <span class="flabel" style="min-width:auto;margin-left:18px">排序</span>\n'
  + ' <span class="sorter" id="sortseg" role="group" aria-label="排序" style="vertical-align:middle">'
  + '<button type="button" data-sort="added" aria-pressed="true" title="上传日期 新→旧"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5v8M4.8 7.3 8 10.5l3.2-3.2M3 13.5h10"/></svg><span>新到旧</span></button>'
  + '<button type="button" data-sort="added_asc" aria-pressed="false" title="上传日期 旧→新"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13.5v-8M4.8 8.7 8 5.5l3.2 3.2M3 2.5h10"/></svg><span>旧到新</span></button>'
  + '<button type="button" data-sort="color" aria-pressed="false" title="按与筛选颜色的相近程度排序（需先在「颜色」行选色）"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="5.2"/><path d="M8 1.2v2.4M8 12.4v2.4M1.2 8h2.4M12.4 8h2.4"/></svg><span>相近</span></button>'
  + '<button type="button" data-sort="random" aria-pressed="false" title="随机排序"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 4.5h2.2c3.2 0 4.6 7 7.6 7H14M2 11.5h2.2c1.3 0 2.2-.9 3-2M8.8 6.5c.8-1.1 1.7-2 3-2H14M12.3 3l1.7 1.5L12.3 6M12.3 10l1.7 1.5-1.7 1.5"/></svg><span>随机</span></button>'
  + '</span>')}
</div>

<main class="grid" id="grid">
{chr(10).join(card_html(it) for it in first_page)}
</main>
<p class="empty" id="empty">没有符合条件的图片</p>

<div class="pgbar">
  <button id="prev" type="button" title="上一页">{pg_ico_l}上一页</button>
  <span id="pgnums"></span>
  <button id="next" type="button" title="下一页">下一页{pg_ico_r}</button>
  <span class="info" id="pageinfo">共 {max(1, -(-len(items) // PAGE_SIZE))} 页</span>
</div>

<script>window.GALLERY_PAGE = {PAGE_SIZE};</script>"""
    website_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "geosciplot",
        "alternateName": "地学科研绘图参考图库",
        "url": SITE_URL,
        "description": cfg["lede"],
        "inLanguage": "zh-CN",
    }, ensure_ascii=False)
    head = f'<script type="application/ld+json">{website_ld}</script>'
    return page_shell(cfg, cfg["subtitle"], body,
                      meta_desc=f"{cfg['lede']}（{len(items)} 张图，可搜索、可筛选、按上传日期浏览）",
                      head_extra=head)


def build_detail(cfg: dict, items: list[dict], idx: int, abs_base: str) -> str:
    it = items[idx]
    prev_it = items[idx - 1] if idx > 0 else None
    next_it = items[idx + 1] if idx < len(items) - 1 else None
    w, h = it.get("width", 0), it.get("height", 0)

    # 上一张 / 下一张：两列等宽卡片。站点没有标题，用「图 {id}」当主文案，
    # 副文案取标签（无标签则回落到 ID / DOI），让访客能预判点进去是哪张图。
    # 缺一张时输出虚线占位块，否则唯一那张会被 grid 拉成通栏。
    chev_l = ('<svg class="ico ico-l" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
              'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<path d="M10 3 5 8l5 5"/></svg>')
    chev_r = ('<svg class="ico ico-r" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
              'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<path d="M6 3l5 5-5 5"/></svg>')

    def pn_item(it_: dict | None, to_next: bool) -> str:
        if it_ is None:
            return '<span class="pn-empty" aria-hidden="true"></span>'
        cls = "pn-next" if to_next else "pn-prev"
        label = "下一张" if to_next else "上一张"
        arrow = chev_r if to_next else chev_l
        inner = (f'{label}{arrow}' if to_next else f'{arrow}{label}')
        sub = " · ".join(it_.get("tags") or []) or (it_.get("doi") or "—")
        return (f'<a class="{cls}" href="../{esc(it_["id"])}/">'
                f'<span class="dir">{inner}</span>'
                f'<span class="ttl">图 {esc(it_["id"])}</span>'
                f'<span class="dir">{esc(sub)}</span></a>')

    # 配色色块（meta 的 colors 字段，最多 20 个，prepare.py 入库时提取）：
    # 点击色块复制色号（gallery.js 在无网格页统一接管）
    sw = []
    for c in (it.get("colors") or [])[:20]:
        hx = str(c.get("hex") or "")
        if not re.match(r"^#[0-9A-Fa-f]{6}$", hx):
            continue
        pct = c.get("pct")
        pct_txt = (f"{pct:.2f}".rstrip("0").rstrip(".") + "%") if isinstance(pct, (int, float)) else ""
        sw.append(f'<button type="button" class="swchip" data-hex="{esc(hx)}"'
                  f' title="点击复制 {esc(hx)} · {esc(pct_txt)}"><i style="background:{esc(hx)}"></i>'
                  f'<b>{esc(hx)}</b><span data-pct="{esc(pct_txt)}">{esc(pct_txt)}</span></button>')
    swatches_html = "".join(sw)
    swatches_row = (chr(10) + f'  <dt>配色</dt><dd class="swatches">{swatches_html}</dd>') if swatches_html else ""

    pager = ['<div class="pager">',
             pn_item(prev_it, False),
             pn_item(next_it, True),
             '</div>']

    # 标签做成可跳转：点击回到首页并自动套用该标签的搜索
    tags = it.get("tags", [])
    if tags:
        tags_html = "".join(
            f'<a class="tag" href="/?tag={quote(str(t), safe="")}">{esc(t)}</a>' for t in tags
        )
    else:
        tags_html = "—"

    # refs.json 里 DOI 可能存的是完整 URL（管理端按粘贴原样入库），
    # 统一剥掉前缀再用，避免拼出 https://doi.org/https://doi.org/… 的坏链
    doi = str(it.get("doi") or "").strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    if doi:
        doi_html = f'<a href="https://doi.org/{esc(doi)}" rel="noopener" target="_blank">{esc(doi)}</a>'
    else:
        doi_html = "—"

    back_ico = ('<svg class="ico ico-l" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
                'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<path d="M10 3 5 8l5 5"/></svg>')
    body = f"""<a class="back" id="backLink" href="../">{back_ico}返回全部</a>
<h2 class="id-title">图 {esc(it['id'])}</h2>
<figure class="shot">
  <img data-rel="{esc(it.get('full'))}" alt="图 {esc(it['id'])}" width="{w}" height="{h}">
</figure>
<p class="cl-go-row"><a class="cl-go" href="../color-lab/?id={esc(it['id'])}">{ICO_PALETTE}转到色彩实验 · 取色 / 调色</a></p>
<dl class="meta">
  <dt>ID</dt><dd class="hl">{esc(it['id'])}</dd>
  <dt>DOI</dt><dd>{doi_html}</dd>
  <dt>上传日期</dt><dd>{esc(it.get('added'))}</dd>
  <dt>被浏览</dt><dd><span id="views">…</span></dd>
  <dt>标签</dt><dd>{tags_html}</dd>{swatches_row}
</dl>
{chr(10).join(pager)}"""
    gh_img = "https://github.com/{}/{}/blob/{}/images/{}".format(
        cfg.get("owner") or "OWNER", cfg["repo"], cfg.get("branch", "main"), it.get("full", ""))
    full_url = f"{abs_base}/{it.get('full', '')}"
    thumb_url = f"{abs_base}/{it.get('thumb', '')}"
    tags = [str(t) for t in it.get("tags", [])]
    added = str(it.get("added") or "")
    desc_parts = [t for t in [" · ".join(tags), added] if t]
    detail_desc = (" · ".join(desc_parts) + f" · DOI: {it.get('doi')}" if it.get("doi") else " · ".join(desc_parts)) or cfg["lede"]
    image_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "ImageObject",
        "name": f"图 {it['id']}" + (f"（{tags[0]}）" if tags else ""),
        "description": detail_desc,
        "contentUrl": full_url,
        "thumbnailUrl": thumb_url,
        "uploadDate": added,
        "url": f"{SITE_URL}/{it['id']}/",
        "keywords": ", ".join(tags),
        "inLanguage": "zh-CN",
        "author": {"@type": "Organization", "name": cfg.get("title", "geosciplot"), "url": SITE_URL},
    }, ensure_ascii=False)
    og_meta = (f'<meta property="og:image" content="{esc(full_url)}">'
               f'<meta property="og:image:width" content="{it.get("width", 0)}">'
               f'<meta property="og:image:height" content="{it.get("height", 0)}">')
    head = (f'{og_meta}<script type="application/ld+json">{image_ld}</script>')
    title_text = f"图 {it['id']}" + (f"（{tags[0]}）" if tags else "")
    return page_shell(cfg, title_text, body, depth=1, gh_url=gh_img,
                      meta_desc=detail_desc, head_extra=head,
                      og_type="article", og_image=full_url,
                      og_url=f"{SITE_URL}/{it['id']}/")


def build_search_page(cfg: dict, items: list[dict]) -> str:
    """全站搜索独立页：版式对齐主站 zbhgis.com 的 /search。
    结果行由 gallery.js 在客户端渲染（数据来自 gallery-data.js），
    缩略图与网格卡片一样走三源降级；结果链接经 data-up 前缀回详情页。"""
    body = f"""<header class="site">
  <p class="kicker">GEOSCIPILOT · SEARCH</p>
  <h1 class="spage-title">全站搜索</h1>
  <p class="lede">检索全部 {len(items)} 张图的 id / DOI / 标签 / 上传日期；多个词用空格分隔（需同时命中）。</p>
</header>

<input id="spage-q" class="spage-q" type="search" placeholder="输入关键词搜索 id / DOI / 标签…" autocomplete="off" autofocus>
<div class="spage-count" id="spage-count"></div>
<div class="spage-list" id="spage-list" data-up="../"></div>"""
    return page_shell(cfg, "全站搜索", body, depth=1,
                      meta_desc="搜索图库全部图片：按 id / DOI / 标签关键词检索，支持筛选与排序",
                      og_url=f"{SITE_URL}/search/")


def build_colorlab_page(cfg: dict, items: list[dict]) -> str:
    """色彩实验独立页（/color-lab/）：纯浏览器端的取色 / 调色工具。
    指定图片 id 载入原图 → 框选区域（不选=整张图）统计占比最高的前几个颜色
    （色块 + HEX/RGB 色号）→ 把区域内指定颜色替换成新颜色，可撤销、可下载 PNG。
    交互逻辑在 assets_src/color-lab.js（构建期原样拷贝进 site/assets/）。"""
    body = f"""<header class="site">
  <p class="kicker">GEOSCIPILOT · COLOR LAB</p>
  <h1 class="spage-title">色彩实验</h1>
  <p class="lede">框选（或不框选=整张图）统计图中占比最高的几个颜色并提供色号，再把指定颜色替换成新颜色，方便调色试色。全部计算在浏览器本地完成，可下载结果图。</p>
</header>

<div class="clayout">
  <section class="cl-stage-col">
    <div class="cl-toolbar">
      <span class="searchbox"><input id="cl-id" class="search" type="search" list="cl-ids" placeholder="输入图片 id（如 c29fd21ed1）…" autocomplete="off"><button id="cl-load" type="button">载入</button></span>
      <button id="cl-random" class="cl-btn" type="button">随机来一张</button>
      <datalist id="cl-ids"></datalist>
    </div>
    <div class="cl-stage" id="cl-stage">
      <canvas id="cl-canvas" width="0" height="0"></canvas>
      <div class="cl-overlay" id="cl-overlay"><div class="cl-selbox" id="cl-selbox"></div></div>
      <p class="cl-placeholder" id="cl-placeholder">先在上方输入图片 id 载入原图</p>
      <div class="cl-loading" id="cl-loading" hidden><span class="cl-spin"></span>载入中…</div>
    </div>
    <div class="cl-stagebar">
      <button id="cl-selmode" class="cl-btn" type="button" aria-pressed="false" title="开启后拖拽框选统计区域；关闭时单击画布打开放大镜">开始框选</button>
      <span id="cl-selinfo"></span>
      <button id="cl-clearsel" class="cl-btn" type="button" disabled>清除框选</button>
      <label class="cl-check"><input type="checkbox" id="cl-highlight"> 高亮将被替换的像素</label>
    </div>
    <p class="cl-status" id="cl-status"></p>
  </section>

  <aside class="cl-panel">
    <section>
      <h3>主色 · 当前区域</h3>
      <div class="cl-row"><label>数量</label><input type="range" id="cl-count" min="4" max="20" step="1" value="8" aria-label="主色数量"><span class="mono" id="cl-countval">8</span></div>
      <div class="cl-palette" id="cl-palette"><p class="cl-note">载入图片后自动统计（按占比排序）</p></div>
      <p class="cl-note">点击色块设为「目标色」；「复制」拿色号；「屏蔽」把背景色（含相近色）移出统计。</p>
      <div class="cl-blacklist" id="cl-blacklist" hidden>
        <div class="cl-bl-head"><span>黑名单 · 以下颜色不计入主色统计</span><button id="cl-blclear" class="cl-btn cl-mini" type="button">清空</button></div>
        <div class="cl-bl-chips" id="cl-blchips"></div>
      </div>
    </section>
    <section>
      <h3>替换颜色</h3>
      <div class="cl-row"><label>目标色</label><span class="cl-target"><span class="cl-chip" id="cl-target-chip"></span><span class="mono" id="cl-target-hex">未选择</span></span></div>
      <div class="cl-row"><label>新颜色</label><input type="color" id="cl-newcolor" value="#58a6ff"></div>
      <div class="cl-row"><label>容差</label><input type="range" id="cl-tol" min="0" max="150" value="60"><span class="mono" id="cl-tolval">60</span></div>
      <div class="cl-row"><label>范围</label><select id="cl-scope"><option value="sel">框选区域</option><option value="all">整张图</option></select></div>
      <div class="cl-actions"><button id="cl-replace" class="cl-btn cl-primary" type="button" disabled>替换颜色</button></div>
    </section>
    <section>
      <h3>结果</h3>
      <div class="cl-actions">
        <button id="cl-undo" class="cl-btn" type="button" disabled>撤销上一步</button>
        <button id="cl-resetimg" class="cl-btn" type="button">还原原图</button>
        <button id="cl-download" class="cl-btn cl-primary" type="button" disabled>下载 PNG</button>
      </div>
    </section>
  </aside>
</div>

<div class="cl-zoom" id="cl-zoom" hidden>
  <div class="cl-zoom-bar">
    <span class="mono" id="cl-zoom-pct">100%</span>
    <button id="cl-zoom-out" class="cl-btn" type="button" title="缩小">−</button>
    <button id="cl-zoom-in" class="cl-btn" type="button" title="放大">＋</button>
    <button id="cl-zoom-fit" class="cl-btn" type="button">适配窗口</button>
    <button id="cl-zoom-one" class="cl-btn" type="button">1:1</button>
    <span class="cl-zoom-tip">滚轮缩放 · 拖拽平移 · Esc 关闭</span>
    <button id="cl-zoom-close" class="cl-btn cl-primary" type="button">关闭</button>
  </div>
  <div class="cl-zoom-view" id="cl-zoom-view"><canvas id="cl-zoom-canvas" width="0" height="0"></canvas></div>
</div>"""
    head = f'<script defer src="../assets/color-lab.js?v={BUILD_VER}"></script>'
    return page_shell(cfg, "色彩实验", body, depth=1,
                      meta_desc="框选图片区域统计主要颜色（色块 + HEX/RGB 色号），并可将指定颜色替换为新颜色；浏览器本地完成，支持下载结果图",
                      og_url=f"{SITE_URL}/color-lab/",
                      head_extra=head)


def build_seo_files(cfg: dict, items: list[dict], sources: list[dict], active: int) -> None:
    """生成 robots.txt / sitemap.xml / llms.txt —— 图库站的 SEO/GEO 三件套。"""
    nl = chr(10)
    ai_bots = ["GPTBot", "ChatGPT-User", "Claude-Web", "ClaudeBot", "Claude-SearchBot",
               "CCBot", "PerplexityBot", "Google-Extended", "OAI-SearchBot",
               "Meta-ExternalAgent", "Applebot-Extended", "Amazonbot", "DuckAssistBot",
               "Bytespider"]
    parts = ["User-Agent: *", "Allow: /", ""]
    for b in ai_bots:
        parts += ["User-Agent: " + b, "Allow: /", ""]
    parts += ["Sitemap: " + SITE_URL + "/sitemap.xml", ""]
    (SITE / "robots.txt").write_text(nl.join(parts), encoding="utf-8")

    today = time.strftime("%Y-%m-%d")
    urls = ["<url><loc>" + SITE_URL + "/</loc><lastmod>" + today + "</lastmod></url>",
            "<url><loc>" + SITE_URL + "/search/</loc><lastmod>" + today + "</lastmod></url>",
            "<url><loc>" + SITE_URL + "/color-lab/</loc><lastmod>" + today + "</lastmod></url>"]
    for it in items:
        lm = str(it.get("added") or today)
        urls.append("<url><loc>" + SITE_URL + "/" + it["id"] + "/</loc><lastmod>" + lm + "</lastmod></url>")
    sm = nl.join(["<?xml version=" + chr(34) + "1.0" + chr(34) + " encoding=" + chr(34) + "UTF-8" + chr(34) + "?>",
                  "<urlset xmlns=" + chr(34) + "http://www.sitemaps.org/schemas/sitemap/0.9" + chr(34) + ">"]
                 + urls + ["</urlset>"])
    (SITE / "sitemap.xml").write_text(sm, encoding="utf-8")

    lines = ["# " + cfg.get("title", "geosciplot"), "",
             cfg.get("subtitle", "") + "（" + SITE_URL + "）—— " + cfg.get("lede", ""),
             "", "## 核心页面", "",
             "- [图库首页](" + SITE_URL + "/)",
             "- [全站搜索](" + SITE_URL + "/search/)",
             "- [色彩实验](" + SITE_URL + "/color-lab/)（框选取色 + 颜色替换调色工具）",
             "", "## 全部图片（共 " + str(len(items)) + " 张）", ""]
    for it in items:
        tags = " · ".join(str(t) for t in it.get("tags", []))
        doi = str(it.get("doi") or "")
        added = str(it.get("added") or "")
        meta = " · ".join(x for x in [tags, doi, added] if x)
        line = "- [图 " + it["id"] + "](" + SITE_URL + "/" + it["id"] + "/)"
        lines.append(line + (" — " + meta if meta else ""))
    lines += ["", "## 说明", "",
              "- 图片本体由 jsDelivr / GitHub raw 分发，各详情页附原始论文 DOI 与上传日期",
              "- 图片元数据的机器可读版见 sitemap.xml"]
    (SITE / "llms.txt").write_text(nl.join(lines) + nl, encoding="utf-8")
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
    active = 0 if args.preview else int(cfg.get("activeSource", 0))
    active = 0 if args.preview else int(cfg.get("activeSource", 1))
    active = max(0, min(active, len(sources) - 1))

    # 过期的详情页目录 → 改名移入 site_trash/（绝不原地删除）。
    # 之前用 shutil.rmtree 清理，会触发 WorkBuddy 沙箱的批量删除保护
    # （SAFE_DELETE_BULK_CONFIRM_REQUIRED）导致构建失败；纯改名则无此问题。
    # site_trash/ 已 gitignore，偶尔手动清空即可。
    if SITE.exists():
        trash = ROOT / "site_trash"
        for d in SITE.iterdir():
            if d.is_dir() and d.name not in ("assets", "images", "search", "color-lab") and (d / "index.html").exists():
                trash.mkdir(parents=True, exist_ok=True)
                dest = trash / (d.name + "-" + str(int(time.time())))
                print(f"· 过期详情页 {d.name} → site_trash/（不删除）")
                try:
                    d.rename(dest)
                except OSError:
                    pass

    (SITE / "assets").mkdir(parents=True, exist_ok=True)
    GENERATED = {"style.css", "gallery.js", "gallery-data.js"}  # 由下方 write_text 生成，不做裸拷贝
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
        "window.GALLERY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")

    (SITE / "index.html").write_text(build_index(cfg, items), encoding="utf-8")
    search_dir = SITE / "search"
    search_dir.mkdir(parents=True, exist_ok=True)
    (search_dir / "index.html").write_text(build_search_page(cfg, items), encoding="utf-8")
    colorlab_dir = SITE / "color-lab"
    colorlab_dir.mkdir(parents=True, exist_ok=True)
    (colorlab_dir / "index.html").write_text(build_colorlab_page(cfg, items), encoding="utf-8")
    for i, it in enumerate(items):
        d = SITE / it["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_detail(cfg, items, i, abs_base=sources[active]["base"]), encoding="utf-8")
    build_seo_files(cfg, items, sources, active)

    # 404 页：noindex + 回首页/搜索入口（nginx 需 error_page 404 /404.html 配合）
    nl404 = chr(10)
    body404 = nl404.join([
        '<div class="v3-col px-6 py-24" style="text-align:center">',
        '  <p class="kicker">404</p>',
        '  <h1 style="font-size:clamp(36px,6vw,56px);margin:16px 0 12px">页面不存在</h1>',
        '  <p style="color:var(--dim)">你访问的地址可能已变更或从未存在。</p>',
        '  <p style="margin-top:24px"><a class="tbtn-inline" href="/" style="color:var(--accent)">返回图库首页</a> ｜ <a class="tbtn-inline" href="/search/" style="color:var(--accent)">全站搜索</a></p>',
        '</div>',
    ])
    (SITE / "404.html").write_text(page_shell(
        cfg,
        "页面不存在",
        body404,
        meta_desc="页面不存在",
        head_extra='<meta name="robots" content="noindex, nofollow">',
    ), encoding="utf-8")

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
