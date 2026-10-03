# -*- coding: utf-8 -*-
"""构建自包含本地演示包（S4 / V2-012，A 本地完整查询版）。

产物 release/nsfc-demo/：
  dist/        前端生产构建（vite build）
  data/        冻结的统一库 + 分析/聚合 JSON（构建时刻的快照）
  serve_api.py 只读 API + dist 静态托管（端口内一体化）
  start_demo.bat / start_demo.sh  一键启动（自动开浏览器）
  README.md / SUBMISSION.md / SNAPSHOT.txt  说明、创作声明、产物哈希清单

用法：python tools/build_package.py [--skip-build]
--skip-build：dist 已构建好时跳过 vite build（数据仍重新冻结）。
整个包不依赖开发目录的绝对路径：启动脚本先切到包自身目录再以相对路径启动。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
RELEASE_DIR = PROJECT_ROOT / "release"
PKG_DIR = RELEASE_DIR / "nsfc-demo"

DATA_FILES = [
    ("data/unified.db", "data/unified.db"),
    ("data/analysis/analysis.json", "data/analysis/analysis.json"),
    ("data/analysis/analysis_advanced.json", "data/analysis/analysis_advanced.json"),
    ("data/national/national.json", "data/national/national.json"),
    ("data/national/recent.json", "data/national/recent.json"),
]
# projects_all.csv（122MB 派生导出）不进包：检索导出走 /api/projects，演示用不到

START_BAT = """@echo off
chcp 65001 >nul
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo [启动失败] 未找到 python，请安装 Python 3.10+。
  exit /b 1
)
echo NSFC 演示服务启动中... http://localhost:8000/
start "" cmd /c "timeout /t 2 >nul & python -m webbrowser http://localhost:8000/"
python serve_api.py --port 8000 --data-dir data --static-dir dist
"""

START_SH = """#!/bin/sh
cd "$(dirname "$0")"
PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
command -v $PY >/dev/null 2>&1 || { echo "[启动失败] 未找到 python3"; exit 1; }
echo "NSFC 演示服务启动中... http://localhost:8000/"
( sleep 2 && $PY -m webbrowser http://localhost:8000/ ) &
$PY serve_api.py --port 8000 --data-dir data --static-dir dist
"""

PACKAGE_README = """# NSFC 科研资助探索台 · 本地演示包

自包含：前端 dist + 冻结数据 + 只读 API，一个进程服务全部页面与接口。

## 启动

Windows：双击 `start_demo.bat`
macOS / Linux：`./start_demo.sh`（先 `chmod +x start_demo.sh`）

浏览器自动打开 http://localhost:8000/ （约 2 秒后；也可手动访问）。
停止：在启动它的终端按 Ctrl+C。

## 环境要求

- Python 3.10+（仅用标准库：http.server / sqlite3 / json，无需 pip 安装）
- 现代浏览器（Chromium 内核或 Firefox）

## 这是什么

库内 165,200 条国自然项目（按结题年度采入的样本，不是全国全量明细）的
可追溯分析台：范围条限定样本 → 图表/表格比较 → 点开项目看逐字段来源与
冲突留档 → 带走带口径的导出（CSV / Markdown 摘要）。

数据快照、哈希与构建时间见 `SNAPSHOT.txt`；创作说明见 `SUBMISSION.md`。
首页「发现问题」给三条真实数据的示例问题，点进去即带筛选打开检索页。

## 常见问题

- 端口被占：编辑启动脚本的 `--port 8000` 改成别的端口。
- 首页空白：看终端输出，`/api/health` 会说明缺哪个产物（本包应全部 ready）。
- 深链接刷新：完全正常——页面/筛选/详情号都在 URL hash 里（如
  http://localhost:8000/#/explorer?q=自噬&year=2018&page=1）。
"""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_dist(skip_build: bool) -> None:
    dist = WEB_DIR / "dist"
    if not skip_build:
        print("[1/5] 构建前端 (vite build)…")
        subprocess.run(["npm", "run", "build"], cwd=str(WEB_DIR), check=True,
                       shell=sys.platform == "win32")
    else:
        print("[1/5] 跳过 vite build，沿用 web/dist")
    if not (dist / "index.html").is_file():
        raise SystemExit("web/dist/index.html 不存在：先跑 npm run build 或去掉 --skip-build")


def freeze_data() -> list[tuple[str, str, int]]:
    print("[2/5] 冻结数据产物…")
    rows = []
    for src_rel, dst_rel in DATA_FILES:
        src = PROJECT_ROOT / src_rel
        dst = PKG_DIR / dst_rel
        if not src.exists():
            raise SystemExit(f"缺少数据产物: {src}（先跑 merge.build / analysis.analyze / build_national）")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        rows.append((dst_rel, sha256_of(dst), dst.stat().st_size))
        print(f"  {dst_rel}  {dst.stat().st_size / 1e6:.1f} MB")
    return rows


def copy_server_and_scripts() -> None:
    print("[3/5] 复制服务与启动脚本…")
    shutil.copy2(PROJECT_ROOT / "tools" / "serve_api.py", PKG_DIR / "serve_api.py")
    (PKG_DIR / "start_demo.bat").write_text(START_BAT, encoding="utf-8")
    (PKG_DIR / "start_demo.sh").write_text(START_SH, encoding="utf-8")
    (PKG_DIR / "README.md").write_text(PACKAGE_README, encoding="utf-8")
    # Shell 脚本给执行位（Windows 上不影响）
    (PKG_DIR / "start_demo.sh").chmod(0o755)


def write_snapshot(data_rows: list[tuple[str, str, int]]) -> None:
    print("[4/5] 写快照清单…")
    db = PKG_DIR / "data" / "unified.db"
    counts = {"unified_projects": "—", "unified_conflicts": "—"}
    if db.is_file():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            counts = {
                "unified_projects": con.execute("SELECT count(*) FROM unified_projects").fetchone()[0],
                "unified_conflicts": con.execute("SELECT count(*) FROM unified_conflicts").fetchone()[0],
            }
        finally:
            con.close()
    dist_files = sorted(str(p.relative_to(PKG_DIR / "dist")) for p in (PKG_DIR / "dist").rglob("*") if p.is_file())
    lines = [
        f"NSFC 本地演示包 · 数据快照清单",
        f"构建时间：{datetime.now().isoformat(timespec='seconds')}",
        f"行计数：unified_projects={counts['unified_projects']:,} unified_conflicts={counts['unified_conflicts']:,}",
        "",
        "数据产物（sha256 全文 / 字节）:",
    ]
    for rel, digest, size in data_rows:
        lines.append(f"  {rel}\t{digest}\t{size}")
    lines += ["", f"前端文件：{len(dist_files)} 个（dist/）", "  index.html", "  assets/…"]
    (PKG_DIR / "SNAPSHOT.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()

    if PKG_DIR.exists():
        print(f"清空旧包: {PKG_DIR}")
        shutil.rmtree(PKG_DIR)
    PKG_DIR.mkdir(parents=True)

    build_dist(args.skip_build)

    print(f"复制 dist → {PKG_DIR / 'dist'}")
    shutil.copytree(WEB_DIR / "dist", PKG_DIR / "dist")

    data_rows = freeze_data()
    copy_server_and_scripts()

    # 演示包不打包 SUBMISSION.md 占位（由 docs/SubMISSION.md 拷入，若有）
    submission = PROJECT_ROOT / "docs" / "SUBMISSION.md"
    if submission.is_file():
        shutil.copy2(submission, PKG_DIR / "SUBMISSION.md")
        print("  含 SUBMISSION.md")

    write_snapshot(data_rows)

    total_mb = sum(f.stat().st_size for f in PKG_DIR.rglob("*") if f.is_file()) / 1e6
    print(f"[5/5] 完成：{PKG_DIR}（{total_mb:.0f} MB）")
    print(f"启动：双击 {PKG_DIR / 'start_demo.bat'}，或 python serve_api.py --port 8000 "
          f"--data-dir data --static-dir dist（在包目录内）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
