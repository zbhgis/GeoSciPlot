"""GeoSciPlot 视图层：页面骨架、导航与各路由的 HTML 模板。

从 build_site.py 抽出的纯前端部分——只负责把数据拼成 HTML，不做文件读取、
数据解析与写盘。构建/编排逻辑留在 build_site.py，资源文件（CSS/JS）在
assets_src/。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from urllib.parse import quote

from site_common import PAGE_SIZE, ROOT, SCOPE_TAGS, SITE_URL, asset_ver, doi_bare, esc

# 作者实体：与主站 /about 的 Person 共用同一 URL 与 sameAs，把子域内容归因到
# 同一作者（E-E-A-T / GEO）。站点是品牌，publisher 仍用 Organization。
AUTHOR_LD = {
    "@type": "Person",
    "name": "zbhgis 浩瀚地学",
    "url": "https://www.zbhgis.com/about",
    "image": "https://www.zbhgis.com/avatar.jpg",
    "sameAs": ["https://github.com/zbhgis", "https://zbhgis.github.io",
               "https://zbhgis.blog.csdn.net"],
}


def ld_json(obj) -> str:
    """JSON-LD 序列化唯一出口：把 "<" 统一转成 \\u003c。

    标题/标签/图注里一旦出现 "</script>"，内嵌脚本会提前闭合——整块结构化数据
    静默失效，页面也可能被破坏。首页与详情页曾直接 json.dumps，与其余页不一致，
    这里收敛成一个函数，避免以后再漏。
    """
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


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

# 指南针图标（lucide compass）：菜单「制图经验」入口——制图/方位意象，与调色板同风格
ICO_GUIDE = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
             '<circle cx="12" cy="12" r="10"/>'
             '<polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>')

# 页面骨架与导航标记独立成文件（与管理台 admin_ui.html 同一种约定）：
# 模板只放静态标记，[[TOKEN]] 由 Python 在构建期单趟替换。
TEMPLATE_DIR = ROOT / "templates"
_TEMPLATES: dict[str, str] = {}


def _tpl(name: str) -> str:
    if name not in _TEMPLATES:
        _TEMPLATES[name] = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    return _TEMPLATES[name]


def _render(name: str, **values) -> str:
    """单趟替换 [[TOKEN]]：替换进去的内容不会被二次解析。"""
    return re.sub(r"\[\[([A-Z0-9_]+)\]\]",
                  lambda m: str(values.get(m.group(1), m.group(0))), _tpl(name))


def nav_html(cfg: dict, up: str = "", active: str = "") -> str:
    """顶部菜单栏：整体移植自 MacroBiodiv 站点的 .mnav（样式同源）。
    「色彩实验」（/color-lab/）与「全站统计」（/statistics/）已实装；
    active 传页面对应的菜单键（如 "stats" / "about"）时该项 accent 常亮并带 aria-current。"""
    ico_stat = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 20V10M12 20V4M6 20v-4"/></svg>')
    ico_about = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/>'
                 '<path d="M12 16v-4"/><path d="M12 8h.01"/></svg>')
    ico_caret = ('<svg class="mnav-more-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>')
    ico_globe = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/>'
                 '<path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>')
    # MacroBiodiv 入口：lucide leaf（生命/多样性意象，与其新芽 logo 同语）——
    # 链接同主站 zbhgis.com「更多」下拉；此前用 globe，与 zbhgis 入口的地球并排易混淆
    ico_mb = ('<svg class="mnav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/>'
              '<path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/></svg>')
    ico_menu = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>')
    brand = esc(cfg.get("title") or "GeoSciPlot")
    brand_href = up if up else "./"   # 首页 = 当前页（./），子页 = 上一级（../），都回到图库首页
    # 当前页菜单项：accent 常亮 + aria-current（对齐 MacroBiodiv /statistics/ 的做法）
    st_attr = ('data-active="true" aria-current="page"' if active == "stats"
               else 'data-active="false"')
    ab_attr = ('data-active="true" aria-current="page"' if active == "about"
               else 'data-active="false"')
    gd_attr = ('data-active="true" aria-current="page"' if active == "guide"
               else 'data-active="false"')
    return _render(
        "nav.html",
        UP=up, BRAND=brand, BRAND_HREF=brand_href, V_FAV=asset_ver("favicon.png"),
        ST_ATTR=st_attr, AB_ATTR=ab_attr, GD_ATTR=gd_attr,
        ICO_PALETTE=ICO_PALETTE, ICO_GUIDE=ICO_GUIDE, ICO_STAT=ico_stat,
        ICO_ABOUT=ico_about, ICO_CARET=ico_caret, ICO_GLOBE=ico_globe,
        ICO_MB=ico_mb, ICO_MENU=ico_menu,
    )


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
    extra_assets: list[str] | None = None,
    active_nav: str = "",
    up_override: str | None = None,
    bare: bool = False,
) -> str:
    # up_override：错误页专用。404 由 nginx error_page 内部重定向，浏览器地址
    # 停留在原始路径（可能是 /a/b/ 任意深度），相对资源路径必然断链，只有
    # 根绝对路径在任何深度都成立
    up = up_override if up_override is not None else ("../" * depth)
    gh = gh_url or "https://github.com/{}/{}".format(
        cfg.get("owner") or "OWNER", cfg["repo"])
    desc = meta_desc or f"{cfg['subtitle']} —— {cfg['lede']}"
    og_url = og_url or (SITE_URL + ("/" if not depth else ""))
    # 无图页（首页/工具页）的 og:image 用站点 logo 兜底：分享卡片无图就是灰底块。
    # 详情页的 og:image 在 head_extra 里（带尺寸），此处不注入避免重复
    if not og_image and "og:image" not in head_extra:
        og_image = SITE_URL + "/assets/logo.png?v=" + asset_ver("logo.png")
    og_img = f'\n<meta property="og:image" content="{esc(og_image)}">' if og_image else ""
    # Twitter/X 卡片：详情页的 og:image 在 head_extra 里（含尺寸与完整 twitter 组），
    # 这里让位避免 twitter:card 重复输出；其余页面按有无 og_image 出大图/摘要卡
    tw = ""
    if "og:image" not in head_extra:
        tw_card = "summary_large_image" if og_image else "summary"
        tw = (f'\n<meta name="twitter:card" content="{tw_card}">'
              f'\n<meta name="twitter:title" content="{esc(title)}">'
              f'\n<meta name="twitter:description" content="{esc(desc[:200])}">')
        if og_image:
            tw += f'\n<meta name="twitter:image" content="{esc(og_image)}">'
    # bare=True（制图经验文章页）：正文不进 .wrap（自带 1400 三栏容器），仅 footer 包一层
    body_outer = body if bare else ""
    body_inner = "" if bare else body
    extra_scripts = "".join(
        f'<script src="{up}assets/{a}?v={asset_ver(a)}"></script>' for a in (extra_assets or []))
    # GEO：每页 head 声明 llms.txt / llms-full.txt，AI 引擎从任意落地页都能发现
    # 语义索引；llms.txt 内部再指向全文（两层结构与 MacroBiodiv 对齐）
    llms_links = (f'<link rel="alternate" type="text/plain" href="{SITE_URL}/llms.txt" title="llms.txt">'
                  f'<link rel="alternate" type="text/plain" href="{SITE_URL}/llms-full.txt" title="llms-full.txt">')
    # 图片站让搜索引擎出大图预览；404 已自带 noindex，不能再叠加 index
    robots_meta = ("" if "noindex" in head_extra else
                   '<meta name="robots" content="index, follow, max-image-preview:large,'
                   ' max-snippet:-1, max-video-preview:-1">')
    return _render(
        "shell.html",
        TITLE=esc(title), DESC=esc(desc), OG_URL=og_url,
        OG_TITLE=esc(title), OG_DESC=esc(desc), OG_TYPE=og_type,
        OG_EXTRA=og_img + tw, HEAD_EXTRA=llms_links + robots_meta + head_extra,
        UP=up,
        V_CSS=asset_ver("style.css"), V_FAV=asset_ver("favicon.png"),
        V_JS=asset_ver("gallery.js"),
        NAV=nav_html(cfg, up, active_nav),
        BODY_OUTER=body_outer, BODY_INNER=body_inner, GH=gh,
        FOOTER_TITLE=esc(cfg["title"]), FOOTER_SUBTITLE=esc(cfg["subtitle"]),
        REPO_URL="https://github.com/{}/{}".format(
            esc(cfg.get("owner") or "OWNER"), esc(cfg["repo"])),
        EXTRA_SCRIPTS=extra_scripts,
    )


def flat(values, default: str = "—") -> Counter:
    return Counter([str(v) if v else default for v in values])


# 范围组固定顺序（site_common.SCOPE_TAGS，用户策展：全球 → 大洲 → 中国地图 →
# 其他）；样式组按热度排序。库里暂不存在的固定项不渲染（点不出结果）


def chips(values: Counter, key: str, pinned: list[str] | None = None) -> str:
    """多选标签 chips（正向选择语义，2026-10-14 与 MacroBiodiv 统一）：默认全不选，
    点击=选中该标签（组内选中值之间 OR）；全选/反选/严格 单独一排收尾，每组独立。
    严格=图片携带的该组每个标签都必须被选中（带任一未选中标签的图排除）。
    pinned 给定时：固定组一排（按给定顺序）+ 其余一排（数量降序）+ 操作一排；
    否则标签一排 + 操作一排。全部同在 .chips[data-key] 容器内 —— gallery.js 的
    容器级事件委托与 querySelectorAll 均不受分组影响。"""
    def chip_btn(name: str, n: int) -> str:
        return (f'<button type="button" class="chip" data-v="{esc(name)}" aria-pressed="false">'
                f'{esc(name)}<i class="n">{n}</i></button>')

    def act_btns() -> list[str]:
        return ['<button type="button" class="chip chip-act" data-act="all">全选</button>',
                '<button type="button" class="chip chip-act" data-act="invert">反选</button>',
                '<button type="button" class="chip chip-act" data-act="strict" data-on="false" aria-pressed="false" '
                'title="严格模式：图片携带的每个标签都必须被选中，带任一未选中标签的图会被排除">严格</button>']

    if pinned:
        pinned_set = set(pinned)
        row1 = [chip_btn(n, values[n]) for n in pinned if n in values]
        row2 = [chip_btn(name, cnt) for name, cnt in
                sorted(((k, v) for k, v in values.items() if k not in pinned_set),
                       key=lambda kv: (-kv[1], str(kv[0])))]
        rows = [row1, row2]
    else:
        rows = [[chip_btn(name, n) for name, n in
                 sorted(values.items(), key=lambda kv: (-kv[1], str(kv[0])))]]
    rows.append(act_btns())
    inner = "".join(
        f'  <div class="chips-row{" chips-act-row" if r is rows[-1] else ""}">\n    '
        + "\n    ".join(r) + '\n  </div>\n' for r in rows)
    return f'<div class="chips" data-key="{key}">\n{inner}</div>'


def filter_row(label: str, inner: str) -> str:
    return f'<div class="fgroup"><span class="flabel">{esc(label)}</span>{inner}</div>'


def card_html(item: dict, base: str) -> str:
    scope = [str(t) for t in (item.get("scope") or [])]
    style = [str(t) for t in (item.get("style") or [])]
    tags = scope + style
    cap = " · ".join(tags) if tags else "—"
    # alt 用语义标签（图片搜索/读屏的主入口），哈希 id 只做无标签时的兜底
    alt = " · ".join(tags) if tags else f"图 {item['id']}"
    # width/height 取 refs.json 里的真实尺寸：加载前预留同比例空间（零抖动），
    # .c-covbox::before 的「加载中」层在图片画出前可见（CSS 同款占位语言）
    w, h = int(item.get("width") or 0), int(item.get("height") or 0)
    dims = f' width="{w}" height="{h}"' if w and h else ""
    # src 在构建期就写死成活动源的绝对地址：gallery.js 的 bind() 运行时也会赋同一个值
    # （不重复请求），但这样爬虫抓原始 HTML、AI 引擎读页面时能直接看到图片地址，
    # LCP 也不必等 JS 跑起来。data-rel 保留——逐源降级靠它换下一个源。
    thumb = str(item.get("thumb") or "")
    src = f' src="{esc(base + "/" + thumb)}"' if thumb else ""
    # 徽章 flex-wrap 换行：范围在前（accent tint 轻微区分），样式在后中性；
    # 双轨迁移后每张图必有两类徽章，无「—」兜底路径（保留防御不删）
    badges = ("".join(f'<i class="sc">{esc(t)}</i>' for t in scope)
              + "".join(f"<i>{esc(t)}</i>" for t in style)) or '<i class="none">—</i>'
    return f"""  <a class="card" href="{esc(item['id'])}/" data-id="{esc(item['id'])}" title="{esc(' · '.join(tags))}">
    <span class="c-covbox"><img{src} data-rel="{esc(item.get('thumb'))}"{dims} alt="{esc(alt)}" loading="lazy"></span>
    <span class="cap"><span class="tags">{badges}</span></span>
  </a>"""



# 排序按钮首帧预置：静态 HTML 把「新到旧」写死为按下态，gallery.js 加载后才按
# 「URL ?sort= > localStorage 偏好」纠正——宽屏慢网能看到一瞬间默认态再跳变。
# 内联脚本紧跟 sortseg 输出、解析期同步执行，按与 gallery.js 相同的优先级预置
# aria-pressed 消除闪烁；不写 localStorage，URL 排序仅本次生效的语义不变
# 筛选控件首帧预置：静态 HTML 把全部控件写成默认态（新到旧按下、chips 全选、
# 取色器白色、输入框留空、面板展开），gallery.js 加载后才按「URL 参数 >
# localStorage 偏好」纠正——慢网下能看到一瞬间默认态再跳变（?sort=random 分享、
# 收起过筛选面板、?tag= 标签跳转等场景）。STATE_PRESTATE 内联脚本紧跟 sortseg
# 输出、解析期同步执行（先于卡片网格绘制），按与 gallery.js 相同的优先级预置
# 各控件状态消除闪烁；不写 localStorage，「URL 排序仅本次生效」语义不变
STATE_PRESTATE = """<script>(function(){try{
var P=new URLSearchParams(location.search);
var col=false;try{col=localStorage.getItem("gsp-filters")==="hidden"}catch(e){}
if(col){var fb=document.getElementById("filters");if(fb)fb.setAttribute("hidden","");
var fbB=document.getElementById("filterBtn");if(fbB){fbB.textContent="筛选 ▾";
fbB.setAttribute("aria-expanded","false")}}
var q=P.get("q");if(q){var qi=document.getElementById("q");if(qi)qi.value=q}
["from","to"].forEach(function(k){var v=P.get(k);if(v){
var el=document.getElementById("f-"+k);if(el)el.value=v}});
/* 双轨标签恢复：scope=/style= 各自多值（| 分隔）；旧 tag= 链接按值归属
   映射到对应组（范围池命中→scope，否则→style），历史分享链接不断链 */
["scope","style","tag"].forEach(function(k){var v=P.get(k);if(!v)return;
v.split("|").forEach(function(name){
var sel='button.chip[data-v="'+name+'"]';
var b=document.querySelector('.chips[data-key="scope"] '+sel)
    ||document.querySelector('.chips[data-key="style"] '+sel);
if(b)b.setAttribute("aria-pressed","true")})});
var c=String(P.get("color")||"").replace(/^#/,"");
if(/^[0-9a-fA-F]{6}$/.test(c)){c="#"+c.toUpperCase();
var ci=document.getElementById("f-color");if(ci)ci.value=c;
var ch=document.getElementById("f-colorhex");if(ch)ch.value=c.slice(1);
var cc=document.getElementById("f-colorclear");if(cc)cc.hidden=false}
var tv=parseInt(P.get("tol"),10);
if(tv>=0&&tv<=150){var fe=document.getElementById("f-tol");if(fe)fe.value=String(tv);
var fv=document.getElementById("f-tolval");if(fv)fv.textContent=String(tv)}
var pv=parseFloat(P.get("pct"));
if(pv>=0&&pv<=100){var fp=document.getElementById("f-minpct");if(fp)fp.value=String(pv);
var fv2=document.getElementById("f-minpctval");if(fv2)fv2.textContent=pv+"%"}
var v=P.get("sort"),ok=["added","added_asc","color","random"];
if(ok.indexOf(v)<0){v=null;try{v=localStorage.getItem("gsp-sort2")}catch(e){}
if(ok.indexOf(v)<0)v=null}
if(v)document.querySelectorAll("#sortseg button").forEach(function(b){
b.setAttribute("aria-pressed",String(b.getAttribute("data-sort")===v))})
/* 每页数量：首帧把 select 预置成访客偏好（网格仍由 JS 重建，但控件不再跳变） */
var pp=parseInt(localStorage.getItem("gsp-per"),10);
if([20,30,50].indexOf(pp)>-1){var pSel=document.getElementById("perpage");
if(pSel)pSel.value=String(pp)}
}catch(e){}})();</script>"""


def build_index(cfg: dict, items: list[dict], img_base: str) -> str:
    scope_counter: Counter = Counter()
    style_counter: Counter = Counter()
    for it in items:
        for t in it.get("scope") or []:
            scope_counter[str(t)] += 1
        for t in it.get("style") or []:
            style_counter[str(t)] += 1

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
  <h1><img class="logo" src="assets/logo-sm.png?v={asset_ver('logo-sm.png')}" alt="GeoSciPlot logo">{esc(cfg['title'])}</h1>
  <a class="gh-note" href="https://github.com/{esc(cfg.get('owner') or 'OWNER')}/{esc(cfg['repo'])}" rel="noopener" target="_blank" title="在 GitHub 查看图片源文件">{ghsvg}<span>图片存储于 <b>GitHub</b>，访问需具备 GitHub 访问能力（点此查看仓库）</span></a>
  <p class="lede">{esc(cfg['lede'])}</p>
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
  + '<input id="f-colorhex" class="hexinp" placeholder="如 1F4E79" maxlength="7" spellcheck="false" autocomplete="off">'
  + '<button id="f-colorclear" class="reset" type="button" title="清除颜色筛选" hidden>×</button>'
  + '</span> <span class="flabel" style="min-width:auto">容差</span>'
  + '<input type="range" id="f-tol" class="tolrange" min="0" max="150" value="60" aria-label="颜色容差（RGB 距离）">'
  + '<span id="f-tolval">60</span>'
  + ' <span class="flabel" style="min-width:auto">占比≥</span>'
  + '<input type="range" id="f-minpct" class="tolrange" min="0" max="100" value="0" aria-label="命中主色的最小占比">'
  + '<span id="f-minpctval">0%</span>')}
{filter_row("范围", chips(scope_counter, "scope", pinned=SCOPE_TAGS))}
{filter_row("样式", chips(style_counter, "style"))}
{filter_row("上传", '<input type="date" id="f-from" class="dateinp">\n'
  + ' <span class="flabel" style="min-width:auto">至</span>\n'
  + '<input type="date" id="f-to" class="dateinp">\n'
  + ' <span class="flabel" style="min-width:auto;margin-left:18px">排序</span>\n'
  + ' <span class="sorter" id="sortseg" role="group" aria-label="排序" style="vertical-align:middle">'
  + '<button type="button" data-sort="added" aria-pressed="true" title="上传日期 新→旧"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5v8M4.8 7.3 8 10.5l3.2-3.2M3 13.5h10"/></svg><span>新到旧</span></button>'
  + '<button type="button" data-sort="added_asc" aria-pressed="false" title="上传日期 旧→新"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13.5v-8M4.8 8.7 8 5.5l3.2 3.2M3 2.5h10"/></svg><span>旧到新</span></button>'
  + '<button type="button" data-sort="color" aria-pressed="false" title="按与筛选颜色的相近程度排序（需先在「颜色」行选色）"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="5.2"/><path d="M8 1.2v2.4M8 12.4v2.4M1.2 8h2.4M12.4 8h2.4"/></svg><span>相近</span></button>'
  + '<button type="button" data-sort="random" aria-pressed="false" title="随机排序"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 4.5h2.2c3.2 0 4.6 7 7.6 7H14M2 11.5h2.2c1.3 0 2.2-.9 3-2M8.8 6.5c.8-1.1 1.7-2 3-2H14M12.3 3l1.7 1.5L12.3 6M12.3 10l1.7 1.5-1.7 1.5"/></svg><span>随机</span></button>'
  + '</span>' + STATE_PRESTATE)}
</div>

<main class="grid" id="grid">
{chr(10).join(card_html(it, img_base) for it in first_page)}
</main>
<p class="empty" id="empty">没有符合条件的图片</p>

<div class="pgbar">
  <button id="prev" type="button" title="上一页">{pg_ico_l}上一页</button>
  <span id="pgnums"></span>
  <button id="next" type="button" title="下一页">下一页{pg_ico_r}</button>
  <span class="info" id="pageinfo">共 {max(1, -(-len(items) // PAGE_SIZE))} 页</span>
</div>

<script>window.GALLERY_PAGE = {PAGE_SIZE};</script>"""
    website_ld = ld_json({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "geosciplot",
        "alternateName": "地学科研绘图参考图库",
        "url": SITE_URL,
        "description": cfg["lede"],
        "inLanguage": "zh-CN",
        # 站点品牌归 Organization，作者归到家主站同一 Person 实体（跨域实体图谱）
        "publisher": AUTHOR_LD,
        # SearchAction：/search/ 支持 id/DOI/标签检索（?q= 预填，gallery.js L207），
        # 声明后引擎可把站内检索挂进结果（MacroBiodiv 首页同款）
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint",
                       "urlTemplate": SITE_URL + "/search/?q={search_term_string}"},
            "query-input": "required name=search_term_string",
        },
    })
    # CollectionPage + 全量图片 ItemList（2026-10-18）：首页是图库主落地页，
    # 与 sitemap 的 image 扩展同源互补——结构化实体清单供 AI 引擎直接取用
    col_ld = ld_json({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "全部图片",
        "description": cfg["lede"],
        "url": SITE_URL + "/",
        "inLanguage": "zh-CN",
        "isPartOf": {"@type": "WebSite", "name": cfg.get("title", "GeoSciPlot"),
                     "url": SITE_URL + "/"},
        # itemListElement 是 ItemList 的属性；CollectionPage 通过 hasPart 挂清单，
        # 引擎才能把「这个页面聚合了哪些图」当成一个整体实体读取
        "hasPart": {
            "@type": "ItemList",
            "numberOfItems": len(items),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1,
                 "name": (" · ".join([str(t) for t in (it.get("scope") or [])]
                                     + [str(t) for t in (it.get("style") or [])]) or f"图 {it['id']}"),
                 "url": f"{SITE_URL}/{it['id']}/"}
                for i, it in enumerate(items)],
        },
    })
    head = (f'<script type="application/ld+json">{website_ld}</script>'
            f'<script type="application/ld+json">{col_ld}</script>')
    return page_shell(cfg, cfg["subtitle"], body,
                      meta_desc=f"{cfg['lede']}（{len(items)} 张图，可搜索、可筛选、按上传日期浏览）",
                      head_extra=head,
                      extra_assets=["gallery-data.js"])


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
        sub = " · ".join([str(t) for t in (it_.get("scope") or [])]
                         + [str(t) for t in (it_.get("style") or [])]) or (it_.get("doi") or "—")
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

    # 标签双轨：范围/样式两行各自可点跳转（点击回首页并套用对应组的筛选）
    scope = [str(t) for t in (it.get("scope") or [])]
    style = [str(t) for t in (it.get("style") or [])]
    scope_html = "".join(
        f'<a class="tag" href="/?scope={quote(t, safe="")}">{esc(t)}</a>' for t in scope
    ) or "—"
    style_html = "".join(
        f'<a class="tag" href="/?style={quote(t, safe="")}">{esc(t)}</a>' for t in style
    ) or "—"

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
    # 语义串：title/alt/ImageObject name 共用。哈希 id 对搜索引擎和 AI 无语义，
    # 范围+样式（主题 · 图表类型）才是图片搜索与语义检索的入口；无标签时退回 id。
    sem = " · ".join(scope + style)
    main_alt = sem if sem else f"图 {it['id']}"
    full_url = f"{abs_base}/{it.get('full', '')}"
    thumb_url = f"{abs_base}/{it.get('thumb', '')}"
    # 展示档：大图（>1600px 或 >512KB）有 1600px WebP 中间档，详情页 <img> 与
    # og:image 用它（LCP 从原图均值 ~2MB/极值 14MB 降到 ~200KB 级）；灯箱
    # （data-lightbox-src）与「查看原图」链接仍走原图。小图无 disp 直用原图
    disp_rel = it.get("disp") or it.get("full", "")
    disp_url = f"{abs_base}/{disp_rel}"
    dw, dh = w, h
    if it.get("disp") and w and h:
        _s = min(1.0, 1600 / max(w, h))
        dw, dh = max(1, round(w * _s)), max(1, round(h * _s))
    raw_bytes = it.get("bytes") or 0
    size_txt = (f"{raw_bytes/1048576:.1f}MB" if raw_bytes >= 1048576
                else (f"{raw_bytes/1024:.0f}KB" if raw_bytes >= 1024 else ""))
    # h1 语义优先（与 <title> 同一口径），哈希 id 仍留在标题里供人核对；
    # 之前这里是个 <h2>图 {id}</h2>——页面没有 h1，且 id 对搜索/AI 零信息量
    h1_text = f"{sem} · 图 {it['id']}" if sem else f"图 {it['id']}"
    body = f"""<a class="back" id="backLink" href="../">{back_ico}返回全部</a>
<h1 class="id-title">{esc(h1_text)}</h1>
<figure class="shot">
  <img src="{esc(disp_url)}" data-rel="{esc(disp_rel)}" data-lightbox-src="{esc(full_url)}" alt="{esc(main_alt)}" width="{w}" height="{h}" fetchpriority="high">
</figure>
<p class="full-row">{'原图 ' + size_txt + ' · ' if size_txt else ''}<a href="{esc(full_url)}" target="_blank" rel="noopener">查看原图</a>（灯箱放大同为原图）</p>
<p class="cl-go-row"><a class="cl-go" href="../color-lab/?id={esc(it['id'])}">{ICO_PALETTE}转到色彩实验 · 取色 / 调色</a></p>
<dl class="meta">
  <dt>ID</dt><dd class="hl">{esc(it['id'])}</dd>
  <dt>DOI</dt><dd>{doi_html}</dd>
  <dt>上传日期</dt><dd>{esc(it.get('added'))}</dd>
  <dt>被浏览</dt><dd><span id="views">…</span></dd>
  <dt>范围</dt><dd>{scope_html}</dd>
  <dt>样式</dt><dd>{style_html}</dd>{swatches_row}
</dl>
{chr(10).join(pager)}"""
    gh_img = "https://github.com/{}/{}/blob/{}/images/{}".format(
        cfg.get("owner") or "OWNER", cfg["repo"], cfg.get("branch", "main"), it.get("full", ""))
    added = str(it.get("added") or "")
    desc_parts = [t for t in [" · ".join(scope + style), added, f"图 {it['id']}"] if t]
    detail_desc = (" · ".join(desc_parts) + f" · DOI: {doi_bare(it.get('doi'))}" if it.get("doi") else " · ".join(desc_parts)) or cfg["lede"]
    image_ld = ld_json({
        "@context": "https://schema.org",
        "@type": "ImageObject",
        "@id": f"{SITE_URL}/{it['id']}/#image",
        "name": (f"{sem}（图 {it['id']}）" if sem else f"图 {it['id']}"),
        "description": detail_desc,
        "contentUrl": full_url,
        "thumbnailUrl": thumb_url,
        "uploadDate": added,
        "url": f"{SITE_URL}/{it['id']}/",
        "keywords": ", ".join(scope + style),
        "inLanguage": "zh-CN",
        # 图片归属与主站同一 Person 实体（E-E-A-T / 跨域实体图谱）；站点品牌仍走 Organization
        "author": AUTHOR_LD,
        "publisher": {"@type": "Organization", "name": cfg.get("title", "GeoSciPlot"),
                      "url": SITE_URL},
    })
    # 详情页 title 语义优先：标签（主题 · 类型）打头，末尾带图 id。
    # 仅用标签会大量撞标题（同主题同类型的图很多），id 让每条 title 唯一。
    title_text = (f"{sem} · 图 {it['id']} · 地学科研绘图参考" if sem
                  else f"图 {it['id']} · 地学科研绘图参考")
    og_meta = (f'<meta property="og:image" content="{esc(disp_url)}">'
               f'<meta property="og:image:width" content="{dw}">'
               f'<meta property="og:image:height" content="{dh}">'
               # Twitter/X 大图卡与 og:image 同源（构建期写死绝对地址）；
               # 用展示档：部分平台拒收 >8MB 原图，webp 各家均支持
               f'<meta name="twitter:card" content="summary_large_image">'
               f'<meta name="twitter:title" content="{esc(title_text)}">'
               f'<meta name="twitter:description" content="{esc(detail_desc[:200])}">'
               f'<meta name="twitter:image" content="{esc(disp_url)}">')
    # 面包屑（图库首页 → 图详情）：与主站文章页同构，帮引擎把图片实体挂到站内层级
    breadcrumb_ld = ld_json({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "图库首页", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": h1_text, "item": f"{SITE_URL}/{it['id']}/"},
        ],
    })
    # AEO/GEO：图库详情页此前只有 ImageObject + BreadcrumbList，缺少「页面」实体，
    # AI 引擎无法把图片挂到带发布时间的页面上。补 WebPage 节点（uploadDate 仍留在
    # ImageObject，语义不混用），mainEntity 用 @id 关联同一张图。
    webpage = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "@id": f"{SITE_URL}/{it['id']}/",
        "url": f"{SITE_URL}/{it['id']}/",
        "name": h1_text,
        "description": detail_desc,
        "inLanguage": "zh-CN",
        "isPartOf": {"@type": "WebSite", "name": cfg.get("title", "GeoSciPlot"),
                     "url": SITE_URL + "/"},
        "mainEntity": {"@type": "ImageObject", "@id": f"{SITE_URL}/{it['id']}/#image"},
        "publisher": {"@type": "Organization", "name": cfg.get("title", "GeoSciPlot"),
                      "url": SITE_URL},
    }
    if added:
        webpage["datePublished"] = added
    webpage_ld = ld_json(webpage)
    head = (f'{og_meta}<script type="application/ld+json">{image_ld}</script>'
            f'<script type="application/ld+json">{webpage_ld}</script>'
            f'<script type="application/ld+json">{breadcrumb_ld}</script>')
    # og:image 经 head_extra 输出（比 page_shell 版多 width/height，爬虫建图更省事）；
    # og_image 参数留空避免同一 meta 输出两遍
    return page_shell(cfg, title_text, body, depth=1, gh_url=gh_img,
                      meta_desc=detail_desc, head_extra=head,
                      og_type="article",
                      og_url=f"{SITE_URL}/{it['id']}/",
                      extra_assets=["image-lightbox.js"])


def build_search_page(cfg: dict, items: list[dict]) -> str:
    """全站搜索独立页：版式对齐主站 zbhgis.com 的 /search。
    结果行由 gallery.js 在客户端渲染（数据来自 gallery-data.js），
    缩略图与网格卡片一样走逐源降级；结果链接经 data-up 前缀回详情页。"""
    body = f"""<header class="site">
  <p class="kicker">GEOSCIPILOT · SEARCH</p>
  <h1 class="spage-title">全站搜索</h1>
  <p class="lede">检索全部 {len(items)} 张图的 id / DOI / 标签 / 上传日期；多个词用空格分隔（需同时命中）。</p>
</header>

<input id="spage-q" class="spage-q" type="search" placeholder="输入关键词搜索 id / DOI / 标签…" autocomplete="off" autofocus>
<div class="spage-count" id="spage-count"></div>
<div class="spage-list" id="spage-list" data-up="../"></div>"""
    # 搜索页是薄内容且查询参数无限，不让搜索引擎收录（与主站 /search 策略一致）
    return page_shell(cfg, "全站搜索", body, depth=1,
                      meta_desc="搜索图库全部图片：按 id / DOI / 标签关键词检索，支持筛选与排序",
                      og_url=f"{SITE_URL}/search/",
                      head_extra='<meta name="robots" content="noindex, follow">',
                      extra_assets=["gallery-data.js"])


def build_colorlab_page(cfg: dict, items: list[dict]) -> str:
    """色彩实验独立页（/color-lab/）：纯浏览器端的取色 / 调色工具。
    指定图片 id 载入原图 → 框选区域（不选=整张图）统计占比最高的前几个颜色
    （色块 + HEX/RGB 色号）→ 把区域内指定颜色替换成新颜色，可撤销、可下载 PNG。
    另可叠加色觉模拟（Protanopia / Deuteranopia / Tritanopia / Achromatopsia + 强度）
    检查配色对色觉障碍读者是否可辨。
    交互逻辑在 assets_src/color-lab.js（构建期原样拷贝进 site/assets/）。"""
    body = f"""<header class="site">
  <p class="kicker">GEOSCIPILOT · COLOR LAB</p>
  <h1 class="spage-title">色彩实验</h1>
  <p class="lede">框选（或不框选=整张图）统计图中占比最高的几个颜色并提供色号，再把指定颜色替换成新颜色，方便调色试色；可叠加色觉模拟（红盲 / 绿盲 / 蓝盲 / 全色盲视角），检查配色对色觉障碍读者是否分得开。全部计算在浏览器本地完成，可下载结果图。</p>
</header>

<div class="clayout">
  <section class="cl-stage-col">
    <div class="cl-toolbar">
      <span class="searchbox"><input id="cl-id" class="search" type="search" placeholder="输入图片 id（如 c29fd21ed1）…" autocomplete="off"><button id="cl-load" type="button">载入</button></span>
      <button id="cl-random" class="cl-btn" type="button">随机来一张</button>
    </div>
    <div class="cl-meta" id="cl-meta" hidden></div>
    <div class="cl-stage" id="cl-stage">
      <canvas id="cl-canvas" width="0" height="0"></canvas>
      <div class="cl-overlay" id="cl-overlay"><div class="cl-selbox" id="cl-selbox"></div></div>
      <p class="cl-placeholder" id="cl-placeholder">先在上方输入图片 id 载入原图</p>
      <i class="cl-grip" id="cl-grip" title="拖动调整显示大小（40%–100%）" aria-hidden="true"></i>
      <div class="cl-loading" id="cl-loading" hidden><span class="cl-spin"></span>载入中…</div>
    </div>
    <div class="cl-stagebar">
      <button id="cl-selmode" class="cl-btn" type="button" aria-pressed="false" title="开启后拖拽框选统计区域；关闭时单击画布打开放大镜">开始框选</button>
      <span id="cl-selinfo"></span>
      <button id="cl-clearsel" class="cl-btn" type="button" disabled>清除框选</button>
      <label class="cl-check"><input type="checkbox" id="cl-highlight"> 高亮将被替换的像素</label>
      <label class="cl-check" title="高亮遮罩的颜色，可自选"><input type="color" id="cl-hlcolor" value="#FF4081"> 高亮色</label>
      <span class="cl-cb"><label for="cl-cbtype">色觉模拟</label><select id="cl-cbtype" title="按二色视觉矩阵近似模拟色觉障碍读者看到的成图效果"><option value="">不模拟</option><option value="prot" title="红色盲：缺失红锥，红/绿/橙互混">Protanopia</option><option value="deut" title="绿色盲：缺失绿锥，最常见的色觉缺陷">Deuteranopia</option><option value="trit" title="蓝色盲：缺失蓝锥，蓝/绿、黄/红互混">Tritanopia</option><option value="achroma" title="全色盲：只剩明暗层次">Achromatopsia</option></select><input type="range" id="cl-cbstrength" class="tolrange" min="10" max="100" step="5" value="100" aria-label="色觉模拟强度" title="模拟强度：100% = 完全二色视觉，调低近似红色弱 / 绿色弱等部分色觉缺陷"><span class="mono" id="cl-cbstrengthval">100%</span></span>
    </div>
    <p class="cl-status" id="cl-status"></p>
  </section>

  <aside class="cl-panel">
    <section>
      <h3>主色 · 当前区域</h3>
      <div class="cl-row"><label>数量</label><input type="range" id="cl-count" min="4" max="20" step="1" value="8" aria-label="主色数量"><span class="mono" id="cl-countval">8</span></div>
      <div class="cl-palette" id="cl-palette"><p class="cl-note">载入图片后自动统计（按占比排序）</p></div>
      <p class="cl-note">点击色块设为「目标色」；「复制」拿色号；「屏蔽」把背景色（含相近色）移出统计。开启色觉模拟时，色块右侧并排显示模拟后的颜色。</p>
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
        <button id="cl-cbapply" class="cl-btn" type="button" disabled title="把当前色觉模拟的结果真正写进图像像素（可撤销），写回后下载 PNG 即为模拟图">固化模拟效果</button>
        <button id="cl-download" class="cl-btn cl-primary" type="button" disabled>下载 PNG</button>
      </div>
      <p class="cl-note">色觉模拟只改显示、不改像素；「固化模拟效果」才把模拟结果写回图像（可撤销 / 还原原图），写回后预览自动关闭以免叠加两次。</p>
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
    head = f'<script defer src="../assets/color-lab.js?v={asset_ver("color-lab.js")}"></script>'
    return page_shell(cfg, "色彩实验", body, depth=1,
                      meta_desc="框选图片区域统计主要颜色（色块 + HEX/RGB 色号），可将指定颜色替换为新颜色，并叠加红盲/绿盲/蓝盲色觉模拟检查配色；浏览器本地完成，支持下载结果图",
                      og_url=f"{SITE_URL}/color-lab/",
                      head_extra=head,
                      extra_assets=["gallery-data.js"])


def build_stats_page(cfg: dict, items: list[dict]) -> str:
    """全站统计页（访客向数据面板）：hero 总览 + 点击量 + 筛选（标签/画幅/
    上传日期区间）联动重算 —— 上传动态面积图 · 主色构成环形图 · 高频颜色条形图 ·
    标签词云。数据来自 stats-data.js（仅本页注入）；
    点击量榜与 hero 浏览数来自统计服务，为全量口径不随筛选重算。"""
    # 屏蔽色工具行：全部色族罗列（点按切换、点亮即屏蔽），两张颜色卡共用同一份
    # 状态（stats.js 的 BL.fams，localStorage 记忆）；色族集合与 colorFamily 一致
    st_fams = [("白", "#FFFFFF"), ("黑", "#000000"), ("灰", "#808080"),
               ("红", "#e5534b"), ("橙", "#f0883e"), ("黄", "#d29922"),
               ("绿", "#3fb950"), ("青", "#39c5cf"), ("蓝", "#58a6ff"),
               ("紫", "#a371f7"), ("粉", "#db61a2")]
    st_bl_buttons = "".join(
        f'<button type="button" class="st-bl-q" data-fam="{n}" title="屏蔽{n}色族">'
        f'<i style="background:{c}"></i>{n}</button>'
        for n, c in st_fams)
    body = f"""<header class="site">
  <p class="kicker">GEOSCIPILOT · STATS</p>
  <h1 class="spage-title">全站统计</h1>
</header>

<section class="st-hero" aria-label="收录总览">
  <div class="st-tile st-tc1"><b id="stv-items">0</b><span>收录图片 · 张</span></div>
  <div class="st-tile st-tc2"><b id="stv-tags">0</b><span>标签 · 个</span></div>
  <div class="st-tile st-tc3"><b id="stv-latest">—</b><span>最近更新 · 日期</span></div>
  <div class="st-tile st-tc4"><b id="stv-views">…</b><span>图片被浏览 · 次</span></div>
</section>

<section class="st-card st-hot"><h3>点击量<em>Top 5 · 按访客浏览量 · 全量口径</em></h3>
<div class="st-ranks" id="st-rank"><p class="st-none">加载中…</p></div></section>

<div class="st-filter">
  <span class="st-fgroup"><span class="flabel">范围</span>
    <select id="st-scope" aria-label="按范围筛选"><option value="*">全部</option></select></span>
  <span class="st-fgroup"><span class="flabel">样式</span>
    <select id="st-style" aria-label="按样式筛选"><option value="*">全部</option></select></span>
  <span class="st-fgroup"><span class="flabel">画幅</span>
    <select id="st-ar" aria-label="按画幅筛选"><option value="*">全部</option></select></span>
  <span class="st-fgroup"><span class="flabel">上传</span>
    <input type="date" id="st-from" class="dateinp" aria-label="上传日期 起"
           title="按上传日期筛选（仅精确到月的日期按整月重叠匹配）">
    <span class="st-dash" aria-hidden="true">–</span>
    <input type="date" id="st-to" class="dateinp" aria-label="上传日期 止"></span>
  <button id="st-reset" class="reset" type="button">重置</button>
  <span class="st-count" id="st-count"></span>
</div>
<p class="st-empty" id="st-empty" hidden>当前筛选条件下没有图片</p>
<div class="st-grid" id="st-grid">
  <section class="st-card st-wide"><h3>上传动态<em>按上传日期 · 累计</em></h3>
    <div class="st-growth" id="st-growth"></div></section>
  <section class="st-card"><h3>主色构成<em>每图取第一未屏蔽主色 · 按色族归类</em></h3>
    <div class="st-bl">
      <span class="st-bl-label">屏蔽色</span>
      {st_bl_buttons}
    </div>
    <div class="st-donut" id="st-donut"></div>
    <p class="st-bl-note" id="st-bl-note" hidden></p></section>
  <section class="st-card"><h3>高频颜色<em>图的前 20 主色中出现该族即计 · 按色族</em></h3>
    <div class="st-bl">
      <span class="st-bl-label">屏蔽色</span>
      {st_bl_buttons}
    </div>
    <div class="st-bars" id="st-bars"></div></section>
  <section class="st-card st-wide"><h3>标签词云<em>上：范围 · 下：样式 · 字号随收录张数</em></h3>
    <div class="st-cloud" id="st-scloud"></div>
    <div class="st-cloud" id="st-tcloud"></div></section>
</div>
<p class="st-cta">想找某张图？<a href="../search/">去全站搜索</a>，或回<a href="../">图库首页</a>按标签浏览，去<a href="../color-lab/">色彩实验</a>取色调色。</p>"""
    return page_shell(cfg, "全站统计", body, depth=1,
                      extra_assets=["stats-data.js", "stats.js"], active_nav="stats",
                      meta_desc="图库全站统计：收录量、画幅构成、上传节奏、标签词云与热门图片浏览榜",
                      og_url=f"{SITE_URL}/statistics/")


def render_about_page(cfg: dict, doc: str) -> str:
    """关于本站页：页头 + about-body prose。正文由 build_site.py 读取并渲染。"""
    body = f"""<header class="site">
  <p class="kicker">GEOSCIPILOT · ABOUT</p>
  <h1 class="spage-title">关于本站</h1>
</header>
<div class="about-wrap">
<article class="about-body">{doc}</article>
</div>"""
    # AboutPage + 主站同一 Person 实体：搜索引擎/AI 引擎可把「关于」页
    # 认定为作者与站点归属的规范说明页（E-E-A-T）
    about_ld = ld_json({
        "@context": "https://schema.org", "@type": "AboutPage",
        "name": f"关于本站 · {cfg.get('title', 'GeoSciPlot')}",
        "url": SITE_URL + "/about/",
        "description": "关于 GeoSciPlot：站点定位、数据来源、图片版权与引用说明。",
        "inLanguage": "zh-CN",
        "mainEntity": AUTHOR_LD,
        "isPartOf": {"@type": "WebSite", "name": cfg.get("title", "GeoSciPlot"),
                     "url": SITE_URL + "/"},
    })
    head = '<script type="application/ld+json">' + about_ld + "</script>"
    return page_shell(cfg, "关于本站", body, depth=1,
                      meta_desc="关于 GeoSciPlot：站点定位、数据来源、图片版权与引用说明。",
                      og_url=SITE_URL + "/about/", active_nav="about", head_extra=head)


# 渲染颜色切换（MacroBiodiv 每周速递同款五档圆点，2026-10-22 补齐）：
# plain=系统色无装饰，accent/green/purple/orange=标题竖线+强调色重映射。
# 偏好存 localStorage gsp-rstyle，shell.html 防闪烁脚本在首帧前恢复（同 MB mbd-rstyle）
RSTYLE_DOTS = (
    ("plain", "普通样式：系统色，标题无装饰", "rst-dot-plain"),
    ("accent", "强调样式：蓝色渲染", "rst-dot-accent"),
    ("green", "强调样式：绿色渲染", "rst-dot-green"),
    ("purple", "强调样式：淡紫渲染", "rst-dot-purple"),
    ("orange", "强调样式：橘色渲染", "rst-dot-orange"),
)


def rstyle_toggle(default: str) -> str:
    btns = "".join(
        f'<button type="button" class="rst-btn" data-rs="{v}" title="{t}"'
        f' aria-pressed="{str(default == v).lower()}"><i class="rst-dot {c}"></i></button>'
        for v, t, c in RSTYLE_DOTS)
    return f'<span class="rstyle" role="group" aria-label="渲染颜色切换">{btns}</span>'


def render_guide_article(cfg: dict, posts: list[dict], i: int) -> str:
    """制图经验文章页：MacroBiodiv 每周速递同款三栏 + 上下篇。"""
    ico_user = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<path d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>')
    ico_doc = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
               'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
               '<path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293'
               'l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>')
    ico_clock = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                 '<path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>')
    ico_left = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<path d="M19 12H5m0 0l6-6m-6 6l6 6"/></svg>')
    ico_right = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                 '<path d="M5 12h14m0 0l-6-6m6 6l-6 6"/></svg>')

    p = posts[i]
    prev_p = posts[i - 1] if i > 0 else None    # 更新的上一篇
    next_p = posts[i + 1] if i + 1 < len(posts) else None
    side_rows = "".join(
        f'<a class="wk-side-link" data-active="{str(q["slug"] == p["slug"]).lower()}" '
        f'href="../{esc(q["slug"])}/">{esc(q["title"])}</a>' for q in posts)
    toc_rows = "".join(
        f'<a class="wk-toc-link" data-lv="{lv}" href="#{hid}">{esc(txt)}</a>'
        for lv, hid, txt in p["toc"])

    def pn_cell(pn: dict | None, to_next: bool) -> str:
        if not pn:
            return '<span class="wk-pn-empty" aria-hidden="true"></span>'
        cls = "wk-pn wk-pn-to-next" if to_next else "wk-pn"
        ico, lbl = ((ico_right, "下一篇") if to_next else (ico_left, "上一篇"))
        return (f'<a class="{cls}" href="../{esc(pn["slug"])}/"><span class="wk-pn-dir">'
                f'{lbl}{ico}</span><span class="wk-pn-ttl">{esc(pn["title"])}</span></a>')

    body = f"""<div class="wk-shell">
<aside class="wk-side"><div class="wk-side-in"><nav class="wk-side-nav">
<div class="wk-side-hd">文章导航</div>{side_rows}</nav></div></aside>
<main class="wk-main"><article>
<h1 class="wk-deco wk-h1">{esc(p["title"])}</h1>
<div class="wk-tagsrow"><span class="wk-tag">{esc(p["month"])}</span></div>
<div class="wk-meta"><a href="https://github.com/zbhgis" target="_blank" rel="noopener" title="作者 GitHub 主页">{ico_user}zbhgis 浩瀚地学</a><span>{ico_doc}{p["words"]} 字</span><span>{ico_clock}约 {p["reading"]} 分钟</span>{rstyle_toggle("plain")}</div>
<div class="wk-dates"><span>创建于 <time datetime="{p["date"]}">{p["date"]}</time></span></div>
<div class="wk-content">{p["doc"]}</div>
<nav class="wk-prevnext" aria-label="文章导航">{pn_cell(prev_p, False)}{pn_cell(next_p, True)}</nav>
</article></main>
<aside class="wk-toc"><div class="wk-toc-in"><h4 class="wk-side-hd">此页内容</h4><nav>{toc_rows}</nav></div></aside>
</div>"""
    url = SITE_URL + f"/guide/{p['slug']}/"
    ld = {
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": p["title"],
        "description": p["summary"],
        "datePublished": p["date"],
        "dateModified": p["date"],
        "inLanguage": "zh-CN",
        "url": url,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "image": p["og_image"] or SITE_URL + "/assets/logo.png",
        # 作者用主站同一 Person 实体（url + sameAs），把子域长文归因到同一作者；
        # publisher 仍是站点品牌，founder 指向该 Person，形成 Organization→Person 图谱
        "author": AUTHOR_LD,
        "publisher": {"@type": "Organization", "name": "GeoSciPlot", "url": SITE_URL,
                      "logo": {"@type": "ImageObject", "url": SITE_URL + "/assets/logo.png"},
                      "founder": AUTHOR_LD},
        "isPartOf": {"@type": "WebSite", "name": cfg.get("title", "GeoSciPlot"),
                     "url": SITE_URL + "/"},
        "articleSection": "制图经验",
        "keywords": "地图投影, 科研绘图, Python, Cartopy, Spilhaus, Orthographic",
    }
    bc = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "图库首页", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "制图经验", "item": SITE_URL + "/guide/"},
            {"@type": "ListItem", "position": 3, "name": p["title"], "item": url},
        ],
    }
    head = (f'<meta property="article:published_time" content="{p["date"]}">'
            f'<meta property="article:modified_time" content="{p["date"]}">'
            f'<meta property="article:section" content="制图经验">'
            f'<script type="application/ld+json">{ld_json(ld)}</script>'
            f'<script type="application/ld+json">{ld_json(bc)}</script>')
    return page_shell(
        cfg, f'{p["title"]} · {cfg["title"]}', body, depth=2,
        meta_desc=p["summary"], og_type="article", og_image=p["og_image"],
        og_url=url, head_extra=head,
        extra_assets=["article-toc.js", "code-block.js", "image-lightbox.js"],
        active_nav="guide", bare=True)


def render_guide_list(cfg: dict, posts: list[dict]) -> str:
    """制图经验列表页：页头 + 月份 chip + 按月分组（Macro 每周速递同款）。"""
    groups: dict[str, list[dict]] = {}
    for p in posts:
        groups.setdefault(p["month"], []).append(p)
    chips = "".join(
        f'<a class="wk-btn" href="#g-{esc(re.sub(r"[^0-9]", "", label))}">'
        f'{esc(label)} <span class="n">{len(items)}</span></a>'
        for label, items in groups.items())
    sections = ""
    for label, items in groups.items():
        rows = "".join(
            f'<a class="wk-line" href="{esc(p["slug"])}/"><span class="wk-line-in">'
            f'<span class="wk-line-main"><h3 class="wk-line-ttl">{esc(p["title"])}</h3>'
            f'<p class="wk-line-sum">{esc(p["summary"])}</p></span>'
            f'<span class="wk-line-side"><span class="wk-line-tags">'
            f'<span class="wk-tag">{esc(label)}</span></span>'
            f'<span class="wk-line-date">{p["date"]}</span></span></span></a>'
            for p in items)
        sections += (f'<section class="wk-group" id="g-{esc(re.sub(r"[^0-9]", "", label))}">'
                     f'<div class="wk-label"><span>{esc(label)}</span>'
                     f'<span class="wk-label-right">{len(items)} 篇</span></div>{rows}</section>')
    body = f"""<header class="site">
  <p class="kicker">{esc(cfg['title'].upper())} · MAPPING GUIDE</p>
  <h1 class="spage-title">制图经验</h1>
  <p class="lede">个人科研制图过程中的一些经验整理</p>
</header>

<div class="wk-quicknav">{chips}</div>
<div class="wk-groups">{sections}</div>"""
    col_ld = {
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": "制图经验",
        "description": "个人科研制图过程中的一些经验整理",
        "url": SITE_URL + "/guide/",
        "inLanguage": "zh-CN",
        "hasPart": {
            "@type": "ItemList",
            "numberOfItems": len(posts),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": p["title"],
                 "url": SITE_URL + f"/guide/{p['slug']}/"}
                for i, p in enumerate(posts)
            ],
        },
    }
    head = '<script type="application/ld+json">' + ld_json(col_ld) + "</script>"
    # 列表面包屑：首页 → 制图经验。详情页有三层面包屑，列表页此前缺失
    bc = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "图库首页", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "制图经验",
             "item": SITE_URL + "/guide/"},
        ],
    }
    head += '<script type="application/ld+json">' + ld_json(bc) + "</script>"
    return page_shell(cfg, f"制图经验 · {cfg['title']}", body, depth=1,
                      meta_desc=f"地学科研制图经验整理，共 {len(posts)} 篇。",
                      og_url=SITE_URL + "/guide/", active_nav="guide", head_extra=head)


def render_404(cfg: dict) -> str:
    """404 页：noindex + 回首页/搜索入口（nginx 需 error_page 404 /404.html 配合）。"""
    return page_shell(cfg, "页面不存在", _tpl("404.html"), meta_desc="页面不存在",
                      head_extra='<meta name="robots" content="noindex, nofollow">',
                      up_override="/")
