(function () {
  var CFG = window.GALLERY, ITEMS = window.GALLERY_DATA || [], PAGE = window.GALLERY_PAGE || 48;
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
        d.items.forEach(function (x) { map[x.path.replace(/\/$/, "")] = x.views; });
        var n = map["/geosciplot" + location.pathname.replace(/\/$/, "")] || 0;
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
    // 阈值 400px 与主站 zbhgis.com 的 .v3-rail-top 保持一致，两站行为统一
    var onScroll = function () { topBtn.classList.toggle("show", window.scrollY > 400); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ── 全站搜索独立页（/search/）：静态站没有检索后端，直接在 gallery-data.js
     的全量元数据上做客户端匹配（id / DOI / 标签 / 日期，多词空格分隔 = 同时命中）。
     结果行带缩略图，经 bind() 走三源降级；无 thumb 的条目直接输出「无图」占位。
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
      // 动态插入的缩略图要手动绑三源降级（gallery.js 只自动绑页面已有的 img[data-rel]）
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
    return;
  }
  grid.querySelectorAll("img[data-rel]").forEach(bind);   // 首屏静态卡片也要绑降级

  /* ── 分页 + 筛选 + 排序 ── */
  var state = { q: "", tag: "*", from: "", to: "", sort: "added", page: 1, per: PAGE };
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
  /* 状态 → URL：筛选/排序/页码写进地址栏（replaceState 不新增历史记录，不打断返回手势）。
     浏览器返回、刷新、分享链接都会带上当前筛选状态；搜索词用输入框原文（保留大小写） */
  function syncUrl() {
    try {
      var parts = [];
      var qv = ((q && q.value) ? q.value : state.q).trim();
      if (qv) parts.push("q=" + encodeURIComponent(qv));
      if (state.tag !== "*") parts.push("tag=" + encodeURIComponent(state.tag));
      if (state.from) parts.push("from=" + encodeURIComponent(state.from));
      if (state.to) parts.push("to=" + encodeURIComponent(state.to));
      if (state.sort !== "added") parts.push("sort=" + encodeURIComponent(state.sort));
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
      var filtered = state.q || state.tag !== "*" || state.from || state.to;
      count.textContent = filtered ? "匹配 " + list.length + " / " + ITEMS.length + " 张"
                                   : "共 " + ITEMS.length + " 张";
    }
    if (empty) empty.style.display = list.length ? "none" : "block";
    syncFilterBtn();
    syncUrl();
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
    if (["added", "added_asc", "random"].indexOf(state.sort) === -1) state.sort = "added";
    var sortBtns = sortseg.querySelectorAll("button");
    sortBtns.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-sort") === state.sort));
      b.addEventListener("click", function () {
        state.sort = b.getAttribute("data-sort");
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
    state = { q: "", tag: "*", from: "", to: "", sort: state.sort, page: 1, per: state.per };
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

  /* 支持带参数的链接（标签跳转 / 分享筛选结果 / 返回恢复）：
     /?tag=海冰&q=xxx&from=…&to=…&sort=added_asc&page=3 */
  var applied = false;
  try {
    var params = new URLSearchParams(location.search);
    ["q", "tag", "from", "to", "sort", "page"].forEach(function (k) {
      var v = params.get(k);
      if (!v) return;
      if (k === "page") {
        var pn = parseInt(v, 10);
        if (pn >= 2) { state.page = pn; applied = true; }   // 第 1 页即默认，不必触发重渲染
        return;
      }
      if (k === "sort") {
        if (["added", "added_asc", "random"].indexOf(v) === -1) return;
        state.sort = v;
        applied = true;
        if (sortseg) sortseg.querySelectorAll("button").forEach(function (x) {
          x.setAttribute("aria-pressed", String(x.getAttribute("data-sort") === v));
        });
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
