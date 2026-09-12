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
  · 分页：每页 48 张，只渲染当前页 → 只请求当前页的缩略图（1000 张也不会一次拉 23MB）
  · 首页首屏的卡片由 Python 直接输出静态 HTML（对爬虫/AI 引擎友好），
    翻页与筛选时改由 JS 渲染
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "gallery.config.json"
REFS_JSON = ROOT / "meta" / "refs.json"
SITE = ROOT / "site"
IMAGES = ROOT / "images"

PAGE_SIZE = 48

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


def build_sources(cfg: dict) -> list[dict]:
    owner = cfg.get("owner") or "OWNER"
    repo = cfg["repo"]
    branch = cfg.get("branch", "main")
    oss = cfg.get("oss", {})
    bucket = oss.get("bucket") or "BUCKET"
    region = oss.get("region", "oss-cn-hangzhou")
    return [
        {"id": "local", "label": "本地（仅预览）", "base": "/images"},
        {"id": "jsdelivr", "label": "jsDelivr", "base": f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/images"},
        {"id": "raw", "label": "GitHub raw", "base": f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/images"},
        {"id": "oss", "label": "OSS 兜底", "base": f"https://{bucket}.{region}.aliyuncs.com/{repo.lower()}/images"},
    ]


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def year_of(item: dict) -> str:
    p = str(item.get("published") or "")
    return p[:4] if len(p) >= 4 and p[:4].isdigit() else ""


def caption_of(item: dict) -> str:
    """卡片副标题：期刊 · 年份（都没有就留空）。"""
    parts = [p for p in [item.get("journal") or "", year_of(item)] if p]
    return " · ".join(parts)


def haystack(item: dict) -> str:
    return " ".join([
        item.get("id", ""),
        item.get("journal") or "",
        str(item.get("published") or ""),
        str(item.get("added") or ""),
        " ".join(item.get("tags", [])),
        item.get("desc") or "",
    ]).lower()


CSS = """\
:root{--bg:#0d1117;--text:#e6edf3;--dim:#8b949e;--faint:#6e7681;--line:#1c2129;--line2:#30363d;--accent:#58a6ff;--card:#161b22}
@media (prefers-color-scheme:light){:root{--bg:#fff;--text:#1f2328;--dim:#59636e;--faint:#818b98;--line:#e8ebef;--line2:#d0d7de;--accent:#0969da;--card:#f6f8fa}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.7 ui-sans-serif,system-ui,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
header.site{padding:72px 0 0}
.kicker{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0}
h1{font-size:clamp(44px,6.5vw,68px);line-height:1.08;letter-spacing:-.03em;margin:24px 0 0;font-weight:700}
.lede{font-size:16px;color:var(--dim);max-width:52ch;margin:20px 0 0}
.meta-row{margin:28px 0 0;padding:14px 0;border-top:1px solid var(--line);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;color:var(--dim)}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:22px 0 6px}
.search{flex:1 1 260px;max-width:380px;padding:8px 12px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--text);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.search:focus{outline:none;border-color:var(--accent)}
.search::placeholder{color:var(--faint)}
select{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;padding:7px 9px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--dim)}
.reset{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;padding:7px 11px;border:1px solid var(--line2);border-radius:4px;background:transparent;color:var(--faint);cursor:pointer}
.reset:hover{color:var(--accent);border-color:var(--accent)}
#filters[hidden]{display:none}
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
dl.meta{display:grid;grid-template-columns:96px 1fr;gap:9px 16px;margin:36px 0 0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.65}
dl.meta dt{font-size:10.5px;color:var(--faint);padding-top:3px;letter-spacing:.06em}
dl.meta dd{margin:0;color:var(--text);word-break:break-all}
dl.meta dd .hl{color:var(--text)}
dl.meta dd a.tag{display:inline-block;margin:0 6px 6px 0;padding:2px 9px;border:1px solid var(--line2);border-radius:4px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px;color:var(--dim);transition:color .16s,border-color .16s}
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
        ph.textContent = "图片加载失败（所有源均不可用）";
        img.parentNode.replaceChild(ph, img);
      }
    });
    img.src = CFG.sources[i] + "/" + rel;
    img.setAttribute("data-source", CFG.sources[i]);
  }
  }
  }
  }
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

  var grid = document.getElementById("grid");
  if (!grid) { document.querySelectorAll("img[data-rel]").forEach(bind); return; }
  grid.querySelectorAll("img[data-rel]").forEach(bind);   // 首屏静态卡片也要绑降级

  /* ── 分页 + 筛选 + 排序 ── */
  var state = { q: "", tag: "*", journal: "*", pub: "*", added: "*", sort: "added", page: 1, per: PAGE };
  try {
    var savedPer = parseInt(localStorage.getItem("gsp-per"), 10);
    if (savedPer === 0 || savedPer >= 12) state.per = savedPer;   // 0 = 显示全部
    if (localStorage.getItem("gsp-sort")) { state.sort = localStorage.getItem("gsp-sort"); }
  } catch (e) {}
  var q = document.getElementById("q");
  var sortSel = document.getElementById("sort");
  var empty = document.getElementById("empty");
  var count = document.getElementById("count");
  var info = document.getElementById("pageinfo");
  var prev = document.getElementById("prev");
  var next = document.getElementById("next");

  function pass(it) {
    if (state.tag !== "*" && (it.tg || []).indexOf(state.tag) === -1) return false;
    if (state.journal !== "*" && (it.jo || "—") !== state.journal) return false;
    if (state.pub !== "*" && ((it.pu || "").slice(0, 4) || "—") !== state.pub) return false;
    if (state.added !== "*" && (it.ad || "—") !== state.added) return false;
    if (state.q && (it.se || "").indexOf(state.q) === -1) return false;
    return true;
  }
  function cmp(a, b) {
    if (state.sort === "published") {
      var pa = (a.pu || ""), pb = (b.pu || "");
      if (pa !== pb) return pa < pb ? 1 : -1;
    } else {
      var aa = (a.ad || ""), ab = (b.ad || "");
      if (aa !== ab) return aa < ab ? 1 : -1;
    }
    return (a.id || "").localeCompare(b.id || "");
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
      var filtered = state.q || state.tag !== "*" || state.journal !== "*" || state.pub !== "*" || state.added !== "*";
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
  ["[data-key=tag]", "[data-key=journal]", "[data-key=pub]", "[data-key=added]"].forEach(bindChips);

  if (q) {
    q.addEventListener("input", function () { state.q = q.value.trim().toLowerCase(); resetPage(); });
    q.addEventListener("keydown", function (e) { if (e.key === "Escape") { q.value = ""; state.q = ""; resetPage(); } });
  }
  if (sortSel) {
    sortSel.value = state.sort;
    sortSel.addEventListener("change", function () {
      state.sort = sortSel.value;
      try { localStorage.setItem("gsp-sort", state.sort); } catch (e) {}
      resetPage();
    });
  }
  if (prev) prev.addEventListener("click", function () { state.page -= 1; render(); });
  if (next) next.addEventListener("click", function () { state.page += 1; render(); });

  var reset = document.getElementById("reset");
  if (reset) reset.addEventListener("click", function () {
    state = { q: "", tag: "*", journal: "*", pub: "*", added: "*", sort: state.sort, page: 1 };
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
    if (state.journal !== "*") parts.push("期刊 " + state.journal);
    if (state.pub !== "*") parts.push("发表 " + state.pub);
    if (state.added !== "*") parts.push("上传 " + state.added);
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

  /* ── 每图浏览量（来自统计服务的按 path 计数） ── */
  var viewsEl = document.getElementById("views");
  if (viewsEl && CFG.api) {
    fetch(CFG.api + "/api/v1/stats/views?prefix=/geosciplot/")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.items) return;
        var map = {};
        d.items.forEach(function (x) { map[x.path.replace(/\\/$/, "")] = x.views; });
        var n = map["/geosciplot" + location.pathname.replace(/\\/$/, "")] || 0;
        viewsEl.textContent = n ? n + " 次" : "首次";
        viewsEl.style.color = "var(--text)";
      }).catch(function () {});
  }

  /* 支持带参数的链接（标签跳转 / 分享筛选结果）：/?tag=海冰&journal=Nature */
  var applied = false;
  try {
    var params = new URLSearchParams(location.search);
    ["q", "tag", "journal", "pub", "added"].forEach(function (k) {
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


def page_shell(cfg: dict, title: str, body: str, depth: int = 0) -> str:
    up = "../" if depth else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(cfg['title'])}</title>
<meta name="description" content="{esc(cfg['subtitle'])} —— {esc(cfg['lede'])}">
<link rel="stylesheet" href="{up}assets/style.css">
</head>
<body>
<div class="wrap">
{body}
<footer class="site">
  <span>{esc(cfg['title'])} · {esc(cfg['subtitle'])}</span>
  <span><a href="https://github.com/{esc(cfg.get('owner') or 'OWNER')}/{esc(cfg['repo'])}" rel="noopener">GitHub 仓库</a> · 图表版权归各原作者，详见各图说明</span>
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
    journals = flat([it.get("journal") for it in items])
    pubs = flat([year_of(it) for it in items])
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
        "jo": it.get("journal") or "",
        "pu": it.get("published") or "",
        "ad": it.get("added") or "",
        "tg": it.get("tags") or [],
        "sub": " · ".join(it.get("tags") or []),
        "se": haystack(it),
    } for it in items]

    body = f"""<header class="site">
  <h1>{esc(cfg['title'])}</h1>
  <p class="lede">{esc(cfg['lede'])}</p>
  <div class="meta-row"><span id="count">共 {len(items)} 张</span> · {len(journals)} 种期刊 · {len(tag_counter)} 个标签 · {len(addeds)} 个上传日期 · 点击查看原图</div>
</header>

<div class="toolbar">
  <input id="q" class="search" type="search" placeholder="搜索 id / 期刊 / 标签 / 说明…" autocomplete="off">
  <select id="sort" aria-label="排序">
    <option value="added">按上传日期（新→旧）</option>
    <option value="published">按论文发表时间（新→旧）</option>
  </select>
  <select id="perpage" aria-label="每页数量">
    <option value="24">每页 24</option>
    <option value="48" selected>每页 48</option>
    <option value="96">每页 96</option>
    <option value="0">显示全部</option>
  </select>
  <button id="filterBtn" class="reset" aria-expanded="true" aria-controls="filters">筛选 ▴</button>
  <button id="reset" class="reset">重置筛选</button>
</div>

<div id="filters">
{filter_row("标签", chips(tag_counter, "tag", "全部"))}
{filter_row("期刊", chips(journals, "journal", "全部"))}
{filter_row("发表", chips(pubs, "pub", "全部"))}
{filter_row("上传", chips(addeds, "added", "全部"))}
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

    body = f"""<a class="back" href="../">← 返回全部</a>
<h2 class="id-title">图 {esc(it['id'])}</h2>
<figure class="shot">
  <img data-rel="{esc(it.get('full'))}" alt="图 {esc(it['id'])}" width="{w}" height="{h}">
</figure>
<dl class="meta">
  <dt>ID</dt><dd class="hl">{esc(it['id'])}</dd>
  <dt>期刊</dt><dd>{esc(it.get('journal') or '—')}</dd>
  <dt>论文发表</dt><dd>{esc(it.get('published') or '—')}</dd>
  <dt>上传日期</dt><dd>{esc(it.get('added'))}</dd>
  <dt>被浏览</dt><dd><span id="views">…</span></dd>
  <dt>标签</dt><dd>{tags_html}</dd>
</dl>
{chr(10).join(pager)}"""
    return page_shell(cfg, f"图 {it['id']}", body, depth=1)


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

    sources = build_sources(cfg)
    active = 0 if args.preview else int(cfg.get("activeSource", 1))
    active = max(0, min(active, len(sources) - 1))

    # 清掉上一次的详情页目录，避免残留（入口 id 目录）
    if SITE.exists():
        for d in SITE.iterdir():
            if d.is_dir() and d.name not in ("assets", "images") and (d / "index.html").exists():
                shutil.rmtree(d, ignore_errors=True)

    (SITE / "assets").mkdir(parents=True, exist_ok=True)
    if args.preview:
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
