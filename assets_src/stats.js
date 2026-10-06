/**
 * stats —— 全站统计页（/stats/，仅该页随 stats-data.js 注入）。
 *
 * 访客向数据面板：hero 总览（数字滚动）→ 热看图片 Top 5（全量口径）→
 * 筛选（标签/画幅/上传日期区间）联动重算：上传动态面积图（SVG）· 主色构成环形图
 * （SVG，第一主色按色族归类 + 屏蔽色）· 高频颜色条形图（前 20 主色中出现该族
 * 即计一张）· 标签词云（螺旋碰撞布局）。
 * 手写 SVG + vanilla JS，无第三方库；数据 window.GSP_STATS 只含 id/标签/上传日期/画幅，
 * 画幅分类（横图/竖图/方图）已在构建期按原图宽高算好。
 */
(function () {
  const DATA = window.GSP_STATS || [];
  const grid = document.getElementById("st-grid");
  if (!grid) return;

  const el = (id) => document.getElementById(id);
  /* HTML 转义：标签是人工录入文本，进 innerHTML 前必须转义文本与属性两处 */
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  const LOCAL = location.hostname.match(/^(localhost|127\.0\.0\.1|)$/);
  const API = window.GSP_STATS_API || "";
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const state = { tag: "*", ar: "*", from: "", to: "" };

  /* 分类调色板（暗色亮色各一档，与站点 token 同源）：环形图 / hero 顶条 / 词云共用 */
  const PAL = [["#58a6ff", "#0969da"], ["#3fb950", "#1a7f37"], ["#a371f7", "#8250df"],
    ["#f0883e", "#bc4c00"], ["#db61a2", "#a2306e"], ["#39c5cf", "#0a7c84"]];
  const isLight = () => document.documentElement.getAttribute("data-theme") === "light";
  const col = (i) => PAL[i % PAL.length][isLight() ? 1 : 0];
  /* 色族 chip 的代表色（族成员均值在重算后才知道，chip 用固定代表色即可） */
  const FAM_SWATCH = { "白": "#FFFFFF", "黑": "#000000", "灰": "#808080", "红": "#e5534b",
    "橙": "#f0883e", "黄": "#d29922", "绿": "#3fb950", "青": "#39c5cf",
    "蓝": "#58a6ff", "紫": "#a371f7", "粉": "#db61a2" };

  /* ── 数字滚动：hero 总览 tile（reduced-motion 直接落值）── */
  function countUp(node, to) {
    if (!REDUCED) {
      const t0 = performance.now();
      const step = (t) => {
        const k = Math.min(1, (t - t0) / 700);
        node.textContent = Math.round(to * (1 - Math.pow(1 - k, 3)));
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    } else node.textContent = to;
  }

  /* ── 筛选控件：选项来自全量数据 ── */
  function fillSelect(sel, values) {
    /* label 由筛选行的 .flabel 承担，首项只写「全部」 */
    sel.innerHTML = `<option value="*">全部</option>` +
      values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  }
  fillSelect(el("st-tag"), [...new Set(DATA.flatMap((d) => d.tg || []))].sort());
  fillSelect(el("st-ar"), [...new Set(DATA.map((d) => d.ar).filter(Boolean))].sort());

  function filtered() {
    /* 时间筛选按上传日期（ad）做年月日比较。ad 目前都是完整日期（YYYY-MM-DD），
       但保留月精度兜底：将来若只到月（YYYY-MM），按整月区间 [月初, 月底] 与
       筛选区间取重叠 —— 字符串比较即可，"-31" 只是月内上界、不校验真实历法 */
    return DATA.filter((d) => {
      if (state.tag !== "*" && (d.tg || []).indexOf(state.tag) === -1) return false;
      if (state.ar !== "*" && d.ar !== state.ar) return false;
      if (state.from || state.to) {
        const v = d.ad || "";
        if (!v) return false;                     // 无上传日期：筛选激活时隐藏
        const ps = v.length === 7 ? v + "-01" : v;
        const pe = v.length === 7 ? v + "-31" : v;
        if (state.from && pe < state.from) return false;
        if (state.to && ps > state.to) return false;
      }
      return true;
    });
  }

  /* ── 聚合 ── */
  function countBy(list, get, topN) {
    const c = {};
    list.forEach((d) => {
      const v = get(d);
      if (!v) return;
      if (Array.isArray(v)) v.forEach((x) => { if (x) c[x] = (c[x] || 0) + 1; });
      else c[v] = (c[v] || 0) + 1;
    });
    const rows = Object.keys(c).map((k) => ({ k, n: c[k] }))
      .sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
    return topN ? rows.slice(0, topN) : rows;
  }

  /* ── 主色构成：每图取第一「未被屏蔽」的主色，按色族（红橙黄绿青蓝紫粉 + 黑灰白）归桶；
     图例色 = 该族成员色的 RGB 均值。屏蔽口径与色彩实验页一致：
     RGB 平方距离 < 1600（即欧氏距离 < 40）视为相近色一并屏蔽 ── */
  const hex2rgb = (h) => [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  const rgb2hex = (r, g, b) => "#" + [r, g, b]
    .map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
  /* 屏蔽色两类：快捷色族（白/黑/灰整族屏蔽，对付深浅不一的纯色背景）与
     拾取的具体色（RGB 平方距离 < 1600 即欧氏距离 < 40 的相近色，同色彩实验口径）。
     localStorage 记忆，重载后仍在 */
  const BL = { tol2: 1600, fams: [], list: [] };
  try {
    const saved = JSON.parse(localStorage.getItem("gsp-st-bl") || "{}");
    (saved.fams || []).forEach((f) => { if (typeof f === "string") BL.fams.push(f); });
    (saved.hexes || []).forEach((h) => {
      if (/^#[0-9A-Fa-f]{6}$/.test(h)) BL.list.push({ hex: h, rgb: hex2rgb(h.slice(1)) });
    });
  } catch (e) {}
  const blSave = () => {
    try {
      localStorage.setItem("gsp-st-bl",
        JSON.stringify({ fams: BL.fams, hexes: BL.list.map((b) => b.hex) }));
    } catch (e) {}
  };
  const isBlocked = (rgb) => BL.fams.indexOf(colorFamily(rgb)) > -1 || BL.list.some((b) =>
    (b.rgb[0] - rgb[0]) * (b.rgb[0] - rgb[0])
    + (b.rgb[1] - rgb[1]) * (b.rgb[1] - rgb[1])
    + (b.rgb[2] - rgb[2]) * (b.rgb[2] - rgb[2]) < BL.tol2);

  function colorFamily(rgb) {
    const [r, g, b] = rgb.map((v) => v / 255);
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    const l = (mx + mn) / 2;
    const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
    if (s < 0.14) return l >= 0.85 ? "白" : l <= 0.2 ? "黑" : "灰";   // 无彩：黑/灰/白
    let h = mx === r ? 60 * (((g - b) / d) % 6)
      : mx === g ? 60 * ((b - r) / d + 2) : 60 * ((r - g) / d + 4);
    if (h < 0) h += 360;
    if (h < 15 || h >= 345) return "红";
    if (h < 45) return "橙";
    if (h < 70) return "黄";
    if (h < 165) return "绿";
    if (h < 200) return "青";
    if (h < 255) return "蓝";
    if (h < 290) return "紫";
    return "粉";
  }

  function renderColorCard(list) {
    const fams = {};
    let noColor = 0, allBlocked = 0;
    list.forEach((d) => {
      const cs = d.cs || [];
      let hit = false;
      for (const hx of cs) {
        const rgb = hex2rgb(hx);
        if (isBlocked(rgb)) continue;          // 命中屏蔽色：落到该图下一主色
        const f = colorFamily(rgb);
        const o = fams[f] || (fams[f] = { n: 0, r: 0, g: 0, b: 0 });
        o.n++; o.r += rgb[0]; o.g += rgb[1]; o.b += rgb[2];
        hit = true;
        break;                                 // 每图只归一族（第一未屏蔽主色）
      }
      if (!hit) cs.length ? allBlocked++ : noColor++;
    });
    /* 图例色 = 族内成员色均值；段色直接用真实色，不走调色板 */
    let rows = Object.keys(fams).map((k) => {
      const o = fams[k];
      return { k, n: o.n, c: rgb2hex(o.r / o.n, o.g / o.n, o.b / o.n) };
    }).sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
    /* 超过 6 族时合并长尾为「其他」（灰阶），中心合计仍是全量口径 */
    const nTypes = rows.length;
    if (rows.length > 6) {
      const restN = rows.slice(6).reduce((s, r) => s + r.n, 0);
      rows = rows.slice(0, 6);
      if (restN > 0) rows.push({ k: "其他", n: restN, c: "var(--faint)" });
    }
    renderDonut(el("st-donut"), rows, nTypes);

    /* 屏蔽色 chips（两张卡各一份，内容同步）与快捷族按钮的点亮态 */
    const chipsHtml = BL.fams.map((f) =>
        `<span class="st-bl-chip"><i style="background:${FAM_SWATCH[f] || "#888"}"></i>${esc(f)}族`
        + `<button type="button" data-fam="${esc(f)}" aria-label="取消屏蔽${esc(f)}色族">×</button></span>`).join("")
      + BL.list.map((b, i) =>
          `<span class="st-bl-chip"><i style="background:${b.hex}"></i>${b.hex}`
          + `<button type="button" data-i="${i}" aria-label="移除屏蔽色 ${b.hex}">×</button></span>`).join("");
    document.querySelectorAll(".st-bl-chips").forEach((box) => { box.innerHTML = chipsHtml; });
    document.querySelectorAll(".st-bl-q").forEach((b) =>
      b.classList.toggle("on", BL.fams.indexOf(b.dataset.fam) > -1));
    const note = el("st-bl-note");
    const dropped = allBlocked + noColor;
    if (BL.list.length && (allBlocked || noColor)) {
      note.textContent = "已屏蔽 " + allBlocked + " 张（主色全部命中屏蔽色）"
        + (noColor ? "，另 " + noColor + " 张无主色数据" : "");
      note.hidden = false;
    } else if (dropped) {
      note.textContent = noColor + " 张无主色数据，未计入";
      note.hidden = false;
    } else note.hidden = true;
  }

  function blAdd(hex) {
    const h = hex.toUpperCase();
    if (BL.list.some((b) => b.hex === h)) return;
    BL.list.push({ hex: h, rgb: hex2rgb(h.slice(1)) });
    blSave();
    render();                                // 屏蔽后整卡重算（含 chips 与提示）
  }
  function blRemove(i) {
    BL.list.splice(i, 1);
    blSave();
    render();
  }
  function blFamToggle(fam) {
    const i = BL.fams.indexOf(fam);
    if (i > -1) BL.fams.splice(i, 1); else BL.fams.push(fam);
    blSave();
    render();
  }

  /* ── 高频颜色：按色族统计「图的前 20 主色里出现过该族」的图数
     （每图每族至多计一次，色号层面天然去重）；屏蔽色与主色构成共用
     同一份状态——命中屏蔽族/拾取屏蔽色的颜色不参与；
     行色板 = 该族全部成员色的 RGB 均值 ── */
  function renderColorBars(list) {
    const fams = {};
    list.forEach((d) => {
      const seen = {};
      (d.cs || []).forEach((hx) => {
        const rgb = hex2rgb(hx);
        if (isBlocked(rgb)) return;
        const f = colorFamily(rgb);
        if (seen[f]) return;                   // 每图每族只计一次
        seen[f] = true;
        const o = fams[f] || (fams[f] = { n: 0, r: 0, g: 0, b: 0, m: 0 });
        o.n++; o.r += rgb[0]; o.g += rgb[1]; o.b += rgb[2]; o.m++;
      });
    });
    const rows = Object.keys(fams).map((k) => {
      const o = fams[k];
      return { k, n: o.n, c: rgb2hex(o.r / o.m, o.g / o.m, o.b / o.m) };
    }).sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
    renderBars(el("st-bars"), rows);
  }
  /* ── 条形图：细轨 + 进场生长动画（innerHTML 重建即触发）；
     行键可带 r.c 色板（高频颜色卡显示具体色号）── */
  function renderBars(box, rows) {
    box.innerHTML = "";
    if (!rows.length) { box.innerHTML = '<p class="st-none">无数据</p>'; return; }
    const max = Math.max(...rows.map((r) => r.n));
    box.innerHTML = rows.map((r) => {
      const w = Math.max(2, Math.round((r.n / max) * 100));
      return `<div class="st-row"><span class="st-k${r.mono ? " mono" : ""}" title="${esc(r.k)}">`
        + (r.c ? `<i class="st-sw" style="background:${r.c}"></i>` : "")
        + `${esc(r.k)}</span>`
        + `<span class="st-bar"><i style="width:${w}%"></i></span>`
        + `<span class="st-n">${r.n}</span></div>`;
    }).join("");
  }

  /* ── 环形图：stroke-dasharray 段（r=15.9155 → 周长恰为 100，直接用百分比），
     中心合计，段与图例双向联动高亮。nTypes = 全部类目数（合并「其他」后
     rows.length 会少计，中心「N 类」标注用真实类目数） ── */
  function renderDonut(box, rows, nTypes) {
    box.innerHTML = "";
    if (!rows.length) { box.innerHTML = '<p class="st-none">无数据</p>'; return; }
    const total = rows.reduce((s, r) => s + r.n, 0);
    let acc = 0;
    const segs = rows.map((r, i) => {
      const pct = (r.n / total) * 100;
      const off = 25 - acc;               // 25 = 把起点从 3 点钟转到 12 点钟
      acc += pct;
      return `<circle class="seg" data-i="${i}" cx="18" cy="18" r="15.9155"`
        + ` style="stroke:${r.c || col(i)};stroke-dasharray:${pct} ${100 - pct};stroke-dashoffset:${off}"`
        + `><title>${esc(r.k)} · ${r.n} 张（${Math.round(pct)}%）</title></circle>`;
    }).join("");
    const legend = rows.map((r, i) =>
      `<div class="st-lg" data-i="${i}" style="--lc:${r.c || col(i)}"><i></i>`
      + `<span title="${esc(r.k)}">${esc(r.k)}</span><b>${r.n}</b><em>${Math.round(r.n / total * 100)}%</em></div>`
    ).join("");
    box.innerHTML = `<svg viewBox="0 0 36 36" role="img" aria-label="主色构成（按色族归类）">`
      + `<circle cx="18" cy="18" r="15.9155" style="fill:none;stroke:var(--line);stroke-width:3.6"/>`
      + segs
      + `<text x="18" y="16.6" text-anchor="middle" class="don-v">${total}</text>`
      + `<text x="18" y="21.2" text-anchor="middle" class="don-k">张 · ${nTypes || rows.length} 类</text></svg>`
      + `<div class="st-legend">${legend}</div>`;
    const segEls = [...box.querySelectorAll(".seg")];
    const lgEls = [...box.querySelectorAll(".st-lg")];
    const hl = (on) => {
      segEls.forEach((s, j) => {
        s.classList.toggle("off", on >= 0 && j !== on);
        s.classList.toggle("big", j === on);
      });
      lgEls.forEach((l, j) => l.classList.toggle("hl", j === on));
    };
    segEls.concat(lgEls).forEach((s) => {
      const i = +s.dataset.i;
      s.addEventListener("mouseenter", () => hl(i));
      s.addEventListener("mouseleave", () => hl(-1));
    });
  }

  /* ── 上传动态面积图：按图片上传日期（d.ad）逐日累计；
     SVG 按容器实测像素构建（文字不变形），resize 防抖重绘；
     悬停显示「日期 · 累计 N 张」── */
  function renderGrowth(box, list) {
    /* 日期归一：兼容只有年月（YYYY-MM）的日期 —— 补成该月首日，
       否则 new Date("2026-03T00:00:00Z") 是 Invalid Date 会直接炸掉图表 */
    const norm = (s) => s.length === 7 ? s + "-01" : s.length === 4 ? s + "-01-01" : s;
    const byDay = {};
    list.forEach((d) => {
      if (!d.ad) return;
      const k = norm(d.ad);
      if (isNaN(new Date(k + "T00:00:00Z"))) return;   // 脏日期兜底：跳过不进图
      byDay[k] = (byDay[k] || 0) + 1;
    });
    const days = Object.keys(byDay).sort();
    if (!days.length) { box.innerHTML = '<p class="st-none">无上传日期数据</p>'; return; }
    const t0 = new Date(days[0] + "T00:00:00Z");
    const N = Math.max(1, Math.round((new Date(days[days.length - 1] + "T00:00:00Z") - t0) / 864e5));
    const W = Math.max(320, box.clientWidth || 640), H = 200;
    const pl = 40, pr = 16, pt = 16, pb = 28;
    const pw = W - pl - pr, ph = H - pt - pb;
    let cum = 0;
    const pts = [];
    for (let i = 0; i <= N; i++) {
      const k = new Date(+t0 + i * 864e5).toISOString().slice(0, 10);
      cum += byDay[k] || 0;
      pts.push([k, cum, byDay[k] || 0]);
    }
    const max = pts[pts.length - 1][1];
    const X = (i) => pl + (i / N) * pw;
    const Y = (v) => pt + (1 - (max ? v / max : 0)) * ph;
    const line = pts.map((p, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
    const base = (pt + ph).toFixed(1);
    const area = `${line} L${X(N).toFixed(1)} ${base} L${X(0).toFixed(1)} ${base} Z`;
    /* 网格：0 / 半值 / 峰值 三条 */
    const ticks = [...new Set([0, Math.round(max / 2), max])];
    const gridSvg = ticks.map((v) =>
      `<line class="gl" x1="${pl}" y1="${Y(v).toFixed(1)}" x2="${W - pr}" y2="${Y(v).toFixed(1)}"/>`
      + `<text class="gt" x="${pl - 7}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${v}</text>`).join("");
    const mid = Math.round(N / 2);
    /* x 轴刻度：首/尾/中三档（端点优先）；索引重复（N≤1 时 mid 撞端点）或
       中点与两端间距 <44px 时丢弃，跨度为 0 只画一枚 */
    const seenI = new Set();
    const xlab = (N === 0 ? [[0, "middle"]] : [[0, "start"], [N, "end"], [mid, "middle"]]
        .filter(([i]) => {
          if (seenI.has(i)) return false;
          if (i !== 0 && i !== N && (X(i) - X(0) < 44 || X(N) - X(i) < 44)) return false;
          seenI.add(i);
          return true;
        }))
      .map(([i, a]) =>
        `<text class="gt" x="${X(i).toFixed(1)}" y="${H - 8}" text-anchor="${a}">${pts[i][0].slice(5)}</text>`).join("");
    /* 数据点：只有真实入库的日期出点；hit 大圆承担 hover */
    const marks = pts.map((p, i) => ({ x: X(i), y: Y(p[1]), k: p[0], n: p[1], add: p[2] }))
      .filter((p) => p.add > 0);
    const dotsSvg = marks.map((p, i) =>
      `<circle class="dotc" data-i="${i}" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3"/>`
      + `<circle class="hit" data-i="${i}" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="12"/>`).join("");
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}"><defs><linearGradient id="stgg" x1="0" y1="0" x2="0" y2="1">`
      + `<stop offset="0" style="stop-color:var(--accent);stop-opacity:.26"/>`
      + `<stop offset="1" style="stop-color:var(--accent);stop-opacity:0"/></linearGradient></defs>`
      + gridSvg
      + `<path d="${area}" style="fill:url(#stgg);stroke:none"/>`
      + `<path d="${line}" style="fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round;stroke-linecap:round"/>`
      + dotsSvg + xlab + `</svg><div class="st-gtip"></div>`;
    const tip = box.querySelector(".st-gtip");
    const dots = [...box.querySelectorAll(".dotc")];
    box.querySelectorAll(".hit").forEach((h) => {
      const i = +h.dataset.i;
      h.addEventListener("mouseenter", () => {
        const p = marks[i];
        const b = box.getBoundingClientRect();
        const r = h.getBoundingClientRect();
        const x = Math.max(46, Math.min(b.width - 46, r.left + r.width / 2 - b.left));
        tip.innerHTML = `<b>${p.k.slice(5)}</b> · 累计 ${p.n} 张（+${p.add}）`;
        tip.style.left = x + "px";
        tip.style.top = (r.top - b.top) + "px";
        tip.style.opacity = 1;
        if (dots[i]) dots[i].style.fill = "var(--accent)";
      });
      h.addEventListener("mouseleave", () => {
        tip.style.opacity = 0;
        if (dots[i]) dots[i].style.fill = "";
      });
    });
  }

  /* ── 词云：经典螺旋布局 —— 首词落中心，其余沿阿基米德螺旋外溢，
     用 DOM 实测包围盒做精确碰撞（不重叠不稀疏）；字号按频次对数映射 11–34px，
     颜色按名次分档（accent → 绿 → 紫 → 橙 → 灰阶），中后段长词偶发竖排；
     布局完全确定性 —— 同样的数据永远同样的形状（主题切换/筛选重绘不跳变）；
     椭圆系数按容器实测宽高归一，宽卡铺满不留大片空白 ── */
  function renderCloud(box, rows) {
    box.innerHTML = "";
    if (!rows.length) { box.innerHTML = '<p class="st-none">无数据</p>'; return; }
    const W = Math.max(280, box.clientWidth), H = Math.max(200, box.clientHeight);
    const small = W < 480;
    const data = rows.slice(0, small ? 16 : 32);
    const max = data[0].n, min = data[data.length - 1].n;
    const lr = Math.log(max / Math.max(1, min));            // 频次对数跨度
    const cx = W / 2, cy = H / 2;
    const TMAX = 620;
    const ax = (W / 2 - 6) / (5.5 * Math.sqrt(TMAX));       // 螺旋半径 → 容器宽映射
    const ay = (H / 2 - 6) / (5.5 * Math.sqrt(TMAX));
    const placed = [];
    const PAD = 3;
    const hits = (x, y, w, h) => placed.some((b) =>
      x < b.x + b.w + PAD && x + w > b.x - PAD && y < b.y + b.h + PAD && y + h > b.y - PAD);
    const tryPlace = (bw, bh) => {
      for (let t = 0; t < TMAX; t++) {
        const rad = 5.5 * Math.sqrt(t);
        const a = -Math.PI / 2 + t * 0.105;
        const x = cx + Math.cos(a) * rad * ax - bw / 2;
        const y = cy + Math.sin(a) * rad * ay - bh / 2;
        if (x < 2 || y < 2 || x + bw > W - 2 || y + bh > H - 2) continue;
        if (!hits(x, y, bw, bh)) return [x, y];
      }
      return null;
    };
    /* 颜色/透明度按名次分档：头两词主色、其后绿→紫→橙、长尾灰阶垫底 */
    const TCOL = [col(0), col(1), col(2), col(3), "var(--faint)"];
    const TOP = [1, .92, .85, .8, .72];
    const tier = (i) => i < 2 ? 0 : i < 6 ? 1 : i < 12 ? 2 : i < 19 ? 3 : 4;
    const frag = document.createDocumentFragment();
    data.forEach((r, i) => {
      const k = lr > 0 ? Math.log(r.n / Math.max(1, min)) / lr : 1;
      const size = Math.round(11 + k * (small ? 17 : 23));  // 11–34px
      const s = document.createElement("span");
      s.className = "st-w";
      s.textContent = r.k;
      s.title = r.k + " × " + r.n;
      s.style.fontSize = size + "px";
      s.style.color = TCOL[tier(i)];
      s.style.opacity = TOP[tier(i)];
      s.style.animationDelay = Math.min(480, i * 18) + "ms";
      frag.appendChild(s);
    });
    box.appendChild(frag);                                  // 入 DOM 才有真实包围盒
    const els = [...box.querySelectorAll(".st-w")];
    /* 面积守恒：词总面积超过容器可用面积（50%）时整体等比缩小字号 ——
       中屏/小屏也能放下全部词（层级关系不变；缩后逐词重测无需重排档位） */
    let area = 0;
    els.forEach((s) => { area += s.offsetWidth * s.offsetHeight; });
    const usable = W * H * 0.5;
    if (area > usable) {
      const f = Math.max(0.55, Math.sqrt(usable / area));   // 最多缩到 55% 防过小
      els.forEach((s) => s.style.fontSize = Math.max(9, parseFloat(s.style.fontSize) * f) + "px");
    }
    let fb = 0;                                             // 兜底堆叠行号
    els.forEach((s, i) => {
      let w = s.offsetWidth, h = s.offsetHeight;
      const vert = !small && i >= 8 && i % 6 === 4 && w > h * 2.2;   // 长词偶发竖排
      if (vert) s.classList.add("st-wv");
      let bw = vert ? h : w, bh = vert ? w : h;             // 旋转后包围盒
      let pos = tryPlace(bw, bh);
      if (!pos) {                                           // 放不下 → 缩 15% 再试
        s.style.fontSize = parseFloat(s.style.fontSize) * 0.85 + "px";
        w = s.offsetWidth; h = s.offsetHeight;
        bw = vert ? h : w, bh = vert ? w : h;
        pos = tryPlace(bw, bh);
      }
      if (pos) {                                            // left/top 取旋转前盒的左上角
        s.style.left = (pos[0] + (bw - w) / 2) + "px";
        s.style.top = (pos[1] + (bh - h) / 2) + "px";
        placed.push({ x: pos[0], y: pos[1], w: bw, h: bh });
      } else {
        s.style.left = "2px";
        s.style.top = (2 + fb * 20) + "px";                 // 兜底：左侧纵向排开不互叠
        placed.push({ x: 2, y: 2 + fb * 20, w: bw, h: bh });
        fb++;
      }
    });
  }

  function render() {
    const list = filtered();
    el("st-count").textContent = `命中 ${list.length} / ${DATA.length} 张`;
    el("st-empty").hidden = list.length > 0;
    grid.style.visibility = list.length ? "visible" : "hidden";

    renderGrowth(el("st-growth"), list);
    renderColorCard(list);
    renderColorBars(list);                   // 高频颜色：具体色号出现次数 Top 10
    renderCloud(el("st-cloud"), countBy(list, (d) => d.tg, 34));
  }

  /* ── hero 总览（全量口径）── */
  countUp(el("stv-items"), DATA.length);
  countUp(el("stv-tags"), new Set(DATA.flatMap((d) => d.tg || []).filter(Boolean)).size);
  countUp(el("stv-months"), new Set(DATA.map((d) => (d.ad || "").slice(0, 7)).filter(Boolean)).size);

  /* ── 热看图片 Top 5 + hero「图片被浏览」：一次 fetch 同时喂两处；
     全量口径不随筛选重算；只统计图片详情页，
     浏览数相同按随机排序，只展示前 5 ── */
  const rankBox = el("st-rank");
  const viewsEl = el("stv-views");
  /* API 为空 = 同源（nginx 把 /api/ 反代到主站统计服务），不能当作「未配置」——
     此前若写成 if (!LOCAL && API)，线上 api 默认空串会导致热看榜永远不 fetch（实测踩过） */
  if (!LOCAL) {
    fetch((API || "") + "/api/v1/stats/views?prefix=/geosciplot/")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d || !d.items) throw 0;
        /* 只统计图片详情页：path 末段必须命中已知图片 id ——
           正则拦不住 /stats/ /search/ /color-lab/ 这类单段系统路径（实测会混进 Top5） */
        const rows = d.items
          .map((x) => {
            const id = x.path.replace(/^\/geosciplot\//, "").replace(/\/$/, "");
            const meta = DATA.find((m) => m.id === id);
            return { id, ok: !!meta, n: x.views || 0,
              sub: ((meta && meta.tg) || []).join(" · "), rnd: Math.random() };
          })
          .filter((r) => r.ok);
        countUp(viewsEl, rows.reduce((s, r) => s + r.n, 0));
        const top = rows.slice().sort((a, b) => b.n - a.n || a.rnd - b.rnd).slice(0, 5);
        if (!top.length) { rankBox.innerHTML = '<p class="st-none">暂无浏览数据</p>'; return; }
        const max = top[0].n || 1;
        rankBox.innerHTML = top.map((r, i) => {
          const medal = i === 0 ? " top" : i < 3 ? " pod" : "";
          return `<div class="st-rank${medal}" style="--w:${Math.max(6, Math.round((r.n / max) * 100))}%">`
            + `<span class="rk">${i + 1}</span>`
            + `<span class="tt"><a href="../${r.id}/" title="图 ${esc(r.id)}">图 ${esc(r.id)}</a>`
            + `<small>${esc(r.sub) || "—"}</small></span>`
            + `<span class="n">${r.n} 次</span></div>`;
        }).join("");
      })
      .catch(() => {
        viewsEl.textContent = "—";
        rankBox.innerHTML = '<p class="st-none">浏览数据获取失败（统计服务不可达）</p>';
      });
  } else {
    viewsEl.textContent = "—";
    viewsEl.title = "部署后按访客实际浏览计入";
    rankBox.innerHTML = '<p class="st-none">本地预览无浏览统计（部署后按访客实际浏览计入）</p>';
  }

  /* ── 明暗主题切换后重绘（SVG 颜色构建时写死，换主题需重建）── */
  new MutationObserver(render).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-theme"] });

  /* ── 窗口尺寸变化：面积图与词云都按容器实测像素构建，统一防抖重算 ── */
  let rzT;
  window.addEventListener("resize", () => {
    clearTimeout(rzT);
    rzT = setTimeout(render, 180);
  });

  /* ── 屏蔽色事件：快捷色族再点一次 = 取消屏蔽；拾色器确认后添加；
     chips 上 × 移除（色族 / 具体色各按其键） ── */
  document.querySelectorAll(".st-bl-q").forEach((b) =>
    b.addEventListener("click", () => blFamToggle(b.dataset.fam)));
  el("st-bl-pick").addEventListener("change", (e) => blAdd(e.target.value));
  document.querySelectorAll(".st-bl-chips").forEach((box) =>
    box.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      if (btn.dataset.fam) blFamToggle(btn.dataset.fam);
      else if (btn.dataset.i !== undefined) blRemove(+btn.dataset.i);
    }));

  /* ── 筛选事件 ── */
  el("st-tag").addEventListener("change", (e) => { state.tag = e.target.value; render(); });
  el("st-ar").addEventListener("change", (e) => { state.ar = e.target.value; render(); });
  el("st-from").addEventListener("input", (e) => { state.from = e.target.value.trim(); render(); });
  el("st-to").addEventListener("input", (e) => { state.to = e.target.value.trim(); render(); });
  el("st-reset").addEventListener("click", () => {
    state.tag = "*"; state.ar = "*"; state.from = ""; state.to = "";
    el("st-tag").value = "*"; el("st-ar").value = "*";
    el("st-from").value = ""; el("st-to").value = "";
    render();
  });

  render();
})();
