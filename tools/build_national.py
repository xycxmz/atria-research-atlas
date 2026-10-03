# -*- coding: utf-8 -*-
"""全国聚合数据构建器：把两份官方口径聚合数据落到 data/national/，供看板读取。

两份数据口径互不相同，看板分页面呈现、不相加：

  national.json  基金委知识门户公开统计（kd.nsfc.cn），与本地行数据同源
                 1986–2023 资助分年、1987–2025 结题分年、2009–2023 分学部、
                 131 个二级学科累计、14 类别累计、成果分年
                 来源：grok 前端工程 zip 里 nsfc.json 为空，真实数据内联在
                 Vercel 构建产物中，已提取为 nsfc_recovered.json

  recent.json    集中接收 / 年度报告口径（申请数、资助数、资助率、经费）
                 2022–2026，分学部 × 3 类别（面上 / 青年 C / 地区）
                 来源：grok 前端 recent.ts，含官方原文出处与 derived/approx 标记

用法：
  python tools/build_national.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTERNAL = PROJECT_ROOT / "data" / "external"
PORTAL_JSON = EXTERNAL / "kCApGaSG8Aij8zul-grok-workspace" / "src" / "data" / "nsfc_recovered.json"
RECENT_TS = EXTERNAL / "kCApGaSG8Aij8zul-grok-workspace" / "src" / "data" / "recent.ts"
OUT_DIR = PROJECT_ROOT / "data" / "national"
WEB_DIR = PROJECT_ROOT / "web"
TMP_DIR = PROJECT_ROOT / "data" / "national_tmp"

# recent.ts 转成 JS 后要抓的导出名
RECENT_EXPORTS = ("RECENT_YEARS", "NATIONAL_HEADLINES", "PROGRAMS", "PROGRAM_YEARS")


def build_portal() -> dict:
    """门户聚合：校验结构后原样落盘。"""
    bundle = json.loads(PORTAL_JSON.read_bytes().decode("utf-8"))
    keys = {"snapshot", "source", "totals", "grants", "conclusions", "deptTotals",
            "yearDept", "yearType", "disciplines", "typeTotals", "resultsByYear"}
    missing = keys - set(bundle)
    if missing:
        raise SystemExit(f"门户聚合缺字段: {missing}")
    assert len({r["year"] for r in bundle["grants"]}) == len(bundle["grants"]), "资助分年有重复"
    return bundle


def build_recent() -> dict:
    """recent.ts 用 rolldown 打包成 CJS 求值，导出为 JSON。"""
    import tempfile

    tmp = TMP_DIR
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    script = (
        "const { build } = require('rolldown');\n"
        f"build({{ input: {str(RECENT_TS)!r}, output: {{ format: 'cjs', dir: {str(tmp)!r} }} }})"
        ".then(() => console.log('bundled')).catch(e => { console.error(e.message); process.exit(1); });\n"
    )
    subprocess.run(
        ["node", "-e", script], cwd=str(WEB_DIR), check=True,
        capture_output=True, text=True, encoding="utf-8",
    )

    js = (tmp / "recent.js").read_text(encoding="utf-8")
    # 求值打包产物（CJS module.exports），取出数据导出
    exports = ",".join(f"{name}: m.{name}" for name in RECENT_EXPORTS)
    probe = (
        f"const m = require({str(tmp / 'recent.js')!r});\n"
        f"const out = {{ {exports} }};\n"
        "for (const k of Object.keys(out)) if (out[k] === undefined) { console.error('missing ' + k); process.exit(1); }\n"
        "console.log(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        ["node", "-e", probe], cwd=str(WEB_DIR),
        capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        raise SystemExit(f"求值 recent.js 失败: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    shutil.rmtree(tmp)

    # 落盘前校验：申请数/资助数/经费都应该是非负数或 null
    def check_cell(c: dict, where: str) -> None:
        for k in ("apply", "funded", "fundingWan", "intensity"):
            v = c.get(k)
            if v is not None and v < 0:
                raise SystemExit(f"{where}.{k} 出现负数: {v}")

    for yr in data["RECENT_YEARS"]:
        for d in yr.get("depts", []):
            for kind in ("general", "youth", "regional"):
                if kind in d:
                    check_cell(d[kind], f"{yr['year']}.{d['dept']}.{kind}")
    return data


def main() -> int:
    if not PORTAL_JSON.exists():
        raise SystemExit(f"找不到门户聚合: {PORTAL_JSON}")
    if not RECENT_TS.exists():
        raise SystemExit(f"找不到 recent.ts: {RECENT_TS}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    portal = build_portal()
    (OUT_DIR / "national.json").write_text(
        json.dumps(portal, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"national.json   门户聚合 {portal['totals']['fundedProjects']:,} 累计立项 · "
          f"资助 {portal['grants'][0]['year']}–{portal['grants'][-1]['year']} · "
          f"结题 {portal['conclusions'][0]['year']}–{portal['conclusions'][-1]['year']} · "
          f"{len(portal['disciplines'])} 学科 · {len(portal['typeTotals'])} 类别")

    recent = build_recent()
    (OUT_DIR / "recent.json").write_text(
        json.dumps(recent, ensure_ascii=False, indent=1), encoding="utf-8")
    years = [y["year"] for y in recent["RECENT_YEARS"]]
    print(f"recent.json    报告口径 {years[0]}–{years[-1]} · "
          f"{len(recent['PROGRAMS'])} 类别序列 · 全国面上资助率 "
          f"{recent['NATIONAL_HEADLINES']['2023']['general']['funded'] / recent['NATIONAL_HEADLINES']['2023']['general']['apply']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
