# -*- coding: utf-8 -*-
"""三库合并层：把 grok 门户库、ChatGPT/Grok 累计主表、atria LetPub 库
按批准号合并为一张统一项目表，写入 data/unified.db。

三库口径互不相同，合并时只做归一化与冲突登记，不做语义推断：
  grok  kd.nsfc.cn 结题年度口径，close_year 2020-2023（135,783 行）
  pkg   第三方存档 + 机构官方，award_year 2004-2024（32,815 行）
  atria LetPub，award_year 2015/2019（1,845 行）

用法：
  python -m merge.build                # 增量更新（默认）
  python -m merge.build --rebuild      # 丢弃旧表重建
  python -m merge.build --report-only  # 只打印核对报告
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 申请代码首字母（A–H 八大学部；L 是联合基金项目，门户原样记作 L）
_CODE_PREFIX = re.compile(r"^[A-HL]\d")
_L3_PATTERN = re.compile(r"三级[:：]\s*([A-HL]\d+)")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GROK_DB = Path("H:/code-grok/nsfc/data/catalog.sqlite")
PKG_DB = PROJECT_ROOT / "data/external/NSFC_累计主数据_非全国全量_2026-10-02/nsfc_consolidated_data_2026-10-02/databases/nsfc_projects.sqlite"
NSTRS_DB = PROJECT_ROOT / "data/external/NSFC_累计主数据_非全国全量_2026-10-02/nsfc_consolidated_data_2026-10-02/databases/nsfc_reports_links.sqlite"
ATRIA_DB = PROJECT_ROOT / "data/nsfc.db"
OUT_DB = PROJECT_ROOT / "data/unified.db"

# 学部代码 → 名称。L 不是学部（联合基金项目），沿用 grok 交接说明的原样记法。
DIVISION_NAMES = {
    "A": "数理科学部", "B": "化学科学部", "C": "生命科学部",
    "D": "地球科学部", "E": "工程与材料科学部", "F": "信息科学部",
    "G": "管理科学部", "H": "医学科学部", "L": "L",
}

# 冲突裁决的来源优先级，数字越小越优先。依据累计主表 field_dictionary 的
# source_priority：基金委公示 > 机构官方 > 商业样本/第三方存档。
# grok 来自基金委门户，级别最高；atria 是本管线亲自核验过的 LetPub 采集；
# pkg 是第三方交付包，内部还分机构官方与第三方存档，见 _pkg_tier()。
SOURCE_TIERS = {"grok": 0, "atria": 1, "pkg": 2}

# 类别标签的等价写法。累计主表明确说明「青年科学基金项目」与「青年科学基金项目（C类）」
# 是同一类别的现行/历史名称，不据此倒推年度；带不带「项目」后缀同理。这些只算写法差异，
# 不记为事实冲突。
_LABEL_SUFFIXES = ("（C类）", "(C类)", "项目")


def _clean(v) -> str | None:
    """None / 空串归一化为 None，其余去首尾空白。"""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _to_int(v) -> int | None:
    s = _clean(v)
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_float(v) -> float | None:
    s = _clean(v)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_date(v) -> str | None:
    """统一日期格式。来源写法各异（'2016.01' / '2012-1-1' / '2014/01/01 00:00:00' /
    '201601' / '2016-01'），统一成 'YYYY-MM-DD'，无日则 'YYYY-MM'，无法解析返回原值。"""
    s = _clean(v)
    if s is None:
        return None
    s = s.split(" ")[0].strip()
    if "-" in s:
        parts = s.split("-")
    elif "." in s:
        parts = s.split(".")
    elif "/" in s:
        parts = s.split("/")
    elif s.isdigit() and len(s) == 6:          # 201601
        parts = [s[:4], s[4:]]
    else:
        return s
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return s
    if len(nums) < 2 or not (1986 <= nums[0] <= 2035):
        return s
    out = f"{nums[0]:04d}-{nums[1]:02d}"
    if len(nums) >= 3:
        out += f"-{nums[2]:02d}"
    return out


def labels_equal(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    if a == b:
        return True
    for suf in _LABEL_SUFFIXES:
        if a.replace(suf, "") == b.replace(suf, ""):
            return True
    return False


# 关键词按中英文分号切分，项目内去重。来源写法不一（12,524 行含中文分号），
# 不能盲拆逗号（科学名称里常有逗号），不做同义合并
_KW_SPLIT = re.compile(r"[;；]+")


def _split_keywords(raw: str | None) -> list[str]:
    """拆出项目内唯一的关键词，保留原词，不规范化、不合近义词。"""
    if not raw:
        return []
    seen: dict[str, None] = {}
    for w in _KW_SPLIT.split(str(raw)):
        w = w.strip()
        if len(w) >= 2 and w not in seen:
            seen[w] = None
    return list(seen)


# 类别标签的规范名。只合并「同一类别、不同时期/不同来源写法」，依据是基金委现行
# 名称（门户与 grok 前端的 recent.ts 均如此）。跨类别（如专项基金项目 vs 专项项目）
# 门户自身也分列，这里不合，避免把不同资助渠道并成一个。
CANON_GRANT_TYPES = {
    "青年科学基金项目": "青年科学基金项目（C类）",
    "青年项目": "青年科学基金项目（C类）",
    "青年基金": "青年科学基金项目（C类）",
    "数学天元基金": "数学天元基金项目",
    "优秀青年科学基金": "优秀青年科学基金项目",
    "优秀青年基金项目": "优秀青年科学基金项目",
    "国家杰出青年科学基金": "国家杰出青年科学基金项目",
}


def canonize_grant_type(label: str | None) -> str | None:
    """类别标签归一：全/半角括号统一为全角、映射到规范名、去掉误拼进来的尾巴。"""
    s = _clean(label)
    if s is None:
        return None
    s = s.replace("(", "（").replace(")", "）")
    # '重点项目/水产养殖生物的繁育及经济性状形成机制' 这类把题目带进来的，截掉
    if "/" in s:
        head, tail = s.split("/", 1)
        if len(tail) > 10:
            s = head.strip()
    return CANON_GRANT_TYPES.get(s, s)


@dataclass
class Record:
    """合并中间结构：某来源对某个批准号的一次观察。"""
    grant_no: str
    source: str                       # grok / atria / pkg
    tier: int
    fields: dict[str, object] = field(default_factory=dict)

    def get(self, name: str):
        v = self.fields.get(name)
        return _clean(v) if isinstance(v, str) else v


# --------------------------------------------------------------------------
# 三个来源的读取器。每个都输出 Record，字段名统一到合并层词汇表：
#   title pi institution award_year close_year grant_type
#   division_code division_name subject_code subject_l1 subject_l2 subject_l3
#   amount_wan amount_inferred begin_date end_date keywords abstract_zh has_report
# --------------------------------------------------------------------------

def read_grok(path: Path) -> list[Record]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT grant_no, title, pi_name, institution, award_year, close_year,"
            " grant_type, division_code, division_name, subject_code, amount_wan,"
            " keywords, has_report FROM project"
        ).fetchall()
    finally:
        con.close()
    out: list[Record] = []
    for r in rows:
        no = _clean(r["grant_no"])
        if not no:
            continue
        out.append(Record(no, "grok", SOURCE_TIERS["grok"], {
            "title": r["title"],
            "pi": r["pi_name"],
            "institution": r["institution"],
            "award_year": r["award_year"],
            "close_year": r["close_year"],
            "grant_type": r["grant_type"],
            "division_code": r["division_code"],
            "division_name": r["division_name"],
            "subject_code": r["subject_code"],
            "amount_wan": _to_float(r["amount_wan"]),
            "keywords": r["keywords"],
            "has_report": r["has_report"],
        }))
    return out


def _pkg_amount(row) -> tuple[float | None, bool]:
    """累计主表金额折算为万元。单位缺失时按量级推断（NSFC 单项经费不会过千万）。"""
    amount = _to_float(row["funding_amount"])
    if amount is None:
        return None, False
    unit = _clean(row["funding_unit"]) or ""
    if unit.startswith("元"):
        return round(amount / 1e4, 4), False
    if unit.startswith("万"):
        return round(amount, 4), False
    # 单位缺失：18,665 行里 18,094 行 <100，明显是万元；>=10000 视为元并标记
    if amount >= 1e4:
        return round(amount / 1e4, 4), True
    return round(amount, 4), True


def read_pkg(path: Path) -> list[Record]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT approval_number, title, pi, institution, award_year, program,"
            " department, subject_code, funding_amount, funding_unit,"
            " start_date_raw, end_date_raw, keywords_zh, abstract_zh,"
            " primary_source_kind FROM projects_core"
        ).fetchall()
    finally:
        con.close()
    out: list[Record] = []
    for r in rows:
        no = _clean(r["approval_number"])
        if not no:
            continue
        amount, inferred = _pkg_amount(r)
        out.append(Record(no, "pkg", SOURCE_TIERS["pkg"], {
            "title": r["title"],
            "pi": r["pi"],
            "institution": r["institution"],
            "award_year": r["award_year"],
            "grant_type": r["program"],
            "division_name": r["department"],
            "subject_code": r["subject_code"],
            "amount_wan": amount,
            "amount_inferred": inferred,
            "begin_date": _normalize_date(r["start_date_raw"]),
            "end_date": _normalize_date(r["end_date_raw"]),
            "keywords": r["keywords_zh"],
            "abstract_zh": r["abstract_zh"],
        }))
    return out


# --------------------------------------------------------------------------
# NSTRS 结题报告元数据：不产生独立项目，只给已有批准号补报告字段
# --------------------------------------------------------------------------

def load_nstrs_links(path: Path, known_grant_nos: set[str]) -> dict[str, dict]:
    """加载报告元数据并关联到批准号。关联规则见 _nstrs_links_from_rows。"""
    if not path.exists():
        logger.warning("NSTRS 库不存在，跳过报告元数据: %s", path)
        return {}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT linked_approval_number, title_zh, pi, institution,"
            " keywords_zh, official_report_landing_url, program"
            " FROM nstrs_reports"
        ).fetchall()
    finally:
        con.close()
    return _nstrs_links_from_rows([dict(r) for r in rows], known_grant_nos)


def _nstrs_links_from_rows(rows: list[dict], known_grant_nos: set[str]) -> dict[str, dict]:
    """两级关联，都是精确匹配、不做模糊推断：
      1. 交付包已用严格规则关联的 665 条（linked_approval_number）；
      2. 其余报告用 (负责人, 标题, 单位) 三元组在已知批准号上唯一匹配，
         扩到约 1,780 条（实测零歧义）。
    匹配到的项目必须三者全同才关联——source_proposal_year 不等于批准年，
    不参与关联（抽查显示它恒比批准年晚 1 年）。报告不新增项目行。
    """
    links: dict[str, dict] = {}
    strict = matched = skipped_ambiguous = 0
    for r in rows:
        kw = _clean(r.get("keywords_zh"))
        url = _clean(r.get("official_report_landing_url"))
        if not kw and not url:
            continue
        linked = _clean(r.get("linked_approval_number"))
        if linked and linked in known_grant_nos:
            links[linked] = {"report_keywords": kw, "report_url": url, "nstrs_rule": "strict"}
            strict += 1
            continue
        pi = _clean(r.get("pi"))
        title = _clean(r.get("title_zh"))
        inst = _clean(r.get("institution"))
        if not (pi and title and inst):
            continue
        # 三元组必须全同：索引按 (pi, title) 命中后，再逐个校验单位
        hits = [g for g in _lookup_by_pi_title(pi, title) if g in known_grant_nos]
        uniq = [g for g in hits if _INSTITUTION_INDEX.get(g) == inst]
        if len(uniq) == 1:
            links[uniq[0]] = {"report_keywords": kw, "report_url": url, "nstrs_rule": "pi_title_unit"}
            matched += 1
        elif len(hits) > 1:
            skipped_ambiguous += 1
    logger.info("NSTRS: 严格关联 %d，三元组匹配 %d，歧义跳过 %d", strict, matched, skipped_ambiguous)
    return links


# 测试用的公开入口（绕过文件读取）
load_nstrs_links_from_rows = _nstrs_links_from_rows


_PI_TITLE_INDEX: dict[tuple[str, str], list[str]] = {}
_INSTITUTION_INDEX: dict[str, str] = {}


def _lookup_by_pi_title(pi: str, title: str) -> list[str]:
    """由 (pi, title) 查批准号。索引在 read_* 阶段建立。"""
    return _PI_TITLE_INDEX.get((pi, title), [])


def read_atria(path: Path) -> list[Record]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT project_no, title, pi, institution, year, grant_type, department,"
            " subject_l1, subject_l2, subject_l3, subject_code, amount_wy,"
            " begin_date, end_date, keywords FROM projects"
        ).fetchall()
    finally:
        con.close()
    out: list[Record] = []
    for r in rows:
        no = _clean(r["project_no"])
        if not no:
            continue
        out.append(Record(no, "atria", SOURCE_TIERS["atria"], {
            "title": r["title"],
            "pi": r["pi"],
            "institution": r["institution"],
            "award_year": r["year"],
            "grant_type": r["grant_type"],
            "division_name": r["department"],
            "subject_l1": r["subject_l1"],
            "subject_l2": r["subject_l2"],
            "subject_l3": r["subject_l3"],
            "subject_code": r["subject_code"],
            "amount_wan": _to_float(r["amount_wy"]),
            "begin_date": _normalize_date(r["begin_date"]),
            "end_date": _normalize_date(r["end_date"]),
            "keywords": r["keywords"],
        }))
    return out


# --------------------------------------------------------------------------
# 学部补全：subject_code 首字母 → 学部代码/名称
# --------------------------------------------------------------------------

def complete_division(rec: Record) -> None:
    code = _clean(rec.fields.get("division_code"))
    name = _clean(rec.fields.get("division_name"))
    subj = _clean(rec.fields.get("subject_code"))
    # atria 少数行的 subject_code 是描述串（'一级：C05，二级：C0501，三级：C050101'），
    # 取三级代码作为申请代码，名称字段已单独保留
    if subj and not _CODE_PREFIX.match(subj):
        m = _L3_PATTERN.search(subj)
        if m:
            subj = m.group(1)
            rec.fields["subject_code"] = subj
    if code is None and subj:
        code = subj[0].upper()
    if code is None and name:
        code = next((k for k, v in DIVISION_NAMES.items() if v == name), None)
    # 只接受 A–H 与 L（联合基金）；其余（M01、Z01 等）是来源脏值，不冒充学部
    if code is not None and code not in DIVISION_NAMES:
        code = None
    if code is not None and name is None:
        name = DIVISION_NAMES[code]
    rec.fields["division_code"] = code
    rec.fields["division_name"] = name


# --------------------------------------------------------------------------
# 学科名称富化：把申请代码映射到一/二/三级学科名
# --------------------------------------------------------------------------

def _undouble(s: str) -> str:
    """subjects_tree.json 等文件的中文值被双重编码过（UTF-8 当 latin-1 存了一次），修回来。"""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def load_subject_names(
    tree_path: Path,
    portal_path: Path,
    grok_db: Path = GROK_DB,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """返回 (L1, L2, L3) 代码→名称映射。三个来源按优先级互补：
    1. grok 门户申请代码表 field_code（现行，1,412 条，L1/L2，直接 UTF-8 无双重编码）
    2. 门户 131 个现行 L1 学科名（含树外的新增代码 A20/H32/E10 等）
    3. 2019 学科树（L2/L3 深度，L3 唯一来源；值需修双重编码）
    皆缺的代码（门户新增但代码表未收的 L2，以及 L 开头的联合基金代码）留空。"""
    l1: dict[str, str] = {}
    l2: dict[str, str] = {}
    l3: dict[str, str] = {}
    # 3. 2019 学科树（先加载，优先级最低，含 L3）
    if tree_path.exists():
        tree = json.loads(tree_path.read_bytes().decode("utf-8"))
        for dept in tree.get("depts", {}).values():
            for l1code, l1row in dept.items():
                l1[l1code] = _undouble(l1row["name"])
                for l2code, l2row in l1row.get("l2", {}).items():
                    l2[l2code] = _undouble(l2row["name"])
                    for l3code, name in l2row.get("l3", {}).items():
                        l3[l3code] = _undouble(name)
    # 2. 门户 131 个现行 L1 学科名
    if portal_path.exists():
        bundle = json.loads(portal_path.read_bytes().decode("utf-8"))
        for d in bundle.get("disciplines", []):
            l1[d["code"]] = d["name"]
    # 1. grok 门户现行申请代码表（L1/L2 最高优先）
    if grok_db.exists():
        con = sqlite3.connect(f"file:{grok_db}?mode=ro", uri=True)
        try:
            for code, name in con.execute("SELECT code, name FROM field_code"):
                if len(code) == 3:
                    l1[code] = name
                elif len(code) == 5:
                    l2[code] = name
        finally:
            con.close()
    return l1, l2, l3


def make_subject_filler(names: tuple[dict[str, str], dict[str, str], dict[str, str]]):
    """生成一个 rec → bool 的补全函数：用申请代码补缺失的学科名，返回是否为推导值。"""
    l1, l2, l3 = names

    def fill(rec: Record) -> bool:
        code = _clean(rec.fields.get("subject_code"))
        if not code:
            return False
        derived = False
        if len(code) >= 3 and not _clean(rec.fields.get("subject_l1")):
            v = l1.get(code[:3])
            if v:
                rec.fields["subject_l1"] = v
                derived = True
        if len(code) >= 5 and not _clean(rec.fields.get("subject_l2")):
            v = l2.get(code[:5])
            if v:
                rec.fields["subject_l2"] = v
                derived = True
        if len(code) >= 7 and not _clean(rec.fields.get("subject_l3")):
            v = l3.get(code)
            if v:
                rec.fields["subject_l3"] = v
                derived = True
        return derived

    return fill


# --------------------------------------------------------------------------
# 合并
# --------------------------------------------------------------------------

MERGE_FIELDS = [
    "title", "pi", "institution", "award_year", "close_year", "grant_type",
    "grant_type_raw",
    "division_code", "division_name", "subject_code", "subject_l1",
    "subject_l2", "subject_l3", "subject_names_derived",
    "amount_wan", "amount_inferred",
    "begin_date", "end_date", "keywords", "abstract_zh", "has_report",
    "report_keywords", "report_url",
]

# 只比较数值/文本是否一致；amount 用近似比较容忍浮点误差，日期按月对齐
# （atria 只到月 '2016-01'，pkg 到日 '2016-01-01'，精度不同不算冲突）
def _values_equal(fname: str, a, b) -> bool:
    if a is None or b is None:
        return False
    if fname == "grant_type":
        return labels_equal(canonize_grant_type(str(a)), canonize_grant_type(str(b)))
    if fname in ("begin_date", "end_date"):
        sa, sb = str(a), str(b)
        if len(sa) >= 7 and len(sb) >= 7:
            return sa[:7] == sb[:7]
        return sa == sb
    if fname == "amount_wan":
        try:
            return abs(float(a) - float(b)) < 0.05
        except (TypeError, ValueError):
            return False
    return str(a) == str(b)


def _amount_inferred_of(recs: list[Record], amount_from: str | None) -> int:
    """推断标记必须取自金额的胜出来源，而不是独立选第一个非空。

    V2-006 之前 amount_inferred 单独按字段顺序选，会出现
    「金额来自 grok（无推断标记）但标记来自 pkg（推断=1）」的错配。
    """
    if amount_from is None:
        return 0
    for r in recs:
        if r.source == amount_from:
            v = r.fields.get("amount_inferred")
            return 1 if v else 0
    return 0


def _classify_conflict(field: str, selected, differing: list[dict]) -> str:
    """冲突逐条分类（V2-007）。

    前缀关系、调动、截断等只是分类线索或已抽查的假设，不是逐条核验后的结论；
    任何不能由结构证明的都标「待核」，不出现「非错误已确认」这类全局断言。
    """
    sel = str(selected) if selected is not None else ""
    if field == "subject_code":
        # 代码呈前缀关系（如 G01 vs G0119）→ 层级差线索；否则可能是历史版本差异。
        # 必须全部落选候选都与选中值呈前缀关系才归此类，混合情形归更保守的「待核」。
        if differing and all(
            str(d.get("value")).startswith(sel) or sel.startswith(str(d.get("value")))
            for d in differing
        ):
            return "代码层级差（前缀关系，待核语义）"
        return "历史代码版本差异（待核）"
    if field == "subject_l2":
        return "学科名映射差异（待核，多随代码版本）"
    if field == "institution":
        return "疑似单位调动（已抽查部分，未逐条核）"
    if field == "title":
        return "疑似第三方标题截断（已抽查部分，未逐条核）"
    if field == "grant_type":
        return "类别写法/口径分歧（待核）"
    return "待核"


def merge(records: list[Record]) -> tuple[list[dict], list[dict]]:
    """按批准号合并。返回 (合并行, 冲突记录)。冲突不丢弃，全部记入第二返回值。"""
    by_no: dict[str, list[Record]] = {}
    for rec in records:
        by_no.setdefault(rec.grant_no, []).append(rec)

    merged: list[dict] = []
    conflicts: list[dict] = []
    for no, recs in by_no.items():
        recs.sort(key=lambda r: r.tier)
        sources = sorted({r.source for r in recs})
        row: dict[str, object] = {"grant_no": no}
        provenance: dict[str, str] = {}
        # 原始类别标签：在 grant_type 处理时记下候选原值，grant_type_raw 直接取，
        # 不能在处理到 grant_type_raw 时回头读 row['grant_type']——那已是规范化值
        # （V2-006：raw 被规范化值覆盖，全库 165,200 行 raw == 规范名）
        raw_grant_type: str | None = None
        raw_grant_type_from: str | None = None
        # 金额与推断标记必须同源（V2-006：5,041 条标记源 ≠ 金额源）
        amount_from: str | None = None
        for fname in MERGE_FIELDS:
            if fname == "grant_type_raw":
                row[fname] = raw_grant_type
                if raw_grant_type is not None and raw_grant_type_from:
                    provenance[fname] = raw_grant_type_from
                continue
            if fname == "subject_names_derived":
                # 跟着 subject_l1 的胜出来源走：名称是来源页面给的还是由申请代码推导的
                winner = next((r for r in recs if _values_equal("subject_l1", r.get("subject_l1"), row.get("subject_l1"))), None)
                row[fname] = winner.get("subject_names_derived") if winner else 0
                continue
            if fname == "amount_inferred":
                # 标记跟随金额的胜出来源，而不是独立选一遍
                # （否则低优先级来源的推断标记会贴到高优先级来源的金额上）
                row[fname] = _amount_inferred_of(recs, amount_from)
                if amount_from is not None:
                    provenance[fname] = amount_from
                continue
            candidates = [(r.get(fname), r.source) for r in recs if r.get(fname) is not None]
            if not candidates:
                row[fname] = None
                continue
            chosen, chosen_from = candidates[0]
            if fname == "grant_type":
                chosen = canonize_grant_type(chosen)
                raw_grant_type = candidates[0][0]
                raw_grant_type_from = chosen_from
            if fname == "amount_wan":
                amount_from = chosen_from
            row[fname] = chosen
            provenance[fname] = chosen_from
            # NSTRS 补充的报告字段：来源指向报告关联记录（含关联规则），
            # 而不是无差别标 grok/atria 等基础来源（V2-006）
            nstrs_rule = next((r.get("_nstrs_rule") for r in recs
                               if r.get("_nstrs_rule") is not None), None)
            if nstrs_rule and fname in ("report_url", "report_keywords", "has_report"):
                provenance[fname] = f"nstrs:{nstrs_rule}"
            # 多来源且值不同 → 记冲突（类别标签的写法差异除外）
            differing = []
            for val, src in candidates[1:]:
                if not _values_equal(fname, val, chosen):
                    differing.append({"value": val, "from": src})
            if differing:
                conflicts.append({
                    "grant_no": no,
                    "field": fname,
                    "selected": str(chosen),
                    "selected_from": chosen_from,
                    "alternatives": json.dumps(differing, ensure_ascii=False),
                    "classification": _classify_conflict(fname, chosen, differing),
                })
        row["sources"] = json.dumps(sources, ensure_ascii=False)
        row["source_count"] = len(sources)
        row["provenance"] = json.dumps(provenance, ensure_ascii=False)
        merged.append(row)

    # 学科名冲突全是申请代码冲突的下游症状（同一批准号的代码不同，名称自然不同），
    # 折叠掉，只留 subject_code 冲突作为根因记录，避免同一问题重复计 4 次
    code_conflict_nos = {c["grant_no"] for c in conflicts if c["field"] == "subject_code"}
    conflicts = [c for c in conflicts
                 if c["field"] not in ("subject_l1", "subject_l2", "subject_l3")
                 or c["grant_no"] not in code_conflict_nos]
    return merged, conflicts


# --------------------------------------------------------------------------
# 落库
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS unified_projects (
    grant_no        TEXT PRIMARY KEY,
    title           TEXT,
    pi              TEXT,
    institution     TEXT,
    award_year      INTEGER,
    close_year      INTEGER,
    grant_type      TEXT,
    grant_type_raw  TEXT,
    division_code   TEXT,
    division_name   TEXT,
    subject_code    TEXT,
    subject_l1      TEXT,
    subject_l2      TEXT,
    subject_l3      TEXT,
    subject_names_derived INTEGER DEFAULT 0,
    amount_wan      REAL,
    amount_inferred INTEGER DEFAULT 0,
    begin_date      TEXT,
    end_date        TEXT,
    keywords        TEXT,
    abstract_zh     TEXT,
    has_report      INTEGER,
    report_keywords TEXT,
    report_url      TEXT,
    sources         TEXT,
    source_count    INTEGER,
    provenance      TEXT,
    updated_at      TEXT
);
CREATE TABLE IF NOT EXISTS unified_conflicts (
    grant_no     TEXT,
    field        TEXT,
    selected     TEXT,
    selected_from TEXT,
    alternatives TEXT,
    classification TEXT,
    PRIMARY KEY (grant_no, field)
);
CREATE INDEX IF NOT EXISTS idx_unified_year ON unified_projects(award_year);
CREATE INDEX IF NOT EXISTS idx_unified_close ON unified_projects(close_year);
CREATE INDEX IF NOT EXISTS idx_unified_division ON unified_projects(division_code);
CREATE INDEX IF NOT EXISTS idx_unified_type ON unified_projects(grant_type);
"""

PLACEHOLDERS = ",".join("?" for _ in MERGE_FIELDS)
COLS = ",".join(MERGE_FIELDS)


def store(merged: list[dict], conflicts: list[dict], rebuild: bool) -> None:
    con = sqlite3.connect(str(OUT_DB))
    try:
        if rebuild:
            con.execute("DROP TABLE IF EXISTS unified_projects")
            con.execute("DROP TABLE IF EXISTS unified_conflicts")
        con.executescript(SCHEMA)
        now = datetime.now().isoformat(timespec="seconds")
        # grant_no 不在 MERGE_FIELDS 里（它是主键，不参与来源裁决），单独写入
        con.executemany(
            f"INSERT OR REPLACE INTO unified_projects (grant_no, {COLS}, sources,"
            f" source_count, provenance, updated_at)"
            f" VALUES (?, {PLACEHOLDERS}, ?, ?, ?, ?)",
            [
                (r["grant_no"],)
                + tuple(r.get(f) for f in MERGE_FIELDS)
                + (r["sources"], r["source_count"], r["provenance"], now)
                for r in merged
            ],
        )
        con.execute("DELETE FROM unified_conflicts")
        con.executemany(
            "INSERT OR REPLACE INTO unified_conflicts"
            " (grant_no, field, selected, selected_from, alternatives, classification)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(c["grant_no"], c["field"], c["selected"], c["selected_from"],
              c["alternatives"], c.get("classification", "待核")) for c in conflicts],
        )
        con.commit()
        con.execute("PRAGMA integrity_check")
    finally:
        con.close()


# --------------------------------------------------------------------------
# 核对报告
# --------------------------------------------------------------------------

def report() -> None:
    con = sqlite3.connect(f"file:{OUT_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        total = con.execute("SELECT count(*) FROM unified_projects").fetchone()[0]
        print(f"\n=== unified.db 核对报告 ===")
        print(f"合并后项目数: {total:,}")
        print(f"冲突记录: {con.execute('SELECT count(*) FROM unified_conflicts').fetchone()[0]:,} 条")
        print("冲突逐条分类（V2-007）：")
        for r in con.execute(
            "SELECT classification, count(*) FROM unified_conflicts"
            " GROUP BY 1 ORDER BY 2 DESC"
        ):
            print(f"  {r[1]:>5,}  {r[0]}")
        for src in ("grok", "atria", "pkg"):
            n = con.execute(
                "SELECT count(*) FROM unified_projects WHERE sources LIKE ?", (f'%"{src}"%',)
            ).fetchone()[0]
            print(f"  含 {src:6} 来源: {n:,}")
        multi = con.execute("SELECT count(*) FROM unified_projects WHERE source_count > 1").fetchone()[0]
        print(f"  多来源重叠: {multi:,}")

        print("\n字段填充率:")
        for f in MERGE_FIELDS:
            # 布尔标记列按真值统计，其余按非空统计
            if f in ("amount_inferred", "subject_names_derived"):
                n = con.execute(f"SELECT count(*) FROM unified_projects WHERE {f}=1").fetchone()[0]
            else:
                n = con.execute(f"SELECT count(*) FROM unified_projects WHERE {f} IS NOT NULL AND {f} != ''").fetchone()[0]
            print(f"  {f:22} {n:>8,}  {n / total:6.1%}")

        print("\n按批准年度（top 15）:")
        for r in con.execute(
            "SELECT award_year, count(*) c FROM unified_projects"
            " WHERE award_year IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 15"
        ):
            print(f"  {r['award_year']}: {r['c']:>7,}")
        print("\n冲突字段分布:")
        for r in con.execute(
            "SELECT field, count(*) c FROM unified_conflicts GROUP BY 1 ORDER BY c DESC"
        ):
            print(f"  {r['field']:16} {r['c']:>6,}")
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true", help="丢弃旧表重建")
    ap.add_argument("--report-only", action="store_true", help="只打印核对报告")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    if args.report_only:
        report()
        return 0

    if not GROK_DB.exists():
        raise SystemExit(f"找不到 grok 库: {GROK_DB}")
    if not PKG_DB.exists():
        raise SystemExit(f"找不到累计主表: {PKG_DB}")
    if not ATRIA_DB.exists():
        raise SystemExit(f"找不到 atria 库: {ATRIA_DB}")

    OUT_DB.parent.mkdir(parents=True, exist_ok=True)

    # 学科名称映射：2019 学科树（L2/L3 深度）+ 门户现行 L1 名（含树外新增代码）
    names = load_subject_names(
        PROJECT_ROOT / "data" / "subjects_tree.json",
        PROJECT_ROOT / "data" / "external" / "kCApGaSG8Aij8zul-grok-workspace" / "src" / "data" / "nsfc_recovered.json",
    )
    fill_subject_names = make_subject_filler(names)
    logger.info("学科名映射: L1=%d L2=%d L3=%d", *map(len, names))

    records: list[Record] = []
    for name, reader, path in (
        ("grok", read_grok, GROK_DB),
        ("pkg", read_pkg, PKG_DB),
        ("atria", read_atria, ATRIA_DB),
    ):
        recs = reader(path)
        for rec in recs:
            complete_division(rec)
            rec.fields["subject_names_derived"] = 1 if fill_subject_names(rec) else 0
            # 建立 (pi, title) → 批准号 索引，供 NSTRS 三元组匹配
            pi, title = rec.get("pi"), rec.get("title")
            if pi and title:
                _PI_TITLE_INDEX.setdefault((pi, title), []).append(rec.grant_no)
            inst = rec.get("institution")
            if inst:
                _INSTITUTION_INDEX[rec.grant_no] = inst
        records += recs
        logger.info("%s: 读取 %d 条", name, len(recs))

    # NSTRS 结题报告元数据：只给已存在的批准号补报告字段，不新增项目
    known = {r.grant_no for r in records}
    nstrs = load_nstrs_links(NSTRS_DB, known)
    nstrs_matched = 0
    for rec in records:
        link = nstrs.get(rec.grant_no)
        if not link:
            continue
        rec.fields["report_keywords"] = link["report_keywords"]
        rec.fields["report_url"] = link["report_url"]
        rec.fields.setdefault("has_report", 1)
        # 随身携带关联规则：合并时报告字段的来源标记为 nstrs 而非承载它的基础来源
        rec.fields["_nstrs_rule"] = link["nstrs_rule"]
        nstrs_matched += 1
    logger.info("NSTRS: 命中合并库 %d 条", nstrs_matched)

    merged, conflicts = merge(records)
    logger.info("合并后 %d 个批准号，%d 条字段冲突", len(merged), len(conflicts))
    store(merged, conflicts, args.rebuild)
    logger.info("写入 %s", OUT_DB)
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
