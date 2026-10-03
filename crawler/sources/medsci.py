# -*- coding: utf-8 -*-
"""MedSci 数据源（补充源，覆盖 2022–2024，LetPub 无此段数据）。

已核验的接口事实（2026-10-02 实测）：
- 端点：GET https://www.medsci.cn/sci/nsfc.do?country=ZH&date_begin=Y&date_end=Y&txtitle=关键词&page=N&sort_type=3
- 数据在页面 JS 变量 nsfcPageData 里，Java DTO toString 格式
- 未登录每查询上限 20 条（data-total 恒为 20；每页 10 条，page=3 起与 page=2 重复 = 截断）
- 字段大面积稀疏：projectName/year/begindate 100%，projectClassname 70%，projectUni 40%，
  projectPi 30%，projectNo 仅 10%，classname(学部) 0%，cost 10%，keywords 0%
- projectid（内部 ID）100% 有值 → 作 MedSci 内部去重键；projectNo 缺失时兜底为 medsci:{projectid}
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.medsci.cn/sci/nsfc.do"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

PAGE_SIZE = 10
MAX_PAGES_PER_QUERY = 2  # 未登录上限 20 条 = 2 页（page=3 起与 page=2 重复）
MAX_TOTAL_PER_QUERY = 20

# nsfcPageData 里的 DTO 记录正则：抓字段名=值
_DTO_RE = re.compile(r"GetportalEsMedsciNsfcPageResponseDTO\((.*?)\)\s*[,\]]", re.S)
_FIELD_RE = re.compile(r"(\w+)=([^,]*?)(?=,\s*\w+=|\s*$)")


class MedSciError(Exception):
    """MedSci 采集异常。"""


@dataclass
class MedSciConfig:
    rate_limit_sec: float = 2.0
    max_retries: int = 3
    timeout_sec: int = 30
    proxy: Optional[dict[str, str]] = field(default=None, repr=False)


class MedSciClient:
    """MedSci 搜索客户端。"""

    def __init__(self, config: Optional[MedSciConfig] = None) -> None:
        self.cfg = config or MedSciConfig()
        self._last_request_time = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        if self.cfg.proxy:
            self._session.proxies.update(self.cfg.proxy)

    def fetch_page(self, query: dict[str, Any], page: int = 1) -> str:
        """抓取单页 HTML。query 支持 year/year_from/year_to/keyword/institution。"""
        year = query.get("year")
        params = {
            "country": "ZH",
            "date_begin": str(query.get("year_from", year or "")),
            "date_end": str(query.get("year_to", year or "")),
            "txtitle": str(query.get("keyword") or ""),
            "page": str(page),
            "sort_type": "3",
        }
        # 单位检索：MedSci 用 txtitle 做关键词，单位无独立字段，并入关键词
        if query.get("institution"):
            params["txtitle"] = str(query["institution"])

        last_err: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_retries + 1):
            elapsed = time.time() - self._last_request_time
            wait = self.cfg.rate_limit_sec - elapsed
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self._session.get(SEARCH_URL, params=params,
                                         timeout=self.cfg.timeout_sec)
                self._last_request_time = time.time()
                resp.encoding = "utf-8"
                if resp.status_code != 200:
                    raise MedSciError(f"HTTP {resp.status_code}")
                return resp.text
            except requests.RequestException as e:
                last_err = e
                backoff = 2.0 ** attempt
                logger.warning("MedSci 请求失败（%.1fs 后重试）: %s", backoff, e)
                time.sleep(backoff)
        raise MedSciError(f"MedSci 请求重试 {self.cfg.max_retries} 次后仍失败: {last_err}")


def _parse_dto_fields(body: str) -> dict[str, str]:
    """解析单条 DTO 的「字段=值」为字典。"""
    rec: dict[str, str] = {}
    for name, value in _FIELD_RE.findall(body):
        value = value.strip()
        if value.startswith(" ") or value == "":
            continue
        rec[name] = value
    return rec


def _clean(value: Optional[str]) -> Optional[str]:
    """Java DTO 的 null / 空串 / 「暂无数据」统一归一化为 None。"""
    if value is None:
        return None
    value = value.strip()
    if value in ("", "null", "暂无数据"):
        return None
    return value


def _norm_date(value: Optional[str]) -> Optional[str]:
    """MedSci 日期格式 202401 → 2024-01。"""
    value = _clean(value)
    if value and len(value) == 6 and value.isdigit():
        return f"{value[:4]}-{value[4:]}"
    return value


def parse_page(html: str) -> list[dict[str, Any]]:
    """解析 nsfcPageData，返回对齐 projects 表的记录。

    projectNo 仅 10% 有值；缺失时兜底 medsci:{projectid}，保证主键非空。
    """
    records: list[dict[str, Any]] = []
    for m in _DTO_RE.finditer(html):
        fields = _parse_dto_fields(m.group(1))
        projectid = _clean(fields.get("projectid"))
        project_no = _clean(fields.get("projectNo"))
        if projectid is None and project_no is None:
            continue  # 无任何标识，丢弃
        try:
            year = int(_clean(fields.get("year")) or 0) or None
        except (TypeError, ValueError):
            year = None
        try:
            cost = float(_clean(fields.get("cost")) or 0) or None
        except (TypeError, ValueError):
            cost = None
        records.append({
            "project_no": project_no or f"medsci:{projectid}",
            "title": _clean(fields.get("projectName")),
            "pi": _clean(fields.get("projectPi")),
            "institution": _clean(fields.get("projectUni")),
            "year": year,
            "grant_type": _clean(fields.get("projectClassname")),
            "department": _clean(fields.get("classname")),
            "subject_l1": "", "subject_l2": "", "subject_l3": "",
            "subject_code": "",
            "amount_wy": cost,
            "begin_date": _norm_date(fields.get("begindate")),
            "end_date": _norm_date(fields.get("enddate")),
            "keywords": "",
            "source": "medsci",
        })
    return records


def parse_total(html: str) -> int:
    """解析 data-total（未登录恒 ≤20）。"""
    m = re.search(r'data-total\s*=\s*["\']?(\d+)', html)
    if m:
        return min(int(m.group(1)), MAX_TOTAL_PER_QUERY)
    m = re.search(r'total["\']?\s*[:=]\s*["\']?(\d+)', html)
    if m:
        return min(int(m.group(1)), MAX_TOTAL_PER_QUERY)
    return 0
