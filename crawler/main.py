# -*- coding: utf-8 -*-
"""采集器 CLI 入口。

用法：
  python -m crawler.main fetch --dept G --year 2015          # 抓取「管理科学部 2015 年」全部分页
  python -m crawler.main fetch --keyword 自然语言处理         # 关键词查询
  python -m crawler.main status                              # 查看库内统计
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from .store import Store
from .sharder import (
    Shard,
    generate_shards,
    load_subject_tree,
    run_shards,
)
from .sources.letpub import (
    DEPARTMENTS,
    LetPubClient,
    LetPubConfig,
    LetPubError,
    MAX_PAGES_PER_QUERY,
    PAGE_SIZE,
    parse_match_info,
    parse_page,
)

logger = logging.getLogger("atria.crawler")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def build_query(args: argparse.Namespace) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if args.year:
        query["year"] = args.year
    if args.dept:
        query["dept"] = args.dept
    if args.subject:
        query["subject_l1"] = args.subject
    if getattr(args, "l2", None):
        # 5 位二级代码（如 G0215）：其一级前缀由代码本身决定，
        # 用于补采 2019 学科树里已退役、但目标年份仍在使用的二级代码。
        query["subject_l1"] = args.l2[:3]
        query["subject_l2"] = args.l2
    if args.company:
        query["company"] = args.company
    if args.keyword:
        query["keyword"] = args.keyword
    return query


def cmd_fetch(args: argparse.Namespace, store: Store) -> int:
    query = build_query(args)
    if not query:
        logger.error("必须至少指定一个查询条件（--year/--dept/--subject/--company/--keyword）")
        return 2

    client = LetPubClient(LetPubConfig(rate_limit_sec=args.rate_limit))
    shard = {
        "source": "letpub", "year": query.get("year"), "dept": query.get("dept"),
        "subject": query.get("subject_l2") or query.get("subject_l1"),
        "company": query.get("company"),
        "keyword": query.get("keyword"),
    }
    desc = " × ".join(str(v) for v in shard.values() if v)
    logger.info("开始抓取分片: %s", desc or "(无条件)")

    store.mark_shard(shard, status="running")
    total_records: list[dict[str, Any]] = []
    seen_nos: set[str] = set()
    match_info: dict[str, int] = {}
    last_page_nos: set[str] = set()  # 上一页编号集合，用于检测服务端截断（重复页）

    def append_page(records: list[dict[str, Any]]) -> None:
        for r in records:
            if r["project_no"] not in seen_nos:
                seen_nos.add(r["project_no"])
                total_records.append(r)

    try:
        # 第 1 页：定位匹配规模
        html = client.fetch_page(query, page=1)
        match_info = parse_match_info(html)
        has_table = 'class="table_yjfx"' in html
        logger.info(
            "匹配 %s 条（共 %s 页，最多显示 %d 页）",
            f"{match_info['total']:,}" if match_info["total"] else "0",
            match_info["total_pages"] or "?", match_info["max_pages"],
        )
        if not has_table:
            logger.warning("该查询无结果")
        else:
            append_page(parse_page(html))
            logger.info("第 1 页: 累计去重 %d 条", len(total_records))
            # 后续页：上限 = min(真实页数, 显示上限)
            last_page = MAX_PAGES_PER_QUERY
            if match_info["total_pages"] > 0:
                last_page = min(match_info["total_pages"], match_info["max_pages"])
            for page in range(2, last_page + 1):
                html = client.fetch_page(query, page=page)
                records = parse_page(html)
                if not records:
                    # 空页可能是瞬时故障：重试一次再判定
                    logger.warning("第 %d 页解析为空，重试一次确认", page)
                    records = parse_page(client.fetch_page(query, page=page))
                    if not records:
                        logger.info("第 %d 页确认为空，结束", page)
                        break
                page_nos = {r["project_no"] for r in records}
                if page_nos and page_nos == last_page_nos:
                    # 服务端截断信号：本页与上一页完全相同
                    logger.info("第 %d 页与上一页重复（服务端截断），结束", page)
                    break
                last_page_nos = page_nos
                append_page(records)
                logger.info("第 %d/%d 页: 累计去重 %d 条", page, last_page, len(total_records))

    except LetPubError as e:
        logger.error("抓取失败: %s", e)
        store.mark_shard(shard, status="failed", fetched_count=len(total_records),
                         total_count=match_info.get("total", 0), error=str(e))
        return 1

    # 触顶判定：真实匹配数 > 实际采到数 → 该分片需要按一级学科/单位细分
    truncated = match_info.get("total", 0) > len(total_records)
    note = None
    if truncated:
        note = (f"truncated: 真实 {match_info['total']} 条 > 采到 {len(total_records)} 条，"
                "需按一级学科/单位细分分片")

    inserted, skipped = store.upsert_projects(total_records)
    store.mark_shard(shard, status="done", fetched_count=len(total_records),
                     total_count=match_info.get("total", 0), error=note)

    logger.info(
        "完成: 抓取 %d 条，入库新增 %d、跳过 %d；库内总计 %d 条%s",
        len(total_records), inserted, skipped, store.count_projects(),
        "（⚠ 触顶：该分片真实 %d 条，仅采到前 %d 条，需细分分片）"
        % (match_info.get("total", 0), len(total_records)) if truncated else "",
    )

    if args.dump:
        out = Path(args.dump)
        out.write_text(json.dumps(total_records, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.info("原始记录已写出: %s", out)
    return 0


def parse_years(args: argparse.Namespace) -> list[int]:
    """解析年份参数：--year 可重复，--years 支持「1997-2019」区间。"""
    years: list[int] = list(getattr(args, "year", []) or [])
    span = getattr(args, "years", None)
    if span:
        if "-" not in span:
            raise SystemExit(f"--years 格式应为「1997-2019」，收到 {span!r}")
        lo, hi = span.split("-", 1)
        years.extend(range(int(lo), int(hi) + 1))
    if not years:
        raise SystemExit("必须指定 --year 或 --years")
    return sorted(set(years))


def cmd_run(args: argparse.Namespace, store: Store) -> int:
    years = parse_years(args)
    tree = load_subject_tree()
    depts = args.depts.split(",") if args.depts else None
    shards = generate_shards(years, depts, tree)
    logger.info("生成 %d 个分片: 年份 %s, 学部 %s", len(shards), years, depts or "全部")

    client = LetPubClient(LetPubConfig(rate_limit_sec=args.rate_limit))
    fetched, skipped, failed = run_shards(store, client, shards, tree)

    logger.info(
        "调度完成: 采 %d 条，跳过 %d 个已完成分片，失败 %d 个；库内总计 %d 条",
        fetched, skipped, failed, store.count_projects(),
    )
    return 1 if failed else 0


def cmd_status(args: argparse.Namespace, store: Store) -> int:
    total = store.count_projects()
    print(f"库内项目总数: {total}")
    print("按年份分布:")
    for year, count in store.count_by_year():
        print(f"  {year}: {count}")
    rows = store.list_shards(limit=args.limit)
    print(f"分片记录（最近 {len(rows)} 条）:")
    for r in rows:
        print(f"  [{r['status']}] {r['source']} year={r['year']} dept={r['dept']} "
              f"subject={r['subject']} company={r['company']} keyword={r['keyword']} "
              f"fetched={r['fetched_count']}/{r['total_count']}"
              + (f" err={r['error']}" if r["error"] else ""))
    return 0


def cmd_departments(args: argparse.Namespace, store: Store) -> int:
    print("LetPub 学部代码（实测自搜索表单）:")
    for code, name in DEPARTMENTS.items():
        print(f"  {code}: {name}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="atria.crawler", description="国自然项目采集器")
    parser.add_argument("--db", default=None, help="SQLite 路径（默认 data/nsfc.db）")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="抓取一个查询分片")
    p_fetch.add_argument("--year", type=int, default=None)
    p_fetch.add_argument("--dept", default=None, help="学部代码（A-H/L，见 departments）")
    p_fetch.add_argument("--subject", default=None, help="一级学科代码（如 F01）")
    p_fetch.add_argument("--l2", default=None,
                         help="二级学科代码（如 G0215），用于补采学科树外已退役代码")
    p_fetch.add_argument("--company", default=None, help="依托单位")
    p_fetch.add_argument("--keyword", default=None, help="关键词")
    p_fetch.add_argument("--rate-limit", type=float, default=1.5, help="请求间隔秒数")
    p_fetch.add_argument("--dump", default=None, help="把原始记录导出为 JSON 文件")

    p_run = sub.add_parser("run", help="批量调度分片（年份×学部，触顶自动细分）")
    p_run.add_argument("--year", action="append", type=int, default=[],
                       help="单年（可重复，如 --year 2015 --year 2016）")
    p_run.add_argument("--years", default=None, help="年份区间，如 --years 1997-2019")
    p_run.add_argument("--depts", default=None, help="学部代码逗号分隔，如 A,B,C")
    p_run.add_argument("--rate-limit", type=float, default=2.0, help="请求间隔秒数")

    p_status = sub.add_parser("status", help="查看库内统计与分片状态")
    p_status.add_argument("--limit", type=int, default=20)

    sub.add_parser("departments", help="列出学部代码")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    store = Store(args.db) if args.db else Store()
    try:
        if args.command == "fetch":
            return cmd_fetch(args, store)
        if args.command == "run":
            return cmd_run(args, store)
        if args.command == "status":
            return cmd_status(args, store)
        if args.command == "departments":
            return cmd_departments(args, store)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
