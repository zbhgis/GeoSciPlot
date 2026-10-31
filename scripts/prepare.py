#!/usr/bin/env python3
"""GeoSciPlot 图片预处理：把 raw/ 里杂乱的原图规范化为「缩略图 + 原图副本 + 索引」。

用法：
    python scripts/prepare.py            # 增量处理（已处理过的跳过）
    python scripts/prepare.py --force    # 全部重新生成
    python scripts/prepare.py --dry-run  # 只报告，不写文件
    python scripts/prepare.py --export-csv   # 导出 meta/titles.csv 供 Excel 编辑

输入：raw/**               任意文件名、任意尺寸、png/jpg/jpeg/webp/bmp/tiff（扁平投放，不看子目录）

输出：images/thumb/{日期}/{id}.webp   列表缩略图（长边 ≤480，质量 78）
      images/disp/{日期}/{id}.webp   详情页展示档（长边 ≤1600，质量 82；
                                     原图 ≤1600px 且 <512KB 时不生成，详情页直用原图）
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
import time
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from colors import extract_colors, to_rgb  # noqa: E402  主色提取 + 共享模式转换（I;16 拉伸）
from site_common import SCOPE_SET, SCOPE_TBD, STYLE_TBD  # noqa: E402  标签双轨白名单


def safe_colors(path: Path) -> list:
    """颜色提取失败的图（CMYK/半损坏等 Pillow 处理不了的）绝不阻塞入库，
    colors 只是增强数据，缺了详情页不显示配色行而已。"""
    try:
        return extract_colors(path)
    except Exception as e:
        print(f"  ! 主色提取失败（跳过颜色）：{path.name} — {e}")
        return []


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
IMG_DIR = ROOT / "images"
THUMB_DIR = IMG_DIR / "thumb"
DISP_DIR = IMG_DIR / "disp"
FULL_DIR = IMG_DIR / "full"
META_DIR = ROOT / "meta"
REFS_JSON = META_DIR / "refs.json"
TITLES_CSV = META_DIR / "titles.csv"

THUMB_MAX = 480         # 缩略图长边上限
THUMB_Q = 78            # 缩略图 WebP 质量
DISP_MAX = 1600         # 展示档长边上限（详情页正文宽度 677px，2.5x 屏留足余量）
DISP_Q = 82             # 展示档 WebP 质量
# 只有「大图」才需要展示档：长边 >1600 或文件 >512KB（1400px 的 8MB 线稿 PNG
# 同样命中）。小图直用原图，避免无谓的重编码与再入库
DISP_EDGE = 1600
DISP_BYTES = 512 * 1024

# ── 标签双轨（2026-10-24 重构）：范围/样式两类并行，每张图两类各至少一个 ──
# 白名单与待定文案见 site_common.py（pages.py 共用同一份）
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

# 人工可编辑字段（CSV 列 → refs.json 字段）
MANUAL_FIELDS = ["doi"]
MANUAL_LIST_FIELDS = ["scope", "style"]


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
        if not (isinstance(data, dict) and isinstance(data.get("items"), list)):
            raise ValueError("形状不符（缺 items 数组）")
        if any(not isinstance(x, dict) for x in data["items"]):
            raise ValueError("items 含非对象元素")
    except (json.JSONDecodeError, ValueError) as e:
        # 与 admin.load_refs 同一道防线：损坏时备份现场并抛错，绝不静默按空库继续
        # ——空库 + raw/ 只剩最近一批时，prune_unused 会把历史图库整批物理删除
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = REFS_JSON.parent / (REFS_JSON.name + f".corrupt-{stamp}")
        backup.write_bytes(REFS_JSON.read_bytes())
        raise RuntimeError(
            f"refs.json 损坏（{e}），已备份为 {backup.name}"
            "——修复或恢复该文件后重试，拒绝以空库清空图库"
        ) from e
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
            for k in MANUAL_FIELDS:
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
    """导出人工编辑表（utf-8-sig：Excel 打开中文不乱码）。
    列序与 admin.py 的 CSV_FIELDS 一致：id, scope, style, doi。"""
    TITLES_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["id"] + MANUAL_LIST_FIELDS + MANUAL_FIELDS
    with TITLES_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for it in items:
            w.writerow([it.get("id", ""),
                        "|".join(it.get("scope") or []), "|".join(it.get("style") or []),
                        it.get("doi", "")])
    print(f"导出编辑表 → {TITLES_CSV.relative_to(ROOT)}（Excel 编辑后重跑本脚本即回填）")


def collect_sources() -> list[Path]:
    """扫描 raw/：扁平投放，子目录名不再承担分类含义。"""
    # 新电脑首次运行：raw/ 不在仓库里（gitignore），自动创建而不是报错退出
    RAW_DIR.mkdir(parents=True, exist_ok=True)
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
    """生成缩略图（压缩）+ 原图副本（不压缩）到 images/{thumb,full}/{日期}/。
    展示档不在这里做 —— 由 ensure_disp 统一处理（新图与历史回填同一入口）。"""
    ext = src.suffix.lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"

    thumb_day = THUMB_DIR / day
    full_day = FULL_DIR / day
    thumb_day.mkdir(parents=True, exist_ok=True)
    full_day.mkdir(parents=True, exist_ok=True)

    full_path = full_day / f"{fid}.{ext}"

    # 先解码生成缩略图、后复制原图：坏文件在 copyfile 之前就崩，不会留下
    # 「full/ 已落盘、索引却没有」的孤儿副本（敌意语料实测的崩溃批次遗留）
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im = to_rgb(im)          # 透明铺白底；I;16/I 灰度按动态范围拉伸（直接转 RGB 会全白/噪声）
        w, h = im.size
        thumb = im.copy()
        thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        thumb.save(thumb_day / f"{fid}.webp", "WEBP", quality=THUMB_Q, method=6)

    shutil.copyfile(src, full_path)          # 原图：逐字节复制
    full_bytes = full_path.stat().st_size

    return w, h, ext, full_bytes


def needs_disp(w: int, h: int, full_bytes: int) -> bool:
    """是否需要展示档：大尺寸或大文件的原图才值得再压一档，
    小图直接用原图，避免重编码造成的质量损失与多余产物。"""
    return max(int(w or 0), int(h or 0)) > DISP_EDGE or int(full_bytes or 0) > DISP_BYTES


def ensure_disp(item: dict, full_path: Path, keep: set, dry_run: bool = False) -> int:
    """详情页展示档的统一入口：新图入库与历史回填（--force 或规则变化后重跑）都走这里。
    需要而生成的写 item["disp"]；不需要或生成失败的一律移除该键（详情页回退原图）。
    返回 disp 文件字节数（未生成/跳过 = 0）。"""
    day = item.get("added") or ""
    fid = item.get("id") or ""
    if not (needs_disp(item.get("width"), item.get("height"), item.get("bytes")) and day and fid
            and full_path.is_file()):
        item.pop("disp", None)
        return 0
    disp_path = DISP_DIR / day / f"{fid}.webp"
    if disp_path.exists():
        item["disp"] = f"disp/{day}/{fid}.webp"
        keep.add(disp_path)
        return disp_path.stat().st_size
    if dry_run:
        item["disp"] = f"disp/{day}/{fid}.webp"   # 只报告路径，不落盘
        return 0
    try:
        with Image.open(full_path) as im:
            im = ImageOps.exif_transpose(im)
            im = to_rgb(im)      # 与 make_assets 同一转换口径
            disp = im.copy()
            disp.thumbnail((DISP_MAX, DISP_MAX), Image.LANCZOS)
            disp_path.parent.mkdir(parents=True, exist_ok=True)
            disp.save(disp_path, "WEBP", quality=DISP_Q, method=6)
    except Exception as e:
        print(f"  ! 展示档生成失败（详情页回退原图）：{fid} — {e}")
        item.pop("disp", None)
        return 0
    item["disp"] = f"disp/{day}/{fid}.webp"
    keep.add(disp_path)
    return disp_path.stat().st_size


def prune_unused(keep: set[Path]) -> int:
    """删除 images/ 下不在本次产物集合里的文件。

    双保险：调用方已保证 raw/ 非空才会到这里；即便如此，
    keep 为空（什么都没生成）时绝不删除——防止误清空图库。

    注意：只删文件，**绝不删目录**。曾经在这里用 rmdir 清理空日期目录，
    在个别 Windows 磁盘上出现「非空目录被连树删除」的诡异行为，
    导致整个图库产物被清空——空的日期目录无害（git 也不跟踪），留着即可。
    """
    if not keep:
        return 0
    removed = 0
    # 先物化完整文件列表再删除，避免「边遍历边删」在任何文件系统上的未知行为
    for p in list(IMG_DIR.rglob("*")):
        try:
            if p.is_file() and p not in keep:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="GeoSciPlot 图片预处理")
    ap.add_argument("--force", action="store_true", help="重新生成全部产物")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    ap.add_argument("--export-csv", action="store_true", help="导出 meta/titles.csv 供编辑")
    ap.add_argument("--backfill-disp", action="store_true",
                    help="只补详情页展示档（raw/ 为空的存量库专用）：不重跑缩略图、"
                         "不清理任何文件，refs.json 仅新增 disp 字段")
    ap.add_argument("--migrate-tags", action="store_true",
                    help="一次性迁移（2026-10-24 双轨标签）：把 items[].tags 按范围"
                         "白名单拆成 scope/style 两字段，缺类补「范围待定/样式待定」，"
                         "并重写 titles.csv 为 id,doi,scope,style 四列")
    args = ap.parse_args()

    # ── 一次性迁移：放在所有 guard 之前，raw/ 为空也能跑 ──
    if args.migrate_tags:
        existing = load_existing()
        if not existing:
            print("! refs.json 为空或不存在，无需迁移")
            return 0
        already = all("scope" in it and "style" in it and "tags" not in it
                      for it in existing.values())
        if already:
            print("· 已是双轨格式，无需迁移")
            return 0
        n_sc = n_st = 0
        for it in existing.values():
            tags = it.pop("tags", None) or []      # 旧单轨字段一律移除
            if "scope" not in it or "style" not in it:
                scope = [t for t in tags if t in SCOPE_SET]
                style = [t for t in tags if t not in SCOPE_SET]
                if not scope:
                    scope, n_sc = [SCOPE_TBD], n_sc + 1
                if not style:
                    style, n_st = [STYLE_TBD], n_st + 1
                it["scope"], it["style"] = scope, style
        items_sorted = sorted(existing.values(),
                              key=lambda x: (x.get("added", ""), x["id"]), reverse=True)
        payload = {"generated": date.today().isoformat(), "count": len(items_sorted),
                   "thumbMax": THUMB_MAX, "items": items_sorted}
        tmp = REFS_JSON.parent / (REFS_JSON.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        tmp.replace(REFS_JSON)
        export_titles(items_sorted)
        print(f"· 迁移完成：{len(items_sorted)} 条 → scope/style 双轨"
              f"（补「{SCOPE_TBD}」{n_sc} 张 · 补「{STYLE_TBD}」{n_st} 张），"
              f"titles.csv 已重写为 id,doi,scope,style")
        return 0

    for d in (THUMB_DIR, DISP_DIR, FULL_DIR, META_DIR):
        d.mkdir(parents=True, exist_ok=True)

    existing = load_existing()
    titles = load_titles()
    if titles:
        print(f"· 读入 {TITLES_CSV.relative_to(ROOT)}：{len(titles)} 条人工字段")
    sources = collect_sources()

    # ── 防误删保险 ──
    # raw/ 为空但索引里有数据 = 投放目录被清空/移动过。
    # 此时继续跑会触发 prune_unused 把 images/ 里的全部产物删光（历史事故）。
    if not sources and existing:
        if args.backfill_disp:
            # 存量库补展示档的专用通道：只对索引里每条记录生成缺失的 disp，
            # 不重跑缩略图/颜色、不清理文件；refs.json 只会新增 disp 键
            keep: set[Path] = set()
            n_new = n_have = 0
            for it in existing.values():
                day = it.get("added") or ""
                fp = FULL_DIR / day / f"{it['id']}.{it.get('ext', 'png')}"
                before = bool(it.get("disp"))
                ensure_disp(it, fp, keep, args.dry_run)
                if it.get("disp"):
                    n_have += 1
                    if not before:
                        n_new += 1
            print(f"· 展示档回填：新生成 {n_new} 张，共 {n_have}/{len(existing)} 张需要展示档")
            dpath = IMG_DIR / "disp"
            if dpath.is_dir():
                tot = sum(1 for _ in dpath.rglob("*.webp"))
                sz = sum(f.stat().st_size for f in dpath.rglob("*.webp"))
                print(f"· images/disp/ 合计 {tot} 张 / {sz/1048576:.1f}MB")
            if not args.dry_run:
                items_sorted = sorted(existing.values(),
                                       key=lambda x: (x.get("added", ""), x["id"]), reverse=True)
                payload = {"generated": date.today().isoformat(), "count": len(items_sorted),
                           "thumbMax": THUMB_MAX, "items": items_sorted}
                tmp = REFS_JSON.parent / (REFS_JSON.name + ".tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
                tmp.replace(REFS_JSON)
                print(f"写入 {REFS_JSON.relative_to(ROOT)}（仅新增 disp 字段）")
            return 0
        print(f"! raw/ 为空，但索引里有 {len(existing)} 条数据 —— 跳过处理（防止误清空图库）。")
        print("  如果确实要清空图库：手动删除 images/、meta/refs.json、meta/titles.csv。")
        return 0

    print(f"扫描 raw/：{len(sources)} 个候选文件，已有索引 {len(existing)} 条\n")

    items: list[dict] = []
    seen_ids: set[str] = set()
    keep_paths: set[Path] = set()
    n_new = n_skip = n_dup = 0
    poison: list[str] = []
    bytes_orig = bytes_full = bytes_thumb = bytes_disp = 0
    today = date.today().isoformat()

    for src in sources:
        fid = file_id(src)
        if fid in seen_ids:
            n_dup += 1
            print(f"  内容重复，跳过：{src.name} (id={fid})")
            continue
        seen_ids.add(fid)

        try:
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
                # 已入库的图沿用旧颜色；历史条目缺失时补算一次（下次继续跳过）
                colors = old.get("colors") or (safe_colors(full_path) if full_path.is_file() else [])
            else:
                if args.dry_run:
                    with Image.open(src) as im:
                        w, h = im.size
                    full_bytes = src.stat().st_size
                    colors = []
                else:
                    w, h, ext, full_bytes = make_assets(src, fid, day)
                    colors = safe_colors(src)
                n_new += 1
                flag = "处理"

            keep_paths.add(thumb_path)
            keep_paths.add(FULL_DIR / day / f"{fid}.{ext}")

            item = {
                "id": fid,
                "doi": manual.get("doi") or old.get("doi", ""),
                # 双轨标签：两类各至少一个（CSV > 旧值 > 待定兜底；新入库未分类的图
                # 落「待定」，可在管理界面按待定筛出来补齐）
                "scope": manual.get("scope") or old.get("scope") or [SCOPE_TBD],
                "style": manual.get("style") or old.get("style") or [STYLE_TBD],
                "width": w,
                "height": h,
                "ext": ext,
                "thumb": f"thumb/{day}/{fid}.webp",
                "full": f"full/{day}/{fid}.{ext}",
                "bytes": full_bytes,
                "origName": src.name,
                "added": day,
            }
            if colors:
                item["colors"] = colors
            # 展示档：增量跳过的老图若缺 disp 会在这里补生成（规则变化/首次升级的回填）
            bytes_disp += ensure_disp(item, full_path, keep_paths, args.dry_run)
            items.append(item)

            tsize = thumb_path.stat().st_size if thumb_path.exists() else 0
            bytes_orig += src.stat().st_size
            bytes_full += full_bytes
            bytes_thumb += tsize
            print(f"  {flag}  {fid}  {w}x{h}  {day}  原图 {full_bytes/1024:7.1f}KB + "
                  f"缩略图 {tsize/1024:5.1f}KB  {src.name}")
        except Exception as e:
            # 单文件隔离（敌意语料实测：一个截断/0 字节/伪装扩展名的文件会让整批
            # 入库崩溃，且毒文件留在 raw/ 把之后每次暂存/推送流水线永久堵死）——
            # 跳过并记录，其余文件照常入库
            poison.append(f"{src.name}: {e}")
            print(f"  跳过（解析失败）  {src.name}  {e}")

    if poison:
        print(f"\n! raw/ 中有 {len(poison)} 个无法解析的文件被跳过（原文件保留，可手工删除后重跑）：")
        for p_ in poison:
            print("  - " + p_)

    # raw/ 里已无原图、但产物还在的条目：保留（不删历史）；展示档同样补齐
    for fid, old in existing.items():
        if fid not in seen_ids:
            day = old.get("added") or today
            t = THUMB_DIR / day / f"{fid}.webp"
            if t.exists():
                bytes_disp += ensure_disp(
                    old, FULL_DIR / day / f"{fid}.{old.get('ext', 'png')}", keep_paths, args.dry_run)
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
        # 原子写（tmp + replace），与 admin.save_refs 同一口径：写一半崩溃不留
        # 半截 JSON——半截 JSON 会在下次运行被 load_existing 静默按空库处理，
        # raw/ 已清空的图会被 prune_unused 连产品带条目整批抹掉
        tmp = REFS_JSON.parent / (REFS_JSON.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(REFS_JSON)
        print(f"\n写入 {REFS_JSON.relative_to(ROOT)}")
        removed = prune_unused(keep_paths)
        if removed:
            print(f"清理旧产物 {removed} 个（不在本次产物集合内）")
        if args.export_csv:
            export_titles(items)

    days = len({i.get("added") for i in items})
    print(f"\n新增 {n_new} · 跳过 {n_skip} · 内容重复 {n_dup} · 索引共 {len(items)} 条（{days} 个日期目录）")
    print(f"原图 {bytes_orig/1048576:.2f}MB → full/ {bytes_full/1048576:.2f}MB（不压缩）+ "
          f"thumb/ {bytes_thumb/1048576:.2f}MB + disp/ {bytes_disp/1048576:.2f}MB")
    n_disp = sum(1 for i in items if i.get("disp"))
    print(f"展示档：{n_disp}/{len(items)} 张（其余原图 ≤1600px 且 <512KB，详情页直用原图）")
    repo_bytes = sum(f.stat().st_size for f in IMG_DIR.rglob("*") if f.is_file())
    print(f"images/ 合计 {repo_bytes/1048576:.2f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
