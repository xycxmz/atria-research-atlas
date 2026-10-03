# -*- coding: utf-8 -*-
"""LetPub 数据源（主力源，覆盖 1997–2021）。

已核验的接口事实（2026-10-02 实测）：
- 端点：POST https://www.letpub.com.cn/nsfcfund_search.php?mode=advanced&datakind=list&currentpage={page}
- 必需 Headers：User-Agent、X-Requested-With: XMLHttpRequest、Referer
- 结果在 <table class="table_yjfx">，每个项目占 5 行：
  数据行(7列: 负责人/单位/金额/项目编号/项目类型/所属学部/批准年份)
  + 题目 + 学科分类(名称三级) + 学科代码(三级) + 执行时间
- 每页 10 条，单次查询上限 20 页 = 200 条（分页行显示「去 /20页」）
- 2020–2023 年不支持按学科/省份搜索，会返回「暂不支持按【学科】搜索」提示
- 列表页无关键词、无详情页链接 → keywords 字段留空
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.letpub.com.cn/nsfcfund_search.php"
FORM_REFERER = "https://www.letpub.com.cn/index.php?page=grant"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 学部代码 → 名称（实测自搜索表单 addcomment_s1 下拉）
DEPARTMENTS = {
    "A": "数理科学部",
    "B": "化学科学部",
    "C": "生命科学部",
    "D": "地球科学部",
    "E": "工程与材料科学部",
    "F": "信息科学部",
    "G": "管理科学部",
    "H": "医学科学部",
    "L": "其他学部",
}

# 单查上限：20 页 × 10 条/页
MAX_PAGES_PER_QUERY = 20
PAGE_SIZE = 10


class LetPubError(Exception):
    """LetPub 采集异常（如结构变更、学科搜索被禁）。"""


class LetPubRateLimit(LetPubError):
    """触发 IP 频率限制。调度层应退避等待后重试，而非立即放弃。"""


@dataclass
class LetPubConfig:
    """采集器运行参数。

    频率限制实测（2026-10-02）：约每 8 个请求触发一次 IP 封锁，与请求间隔关系
    不大（3s 间隔仍在第 9 个请求触发）；封锁 20 秒内恢复。故采用主动限流：
    每 proactive_every 个请求后主动等待 proactive_wait 秒，把被动触发变为主动规避。
    """
    rate_limit_sec: float = 2.0      # 相邻请求间隔下限
    proactive_every: int = 7         # 每 N 个请求主动等待一次（实测第 8 个触发，留 1 个余量）
    proactive_wait: float = 25.0     # 主动等待秒数（实测封锁 ≤20s 恢复，留 5s 余量）
    max_retries: int = 3             # 网络失败重试次数（指数退避）
    rate_limit_wait: float = 25.0    # 基础等待秒数（实测封锁 ≤20s 恢复，留 5s 余量）
    rate_limit_retries: int = 4      # 频率限制重试次数
    aimd_max_wait: float = 300.0     # 动态退避上限（深度惩罚期最多等 5 分钟）
    aimd_recover_every: int = 14     # 连续成功 N 次后动态等待值减半（≈2 个限流周期）
    timeout_sec: int = 30
    proxy: Optional[dict[str, str]] = field(default=None, repr=False)


class LetPubClient:
    """LetPub 搜索客户端：单页抓取 + 限速 + 指数退避重试。"""

    def __init__(self, config: Optional[LetPubConfig] = None) -> None:
        self.cfg = config or LetPubConfig()
        self._last_request_time = 0.0
        self._request_count = 0
        self._success_streak = 0          # 连续成功计数（用于动态退避的"减速恢复"）
        self._dynamic_wait = self.cfg.rate_limit_wait  # AIMD 动态等待值
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": FORM_REFERER,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        if self.cfg.proxy:
            self._session.proxies.update(self.cfg.proxy)

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        wait = self.cfg.rate_limit_sec - elapsed
        if wait > 0:
            time.sleep(wait)

    def fetch_page(self, query: dict[str, Any], page: int = 1) -> str:
        """抓取单页 HTML。query 为搜索条件（year/dept/subject/company/keyword 等）。

        - 网络错误：指数退避重试（max_retries 次）
        - 触发频率限制：等待 rate_limit_wait × 2^n 秒后重试（rate_limit_retries 次）
        - 其他反爬/限制提示：直接抛 LetPubError，由调度层决定降速或暂停
        """
        form = self._build_form(query, page)
        url = f"{SEARCH_URL}?mode=advanced&datakind=list&currentpage={page}"

        last_err: Optional[Exception] = None
        net_attempt = 0      # 网络错误计数（指数退避后重置需求见下）
        rate_attempt = 0     # 频率限制计数

        while True:
            # 主动限流：每 N 个请求后主动等待，规避 IP 封锁（proactive_every<=0 禁用）
            if (self.cfg.proactive_every > 0
                    and self._request_count > 0
                    and self._request_count % self.cfg.proactive_every == 0):
                logger.debug("主动限流：第 %d 个请求，等待 %.0fs",
                             self._request_count, self._dynamic_wait)
                time.sleep(self._dynamic_wait)
                self._last_request_time = 0.0  # 等待后重置间隔计时
            self._rate_limit()
            try:
                resp = self._session.post(url, data=form, timeout=self.cfg.timeout_sec)
                self._last_request_time = time.time()
                self._request_count += 1
                resp.encoding = "utf-8"
                html = resp.text
                self._check_anti_scrape(html)
                if resp.status_code != 200:
                    raise LetPubError(f"HTTP {resp.status_code}")
                # AIMD「减」：连续成功后缓慢回落动态等待值
                self._success_streak += 1
                if self._success_streak >= self.cfg.aimd_recover_every:
                    self._success_streak = 0
                    old = self._dynamic_wait
                    self._dynamic_wait = max(self.cfg.rate_limit_wait,
                                             self._dynamic_wait / 2)
                    if self._dynamic_wait != old:
                        logger.debug("连续成功，动态退避 %.0fs → %.0fs", old, self._dynamic_wait)
                return html
            except LetPubRateLimit as e:
                # AIMD「增」：触发封锁即翻倍动态等待值（上限 300s）
                self._success_streak = 0
                old = self._dynamic_wait
                self._dynamic_wait = min(self._dynamic_wait * 2, self.cfg.aimd_max_wait)
                rate_attempt += 1
                if rate_attempt > self.cfg.rate_limit_retries:
                    raise LetPubError(
                        f"频率限制重试 {self.cfg.rate_limit_retries} 次后仍失败: {e}"
                    ) from e
                wait = self._dynamic_wait * (2.0 ** (rate_attempt - 1))
                logger.warning(
                    "触发频率限制（第 %d/%d 次），动态退避 %.0fs→%.0fs，等 %.0fs 后重试 p%d",
                    rate_attempt, self.cfg.rate_limit_retries, old, self._dynamic_wait,
                    wait, page,
                )
                time.sleep(wait)
                # 重置限速计时，避免退避结束后立刻又因间隔太短被封
                self._last_request_time = time.time()
            except requests.RequestException as e:
                last_err = e
                net_attempt += 1
                if net_attempt > self.cfg.max_retries:
                    raise LetPubError(
                        f"LetPub 请求重试 {self.cfg.max_retries} 次后仍失败: {e}"
                    ) from e
                backoff = 2.0 ** net_attempt
                logger.warning(
                    "LetPub 请求失败 (attempt %d/%d，%.1fs 后重试): %s",
                    net_attempt, self.cfg.max_retries, backoff, e,
                )
                time.sleep(backoff)

    @staticmethod
    def _build_form(query: dict[str, Any], page: int) -> dict[str, str]:
        """构造 POST 表单。query 支持的键：
        year / year_from / year_to / dept / subject_l1 / subject_l2 / subject_l3
        / company / keyword / pi / project_no / province / grant_type / money_from / money_to
        """
        year = query.get("year")
        y_from = query.get("year_from", year)
        y_to = query.get("year_to", year)
        form = {
            "searchsubmit": "true",
            "name": str(query.get("keyword") or ""),
            "person": str(query.get("pi") or ""),
            "no": str(query.get("project_no") or ""),
            "company": str(query.get("company") or ""),
            "addcomment_s1": str(query.get("dept") or ""),
            "addcomment_s2": str(query.get("subject_l1") or ""),
            "addcomment_s3": str(query.get("subject_l2") or ""),
            "addcomment_s4": str(query.get("subject_l3") or ""),
            "province_main": str(query.get("province") or ""),
            "subcategory": str(query.get("grant_type") or ""),
            "money1": str(query.get("money_from") or ""),
            "money2": str(query.get("money_to") or ""),
            "startTime": str(y_from if y_from is not None else ""),
            "endTime": str(y_to if y_to is not None else ""),
        }
        return {k: v for k, v in form.items()}

    @staticmethod
    def _check_anti_scrape(html: str) -> None:
        """检测反爬/限制提示。

        - 频率限制（可恢复）：抛 LetPubRateLimit，由调度层退避等待后重试
        - 业务限制（不可恢复）：抛 LetPubError，该分片直接标记失败
        """
        # 频率限制：实测文本「温馨提示：您使用的IP地址【x】请求后台数据过于频繁，请稍后再试！」
        for pat in ("请求后台数据过于频繁", "请求过于频繁", "稍后再试"):
            if pat in html:
                raise LetPubRateLimit(f"LetPub IP 频率限制（命中「{pat}」）")
        # 业务限制：2020–2023 年学科/省份搜索被禁。
        # 必须与零结果页区分：零结果页（「很遗憾，没有找到相关的基金项目！」）
        # 底部恒带一段静态帮助提示，其中也含「暂不支持按【学科】搜索」字样，
        # 但那只是通用说明，不代表本次查询被限制。真·限制页是独立片段，
        # 独有特征是「请去掉过滤条件」。若不区分，真实 0 结果的分片会被误判
        # 为 failed（2015 × G × G0119 即为此 bug 的实例，实测该分片确为 0 条）。
        for pat, msg in [
            ("不支持按【学科】搜索", "该年份段暂不支持按学科搜索（2020–2023 限制）"),
            ("不支持按【省份】搜索", "该年份段暂不支持按省份搜索（2020–2023 限制）"),
        ]:
            if pat in html and "请去掉过滤条件" in html:
                raise LetPubError(msg)


# ----------------------------------------------------------------------
# HTML 解析（table_yjfx → 结构化记录）
# ----------------------------------------------------------------------
_LABEL_ROW = 0  # 7 列数据行：新记录开始
_SUBJECT_NAME_RE = re.compile(r"一级：([^，]*)，?\s*二级：([^，]*)，?\s*三级：([^，]*)")
_SUBJECT_CODE_RE = re.compile(r"一级：([A-Z]\d{2})，?\s*二级：([A-Z]\d{4})，?\s*三级：([A-Z]\d{6})")
_DATE_RE = re.compile(r"(\d{4}-\d{2})\s*至\s*(\d{4}-\d{2})")


def parse_subject_line(text: str) -> tuple[str, str, str]:
    """解析「一级：X，二级：Y，三级：Z」为三元组（缺失留空）。"""
    m = _SUBJECT_NAME_RE.search(text.replace(" ", ""))
    if not m:
        # 只有部分级别（如「一级：计算机科学」）
        parts = re.findall(r"[一二三]级：([^，]*)", text)
        return tuple(parts) + ("", "", "")[: max(0, 3 - len(parts))]  # type: ignore[return-value]
    return tuple(g or "" for g in m.groups())  # type: ignore[return-value]


def parse_subject_codes(text: str) -> tuple[str, str, str]:
    """解析学科代码行，取最细可用代码（三级>二级>一级）。"""
    text = text.replace(" ", "")
    m = _SUBJECT_CODE_RE.search(text)
    if m:
        codes = [g or "" for g in m.groups()]
    else:
        codes = re.findall(r"[一二三]级：([A-Z]\d+)", text) + ["", "", ""]
    return tuple(codes)  # type: ignore[return-value]


def _pick_finest_code(codes: tuple[str, str, str]) -> str:
    for c in reversed(codes):
        if c:
            return c
    return ""


def parse_page(html: str, source: str = "letpub") -> list[dict[str, Any]]:
    """解析单页 table_yjfx，返回结构化记录列表。

    每条记录 keys 对齐 store.projects 表：project_no/title/pi/institution/
    year/grant_type/department/subject_l1..3/subject_code/amount_wy/
    begin_date/end_date/keywords/source。
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table_yjfx")
    if table is None:
        # 无结果页面（如空查询）返回空列表，不报错
        return []

    records: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None

    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        ncells = len(cells)
        texts = [c.get_text(" ", strip=True) for c in cells]

        # 1-cell 行是分页导航，跳过
        if ncells == 1:
            continue
        # 表头行
        if texts and texts[0] == "负责人":
            continue

        if ncells == 7:
            # 数据行：收尾上一条，开启新记录
            if current is not None:
                records.append(current)
            try:
                year = int(texts[6]) if texts[6] else None
            except ValueError:
                year = None
            try:
                amount = float(texts[2]) if texts[2] else None
            except ValueError:
                amount = None
            current = {
                "project_no": texts[3],
                "pi": texts[0],
                "institution": texts[1],
                "amount_wy": amount,
                "grant_type": texts[4],
                "department": texts[5],
                "year": year,
                "title": "",
                "subject_l1": "", "subject_l2": "", "subject_l3": "",
                "subject_code": "",
                "begin_date": "", "end_date": "",
                "keywords": "",  # 列表页不提供
                "source": source,
            }
        elif current is not None and ncells == 2:
            label, value = texts[0], texts[1]
            if label == "题目":
                current["title"] = value
            elif label == "学科分类":
                l1, l2, l3 = parse_subject_line(value)
                current["subject_l1"], current["subject_l2"], current["subject_l3"] = l1, l2, l3
            elif label == "学科代码":
                codes = parse_subject_codes(value)
                current["subject_code"] = _pick_finest_code(codes)
            elif label == "执行时间":
                m = _DATE_RE.search(value.replace(" ", ""))
                if m:
                    current["begin_date"], current["end_date"] = m.group(1), m.group(2)

    if current is not None:
        records.append(current)

    # 丢弃没有项目编号的残缺记录
    return [r for r in records if r.get("project_no")]


def parse_match_info(html: str) -> dict[str, int]:
    """从页面顶部提取匹配信息。

    实测文本格式：
      「搜索条件匹配： 1721 条 相关记录！每页显示10条，当前第8页，共173页。
       结果最多显示20页，如果匹配结果太多，请您进一步精炼筛选条件。」

    返回 {'total': 真实匹配条数, 'total_pages': 真实页数, 'max_pages': 显示页数上限}。
    无结果页面返回全 0。
    """
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    info = {"total": 0, "total_pages": 0, "max_pages": MAX_PAGES_PER_QUERY}
    m = re.search(r"搜索条件匹配[：:]\s*([\d,]+)\s*条", text)
    if m:
        info["total"] = int(m.group(1).replace(",", ""))
    m = re.search(r"共\s*([\d,]+)\s*页", text)
    if m:
        info["total_pages"] = int(m.group(1).replace(",", ""))
    m = re.search(r"最多显示\s*(\d+)\s*页", text)
    if m:
        info["max_pages"] = int(m.group(1))
    return info


def parse_total_pages(html: str) -> int:
    """从分页导航解析真实总页数。无结果返回 0。

    废弃说明：分页导航「去 /20页」里的 20 是显示上限（固定值），不是真实页数；
    真实页数在「共N页」里，应优先用 parse_match_info。本函数保留作降级使用。
    """
    info = parse_match_info(html)
    if info["total_pages"] > 0:
        return min(info["total_pages"], info["max_pages"])
    # 降级：无「共N页」文本时按跳页表单的上限算
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(r"去\s*/\s*(\d+)\s*页", text)
    if m:
        return int(m.group(1))
    if 'class="table_yjfx"' in html and "下一页" not in text:
        return 1
    return 0


def estimate_total_count(total_pages: int) -> int:
    """由总页数估算总条数（每页 PAGE_SIZE 条）。

    注意：total_pages 已是 min(真实页数, 20)，因此本估算在触顶时
    只是下限。真实条数应直接取 parse_match_info()['total']。
    """
    if total_pages <= 0:
        return 0
    return total_pages * PAGE_SIZE
