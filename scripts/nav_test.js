#!/usr/bin/env node
/* GeoSciPlot 导航 / 返回链路冒烟测试（playwright-core + 本机 Chrome/Edge，无需下载浏览器）
 *
 * 前置：
 *   1) python scripts/build_site.py --preview     # 本地图片源构建
 *   2) cd site && python -m http.server 7332 --bind 127.0.0.1   # 7332 = README 约定的预览端口
 *   3) NODE_PATH=<node workspace>/node_modules node scripts/nav_test.js
 *
 * 覆盖用例：
 *   T1 标签筛选 → URL 同步 → 进详情 → 「返回全部」回到带筛选的首页
 *   T2 筛选 → 详情 → 「下一张」跨详情跳转 → 返回仍带筛选
 *   T3 翻页 → 进详情 → 浏览器返回 → 停留在第 2 页
 *   T4 带参 URL 直开 / 刷新 → 筛选状态恢复（含日期输入框回填）
 *   T5 搜索页 → 结果 → 返回全部 → 回到带 ?q= 的搜索结果
 *   T6 直链打开详情页（无图库访问记录）→ 「返回全部」回落 ../
 *   T7 排序 → URL 同步 + 刷新后按钮态恢复
 */
'use strict';
const { chromium } = require('playwright-core');
const fs = require('fs');

const BASE = process.env.GSP_BASE || 'http://127.0.0.1:7332';
const OUT = process.env.GSP_OUT || 'nav_test_result.json';
const results = [];
const jsErrors = [];

function log(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail || '' });
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (ok ? '' : '  ← ' + (detail || '')));
}
const pathQS = (u) => { const x = new URL(u); return x.pathname + x.search; };

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  page.on('pageerror', (e) => jsErrors.push(String(e)));

  /* ---------- T1 标签筛选 → 详情 → 返回全部 ---------- */
  await page.goto(BASE + '/');
  const tag = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.chips[data-key="tag"] button')];
    for (const b of btns) {
      const v = b.getAttribute('data-v');
      if (v && v !== '*') {
        const m = (b.textContent || '').match(/(\d+)\s*$/);
        if (m && parseInt(m[1], 10) >= 2) return v;   // 选计数 ≥2 的标签，保证能测「下一张」
      }
    }
    return btns.length > 1 ? btns[1].getAttribute('data-v') : null;
  });
  log('T1-prep 找到计数≥2的标签', !!tag, 'tag=' + tag);
  await page.evaluate((t) => {
    document.querySelector('.chips[data-key="tag"] button[data-v="' + t + '"]').click();
  }, tag);
  await page.waitForFunction((t) => new URLSearchParams(location.search).get('tag') === t, tag);
  const t1url = await page.evaluate(() => location.pathname + location.search);
  log('T1a 点击标签后 URL 带 ?tag=', t1url.indexOf('tag=') > -1, t1url);
  const t1pressed = await page.evaluate((t) =>
    document.querySelector('.chips[data-key="tag"] button[data-v="' + t + '"]').getAttribute('aria-pressed') === 'true', tag);
  log('T1b 标签按钮选中态', t1pressed);
  const t1count = await page.evaluate(() => document.getElementById('count').textContent);
  log('T1c 计数文案变为「匹配 …」', t1count.indexOf('匹配') === 0, t1count);

  await page.click('.grid a.card');
  await page.waitForFunction(() => document.getElementById('backLink') !== null);
  const t1back = await page.evaluate(() => document.getElementById('backLink').getAttribute('href'));
  log('T1d 详情页返回链接指向带筛选的首页', t1back === '/?tag=' + encodeURIComponent(tag), 'href=' + t1back);
  await page.click('#backLink');
  await page.waitForFunction((t) => new URLSearchParams(location.search).get('tag') === t, tag);
  const t1backPressed = await page.evaluate((t) =>
    document.querySelector('.chips[data-key="tag"] button[data-v="' + t + '"]').getAttribute('aria-pressed') === 'true', tag);
  log('T1e 返回后筛选态恢复（按钮选中 + 计数）', t1backPressed &&
    (await page.evaluate(() => document.getElementById('count').textContent)).indexOf('匹配') === 0);

  /* ---------- T2 详情 → 下一张 → 返回全部 ---------- */
  await page.click('.grid a.card');
  await page.waitForFunction(() => document.getElementById('backLink') !== null);
  const hasNext = await page.evaluate(() => document.querySelector('a.pn-next') !== null);
  if (hasNext) {
    await page.click('a.pn-next');
    await page.waitForFunction(() =>
      document.getElementById('backLink') && /\/[0-9a-f]{8,}\/$/.test(location.pathname));
    const t2back = await page.evaluate(() => document.getElementById('backLink').getAttribute('href'));
    log('T2a 跨详情跳转后返回链接仍带筛选', t2back === '/?tag=' + encodeURIComponent(tag), 'href=' + t2back);
    await page.click('#backLink');
    await page.waitForFunction((t) => new URLSearchParams(location.search).get('tag') === t, tag);
    log('T2b 返回后仍在筛选结果', true);
  } else {
    log('T2 跳过（该标签只有 1 张图）', true);
  }

  /* ---------- T3 翻页 → 详情 → 浏览器返回 ---------- */
  await page.goto(BASE + '/');
  await page.waitForFunction(() => !!document.getElementById('next'));
  await page.click('#next');
  await page.waitForFunction(() => new URLSearchParams(location.search).get('page') === '2');
  log('T3a 翻页后 URL 带 ?page=2', true);
  const t3id = await page.evaluate(() => document.querySelector('.grid a.card').getAttribute('data-id'));
  await page.click('.grid a.card');
  await page.waitForFunction(() => document.getElementById('backLink') !== null);
  await page.goBack();
  await page.waitForFunction(() => new URLSearchParams(location.search).get('page') === '2');
  const t3on = await page.evaluate(() => {
    const b = document.querySelector('.pgnum[aria-current="page"]');
    return b ? b.textContent : '';
  });
  log('T3b 浏览器返回后停在第 2 页', t3on === '2', 'active=' + t3on + ' card=' + t3id);

  /* ---------- T4 带参 URL 直开：筛选+页码+日期恢复 ---------- */
  await page.goto(BASE + '/?tag=' + encodeURIComponent(tag) + '&page=1');
  const t4a = await page.evaluate((t) =>
    document.querySelector('.chips[data-key="tag"] button[data-v="' + t + '"]').getAttribute('aria-pressed') === 'true', tag);
  log('T4a ?tag= 直开恢复标签选中', t4a);
  await page.goto(BASE + '/?from=2026-01-01&to=2099-12-31');
  const t4b = await page.evaluate(() => ({
    from: document.getElementById('f-from').value,
    to: document.getElementById('f-to').value,
    count: document.getElementById('count').textContent,
  }));
  log('T4b 日期参数回填输入框并生效',
    t4b.from === '2026-01-01' && t4b.to === '2099-12-31' && t4b.count.indexOf('匹配') === 0,
    JSON.stringify(t4b));

  /* ---------- T5 搜索页 → 结果 → 返回全部 ---------- */
  await page.goto(BASE + '/search/');
  const term = tag;
  await page.fill('#spage-q', term);
  await page.waitForFunction((t) => new URLSearchParams(location.search).get('q') === t, term);
  const nres = await page.evaluate(() => document.querySelectorAll('.sres').length);
  log('T5a 搜索出结果且 URL 带 ?q=', nres > 0, 'n=' + nres);
  if (nres > 0) {
    await page.click('.sres');
    await page.waitForFunction(() => document.getElementById('backLink') !== null);
    const t5back = await page.evaluate(() => document.getElementById('backLink').getAttribute('href'));
    log('T5b 详情返回链接指向搜索结果页', t5back === '/search/?q=' + encodeURIComponent(term), 'href=' + t5back);
    await page.click('#backLink');
    await page.waitForFunction((t) => document.getElementById('spage-q').value === t, term);
    const t5n = await page.evaluate(() => document.querySelectorAll('.sres').length);
    log('T5c 返回后搜索结果仍在', t5n === nres, 'n=' + t5n);
  }

  /* ---------- T6 直链详情页：返回链接回落 ../ ---------- */
  const someId = await page.evaluate(() => window.GALLERY_DATA[0].id);
  const ctx2 = await browser.newContext();          // 全新会话：无 sessionStorage 记录
  const p2 = await ctx2.newPage();
  p2.on('pageerror', (e) => jsErrors.push('ctx2: ' + String(e)));
  await p2.goto(BASE + '/' + someId + '/');
  const t6href = await p2.evaluate(() => document.getElementById('backLink').getAttribute('href'));
  log('T6a 直链打开时返回链接保持 ../', t6href === '../', 'href=' + t6href);
  await p2.click('#backLink');
  await p2.waitForFunction(() => location.pathname === '/' && location.search === '');
  log('T6b 回落到未筛选首页', true);
  await ctx2.close();

  /* ---------- T7 排序 → URL 同步 + 刷新恢复 ---------- */
  await page.goto(BASE + '/');
  await page.evaluate(() => document.querySelector('#sortseg button[data-sort="added_asc"]').click());
  await page.waitForFunction(() => new URLSearchParams(location.search).get('sort') === 'added_asc');
  await page.reload();
  const t7 = await page.evaluate(() => ({
    url: new URLSearchParams(location.search).get('sort'),
    pressed: document.querySelector('#sortseg button[data-sort="added_asc"]').getAttribute('aria-pressed'),
  }));
  log('T7 排序写入 URL 且刷新后按钮态恢复', t7.url === 'added_asc' && t7.pressed === 'true', JSON.stringify(t7));

  await browser.close();
  const fails = results.filter(r => !r.ok).length;
  fs.writeFileSync(OUT, JSON.stringify({ base: BASE, fails, jsErrors, results }, null, 2), 'utf-8');
  console.log('----');
  console.log(fails === 0 && jsErrors.length === 0
    ? 'ALL PASS (' + results.length + ' checks)'
    : 'FAILS=' + fails + ' JS_ERRORS=' + jsErrors.length);
  if (jsErrors.length) console.log('jsErrors: ' + jsErrors.join(' | '));
  process.exit(fails === 0 && jsErrors.length === 0 ? 0 : 1);
})().catch((e) => { console.error('RUNNER ERROR: ' + e.message); process.exit(2); });
