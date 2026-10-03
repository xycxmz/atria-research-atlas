# -*- coding: utf-8 -*-
"""看板后端：标准库 http.server，提供分析产物与项目查询 API。

设计：分析维度由 analysis.analyze 预计算为 JSON，本服务只做静态文件
托管 + 轻量项目检索（分页/过滤），避免在看板侧重复实现 pandas 逻辑。

用法：python tools/serve_api.py [--port 8000]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = PROJECT_ROOT / "data" / "analysis"
NATIONAL_DIR = PROJECT_ROOT / "data" / "national"
UNIFIED_DB = PROJECT_ROOT / "data" / "unified.db"
LETPUB_DB = PROJECT_ROOT / "data" / "nsfc.db"
WEB_DIR = PROJECT_ROOT / "web"

# 优先合并库（三库合一，16.5 万条）；未构建合并时回退到本地采集库
DB_PATH = UNIFIED_DB if UNIFIED_DB.exists() else LETPUB_DB

# 生产静态托管目录（vite build 产物）；为空/缺失时首页给出明确「未构建」提示（V2-012）
STATIC_DIR = WEB_DIR / "dist"

MIME_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def configure(data_dir: Path | None = None, static_dir: Path | None = None) -> None:
    """重新指定数据与静态前端目录（演示包自包含运行时用）。"""
    global UNIFIED_DB, ANALYSIS_DIR, NATIONAL_DIR, STATIC_DIR, ARTIFACTS, DB_PATH
    if data_dir is not None:
        UNIFIED_DB = data_dir / "unified.db"
        ANALYSIS_DIR = data_dir / "analysis"
        NATIONAL_DIR = data_dir / "national"
        ARTIFACTS = [
            ("unified_db", UNIFIED_DB, "core"),
            ("analysis", ANALYSIS_DIR / "analysis.json", "core"),
            ("advanced", ANALYSIS_DIR / "analysis_advanced.json", "core"),
            ("national", NATIONAL_DIR / "national.json", "aux"),
            ("recent", NATIONAL_DIR / "recent.json", "aux"),
        ]
        DB_PATH = UNIFIED_DB if UNIFIED_DB.exists() else LETPUB_DB
    if static_dir is not None:
        STATIC_DIR = static_dir

PROJECT_COLS = [
    "grant_no", "title", "pi", "institution", "award_year", "close_year",
    "grant_type", "grant_type_raw", "division_name", "subject_code", "subject_l1", "subject_l2",
    "subject_l3", "subject_names_derived",
    "amount_wan", "amount_inferred", "begin_date", "end_date",
    "keywords", "abstract_zh", "has_report", "sources",
    "report_keywords", "report_url",
]


class ProductError(Exception):
    """分析产物缺失或损坏。缺文件不能以 200 空对象冒充有效分析（V2-011）。"""

    def __init__(self, kind: str, name: str, detail: str = "") -> None:
        self.kind = kind  # missing / corrupt
        self.name = name
        self.detail = detail
        super().__init__(f"{kind}: {name}")


# 产物清单：核心三件决定能否宣称 ready，其余缺失只降级为 partial
ARTIFACTS: list[tuple[str, Path, str]] = [
    ("unified_db", UNIFIED_DB, "core"),
    ("analysis", ANALYSIS_DIR / "analysis.json", "core"),
    ("advanced", ANALYSIS_DIR / "analysis_advanced.json", "core"),
    ("national", NATIONAL_DIR / "national.json", "aux"),
    ("recent", NATIONAL_DIR / "recent.json", "aux"),
]


def _is_valid_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (json.JSONDecodeError, OSError):
        return False


def snapshot_versions() -> dict[str, str]:
    """产物 sha256 前 12 位；按 (size, mtime) 缓存，避免每次请求重算 152MB。"""
    cache: dict[str, tuple[int, float, str]] = getattr(snapshot_versions, "_cache", {})
    out: dict[str, str] = {}
    for key, path, _tier in ARTIFACTS:
        if not path.exists():
            continue
        st = path.stat()
        hit = cache.get(str(path))
        if not hit or hit[0] != st.st_size or hit[1] != st.st_mtime:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            hit = (st.st_size, st.st_mtime, h.hexdigest()[:12])
            cache[str(path)] = hit
        out[key] = hit[2]
    snapshot_versions._cache = cache  # type: ignore[attr-defined]
    return out


def readiness() -> dict:
    """ready：核心齐备；partial：核心齐备但有辅助产物缺/损；unavailable：核心不齐。"""
    core = {k for k, _, tier in ARTIFACTS if tier == "core"}
    missing = [k for k, p, _t in ARTIFACTS if not p.exists()]
    corrupt = [k for k, p, _t in ARTIFACTS
               if p.exists() and p.suffix == ".json" and not _is_valid_json(p)]
    bad = set(missing) | set(corrupt)
    status = "ready" if not bad else ("unavailable" if bad & core else "partial")
    return {
        "status": status,
        "missing": missing,
        "corrupt": corrupt,
        "snapshot": snapshot_versions(),
        "hint": "partial/unavailable 时缺/损的产物页应显示未就绪，不要当空数据渲染",
    }


def load_json(name: str, directory: Path | None = None) -> dict:
    # directory 默认在调用时取当前全局：configure() 重绑目录后，函数默认参数
    # 不会跟随（V2-012 打包时踩到——演示包里 load_json 读到错误目录）
    d = ANALYSIS_DIR if directory is None else directory
    path = d / name
    if not path.exists():
        raise ProductError("missing", name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProductError("corrupt", name, str(e)) from e


# 旧 LetPub 库回退用（字段名与合并库不同）
LETPUB_COLS = ["grant_no AS grant_no", "title", "pi", "institution",
               "year AS award_year", "NULL AS close_year", "grant_type",
               "department AS division_name", "subject_code", "subject_l1",
               "subject_l2", "amount_wy AS amount_wan", "begin_date", "end_date",
               "keywords", "source AS sources"]


def query_projects(params: dict) -> dict:
    """分页 + 多条件过滤查询 unified_projects。"""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    unified = DB_PATH == UNIFIED_DB
    table = "unified_projects" if unified else "projects"
    cols = PROJECT_COLS if unified else LETPUB_COLS
    order_col = "award_year" if unified else "year"
    try:
        where = []
        args: list = []
        for key, col in (("q", None), ("year", "award_year"), ("dept", "division_name"),
                         ("inst", "institution"), ("type", "grant_type"),
                         ("subj", "subject_l1")):
            val = params.get(key)
            if not val:
                continue
            if key == "q":
                where.append("(title LIKE ? OR pi LIKE ? OR grant_no LIKE ? OR keywords LIKE ?)")
                args += [f"%{val}%"] * 4
            else:
                # 回退库的过滤列名不同
                if not unified and col == "award_year":
                    col = "year"
                if not unified and col == "division_name":
                    col = "department"
                where.append(f"{col} LIKE ?")
                args.append(f"%{val}%")
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        total = con.execute(f"SELECT COUNT(*) FROM {table}{clause}", args).fetchone()[0]
        page = max(1, int(params.get("page", 1)))
        size = min(100, max(10, int(params.get("size", 20))))
        offset = (page - 1) * size
        rows = con.execute(
            f"SELECT {','.join(cols)} FROM {table}{clause}"
            f" ORDER BY {order_col} DESC, grant_no LIMIT ? OFFSET ?",
            args + [size, offset],
        ).fetchall()
        return {
            "total": total,
            "page": page,
            "size": size,
            "rows": [dict(r) for r in rows],
        }
    finally:
        con.close()


def query_conflicts(params: dict) -> dict:
    """分页 + 按字段/分类过滤查询字段冲突。字段与分类分布始终给全量，供看板筛选。"""
    con = sqlite3.connect(str(UNIFIED_DB))
    con.row_factory = sqlite3.Row
    try:
        where = []
        args: list = []
        field = params.get("field")
        if field:
            where.append("field = ?")
            args.append(field)
        cls = params.get("cls")
        if cls:
            where.append("classification = ?")
            args.append(cls)
        q = params.get("q")
        if q:
            where.append("(grant_no LIKE ? OR selected LIKE ? OR alternatives LIKE ?)")
            args += [f"%{q}%"] * 3
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        total = con.execute(f"SELECT COUNT(*) FROM unified_conflicts{clause}", args).fetchone()[0]
        page = max(1, int(params.get("page", 1)))
        size = min(100, max(10, int(params.get("size", 20))))
        offset = (page - 1) * size
        rows = con.execute(
            f"SELECT grant_no, field, selected, selected_from, alternatives, classification"
            f" FROM unified_conflicts{clause} ORDER BY grant_no, field LIMIT ? OFFSET ?",
            args + [size, offset],
        ).fetchall()
        fields = [
            {"field": r[0], "count": r[1]}
            for r in con.execute("SELECT field, count(*) FROM unified_conflicts GROUP BY 1 ORDER BY 2 DESC")
        ]
        classes = [
            {"classification": r[0], "count": r[1]}
            for r in con.execute("SELECT classification, count(*) FROM unified_conflicts GROUP BY 1 ORDER BY 2 DESC")
        ]
        return {
            "total": total,
            "page": page,
            "size": size,
            "fields": fields,
            "classifications": classes,
            "rows": [dict(r) for r in rows],
        }
    finally:
        con.close()


def get_project(grant_no: str) -> dict:
    """单条项目完整记录 + 逐字段来源 + 该批准号的全部冲突。"""
    con = sqlite3.connect(str(UNIFIED_DB))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            f"SELECT {','.join(PROJECT_COLS)}, provenance, grant_type_raw, subject_names_derived"
            " FROM unified_projects WHERE grant_no = ?",
            (grant_no,),
        ).fetchone()
        if row is None:
            return {"found": False}
        d = dict(row)
        try:
            d["provenance"] = json.loads(d.get("provenance") or "{}")
        except json.JSONDecodeError:
            d["provenance"] = {}
        conflicts = [
            dict(c) for c in con.execute(
                "SELECT field, selected, selected_from, alternatives"
                " FROM unified_conflicts WHERE grant_no = ? ORDER BY field",
                (grant_no,),
            ).fetchall()
        ]
        for c in conflicts:
            try:
                c["alternatives"] = json.loads(c.get("alternatives") or "[]")
            except json.JSONDecodeError:
                c["alternatives"] = []
        return {"found": True, "project": d, "conflicts": conflicts}
    finally:
        con.close()


def pick_static(path: str) -> tuple[Path | None, str]:
    """把 URL 路径解析到 dist 内的文件。
    返回 (文件路径, 原因)。非法/不存在时回退 index.html（SPA）；dist 未构建时返回 None。
    """
    if not (STATIC_DIR / "index.html").is_file():
        return None, "unbuilt"
    rel = path.lstrip("/") or "index.html"
    candidate = (STATIC_DIR / rel).resolve()
    root = STATIC_DIR.resolve()
    # 防目录穿越：必须仍在 dist 内
    if not str(candidate).startswith(str(root) + os.sep) or not candidate.is_file():
        return STATIC_DIR / "index.html", "fallback"
    return candidate, "file"


UNBUILT_HTML = """<!doctype html><meta charset="utf-8">
<h1>前端未构建</h1>
<p>当前静态目录没有 dist 产物。在仓库 web/ 目录执行 <code>npm run build</code>，
或检查启动脚本的 --static-dir 指向。</p>
<p>API 仍可用：<code>/api/health</code>、<code>/api/analysis</code> 等。</p>
""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload, ctype: str = "application/json") -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if not isinstance(payload, bytes) else payload
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        try:
            if path == "/api/analysis":
                self._send(200, load_json("analysis.json"))
            elif path == "/api/analysis/advanced":
                self._send(200, load_json("analysis_advanced.json"))
            elif path == "/api/national":
                # 门户公开聚合（1986–2025 全量口径，与本地行数据同源）
                self._send(200, load_json("national.json", NATIONAL_DIR))
            elif path == "/api/recent":
                # 年度报告口径（2022–2026 申请/资助/资助率/经费）
                self._send(200, load_json("recent.json", NATIONAL_DIR))
            elif path == "/api/projects":
                self._send(200, query_projects(params))
            elif path == "/api/conflicts":
                if UNIFIED_DB.exists():
                    self._send(200, query_conflicts(params))
                else:
                    self._send(503, {"error": "合并库未构建：先运行 python -m merge.build",
                                     "kind": "missing", "missing": ["unified_db"]})
            elif path.startswith("/api/project/"):
                if UNIFIED_DB.exists():
                    no = urllib.parse.unquote(path[len("/api/project/"):])
                    self._send(200, get_project(no))
                else:
                    self._send(503, {"error": "合并库未构建：先运行 python -m merge.build",
                                     "kind": "missing", "missing": ["unified_db"]})
            elif path == "/api/health":
                r = readiness()
                code = 200 if r["status"] == "ready" else 503
                self._send(code, r)
            elif path.startswith("/api/"):
                self._send(404, {"error": f"not found: {path}"})
            else:
                # 生产静态托管：非 API 路径服务 dist（V2-012）
                target, why = pick_static(path)
                if target is None:
                    self._send(503, UNBUILT_HTML, ctype="text/html")
                else:
                    self._send_file(target)
        except ProductError as e:
            self._send(503, {
                "error": f"产物未就绪：{e.name}（{e.kind}）",
                "kind": e.kind,
                "missing": [e.name] if e.kind == "missing" else [],
                "corrupt": [e.name] if e.kind == "corrupt" else [],
                "detail": e.detail,
            })
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def log_message(self, *args) -> None:
        pass  # 静默，避免刷屏


def default_run_dirs(here: Path) -> tuple[Path | None, Path | None]:
    """无显式参数时的目录解析（V2R2-005）：serve_api.py 同级同时存在
    data/unified.db 与 dist/（演示包自包含布局）时用它，否则返回 None
    沿用模块级仓库默认值——包内裸跑不能隐式落到开发目录然后全 503。"""
    if (here / "data" / "unified.db").exists() and (here / "dist" / "index.html").is_file():
        return here / "data", here / "dist"
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data-dir", default=None, help="数据目录（含 unified.db/analysis/national；默认仓库 data/）")
    ap.add_argument("--static-dir", default=None, help="前端 dist 目录；默认仓库 web/dist")
    args = ap.parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else None
    static_dir = Path(args.static_dir) if args.static_dir else None
    if data_dir is None and static_dir is None:
        data_dir, static_dir = default_run_dirs(Path(__file__).resolve().parent)
    if data_dir is not None or static_dir is not None:
        configure(data_dir, static_dir)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    base = f"http://127.0.0.1:{args.port}"
    print(f"演示服务: {base}/  （dist: {STATIC_DIR}）")
    print(f"  /api/health            就绪状态（ready/partial/unavailable）+ 产物快照哈希")
    print(f"  /api/analysis          分析摘要（基础维度）")
    print(f"  /api/analysis/advanced 交叉透视与分布（看板交互）")
    print(f"  /api/national          门户全量聚合（1986–2025）")
    print(f"  /api/recent            年度报告口径（2022–2026 申请/资助率）")
    print(f"  /api/projects?q=&year=&dept=&inst=&type=&subj=&page=1&size=20")
    print(f"  /api/conflicts?field=&cls=&q=&page=1&size=20")
    print(f"  /api/project/12345678  单条项目 + 逐字段来源 + 冲突")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
