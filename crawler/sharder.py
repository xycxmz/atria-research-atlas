# -*- coding: utf-8 -*-
"""分片调度器：生成分片队列、触顶自动细分、断点续传。

已核验的分片策略（2026-10-02 实测）：
- 1997–2019：year × 学部 × 一级学科（学科搜索有效）；单片 >200 条时按二级→三级递归细分
- 2020–2021：学科参数返回 0 条（失效），只能走「学部 × 单位」分片（见 split_by_company）
- 单查上限 20 页 × 10 条 = 200 条

学科参数必须传代码（G01/G0101/G010101），传名称会触发「暂不支持按学科搜索」。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from .sources.letpub import (
    LetPubClient,
    LetPubError,
    MAX_PAGES_PER_QUERY,
    PAGE_SIZE,
    parse_match_info,
    parse_page,
)
from .store import Store

logger = logging.getLogger(__name__)

CAP_PER_QUERY = MAX_PAGES_PER_QUERY * PAGE_SIZE  # 200

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUBJECT_TREE_PATH = PROJECT_ROOT / "data" / "subjects_tree.json"


def load_subject_tree(path: Path = SUBJECT_TREE_PATH) -> dict[str, Any]:
    """加载学科树（data/subjects_tree.json）。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)["depts"]


@dataclass
class Shard:
    """单个采集分片。subject_* 存学科代码（G01/G0101/G010101），非名称。"""
    year: int
    dept: str
    subject_l1: str = ""
    subject_l2: str = ""
    subject_l3: str = ""
    company: str = ""
    keyword: str = ""
    source: str = "letpub"

    @property
    def level(self) -> int:
        """0=学部级，1/2/3=一级/二级/三级学科。"""
        if self.subject_l3:
            return 3
        if self.subject_l2:
            return 2
        if self.subject_l1:
            return 1
        return 0

    def to_query(self) -> dict[str, Any]:
        q: dict[str, Any] = {"year": self.year, "dept": self.dept}
        if self.subject_l1:
            q["subject_l1"] = self.subject_l1
        if self.subject_l2:
            q["subject_l2"] = self.subject_l2
        if self.subject_l3:
            q["subject_l3"] = self.subject_l3
        if self.company:
            q["company"] = self.company
        if self.keyword:
            q["keyword"] = self.keyword
        return q

    def to_store_dict(self) -> dict[str, Any]:
        # subject 必须取最细级别的学科代码：二级分片 G0102 的键应为 "G0102"，
        # 不能取 subject_l1（"G01"），否则与父级一级分片键冲突，
        # 导致同父级下的子分片相互误命中、被断点续传错误跳过。
        return {
            "source": self.source, "year": self.year, "dept": self.dept,
            "subject": self.subject_l3 or self.subject_l2 or self.subject_l1 or "",
            "company": self.company, "keyword": self.keyword,
        }

    def describe(self) -> str:
        parts = [f"{self.year}", self.dept]
        if self.subject_l1:
            parts.append(self.subject_l1)
        if self.subject_l2:
            parts.append(self.subject_l2)
        if self.subject_l3:
            parts.append(self.subject_l3)
        if self.company:
            parts.append(f"@{self.company}")
        return " × ".join(parts)


@dataclass
class RunResult:
    shard: Shard
    status: str               # done / skipped / failed / truncated / split
    fetched: int = 0
    total: int = 0
    error: Optional[str] = None
    children: list["RunResult"] = field(default_factory=list)

    @property
    def all_fetched(self) -> int:
        """含子分片的总采条数。"""
        return self.fetched + sum(c.all_fetched for c in self.children)


# ----------------------------------------------------------------------
# 分片生成
# ----------------------------------------------------------------------
def generate_shards(years: list[int], depts: Optional[list[str]] = None,
                    tree: Optional[dict[str, Any]] = None) -> list[Shard]:
    """生成分片队列。

    1997–2019：year × 学部（不绑定学科，由 run_shard 触顶时自动细分到一级学科）。
    2020–2021：同上，但学科参数失效，需通过 split_by_company 走单位维度
    （run_shard 检测到 total>0 但按学科细分无效时，会回退到单位分片）。
    """
    if tree is None:
        tree = load_subject_tree()
    shards: list[Shard] = []
    for year in years:
        for dept in (depts or list(tree.keys())):
            if dept not in tree:
                logger.warning("未知学部 %s，跳过", dept)
                continue
            shards.append(Shard(year=year, dept=dept))
    return shards


def split_shard(shard: Shard, tree: dict[str, Any]) -> list[Shard]:
    """将触顶分片按下一级学科拆分。无法拆分时返回空列表。"""
    dept = tree.get(shard.dept)
    if dept is None:
        return []
    try:
        if shard.level == 0:
            # 学部级 → 各一级学科
            return [Shard(year=shard.year, dept=shard.dept, subject_l1=code)
                    for code in sorted(dept.keys())]
        if shard.level == 1:
            l1 = dept.get(shard.subject_l1, {})
            l2s = l1.get("l2", {}) if isinstance(l1, dict) else {}
            return [Shard(year=shard.year, dept=shard.dept, subject_l1=shard.subject_l1,
                          subject_l2=code) for code in sorted(l2s.keys())]
        if shard.level == 2:
            l1 = dept.get(shard.subject_l1, {})
            l2 = (l1.get("l2", {}) if isinstance(l1, dict) else {}).get(shard.subject_l2, {})
            l3s = l2.get("l3", {}) if isinstance(l2, dict) else {}
            return [Shard(year=shard.year, dept=shard.dept, subject_l1=shard.subject_l1,
                          subject_l2=shard.subject_l2, subject_l3=code)
                    for code in sorted(l3s.keys())]
    except (AttributeError, TypeError) as e:
        logger.warning("学科树结构异常，无法细分 %s: %s", shard.describe(), e)
    return []


# ----------------------------------------------------------------------
# 单分片执行（含触顶细分与断点续传）
# ----------------------------------------------------------------------
def run_shard(store: Store, client: LetPubClient, shard: Shard,
              tree: Optional[dict[str, Any]] = None,
              max_level: int = 3) -> RunResult:
    """执行单个分片：抓取、落库；触顶时自动细分递归；已完成则跳过（断点续传）。"""
    if tree is None:
        tree = load_subject_tree()
    result = RunResult(shard=shard, status="done")

    # 断点续传：已完成 → 跳过。触顶分片记录的 status 是 "truncated"（非 done），
    # 因此不会被跳过，重跑时会重新探查并尝试补采。
    if store.get_shard_status(shard.to_store_dict()) == "done":
        result.status = "skipped"
        # 被跳过的子分片仍要把它历史采到的条数带回父分片聚合，
        # 否则父分片（如 G01）在断点续传后统计会凭空少掉已跳过子分片的量。
        row = store.get_shard_row(shard.to_store_dict())
        result.fetched = row["fetched_count"] if row else 0
        result.total = row["total_count"] if row else 0
        logger.info("跳过已完成分片: %s（历史采 %d 条）", shard.describe(), result.fetched)
        return result

    store.mark_shard(shard.to_store_dict(), status="running")
    query = shard.to_query()

    try:
        # 先探查第 1 页：拿真实匹配总数，决定「直接抓取」还是「触顶细分」
        html = client.fetch_page(query, page=1)
        info = parse_match_info(html)
        total = info["total"]
    except LetPubError as e:
        result.status = "failed"
        result.error = str(e)
        store.mark_shard(shard.to_store_dict(), status="failed", error=str(e))
        logger.error("分片失败: %s (%s)", shard.describe(), e)
        return result

    result.total = total

    # 触顶且可细分：只保留探查到的记录，直接拆分给子分片（省下 19 页重复抓取）
    children = split_shard(shard, tree) if shard.level < max_level else []
    if total > CAP_PER_QUERY and children:
        probe_records = parse_page(html)
        result.fetched = len(probe_records)
        store.upsert_projects(probe_records)
        logger.info("%s: 真实 %d 条 > %d 上限，细分为 %d 个子分片（探查页 %d 条先入库）",
                    shard.describe(), total, CAP_PER_QUERY, len(children), len(probe_records))
        store.mark_shard(shard.to_store_dict(), status="split",
                         fetched_count=result.fetched, total_count=total,
                         error=f"split: 细分为 {len(children)} 个 {shard.level + 1} 级子分片")
        result.status = "split"
        for child in children:
            result.children.append(run_shard(store, client, child, tree, max_level))
        _aggregate_to_parent(store, shard, result)
        return result

    # 正常抓取（含「触顶但无法再细分」的情况，抓满 20 页并标记缺口）
    try:
        records, total = _crawl_pages(store, client, query, shard, first_html=html, first_info=info)
    except LetPubError as e:
        result.status = "failed"
        result.error = str(e)
        store.mark_shard(shard.to_store_dict(), status="failed", error=str(e))
        logger.error("分片失败: %s (%s)", shard.describe(), e)
        return result

    result.total = total
    result.fetched = len(records)
    inserted, _ = store.upsert_projects(records)

    note = None
    if total > result.fetched:
        note = (f"truncated: 真实 {total} 条 > 采到 {result.fetched} 条，"
                "已达最细学科级，缺口留待单位维度补采")
        result.status = "truncated"
        logger.warning("%s: 触顶且无法细分（真实 %d 条，仅采 %d 条）",
                       shard.describe(), total, result.fetched)

    store.mark_shard(shard.to_store_dict(), status=result.status,
                     fetched_count=result.fetched, total_count=total, error=note)
    logger.info("完成 %s: 采 %d 条（真实 %d），入库 %d",
                shard.describe(), result.fetched, total, inserted)
    return result


def _crawl_pages(store: Store, client: LetPubClient, query: dict[str, Any],
                 shard: Shard, first_html: Optional[str] = None,
                 first_info: Optional[dict[str, int]] = None
                 ) -> tuple[list[dict[str, Any]], int]:
    """翻页抓取单个查询，返回 (记录列表, 真实匹配总数)。

    first_html/first_info 可传入已抓取的第 1 页，避免重复请求。
    """
    if first_html is not None and first_info is not None:
        html, info = first_html, first_info
    else:
        html = client.fetch_page(query, page=1)
        info = parse_match_info(html)
    total = info["total"]
    if total == 0 and 'class="table_yjfx"' not in html:
        return [], 0

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_nos: set[str] = set()

    def append(recs: list[dict[str, Any]]) -> None:
        for r in recs:
            if r["project_no"] not in seen:
                seen.add(r["project_no"])
                records.append(r)

    append(parse_page(html))
    last_nos = set(seen)

    last_page = MAX_PAGES_PER_QUERY
    if info["total_pages"] > 0:
        last_page = min(info["total_pages"], info["max_pages"])
    for page in range(2, last_page + 1):
        html = client.fetch_page(query, page=page)
        page_recs = parse_page(html)
        if not page_recs:
            logger.warning("%s 第 %d 页为空，重试一次", shard.describe(), page)
            page_recs = parse_page(client.fetch_page(query, page=page))
            if not page_recs:
                logger.info("%s 第 %d 页确认空，停止", shard.describe(), page)
                break
        page_nos = {r["project_no"] for r in page_recs}
        if page_nos and page_nos == last_nos:
            logger.info("%s 第 %d 页与上页重复（服务端截断），停止", shard.describe(), page)
            break
        last_nos = page_nos
        append(page_recs)
    return records, total


def _aggregate_to_parent(store: Store, shard: Shard, result: RunResult) -> None:
    """把子分片结果汇总回父分片的 fetch_log。"""
    fetched = result.all_fetched
    note = None
    if result.total > fetched:
        note = (f"truncated: 真实 {result.total} 条 > 采到 {fetched} 条，"
                "已达最细学科级，缺口留待单位维度补采")
        result.status = "truncated"
    store.mark_shard(shard.to_store_dict(), status=result.status,
                     fetched_count=fetched, total_count=result.total, error=note)


def run_shards(store: Store, client: LetPubClient, shards: list[Shard],
               tree: Optional[dict[str, Any]] = None,
               max_level: int = 3) -> tuple[int, int, int]:
    """批量执行分片，返回 (总采条数, 跳过数, 失败数)。"""
    if tree is None:
        tree = load_subject_tree()
    total_fetched = skipped = failed = 0
    for shard in shards:
        res = run_shard(store, client, shard, tree, max_level)
        if res.status == "skipped":
            skipped += 1
        elif res.status == "failed":
            failed += 1
        total_fetched += res.all_fetched
    return total_fetched, skipped, failed
