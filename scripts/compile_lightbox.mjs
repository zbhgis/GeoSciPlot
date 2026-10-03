// 把 lib/image-lightbox.ts（零依赖原生 TS）编译成浏览器可直接 <script> 引用的
// assets_src/image-lightbox.js：Node ≥23.2 内置 TS 类型剥离，无需任何 npm 依赖。
// 用法：node scripts/compile_lightbox.mjs（改完 TS 源后重跑，再 python scripts/build_site.py）
import { readFileSync, writeFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const src = readFileSync(join(root, "lib", "image-lightbox.ts"), "utf8");

// strip 模式只删除类型（接口/标注/断言），遇到 enum 等不可剥离语法会直接报错，
// 恰好守住"这份源码必须保持零依赖可剥离"的约束。
const js = stripTypeScriptTypes(src, { mode: "strip" });

// 唯一的 ESM 导出改成 IIFE 内函数，并挂到全局供宿主页面调用
if (!js.includes("export function attachImageLightbox")) {
  throw new Error("lib/image-lightbox.ts 的导出形式变了，请同步修改本编译脚本");
}
const banner =
  "/*! 由 lib/image-lightbox.ts 编译生成（node scripts/compile_lightbox.mjs），勿直接改动 */\n";
const out =
  banner +
  js.replace("export function attachImageLightbox", "function attachImageLightbox") +
  "\nglobalThis.ImageLightbox = { attachImageLightbox };\n";
writeFileSync(join(root, "assets_src", "image-lightbox.js"), out, "utf8");
console.log("· image-lightbox.ts → assets_src/image-lightbox.js（" + out.length + " 字节）");
