#!/usr/bin/env python3
"""GeoSciPlot 静态站生成器：读 meta/refs.json → 生成 site/ 纯静态站点。

用法：
    python scripts/build_site.py              # 生产构建（图片走 jsDelivr/raw/OSS 三源）
    python scripts/build_site.py --preview    # 本地预览（把 images/ 复制进 site/，源改本地）

产出：
    site/index.html              画廊首页（缩略图网格 + 分页 + 搜索 + 多维筛选 + 排序）
    site/{id}/index.html         每图详情页（原图 + 元信息 + 上下张）
    site/assets/style.css        样式
    site/assets/gallery.js       三源降级加载 + 分页/筛选/排序 + 统计打点

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

PAGE_SIZE = 30

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
    return " ".join([
        item.get("id", ""),
        item.get("doi") or "",
        str(item.get("added") or ""),
        " ".join(item.get("tags", [])),
    ]).lower()


CSS = """\
:root{--bg:#0d1117;--text:#e6edf3;--dim:#8b949e;--faint:#6e7681;--line:#1c2129;--line2:#30363d;--accent:#58a6ff;--card:#161b22;color-scheme:dark}
:root[data-theme=dark]{color-scheme:dark}
:root[data-theme=light]{--bg:#fff;--text:#1f2328;--dim:#59636e;--faint:#818b98;--line:#e8ebef;--line2:#d0d7de;--accent:#0969da;--card:#f6f8fa;color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.7 ui-sans-serif,system-ui,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
header.site{padding:72px 0 0}
.fab{position:fixed;right:16px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:9px;z-index:50}
.tbtn{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border:1px solid var(--line2);border-radius:50%;background:var(--card);color:var(--dim);cursor:pointer;transition:color .16s,border-color .16s,transform .16s}
.tbtn:hover{color:var(--accent);border-color:var(--accent);transform:scale(1.06)}
.tbtn svg{width:17px;height:17px;flex:none}
#topBtn{opacity:0;pointer-events:none}
#topBtn.show{opacity:1;pointer-events:auto}
@media (max-width:760px){.fab{right:10px;gap:7px}.tbtn{width:36px;height:36px}.tbtn svg{width:15px;height:15px}}
.tbtn .ic-sun{display:inline}.tbtn .ic-moon{display:none}
:root[data-theme=light] .tbtn .ic-sun{display:inline}:root[data-theme=light] .tbtn .ic-moon{display:none}
:root[data-theme=dark] .tbtn .ic-sun{display:none}:root[data-theme=dark] .tbtn .ic-moon{display:inline}
.kicker{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0}
h1{display:flex;align-items:center;gap:18px;font-size:clamp(44px,6.5vw,68px);line-height:1.08;letter-spacing:-.03em;margin:24px 0 0;font-weight:700}
h1 img.logo{height:clamp(44px,5.4vw,58px);width:auto;flex:none}
.lede{font-size:16px;color:var(--dim);max-width:52ch;margin:20px 0 0}
.gh-note{display:inline-flex;align-items:center;gap:9px;margin:18px 0 0;padding:9px 16px;border:1px solid var(--accent);border-left-width:3px;border-radius:6px;background:var(--card);font-size:13.5px;color:var(--text)}
.gh-note svg{width:16px;height:16px;flex:none;color:var(--accent)}
.meta-row{margin:28px 0 0;padding:14px 0;border-top:1px solid var(--line);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;color:var(--dim)}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:22px 0 6px}
.search{flex:1 1 260px;max-width:380px;padding:8px 12px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--text);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.search:focus{outline:none;border-color:var(--accent)}
.search::placeholder{color:var(--faint)}
select{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;padding:7px 9px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--dim)}
.reset{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;padding:7px 11px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--faint);cursor:pointer}
.reset:hover{color:var(--accent);border-color:var(--accent)}
#filters[hidden]{display:none}
.sorter{display:inline-flex;align-items:center;gap:2px;padding:3px;border:1px solid var(--line2);border-radius:999px;background:var(--card)}
.sorter button{display:inline-flex;align-items:center;gap:6px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px;padding:6px 13px;border:none;border-radius:999px;background:transparent;color:var(--dim);cursor:pointer;transition:color .15s,background-color .15s}
.sorter button:hover{color:var(--text)}
.sorter button[aria-pressed=true]{background:var(--accent);color:var(--bg)}
.sorter button svg{width:13px;height:13px;flex:none}
.dateinp{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;padding:6px 9px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--dim);color-scheme:dark light}
.fgroup{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:10px 0 0;padding-bottom:8px;border-bottom:1px solid var(--line)}
.flabel{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;color:var(--faint);min-width:44px;letter-spacing:.06em}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chips button{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;padding:4px 10px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--dim);cursor:pointer;transition:color .16s,border-color .16s}
.chips button:hover{color:var(--text)}
.chips button[aria-pressed=true]{color:var(--accent);border-color:var(--accent)}
/* 多列瀑布流：每列独立堆叠。改用 grid 的话同一行会被"最高的那张"定高，
   矮卡片下方必然空出一大片 —— 这正是之前空白多的根因 */
.grid{columns:4;column-gap:18px;margin-top:26px}
@media (max-width:1100px){.grid{columns:3}}
@media (max-width:760px){.grid{columns:2;column-gap:12px}h1{font-size:32px}}
.card{break-inside:avoid;display:block;margin:0 0 18px;border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--card);transition:border-color .16s}
.card:hover{border-color:var(--accent)}
.card img{display:block;width:100%;height:auto;background:var(--line)}
.card .cap{display:block;padding:7px 9px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;line-height:1.5;color:var(--faint)}
.card .cap .tags{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ph{display:flex;align-items:center;justify-content:center;min-height:120px;padding:18px;font-family:ui-monospace,monospace;font-size:11px;color:var(--faint);text-align:center}
.pgbar{display:flex;align-items:center;justify-content:center;gap:14px;margin:34px 0 0;padding-top:20px;border-top:1px solid var(--line)}
.pgbar button{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;padding:7px 14px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--dim);cursor:pointer}
.pgbar button:hover:not(:disabled){color:var(--accent);border-color:var(--accent)}
.pgbar button:disabled{opacity:.35;cursor:not-allowed}
.pgbar .info{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;color:var(--faint);min-width:132px;text-align:center}
.empty{padding:52px 0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;color:var(--faint);display:none;text-align:center}
footer.site{margin-top:56px;padding:24px 0 64px;border-top:1px solid var(--line);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;color:var(--faint);display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between}
figure.shot{margin:0;display:flex;justify-content:center;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
figure.shot img{max-width:100%;max-height:86vh;object-fit:contain;background:var(--line)}
dl.meta{display:grid;grid-template-columns:104px 1fr;gap:11px 18px;margin:36px 0 0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14.5px;line-height:1.7}
dl.meta dt{font-size:11.5px;color:var(--faint);padding-top:4px;letter-spacing:.06em}
dl.meta dd{margin:0;color:var(--text);word-break:break-all}
dl.meta dd .hl{color:var(--text)}
dl.meta dd a.tag{display:inline-block;margin:0 8px 8px 0;padding:3px 11px;border:1px solid var(--line2);border-radius:4px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;color:var(--dim);transition:color .16s,border-color .16s}
dl.meta dd a.tag:hover{color:var(--accent);border-color:var(--accent)}
.pager{display:flex;justify-content:space-between;gap:16px;margin:40px 0 0;padding-top:18px;border-top:1px solid var(--line);font-size:13px}
.pager a{color:var(--dim)}
.pager a:hover{color:var(--accent)}
.back{display:inline-block;margin:36px 0 20px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;color:var(--dim)}
.back:hover{color:var(--accent)}
h2.id-title{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:18px;font-weight:500;margin:0 0 20px;color:var(--dim);letter-spacing:.02em}
"""

JS = """\
(function () {
  var CFG = window.GALLERY, ITEMS = window.GALLERY_ITEMS || [], PAGE = window.GALLERY_PAGE || 48;
  if (!CFG) return;

  /* ── 三源降级：当前源失败就自动换下一个源 ── */
  function bind(img) {
    var rel = img.getAttribute("data-rel");
    var i = CFG.active;
    img.addEventListener("error", function () {
      i += 1;
      if (i < CFG.sources.length) {
        img.src = CFG.sources[i] + "/" + rel;
        img.setAttribute("data-source", CFG.sources[i]);
      } else {
        img.removeAttribute("src");
        var ph = document.createElement("div");
        ph.className = "ph";
        ph.textContent = "图片加载失败（图片托管于 GitHub，需具备 GitHub 访问能力）";
        img.parentNode.replaceChild(ph, img);
      }
    });
    img.src = CFG.sources[i] + "/" + rel;
    img.setAttribute("data-source", CFG.sources[i]);
  }

  /* 统计打点：所有页面（首页 + 详情页）都要执行。之前放在网格逻辑之后，
     详情页因没有 #grid 提前 return，打点从未跑过（被浏览一直为空的根因） */
  if (CFG.tracker && !location.hostname.match(/^(localhost|127\.0\.0\.1|)$/)) {
    try {
      if (navigator.doNotTrack === "1") return;
      fetch(CFG.tracker, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: "/geosciplot" + location.pathname, referrer: document.referrer || undefined }),
        keepalive: true,
      }).catch(function () {});
    } catch (e) {}
  }

  /* ── 每图浏览量（来自统计服务的按 path 计数） ── */
  var viewsEl = document.getElementById("views");
  if (viewsEl) {
    fetch((CFG.api || "") + "/api/v1/stats/views?prefix=/geosciplot/")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.items) throw 0;
        var map = {};
        d.items.forEach(function (x) { map[x.path.replace(/\\/$/, "")] = x.views; });
        var n = map["/geosciplot" + location.pathname.replace(/\\/$/, "")] || 0;
        viewsEl.textContent = n ? n + " 次" : "首次";
        viewsEl.style.color = "var(--text)";
      }).catch(function () { viewsEl.textContent = "—"; });
  }

  var themeBtn = document.getElementById("themeBtn");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var root = document.documentElement;
    // 默认暗色（不跟随系统偏好）；仅当访客手动切过才用其选择
    var light = root.getAttribute("data-theme") === "light";
    var t = light ? "dark" : "light";
    root.setAttribute("data-theme", t);
    try { localStorage.setItem("gsp-theme", t); } catch (e) {}
  });
  var topBtn = document.getElementById("topBtn");
  if (topBtn) {
    topBtn.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });
    var onScroll = function () { topBtn.classList.toggle("show", window.scrollY > 260); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  var grid = document.getElementById("grid");
  if (!grid) { document.querySelectorAll("img[data-rel]").forEach(bind); return; }
  grid.querySelectorAll("img[data-rel]").forEach(bind);   // 首屏静态卡片也要绑降级

  /* ── 分页 + 筛选 + 排序 ── */
  var state = { q: "", tag: "*", from: "", to: "", sort: "added", page: 1, per: PAGE };
  try {
    var savedPer = parseInt(localStorage.getItem("gsp-per"), 10);
    if ([20, 30, 50].indexOf(savedPer) > -1) state.per = savedPer;   // 仅接受合法档位，旧值自动回默认 30
    if (localStorage.getItem("gsp-sort")) { state.sort = localStorage.getItem("gsp-sort"); }
  } catch (e) {}
  var q = document.getElementById("q");
  var empty = document.getElementById("empty");
  var count = document.getElementById("count");
  var info = document.getElementById("pageinfo");
  var prev = document.getElementById("prev");
  var next = document.getElementById("next");

  function pass(it) {
    if (state.tag !== "*" && (it.tg || []).indexOf(state.tag) === -1) return false;
    if (state.from && (it.ad || "") < state.from) return false;
    if (state.to && (it.ad || "") > state.to) return false;
    if (state.q && (it.se || "").indexOf(state.q) === -1) return false;
    return true;
  }
  function cmp(a, b) {
    if (state.sort === "random") {
      if (a._rk === undefined) a._rk = Math.random();
      if (b._rk === undefined) b._rk = Math.random();
      return a._rk - b._rk;
    }
    var dir = state.sort === "added_asc" ? 1 : -1;
    var aa = (a.ad || ""), ab = (b.ad || "");
    if (aa !== ab) return (aa < ab ? -1 : 1) * dir;
    // 同日期内按 id 排：与 prepare.py 的静态首屏顺序（reverse）保持一致
    return (a.id || "").localeCompare(b.id || "") * dir;
  }
  function cardNode(it) {
    var a = document.createElement("a");
    a.className = "card";
    a.href = it.id + "/";
    a.setAttribute("data-id", it.id);
    var img = document.createElement("img");
    img.setAttribute("data-rel", it.rel);
    img.alt = "图 " + it.id;
    img.loading = "lazy";
    a.appendChild(img);
    var cap = document.createElement("span");
    cap.className = "cap";
    var tagsEl = document.createElement("span");
    tagsEl.className = "tags";
    tagsEl.textContent = it.sub || "—";
    cap.appendChild(tagsEl);
    a.appendChild(cap);
    a.title = it.sub || "";
    bind(img);
    return a;
  }
  function perSize(list) { return state.per > 0 ? state.per : (list.length || 1); }
  function render() {
    var list = ITEMS.filter(pass).sort(cmp);
    var per = perSize(list);
    var pages = Math.max(1, Math.ceil(list.length / per));
    if (state.page > pages) state.page = pages;
    if (state.page < 1) state.page = 1;
    var slice = list.slice((state.page - 1) * per, state.page * per);
    grid.innerHTML = "";
    slice.forEach(function (it) { grid.appendChild(cardNode(it)); });
    if (info) info.textContent = "第 " + state.page + " / " + pages + " 页";
    if (prev) prev.disabled = state.page <= 1;
    if (next) next.disabled = state.page >= pages;
    if (count) {
      var filtered = state.q || state.tag !== "*" || state.from || state.to;
      count.textContent = filtered ? "匹配 " + list.length + " / " + ITEMS.length + " 张"
                                   : "共 " + ITEMS.length + " 张";
    }
    if (empty) empty.style.display = list.length ? "none" : "block";
    syncFilterBtn();
  }
  function resetPage() { state.page = 1; render(); }

  function bindChips(sel) {
    var box = document.querySelector(sel);
    if (!box) return;
    box.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        state[box.getAttribute("data-key")] = b.getAttribute("data-v");
        box.querySelectorAll("button").forEach(function (x) {
          x.setAttribute("aria-pressed", String(x === b));
        });
        resetPage();
      });
    });
  }
  ["[data-key=tag]"].forEach(bindChips);

  if (q) {
    q.addEventListener("input", function () { state.q = q.value.trim().toLowerCase(); resetPage(); });
    q.addEventListener("keydown", function (e) { if (e.key === "Escape") { q.value = ""; state.q = ""; resetPage(); } });
  }
  var sortseg = document.getElementById("sortseg");
  if (sortseg) {
    if (["added", "added_asc", "random"].indexOf(state.sort) === -1) state.sort = "added";
    var sortBtns = sortseg.querySelectorAll("button");
    sortBtns.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-sort") === state.sort));
      b.addEventListener("click", function () {
        state.sort = b.getAttribute("data-sort");
        try { localStorage.setItem("gsp-sort", state.sort); } catch (e) {}
        sortBtns.forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        resetPage();
      });
    });
  }
  var fFrom = document.getElementById("f-from"), fTo = document.getElementById("f-to");
  if (fFrom) fFrom.addEventListener("change", function () { state.from = fFrom.value; resetPage(); });
  if (fTo) fTo.addEventListener("change", function () { state.to = fTo.value; resetPage(); });
  if (prev) prev.addEventListener("click", function () { state.page -= 1; render(); });
  if (next) next.addEventListener("click", function () { state.page += 1; render(); });

  var reset = document.getElementById("reset");
  if (reset) reset.addEventListener("click", function () {
    state = { q: "", tag: "*", from: "", to: "", sort: state.sort, page: 1 };
    var fF = document.getElementById("f-from"), fT = document.getElementById("f-to");
    if (fF) fF.value = "";
    if (fT) fT.value = "";
    if (q) q.value = "";
    document.querySelectorAll(".chips").forEach(function (box) {
      box.querySelectorAll("button").forEach(function (x, i) {
        x.setAttribute("aria-pressed", String(i === 0));
      });
    });
    render();
  });

  /* ── 每页显示数量 ── */
  var perSel = document.getElementById("perpage");
  if (perSel) {
    perSel.value = String(state.per);
    perSel.addEventListener("change", function () {
      state.per = parseInt(perSel.value, 10) || 0;
      try { localStorage.setItem("gsp-per", String(state.per)); } catch (e) {}
      resetPage();
    });
  }

  /* ── 筛选区折叠（状态记在 localStorage） ── */
  var filterBtn = document.getElementById("filterBtn");
  var filterBox = document.getElementById("filters");
  function activeFilters() {
    var parts = [];
    if (state.tag !== "*") parts.push("标签 " + state.tag);
    if (state.from || state.to) parts.push("上传 " + (state.from || "…") + " ~ " + (state.to || "…"));
    if (state.q) parts.push("搜索 " + state.q);
    return parts;
  }
  function syncFilterBtn() {
    if (!filterBtn || !filterBox) return;
    var open = !filterBox.hasAttribute("hidden");
    var list = activeFilters();
    filterBtn.textContent = (open ? "筛选 ▴" : "筛选 ▾") + (list.length ? " · " + list.length : "");
    filterBtn.setAttribute("aria-expanded", String(open));
    filterBtn.title = list.length ? "当前筛选：" + list.join(" / ") : "展开或收起筛选条件";
  }
  if (filterBox) {
    var collapsed = false;
    try { collapsed = localStorage.getItem("gsp-filters") === "hidden"; } catch (e) {}
    if (collapsed) filterBox.setAttribute("hidden", "");
  }
  if (filterBtn && filterBox) {
    filterBtn.addEventListener("click", function () {
      var open = !filterBox.hasAttribute("hidden");
      if (open) filterBox.setAttribute("hidden", ""); else filterBox.removeAttribute("hidden");
      try { localStorage.setItem("gsp-filters", open ? "hidden" : "shown"); } catch (e) {}
      syncFilterBtn();
    });
  }

  /* 支持带参数的链接（标签跳转 / 分享筛选结果）：/?tag=海冰&journal=Nature */
  var applied = false;
  try {
    var params = new URLSearchParams(location.search);
    ["q", "tag", "from", "to"].forEach(function (k) {
      var v = params.get(k);
      if (!v) return;
      applied = true;
      if (k === "q") {
        state.q = v.trim().toLowerCase();
        if (q) q.value = v;
      } else {
        state[k] = v;
        var box = document.querySelector('.chips[data-key="' + k + '"]');
        if (box) {
          box.querySelectorAll("button").forEach(function (x) {
            x.setAttribute("aria-pressed", String(x.getAttribute("data-v") === v));
          });
        }
      }
    });
  } catch (e) {}

  /* 首屏卡片是构建时静态输出的（对爬虫友好）。只有当"每页数量/排序"被用户改过、
     或链接带了筛选参数时，才用 JS 重新渲染，保证 DOM 与状态一致。
     （不重渲染的默认情况下，静态输出与 JS 首屏完全一致） */
  var needRender = applied || state.per !== PAGE || state.sort !== "added";
  if (needRender) {
    state.page = 1;
    render();
  } else {
    var per0 = perSize(ITEMS);
    if (info) info.textContent = "第 1 / " + Math.max(1, Math.ceil(ITEMS.length / per0)) + " 页";
    if (next) next.disabled = ITEMS.length <= per0;
    syncFilterBtn();
  }

})();
"""


def page_shell(cfg: dict, title: str, body: str, depth: int = 0, gh_url: str = "") -> str:
    up = "../" if depth else ""
    gh = gh_url or "https://github.com/{}/{}".format(
        cfg.get("owner") or "OWNER", cfg["repo"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>geosciplot</title>
<meta name="description" content="{esc(cfg['subtitle'])} —— {esc(cfg['lede'])}">
<link rel="stylesheet" href="{up}assets/style.css">
<link rel="icon" type="image/png" href="{up}assets/favicon.png">
<script>try{{var t=localStorage.getItem("gsp-theme");if(t)document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
</head>
<body>
<div class="wrap">
<div class="fab"><a class="tbtn" href="https://www.zbhgis.com" title="返回主站 浩瀚地学"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 8 8 3l5.5 5M4 7v6h8V7"/></svg></a><a class="tbtn" href="{gh}" rel="noopener" target="_blank" title="在 GitHub 查看（详情页直达当前图片）"><svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg></a><button type="button" class="tbtn" id="themeBtn" title="切换明暗主题" aria-label="切换明暗主题"><svg class="ic-sun" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1"/></svg><svg class="ic-moon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.5 9.5A6 6 0 0 1 6.5 2.5a6 6 0 1 0 7 7z"/></svg></button><button type="button" class="tbtn" id="topBtn" title="回到顶部" aria-label="回到顶部"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13.5v-9M4.5 8 8 4.5 11.5 8"/></svg></button></div>
{body}
<footer class="site">
  <span>{esc(cfg['title'])} · {esc(cfg['subtitle'])}</span>
  <span><a href="https://github.com/{esc(cfg.get('owner') or 'OWNER')}/{esc(cfg['repo'])}" rel="noopener">GitHub 仓库</a> · 图表版权归各原作者</span>
</footer>
</div>
<script src="{up}assets/gallery.js"></script>
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
    data = [{
        "id": it["id"],
        "rel": it.get("thumb", ""),
        "ad": it.get("added") or "",
        "tg": it.get("tags") or [],
        "sub": " · ".join(it.get("tags") or []),
        "se": haystack(it),
    } for it in items]

    ghsvg = ('<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">'
            '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>')
    body = f"""<header class="site">
  <h1><img class="logo" src="assets/logo.png" alt="GeoSciPlot logo">{esc(cfg['title'])}</h1>
  <a class="gh-note" href="https://github.com/{esc(cfg.get('owner') or 'OWNER')}/{esc(cfg['repo'])}" rel="noopener" target="_blank" title="在 GitHub 查看图片源文件">{ghsvg}<span>图片存储于 <b>GitHub</b>，访问需具备 GitHub 访问能力（点此查看仓库）</span></a>
  <p class="lede">{esc(cfg['lede'])}</p>
  <div class="meta-row"><span id="count">共 {len(items)} 张</span> · {len(tag_counter)} 个标签 · {len(addeds)} 个上传日期 · 点击查看原图</div>
</header>

<div class="toolbar">
  <input id="q" class="search" type="search" placeholder="搜索 id / DOI / 标签 / 标题…" autocomplete="off">
  <span class="sorter" id="sortseg" role="group" aria-label="排序">
    <button type="button" data-sort="added" aria-pressed="true" title="上传日期 新→旧"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5v8M4.8 7.3 8 10.5l3.2-3.2M3 13.5h10"/></svg><span>新到旧</span></button>
    <button type="button" data-sort="added_asc" aria-pressed="false" title="上传日期 旧→新"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13.5v-8M4.8 8.7 8 5.5l3.2 3.2M3 2.5h10"/></svg><span>旧到新</span></button>
    <button type="button" data-sort="random" aria-pressed="false" title="随机排序"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 4.5h2.2c3.2 0 4.6 7 7.6 7H14M2 11.5h2.2c1.3 0 2.2-.9 3-2M8.8 6.5c.8-1.1 1.7-2 3-2H14M12.3 3l1.7 1.5L12.3 6M12.3 10l1.7 1.5-1.7 1.5"/></svg><span>随机</span></button>
  </span>
  <select id="perpage" aria-label="每页数量">
    <option value="20">每页 20</option>
    <option value="30" selected>每页 30</option>
    <option value="50">每页 50</option>
  </select>
  <button id="filterBtn" class="reset" aria-expanded="true" aria-controls="filters">筛选 ▴</button>
  <button id="reset" class="reset">重置筛选</button>
</div>

<div id="filters">
{filter_row("标签", chips(tag_counter, "tag", "全部"))}
{filter_row("上传", '<input type="date" id="f-from" class="dateinp">\n'
  + ' <span class="flabel" style="min-width:auto">至</span>\n'
  + '<input type="date" id="f-to" class="dateinp">')}
</div>

<main class="grid" id="grid">
{chr(10).join(card_html(it) for it in first_page)}
</main>
<p class="empty" id="empty">没有符合条件的图片</p>

<div class="pgbar">
  <button id="prev" disabled>← 上一页</button>
  <span class="info" id="pageinfo">第 1 / {max(1, -(-len(items) // PAGE_SIZE))} 页</span>
  <button id="next" disabled>下一页 →</button>
</div>

<script>window.GALLERY_PAGE = {PAGE_SIZE};
window.GALLERY_ITEMS = {json.dumps(data, ensure_ascii=False, separators=(",", ":"))};</script>"""
    return page_shell(cfg, cfg["subtitle"], body)


def build_detail(cfg: dict, items: list[dict], idx: int) -> str:
    it = items[idx]
    prev_it = items[idx - 1] if idx > 0 else None
    next_it = items[idx + 1] if idx < len(items) - 1 else None
    w, h = it.get("width", 0), it.get("height", 0)

    pager = ['<div class="pager">']
    pager.append(f'<a href="../{esc(prev_it["id"])}/">← 上一张</a>' if prev_it else "<span></span>")
    pager.append(f'<a href="../{esc(next_it["id"])}/">下一张 →</a>' if next_it else "<span></span>")
    pager.append("</div>")

    # 标签做成可跳转：点击回到首页并自动套用该标签的搜索
    tags = it.get("tags", [])
    if tags:
        tags_html = "".join(
            f'<a class="tag" href="/?tag={quote(str(t), safe="")}">{esc(t)}</a>' for t in tags
        )
    else:
        tags_html = "—"

    doi = str(it.get("doi") or "").strip()
    if doi:
        doi_html = f'<a href="https://doi.org/{esc(doi)}" rel="noopener" target="_blank">{esc(doi)}</a>'
    else:
        doi_html = "—"

    body = f"""<a class="back" href="../">← 返回全部</a>
<h2 class="id-title">图 {esc(it['id'])}</h2>
<figure class="shot">
  <img data-rel="{esc(it.get('full'))}" alt="图 {esc(it['id'])}" width="{w}" height="{h}">
</figure>
<dl class="meta">
  <dt>ID</dt><dd class="hl">{esc(it['id'])}</dd>
  <dt>DOI</dt><dd>{doi_html}</dd>
  <dt>上传日期</dt><dd>{esc(it.get('added'))}</dd>
  <dt>被浏览</dt><dd><span id="views">…</span></dd>
  <dt>标签</dt><dd>{tags_html}</dd>
</dl>
{chr(10).join(pager)}"""
    gh_img = "https://github.com/{}/{}/blob/{}/images/{}".format(
        cfg.get("owner") or "OWNER", cfg["repo"], cfg.get("branch", "main"), it.get("full", ""))
    return page_shell(cfg, f"图 {it['id']}", body, depth=1, gh_url=gh_img)


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
            if d.is_dir() and d.name not in ("assets", "images") and (d / "index.html").exists():
                trash.mkdir(parents=True, exist_ok=True)
                dest = trash / (d.name + "-" + str(int(time.time())))
                print(f"· 过期详情页 {d.name} → site_trash/（不删除）")
                try:
                    d.rename(dest)
                except OSError:
                    pass

    (SITE / "assets").mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "assets_src").glob("*"):
        if f.is_file():
            shutil.copyfile(f, SITE / "assets" / f.name)
    if args.preview:
        # 仅预览构建复制图片副本（生产走 GitHub 链接，本站不分发图片）
        dst = SITE / "images"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(IMAGES, dst)
        n = sum(1 for p in dst.rglob("*") if p.is_file())
        print(f"· 预览模式：images/ → site/images/（{n} 个文件）")

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

    (SITE / "index.html").write_text(build_index(cfg, items), encoding="utf-8")
    for i, it in enumerate(items):
        d = SITE / it["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_detail(cfg, items, i), encoding="utf-8")

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
