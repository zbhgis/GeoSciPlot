#!/usr/bin/env python3
"""GeoSciPlot 图片预处理：把 raw/ 里杂乱的原图规范化为「缩略图 + 原图副本 + 索引」。

用法：
    python scripts/prepare.py            # 增量处理（已处理过的跳过）
    python scripts/prepare.py --force    # 全部重新生成
    python scripts/prepare.py --dry-run  # 只报告，不写文件
    python scripts/prepare.py --export-csv   # 导出 meta/titles.csv 供 Excel 编辑

输入：raw/**               任意文件名、任意尺寸、png/jpg/jpeg/webp/bmp/tiff（扁平投放，不看子目录）

输出：images/thumb/{日期}/{id}.webp   列表缩略图（长边 ≤480，质量 78）
      images/full/{日期}/{id}.{ext}   原图副本（**原始字节，不做任何压缩**）
      meta/refs.json                  索引（前端唯一数据源）

**日期目录**：目录名 = 该图**首次进入管道的日期**（即上传日期，YYYY-MM-DD），
同一天上传的图放在一起；重新生成时沿用索引里记录的日期，路径保持稳定。

命名策略：id = 文件内容的 sha1 前 10 位，与文件名无关。因此
  * 同一张图改名或重传，不会产生重复条目（内容去重）
  * meta/titles.csv 里人工填写的字段会被保留（优先级：CSV > refs.json）
  原始文件名记录在 origName 字段里，可追溯。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
IMG_DIR = ROOT / "images"
THUMB_DIR = IMG_DIR / "thumb"
FULL_DIR = IMG_DIR / "full"
META_DIR = ROOT / "meta"
REFS_JSON = META_DIR / "refs.json"
TITLES_CSV = META_DIR / "titles.csv"

THUMB_MAX = 480         # 缩略图长边上限
THUMB_Q = 78            # 缩略图 WebP 质量

SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

# 人工可编辑字段（CSV 列 → refs.json 字段）
MANUAL_FIELDS = ["journal", "published", "desc"]
MANUAL_LIST_FIELDS = ["tags"]
# 仅保留历史数据、不再在前端使用（迁移期兼容）
KEEP_FIELDS = ["title", "category"]


def file_id(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:10]


def load_existing() -> dict[str, dict]:
    if not REFS_JSON.exists():
        return {}
    try:
        data = json.loads(REFS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("  ! meta/refs.json 解析失败，将重新生成（人工字段会丢失）")
        return {}
    return {item["id"]: item for item in data.get("items", []) if item.get("id")}


def load_titles() -> dict[str, dict]:
    """读 meta/titles.csv（人工编辑表）。CSV 优先级高于 refs.json。"""
    if not TITLES_CSV.exists():
        return {}
    out: dict[str, dict] = {}
    with TITLES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            fid = (row.get("id") or "").strip()
            if not fid:
                continue
            rec: dict = {}
            for k in MANUAL_FIELDS + KEEP_FIELDS:
                v = (row.get(k) or "").strip()
                if v:
                    rec[k] = v
            for k in MANUAL_LIST_FIELDS:
                v = (row.get(k) or "").strip()
                if v:
                    rec[k] = [t.strip() for t in v.split("|") if t.strip()]
            out[fid] = rec
    return out


def export_titles(items: list[dict]) -> None:
    """导出人工编辑表（utf-8-sig：Excel 打开中文不乱码）。"""
    TITLES_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["id"] + MANUAL_FIELDS + KEEP_FIELDS[:1] + MANUAL_LIST_FIELDS
    with TITLES_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for it in items:
            w.writerow([it.get("id", ""), it.get("journal", ""), it.get("published", ""),
                        it.get("desc", ""), it.get("title", ""),
                        "|".join(it.get("tags", []))])
    print(f"导出编辑表 → {TITLES_CSV.relative_to(ROOT)}（Excel 编辑后重跑本脚本即回填）")


def collect_sources() -> list[Path]:
    """扫描 raw/：扁平投放，子目录名不再承担分类含义。"""
    if not RAW_DIR.exists():
        print(f"! 找不到投放目录 {RAW_DIR}")
        sys.exit(1)
    out: list[Path] = []
    for p in sorted(RAW_DIR.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in SUPPORTED:
            print(f"  - 跳过不支持的文件：{p.relative_to(RAW_DIR)}")
            continue
        out.append(p)
    return out


def make_assets(src: Path, fid: str, day: str) -> tuple[int, int, str, int]:
    """生成缩略图（压缩）+ 原图副本（不压缩）到 images/{thumb,full}/{日期}/。"""
    ext = src.suffix.lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"

    thumb_day = THUMB_DIR / day
    full_day = FULL_DIR / day
    thumb_day.mkdir(parents=True, exist_ok=True)
    full_day.mkdir(parents=True, exist_ok=True)

    full_path = full_day / f"{fid}.{ext}"
    shutil.copyfile(src, full_path)          # 原图：逐字节复制
    full_bytes = full_path.stat().st_size

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        w, h = im.size
        thumb = im.copy()
        thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        thumb.save(thumb_day / f"{fid}.webp", "WEBP", quality=THUMB_Q, method=6)

    return w, h, ext, full_bytes


def prune_unused(keep: set[Path]) -> int:
    """删除 images/ 下不在本次产物集合里的文件（布局迁移时清理旧产物）。"""
    removed = 0
    for p in IMG_DIR.rglob("*"):
        if p.is_file() and p not in keep:
            p.unlink()
            removed += 1
    # 清掉空目录
    for d in sorted([d for d in IMG_DIR.rglob("*") if d.is_dir()], reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="GeoSciPlot 图片预处理")
    ap.add_argument("--force", action="store_true", help="重新生成全部产物")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    ap.add_argument("--export-csv", action="store_true", help="导出 meta/titles.csv 供编辑")
    args = ap.parse_args()

    for d in (THUMB_DIR, FULL_DIR, META_DIR):
        d.mkdir(parents=True, exist_ok=True)

    existing = load_existing()
    titles = load_titles()
    if titles:
        print(f"· 读入 {TITLES_CSV.relative_to(ROOT)}：{len(titles)} 条人工字段")
    sources = collect_sources()
    print(f"扫描 raw/：{len(sources)} 个候选文件，已有索引 {len(existing)} 条\n")

    items: list[dict] = []
    seen_ids: set[str] = set()
    keep_paths: set[Path] = set()
    n_new = n_skip = n_dup = 0
    bytes_orig = bytes_full = bytes_thumb = 0
    today = date.today().isoformat()

    for src in sources:
        fid = file_id(src)
        if fid in seen_ids:
            n_dup += 1
            print(f"  内容重复，跳过：{src.name} (id={fid})")
            continue
        seen_ids.add(fid)

        old = existing.get(fid, {})
        manual = titles.get(fid, {})
        day = old.get("added") or today          # 日期目录：首次处理那天，保持稳定
        thumb_path = THUMB_DIR / day / f"{fid}.webp"

        exts = {p.suffix.lower().lstrip(".") for p in (FULL_DIR / day).glob(f"{fid}.*")}
        has_full = bool(exts)
        ext = old.get("ext") or (next(iter(exts)) if exts else src.suffix.lower().lstrip("."))
        full_path = FULL_DIR / day / f"{fid}.{ext}"

        if not args.force and thumb_path.exists() and has_full:
            w, h = old.get("width"), old.get("height")
            if not w or not h:
                with Image.open(src) as im:
                    w, h = im.size
            full_bytes = full_path.stat().st_size
            n_skip += 1
            flag = "跳过"
        else:
            if args.dry_run:
                with Image.open(src) as im:
                    w, h = im.size
                full_bytes = src.stat().st_size
            else:
                w, h, ext, full_bytes = make_assets(src, fid, day)
            n_new += 1
            flag = "处理"

        keep_paths.add(thumb_path)
        keep_paths.add(FULL_DIR / day / f"{fid}.{ext}")

        item = {
            "id": fid,
            "journal": manual.get("journal") or old.get("journal", ""),
            "published": manual.get("published") or old.get("published", ""),
            "tags": manual.get("tags") or old.get("tags", []),
            "desc": manual.get("desc") or old.get("desc", ""),
            # 迁移期兼容字段：保留历史值，前端已不再使用
            "title": manual.get("title") or old.get("title", ""),
            "category": manual.get("category") or old.get("category", ""),
            "width": w,
            "height": h,
            "ext": ext,
            "thumb": f"thumb/{day}/{fid}.webp",
            "full": f"full/{day}/{fid}.{ext}",
            "bytes": full_bytes,
            "origName": src.name,
            "added": day,
        }
        items.append(item)

        tsize = thumb_path.stat().st_size if thumb_path.exists() else 0
        bytes_orig += src.stat().st_size
        bytes_full += full_bytes
        bytes_thumb += tsize
        print(f"  {flag}  {fid}  {w}x{h}  {day}  原图 {full_bytes/1024:7.1f}KB + "
              f"缩略图 {tsize/1024:5.1f}KB  {src.name}")

    # raw/ 里已无原图、但产物还在的条目：保留（不删历史）
    for fid, old in existing.items():
        if fid not in seen_ids:
            day = old.get("added") or today
            t = THUMB_DIR / day / f"{fid}.webp"
            if t.exists():
                items.append(old)
                keep_paths.add(t)
                keep_paths.add(FULL_DIR / day / f"{fid}.{old.get('ext', 'png')}")
                print(f"  保留（raw/ 中已无原图）  {fid}  {day}")

    items.sort(key=lambda x: (x.get("added", ""), x["id"]), reverse=True)

    payload = {
        "generated": today,
        "count": len(items),
        "thumbMax": THUMB_MAX,
        "items": items,
    }

    if args.dry_run:
        print("\n[dry-run] 未写入任何文件")
    else:
        REFS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n写入 {REFS_JSON.relative_to(ROOT)}")
        removed = prune_unused(keep_paths)
        if removed:
            print(f"清理旧产物 {removed} 个（不在本次产物集合内）")
        if args.export_csv:
            export_titles(items)

    days = len({i.get("added") for i in items})
    print(f"\n新增 {n_new} · 跳过 {n_skip} · 内容重复 {n_dup} · 索引共 {len(items)} 条（{days} 个日期目录）")
    print(f"原图 {bytes_orig/1048576:.2f}MB → full/ {bytes_full/1048576:.2f}MB（不压缩）+ "
          f"thumb/ {bytes_thumb/1048576:.2f}MB = {(bytes_full+bytes_thumb)/1048576:.2f}MB")
    repo_bytes = sum(f.stat().st_size for f in IMG_DIR.rglob("*") if f.is_file())
    print(f"images/ 合计 {repo_bytes/1048576:.2f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
