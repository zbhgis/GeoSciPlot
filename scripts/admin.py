#!/usr/bin/env python3
"""GeoSciPlot 本地管理界面 —— 只有本机能访问（服务只绑定 127.0.0.1）。

用法：
    python scripts/admin.py                 # 自动打开 http://127.0.0.1:5199
    python scripts/admin.py --port 5200     # 换端口
    python scripts/admin.py --no-open       # 不自动打开浏览器

功能：
    1. 拖拽 / 点击选择 / Ctrl+V 粘贴上传图片 → 存入 raw/，按内容算出 id，并给出缩略图预览
       （粘贴支持混合内容：自动只提取其中的图片；text/html 里的远程 <img> 由本机服务代取）
    2. 逐张填写 期刊 / 论文发表 / 标签 / 说明
    3. 图片管理：增删查改。元数据「保存」= **暂存到本地**（titles.csv + refs.json，
       毫秒级，不构建不推送）——可以连续改很多条再统一推送；
       「一键推送全部」= 把所有已暂存/已保存的变更一次性：prepare 增量入库
       → 构建站点 → git 提交推送 →（可选）同步服务器
    4. raw 暂存区：查看 raw/ 里全部文件（含已发布图的副本，可筛选/单个删除），一键清空 raw/
    5. 制图经验文章（content/guide/*.md，mystation admin-server 同款交互）：列表搜索 /
       行内改元数据（frontmatter，日期联动文件名前缀）/ 正文浮层编辑器（.bak 自动备份 +
       mtime 乐观锁）/ 新建（frontmatter 自动生成）/ 删除进本机回收站（content/.trash/guide/）
       与恢复；改动只落本地文件，随「一键推送全部」流水线统一发布
    6. 点「保存并推送」→ 自动执行：写 meta/titles.csv → prepare.py → build_site.py
       → git add / commit / push →（可选）同步到服务器

为什么不需要登录：服务只监听 127.0.0.1，物理上只有本机能连；推送用你本机已配置的
git 凭据（SSH key 或凭据管理器），**不需要在服务器上存任何 token**。
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError

from PIL import Image, ImageOps  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_md import plain_text  # noqa: E402  字数统计与构建同源（含导流模板剥离）
from site_common import SCOPE_TAGS  # noqa: E402  标签双轨的范围白名单（prepare/构建同一份）
from colors import to_rgb  # noqa: E402  预览缩略图与入库管线同一模式转换（I;16/F 全同值等）

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
IMG_DIR = ROOT / "images"
META_DIR = ROOT / "meta"
TITLES_CSV = META_DIR / "titles.csv"
REFS_JSON = META_DIR / "refs.json"
SITE = ROOT / "site"                     # build_site.py 的产物目录（「同步服务器」用）
UI_HTML = Path(__file__).resolve().parent / "admin_ui.html"

PYTHON = sys.executable
DEFAULT_REMOTE = "git@github.com:zbhgis/GeoSciPlot.git"
MAX_BODY = 200 * 1024 * 1024          # 单次请求体上限
MAX_FETCH = 30 * 1024 * 1024          # 单张远程图片的下载上限
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
# 标签双轨（2026-10-24，与 site_common/prepare 同一套）：范围/样式两类并行，
# 每张图两类各至少一个；缺类在 do_stage / do_save 兜底成「待定」
CSV_FIELDS = ["id", "scope", "style", "doi"]
MANUAL_TEXT = ("doi",)
MANUAL_LIST = ("scope", "style")
SCOPE_TBD = "范围待定"
STYLE_TBD = "样式待定"
IMG_TYPES = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg",
             ".jpeg": "image/jpeg", ".gif": "image/gif"}


# ────────────────────────── 工具 ──────────────────────────

def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=timeout)
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, f"命令超时：{' '.join(cmd)}"
    except FileNotFoundError as e:
        return 127, f"命令不存在：{e}"


def safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base).strip() or "image"
    return base[:120]


def content_id(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:10]


def load_refs() -> dict:
    """refs.json 是全站元数据的唯一真源：损坏时备份现场并抛错，绝不静默归零
    ——静默返回空库后，下一次「更新元数据」就把空库写回，全部图片的
    标签/DOI/收录时间整批丢失。主站 loadConfig 的同款教训。"""
    if REFS_JSON.exists():
        try:
            data = json.loads(REFS_JSON.read_text(encoding="utf-8"))
            if not (isinstance(data, dict) and isinstance(data.get("items"), list)):
                raise ValueError("形状不符（缺 items 数组）")
            if any(not isinstance(x, dict) for x in data["items"]):
                raise ValueError("items 含非对象元素")
        except (json.JSONDecodeError, ValueError) as e:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = REFS_JSON.parent / (REFS_JSON.name + f".corrupt-{stamp}")
            backup.write_bytes(REFS_JSON.read_bytes())
            raise RuntimeError(
                f"refs.json 损坏（{e}），已备份为 {backup.name}"
                "——修复或恢复该文件后重试，拒绝以空库覆盖"
            ) from e
        return data
    return {"items": []}


def save_refs(refs: dict) -> None:
    # 原子写（tmp + replace）：写一半崩溃不留半截 JSON——半截 JSON 会触发上面的
    # 损坏防护抛错，管理台与发布全部停摆
    tmp = REFS_JSON.parent / (REFS_JSON.name + ".tmp")
    tmp.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(REFS_JSON)


def read_titles() -> tuple[list[str], dict[str, dict]]:
    if not TITLES_CSV.exists():
        return list(CSV_FIELDS), {}
    with TITLES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        fields = rd.fieldnames or list(CSV_FIELDS)
        rows: dict[str, dict] = {}
        for r in rd:
            fid = (r.get("id") or "").strip()
            if fid:
                rows[fid] = {k: (r.get(k) or "") for k in fields}
    return fields, rows


def write_titles(fields: list[str], rows: dict[str, dict]) -> None:
    TITLES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with TITLES_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows.values():
            w.writerow({k: r.get(k, "") for k in fields})


def preview_b64(path: Path, box: int = 360) -> str:
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im = to_rgb(im)   # 16-bit/float 灰度等与入库管线同一口径，预览不再白图/噪声
            im.thumbnail((box, box), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=72, method=4)
            return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def doi_key(s: str) -> str:
    """DOI 归一化，用于查重的键。

    必须归一化，否则查重会静默失效：库里历史数据存的是**完整 URL 形式**
    （`https://doi.org/10.1038/xxx`，见 meta/titles.csv），而用户手输的多半是
    **裸 DOI**（`10.1038/xxx`）——粘贴来源还可能给出无协议的 `doi.org/10.x`。
    另外 DOI 本身大小写不敏感。
    前端 `doiKey()` 用的是同一套规则，两边必须保持一致。
    """
    k = str(s or "").strip().lower()
    k = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", k)
    k = re.sub(r"^doi:\s*", "", k)
    return k


def repo_state() -> dict:
    refs = load_refs()
    items = refs.get("items", [])
    # exists() 而非 is_dir()：git worktree 检出时 .git 是文件，is_dir 会误判成「非仓库」
    is_repo = (ROOT / ".git").exists()
    remote = ""
    branch = "main"
    dirty = 0
    unpushed = 0        # 非 git 仓库不进入下面的 if 块——必须先初始化，否则 return 处 NameError
    if is_repo:
        code, out = run(["git", "remote", "get-url", "origin"])
        remote = out if code == 0 else ""
        code, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        branch = out if code == 0 else "main"
        code, out = run(["git", "status", "--porcelain"])
        dirty = len([l for l in out.splitlines() if l.strip()]) if code == 0 else 0
        # 本地领先远端的提交数：暂存模型的「有东西没推」指示灯。
        # origin/<branch> 是本地引用（上次 fetch/push 时更新），这里不做网络请求，够用
        code, out = run(["git", "rev-list", "--count", f"origin/{branch}..HEAD"])
        unpushed = int(out.strip()) if code == 0 and out.strip().isdigit() else 0

    # 归一化后的 DOI → 已入库图片 id 的倒排索引，供「添加图片」页做同 DOI 提示
    dois: dict[str, list[str]] = {}
    for i in items:
        k = doi_key(i.get("doi"))
        fid = i.get("id")
        if k and fid:
            dois.setdefault(k, []).append(fid)

    return {
        "isRepo": is_repo,
        "remote": remote,
        "branch": branch,
        "dirty": dirty,
        "unpushed": unpushed,
        "count": len(items),
        "scope": sorted({t for i in items for t in (i.get("scope") or [])}),
        "style": sorted({t for i in items for t in (i.get("style") or [])}),
        # 范围白名单：管理界面给旧格式 raw 标签做归属切分用（site_common 同一份）
        "scopeTags": SCOPE_TAGS,
        "dois": dois,
        "defaultRemote": DEFAULT_REMOTE,
    }


# ────────────────────────── 后台任务系统 ──────────────────────────
# 发布/删除/更新/推送都是「生成站点 + git push + scp 服务器」的长操作，
# 以前在 HTTP 请求里同步执行，git push 一卡界面就停滞几分钟。
# 现在：POST 立即返回任务号，后台线程跑流水线，前端轮询 /api/job/<id> 看实时进度。

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

# 流水线互斥：构建/提交/推送/删除这类「会动 site/、git、refs.json」的任务
# 同一时间只允许一个——否则暂存写一半、流水线读一半，产物就是撕裂状态。
# 暂存类操作（/api/save）也会先看这把锁，忙时直接拒绝而不是排队。
PIPELINE_LOCK = threading.Lock()
PIPELINE_KINDS = {"publish", "update", "delete", "stage", "deploy",
                  "sync-server", "init", "push"}


def step(log: list[dict], name: str, cmd: list[str] | None, timeout: int = 300) -> tuple[bool, str]:
    """带「运行中」标记的步骤：先写入 ok=None 条目（前端显示 …），命令结束后回填结果。"""
    log.append({"step": name, "out": "", "ok": None})
    if cmd is None:
        return True, ""
    code, out = run(cmd, timeout)
    entry = log[-1]
    entry["ok"] = code == 0
    entry["out"] = out
    return entry["ok"], out


def start_job(kind: str, body: dict) -> str:
    """启动后台任务，立即返回任务号。流水线类任务互斥：忙时直接返回「秒败」任务。"""
    jid = uuid.uuid4().hex[:8]
    if kind in PIPELINE_KINDS and not PIPELINE_LOCK.acquire(blocking=False):
        with JOBS_LOCK:
            JOBS[jid] = {"kind": kind, "done": True, "ok": False,
                         "hint": "已有发布/推送任务在运行——等下方日志显示结束后再操作",
                         "log": [{"step": "忙碌", "ok": False,
                                  "out": "同一时间只允许一条发布/推送流水线"}]}
        return jid
    # 共享日志：job["log"] 与 do_* 里 step() 写的是同一个列表对象——
    # 此前日志只在 worker 收尾时一次性塞回，前端轮询在整个构建+推送期间
    # 拿到的恒为空列表，「实时进度」从未真正生效（子代理复盘发现）
    shared_log: list[dict] = []
    job = {"kind": kind, "log": shared_log, "done": False, "ok": None, "hint": ""}
    with JOBS_LOCK:
        JOBS[jid] = job
        done_ids = [k for k, v in JOBS.items() if v["done"]]
        for k in done_ids[:-20]:          # 只保留最近 20 个已完成的任务
            JOBS.pop(k, None)

    def worker():
        try:
            if kind == "publish":
                res = do_publish(body.get("items") or [], body.get("message") or "",
                                 bool(body.get("push", True)), bool(body.get("sync", True)),
                                 log=shared_log)
            elif kind == "stage":
                res = do_stage(body.get("items") or [], log=shared_log)
            elif kind == "deploy":
                res = do_deploy(body.get("message") or "",
                                bool(body.get("push", True)), bool(body.get("sync", True)),
                                log=shared_log)
            elif kind == "delete":
                res = do_delete_and_finish((body.get("id") or "").strip(), body.get("message") or "",
                                           bool(body.get("push", True)), bool(body.get("sync", True)),
                                           log=shared_log)
            elif kind == "sync-server":
                res = do_sync_server(log=shared_log)
            elif kind == "init":
                res = do_init(body.get("remote") or "", log=shared_log)
            elif kind == "push":
                res = do_push(log=shared_log)
            else:
                res = {"ok": False, "log": [{"step": kind, "ok": False, "out": "未知任务类型"}]}
        except Exception as e:            # 后台线程绝不能静默死掉
            # 异常条目追加进共享日志而不是整表替换：前面步骤的实时记录要保留
            shared_log.append({"step": "后台任务异常", "ok": False, "out": repr(e)})
            res = {"ok": False, "hint": "", "log": shared_log}
        finally:
            if kind in PIPELINE_KINDS:
                PIPELINE_LOCK.release()
        with JOBS_LOCK:
            job["log"] = res.get("log", job["log"])
            job["done"] = True
            job["ok"] = bool(res.get("ok"))
            job["hint"] = res.get("hint", "")

    try:
        threading.Thread(target=worker, daemon=True, name=f"job-{kind}-{jid}").start()
    except Exception as e:
        # 线程启动失败时 worker 不会运行、finally 里的锁释放不会发生——
        # 不在这里补放 PIPELINE_LOCK 的话，所有流水线任务从此永远「忙碌」直到重启
        if kind in PIPELINE_KINDS:
            PIPELINE_LOCK.release()
        with JOBS_LOCK:
            job.update(done=True, ok=False, hint="后台线程启动失败，请重试",
                       log=[{"step": "启动后台任务", "ok": False, "out": repr(e)}])
    return jid


def job_snapshot(jid: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(jid)
        if not job:
            return {"done": True, "ok": False, "log": [], "hint": "任务不存在（服务重启过？刷新页面重试）"}
        return {"done": job["done"], "ok": job["ok"], "hint": job["hint"],
                "log": [dict(x) for x in job["log"]]}


# ────────────────────────── 元数据读写 ──────────────────────────

def apply_to_csv(updates: dict[str, dict]) -> int:
    fields, rows = read_titles()
    for f in CSV_FIELDS:
        if f not in fields:
            fields.append(f)
    n = 0
    for fid, upd in updates.items():
        row = rows.get(fid, {k: "" for k in fields})
        for k in MANUAL_TEXT + MANUAL_LIST:
            if k in upd:
                row[k] = "|".join(upd[k]) if isinstance(upd[k], list) else str(upd[k])
        row["id"] = fid
        rows[fid] = row
        n += 1
    write_titles(fields, rows)
    return n


def apply_to_refs(updates: dict[str, dict]) -> int:
    refs = load_refs()
    items = refs.get("items", [])
    n = 0
    for it in items:
        upd = updates.get(it.get("id"))
        if not upd:
            continue
        for k in MANUAL_TEXT + MANUAL_LIST:
            if k in upd:
                it[k] = upd[k]
        n += 1
    save_refs(refs)
    return n


# ────────────────────────── 动作 ──────────────────────────

def _prune_empty_dirs() -> None:
    """删掉 raw/ 下的空目录（不动 raw/ 本身）。按深度倒序，才能一次清完嵌套的空目录。"""
    if not RAW_DIR.exists():
        return
    dirs = sorted((p for p in RAW_DIR.rglob("*") if p.is_dir()),
                  key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


def do_raw_list() -> dict:
    """列出 raw/ 收件箱里的全部图片（「查看 raw」页与页面刷新后恢复「待发布」列表共用）。

    注意：这里**不过滤**已发布图的副本（duplicate=true 的也返回），
    否则 raw/ 的真实占用就看不全了 —— 「添加图片」页自己会滤掉 duplicate 的。
    """
    known = {i["id"] for i in load_refs().get("items", [])}
    out: list[dict] = []
    if RAW_DIR.exists():
        for f in sorted(RAW_DIR.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in SUPPORTED:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            fid = content_id(f)
            rec = {"name": f.name,
                   "rel": str(f.relative_to(RAW_DIR)).replace("\\", "/"),
                   "savedAs": f.name, "id": fid, "bytes": st.st_size,
                   "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                   "duplicate": fid in known, "preview": preview_b64(f)}
            try:
                with Image.open(f) as im:
                    rec["width"], rec["height"] = im.size
            except Exception:
                pass
            out.append(rec)
    return {"files": out}


def do_raw_delete(name: str) -> dict:
    """删除 raw/ 里的单个源文件（「待发布」表单点「移除」、raw 列表点「删除」都走这里）。
    传相对路径（rel）或文件名都行 —— raw/ 目前是平的，但保留子目录能力。"""
    rel = (name or "").replace("\\", "/").strip().lstrip("/")
    if not rel:
        return {"ok": False, "error": "缺少文件名"}
    target = (RAW_DIR / rel).resolve()
    try:
        target.relative_to(RAW_DIR.resolve())        # 防目录穿越（旧实现用 safe_name 截成 basename，
    except ValueError:                               # 子目录里的文件反而删不掉）
        return {"ok": False, "error": "非法路径"}
    if not target.is_file():
        return {"ok": False, "error": "文件不存在"}
    ok, err = unlink_retry(target)
    if not ok:
        return {"ok": False, "error": f"删除失败：{err}"}
    _prune_empty_dirs()
    return {"ok": True}


def do_raw_clear() -> dict:
    """清空 raw/ 收件箱。

    只删「能识别的图片」（与列表口径一致），raw/ 里的其它文件一律保留并在结果里报出。
    安全性：raw/ 只是收件箱 —— 已发布图片的**逐字节原图另存于 images/full/**
    （见 .gitignore 注释），所以清空不会损坏图库；
    但**尚未发布**的图会随清空一起丢失，前端确认框必须把这一点说清楚。
    """
    if not RAW_DIR.exists():
        return {"ok": True, "removed": 0, "freed": 0, "pending": 0,
                "duplicate": 0, "failed": 0, "others": 0,
                "log": [{"step": "清空 raw", "ok": True, "out": "raw/ 不存在，无需清理"}]}

    known = {i["id"] for i in load_refs().get("items", [])}
    removed = freed = failed = pending = dup = 0
    res_errors: list[str] = []
    for f in sorted(RAW_DIR.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in SUPPORTED:
            continue
        try:
            if content_id(f) in known:
                dup += 1
            else:
                pending += 1
            freed += f.stat().st_size
        except Exception:
            failed += 1
            continue
        ok, err = unlink_retry(f)
        if ok:
            removed += 1
        else:
            failed += 1
            res_errors.append(f"{f.name}: {err}")
    others = sum(1 for p in RAW_DIR.rglob("*")
                 if p.is_file() and p.suffix.lower() not in SUPPORTED)
    _prune_empty_dirs()

    msg = f"已删除 {removed} 个图片文件，释放 {freed / 1048576:.1f} MB"
    if pending:
        msg += f"（其中 {pending} 个尚未发布）"
    if failed:
        msg += f"；{failed} 个删除失败：{'；'.join(res_errors[:3])}"
    if others:
        msg += f"；raw/ 里还有 {others} 个非图片文件，未动"
    return {"ok": failed == 0, "removed": removed, "freed": freed,
            "pending": pending, "duplicate": dup, "failed": failed,
            "others": others, "errors": res_errors,
            "log": [{"step": "清空 raw", "ok": failed == 0, "out": msg}]}


def do_upload(files: list[dict]) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    known = {i["id"] for i in load_refs().get("items", [])}
    out = []
    for f in files:
        name = safe_name(f.get("name") or "image")
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED:
            out.append({"name": name, "error": f"不支持的格式 {ext or '(无扩展名)'}"})
            continue
        try:
            data = base64.b64decode(f.get("b64") or "", validate=False)
        except Exception as e:
            out.append({"name": name, "error": f"base64 解码失败：{e}"})
            continue
        if not data:
            out.append({"name": name, "error": "空文件"})
            continue

        target = RAW_DIR / name
        if target.exists():
            stem, i = target.stem, 1
            while target.exists():
                target = RAW_DIR / f"{stem}_{i}{ext}"
                i += 1
        target.write_bytes(data)

        fid = content_id(target)
        dup = fid in known
        rec = {"name": name, "savedAs": target.name, "id": fid,
               "bytes": len(data), "duplicate": dup, "preview": ""}
        try:
            with Image.open(target) as im:
                rec["width"], rec["height"] = im.size
            rec["preview"] = preview_b64(target)
        except Exception as e:
            rec["error"] = f"无法解析为图片：{e}"
            # 坏文件不留仓：解析失败说明根本不是可用图片
            try:
                target.unlink()
            except OSError:
                pass
        if dup and target.exists():
            # 内容与图库中已有图完全一致：不留副本，直接清掉刚存进来的这份，
            # 免得 raw/ 里堆积永远用不上的重复文件
            try:
                target.unlink()
                rec["cleaned"] = True
            except OSError:
                pass
        out.append(rec)
    return {"files": out}


def do_update(updates: list[dict]) -> dict:
    """批量更新元数据：写 titles.csv + 回填 refs.json（不重新生成站点）。"""
    upd_map: dict[str, dict] = {}
    skipped: list[str] = []
    known = {it.get("id") for it in load_refs().get("items", [])}
    for u in updates:
        fid = (u.get("id") or "").strip()
        if not fid:
            continue
        if fid not in known:
            # 杂散 id 入 CSV 会被构建门禁 2d 判收敛失败，堵死之后的每次发布——
            # 这里直接拒绝而不是照写（UI 不会发，防 curl/脚本误敲）
            skipped.append(fid)
            continue
        # 先记录调用方显式提供的字段：ensure_tbd 会给缺标签的 u 补「待定」，
        # 那是为「表单整包保存、用户清空标签」设计的兜底；若部分字段的 API 调用
        # （如只改 doi）也吃进补出来的待定值，就会把没动过的真实标签整组覆盖掉
        provided = [k for k in list(MANUAL_TEXT) + list(MANUAL_LIST) if k in u]
        ensure_tbd(u)
        # None 与「显式空串/空数组」语义不同：null 不是用户输入（UI 不会发），
        # 过滤掉，否则 str(None) 会把字面 "None" 写进 titles.csv 并回流成坏链
        upd_map[fid] = {k: u[k] for k in provided if k in u and u[k] is not None}
    if not upd_map:
        msg = "没有可更新的字段"
        if skipped:
            msg += f"（{len(skipped)} 个 id 不在图库中：{' '.join(skipped[:5])}）"
        return {"ok": False, "log": [{"step": "更新元数据", "ok": False, "out": msg}]}

    n_csv = apply_to_csv(upd_map)
    n_refs = apply_to_refs(upd_map)
    return {"ok": True,
            "log": [{"step": "更新元数据", "ok": True,
                     "out": f"titles.csv 与 refs.json 各回填 {n_csv}/{n_refs} 条"}]}


def do_delete(fid: str, log: list[dict] | None = None) -> dict:
    if log is None:
        log = []
    refs = load_refs()
    items = refs.get("items", [])
    it = next((x for x in items if x.get("id") == fid), None)
    if not it:
        return {"ok": False, "log": [{"step": "删除", "ok": False, "out": f"id 不存在：{fid}"}]}

    removed: list[str] = []
    failed: list[str] = []
    for key in ("thumb", "full", "disp"):   # disp 一并删：孤立展示档要等下次 prepare 才被清，期间还进 git
        p = IMG_DIR / str(it.get(key, ""))
        # is_file() 而非 exists()：字段缺失时路径落在 images/ 目录本身，
        # exists() 为真、unlink() 对目录抛 PermissionError——此时图片已删、
        # save_refs 未执行，状态撕裂且每次重试都卡在同一处
        if p.is_file():
            # unlink_retry：Windows 上杀软/索引服务的短时句柄占用很常见，
            # 与 do_raw_delete/do_raw_clear 同一口径，不再让单个文件锁毁掉整个删除任务
            ok, err = unlink_retry(p)
            if ok:
                removed.append(str(p.relative_to(ROOT)))
            else:
                failed.append(f"{p.name}：{err}")
    raw_file = RAW_DIR / str(it.get("origName", ""))
    if raw_file.is_file():
        ok, err = unlink_retry(raw_file)
        if ok:
            removed.append(str(raw_file.relative_to(ROOT)))
        else:
            failed.append(f"{raw_file.name}：{err}")

    refs["items"] = [x for x in items if x.get("id") != fid]
    refs["count"] = len(refs["items"])
    save_refs(refs)

    fields, rows = read_titles()
    rows.pop(fid, None)
    write_titles(fields, rows)

    for d in (IMG_DIR / "thumb", IMG_DIR / "full", IMG_DIR / "disp"):
        if d.exists():
            for sub in d.iterdir():
                if sub.is_dir() and not any(sub.iterdir()):
                    sub.rmdir()

    out = "已移除 " + "、".join(removed) if removed else "已从索引移除"
    if failed:
        out += ("；以下文件删除失败（文件被占用，raw/ 非空的下次入库时会由 prepare "
                "重试清理，或手动删除）：" + "；".join(failed))
    log.append({"step": f"删除 {fid}", "ok": True, "out": out})
    return {"ok": True, "item": it, "log": log}


def do_sync_server(log: list[dict] | None = None) -> dict:
    """把 site/ 同步到服务器：SSH 建 staging → scp 上传 → 原子换台（失败回滚）→ IndexNow。
    传入 start_job 的共享 log 时每阶段完成即写入，前端轮询能看到实时进度。"""
    if log is None:
        log = []
    cfg = {}
    cfg_path = ROOT / "gallery.config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    srv = cfg.get("server") or {}
    host = srv.get("host")
    webroot = srv.get("webroot", "/var/www/geosciplot")
    # IndexNow 推送的目标站点 URL：配置优先，缺省用正式域名；
    # 此前引用了从未赋值的 SITE_URL 全局名，同步最后一步必 NameError（站点本体
    # 已换台成功、任务却被标失败）—— 这里就地解析并容错跳过
    site_url = (cfg.get("site_url") or "").rstrip("/") or "https://geosciplot.zbhgis.com"
    if not host:
        log.append({"step": "同步服务器", "ok": False,
                    "out": "未配置 server.host —— 在 gallery.config.json 里加 "
                           "\"server\": {\"host\": \"root@47.98.133.104\", \"webroot\": \"/var/www/geosciplot\"}"})
        return {"ok": False, "log": log}

    ssh_base = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", host]
    # 原子换台式同步：先整体传到 staging 目录，成功后再毫秒级 rename 就位。
    # 旧流程「清空 webroot → 逐文件 scp」有分钟级发布空窗——期间访问 /
    # 是 403（目录在但 index.html 未传到），访问详情页会拿到引用缺失资源的
    # 半套页面。staging 失败时旧站点原样保留，发布失败不再破坏线上。
    stage = webroot + ".staging"
    code, out = run(ssh_base + [f"rm -rf {stage} && mkdir -p {stage}"],
                    timeout=60)
    ssh_msg = "" if code == 0 else ("SSH 连接失败（需先把本机公钥加入服务器 authorized_keys，"
                                    "命令见 README「服务器部署」一节）\n" + out)
    log.append({"step": "SSH 建暂存目录", "ok": code == 0, "out": ssh_msg})
    if code != 0:
        return {"ok": False, "log": log}

    code, out = run(["scp", "-r", "-o", "BatchMode=yes", str(SITE) + "/.", f"{host}:{stage}/"], timeout=600)
    log.append({"step": f"scp 上传 site/ → {host}:{stage}/", "ok": code == 0,
                "out": "scp 失败（线上保持旧版本）\n" + out if code != 0 else ""})
    if code != 0:
        run(ssh_base + [f"rm -rf {stage}"], timeout=60)  # 清掉残局，线上保持旧版本
        return {"ok": False, "log": log}
    # 原子换台（防嵌套语义）：先清掉上次失败可能遗留的 webroot.old（换台成功本来
    # 就要删它；不清理则本次 mv webroot 会嵌进旧备份，回滚恢复出坏布局）；
    # webroot 存在则必须先挪走（挪不走 = 挂载点/权限问题，直接放弃——继续 mv stage
    # 会把 staging 嵌进现网目录并伪成功）；换台失败按回滚结果分型报错
    swap_cmd = (
        f"rm -rf {webroot}.old; "
        f"if [ -d {webroot} ]; then mv {webroot} {webroot}.old || {{ echo MOVE_FAIL; exit 1; }}; fi; "
        f"if mv {stage} {webroot}; then rm -rf {webroot}.old; echo SWAP_OK; "
        f"else if [ -d {webroot}.old ]; then if mv {webroot}.old {webroot}; then echo ROLLBACK_OK; "
        f"else echo ROLLBACK_FAIL; fi; else echo NO_OLD; fi; exit 1; fi"
    )
    code, out = run(ssh_base + [swap_cmd], timeout=120)
    if code != 0:
        if "ROLLBACK_FAIL" in out:
            swap_msg = "换台失败且自动回滚未成功——旧版本仍在 " + webroot + ".old，需手工恢复"
        elif "NO_OLD" in out:
            swap_msg = "换台失败（首次部署，服务器上无旧版本可回滚）——staging 保留在服务器，可直接重试"
        elif "MOVE_FAIL" in out:
            swap_msg = "旧站点目录无法挪动（挂载点/权限？），本次部署未生效，线上保持原样"
        else:
            swap_msg = "换台失败（旧版本已回滚就位）"
        log.append({"step": "原子换台", "ok": False, "out": swap_msg + "\n" + out})
    else:
        log.append({"step": "原子换台", "ok": True, "out": f"site/ → {host}:{webroot}"})
    if code != 0:
        return {"ok": False, "log": log}
    # 部署后搜索引擎推送：服务器端 ping-search.sh 按 sitemap 增量对比推 IndexNow
    # （脚本与主站共用同一份，按传入 URL 分账状态；失败只记日志不影响发布）
    ping, ping_out = run(ssh_base + [f"bash /opt/mystation/deploy/ping-search.sh {site_url}"], timeout=120)
    log.append({"step": "搜索引擎推送（IndexNow）", "ok": ping == 0, "out": ping_out.strip() or "完成"})
    return {"ok": True, "log": log}


def pipeline_after_content(log: list[dict], message: str, push: bool, sync: bool) -> dict:
    """内容变更后的公共收尾：生成站点 → git 提交推送 →（可选）同步服务器。
    所有步骤用 step() 执行，前端能看到每一步的实时状态。"""
    ok, out = step(log, "生成静态站 (build_site.py)", [PYTHON, "scripts/build_site.py"])
    if not ok:
        return {"ok": False, "log": log, "hint": "build_site.py 失败，未提交"}

    if not (ROOT / ".git").exists():   # exists()：worktree 下 .git 是文件（口径同 repo_state）
        log.append({"step": "Git", "ok": False,
                    "out": "尚未初始化 git 仓库 —— 点上方「初始化仓库」后再发布"})
        return {"ok": False, "log": log, "hint": "请先初始化 git 仓库"}

    if not message.strip():
        message = "update: 图库内容变更"

    step(log, "git add", ["git", "add", "-A"])
    ok, out = step(log, f"git commit -m \"{message}\"", ["git", "commit", "-m", message])
    if not (ok or "nothing to commit" in out):
        return {"ok": False, "log": log, "hint": "提交失败（检查 git user.name / user.email）"}

    if push:
        # 国内网络 push 到 GitHub 可能很慢，后台任务模式下超时放宽到 5 分钟
        ok, out = step(log, "git push（推送到 GitHub）", ["git", "push"], timeout=300)
        if not ok:
            return {"ok": False, "log": log, "hint": "推送失败：检查 origin 与 SSH key（也可能是网络波动，稍后手动 git push）"}

    if sync:
        # 各阶段条目由 do_sync_server 直接写进共享 log（scp 上传较久，实时可见）
        res = do_sync_server(log=log)
        if not res["ok"]:
            return {"ok": True, "log": log,
                    "hint": "GitHub 已同步；服务器同步失败（见日志）——通常是本机公钥还没加到服务器的 authorized_keys，"
                            "也可以手动在 Git Bash 里 cd site && scp -r ./* root@47.98.133.104:/var/www/geosciplot/"}

    return {"ok": True, "log": log}


def ensure_tbd(it: dict) -> None:
    """双轨兜底：两类各至少一个标签，缺的补「待定」（前端已兜底，这里是后端保险，
    防止手改 CSV / 直接调 API 漏字段）。原地修改。"""
    if not [t for t in (it.get("scope") or []) if str(t).strip()]:
        it["scope"] = [SCOPE_TBD]
    if not [t for t in (it.get("style") or []) if str(t).strip()]:
        it["style"] = [STYLE_TBD]


def apply_items_to_csv(items: list[dict]) -> int:
    """把「待发布表单」的元数据写进 titles.csv（保留未提及字段的旧值）。"""
    fields, rows = read_titles()
    for f in CSV_FIELDS:
        if f not in fields:
            fields.append(f)
    written = 0
    for it in items:
        fid = (it.get("id") or "").strip()
        if not fid:
            continue
        ensure_tbd(it)
        row = rows.get(fid, {k: "" for k in fields})
        for k in ("doi",):
            v = (it.get(k) or "").strip()
            if v:
                row[k] = v
        for k in MANUAL_LIST:
            v = it.get(k)
            if isinstance(v, list):
                v = "|".join(t.strip() for t in v if str(t).strip())
            if v:
                row[k] = str(v)
        row["id"] = fid
        rows[fid] = row
        written += 1
    write_titles(fields, rows)
    return written


def do_stage(items: list[dict], log: list[dict] | None = None) -> dict:
    """暂存到本地（不推送）：写 titles.csv + prepare.py 增量入库（缩略图 + refs.json）。

    之后不构建站点、不碰 git——攒够一批后点「一键推送全部」统一发布。
    prepare.py 本身是增量的：raw/ 里没有新图时直接跳过（防误删保险），秒级返回。"""
    if log is None:
        log = []
    written = apply_items_to_csv(items)
    log.append({"step": "写入标题表", "ok": True, "out": f"meta/titles.csv 更新 {written} 条"})
    ok, out = step(log, "生成图片与索引 (prepare.py)", [PYTHON, "scripts/prepare.py"])
    if not ok:
        return {"ok": False, "log": log, "hint": "prepare.py 失败，未暂存"}
    log.append({"step": "暂存完成", "ok": True,
                "out": f"{written} 张图已入库本地索引（未构建站点、未推送）——改完后点「一键推送全部」统一发布"})
    return {"ok": True, "log": log}


def do_deploy(message: str, push: bool = True, sync: bool = True,
              log: list[dict] | None = None) -> dict:
    """一键推送所有已保存的变更：prepare 增量入库 → 构建站点 → git 提交推送 →（可选）同步服务器。

    「所有已保存的」= 此前用「暂存」写进 titles.csv / refs.json 的元数据改动、
    raw/ 里还没入库的图（prepare 增量收录），以及一切未提交的本地文件——
    流水线对内容不可知，git add -A 全收。"""
    if log is None:
        log = []
    ok, out = step(log, "增量入库 (prepare.py)", [PYTHON, "scripts/prepare.py"])
    if not ok:
        return {"ok": False, "log": log, "hint": "prepare.py 失败，未继续后面的步骤"}
    return pipeline_after_content(log, message or "update: 图库内容变更", push, sync)


def do_publish(items: list[dict], message: str, push: bool = True, sync: bool = True,
               log: list[dict] | None = None) -> dict:
    """保存并推送 = 暂存（写表 + 入库）+ 完整流水线。"""
    if log is None:
        log = []
    written = apply_items_to_csv(items)
    log.append({"step": "写入标题表", "ok": True, "out": f"meta/titles.csv 更新 {written} 条"})

    ok, out = step(log, "生成图片与索引 (prepare.py)", [PYTHON, "scripts/prepare.py"])
    if not ok:
        return {"ok": False, "log": log, "hint": "prepare.py 失败，未继续后面的步骤"}

    return pipeline_after_content(log, message or f"add: {written} 张图", push, sync)


def do_push(log: list[dict] | None = None) -> dict:
    if log is None:
        log = []
    ok, out = step(log, "git push（推送到 GitHub）", ["git", "push"], timeout=300)
    if not ok:
        return {"ok": False, "log": log, "hint": "推送失败：检查 origin 与 SSH key（也可能是网络波动，稍后重试）"}
    return {"ok": True, "log": log}


def do_init(remote: str, log: list[dict] | None = None) -> dict:
    if log is None:
        log = []
    if not remote.strip():
        remote = DEFAULT_REMOTE

    ok, _ = step(log, "git init", ["git", "init"])
    if not ok:
        return {"ok": False, "log": log, "hint": "git init 失败"}

    ok, out = step(log, f"git remote add origin {remote}", ["git", "remote", "add", "origin", remote])
    if not ok:
        ok, out = step(log, "remote 已存在，改为 set-url", ["git", "remote", "set-url", "origin", remote])
        if not ok:
            return {"ok": False, "log": log, "hint": "设置 origin 失败"}

    step(log, "git add -A", ["git", "add", "-A"])
    code, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = out if code == 0 and out else "main"
    ok, out = step(log, f"git commit（首提）", ["git", "commit", "-m", "init: 初始提交"])
    if not (ok or "nothing to commit" in out):
        return {"ok": False, "log": log, "hint": "首次提交失败（检查 git user.name / user.email）"}

    ok, out = step(log, f"git push -u origin {branch}", ["git", "push", "-u", "origin", branch], timeout=300)
    if not ok:
        return {"ok": False, "log": log, "hint": "首次推送失败：检查远端仓库与 SSH key"}
    return {"ok": True, "log": log}


def do_delete_and_finish(fid: str, message: str, push: bool, sync: bool,
                         log: list[dict] | None = None) -> dict:
    res = do_delete(fid, log=log)
    if not res.get("ok"):
        return res
    log = res.get("log", log if log is not None else [])
    return pipeline_after_content(log, message or f"delete: 图 {fid}", push, sync)


def unlink_retry(path: Path, tries: int = 5, delay: float = 0.3) -> tuple[bool, str]:
    """带短退避的删除。Windows 上刚写入的文件常被杀软/索引服务短暂占用，
    立即 unlink 会偶发 PermissionError —— 粘贴后几秒内点「清空 raw」最容易踩中。
    实测教训：不做重试时 2 张里稳挂 1 张（恰是最新写入的那张）。"""
    for i in range(tries):
        try:
            path.unlink()
            return True, ""
        except FileNotFoundError:
            return True, ""                      # 已经没了 = 目的达成
        except OSError:
            if i < tries - 1:
                time.sleep(delay * (i + 1))      # 0.3 / 0.6 / 0.9 / 1.2s
        except Exception as e:                   # 沙箱等非系统拦截：不重试
            return False, repr(e)
    last = ""
    try:
        last = f"{path.stat().st_size}B"
    except OSError:
        pass
    return False, f"文件仍被占用（{last}）"


def do_fetch_image(query: dict) -> tuple[int, bytes, str]:
    """代取 <img> 的远程图片地址，供「粘贴提取图片」用。

    为什么必须由服务端代取：管理页跑在 http://127.0.0.1:5199 上，
    对任意外站图片做跨源 fetch 会被 CORS 拦住读不到响应体；
    改用 <img> + 画布又会因「画布被污染」拒绝 toDataURL。
    只有本机服务端发请求才绕得开 —— 而本服务只监听 127.0.0.1，无暴露面。
    返回 (http 状态码, 响应体, Content-Type)。
    """
    url = str((query.get("url") or [""])[0]).strip()
    if not re.match(r"^https?://", url, re.I):
        return 400, "只支持 http/https 图片地址".encode("utf-8"), "text/plain; charset=utf-8"

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GeoSciPlotAdmin/1.1",
        "Accept": "image/*,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = r.read(MAX_FETCH + 1)
    except HTTPError as e:
        return 502, f"远端返回 HTTP {e.code}".encode("utf-8"), "text/plain; charset=utf-8"
    except (URLError, TimeoutError, OSError) as e:
        return 502, f"下载失败：{e}".encode("utf-8"), "text/plain; charset=utf-8"

    if len(data) > MAX_FETCH:
        return 413, "图片超过 30MB 上限".encode("utf-8"), "text/plain; charset=utf-8"
    if not data:
        return 502, "远端返回空内容".encode("utf-8"), "text/plain; charset=utf-8"
    # 部分图床给 application/octet-stream，先放行，真正的校验交给上传时的 PIL 解析
    if ctype and not (ctype.startswith("image/") or ctype == "application/octet-stream"):
        return 415, f"返回的不是图片（Content-Type: {ctype}）".encode("utf-8"), "text/plain; charset=utf-8"
    return 200, data, (ctype or "image/png")


# ────────────────────────── 制图经验文章管理 ──────────────────────────
# content/guide/*.md 的本地增删改查，交互照搬 mystation 的 admin-server：
# 列表（默认只读）· 行内改元数据（frontmatter）· 正文浮层编辑器（frontmatter
# 分离保留）· 新建（frontmatter 自动生成）· 删除进本机回收站 + 恢复。
# 所有改动都只是本地文件写（毫秒级）；构建与推送走既有「一键推送全部」流水线，
# 单次编辑不触发 git —— 与图库的「暂存 → 一键推送」同一节奏。

GUIDE_DIR = ROOT / "content" / "guide"
ARTICLE_TRASH = ROOT / "content" / ".trash" / "guide"   # 本机回收站（gitignore，不进仓库）
FM_OPEN_RE = re.compile(r"\A[\s\uFEFF]*---[ \t]*\r?\n")
ARTICLE_MAX = 2 * 1024 * 1024          # 单篇读写上限（与 mystation admin-server 一致）


def article_safe_name(name: str) -> str:
    """文件名清洗：只留 basename、去路径成分与非法字符，缺 .md 补上。"""
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name).strip()
    if not name:
        return ""
    if not name.lower().endswith(".md"):
        name += ".md"
    return name


def _under_dir(path: Path, d: Path) -> bool:
    """路径必须落在目录内（防目录穿越；d 需为已解析的绝对路径）。"""
    try:
        path.resolve().relative_to(d.resolve())
        return True
    except ValueError:
        return False


def split_front_matter(text: str) -> tuple[str, str, str]:
    """拆 frontmatter → (fm 块含首尾 ---（无尾换行）, --- 行尾换行, 正文)。
    分隔换行必须与正文分开保真：重写元数据按 `fm + sep + body` 拼回，二次拆分
    幂等且 body 逐字节不变。注意调用方经 read_text() 读文件（通用换行翻译），
    CRLF 在进入本函数前已是 LF——首保存把 CRLF 文件整体规范成 LF 是 read_text
    的行为，不是本函数引入；本函数在 LF 域内逐字节保真。无 frontmatter 时前两项为空串。"""
    m = FM_OPEN_RE.match(text)
    if not m:
        return "", "", text
    rest = text[m.end():]
    # 捕获 closing --- 前的换行并原样复用：CRLF 文件少一次无谓改写
    # （此前重组补硬编码 \n，会把 FM 内部最后一行的 \r\n 规范化掉）
    close = re.search(r"(\r?\n)---[ \t]*(?=\r?\n)", rest)    # closing --- 行（后面还有内容）
    if close is None:
        close = re.search(r"(\r?\n)---[ \t]*\Z", rest)        # 文件恰在 --- 结束
        if close is None:
            return "", "", text
        return "---\n" + rest[:close.start()] + close.group(1) + "---", "", ""
    after = rest[close.end():]
    nl = re.match(r"\r?\n", after)
    return ("---\n" + rest[:close.start()] + close.group(1) + "---",
            nl.group(0) if nl else "",
            after[len(nl.group(0)):] if nl else after)


def parse_fm_fields(fm_block: str) -> dict:
    """frontmatter → {title, date, categoryTags: [...], subCategoryTags: [...]}。
    极简 YAML 子集（数组优先按 JSON 解析，退回逗号拆分），与 render_md 同口径。"""
    out: dict = {"title": "", "date": "", "categoryTags": [], "subCategoryTags": []}
    for line in fm_block.splitlines():
        if ":" not in line or line.strip().startswith("---"):
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key not in out:
            continue
        if isinstance(out[key], list):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    out[key] = [str(x).strip() for x in parsed if str(x).strip()]
                    continue
            except ValueError:
                pass
            out[key] = [x.strip().strip('"').strip("'")
                        for x in val.strip().strip("[]").split(",") if x.strip()]
        else:
            out[key] = val.strip().strip('"').strip("'")
    return out


def build_front_matter(meta: dict) -> str:
    """元数据 → 规范 frontmatter 块（双引号标量 + JSON 数组，与存量文章同款）。"""
    def q(s: str) -> str:
        return '"' + str(s or "").replace('"', "'") + '"'
    lines = ["---",
             f"title: {q(meta.get('title', ''))}",
             f"date: {q(meta.get('date', ''))}"]
    for k in ("categoryTags", "subCategoryTags"):
        tags = meta.get(k) or []
        lines.append(f"{k}: [" + ", ".join(q(t) for t in tags) + "]")
    lines.append("---")
    return "\n".join(lines)          # 不带尾换行 —— 拼回时用 split_front_matter 的 sep 保真


def _fm_title(meta: dict, body: str, stem: str) -> str:
    """标题兜底链与构建一致：frontmatter title > 正文首个 # 标题 > 文件名。"""
    if meta.get("title"):
        return str(meta["title"])
    h1 = re.search(r"(?m)^#\s+(.+)$", body)
    return (h1.group(1).strip() if h1 else "") or stem


def article_record(path: Path) -> dict | None:
    """列表行：文件名 + 元数据 + slug / 字数 / 大小 / 修改时间。"""
    try:
        st = path.stat()
        text = path.read_text(encoding="utf-8").replace("\uFEFF", "")
    except (OSError, UnicodeDecodeError):
        return None
    fm, _sep, body = split_front_matter(text)
    meta = parse_fm_fields(fm)
    m_date = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", path.stem)
    # 字数与构建同口径（剥标记纯文本；plain_text 自带 frontmatter 剥离与模板段过滤）
    try:
        words = len(plain_text(body).strip())
    except Exception:
        words = len(re.sub(r"\s", "", body))
    return {"file": path.name,
            "title": _fm_title(meta, body, path.stem),
            "date": meta.get("date") or (m_date.group(1) if m_date else ""),
            "categoryTags": meta.get("categoryTags") or [],
            "subCategoryTags": meta.get("subCategoryTags") or [],
            "slug": m_date.group(2) if m_date else path.stem,
            "sizeBytes": st.st_size, "mtimeMs": round(st.st_mtime * 1000),
            "words": words}


def article_trash_list() -> list[dict]:
    """content/.trash/guide/ 下的已删文章（本机回收站）。"""
    out: list[dict] = []
    if ARTICLE_TRASH.is_dir():
        for md in ARTICLE_TRASH.glob("*.md"):
            try:
                st = md.stat()
                text = md.read_text(encoding="utf-8").replace("\uFEFF", "")
            except (OSError, UnicodeDecodeError):
                continue
            fm, _sep, body = split_front_matter(text)
            out.append({"name": md.name, "title": _fm_title(parse_fm_fields(fm), body, md.stem),
                        "sizeBytes": st.st_size, "mtimeMs": round(st.st_mtime * 1000)})
    out.sort(key=lambda r: r["mtimeMs"], reverse=True)
    return out


def do_articles_list() -> dict:
    arts: list[dict] = []
    if GUIDE_DIR.is_dir():
        for md in GUIDE_DIR.glob("*.md"):
            rec = article_record(md)
            if rec:
                arts.append(rec)
    arts.sort(key=lambda r: (r["date"], r["file"]), reverse=True)
    return {"articles": arts, "trash": article_trash_list()}


def _article_path(file: str) -> tuple[Path | None, str]:
    """清洗并解析文章绝对路径；返回 (路径, 错误信息)。防目录穿越。"""
    fname = article_safe_name(file)
    if not fname:
        return None, "文件名不合法"
    p = (GUIDE_DIR / fname)
    if not _under_dir(p, GUIDE_DIR):
        return None, "非法路径"
    return p, ""


def do_article_read(file: str) -> dict:
    """正文预览/编辑：frontmatter 与正文分体返回（编辑器只编辑正文）。"""
    p, err = _article_path(file)
    if err:
        return {"ok": False, "error": err}
    if not p.is_file():
        return {"ok": False, "error": "文件不存在（可能已删除）"}
    try:
        st = p.stat()
        if st.st_size > ARTICLE_MAX:
            return {"ok": False, "error": "文件超过 2MB，不支持在线编辑"}
        raw = p.read_text(encoding="utf-8").replace("\uFEFF", "")
    except (OSError, UnicodeDecodeError) as e:
        return {"ok": False, "error": f"读取失败：{e}"}
    fm, _sep, body = split_front_matter(raw)
    meta = parse_fm_fields(fm)
    return {"ok": True, "file": p.name, "title": _fm_title(meta, body, p.stem),
            "meta": meta, "frontmatter": fm, "body": body,
            "sizeBytes": st.st_size, "mtimeMs": round(st.st_mtime * 1000)}


def _mtime_conflict(p: Path, expected) -> str:
    """乐观锁（mystation 同款）：expected 带了且与当前 mtime 对不上 → 提示冲突。
    防两处静默覆盖：另一标签页保存过 / 外部编辑器改过文件。"""
    if expected in (None, ""):
        return ""
    try:
        cur = round(p.stat().st_mtime * 1000)
    except OSError:
        return "文件已不存在（可能被删除或移入回收站）——请刷新列表"
    if abs(cur - float(expected)) > 1:
        return ("文章已在后台被更新（其他标签页或外部编辑器），当前编辑已过期——"
                "刷新列表取最新内容后重做，避免覆盖他人改动")
    return ""


def _backup_md(p: Path) -> None:
    """写回前备份上一版为同名 .bak（覆盖式单份）：手滑改坏时有一步回退。"""
    if p.exists():
        p.with_name(p.name + ".bak").write_bytes(p.read_bytes())


def do_article_save(file: str, body: str, expected_mtime) -> dict:
    """保存正文：只写正文，文件自己的 frontmatter 原样保留。"""
    p, err = _article_path(file)
    if err:
        return {"ok": False, "error": err}
    if not p.is_file():
        return {"ok": False, "error": "文件不存在（可能已删除）"}
    if conflict := _mtime_conflict(p, expected_mtime):
        return {"ok": False, "conflict": True, "error": conflict}
    if len(body or "") > ARTICLE_MAX:
        return {"ok": False, "error": "正文超过 2MB"}
    try:
        raw = p.read_text(encoding="utf-8").replace("\uFEFF", "")
        fm, sep, _ = split_front_matter(raw)
        _backup_md(p)
        # 正文里的 BOM 一并剥掉（Windows 剪贴板常带，卡在行首会让 ^ 锚点失配）
        p.write_text(fm + sep + (body or "").replace("\uFEFF", ""),
                     encoding="utf-8", newline="\n")
    except OSError as e:
        return {"ok": False, "error": f"写入失败：{e}"}
    return {"ok": True, "mtimeMs": round(p.stat().st_mtime * 1000)}


def do_article_meta(file: str, meta: dict, expected_mtime) -> dict:
    """行内元数据编辑：重写 frontmatter（title/date/两级标签），正文原样保留。

    文件名日期前缀是排序与 slug 的真正来源（构建优先取它），只改 frontmatter
    date 会造成「列表显示新日期、站点仍旧日期」的静默不一致 —— 前缀存在时
    随 date 一起重命名文件，保持单一口径。"""
    p, err = _article_path(file)
    if err:
        return {"ok": False, "error": err}
    if not p.is_file():
        return {"ok": False, "error": "文件不存在（可能已删除）"}
    if conflict := _mtime_conflict(p, expected_mtime):
        return {"ok": False, "conflict": True, "error": conflict}

    new_meta = {
        "title": str((meta or {}).get("title") or "").strip(),
        "date": str((meta or {}).get("date") or "").strip()[:10],
        "categoryTags": [str(t).strip() for t in ((meta or {}).get("categoryTags") or []) if str(t).strip()],
        "subCategoryTags": [str(t).strip() for t in ((meta or {}).get("subCategoryTags") or []) if str(t).strip()],
    }
    if not new_meta["title"]:
        return {"ok": False, "error": "标题不能为空"}
    if new_meta["date"] and not re.match(r"^\d{4}-\d{2}-\d{2}$", new_meta["date"]):
        return {"ok": False, "error": "日期格式应为 YYYY-MM-DD"}

    try:
        raw = p.read_text(encoding="utf-8").replace("\uFEFF", "")
        _, sep, body = split_front_matter(raw)
        renamed = ""
        m_date = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", p.stem)
        if new_meta["date"] and m_date and m_date.group(1) != new_meta["date"]:
            target = GUIDE_DIR / f"{new_meta['date']}-{m_date.group(2)}.md"
            if target.exists():
                return {"ok": False, "error": f"目标文件名已存在：{target.name}（改日期会重命名文件，但同名文件已在）"}
            old_bak = p.with_name(p.name + ".bak")
            p.rename(target)
            if old_bak.exists():                 # .bak 跟着文件改名，避免旧名孤儿备份散在目录里
                old_bak.rename(target.with_name(target.name + ".bak"))
            p = target
            renamed = target.name
        # 备份放在改名**之后**：.bak 必须跟最终文件名配对，否则改名场景下旧名 .bak 会失配
        _backup_md(p)
        # 无 frontmatter 的文章（手拷进来的 md）：sep 为空会让闭合 --- 与正文首行
        # 粘成一行，此后 frontmatter 永远解析不出——补一个换行
        if not sep:
            sep = "\n"
        p.write_text(build_front_matter(new_meta) + sep + body, encoding="utf-8", newline="\n")
    except OSError as e:
        return {"ok": False, "error": f"写入失败：{e}"}
    return {"ok": True, "file": p.name, "renamed": renamed,
            "mtimeMs": round(p.stat().st_mtime * 1000)}


def do_article_new(title: str, slug: str, date: str, category_tags, sub_tags) -> dict:
    """新建文章：frontmatter 自动生成，文件名 = 日期前缀 + 语义 slug（构建同款）。"""
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "标题不能为空"}
    date = (date or "").strip() or time.strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return {"ok": False, "error": "日期格式应为 YYYY-MM-DD（或留空用今天）"}
    # slug 是 URL 的一部分（/guide/<slug>/）：只留 URL 安全字符
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", (slug or "").strip()).strip("-").lower()
    if not slug:
        return {"ok": False, "error": "slug 只能含英文字母 / 数字 / 连字符"}
    GUIDE_DIR.mkdir(parents=True, exist_ok=True)
    target = GUIDE_DIR / f"{date}-{slug}.md"
    if target.exists():
        return {"ok": False, "error": f"同名文件已存在：{target.name}"}
    meta = {"title": title, "date": date,
            "categoryTags": [str(t).strip() for t in (category_tags or []) if str(t).strip()],
            "subCategoryTags": [str(t).strip() for t in (sub_tags or []) if str(t).strip()]}
    try:
        target.write_text(build_front_matter(meta) + "\n" + f"# {title}\n\n",
                          encoding="utf-8", newline="\n")
    except OSError as e:
        return {"ok": False, "error": f"创建失败：{e}"}
    return {"ok": True, "file": target.name, "slug": slug}


def do_article_delete(file: str) -> dict:
    """删除 = 移入本机回收站 content/.trash/guide/（mystation 同款软删除）。
    不动 git、不构建 —— 线上下线随下一次「推送文章改动」生效。"""
    p, err = _article_path(file)
    if err:
        return {"ok": False, "error": err}
    if not p.is_file():
        return {"ok": False, "error": "文件不存在（可能已删除）"}
    ARTICLE_TRASH.mkdir(parents=True, exist_ok=True)
    target = ARTICLE_TRASH / p.name
    if target.exists():
        target = ARTICLE_TRASH / f"{p.stem}.deleted-{int(time.time())}.md"
    try:
        p.rename(target)
        bak = p.with_name(p.name + ".bak")      # .bak 随正文一起进回收站，恢复时才不散架
        if bak.exists():
            bak.rename(ARTICLE_TRASH / bak.name)
    except OSError as e:
        return {"ok": False, "error": f"移动失败：{e}"}
    return {"ok": True, "trashName": target.name}


def do_article_restore(name: str) -> dict:
    """从回收站恢复。原文件名被占时改用 .restored-<时间戳> 名（如实告知）。"""
    fname = article_safe_name(name)
    if not fname:
        return {"ok": False, "error": "文件名不合法"}
    src = ARTICLE_TRASH / fname
    if not _under_dir(src, ARTICLE_TRASH) or not src.is_file():
        return {"ok": False, "error": "回收站中不存在该文件"}
    GUIDE_DIR.mkdir(parents=True, exist_ok=True)
    dest = GUIDE_DIR / fname
    if dest.exists():
        dest = GUIDE_DIR / f"{Path(fname).stem}.restored-{int(time.time())}.md"
    try:
        src.rename(dest)
        bak = src.with_name(src.name + ".bak")   # .bak 跟着恢复，名字对齐恢复后的文件名
        if bak.exists():
            bak.rename(dest.with_name(dest.name + ".bak"))
    except OSError as e:
        return {"ok": False, "error": f"恢复失败：{e}"}
    return {"ok": True, "file": dest.name}


# ────────────────────────── HTTP ──────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "GeoSciPlotAdmin/1.1"

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write(f"  {self.command} {self.path}\n")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _serve_local_image(self, rel: str) -> None:
        target = (IMG_DIR / rel).resolve()
        try:
            target.relative_to(IMG_DIR)          # 防目录穿越
        except ValueError:
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if target.is_file() and target.suffix.lower() in IMG_TYPES:
            self._send(200, target.read_bytes(), IMG_TYPES[target.suffix.lower()])
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def _safe_500(self, e: BaseException) -> None:
        """任何未捕获异常都转成 500 + JSON，而不是让线程带着异常死掉、
        客户端只看到「连接被无声关闭」。实测教训：文件删除可能被外部
        （杀软 / 沙箱）抛出非 OSError 的拦截异常，一旦穿透就是这种症状。"""
        try:
            self._json({"ok": False, "error": "服务器内部错误：" + repr(e)}, 500)
        except Exception:
            pass

    def _trusted(self) -> bool:
        """本机信任校验（与主站 admin-server.ts 的 trusted() 同一防御）。

        rebinding：攻击者域名 A 记录指到 127.0.0.1 后浏览器视为同源，但 Host 头
        仍是攻击者域名 → Host 白名单直接挡死。
        CSRF：本服务的 POST 全部是简单请求（fetch 带任意 Content-Type 的 JSON），
        免预检即可跨站发出；跨站时浏览器必带 Origin 头 → 非本机 Origin 一律拒绝；
        curl 等本机工具不带 Origin → 放行。没有这层，任意网页可打 /api/delete、
        甚至 /api/init 用本机 SSH key 把仓库 push 到攻击者远端。"""
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}",
                        "127.0.0.1", "localhost"):
            return False
        # Origin 只要有就校验（不限方法）：跨站 fetch 的 GET 同样带 Origin，
        # 不挡的话 /api/fetch-image 代理可被任意网页免预检滥用；同源 GET、
        # 地址栏导航、curl 等本机工具都不带 Origin，照常放行
        origin = (self.headers.get("Origin") or "").strip().lower()
        if origin and origin not in (f"http://127.0.0.1:{port}",
                                     f"http://localhost:{port}"):
            return False
        return True

    def do_GET(self):
        try:
            if not self._trusted():
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            self._handle_get()
        except Exception as e:
            self._safe_500(e)

    def _handle_get(self):
        path = (self.path or "/").split("?")[0]
        if path in ("/", "/index.html"):
            if UI_HTML.exists():
                self._send(200, UI_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(500, b"admin_ui.html not found", "text/plain; charset=utf-8")
        elif path == "/api/status":
            self._json(repo_state())
        elif path == "/api/items":
            self._json(load_refs())
        elif path == "/api/raw":
            self._json(do_raw_list())
        elif path == "/api/articles":
            self._json(do_articles_list())
        elif path == "/api/article/trash":
            self._json({"items": article_trash_list()})
        elif path == "/api/article":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._json(do_article_read((q.get("file") or [""])[0]))
        elif path.startswith("/api/job/"):
            self._json(job_snapshot(path[len("/api/job/"):]))
        elif path == "/api/fetch-image":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code, body, ctype = do_fetch_image(q)
            self._send(code, body, ctype)
        elif path.startswith("/images/"):
            self._serve_local_image(path[len("/images/"):])
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        try:
            if not self._trusted():
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            self._handle_post()
        except Exception as e:
            self._safe_500(e)

    def _handle_post(self):
        path = (self.path or "").split("?")[0]
        body = self._read_json()
        if path == "/api/upload":
            # 上传是纯本地快速操作，保持同步返回
            self._json(do_upload(body.get("files") or []))
        elif path == "/api/raw/delete":
            self._json(do_raw_delete(body.get("name") or body.get("rel") or ""))
        elif path == "/api/raw/clear":
            # 纯本地删文件，很快，保持同步返回（与 /api/raw/delete 一致）
            self._json(do_raw_clear())
        elif path == "/api/save":
            # 元数据暂存：纯本地读写（titles.csv + refs.json），毫秒级，同步返回。
            # 真持锁再写（此前只 locked() 探测存在 check-then-write 窗口）：
            # 流水线持有锁期间到这里的写入直接被拒，refs.json / titles.csv 不会撕裂
            if PIPELINE_LOCK.acquire(blocking=False):
                try:
                    self._json(do_update(body.get("items") or []))
                finally:
                    PIPELINE_LOCK.release()
            else:
                self._json({"ok": False, "error": "已有发布/推送任务在运行，等它结束后再保存"})
        elif path.startswith("/api/article/"):
            # 文章增删改都是本地文件写（毫秒级），同步返回；
            # 真持锁再写（口径同 /api/save）—— content/guide 可能正被构建读取
            if not PIPELINE_LOCK.acquire(blocking=False):
                self._json({"ok": False, "error": "已有发布/推送任务在运行，等它结束后再操作文章"})
            else:
                try:
                    if path == "/api/article/save":
                        self._json(do_article_save(body.get("file") or "", body.get("body") or "",
                                                   body.get("expectedMtimeMs")))
                    elif path == "/api/article/meta":
                        self._json(do_article_meta(body.get("file") or "", body.get("meta") or {},
                                                   body.get("expectedMtimeMs")))
                    elif path == "/api/article/new":
                        self._json(do_article_new(body.get("title") or "", body.get("slug") or "",
                                                  body.get("date") or "",
                                                  body.get("categoryTags"), body.get("subCategoryTags")))
                    elif path == "/api/article/delete":
                        self._json(do_article_delete(body.get("file") or ""))
                    elif path == "/api/article/restore":
                        self._json(do_article_restore(body.get("name") or ""))
                    else:
                        self._send(404, b"not found", "text/plain; charset=utf-8")
                finally:
                    PIPELINE_LOCK.release()
        elif path in ("/api/publish", "/api/stage", "/api/deploy", "/api/delete",
                      "/api/sync-server", "/api/init", "/api/push"):
            # 长操作：立即返回任务号，后台线程执行，前端轮询 /api/job/<id>
            self._json({"job": start_job(path[len("/api/"):], body)})
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="GeoSciPlot 本地管理界面")
    ap.add_argument("--port", type=int, default=5199)
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    for d in (RAW_DIR, META_DIR):
        d.mkdir(parents=True, exist_ok=True)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print("GeoSciPlot 管理界面")
    print(f"  → {url}")
    print("  只监听 127.0.0.1：仅本机可访问，无需登录")
    print(f"  仓库：{ROOT}")
    print("  Ctrl+C 退出\n")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
