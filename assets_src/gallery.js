(function () {
  var CFG = window.GALLERY, ITEMS = window.GALLERY_DATA || [], PAGE = window.GALLERY_PAGE || 48;
  if (!CFG) return;

  /* ── 随机会话种子：随机键 = hash(id + 种子)，种子存 sessionStorage ——
     同一会话内从详情页返回 / 刷新 / 翻页 / 筛选都不重排，点「随机」换新种子重洗。
     此前懒分配 Math.random()，每次页面加载全新键，返回后顺序全变 ── */
  function hash01(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return ((h >>> 0) % 100000) / 100000;
  }
  function rseed() {
    try { return sessionStorage.getItem("gsp-rseed") || ""; } catch (e) { return ""; }
  }
  function newSeed() {
    var s = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
    try { sessionStorage.setItem("gsp-rseed", s); } catch (e) {}
    return s;
  }
  var RSEED = rseed() || newSeed();

  /* ── 逐源降级：当前源失败就自动换下一个源 ── */
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
        /* 连 c-covbox 一起换掉：占位块就位的同时把「加载中」层撤掉 */
        var box = img.closest ? img.closest(".c-covbox") : null;
        if (box) box.parentNode.replaceChild(ph, box);
        else img.parentNode.replaceChild(ph, img);
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
        d.items.forEach(function (x) { map[x.path.replace(/\/$/, "")] = x.views; });
        var n = map["/geosciplot" + location.pathname.replace(/\/$/, "")] || 0;
        viewsEl.textContent = n ? n + " 次" : "首次";
        viewsEl.style.color = "var(--text)";
      }).catch(function () { viewsEl.textContent = "—"; });
  }

  var themeBtn = document.getElementById("themeBtn");
  if (themeBtn) {
    // 按钮文案同主站：指向点击后将切换到的主题（默认暗色 → 切换为浅色模式）
    var syncTheme = function () {
      var dark = document.documentElement.getAttribute("data-theme") !== "light";
      themeBtn.title = dark ? "切换为浅色模式" : "切换为深色模式";
      themeBtn.setAttribute("aria-label", themeBtn.title);
    };
    syncTheme();
    themeBtn.addEventListener("click", function () {
      var root = document.documentElement;
      // 默认暗色（不跟随系统偏好）；仅当访客手动切过才用其选择
      var light = root.getAttribute("data-theme") === "light";
      var t = light ? "dark" : "light";
      root.setAttribute("data-theme", t);
      try { localStorage.setItem("gsp-theme", t); } catch (e) {}
      syncTheme();
    });
  }

  /* ── 字号调节：FAB 的 A 按钮在 标准/放大 两档间切换，localStorage 记忆，
     head 内联脚本在渲染前恢复，切档无闪烁 ── */
  var fsBtn = document.getElementById("fsBtn");
  if (fsBtn) {
    var fsOn = false;
    try { fsOn = localStorage.getItem("gsp-fs") === "lg"; } catch (e) {}
    var syncFs = function () {
      if (fsOn) document.documentElement.setAttribute("data-fs", "lg");
      else document.documentElement.removeAttribute("data-fs");
      fsBtn.title = fsOn ? "字号：放大（点击还原）" : "字号：标准（点击放大）";
      fsBtn.setAttribute("aria-label", fsBtn.title);
      fsBtn.classList.toggle("on", fsOn);   // 放大档按钮点亮
      try { localStorage.setItem("gsp-fs", fsOn ? "lg" : ""); } catch (e) {}
    };
    fsBtn.addEventListener("click", function () { fsOn = !fsOn; syncFs(); });
    syncFs();
  }
  var topBtn = document.getElementById("topBtn");
  if (topBtn) {
    topBtn.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });
    // 阈值 400px 与主站 zbhgis.com 的 .v3-rail-top 保持一致，两站行为统一
    var onScroll = function () { topBtn.classList.toggle("show", window.scrollY > 400); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ── 全站搜索独立页（/search/）：静态站没有检索后端，直接在 gallery-data.js
     的全量元数据上做客户端匹配（id / DOI / 标签 / 日期，多词空格分隔 = 同时命中）。
     结果行带缩略图，经 bind() 走逐源降级；无 thumb 的条目直接输出「无图」占位。
     放在网格逻辑之前 —— 搜索页没有 #grid 会提前 return ── */
  var spageQ = document.getElementById("spage-q");
  if (spageQ) {
    var sList = document.getElementById("spage-list");
    var sCount = document.getElementById("spage-count");
    var sUp = sList ? (sList.getAttribute("data-up") || "") : "";

    function escHtml(s) {
      return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function hl(text, tokens) {
      // 先转义再高亮：token 也过同一套转义，两边一致，特殊字符不会破坏 HTML 结构
      var out = escHtml(text);
      tokens.forEach(function (t) {
        var et = escHtml(t).replace(/[.*+?^${}()|[\]\\]/g, "$&");
        out = out.replace(new RegExp(et, "gi"), "<mark>$&</mark>");
      });
      return out;
    }
    function renderSearch(raw) {
      var tokens = raw.trim().toLowerCase().split(/\s+/).filter(Boolean);
      if (!tokens.length) {
        sCount.textContent = "";
        sList.innerHTML = '<p class="spage-hint">输入 id / DOI / 标签关键词开始检索；多个词用空格分隔（需同时命中）</p>';
        return;
      }
      var hits = ITEMS.filter(function (it) {
        var hay = (it.se || "").toLowerCase();
        return tokens.every(function (t) { return hay.indexOf(t) > -1; });
      });
      sCount.textContent = "找到 " + hits.length + " / " + ITEMS.length + " 张";
      if (!hits.length) {
        sList.innerHTML = '<p class="spage-empty">未找到与 “' + escHtml(raw) + '” 相关的图片</p>';
        return;
      }
      sList.innerHTML = hits.map(function (it) {
        var meta = [];
        if ((it.tg || []).length) meta.push(hl((it.tg || []).join(" · "), tokens));
        // refs.json 里 DOI 存的是完整 URL，展示时剥掉协议前缀（检索仍按原文匹配）
        if (it.doi) meta.push(hl(String(it.doi).replace(/^https?:\/\/doi\.org\//i, ""), tokens));
        if (it.ad) meta.push(escHtml(it.ad));
        var media = it.rel
          ? '<span class="sres-media"><img data-rel="' + escHtml(it.rel) + '" alt="图 ' + escHtml(it.id) + '"></span>'
          : '<span class="sres-media sres-noimg">无图</span>';
        return '<a class="sres" href="' + sUp + escHtml(it.id) + '/">' + media
          + '<span class="sres-body"><span class="sres-id">' + hl("图 " + it.id, tokens) + '</span>'
          + '<span class="sres-meta">' + meta.join('<i class="sres-sep">·</i>') + '</span></span></a>';
      }).join("");
      // 动态插入的缩略图要手动绑逐源降级（gallery.js 只自动绑页面已有的 img[data-rel]）
      sList.querySelectorAll("img[data-rel]").forEach(bind);
    }
    // ?q= 预填：与主站 /search?q= 行为一致，结果可分享
    var sq = "";
    try { sq = new URLSearchParams(location.search).get("q") || ""; } catch (e) {}
    spageQ.value = sq;
    renderSearch(sq);
    /* 记录搜索页当前地址（含 ?q=），详情页「返回全部」据此跳回搜索结果 */
    try { sessionStorage.setItem("gsp-back", location.pathname + location.search); } catch (e) {}
    spageQ.addEventListener("input", function () {
      renderSearch(spageQ.value);
      try {
        var v = spageQ.value.trim();
        history.replaceState(null, "", v ? "?q=" + encodeURIComponent(v) : location.pathname);
        sessionStorage.setItem("gsp-back", location.pathname + location.search);
      } catch (e) {}
    });
  }

  /* 剪贴板兜底：非安全上下文（如 http:// 局域网访问）没有 navigator.clipboard */
  function legacyCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (e) {}
    document.body.removeChild(ta);
  }

  var grid = document.getElementById("grid");
  if (!grid) {
    document.querySelectorAll("img[data-rel]").forEach(bind);
    /* 详情页「返回全部」：优先回最近访问过的图库/搜索页（URL 自带筛选/页码状态，
       跨「上一张/下一张」多跳后依然有效）；无记录（如直链打开）时保持 ../ 兜底 */
    try {
      var backLink = document.getElementById("backLink");
      var backUrl = sessionStorage.getItem("gsp-back");
      if (backLink && backUrl) backLink.setAttribute("href", backUrl);
    } catch (e) {}
    /* 详情页「配色」色块：点击复制色号，百分比位闪一下「已复制」作反馈
       （dd 本身就是 .swatches 容器，不能用后代选择器） */
    var swList = document.querySelector("dl.meta dd.swatches");
    if (swList) swList.addEventListener("click", function (e) {
      var chip = e.target.closest ? e.target.closest(".swchip") : null;
      if (!chip) return;
      e.preventDefault();
      var hx = chip.getAttribute("data-hex");
      if (!hx) return;
      var done = function () {
        var pctEl = chip.querySelector("span");
        if (!pctEl) return;
        if (chip._t) clearTimeout(chip._t);
        pctEl.textContent = "已复制";
        chip.classList.add("copied");
        chip._t = setTimeout(function () {
          pctEl.textContent = pctEl.getAttribute("data-pct") || "";
          chip.classList.remove("copied");
        }, 1100);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(hx).then(done, function () { legacyCopy(hx, done); });
      } else legacyCopy(hx, done);
    });
    return;
  }
  grid.querySelectorAll("img[data-rel]").forEach(bind);   // 首屏静态卡片也要绑降级

  /* ── 分页 + 筛选 + 排序 ── */
  var state = { q: "", tags: null, from: "", to: "", sort: "added", color: "", tol: 60, minpct: 0, page: 1, per: PAGE };
  /* tags=null = 标签全选（不筛选）；数组 = 仅这些标签（OR 命中）。
     DOM（chips 的 aria-pressed）是唯一真源，state.tags 由它派生。 */
  try {
    var savedPer = parseInt(localStorage.getItem("gsp-per"), 10);
    if ([20, 30, 50].indexOf(savedPer) > -1) state.per = savedPer;   // 仅接受合法档位，旧值自动回默认 30
    if (localStorage.getItem("gsp-sort2")) { state.sort = localStorage.getItem("gsp-sort2"); }
  } catch (e) {}
  var q = document.getElementById("q");
  var empty = document.getElementById("empty");
  var count = document.getElementById("count");
  var info = document.getElementById("pageinfo");
  var prev = document.getElementById("prev");
  var next = document.getElementById("next");
  var pgnums = document.getElementById("pgnums");

  /* 视口越窄，页码窗口收得越小：
     ≥1000 → 当前页 ±2 且总页数 ≤9 时全列；≥640 → ±1；更窄 → 只列当前页（总数缩到 4 个节点） */
  function windowSize() {
    var w = window.innerWidth || 1024;
    return w < 640 ? 0 : (w < 1000 ? 1 : 2);
  }
  function digits(n) { return ("0" + n).slice(-2); }

  /* 页码节点用事件委托：一次绑定，翻页时只重建 innerHTML，不重新挂监听 */
  function paintNums(page, pages) {
    if (!pgnums) return;
    if (pages <= 1) { pgnums.innerHTML = ""; return; }
    var win = windowSize();
    var nums = [];
    for (var i = 1; i <= pages; i++) {
      if (i === 1 || i === pages || Math.abs(i - page) <= win) nums.push(i);
    }
    var html = "", last = 0;
    nums.forEach(function (i) {
      if (last && i - last > 1) html += '<span class="pggap">…</span>';
      html += '<button type="button" class="pgnum" data-page="' + i + '"'
            + (i === page ? ' data-on="true" aria-current="page"' : '')
            + ' title="第 ' + i + ' 页">' + i + '</button>';
      last = i;
    });
    pgnums.innerHTML = html;
  }
  if (pgnums) {
    pgnums.addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest(".pgnum") : null;
      if (!b) return;
      var n = parseInt(b.getAttribute("data-page"), 10);
      if (!n || n === state.page) return;
      state.page = n;
      render();
      var bar = document.querySelector(".pgbar");
      if (bar && bar.getBoundingClientRect().top < 0) bar.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  /* ── 颜色筛选：state.color=#RRGGBB，容差 = RGB 欧氏距离阈值。
     colorDist = 图内主色与筛选色的最小距离（无色数据 → Infinity，必不匹配）；
     data 由构建期写入 it.cs = [[hex无#, 占比], ...] ── */
  function setCrgb() {
    state._crgb = state.color
      ? [parseInt(state.color.slice(1, 3), 16), parseInt(state.color.slice(3, 5), 16), parseInt(state.color.slice(5, 7), 16)]
      : null;
  }
  function colorDist(it) {
    var cr = state._crgb;
    if (!state.color || !cr || !it.cs || !it.cs.length) return Infinity;
    var best = Infinity;
    for (var i = 0; i < it.cs.length; i++) {
      var h = it.cs[i][0];
      var dr = parseInt(h.slice(0, 2), 16) - cr[0];
      var dg = parseInt(h.slice(2, 4), 16) - cr[1];
      var db = parseInt(h.slice(4, 6), 16) - cr[2];
      var d = dr * dr + dg * dg + db * db;
      if (d < best) best = d;
    }
    return Math.sqrt(best);
  }

  function colorPass(it) {   // 是否存在「容差内 且 占比≥阈值」的主色（占比筛掉 0.x% 的噪点色）
    var cr = state._crgb;
    if (!cr || !it.cs || !it.cs.length) return false;
    var t2 = state.tol * state.tol;
    for (var i = 0; i < it.cs.length; i++) {
      var h = it.cs[i][0];
      var dr = parseInt(h.slice(0, 2), 16) - cr[0];
      var dg = parseInt(h.slice(2, 4), 16) - cr[1];
      var db = parseInt(h.slice(4, 6), 16) - cr[2];
      if (dr * dr + dg * dg + db * db <= t2 && it.cs[i][1] >= state.minpct) return true;
    }
    return false;
  }

  function pass(it) {
    if (state.tags) {
      var tg = it.tg || [], hit = false;
      for (var ti = 0; ti < tg.length; ti++) if (state.tags.indexOf(tg[ti]) > -1) { hit = true; break; }
      if (!hit) return false;   // OR 语义：至少命中一个选中标签；无标签的图在筛选时隐藏
    }
    if (state.from && (it.ad || "") < state.from) return false;
    if (state.to && (it.ad || "") > state.to) return false;
    if (state.q && (it.se || "").indexOf(state.q) === -1) return false;
    if (state.color && !colorPass(it)) return false;
    return true;
  }
  function cmp(a, b) {
    if (state.sort === "random") {
      if (a._rk === undefined) a._rk = hash01((a.id || "") + ":" + RSEED);
      if (b._rk === undefined) b._rk = hash01((b.id || "") + ":" + RSEED);
      return a._rk - b._rk;
    }
    /* 相近排序：按与筛选色的最小距离升序；未选色/距离相同 → 上传日期新到旧 */
    if (state.sort === "color") {
      if (state.color) {
        var da = colorDist(a), db = colorDist(b);
        if (da !== db) return da - db;
      }
      var fa = (a.ad || ""), fb = (b.ad || "");
      if (fa !== fb) return fa < fb ? 1 : -1;
      return (a.id || "").localeCompare(b.id || "");
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
    /* c-covbox 垫「加载中」占位层；w/h 预留同比例空间防抖动（与静态首屏一致） */
    var box = document.createElement("span");
    box.className = "c-covbox";
    var img = document.createElement("img");
    img.setAttribute("data-rel", it.rel);
    if (it.w && it.h) { img.width = it.w; img.height = it.h; }
    img.alt = "图 " + it.id;
    img.loading = "lazy";
    box.appendChild(img);
    a.appendChild(box);
    var cap = document.createElement("span");
    cap.className = "cap";
    var tagsEl = document.createElement("span");
    tagsEl.className = "tags";
    /* 标签徽章（与静态首屏 card_html 同构）：每标签一枚 accent 描边胶囊 */
    var tg = it.tg || [];
    if (tg.length) {
      for (var bi = 0; bi < tg.length; bi++) {
        var bd = document.createElement("i");
        bd.textContent = tg[bi];
        tagsEl.appendChild(bd);
      }
    } else {
      var nb = document.createElement("i");
      nb.className = "none";
      nb.textContent = "—";
      tagsEl.appendChild(nb);
    }
    cap.appendChild(tagsEl);
    a.appendChild(cap);
    a.title = it.sub || "";
    bind(img);
    return a;
  }
  function perSize(list) { return state.per > 0 ? state.per : (list.length || 1); }
  /* 状态 → URL：筛选/排序/页码写进地址栏（replaceState 不新增历史记录，不打断返回手势）。
     浏览器返回、刷新、分享链接都会带上当前筛选状态；搜索词用输入框原文（保留大小写） */
  function syncUrl() {
    try {
      var parts = [];
      var qv = ((q && q.value) ? q.value : state.q).trim();
      if (qv) parts.push("q=" + encodeURIComponent(qv));
      if (state.tags) parts.push("tag=" + encodeURIComponent(state.tags.join("|")));
      if (state.from) parts.push("from=" + encodeURIComponent(state.from));
      if (state.to) parts.push("to=" + encodeURIComponent(state.to));
      if (state.sort !== "added") parts.push("sort=" + encodeURIComponent(state.sort));
      if (state.color) {
        parts.push("color=" + encodeURIComponent(state.color.slice(1)));
        parts.push("tol=" + state.tol);
        parts.push("pct=" + state.minpct);
      }
      if (state.page > 1) parts.push("page=" + state.page);
      history.replaceState(null, "", location.pathname + (parts.length ? "?" + parts.join("&") : ""));
      /* 顺带记录图库当前地址，详情页「返回全部」据此跳回 */
      sessionStorage.setItem("gsp-back", location.pathname + location.search);
    } catch (e) {}
  }
  function render() {
    var list = ITEMS.filter(pass).sort(cmp);
    var per = perSize(list);
    var pages = Math.max(1, Math.ceil(list.length / per));
    if (state.page > pages) state.page = pages;
    if (state.page < 1) state.page = 1;
    var slice = list.slice((state.page - 1) * per, state.page * per);
    grid.innerHTML = "";
    slice.forEach(function (it) { grid.appendChild(cardNode(it)); });
    if (info) info.textContent = "共 " + pages + " 页";
    if (prev) prev.disabled = state.page <= 1;
    if (next) next.disabled = state.page >= pages;
    paintNums(state.page, pages);
    if (count) {
      var filtered = state.q || state.tag !== "*" || state.from || state.to || state.color;
      count.textContent = filtered ? "匹配 " + list.length + " / " + ITEMS.length + " 张"
                                   : "共 " + ITEMS.length + " 张";
    }
    if (empty) empty.style.display = list.length ? "none" : "block";
    syncFilterBtn();
    syncUrl();
  }
  function resetPage() { state.page = 1; render(); }

  /* ── 标签多选：chips 的 aria-pressed 是真源。默认全选（构建期即 pressed=true），
     点击剔除、全选/反选；全选态下 URL 不带 tag 参数 ── */
  var tagBox = document.querySelector('.chips[data-key="tag"]');
  function tagChips() { return tagBox ? tagBox.querySelectorAll("button.chip[data-v]") : []; }
  function readTags() {
    if (!tagBox) return;
    var sel = [], c = tagChips();
    c.forEach(function (b) { if (b.getAttribute("aria-pressed") === "true") sel.push(b.getAttribute("data-v")); });
    state.tags = sel.length === c.length ? null : sel;
  }
  function writeTags() {
    tagChips().forEach(function (b) {
      b.setAttribute("aria-pressed", String(!state.tags || state.tags.indexOf(b.getAttribute("data-v")) > -1));
    });
  }
  if (tagBox) tagBox.addEventListener("click", function (e) {
    var act = e.target.closest ? e.target.closest(".chip-act") : null;
    if (act) {
      var all = act.getAttribute("data-act") === "all";
      tagChips().forEach(function (b) { b.setAttribute("aria-pressed", String(all ? true : b.getAttribute("aria-pressed") !== "true")); });
    } else {
      var chip = e.target.closest ? e.target.closest("button.chip[data-v]") : null;
      if (!chip) return;
      chip.setAttribute("aria-pressed", String(chip.getAttribute("aria-pressed") !== "true"));
    }
    readTags(); resetPage();
  });

  if (q) {
    q.addEventListener("input", function () { state.q = q.value.trim().toLowerCase(); resetPage(); });
    q.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { q.value = ""; state.q = ""; resetPage(); }
      if (e.key === "Enter") { e.preventDefault(); runSearch(); }
    });
  }
  var qBtn = document.getElementById("qBtn");
  function runSearch() {
    state.q = (q ? q.value : "").trim().toLowerCase();
    resetPage();
    var g = document.getElementById("grid");
    if (g && g.getBoundingClientRect().top < 0) g.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  if (qBtn) qBtn.addEventListener("click", runSearch);
  var sortseg = document.getElementById("sortseg");
  if (sortseg) {
    if (["added", "added_asc", "color", "random"].indexOf(state.sort) === -1) state.sort = "added";
    var sortBtns = sortseg.querySelectorAll("button");
    sortBtns.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-sort") === state.sort));
      b.addEventListener("click", function () {
        state.sort = b.getAttribute("data-sort");
        if (state.sort === "random") {
          /* 每次选「随机」换新种子重洗；清掉已分配的旧键让 cmp 用新种子重算 */
          RSEED = newSeed();
          ITEMS.forEach(function (it) { delete it._rk; });
        }
        try { localStorage.setItem("gsp-sort2", state.sort); } catch (e) {}
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
    state = { q: "", tags: null, from: "", to: "", sort: state.sort, color: "", tol: 60, minpct: 0, page: 1, per: state.per };
    setCrgb(); syncColorUI(); writeTags();
    var fF = document.getElementById("f-from"), fT = document.getElementById("f-to");
    if (fF) fF.value = "";
    if (fT) fT.value = "";
    if (q) q.value = "";
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

  /* ── 颜色筛选 UI：取色器 / hex 输入 / 容差滑块（函数声明提升，reset 等处可先调用） ── */
  var fColor = document.getElementById("f-color");
  var fColorHex = document.getElementById("f-colorhex");
  var fColorClear = document.getElementById("f-colorclear");
  var fTol = document.getElementById("f-tol");
  var fTolVal = document.getElementById("f-tolval");
  var fMinPct = document.getElementById("f-minpct");
  var fMinPctVal = document.getElementById("f-minpctval");
  function syncColorUI() {
    if (!fColor) return;
    fColor.value = state.color || "#ffffff";
    fColorHex.value = state.color ? state.color.slice(1) : "";
    /* 任何非「手打非法hex」路径走到这里都说明值合法，残留的标红要清掉 */
    fColorHex.classList.remove("bad");
    fColorClear.hidden = !state.color;
    fTol.value = String(state.tol);
    fTolVal.textContent = String(state.tol);
    fMinPct.value = String(state.minpct);
    fMinPctVal.textContent = state.minpct + "%";
  }
  if (fColor) {
    fColor.addEventListener("input", function () {
      state.color = fColor.value.toUpperCase();
      setCrgb(); syncColorUI(); resetPage();
    });
    fColorHex.addEventListener("input", function () {
      var raw = fColorHex.value.trim().replace(/^#/, "");
      if (/^[0-9a-fA-F]{6}$/.test(raw)) {
        fColorHex.classList.remove("bad");
        state.color = "#" + raw.toUpperCase();
        setCrgb(); syncColorUI(); resetPage();
      } else if (!raw) {
        fColorHex.classList.remove("bad");
        state.color = ""; setCrgb(); syncColorUI(); resetPage();
      } else {
        fColorHex.classList.add("bad");   // 非法 hex 只标红不打断输入
      }
    });
    fColorHex.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        fColorHex.value = ""; fColorHex.classList.remove("bad");
        state.color = ""; setCrgb(); syncColorUI(); resetPage();
      }
    });
    fColorClear.addEventListener("click", function () {
      fColorHex.classList.remove("bad");
      state.color = ""; setCrgb(); syncColorUI(); resetPage();
    });
    fTol.addEventListener("input", function () {
      state.tol = parseInt(fTol.value, 10) || 0;
      fTolVal.textContent = String(state.tol);
      if (state.color) resetPage();   // 没选色时容差不参与筛选
    });
    fMinPct.addEventListener("input", function () {
      state.minpct = parseFloat(fMinPct.value) || 0;
      fMinPctVal.textContent = state.minpct + "%";
      if (state.color) resetPage();
    });
    syncColorUI();
  }

  /* ── 筛选区折叠（状态记在 localStorage） ── */
  var filterBtn = document.getElementById("filterBtn");
  var filterBox = document.getElementById("filters");
  function activeFilters() {
    var parts = [];
    if (state.tags) {
      var allT = [], ex = [];
      tagChips().forEach(function (b) { allT.push(b.getAttribute("data-v")); });
      allT.forEach(function (t) { if (state.tags.indexOf(t) < 0) ex.push(t); });
      parts.push("标签 " + (ex.length > 0 && ex.length <= 3 ? "排除 " + ex.join("、") : "仅 " + state.tags.join("、")));
    }
    if (state.from || state.to) parts.push("上传 " + (state.from || "…") + " ~ " + (state.to || "…"));
    if (state.q) parts.push("搜索 " + state.q);
    if (state.color) parts.push("颜色 " + state.color + " ±" + state.tol
      + (state.minpct > 0 ? " · 占比≥" + state.minpct + "%" : ""));
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

  /* 支持带参数的链接（标签跳转 / 分享筛选结果 / 返回恢复）：
     /?tag=海冰&q=xxx&from=…&to=…&sort=added_asc&color=1F4E79&tol=60&page=3 */
  var applied = false;
  try {
    var params = new URLSearchParams(location.search);
    ["q", "tag", "from", "to", "sort", "color", "tol", "pct", "page"].forEach(function (k) {
      var v = params.get(k);
      if (!v) return;
      if (k === "page") {
        var pn = parseInt(v, 10);
        if (pn >= 2) { state.page = pn; applied = true; }   // 第 1 页即默认，不必触发重渲染
        return;
      }
      if (k === "sort") {
        if (["added", "added_asc", "color", "random"].indexOf(v) === -1) return;
        state.sort = v;
        applied = true;
        if (sortseg) sortseg.querySelectorAll("button").forEach(function (x) {
          x.setAttribute("aria-pressed", String(x.getAttribute("data-sort") === v));
        });
        return;
      }
      if (k === "color") {
        var hc = String(v).replace(/^#/, "");
        if (/^[0-9a-fA-F]{6}$/.test(hc)) { state.color = "#" + hc.toUpperCase(); setCrgb(); applied = true; }
        return;
      }
      if (k === "tol") {
        var tv = parseInt(v, 10);
        if (tv >= 0 && tv <= 150) { state.tol = tv; if (state.color) applied = true; }
        return;
      }
      if (k === "pct") {
        var pv = parseFloat(v);
        if (pv >= 0 && pv <= 100) { state.minpct = pv; if (state.color) applied = true; }
        return;
      }
      if (k === "tag") {   // 多选：tag=A|B|C（兼容旧的单值链接）
        var names = String(v).split("|"), selT = [], c0 = tagChips();
        c0.forEach(function (b) {
          var on = names.indexOf(b.getAttribute("data-v")) > -1;
          b.setAttribute("aria-pressed", String(on));
          if (on) selT.push(b.getAttribute("data-v"));
        });
        state.tags = selT.length === c0.length ? null : selT;
        if (state.tags) applied = true;
        return;
      }
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
        /* from/to 不是 chips，日期输入框要同步回填，否则界面与状态不一致 */
        if (k === "from" && fFrom) fFrom.value = v;
        if (k === "to" && fTo) fTo.value = v;
      }
    });
  } catch (e) {}
  syncColorUI();   // URL 带 color/tol 进来时，把取色器/hex 输入/滑块回填成实际状态

  /* 首屏卡片是构建时静态输出的（对爬虫友好）。只有当"每页数量/排序"被用户改过、
     或链接带了筛选参数时，才用 JS 重新渲染，保证 DOM 与状态一致。
     （不重渲染的默认情况下，静态输出与 JS 首屏完全一致） */
  var needRender = applied || state.per !== PAGE || state.sort !== "added";
  if (needRender) {
    /* state.page > 1 只可能来自 URL 的 page 参数（如返回恢复 / 分享链接），保留之 */
    render();
  } else {
    var per0 = perSize(ITEMS);
    var pages0 = Math.max(1, Math.ceil(ITEMS.length / per0));
    if (info) info.textContent = "共 " + pages0 + " 页";
    if (prev) prev.disabled = true;
    if (next) next.disabled = ITEMS.length <= per0;
    paintNums(1, pages0);
    syncFilterBtn();
  }
  /* 记录图库当前地址（含筛选/页码），详情页「返回全部」据此跳回 */
  try { sessionStorage.setItem("gsp-back", location.pathname + location.search); } catch (e) {}

  /* 窄屏 / 宽屏切换时页码窗口会变，重算一次节点（不重建卡片） */
  var lastWin = windowSize();
  var onResize = function () {
    if (windowSize() === lastWin) return;
    lastWin = windowSize();
    var per1 = perSize(ITEMS.filter(pass));
    paintNums(state.page, Math.max(1, Math.ceil(ITEMS.filter(pass).length / per1)));
  };
  window.addEventListener("resize", onResize);

})();
