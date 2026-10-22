"""构建脚本与视图层共用的站点常量与纯工具。

只放两边都要用的最小集合：路径根、站点 URL、资源版本号、分页大小，
以及 HTML 转义 / DOI 展示清洗。页面模板在 pages.py，构建编排在
build_site.py。
"""
from __future__ import annotations

import html
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAGE_SIZE = 30
# 资源版本号（构建时间戳）：CSS/JS 引用统一带 ?v=，部署后老访客的浏览器
# 不会再用缓存的旧脚本配新页面（2026-10 搜索改版踩过：旧 gallery.js 读不到新数据源）
BUILD_VER = str(int(time.time()))
SITE_URL = "https://geosciplot.zbhgis.com"


def esc(s) -> str:
    """HTML 转义（保持原构建脚本口径：不转义引号，None → 空串）。"""
    return html.escape(str(s if s is not None else ""))


def doi_bare(v) -> str:
    """展示用短 DOI：剥掉 https://doi.org/ 前缀（refs.json 存的是完整 URL），
    链接场景由调用方自行拼接"""
    return str(v or "").removeprefix("https://doi.org/").removeprefix("http://doi.org/")
