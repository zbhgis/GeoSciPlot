#!/usr/bin/env python3
"""制图经验文章图片入库：远端图床 → 本站三档图 + 映射表。

背景：制图经验（content/guide/*.md）的图片原本直链公众号图床
（cdn.jsdelivr.net/gh/zbhgis/BlogImg*），既没有缩略图/展示档，也不走图库那套
「逐源降级」链路。本脚本把它们收进本站图片流水线：

输入：content/guide/*.md 里的 ![…](URL)（**只读，绝不改写 md**）
输出：images/guide/thumb/{id}.webp   列表用小图（长边 ≤480，q78）
      images/guide/disp/{id}.webp    正文展示档（长边 ≤1600，q82）
      images/guide/full/{id}.{ext}   原图逐字节副本（灯箱放大用）
      meta/guide_images.json         原 URL → 三档相对路径 + 宽高

与图库同一套口径：id = 文件内容 sha1 前 10 位（内容去重，改名/重传不产生新条目），
日期目录这里不用——制图经验的图不属于「某天上传的图库条目」，扁平存放更直观。

用法：
    python scripts/guide_images.py            # 增量（已有产物跳过）
    python scripts/guide_images.py --force    # 全部重下重生成
    python scripts/guide_images.py --dry-run  # 只报告，不写文件
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from colors import to_rgb  # noqa: E402  与图库同一套模式转换（I;16 拉伸 / 透明铺白）

ROOT = Path(__file__).resolve().parent.parent
GUIDE_DIR = ROOT / "content" / "guide"
CACHE_DIR = ROOT / ".cache" / "guide-images"

IMAGES = ROOT / "images"
IMG_ROOT = IMAGES / "guide"
THUMB_DIR = IMG_ROOT / "thumb"
DISP_DIR = IMG_ROOT / "disp"
FULL_DIR = IMG_ROOT / "full"
META_DIR = ROOT / "meta"
GUIDE_JSON = META_DIR / "guide_images.json"
REFS_JSON = META_DIR / "refs.json"

THUMB_MAX = 480
THUMB_Q = 78
DISP_MAX = 1600          # 与图库同口径：正文 760px 栏宽 × 2x 屏留足余量
DISP_Q = 82

MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
# 只接管 jsDelivr 的 gh 直链：其他形态（本站相对路径等）原样放行
GH_RE = re.compile(r"^https://cdn\.jsdelivr\.net/gh/([^/]+)/([^@/]+)@([^/]+)/(.+)$")
UA = "GeoSciPlot/1.0 (+https://geosciplot.zbhgis.com)"


def file_id(data: bytes) -> str:
    """与 prepare.py 同口径：内容 sha1 前 10 位。"""
    return hashlib.sha1(data).hexdigest()[:10]


def collect_urls(scan_paths: list[Path]) -> dict[str, list[str]]:
    """URL → 出现在哪些文章里（同一张图可被多篇复用，入库只做一份）。
    scan_paths 可以是目录（递归）或单个 md 文件——其他站点的内容目录（如
    mystation 的博客/笔记）也能接同一套三档流水线。"""
    files: list[Path] = []
    for p in scan_paths:
        if p.is_dir():
            files += sorted(p.rglob("*.md"))
        elif p.is_file() and p.suffix.lower() == ".md":
            files.append(p)
    out: dict[str, list[str]] = {}
    for md in files:
        text = md.read_text(encoding="utf-8", errors="ignore")
        for url in MD_IMG_RE.findall(text):
            out.setdefault(url, []).append(md.stem)
    return out


def cache_path(url: str) -> Path:
    """缓存名 = URL 的 sha1 + 原扩展名（扩展名参与 Pillow 解码，不能丢）。"""
    ext = (Path(urlparse(url).path).suffix or ".png").lower()
    return CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest()[:16] + ext)


def raw_url(url: str) -> str | None:
    """jsDelivr gh 直链 → GitHub raw 等价地址。

    BlogImg2 整包已超 jsDelivr 的 50MB 上限（data.jsdelivr.com 直接返回
    status 403 "Package size exceeded ..."）：已缓存的图还能命中，没缓存的新图
    一律 403，只有 raw 取得到。所以下载必须带 raw 兜底。"""
    m = GH_RE.match(url)
    if not m:
        return None
    owner, repo, branch, path = m.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"


def fetch(url: str, force: bool = False) -> bytes:
    """下载原图（带磁盘缓存）：重跑/换机器都不必再下一次 100MB。"""
    cp = cache_path(url)
    if cp.is_file() and not force:
        return cp.read_bytes()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    last_err = ""
    candidates = [url] + ([raw_url(url)] if raw_url(url) else [])
    for attempt in range(3):
        for cand in candidates:
            try:
                req = Request(cand, headers={"User-Agent": UA})
                with urlopen(req, timeout=60) as r:
                    data = r.read()
                if not data:
                    raise OSError("空响应")
                cp.write_bytes(data)
                return data
            except Exception as e:          # 网络抖动/403 换下一个候选
                last_err = f"{cand} → {e}"
        if attempt < 2:
            time.sleep(1 + attempt * 2)
    raise OSError(f"下载失败（{last_err}）")


def build_tiers(data: bytes, ext: str, fid: str) -> tuple[int, int, dict]:
    """写三档并返回 (宽, 高, 各档字节数)。先解码后落盘——坏图不会留下半套产物。"""
    with Image.open(io.BytesIO(data)) as im:
        im = to_rgb(ImageOps.exif_transpose(im))
        w, h = im.size
        thumb = im.copy()
        thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        disp = im.copy()
        disp.thumbnail((DISP_MAX, DISP_MAX), Image.LANCZOS)
        for d in (THUMB_DIR, DISP_DIR, FULL_DIR):
            d.mkdir(parents=True, exist_ok=True)
        thumb_path = THUMB_DIR / f"{fid}.webp"
        disp_path = DISP_DIR / f"{fid}.webp"
        full_path = FULL_DIR / f"{fid}.{ext}"
        thumb.save(thumb_path, "WEBP", quality=THUMB_Q, method=6)
        disp.save(disp_path, "WEBP", quality=DISP_Q, method=6)
        full_path.write_bytes(data)      # 原图：逐字节，不重编码
    return w, h, {"thumb": thumb_path.stat().st_size,
                  "disp": disp_path.stat().st_size,
                  "full": full_path.stat().st_size}


def load_mapping() -> dict[str, dict]:
    if not GUIDE_JSON.is_file():
        return {}
    try:
        data = json.loads(GUIDE_JSON.read_text(encoding="utf-8"))
        items = data.get("items")
        if isinstance(items, dict):
            return items
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def load_gallery_items() -> dict[str, dict]:
    """图库条目（id → item）。文章配图有相当一部分就是图库里收录的那张图
    （文章里「收录于 /<id>」正是同一条目）：内容 sha1 相同 → id 相同，
    直接复用它的三档产物，不再存一份重复原图（实测约 35% 命中、省近 80MB）。"""
    if not REFS_JSON.is_file():
        return {}
    try:
        data = json.loads(REFS_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {it["id"]: it for it in data.get("items", []) if it.get("id")}


def main() -> int:
    ap = argparse.ArgumentParser(description="制图经验文章图片入库")
    ap.add_argument("--force", action="store_true", help="忽略已有产物，全部重下重生成")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    ap.add_argument("--scan", action="append", metavar="DIR",
                    help="额外的 md 目录（可重复）；缺省只扫 content/guide")
    ap.add_argument("--md", action="append", metavar="FILE",
                    help="指定的 md 文件（可重复），比 --scan 更精确")
    ap.add_argument("--scope", default="guide",
                    help="本批条目归属标记（默认 guide）；只清理同 scope 的失效映射，"
                         "不同站点互不误删")
    args = ap.parse_args()

    scan_paths = [Path(p) for p in (args.scan or [])] + [Path(p) for p in (args.md or [])]
    if not scan_paths:
        scan_paths = [GUIDE_DIR]
    for p in scan_paths:
        if not p.exists():
            print(f"! 路径不存在：{p}")
            return 2
    urls = collect_urls(scan_paths)
    if not urls:
        print(f"! {len(scan_paths)} 个路径下没有图片引用")
        return 0
    mapping = load_mapping()
    gallery = load_gallery_items()
    print(f"扫描 {len(scan_paths)} 个路径：{len(urls)} 个图片 URL（映射表现有 {len(mapping)} 条，"
          f"图库可复用条目 {len(gallery)} 条，scope={args.scope}）")

    todo = [(u, arts) for u, arts in urls.items() if GH_RE.match(u)]
    skipped = [u for u in urls if not GH_RE.match(u)]
    for u in skipped:
        print(f"  - 非 jsDelivr gh 直链，保持原样：{u}")

    n_new = n_skip = n_fail = n_reuse = 0
    bytes_full = bytes_disp = bytes_thumb = 0
    fails: list[str] = []
    for url, arts in todo:
        rec = mapping.get(url)
        # 已有记录：不重复下载。先看这张图是否其实已收录进图库（早期版本按独立
        # 副本写过，这里就地改指向并清掉重复产物），再看三档是否齐全
        if rec and rec.get("id") and not args.force:
            hit = gallery.get(rec["id"])
            if hit:
                for p in (list(THUMB_DIR.glob(f"{rec['id']}.webp"))
                          + list(DISP_DIR.glob(f"{rec['id']}.webp"))
                          + list(FULL_DIR.glob(f"{rec['id']}.*"))):
                    p.unlink(missing_ok=True)
                disp_rel = hit.get("disp") or hit["full"]
                if (rec["thumb"], rec["disp"], rec["full"]) != (hit["thumb"], disp_rel, hit["full"]):
                    rec.update({"thumb": hit["thumb"], "disp": disp_rel, "full": hit["full"],
                                "width": hit.get("width"), "height": hit.get("height"),
                                "bytes": hit.get("bytes") or 0, "reuse": "gallery"})
                    n_reuse += 1
                    print(f"  改复用图库 {rec['id']}（清掉重复副本）")
                else:
                    n_skip += 1
                continue
            if all((IMAGES / rec[k]).is_file() for k in ("thumb", "disp", "full")):
                n_skip += 1
                bytes_full += rec.get("bytes") or 0
                bytes_disp += (IMAGES / rec["disp"]).stat().st_size
                bytes_thumb += (IMAGES / rec["thumb"]).stat().st_size
                continue
        if args.dry_run:
            print(f"  [dry-run] 待入库 {url}")
            n_new += 1
            continue
        try:
            data = fetch(url, force=args.force)
            fid = file_id(data)
            hit = gallery.get(fid)
            if hit:
                # 与图库条目同图（内容 sha1 相同）：直接指向它的三档，不再存副本
                for p in list(THUMB_DIR.glob(f"{fid}.webp")) + list(DISP_DIR.glob(f"{fid}.webp")) \
                        + list(FULL_DIR.glob(f"{fid}.*")):
                    p.unlink(missing_ok=True)      # 清掉先前按独立副本写下的重复产物
                disp_rel = hit.get("disp") or hit["full"]
                mapping[url] = {
                    "id": fid, "width": hit.get("width"), "height": hit.get("height"),
                    "thumb": hit["thumb"], "disp": disp_rel, "full": hit["full"],
                    "bytes": hit.get("bytes") or 0, "articles": arts, "scope": args.scope,
                    "reuse": "gallery",
                }
                n_reuse += 1
                print(f"  复用图库 {fid}  {hit.get('width')}x{hit.get('height')}  {url.rsplit('/', 1)[-1]}")
                continue
            ext = (Path(urlparse(url).path).suffix or ".png").lower().lstrip(".")
            ext = "jpg" if ext == "jpeg" else ext
            w, h, sizes = build_tiers(data, ext, fid)
            mapping[url] = {
                "id": fid,
                "width": w,
                "height": h,
                "thumb": f"guide/thumb/{fid}.webp",
                "disp": f"guide/disp/{fid}.webp",
                "full": f"guide/full/{fid}.{ext}",
                "bytes": sizes["full"],
                "articles": arts,
                "scope": args.scope,
            }
            n_new += 1
            bytes_full += sizes["full"]
            bytes_disp += sizes["disp"]
            bytes_thumb += sizes["thumb"]
            print(f"  入库 {fid}  {w}x{h}  原图 {sizes['full']/1024:7.1f}KB → "
                  f"展示档 {sizes['disp']/1024:6.1f}KB · 缩略图 {sizes['thumb']/1024:5.1f}KB")
        except Exception as e:
            n_fail += 1
            fails.append(f"{url} — {e}")
            print(f"  ! 失败 {url} — {e}")

    if args.dry_run:
        print("\n[dry-run] 未写入任何文件")
        return 0

    # 只清理本批 scope 的失效条目：不同站点（guide / blog / note）共用一张表，
    # 互相不能误删
    stale = [u for u in mapping
             if u not in urls and mapping[u].get("scope", "guide") == args.scope]
    for u in stale:
        mapping.pop(u, None)
    if stale:
        print(f"· 清理映射表中已不被引用的 {len(stale)} 条（产物文件保留，可手动删）")

    META_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": time.strftime("%Y-%m-%d"),
        "count": len(mapping),
        "items": mapping,
    }
    tmp = GUIDE_JSON.parent / (GUIDE_JSON.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(GUIDE_JSON)
    print(f"\n写入 {GUIDE_JSON.relative_to(ROOT)}（{len(mapping)} 条）")
    print(f"新增 {n_new} · 复用图库 {n_reuse} · 跳过 {n_skip} · 失败 {n_fail}")
    print(f"guide 三档（仅新建部分）：full {bytes_full/1048576:.1f}MB + "
          f"disp {bytes_disp/1048576:.1f}MB + thumb {bytes_thumb/1048576:.1f}MB")
    if n_reuse:
        print(f"复用图库的 {n_reuse} 张不占额外空间（与图库条目共用同一份原图/展示档）")
    if fails:
        print("\n以下图片未入库（页面上仍用原始远端地址）：")
        for f in fails:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
