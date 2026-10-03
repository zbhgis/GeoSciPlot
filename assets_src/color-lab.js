/* 色彩实验（/color-lab/）：本地取色 + 调色工具，无任何外部依赖。
   数据来自 gallery-data.js（id 清单 + fu=原图相对路径）；
   图片按「原图各源 → 缩略图各源」分两层加载，层内各源并行竞速
   （全部带 CORS 并通过 1×1 可读性测试，最先可读者胜出）——
   串行逐源降级时，慢源/被墙源会把后续源全部堵住，随机一张要等十几秒。
   流程：载入原图 → 框选区域（不框选=整张图）→ 统计占比前 N 的主色（数量滑块 4–20，
        色块+色号）→ 背景色可「屏蔽」进黑名单（含相近色），占比按剩余像素重新归一
        → 点选目标色 + 容差 + 新颜色 → 区域内替换 → 可叠加 / 撤销 / 还原 / 下载 PNG。
   画布交互分两种模式（「开始/结束框选」按钮切换）：框选模式下拖拽选区；
   非框选模式（默认）单击画布打开放大镜（滚轮缩放/拖拽平移，显示当前编辑状态）。
   全部计算在浏览器本地完成。 */
(function () {
  "use strict";
  var CFG = window.GALLERY, ITEMS = window.GALLERY_DATA || [];
  var $ = function (id) { return document.getElementById(id); };
  if (!CFG || !$("cl-canvas")) return;

  var canvas = $("cl-canvas"), ctx = canvas.getContext("2d", { willReadFrequently: true });
  var work = document.createElement("canvas"), wctx = work.getContext("2d", { willReadFrequently: true });
  var overlay = $("cl-overlay"), selbox = $("cl-selbox"), placeholder = $("cl-placeholder");
  var statusEl = $("cl-status"), selinfo = $("cl-selinfo");
  var idInput = $("cl-id"), paletteEl = $("cl-palette");
  var loadBtn = $("cl-load"), randomBtn = $("cl-random"), loadingEl = $("cl-loading");
  var targetChip = $("cl-target-chip"), targetHex = $("cl-target-hex");
  var newColor = $("cl-newcolor"), tol = $("cl-tol"), tolval = $("cl-tolval");
  var scopeSel = $("cl-scope"), highlightCb = $("cl-highlight");
  var paletteCount = $("cl-count"), paletteCountVal = $("cl-countval");
  var replaceBtn = $("cl-replace"), undoBtn = $("cl-undo"), downloadBtn = $("cl-download");
  var clearselBtn = $("cl-clearsel"), selModeBtn = $("cl-selmode");
  var zoomEl = $("cl-zoom"), zoomView = $("cl-zoom-view"), zoomCanvas = $("cl-zoom-canvas");
  var zctx = zoomCanvas.getContext("2d");

  var origImg = null, curId = "";
  var natW = 0, natH = 0;
  var sel = null;          // 框选区域 {x,y,w,h}（原图自然坐标）；null = 整张图
  var target = null;       // 待替换的目标色 {r,g,b,hex}
  var blacklist = [];      // [{r,g,b,hex}] 屏蔽的背景色（含相近色，不计入主色统计）
  var undoStack = [];      // [{x,y,data:ImageData}] 每次替换前的区域快照
  var rafPending = false;
  var loadBusy = false;    // 载入进行中：禁用「载入/随机」按钮，防止并发载入互相覆盖
  var selMode = false;     // 框选模式：开=拖拽选区，关（默认）=单击画布打开放大镜
  var zoomOpen = false, zoomScale = 1;
  var urlColor = "";       // ?color=%23AABBCC（详情页配色色块跳入）：载入后预选为目标色

  function setStatus(msg, isErr) {
    statusEl.textContent = msg || "";
    statusEl.style.color = isErr ? "#f85149" : "";
  }
  function hex2(r, g, b) {
    return "#" + ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1).toUpperCase();
  }
  function hexToRgb(h) {
    var m = /^#?([0-9a-f]{6})$/i.exec(String(h).trim());
    if (!m) return null;
    var n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  /* ── 载入：分层竞速。candidateTiers 返回 [原图×各源, 缩略图×各源]，
     层内并行请求、最先通过可读性测试（1×1 getImageData，CORS）者胜出；
     整层全败才降下一层。单源 20s 兜底超时，防止被墙源把整层挂死 ── */
  function candidateTiers(id) {
    for (var i = 0; i < ITEMS.length; i++) {
      if (ITEMS[i].id !== id) continue;
      var rels = [];
      if (ITEMS[i].fu) rels.push(ITEMS[i].fu);
      if (ITEMS[i].rel) rels.push(ITEMS[i].rel);
      var bases = CFG.sources.slice(CFG.active).concat(CFG.sources.slice(0, CFG.active));
      return rels.map(function (rel) {
        return bases.map(function (base) { return base + "/" + rel; });
      });
    }
    return null;
  }
  var LOAD_TIMEOUT = 20000;
  function raceLoad(urls, ok, fail) {
    var pending = urls.length;
    if (!pending) { fail(); return; }
    var settled = false;
    urls.forEach(function (url) {
      var img = new Image();
      img.crossOrigin = "anonymous";
      var done = false;
      var timer = setTimeout(function () {
        if (done || settled) return;
        done = true;
        img.src = "";   // 中止挂死的下载
        if (--pending === 0) fail();
      }, LOAD_TIMEOUT);
      img.onload = function () {
        if (done || settled) return;
        done = true; clearTimeout(timer);
        try {   // 画得上 ≠ 读得了：1×1 像素可读性测试（CORS）
          var t = document.createElement("canvas");
          t.width = 1; t.height = 1;
          var tc = t.getContext("2d");
          tc.drawImage(img, 0, 0, 1, 1);
          tc.getImageData(0, 0, 1, 1);
        } catch (e) {
          if (--pending === 0) fail();
          return;
        }
        settled = true;
        img.setAttribute("data-src", url);
        ok(img);
      };
      img.onerror = function () {
        if (done || settled) return;
        done = true; clearTimeout(timer);
        if (--pending === 0) fail();
      };
      img.src = url;
    });
  }
  function loadById(rawId) {
    if (loadBusy) return;
    var id = String(rawId || "").trim();
    if (!id) { setStatus("请先输入图片 id", true); return; }
    var tiers = candidateTiers(id);
    if (!tiers) { setStatus("图库里没有 id 为 " + id + " 的图片", true); return; }
    loadBusy = true;
    loadBtn.disabled = true; randomBtn.disabled = true;
    loadingEl.hidden = false;
    setStatus("载入中：" + id + " …");
    var ti = 0;
    (function nextTier() {
      if (ti >= tiers.length) { endLoad(false, id, null); return; }
      raceLoad(tiers[ti++], function (img) { endLoad(true, id, img); }, nextTier);
    })();
  }
  function endLoad(got, id, img) {
    loadBusy = false;
    loadBtn.disabled = false; randomBtn.disabled = false;
    loadingEl.hidden = true;
    if (!got) { setStatus("载入失败：" + id + "（图片托管于 GitHub，需要具备访问能力）", true); return; }
    curId = id;   // 载入成功才记 id：失败时画布/下载仍对应上一张图
    origImg = img;
    natW = img.naturalWidth; natH = img.naturalHeight;
    work.width = natW; work.height = natH;
    canvas.width = natW; canvas.height = natH;
    wctx.drawImage(img, 0, 0);
    sel = null; target = null; undoStack = [];
    targetChip.style.background = "transparent";
    targetHex.textContent = "未选择";
    syncSelbox(); syncControls();
    redraw(); computePalette();
    placeholder.style.display = "none";
    if (urlColor) {   // 详情页配色色块带 ?color= 跳入 → 只在首次载入预选一次
      setTarget(urlColor);
      urlColor = "";
    }
    var isThumb = (img.getAttribute("data-src") || "").indexOf("/thumb/") > -1;
    setStatus("已载入 图 " + id + "（" + natW + "×" + natH + "px" + (isThumb ? "，原图不可达，暂用缩略图" : "") + "）");
    try {
      history.replaceState(null, "", "?id=" + encodeURIComponent(id)
        + (urlColor ? "&color=" + encodeURIComponent(urlColor) : ""));
    } catch (e) {}
  }

  /* ── 框选模式开关：开=拖拽选区（十字光标）；关=单击画布打开放大镜（zoom-in 光标） ── */
  function setSelMode(on) {
    selMode = on;
    selModeBtn.textContent = on ? "结束框选" : "开始框选";
    selModeBtn.setAttribute("data-on", String(on));
    selModeBtn.setAttribute("aria-pressed", String(on));
    selModeBtn.title = on ? "关闭后恢复单击打开放大镜" : "开启后拖拽框选统计区域；关闭时单击画布打开放大镜";
    overlay.setAttribute("data-sel", String(on));
  }
  selModeBtn.addEventListener("click", function () { setSelMode(!selMode); });

  /* ── 画布指针交互：统一鼠标/触摸；显示坐标换算成原图自然像素 ── */
  function ptOf(e) {
    var r = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(natW, Math.round((e.clientX - r.left) * (natW / r.width)))),
      y: Math.max(0, Math.min(natH, Math.round((e.clientY - r.top) * (natH / r.height))))
    };
  }
  function paintSelbox(x, y, w, h) {
    selbox.style.display = "block";
    selbox.style.left = (x / natW * 100) + "%";
    selbox.style.top = (y / natH * 100) + "%";
    selbox.style.width = (w / natW * 100) + "%";
    selbox.style.height = (h / natH * 100) + "%";
  }
  function syncSelbox() {
    if (sel) paintSelbox(sel.x, sel.y, sel.w, sel.h);
    else selbox.style.display = "none";
    syncSelinfo();
  }
  function syncSelinfo() {
    if (!origImg) { selinfo.textContent = ""; return; }
    if (!sel) { selinfo.textContent = "未框选 · 当前统计整张图（" + natW + "×" + natH + "）"; return; }
    var pct = (sel.w * sel.h / (natW * natH) * 100).toFixed(1);
    selinfo.textContent = "已框选 " + sel.w + "×" + sel.h + "px（占整图 " + pct + "%）";
  }
  var dragStart = null, downPt = null;
  overlay.addEventListener("pointerdown", function (e) {
    if (!origImg || (e.button && e.button > 0)) return;
    downPt = ptOf(e);
    overlay.setPointerCapture(e.pointerId);
    if (selMode) dragStart = downPt;
    e.preventDefault();
  });
  overlay.addEventListener("pointermove", function (e) {
    if (!dragStart) return;
    var p = ptOf(e);
    paintSelbox(Math.min(dragStart.x, p.x), Math.min(dragStart.y, p.y),
      Math.abs(dragStart.x - p.x), Math.abs(dragStart.y - p.y));
  });
  overlay.addEventListener("pointerup", function (e) {
    if (!downPt) return;
    var down = downPt;
    downPt = null;
    var c = ptOf(e);
    if (!dragStart) {   // 非框选模式：单击（位移很小）= 打开放大镜
      if (Math.abs(c.x - down.x) < 5 && Math.abs(c.y - down.y) < 5) openZoom();
      return;
    }
    var a = dragStart;
    dragStart = null;
    var x0 = Math.min(a.x, c.x), y0 = Math.min(a.y, c.y);
    var w = Math.abs(a.x - c.x), h = Math.abs(a.y - c.y);
    if (w < 4 || h < 4) { syncSelbox(); return; }   // 太小视为误触，维持原框选
    sel = { x: x0, y: y0, w: w, h: h };
    syncSelbox(); syncControls();
    computePalette(); requestRedraw();
  });
  overlay.addEventListener("pointercancel", function () {
    /* 触屏拖拽被系统手势/来电等接管时必须复位 dragStart，
       否则残留后无按键的 pointermove 会拖着选框跟光标跑 */
    dragStart = null; downPt = null;
    syncSelbox();
  });
  clearselBtn.addEventListener("click", function () {
    if (!sel) return;
    sel = null;
    syncSelbox(); syncControls();
    computePalette(); requestRedraw();
  });

  /* ── 放大镜：渲染当前（可能已替换）画布状态，滚轮以光标为锚缩放、
     拖拽平移、＋/−/适配窗口/1:1、Esc 或按钮关闭；叠加显示框选矩形 ── */
  var ZOOM_MIN = 0.05, ZOOM_MAX = 8;
  function zoomClamp(s) { return Math.min(Math.max(s, ZOOM_MIN), ZOOM_MAX); }
  function zoomRender() {
    var w = Math.max(1, Math.round(natW * zoomScale));
    var h = Math.max(1, Math.round(natH * zoomScale));
    zoomCanvas.width = w; zoomCanvas.height = h;
    zctx.imageSmoothingEnabled = zoomScale < 1;   // 放大看细节时保留原始像素感
    zctx.drawImage(work, 0, 0, w, h);
    if (sel) {
      var accent = "#58a6ff";
      try {
        var av = getComputedStyle(document.documentElement).getPropertyValue("--accent");
        if (av) accent = av.trim();
      } catch (e) {}
      /* 画布像素空间 = 原图坐标 × zoomScale，矩形坐标要同步缩放；
         lineWidth=2 即 2 屏幕像素（canvas 本身 1:1 显示） */
      zctx.strokeStyle = accent;
      zctx.lineWidth = 2;
      zctx.strokeRect(sel.x * zoomScale, sel.y * zoomScale, sel.w * zoomScale, sel.h * zoomScale);
      zctx.fillStyle = "rgba(88,166,255,.12)";
      zctx.fillRect(sel.x * zoomScale, sel.y * zoomScale, sel.w * zoomScale, sel.h * zoomScale);
    }
    $("cl-zoom-pct").textContent = Math.round(zoomScale * 100) + "%";
  }
  function zoomFitScale() {
    var vw = zoomView.clientWidth - 24, vh = zoomView.clientHeight - 24;
    return zoomClamp(Math.min(vw / natW, vh / natH));
  }
  function zoomCenter() {
    zoomView.scrollLeft = (zoomCanvas.width - zoomView.clientWidth) / 2;
    zoomView.scrollTop = (zoomCanvas.height - zoomView.clientHeight) / 2;
  }
  function openZoom() {
    if (!origImg) return;
    zoomOpen = true;
    zoomEl.hidden = false;
    document.body.style.overflow = "hidden";
    zoomScale = zoomFitScale();
    zoomRender();
    zoomCenter();
  }
  function closeZoom() {
    zoomOpen = false;
    zoomEl.hidden = true;
    document.body.style.overflow = "";
  }
  zoomView.addEventListener("wheel", function (e) {
    if (!zoomOpen) return;
    e.preventDefault();
    var rect = zoomView.getBoundingClientRect();
    var cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    var sx = (zoomView.scrollLeft + cx) / zoomScale;   // 光标下的原图坐标
    var sy = (zoomView.scrollTop + cy) / zoomScale;
    zoomScale = zoomClamp(zoomScale * (e.deltaY < 0 ? 1.2 : 1 / 1.2));
    zoomRender();
    zoomView.scrollLeft = sx * zoomScale - cx;
    zoomView.scrollTop = sy * zoomScale - cy;
  }, { passive: false });
  var panStart = null;
  zoomView.addEventListener("pointerdown", function (e) {
    if (!zoomOpen) return;
    panStart = { x: e.clientX, y: e.clientY, sl: zoomView.scrollLeft, st: zoomView.scrollTop };
    zoomView.setPointerCapture(e.pointerId);
  });
  zoomView.addEventListener("pointermove", function (e) {
    if (!panStart) return;
    zoomView.scrollLeft = panStart.sl - (e.clientX - panStart.x);
    zoomView.scrollTop = panStart.st - (e.clientY - panStart.y);
  });
  ["pointerup", "pointercancel"].forEach(function (t) {
    zoomView.addEventListener(t, function () { panStart = null; });
  });
  $("cl-zoom-in").addEventListener("click", function () { zoomScale = zoomClamp(zoomScale * 1.25); zoomRender(); });
  $("cl-zoom-out").addEventListener("click", function () { zoomScale = zoomClamp(zoomScale / 1.25); zoomRender(); });
  $("cl-zoom-fit").addEventListener("click", function () { zoomScale = zoomFitScale(); zoomRender(); zoomCenter(); });
  $("cl-zoom-one").addEventListener("click", function () { zoomScale = 1; zoomRender(); zoomCenter(); });
  $("cl-zoom-close").addEventListener("click", closeZoom);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && zoomOpen) closeZoom();
  });

  /* ── 主色统计：5bit/通道直方图 → 按像素数排序 → 黑名单过滤（欧氏距离<40，含相近色）
     → 近色合并（同阈值）→ 前 N（数量滑块 4–20）。大区域按 step 抽样，
     采样点上限约 16 万。黑名单像素从分母剔除，占比在剩余颜色间重新归一 ── */
  function computePalette() {
    if (!origImg) return;
    var topN = parseInt(paletteCount.value, 10) || 8;
    var r = sel || { x: 0, y: 0, w: natW, h: natH };
    var data;
    try { data = wctx.getImageData(r.x, r.y, r.w, r.h).data; }
    catch (e) { setStatus("读取像素失败（图片源不允许跨域读取）", true); return; }
    var step = Math.max(1, Math.round(Math.sqrt(r.w * r.h / 160000)));
    var N = 32768;
    var cnt = new Uint32Array(N), sr = new Uint32Array(N), sg = new Uint32Array(N), sb = new Uint32Array(N);
    var n = 0;
    for (var y = 0; y < r.h; y += step) {
      var row = y * r.w;
      for (var x = 0; x < r.w; x += step) {
        var i = (row + x) * 4;
        if (data[i + 3] < 128) continue;   // 半透明/全透明像素不参与
        var R = data[i], G = data[i + 1], B = data[i + 2];
        var k = ((R >> 3) << 10) | ((G >> 3) << 5) | (B >> 3);
        cnt[k]++; sr[k] += R; sg[k] += G; sb[k] += B; n++;
      }
    }
    if (!n) { paletteEl.innerHTML = '<p class="cl-note">该区域没有不透明像素</p>'; return; }
    var bins = [];
    for (var k2 = 0; k2 < N; k2++) if (cnt[k2]) bins.push(k2);
    bins.sort(function (a, b) { return cnt[b] - cnt[a]; });
    var out = [], nSkip = 0;
    for (var bi = 0; bi < bins.length && out.length < topN; bi++) {
      var kb = bins[bi];
      var c = [Math.round(sr[kb] / cnt[kb]), Math.round(sg[kb] / cnt[kb]), Math.round(sb[kb] / cnt[kb])];
      var banned = false;
      for (var b2 = 0; b2 < blacklist.length; b2++) {
        var bl = blacklist[b2];
        var bd = (bl.r - c[0]) * (bl.r - c[0]) + (bl.g - c[1]) * (bl.g - c[1]) + (bl.b - c[2]) * (bl.b - c[2]);
        if (bd < 1600) { banned = true; break; }
      }
      if (banned) { nSkip += cnt[kb]; continue; }
      var dup = -1;
      for (var j = 0; j < out.length; j++) {
        var o = out[j].rgb;
        var dd = (o[0] - c[0]) * (o[0] - c[0]) + (o[1] - c[1]) * (o[1] - c[1]) + (o[2] - c[2]) * (o[2] - c[2]);
        if (dd < 1600) { dup = j; break; }
      }
      if (dup > -1) out[dup].w += cnt[kb];
      else out.push({ rgb: c, w: cnt[kb] });
    }
    /* 近色合并会打乱累计占比的顺序，按权重重排保证主色列表严格降序 */
    out.sort(function (a, b) { return b.w - a.w; });
    var denom = n - nSkip;
    if (denom <= 0) {
      paletteEl.innerHTML = '<p class="cl-note">黑名单屏蔽了该区域全部颜色，可移除部分或清空黑名单</p>';
      return;
    }
    var html = "";
    out.forEach(function (o) {
      var hx = hex2(o.rgb[0], o.rgb[1], o.rgb[2]);
      var pct = o.w / denom * 100;
      html += '<button type="button" class="cl-swatch" data-hex="' + hx + '"'
        + (target && target.hex === hx ? ' data-on="true"' : '')
        + ' title="点击设为要替换的目标色">'
        + '<span class="cl-chip" style="background:' + hx + '"></span>'
        + '<span class="cl-meta"><span class="cl-hex mono">' + hx + '</span>'
        + '<span class="cl-sub">rgb(' + o.rgb.join(",") + ') · ' + (pct >= 10 ? pct.toFixed(1) : pct.toFixed(2)) + '%</span></span>'
        + '<span class="cl-copy" title="复制色号">复制</span>'
        + '<span class="cl-ban" title="加入黑名单（含相近色，不计入统计）">屏蔽</span></button>';
    });
    paletteEl.innerHTML = html;
  }
  paletteEl.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".cl-swatch") : null;
    if (!btn) return;
    var hx = btn.getAttribute("data-hex");
    if (e.target.classList && e.target.classList.contains("cl-ban")) { banColor(hx); return; }
    if (e.target.classList && e.target.classList.contains("cl-copy")) { copyText(hx); return; }
    setTarget(hx);
  });
  /* ── 黑名单：屏蔽/移除/清空。名单在换图时保留（方便连续浏览同一批同底色图），
     仅存于当前页面会话，刷新即复位 ── */
  function banColor(hex) {
    var rgb = hexToRgb(hex);
    if (!rgb) return;
    var hx = hex.toUpperCase();
    for (var i = 0; i < blacklist.length; i++) {
      if (blacklist[i].hex === hx) return;
    }
    blacklist.push({ r: rgb[0], g: rgb[1], b: rgb[2], hex: hx });
    renderBlacklist();
    computePalette();
    setStatus("已屏蔽 " + hx + "（含相近色），主色已重算");
  }
  function renderBlacklist() {
    var box = $("cl-blacklist");
    if (!blacklist.length) { box.hidden = true; return; }
    box.hidden = false;
    $("cl-blchips").innerHTML = blacklist.map(function (b, i) {
      return '<span class="cl-bl-chip"><i style="background:' + b.hex + '"></i>' + b.hex
        + '<a data-i="' + i + '" title="移除">×</a></span>';
    }).join("");
  }
  $("cl-blchips").addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!a) return;
    blacklist.splice(parseInt(a.getAttribute("data-i"), 10), 1);
    renderBlacklist();
    computePalette();
  });
  $("cl-blclear").addEventListener("click", function () {
    if (!blacklist.length) return;
    blacklist = [];
    renderBlacklist();
    computePalette();
    setStatus("黑名单已清空，主色已重算");
  });
  function setTarget(hex) {
    var rgb = hexToRgb(hex);
    if (!rgb) return;
    target = { r: rgb[0], g: rgb[1], b: rgb[2], hex: hex.toUpperCase() };
    targetChip.style.background = target.hex;
    targetHex.textContent = target.hex;
    paletteEl.querySelectorAll(".cl-swatch").forEach(function (b) {
      b.setAttribute("data-on", String(b.getAttribute("data-hex") === target.hex));
    });
    syncControls(); requestRedraw();
  }
  function copyText(s) {
    var done = function () { setStatus("已复制 " + s); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(s).then(done, function () { fallbackCopy(s, done); });
    } else fallbackCopy(s, done);
  }
  function fallbackCopy(s, done) {
    var ta = document.createElement("textarea");
    ta.value = s;
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) {}
    document.body.removeChild(ta);
  }

  /* ── 替换：目标色容差内（RGB 欧氏距离）的像素 → 新颜色，只动选定范围。
     替换前保存区域快照供撤销；替换后重算主色，方便连续调色 ── */
  function scopeRect() {
    if (scopeSel.value === "all" || !sel) return { x: 0, y: 0, w: natW, h: natH };
    return sel;
  }
  replaceBtn.addEventListener("click", function () {
    if (!origImg || !target) return;
    var r = scopeRect();
    var t = [target.r, target.g, target.b];
    var nc = hexToRgb(newColor.value) || [0, 0, 0];
    var t2 = (+tol.value) * (+tol.value);
    var snap, img;
    try {
      snap = wctx.getImageData(r.x, r.y, r.w, r.h);
      img = wctx.getImageData(r.x, r.y, r.w, r.h);
    } catch (e) { setStatus("读取像素失败", true); return; }
    var d = img.data, n = 0;
    for (var i = 0; i < d.length; i += 4) {
      if (d[i + 3] === 0) continue;
      var dr = d[i] - t[0], dg = d[i + 1] - t[1], db = d[i + 2] - t[2];
      if (dr * dr + dg * dg + db * db <= t2) {
        d[i] = nc[0]; d[i + 1] = nc[1]; d[i + 2] = nc[2]; n++;
      }
    }
    if (!n) { setStatus("容差 " + tol.value + " 内没有命中「" + target.hex + "」的像素，可调大容差"); return; }
    undoStack.push({ x: r.x, y: r.y, data: snap });
    /* 快照按区域像素×4B 吃内存：大图（>4MP）限 3 步，常规图 8 步 */
    var maxUndo = natW * natH > 4000000 ? 3 : 8;
    if (undoStack.length > maxUndo) undoStack.shift();
    wctx.putImageData(img, r.x, r.y);
    redraw(); computePalette(); syncControls();
    setStatus("已替换 " + n.toLocaleString() + " 个像素 → " + hex2(nc[0], nc[1], nc[2]));
  });
  undoBtn.addEventListener("click", function () {
    var u = undoStack.pop();
    if (!u) return;
    wctx.putImageData(u.data, u.x, u.y);
    redraw(); computePalette(); syncControls();
    setStatus("已撤销一步");
  });
  $("cl-resetimg").addEventListener("click", function () {
    if (!origImg) return;
    wctx.drawImage(origImg, 0, 0);
    undoStack = [];
    redraw(); computePalette(); syncControls();
    setStatus("已还原为原图");
  });
  downloadBtn.addEventListener("click", function () {
    if (!origImg) return;
    work.toBlob(function (blob) {
      if (!blob) { setStatus("导出失败", true); return; }
      var a = document.createElement("a");
      var url = URL.createObjectURL(blob);
      a.href = url;
      a.download = (curId || "image") + "-调色.png";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 3000);
    }, "image/png");
  });

  /* ── 画布渲染：当前状态 + 可选的「将被替换像素」品红高亮遮罩 ── */
  function redraw() {
    if (!origImg) return;
    ctx.drawImage(work, 0, 0);
    if (highlightCb.checked && target) drawHighlight();
  }
  function drawHighlight() {
    var r = scopeRect();
    var img;
    try { img = wctx.getImageData(r.x, r.y, r.w, r.h); } catch (e) { return; }
    var d = img.data;
    var t = [target.r, target.g, target.b], t2 = (+tol.value) * (+tol.value);
    var mask = document.createElement("canvas");
    mask.width = r.w; mask.height = r.h;
    var mc = mask.getContext("2d");
    var md = mc.createImageData(r.w, r.h);
    var m = md.data;
    for (var i = 0; i < d.length; i += 4) {
      if (d[i + 3] === 0) continue;
      var dr = d[i] - t[0], dg = d[i + 1] - t[1], db = d[i + 2] - t[2];
      if (dr * dr + dg * dg + db * db <= t2) {
        m[i] = 255; m[i + 1] = 64; m[i + 2] = 129; m[i + 3] = 140;
      }
    }
    mc.putImageData(md, 0, 0);
    ctx.drawImage(mask, r.x, r.y);
  }
  function requestRedraw() {
    if (rafPending || !origImg) return;
    rafPending = true;
    requestAnimationFrame(function () { rafPending = false; redraw(); });
  }
  tol.addEventListener("input", function () { tolval.textContent = tol.value; requestRedraw(); });
  highlightCb.addEventListener("change", requestRedraw);
  scopeSel.addEventListener("change", requestRedraw);
  paletteCount.addEventListener("input", function () {
    paletteCountVal.textContent = paletteCount.value;
    computePalette();
  });

  function syncControls() {
    overlay.style.pointerEvents = origImg ? "auto" : "none";
    replaceBtn.disabled = !origImg || !target;
    undoBtn.disabled = !origImg || !undoStack.length;
    downloadBtn.disabled = !origImg;
    clearselBtn.disabled = !origImg || !sel;
  }

  /* ── 初始化：id 候选列表（datalist）+ 随机 + ?id= 直达 ── */
  (function init() {
    var dl = $("cl-ids");
    ITEMS.forEach(function (it) {
      var o = document.createElement("option");
      o.value = it.id;
      var lb = (it.tg || []).join(" · ");
      if (lb) o.label = lb;
      dl.appendChild(o);
    });
    $("cl-load").addEventListener("click", function () { loadById(idInput.value); });
    idInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); loadById(idInput.value); }
    });
    $("cl-random").addEventListener("click", function () {
      if (!ITEMS.length) return;
      loadById(ITEMS[Math.floor(Math.random() * ITEMS.length)].id);
    });
    var qid = "", qcolor = "";
    try {
      qid = new URLSearchParams(location.search).get("id") || "";
      qcolor = (new URLSearchParams(location.search).get("color") || "").toUpperCase();
    } catch (e) {}
    if (qcolor && hexToRgb(qcolor)) urlColor = qcolor;
    if (qid) { idInput.value = qid; loadById(qid); }
    setSelMode(false);
    syncControls();
  })();
})();
