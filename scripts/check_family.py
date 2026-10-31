#!/usr/bin/env python3
"""跨项目「同源 bug 家族」指纹扫描器（2026-10-31 第六轮落地）。

背景：GeoSciPlot / MacroBiodiv / mystation 三仓共享大量复制代码，bug 的传播
方向是「修过的仓库 → 未修的仓库」单向失忆——修复注释写得再好，知识也只活在
修复现场。本脚本把历轮修复沉淀成**可 grep 的家族指纹**，复制代码或同步修复
后跑一遍，未修的兄弟副本当场现形。

用法：
    python scripts/check_family.py [目标仓库根 ...]
    缺省扫描当前仓库；跨项目时传多个根：python scripts/check_family.py . ../MacroBiodiv

退出码：发现 FAIL 项 = 1（告警不算）；全部通过/仅告警 = 0。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 每条指纹 = (家族名, 相对文件 glob, 匹配正则, 级别, 修复口径)
FAMILY_PRINTS = [
    ("F1 DNT 早退杀全站交互", "assets_src/*.js",
     r"doNotTrack\s*===\s*[\"']1[\"']\s*\)\s*return", "FAIL",
     "DNT 只能跳过打点本身——把条件并入打点 if，绝不能在 IIFE 里 return"),
    ("F2 .git 用 is_dir 判断（worktree 不兼容）", "scripts/admin.py",
     r'\.git"\)\.is_dir\(\)', "FAIL",
     "改用 exists()：worktree 检出时 .git 是文件"),
    ("F3 后台任务日志非流式（job 初始 log 为独立空表）", "scripts/admin.py",
     r'job\s*=\s*\{"kind":\s*kind,\s*"log":\s*\[\]', "FAIL",
     "共享同一列表对象（shared_log）并传入 do_*，或 step() 镜像"),
    ("F4 /api/save 用 locked() 探测（TOCTOU）", "scripts/admin.py",
     r"PIPELINE_LOCK\.locked\(\)", "FAIL",
     "改为 acquire(blocking=False) 真持锁 + finally 释放"),
    ("F5 split_front_matter 的 after[1:]（CRLF 只剥 1 字节）", "scripts/admin.py",
     r"after\[1:\]\s*if nl else after", "FAIL",
     "after[len(nl.group(0)):]，或捕获换行组原样复用"),
    ("F6 DOI 链接拼接不剥前缀", "scripts/admin_ui.html",
     r'a\.href\s*=\s*"https://doi\.org/"\s*\+\s*it\.doi', "FAIL",
     "剥 (?:https?://)?(?:dx\\.)?doi.org/ 前缀；非 DOI 绝对链接直用"),
    ("F7 索引损坏静默按空库继续", "scripts/admin.py",
     r"except\s+json\.JSONDecodeError:\s*\n\s*.*\n\s*return\s*\{\}", "FAIL",
     "备份现场并抛错（.corrupt-<时间戳>），绝不以空库覆盖"),
    ("F8 统计数据后写盘（asset_ver ?v= 滞后一轮）", "scripts/build_site.py",
     r"build_stats_page\(cfg[^\n]*\)\n\s*build_stats_data\(", "FAIL",
     "先写 stats-data 再渲染统计页（asset_ver 读的是最终内容）"),
    ("F9 og:image 双重转义（取自已转义 HTML 再 esc）", "scripts/build_site.py",
     r'"og_image":\s*first_img\.group\(1\)\s+if', "WARN",
     "html.unescape 后存 og_image（page_shell 会再 esc 一次）"),
    ("F10 删除流程漏 disp 档", "scripts/admin.py",
     r'for key in \("thumb", "full"\)', "WARN",
     "清理档位集合必须 ⊇ prepare 产出的档位集合（thumb/full/disp）"),
]


def scan(repo: Path) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    for family, glob, pattern, level, hint in FAMILY_PRINTS:
        for f in sorted(repo.glob(glob)):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if re.search(pattern, text):
                rel = f.relative_to(repo)
                line_no = "-"
                m = re.search(pattern, text)
                if m:
                    line_no = str(text[: m.start()].count("\n") + 1)
                entry = f"[{family}] {repo.name}/{rel}:{line_no} → {hint}"
                (fails if level == "FAIL" else warns).append(entry)
    return fails, warns


def main(argv: list[str]) -> int:
    repos = [Path(a) for a in argv[1:]] or [Path(__file__).resolve().parent.parent]
    total_fails = 0
    for repo in repos:
        if not repo.is_dir():
            print(f"! 跳过不存在的仓库根：{repo}")
            continue
        fails, warns = scan(repo)
        print(f"── {repo.resolve().name} ── FAIL {len(fails)} / WARN {len(warns)}")
        for e in fails + warns:
            print("  " + e)
        total_fails += len(fails)
    if total_fails:
        print(f"\n共 {total_fails} 处未修家族副本（复制代码/同步修复后必跑本脚本）")
        return 1
    print("\n全部家族指纹通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
