# -*- coding: utf-8 -*-
"""pandas 分析：年份趋势 / 学部分布 / 单位排行 / 类型构成 / 学科分布 / 覆盖率。

默认读取 merge.build 产出的 data/unified.db（三库合并，16.5 万条）。
若合并库不存在，回退到只有 LetPub 采集的 data/nsfc.db，看板仍可运行。

用法：
  python -m analysis.analyze                     # 默认 data/unified.db
  python -m analysis.analyze --db data/nsfc.db  # 只分析本地采集库
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UNIFIED_DB = PROJECT_ROOT / "data" / "unified.db"
LETPUB_DB = PROJECT_ROOT / "data" / "nsfc.db"

# 官方基数。两套口径都要保留，不能相加：
#   portal  来自基金委知识门户（与本地行数据同源，1986-2023）
#   report  来自基金委年度报告/决算（2016-2026），部分年份与门户不一致
PORTAL_BASINES = PROJECT_ROOT / "data" / "external" / "kCApGaSG8Aij8zul-grok-workspace" / "src" / "data" / "nsfc_recovered.json"
REPORT_BASELINES = (
    PROJECT_ROOT / "data" / "external" / "NSFC_累计主数据_非全国全量_2026-10-02"
    / "nsfc_consolidated_data_2026-10-02" / "annual_baselines.json"
)

# 2019 版学科树以外的学部名（L = 联合基金项目，门户原样记作 L，不是学部）
NOT_A_DIVISION = {"L"}


def default_db() -> Path:
    if UNIFIED_DB.exists():
        return UNIFIED_DB
    logger.warning("data/unified.db 不存在，回退到 data/nsfc.db（仅本地 LetPub 采集）")
    return LETPUB_DB


def load_projects(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    try:
        if "unified_projects" in {
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }:
            df = pd.read_sql_query("SELECT * FROM unified_projects", con)
            df["amount_wan"] = pd.to_numeric(df["amount_wan"], errors="coerce")
            df["award_year"] = pd.to_numeric(df["award_year"], errors="coerce").astype("Int64")
            df["close_year"] = pd.to_numeric(df["close_year"], errors="coerce").astype("Int64")
        else:
            # 回退：旧 LetPub 库字段名不同，做一次对齐
            df = pd.read_sql_query("SELECT * FROM projects", con)
            df = df.rename(columns={"project_no": "grant_no", "year": "award_year",
                                    "amount_wy": "amount_wan", "department": "division_name"})
            df["amount_wan"] = pd.to_numeric(df["amount_wan"], errors="coerce")
            df["award_year"] = pd.to_numeric(df["award_year"], errors="coerce").astype("Int64")
            df["close_year"] = pd.Series([pd.NA] * len(df), dtype="Int64")
            df["sources"] = df["source"].map(lambda s: json.dumps([s], ensure_ascii=False))
    finally:
        con.close()
    return df


def _official_series() -> dict[str, dict[int, int]]:
    """读取两套官方年度批准数。缺文件返回空字典，覆盖率维度自动跳过。"""
    out: dict[str, dict[int, int]] = {}
    if PORTAL_BASINES.exists():
        bundle = json.loads(PORTAL_BASINES.read_text(encoding="utf-8"))
        out["portal"] = {int(r["year"]): int(r["count"]) for r in bundle.get("grants", [])}
    if REPORT_BASELINES.exists():
        bundle = json.loads(REPORT_BASELINES.read_text(encoding="utf-8"))
        rows = {}
        for r in bundle.get("rows", []):
            n = r.get("project_count")
            if isinstance(n, int) and r.get("scope") == "all_categories_approved":
                # 同一年若有多条不同口径，取精确计数那条
                if r.get("count_precision") == "exact" or r["funding_year"] not in rows:
                    rows[int(r["funding_year"])] = n
        out["report"] = rows
    return out


def coverage_report(df: pd.DataFrame) -> dict[str, object]:
    """各批准年度实采条数 vs 官方批准总数。

    分母同时给出门户与年报两套口径：门户序列与本地行数据同源（kd.nsfc.cn），
    年报序列覆盖更近的年份。二者部分年份不一致是口径差异，不是矛盾，
    页面上并列呈现，不取平均、不相加。
    """
    series = _official_series()
    have = df.dropna(subset=["award_year"])
    have = have.groupby(have["award_year"].astype(int))["grant_no"].nunique().to_dict()
    years = sorted(set(have) | {y for s in series.values() for y in s})
    by_year = []
    for y in years:
        entry: dict[str, object] = {"year": y, "have": have.get(y, 0)}
        for key, s in series.items():
            if y in s:
                total = s[y]
                entry[key] = total
                entry[f"rate_{key}"] = round(have.get(y, 0) / total, 4) if total else None
        by_year.append(entry)
    return {
        "by_year": by_year,
        "sources": list(series.keys()),
        "note": "门户序列与本地数据同源(kd.nsfc.cn)；年报序列来自基金委年度报告。两套口径不一致，不相加。",
    }


def source_report(df: pd.DataFrame) -> dict[str, object]:
    """来源构成。合并后一条记录可同时来自多个库，分别统计贡献数。"""
    counts: dict[str, int] = {}
    multi = 0
    for raw in df["sources"].dropna():
        try:
            tags = json.loads(raw) if isinstance(raw, str) else list(raw)
        except json.JSONDecodeError:
            continue
        if len(tags) > 1:
            multi += 1
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
    return {"contributions": counts, "multi_source_projects": multi}


def _rank_within_scope(groups: pd.DataFrame, scope_col: str, top_k: int,
                       scope_totals: pd.Series | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """先按范围分组排名，再取每范围 TopK（V2-003）。

    返回 (带 rank_in_scope 的 TopK 行, 每范围对账元数据)。对账字段：
    candidates 候选条数 / shown 已展示条数 / shown_count 已展示项目数 /
    other_count 未展示（「其他」）项目数 / total_count 该维度有值的项目数。
    传入 scope_totals（每范围全部项目数）时追加 unknown_count：
    该范围连维度取值都没有的项目数，使榜单可与范围总计对账。
    """
    ranked = groups.sort_values([scope_col, "count"], ascending=[True, False], kind="mergesort")
    ranked["rank_in_scope"] = ranked.groupby(scope_col).cumcount() + 1
    top = ranked[ranked["rank_in_scope"] <= top_k]
    shown_n = top.groupby(scope_col).size()
    shown_count = top.groupby(scope_col)["count"].sum()
    meta: list[dict[str, object]] = []
    for scope, g in ranked.groupby(scope_col):
        shown = int(shown_count.get(scope, 0))
        total = int(g["count"].sum())
        entry: dict[str, object] = {
            "scope": str(scope),
            "candidates": int(len(g)),
            "shown": int(shown_n.get(scope, 0)),
            "shown_count": shown,
            "other_count": total - shown,
            "total_count": total,
        }
        if scope_totals is not None:
            base = int(scope_totals.get(scope, 0))
            entry["unknown_count"] = base - total
        meta.append(entry)
    return top, meta


def analyze(df: pd.DataFrame) -> dict[str, object]:
    """全部维度分析，返回可直接 JSON 序列化的字典。"""
    result: dict[str, object] = {}
    result["meta"] = {
        "total_projects": int(len(df)),
        "year_min": int(df["award_year"].min()) if df["award_year"].notna().any() else None,
        "year_max": int(df["award_year"].max()) if df["award_year"].notna().any() else None,
        "close_year_max": int(df["close_year"].max()) if df["close_year"].notna().any() else None,
        "total_amount_wan": round(float(df["amount_wan"].sum(skipna=True)), 1),
        "distinct_institutions": int(df["institution"].nunique()),
        "distinct_pis": int(df["pi"].nunique()),
    }

    # 1. 批准年度趋势：立项数 + 资助金额
    awarded = df.dropna(subset=["award_year"])
    by_year = awarded.groupby(awarded["award_year"].astype(int)).agg(
        count=("grant_no", "size"),
        amount=("amount_wan", "sum"),
    ).reset_index()
    by_year = by_year.rename(columns={"award_year": "year"})
    by_year["amount"] = by_year["amount"].round(1)
    result["by_year"] = by_year.to_dict(orient="records")

    # 1b. 结题年度趋势（grok 门户库独有维度）
    closed = df.dropna(subset=["close_year"])
    closed = closed.groupby(closed["close_year"].astype(int)).agg(
        count=("grant_no", "size"),
    ).reset_index()
    closed = closed.rename(columns={"close_year": "year"})
    result["by_close_year"] = closed.to_dict(orient="records")

    # 2. 学部分布（L 不是学部，单独列出）
    #    valid_n = 金额非空的项目数：平均强度要用它做分母
    #    （V2-008：用全部项目数会把缺失金额当隐式零，拉低均值）
    div = df[df["division_name"].notna() & (df["division_name"] != "")]
    by_dept = div.groupby("division_name").agg(
        count=("grant_no", "size"),
        amount=("amount_wan", "sum"),
        valid_n=("amount_wan", "count"),
    ).sort_values("count", ascending=False).reset_index()
    by_dept["amount"] = by_dept["amount"].round(1)
    result["by_department"] = by_dept.to_dict(orient="records")

    # 3. 单位排行（Top 30）
    by_inst = df.groupby("institution").agg(
        count=("grant_no", "size"),
        amount=("amount_wan", "sum"),
    ).sort_values("count", ascending=False).head(30).reset_index()
    by_inst["amount"] = by_inst["amount"].round(1)
    result["top_institutions"] = by_inst.to_dict(orient="records")

    # 4. 项目类型构成
    by_type = df.groupby("grant_type").agg(
        count=("grant_no", "size"),
        amount=("amount_wan", "sum"),
    ).sort_values("count", ascending=False).reset_index()
    by_type["amount"] = by_type["amount"].round(1)
    result["by_grant_type"] = by_type.to_dict(orient="records")

    # 5. 一级学科分布：按学部分组排名，每学部取 Top 15
    #    （V2-003：此前全局 Top20 截断后再在前端按学部过滤，
    #     数理 L1 只剩 1 条，不是该学部真正的 Top15）
    l1 = df[df["subject_l1"].notna() & (df["subject_l1"] != "")]
    by_l1 = l1.groupby(["division_name", "subject_l1"]).agg(
        count=("grant_no", "size"),
    ).reset_index()
    by_l1, l1_meta = _rank_within_scope(by_l1, "division_name", 15,
                                        scope_totals=by_dept.set_index("division_name")["count"])
    result["top_subjects_l1"] = by_l1.to_dict(orient="records")
    result["top_subjects_l1_meta"] = l1_meta

    # 6. 数据来源构成
    result["by_source"] = source_report(df)

    # 7. 覆盖率（实采 vs 官方基数）
    result["coverage"] = coverage_report(df)
    return result


def analyze_advanced(df: pd.DataFrame) -> dict[str, object]:
    """看板交互分析：交叉透视、金额分布、学科下钻、年度环比。"""
    result: dict[str, object] = {}
    valid = df.dropna(subset=["award_year"]).copy()
    valid["award_year"] = valid["award_year"].astype(int)

    # 1. 学部 × 批准年度 立项数矩阵（堆叠柱状图 / 热力图）
    pivot = valid.pivot_table(
        index="division_name", columns="award_year", values="grant_no",
        aggfunc="count", fill_value=0,
    )
    result["dept_year_matrix"] = {
        "departments": pivot.index.tolist(),
        "years": [int(c) for c in pivot.columns],
        "counts": pivot.values.tolist(),
    }

    # 1b. 结题 × 批准年度矩阵（看结题进度）
    both = valid.dropna(subset=["close_year"]).copy()
    both["close_year"] = both["close_year"].astype(int)
    pivot2 = both.pivot_table(
        index="close_year", columns="award_year", values="grant_no",
        aggfunc="count", fill_value=0,
    )
    result["close_award_matrix"] = {
        "close_years": [int(r) for r in pivot2.index],
        "award_years": [int(c) for c in pivot2.columns],
        "counts": pivot2.values.tolist(),
    }

    # 2. 金额分布（项目级，直方图分箱，单位万元）
    #    分箱为左闭右开 [lo, hi)，标签与边界一致；尾箱用正无穷
    #    （V2-008：曾把 [0,20) 标 "≤20"，20 恰有 8,221 条被错分）
    amounts = df["amount_wan"].dropna()
    bins = [0, 20, 40, 60, 80, 100, 150, 200, 300, 500, float("inf")]
    labels = ["0-20", "20-40", "40-60", "60-80", "80-100",
              "100-150", "150-200", "200-300", "300-500", "500+"]
    binned = pd.cut(amounts, bins=bins, labels=labels,
                    right=False, include_lowest=True)
    dist = binned.value_counts().reindex(labels, fill_value=0)
    result["amount_distribution"] = {
        "bins": labels,
        "counts": [int(v) for v in dist.tolist()],
        "valid_n": int(len(amounts)),
        "note": "区间为左闭右开 [下限, 上限)；缺失金额不计入任何区间",
    }

    # 3. 二级学科：同样先按学部范围排名再取 Top 15（下钻用；仅 atria 库有学科名）
    #    （V2-003：此前全局 Top20 截断，学部筛选后小学部榜单不完整）
    sub = valid[valid["subject_l2"].notna() & (valid["subject_l2"] != "")]
    by_l2 = sub.groupby(["division_name", "subject_l1", "subject_l2"]).agg(
        count=("grant_no", "size"),
        amount=("amount_wan", "sum"),
    ).reset_index()
    valid_div = valid[valid["division_name"].notna() & (valid["division_name"] != "")]
    div_totals = valid_div.groupby("division_name")["grant_no"].size()
    by_l2, l2_meta = _rank_within_scope(by_l2, "division_name", 15, scope_totals=div_totals)
    by_l2["amount"] = by_l2["amount"].round(1)
    result["top_subjects_l2"] = by_l2.to_dict(orient="records")
    result["top_subjects_l2_meta"] = l2_meta

    # 4. 单位 × 学部 交叉 Top 15（每个单位的主导学部）
    inst_dept = valid.groupby(["institution", "division_name"]).agg(
        count=("grant_no", "size"),
    ).sort_values("count", ascending=False).head(15).reset_index()
    result["top_institution_dept"] = inst_dept.to_dict(orient="records")

    # 5. 年度环比（增长率，趋势图标注用）
    by_year = valid.groupby("award_year").agg(count=("grant_no", "size")).sort_index()
    by_year["yoy"] = by_year["count"].pct_change().round(4)
    result["year_yoy"] = [
        {"year": int(y), "count": int(r["count"]),
         "yoy": None if pd.isna(r["yoy"]) else round(float(r["yoy"]), 4)}
        for y, r in by_year.iterrows()
    ]

    # 6. 平均资助强度（万元/项，按年）
    strength = valid.groupby("award_year").agg(
        avg_amount=("amount_wan", "mean"),
        median_amount=("amount_wan", "median"),
    ).round(2)
    result["amount_strength"] = [
        {"year": int(y), "avg": float(r["avg_amount"]), "median": float(r["median_amount"])}
        for y, r in strength.iterrows()
    ]

    # 6b. 类型 × 资助强度（万元/项）：avg/median 对比 funding distribution
    typed = valid.dropna(subset=["amount_wan"])
    by_type = typed.groupby("grant_type").agg(
        count=("grant_no", "size"),
        avg=("amount_wan", "mean"),
        median=("amount_wan", "median"),
        total=("amount_wan", "sum"),
    ).round(2).sort_values("count", ascending=False)
    result["strength_by_type"] = [
        {"grant_type": t, "count": int(r["count"]), "avg": float(r["avg"]),
         "median": float(r["median"]), "total": float(r["total"])}
        for t, r in by_type.iterrows()
    ]

    # 7. 关键词词频：总榜 top N + 分学部 top N + 分年 top N
    #    关键词统一以 ';' 分隔；短于 2 字的碎片不计数
    result["keyword_freq"] = keyword_frequency(df, valid)

    # 8. 学部 × 类别交叉：青年/面上比反映学科人员年龄结构
    main_types = ["面上项目", "青年科学基金项目（C类）", "地区科学基金项目", "重点项目"]
    dt = valid[valid["grant_type"].isin(main_types)]
    pivot3 = dt.pivot_table(
        index="division_name", columns="grant_type", values="grant_no",
        aggfunc="count", fill_value=0,
    )
    # 保证列齐全（某个类别某学部可能为 0 导致缺列）
    for t in main_types:
        if t not in pivot3.columns:
            pivot3[t] = 0
    pivot3 = pivot3[main_types]
    youth_ratio = (pivot3["青年科学基金项目（C类）"] /
                   pivot3["面上项目"].replace(0, float("nan")))
    result["dept_type_matrix"] = {
        "departments": [str(d) for d in pivot3.index],
        "types": main_types,
        "counts": pivot3.values.tolist(),
        # 青年:面上比，>1 表示该学部青年项目多于面上
        "youth_ratio": [None if pd.isna(v) else round(float(v), 3) for v in youth_ratio.tolist()],
    }

    # 9. TOP 单位年度趋势（看头部单位的立项节奏，而非只看存量）
    inst_year = valid.pivot_table(
        index="institution", columns="award_year", values="grant_no",
        aggfunc="count", fill_value=0,
    )
    inst_year["__total"] = inst_year.sum(axis=1)
    top_insts = inst_year.sort_values("__total", ascending=False).head(10).drop(columns="__total")
    result["top_institution_years"] = {
        "institutions": top_insts.index.tolist(),
        "years": [int(c) for c in top_insts.columns],
        "counts": top_insts.values.tolist(),
    }
    return result


def keyword_frequency(df: pd.DataFrame, valid: pd.DataFrame, top_n: int = 40) -> dict[str, object]:
    """关键词词频。总榜 40，分学部与分批准年度各取 top 15。

    词频只统计有关键词的行，且每个词按 COUNT(DISTINCT 批准号) 计：
    同一项目内重复出现的词只计一次。分母是有关键词的项目数而非全库，
    所以份额要按「出现该词的项目数 / 有关键词项目数」理解。
    低覆盖年份（2023 仅 5 条、2024 为 0）只标缺测，不画趋势线。
    """
    from merge.build import _split_keywords

    def tokenize(series: pd.Series) -> dict[str, int]:
        freq: dict[str, int] = {}
        for raw in series.dropna():
            for w in _split_keywords(str(raw)):
                freq[w] = freq.get(w, 0) + 1
        return freq

    def top(series: pd.Series, n: int) -> list[dict[str, object]]:
        freq = tokenize(series)
        return [{"keyword": w, "count": c} for w, c in
                sorted(freq.items(), key=lambda kv: -kv[1])[:n]]

    kw = df["keywords"].dropna().astype(str)
    kw = kw[kw.str.strip() != ""]
    overall_total = len(kw)

    by_dept: list[dict[str, object]] = []
    for dept, grp in valid.groupby(valid["division_name"].fillna("(未分学部)")):
        series = grp["keywords"].dropna().astype(str)
        series = series[series.str.strip() != ""]
        if len(series) < 100:
            continue
        by_dept.append({"division_name": str(dept), "top": top(series, 15),
                        "keyworded_n": int(len(series))})

    by_year: list[dict[str, object]] = []
    for year in sorted(valid["award_year"].dropna().unique()):
        year_int = int(year)
        if year_int < 2015:
            continue
        grp = valid[valid["award_year"] == year]
        series = grp["keywords"].dropna().astype(str)
        series = series[series.str.strip() != ""]
        # 低覆盖年标缺测：词频不足支撑结论时返回空榜与实际 N
        by_year.append({
            "year": year_int,
            "keyworded_n": int(len(series)),
            "top": top(series, 15) if len(series) >= 100 else [],
            "sufficient": len(series) >= 100,
        })

    return {
        "overall": top(kw, top_n),
        "overall_rows": int(overall_total),
        "by_division": by_dept,
        "by_year": by_year,
    }


def export_csv(df: pd.DataFrame, outdir: Path) -> None:
    """导出常用 CSV。"""
    df.to_csv(outdir / "projects_all.csv", index=False, encoding="utf-8-sig")
    awarded = df.dropna(subset=["award_year"])
    pivot = awarded.pivot_table(
        index="institution", columns=awarded["award_year"].astype(int),
        values="grant_no", aggfunc="count", fill_value=0,
    )
    pivot.to_csv(outdir / "institution_year_matrix.csv", encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="国自然项目多维分析")
    parser.add_argument("--db", default=str(default_db()))
    parser.add_argument("--outdir", default=str(PROJECT_ROOT / "data" / "analysis"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = load_projects(Path(args.db))
    logger.info("载入 %d 条项目记录（%s）", len(df), args.db)
    if df.empty:
        logger.warning("库为空，无分析结果")
        return 0

    result = analyze(df)
    adv = analyze_advanced(df)
    json_path = outdir / "analysis.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    adv_path = outdir / "analysis_advanced.json"
    adv_path.write_text(json.dumps(adv, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("分析结果写出: %s / %s", json_path, adv_path)

    export_csv(df, outdir)
    logger.info("CSV 导出完成: %s", outdir)

    m = result["meta"]
    print(f"\n=== 分析摘要（{m['total_projects']:,} 条，{m['year_min']}–{m['year_max']}）===")
    print(f"总资助金额: {m['total_amount_wan']:,.1f} 万元")
    print(f"依托单位: {m['distinct_institutions']:,} 家 | 负责人: {m['distinct_pis']:,} 人")
    print("\n来源贡献:", result["by_source"]["contributions"],
          "| 多来源:", result["by_source"]["multi_source_projects"])
    print("\n学部分布:")
    for r in result["by_department"]:
        print(f"  {r['division_name']:12}: {r['count']:>6,} 条 | {r['amount']:>12,.1f} 万元")
    print("\n覆盖率（vs 门户基数）:")
    for r in result["coverage"]["by_year"]:
        if r.get("rate_portal") is not None and 2014 <= r["year"] <= 2025:
            print(f"  {r['year']}: {r['have']:>6,} / {r['portal']:>6,} = {r['rate_portal']:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
