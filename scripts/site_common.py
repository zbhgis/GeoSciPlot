"""构建脚本与视图层共用的站点常量与纯工具。

只放两边都要用的最小集合：路径根、站点 URL、资源版本号、分页大小，
以及 HTML 转义 / DOI 展示清洗。页面模板在 pages.py，构建编排在
build_site.py。
"""
from __future__ import annotations

import hashlib
import html
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAGE_SIZE = 30
# 兜底版本号（构建时间戳）：仅 asset_ver 找不到部署文件时使用。
# 2026-10 搜索改版踩过：旧 gallery.js 配新数据源会静默失效，?v= 必须保证
# 内容一变 URL 就变；但全站统一时间戳会让没改的文件缓存也全失效。
BUILD_VER = str(int(time.time()))
SITE_URL = "https://geosciplot.zbhgis.com"

# asset_ver 缓存：一次构建内同一文件只读一次
_VERS: dict[str, str] = {}


def asset_ver(name: str) -> str:
    """按部署文件内容取版本号（sha1 前 8 位）：内容不变 → ?v= 不变 →
    浏览器/CDN 缓存继续命中。gallery.js 等构建期注入配置的产物以 site/assets/
    里的最终内容为准，所以必须在资源写盘之后、页面渲染期间调用
    （build_site.py 的编排恰好是这个顺序）。"""
    v = _VERS.get(name)
    if v is None:
        f = ROOT / "site" / "assets" / name
        v = hashlib.sha1(f.read_bytes()).hexdigest()[:8] if f.is_file() else BUILD_VER
        _VERS[name] = v
    return v


def esc(s) -> str:
    """HTML 转义（保持原构建脚本口径：不转义引号，None → 空串）。"""
    return html.escape(str(s if s is not None else ""))


def doi_bare(v) -> str:
    """展示用短 DOI：剥掉 https://doi.org/ 前缀（refs.json 存的是完整 URL），
    链接场景由调用方自行拼接"""
    return str(v or "").removeprefix("https://doi.org/").removeprefix("http://doi.org/")
