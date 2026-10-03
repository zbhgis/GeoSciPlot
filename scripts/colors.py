#!/usr/bin/env python3
"""GeoSciPlot 配色提取：统计图片占比最高的前 N 个主色，作为图片 meta 的一部分。

产出写入 meta/refs.json 各条目的 colors 字段：
    "colors": [{"hex": "#AABBCC", "pct": 12.34}, ...]   # 按占比降序，最多 20 个

消费方：
    · scripts/build_site.py —— 详情页「配色」色块行（色块可跳转色彩实验并预选目标色）
    · 与 assets_src/color-lab.js 的浏览器端算法保持一致（5bit/通道直方图 +
      近色合并，欧氏距离 < 40），两边对同一张图给出的主色基本相同

用法：
    python scripts/colors.py             # 回填：只为缺 colors 的条目计算
    python scripts/colors.py --force     # 重新计算全部条目
    python scripts/colors.py --dry-run   # 只报告，不写文件

正常上传流程不需要单独跑本脚本：scripts/prepare.py 入库时会自动计算新图的颜色。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "images"
REFS_JSON = ROOT / "meta" / "refs.json"

TOP_N = 20              # 最多保留的主色个数
MAX_SAMPLES = 160_000   # 抽样像素上限（大图先等比缩小再统计）
MERGE_DIST2 = 1600      # 近色合并阈值：RGB 欧氏距离平方 < 40^2
ALPHA_MIN = 128         # 透明度低于该值的像素不参与统计（与前端一致）


def extract_colors(path: Path, top: int = TOP_N) -> list[dict]:
    """统计一张图的主色：[{hex, pct}]，pct 为相对全部不透明采样像素的占比。"""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if "A" in img.getbands() or img.mode == "P":
            img = img.convert("RGBA")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        n_px = w * h
        if n_px > MAX_SAMPLES:
            scale = math.sqrt(MAX_SAMPLES / n_px)
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BOX)
        img = img.convert("RGBA")

        counts: dict[int, int] = {}
        sums: dict[int, list[int]] = {}
        total = 0
        for r, g, b, a in img.getdata():
            if a < ALPHA_MIN:
                continue
            k = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
            c = counts.get(k)
            if c is None:
                counts[k] = 1
                sums[k] = [r, g, b]
            else:
                counts[k] = c + 1
                sums[k][0] += r
                sums[k][1] += g
                sums[k][2] += b
            total += 1

    if not total:
        return []

    out: list[list] = []   # [累计像素数, r, g, b]
    for k in sorted(counts, key=counts.get, reverse=True):
        if len(out) >= top:
            break
        c = counts[k]
        s = sums[k]
        r, g, b = round(s[0] / c), round(s[1] / c), round(s[2] / c)
        dup = -1
        for j, o in enumerate(out):
            dd = (o[1] - r) ** 2 + (o[2] - g) ** 2 + (o[3] - b) ** 2
            if dd < MERGE_DIST2:
                dup = j
                break
        if dup >= 0:
            out[dup][0] += c
        else:
            out.append([c, r, g, b])

    # 近色合并会把靠后 bin 的权重累计进靠前的色，最终占比可能与主 bin 顺序不一致，
    # 按累计权重重新排序保证色块行严格降序
    out.sort(key=lambda o: -o[0])
    return [{"hex": "#%02X%02X%02X" % (r, g, b),
             "pct": round(c / total * 100, 2)} for c, r, g, b in out]


def backfill(force: bool = False, dry_run: bool = False) -> int:
    if not REFS_JSON.exists():
        print("! 找不到 meta/refs.json，请先运行 python scripts/prepare.py")
        return 1
    refs = json.loads(REFS_JSON.read_text(encoding="utf-8"))
    items = refs.get("items", [])
    n_done = n_skip = n_fail = 0
    for it in items:
        if not force and it.get("colors"):
            n_skip += 1
            continue
        full = IMG_DIR / str(it.get("full", ""))
        if not full.is_file():
            print(f"  ! 原图缺失，跳过：{it.get('id')}（{it.get('full')}）")
            n_fail += 1
            continue
        colors = extract_colors(full)
        if colors:
            it["colors"] = colors
            n_done += 1
        print(f"  {it['id']}  {len(colors)} 色  前3："
              + " ".join(f"{c['hex']}({c['pct']}%)" for c in colors[:3]))
    if not dry_run and n_done:
        REFS_JSON.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n写入 {REFS_JSON.relative_to(ROOT)}")
    print(f"计算 {n_done} 条 · 已有跳过 {n_skip} 条 · 失败 {n_fail} 条 · 共 {len(items)} 条")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="GeoSciPlot 配色提取 / 回填")
    ap.add_argument("--force", action="store_true", help="重新计算全部条目（默认只补缺失的）")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = ap.parse_args()
    sys.exit(backfill(force=args.force, dry_run=args.dry_run))
