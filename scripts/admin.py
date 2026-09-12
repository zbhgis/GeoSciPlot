#!/usr/bin/env python3
"""GeoSciPlot 本地管理界面 —— 只有本机能访问（服务只绑定 127.0.0.1）。

用法：
    python scripts/admin.py                 # 自动打开 http://127.0.0.1:5199
    python scripts/admin.py --port 5200     # 换端口
    python scripts/admin.py --no-open       # 不自动打开浏览器

功能：
    1. 拖拽上传图片 → 存入 raw/，按内容算出 id，并在界面上给出缩略图预览
    2. 逐张填写 期刊 / 论文发表 / 标签 / 说明
    3. 图片管理：增删查改（元数据修改、删除图片），改动自动同步 GitHub 与线上站点
    4. 点「发布」→ 自动执行：写 meta/titles.csv → prepare.py → build_site.py
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
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageOps  # noqa: E402

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
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
CSV_FIELDS = ["id", "tags", "doi", "title", "category"]
MANUAL_TEXT = ("doi",)
MANUAL_LIST = ("tags",)
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
    if REFS_JSON.exists():
        try:
            return json.loads(REFS_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"items": []}


def save_refs(refs: dict) -> None:
    REFS_JSON.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            im.thumbnail((box, box), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=72, method=4)
            return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def repo_state() -> dict:
    refs = load_refs()
    items = refs.get("items", [])
    is_repo = (ROOT / ".git").is_dir()
    remote = ""
    branch = "main"
    dirty = 0
    if is_repo:
        code, out = run(["git", "remote", "get-url", "origin"])
        remote = out if code == 0 else ""
        code, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        branch = out if code == 0 else "main"
        code, out = run(["git", "status", "--porcelain"])
        dirty = len([l for l in out.splitlines() if l.strip()]) if code == 0 else 0
    return {
        "isRepo": is_repo,
        "remote": remote,
        "branch": branch,
        "dirty": dirty,
        "count": len(items),
        "categories": sorted({i.get("category") for i in items if i.get("category")}),
        "defaultRemote": DEFAULT_REMOTE,
    }


# ────────────────────────── 后台任务系统 ──────────────────────────
# 发布/删除/更新/推送都是「生成站点 + git push + scp 服务器」的长操作，
# 以前在 HTTP 请求里同步执行，git push 一卡界面就停滞几分钟。
# 现在：POST 立即返回任务号，后台线程跑流水线，前端轮询 /api/job/<id> 看实时进度。

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


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
    """启动后台任务，立即返回任务号。"""
    jid = uuid.uuid4().hex[:8]
    job = {"kind": kind, "log": [], "done": False, "ok": None, "hint": ""}
    with JOBS_LOCK:
        JOBS[jid] = job
        done_ids = [k for k, v in JOBS.items() if v["done"]]
        for k in done_ids[:-20]:          # 只保留最近 20 个已完成的任务
            JOBS.pop(k, None)

    def worker():
        try:
            if kind == "publish":
                res = do_publish(body.get("items") or [], body.get("message") or "",
                                 bool(body.get("push", True)), bool(body.get("sync", True)))
            elif kind == "update":
                res = do_update_and_finish(body.get("items") or [], body.get("message") or "",
                                           bool(body.get("push", True)), bool(body.get("sync", True)))
            elif kind == "delete":
                res = do_delete_and_finish((body.get("id") or "").strip(), body.get("message") or "",
                                           bool(body.get("push", True)), bool(body.get("sync", True)))
            elif kind == "sync-server":
                res = do_sync_server()
            elif kind == "init":
                res = do_init(body.get("remote") or "")
            elif kind == "push":
                res = do_push()
            else:
                res = {"ok": False, "log": [{"step": kind, "ok": False, "out": "未知任务类型"}]}
        except Exception as e:            # 后台线程绝不能静默死掉
            res = {"ok": False, "hint": "", "log": [{"step": "后台任务异常", "ok": False, "out": repr(e)}]}
        with JOBS_LOCK:
            job["log"] = res.get("log", job["log"])
            job["done"] = True
            job["ok"] = bool(res.get("ok"))
            job["hint"] = res.get("hint", "")

    threading.Thread(target=worker, daemon=True, name=f"job-{kind}-{jid}").start()
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
        for k in MANUAL_TEXT + MANUAL_LIST + ("category", "title"):
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
        for k in MANUAL_TEXT + MANUAL_LIST + ("category", "title"):
            if k in upd:
                it[k] = upd[k]
        n += 1
    save_refs(refs)
    return n


# ────────────────────────── 动作 ──────────────────────────

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
        rec = {"name": name, "savedAs": target.name, "id": fid,
               "bytes": len(data), "duplicate": fid in known, "preview": ""}
        try:
            with Image.open(target) as im:
                rec["width"], rec["height"] = im.size
            rec["preview"] = preview_b64(target)
        except Exception as e:
            rec["error"] = f"无法解析为图片：{e}"
        out.append(rec)
    return {"files": out}


def do_update(updates: list[dict]) -> dict:
    """批量更新元数据：写 titles.csv + 回填 refs.json（不重新生成站点）。"""
    upd_map: dict[str, dict] = {}
    for u in updates:
        fid = (u.get("id") or "").strip()
        if not fid:
            continue
        upd_map[fid] = {k: u[k] for k in list(MANUAL_TEXT) + list(MANUAL_LIST) if k in u}
    if not upd_map:
        return {"ok": False, "log": [{"step": "更新元数据", "ok": False, "out": "没有可更新的字段"}]}

    n_csv = apply_to_csv(upd_map)
    n_refs = apply_to_refs(upd_map)
    return {"ok": True,
            "log": [{"step": "更新元数据", "ok": True,
                     "out": f"titles.csv 与 refs.json 各回填 {n_csv}/{n_refs} 条"}]}


def do_delete(fid: str) -> dict:
    refs = load_refs()
    items = refs.get("items", [])
    it = next((x for x in items if x.get("id") == fid), None)
    if not it:
        return {"ok": False, "log": [{"step": "删除", "ok": False, "out": f"id 不存在：{fid}"}]}

    removed: list[str] = []
    for key in ("thumb", "full"):
        p = IMG_DIR / str(it.get(key, ""))
        if p.exists():
            p.unlink()
            removed.append(str(p.relative_to(ROOT)))
    raw_file = RAW_DIR / str(it.get("origName", ""))
    if raw_file.exists():
        raw_file.unlink()
        removed.append(str(raw_file.relative_to(ROOT)))

    refs["items"] = [x for x in items if x.get("id") != fid]
    refs["count"] = len(refs["items"])
    save_refs(refs)

    fields, rows = read_titles()
    rows.pop(fid, None)
    write_titles(fields, rows)

    for d in (IMG_DIR / "thumb", IMG_DIR / "full"):
        if d.exists():
            for sub in d.iterdir():
                if sub.is_dir() and not any(sub.iterdir()):
                    sub.rmdir()

    out = "已移除 " + "、".join(removed) if removed else "已从索引移除"
    return {"ok": True, "item": it,
            "log": [{"step": f"删除 {fid}", "ok": True, "out": out}]}


def do_sync_server() -> dict:
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
    if not host:
        return {"ok": False,
                "log": [{"step": "同步服务器", "ok": False,
                         "out": "未配置 server.host —— 在 gallery.config.json 里加 "
                                "\"server\": {\"host\": \"root@47.98.133.104\", \"webroot\": \"/var/www/geosciplot\"}"}]}

    ssh_base = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", host]
    code, out = run(ssh_base + [f"mkdir -p {webroot} && find {webroot} -mindepth 1 -maxdepth 1 -exec rm -rf {{}} +"],
                    timeout=120)
    if code != 0:
        return {"ok": False, "log": [{"step": "同步服务器", "ok": False,
                                      "out": "SSH 连接失败（需先把本机公钥加入服务器 authorized_keys，"
                                             "命令见 README「服务器部署」一节）\n" + out}]}

    code, out = run(["scp", "-r", "-o", "BatchMode=yes", str(SITE) + "/.", f"{host}:{webroot}/"], timeout=600)
    if code != 0:
        return {"ok": False, "log": [{"step": "同步服务器", "ok": False, "out": "scp 失败\n" + out}]}
    return {"ok": True, "log": [{"step": "同步服务器", "ok": True, "out": f"site/ → {host}:{webroot}"}]}


def pipeline_after_content(log: list[dict], message: str, push: bool, sync: bool) -> dict:
    """内容变更后的公共收尾：生成站点 → git 提交推送 →（可选）同步服务器。
    所有步骤用 step() 执行，前端能看到每一步的实时状态。"""
    ok, out = step(log, "生成静态站 (build_site.py)", [PYTHON, "scripts/build_site.py"])
    if not ok:
        return {"ok": False, "log": log, "hint": "build_site.py 失败，未提交"}

    if not (ROOT / ".git").is_dir():
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
        log.append({"step": "同步服务器（ssh 清理 + scp 上传）", "out": "", "ok": None})
        res = do_sync_server()
        log[-1]["ok"] = bool(res["ok"])
        log[-1]["out"] = "\n".join(x.get("out", "") for x in res["log"])
        if not res["ok"]:
            return {"ok": True, "log": log,
                    "hint": "GitHub 已同步；服务器同步失败（见日志）——通常是本机公钥还没加到服务器的 authorized_keys，"
                            "也可以手动在 Git Bash 里 cd site && scp -r ./* root@47.98.133.104:/var/www/geosciplot/"}

    return {"ok": True, "log": log}


def do_publish(items: list[dict], message: str, push: bool = True, sync: bool = True) -> dict:
    log: list[dict] = []

    fields, rows = read_titles()
    for f in CSV_FIELDS:
        if f not in fields:
            fields.append(f)
    written = 0
    for it in items:
        fid = (it.get("id") or "").strip()
        if not fid:
            continue
        row = rows.get(fid, {k: "" for k in fields})
        for k in ("title", "category", "doi"):
            v = (it.get(k) or "").strip()
            if v:
                row[k] = v
        tags = it.get("tags")
        if isinstance(tags, list):
            tags = "|".join(t.strip() for t in tags if str(t).strip())
        if tags:
            row["tags"] = str(tags)
        row["id"] = fid
        rows[fid] = row
        written += 1
    write_titles(fields, rows)
    log.append({"step": "写入标题表", "ok": True, "out": f"meta/titles.csv 更新 {written} 条"})

    ok, out = step(log, "生成图片与索引 (prepare.py)", [PYTHON, "scripts/prepare.py"])
    if not ok:
        return {"ok": False, "log": log, "hint": "prepare.py 失败，未继续后面的步骤"}

    return pipeline_after_content(log, message or f"add: {written} 张图", push, sync)


def do_push() -> dict:
    log: list[dict] = []
    ok, out = step(log, "git push（推送到 GitHub）", ["git", "push"], timeout=300)
    if not ok:
        return {"ok": False, "log": log, "hint": "推送失败：检查 origin 与 SSH key（也可能是网络波动，稍后重试）"}
    return {"ok": True, "log": log}


def do_init(remote: str) -> dict:
    log: list[dict] = []
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


def do_update_and_finish(updates: list[dict], message: str, push: bool, sync: bool) -> dict:
    res = do_update(updates)
    if not res.get("ok"):
        return res
    log = res.get("log", [])
    return pipeline_after_content(log, message or "update: 图库元信息变更", push, sync)


def do_delete_and_finish(fid: str, message: str, push: bool, sync: bool) -> dict:
    res = do_delete(fid)
    if not res.get("ok"):
        return res
    log = res.get("log", [])
    return pipeline_after_content(log, message or f"delete: 图 {fid}", push, sync)


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

    def do_GET(self):
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
        elif path.startswith("/api/job/"):
            self._json(job_snapshot(path[len("/api/job/"):]))
        elif path.startswith("/images/"):
            self._serve_local_image(path[len("/images/"):])
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = (self.path or "").split("?")[0]
        body = self._read_json()
        if path == "/api/upload":
            # 上传是纯本地快速操作，保持同步返回
            self._json(do_upload(body.get("files") or []))
        elif path in ("/api/publish", "/api/update", "/api/delete",
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
