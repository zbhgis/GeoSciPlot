/**
 * code-block —— 代码块工具栏（复制 / 折叠展开 / 高亮开关）
 *
 * 拷自主站 zbhgis.com 博客详情页（PageEnhancements 的 CodeBlockEnhancements，
 * React → 原生 JS 改写）。纯静态站无动态插入，构建期已渲染完所有
 * [data-code-block]，脚本在 body 末尾注入时 DOM 已就绪，扫一遍绑定即可，
 * 无需 MutationObserver。配套样式（.code-block 全套）在站点 style.css。
 */
(() => {
  document.querySelectorAll("[data-code-block]").forEach((block) => {
    const pre = block.querySelector("pre");
    if (!pre) return;
    const text = pre.textContent || "";

    // —— 复制：clipboard API 优先，execCommand 兜底；成功后 copied 态 1.5s
    const copyBtn = block.querySelector("[data-action=copy]");
    copyBtn?.addEventListener("click", async () => {
      let ok = false;
      try {
        if (navigator.clipboard) {
          await navigator.clipboard.writeText(text);
          ok = true;
        }
      } catch (err) { /* 非安全上下文等场景 */ }
      if (!ok) {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        try { ok = document.execCommand("copy"); } catch (err) { /* 仍失败则静默 */ }
        document.body.removeChild(ta);
      }
      if (ok) {
        copyBtn.classList.add("copied");
        copyBtn.title = "已复制";
        setTimeout(() => {
          copyBtn.classList.remove("copied");
          copyBtn.title = "复制";
        }, 1500);
      }
    });

    // —— 高亮开关：off 时 token 全部回退正文色（CSS .highlight-off 接管）
    const hlBtn = block.querySelector("[data-action=highlight]");
    hlBtn?.addEventListener("click", () => {
      const off = block.classList.toggle("highlight-off");
      hlBtn.classList.toggle("active", !off);
    });

    // —— 折叠/展开：收至 ~3 行 + 底部渐隐（CSS .collapsed 接管）
    const colBtn = block.querySelector("[data-action=collapse]");
    colBtn?.addEventListener("click", () => {
      const collapsed = block.classList.toggle("collapsed");
      colBtn.classList.toggle("active", collapsed);
      colBtn.title = collapsed ? "展开" : "折叠/展开";
    });
  });
})();
