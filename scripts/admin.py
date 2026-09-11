#!/usr/bin/env python3
"""GeoSciPlot 本地管理界面 —— 只有本机能访问（服务只绑定 127.0.0.1）。

用法：
    python scripts/admin.py                 # 自动打开 http://127.0.0.1:5199
    python scripts/admin.py --port 5200     # 换端口
    python scripts/admin.py --no-open       # 不自动打开浏览器

它能做什么：
    1. 拖拽上传图片 → 存入 raw/，按内容算出 id，并在界面上给出缩略图预览
    2. 逐张填写 标题 / 分类 / 期刊 / 发表时间 / 标签 / 说明
    3. 点「发布」→ 自动执行：写 meta/titles.csv → prepare.py → build_site.py
       → git add / commit / push（一条龙，界面显示每步日志）

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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
META_DIR = ROOT / "meta"
TITLES_CSV = META_DIR / "titles.csv"
REFS_JSON = META_DIR / "refs.json"
UI_HTML = Path(__file__).resolve().parent / "admin_ui.html"

PYTHON = sys.executable
DEFAULT_REMOTE = "git@github.com:zbhgis/GeoSciPlot.git"
MAX_BODY = 200 * 1024 * 1024          # 单次请求体上限
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
CSV_FIELDS = ["id", "title", "category", "journal", "published", "tags", "desc"]

from PIL import Image, ImageOps  # noqa: E402


# ────────────────────────── 工具 ──────────────────────────

def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    """执行命令，合并 stdout/stderr 返回。"""
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=timeout)
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, f"命令超时：{' '.join(cmd)}"
    except FileNotFoundError as e:
        return 127, f"命令不存在：{e}"


def safe_name(name: str) -> str:
    """只保留文件名本身，去掉路径与危险字符。"""
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


def read_titles() -> tuple[list[str], dict[str, dict]]:
    """返回 (列名顺序, {id: row})。保留未知列，避免丢人工数据。"""
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
    """生成界面预览用的小图（WebP → base64）。"""
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
        "journals": sorted({i.get("journal") for i in items if i.get("journal")}),
        "defaultRemote": DEFAULT_REMOTE,
    }


# ────────────────────────── 动作 ──────────────────────────

def do_upload(files: list[dict]) -> dict:
    """保存上传的图片到 raw/，返回 id、尺寸与预览。"""
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


def do_publish(items: list[dict], message: str, push: bool = True) -> dict:
    """写 CSV → 跑 prepare → 跑 build_site → git 提交推送。返回每步日志。"""
    log: list[dict] = []

    # 1) 元数据写进 titles.csv（保留未提交过的行与未知列）
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
        for k in ("title", "category", "journal", "published", "desc"):
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
    log.append({"step": "写入标题表", "ok": True,
                "out": f"meta/titles.csv 更新 {written} 条"})

    # 2) 图片规范化 + 索引
    code, out = run([PYTHON, "scripts/prepare.py"])
    log.append({"step": "生成图片与索引 (prepare.py)", "ok": code == 0, "out": out})
    if code != 0:
        return {"ok": False, "log": log, "hint": "prepare.py 失败，未继续后面的步骤"}

    # 3) 生成静态站
    code, out = run([PYTHON, "scripts/build_site.py"])
    log.append({"step": "生成静态站 (build_site.py)", "ok": code == 0, "out": out})
    if code != 0:
        return {"ok": False, "log": log, "hint": "build_site.py 失败，未提交"}

    # 4) git 提交推送
    if not (ROOT / ".git").is_dir():
        log.append({"step": "Git", "ok": False,
                    "out": "尚未初始化 git 仓库 —— 点上方「初始化仓库」后再发布"})
        return {"ok": False, "log": log, "hint": "请先初始化 git 仓库"}

    if not message.strip():
        titles = [ (i.get("title") or "").strip() for i in items if (i.get("title") or "").strip() ]
        head = "、".join(titles[:3]) + ("…" if len(titles) > 3 else "")
        message = f"add: {len(items)} 张图" + (f"（{head}）" if head else "")

    code, out = run(["git", "add", "-A"])
    log.append({"step": "git add", "ok": code == 0, "out": out or "已暂存全部改动"})
    if code != 0:
        return {"ok": False, "log": log}

    code, out = run(["git", "commit", "-m", message])
    ok_commit = code == 0 or "nothing to commit" in out
    log.append({"step": f"git commit -m \"{message}\"", "ok": ok_commit, "out": out})
    if not ok_commit:
        return {"ok": False, "log": log, "hint": "提交失败（检查 git user.name / user.email）"}

    if not push:
        return {"ok": True, "log": log, "hint": "已跳过推送（可在界面里单独推送）"}

    code, out = run(["git", "push"], timeout=180)
    log.append({"step": "git push", "ok": code == 0, "out": out})
    if code != 0:
        return {"ok": False, "log": log,
                "hint": "推送失败：检查 origin 是否为 github.com:zbhgis/GeoSciPlot.git，以及 SSH key"}
    return {"ok": True, "log": log}


def do_init(remote: str) -> dict:
    """git init + 加 remote + 首次提交（仅当还不是仓库时）。"""
    log: list[dict] = []
    if (ROOT / ".git").is_dir():
        return {"ok": False, "log": [{"step": "初始化", "ok": False, "out": "已经是 git 仓库"}]}

    for cmd, label in [
        (["git", "init", "-b", "main"], "git init"),
        (["git", "add", "-A"], "git add -A"),
        (["git", "commit", "-m", "chore: 初始化 GeoSciPlot 图库"], "git commit"),
    ]:
        code, out = run(cmd)
        ok = code == 0 or "nothing to commit" in out
        log.append({"step": label, "ok": ok, "out": out or "完成"})
        if not ok:
            return {"ok": False, "log": log}

    if remote.strip():
        code, out = run(["git", "remote", "add", "origin", remote.strip()])
        log.append({"step": f"git remote add origin {remote.strip()}", "ok": code == 0, "out": out or "已设置"})
        if code == 0:
            code, out = run(["git", "push", "-u", "origin", "main"], timeout=180)
            log.append({"step": "git push -u origin main", "ok": code == 0, "out": out})
    return {"ok": True, "log": log}


def do_push() -> dict:
    code, out = run(["git", "push"], timeout=180)
    return {"ok": code == 0, "log": [{"step": "git push", "ok": code == 0, "out": out}]}


# ────────────────────────── HTTP ──────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "GeoSciPlotAdmin/1.0"

    def log_message(self, fmt, *args):        # 精简访问日志
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

    def do_GET(self):
        path = (self.path or "/").split("?")[0]
        if path in ("/", "/index.html"):
            if UI_HTML.exists():
                self._send(200, UI_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(500, b"admin_ui.html not found", "text/plain; charset=utf-8")
        elif path == "/api/status":
            self._json(repo_state())
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = (self.path or "").split("?")[0]
        body = self._read_json()
        if path == "/api/upload":
            self._json(do_upload(body.get("files") or []))
        elif path == "/api/publish":
            self._json(do_publish(body.get("items") or [], body.get("message") or "",
                                  bool(body.get("push", True))))
        elif path == "/api/init":
            self._json(do_init(body.get("remote") or ""))
        elif path == "/api/push":
            self._json(do_push())
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
