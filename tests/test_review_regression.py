# -*- coding: utf-8 -*-
"""S1 失败夹具：评审指出的六项事实层问题。

这些测试在修复前应当失败（红），修复后转为通过。
逐项对应 v2-review.md 的 V2-002 / V2-003 / V2-004 / V2-005 / V2-006 / V2-008。

运行：
  python -m unittest discover -s tests -t . -k ReviewRegression
"""

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADVANCED = PROJECT_ROOT / "data" / "analysis" / "analysis_advanced.json"

SAMPLE_WITH_CHINESE_SEMICOLON = "分子机制；细胞凋亡;自噬"


class ReviewRegression(unittest.TestCase):
    """对应 v2-review.md 的逐项回归。"""

    # ---- V2-005：详情 DTO 缺字段（abstract_zh / subject_l3 / has_report）----

    def test_v2_005_detail_dto_fields(self):
        """详情接口必须返回已存在的 abstract_zh / subject_l3 / has_report。"""
        src = (PROJECT_ROOT / "tools" / "serve_api.py").read_text(encoding="utf-8")
        for f in ("abstract_zh", "subject_l3", "has_report"):
            self.assertIn(f, src, f"PROJECT_COLS 缺字段 {f}（库内有数据但详情取不到）")

    # ---- V2-002：关键词中英文分号与项目内去重 ----

    def test_v2_002_chinese_semicolon_tokenized(self):
        """含中文分号的关键词必须被拆分，不能整串当一个词。"""
        from merge.build import _split_keywords
        words = _split_keywords(SAMPLE_WITH_CHINESE_SEMICOLON)
        self.assertEqual(sorted(words), ["分子机制", "细胞凋亡", "自噬"])

    def test_v2_002_project_level_dedup(self):
        """同一项目内重复出现的词只计一次。"""
        from merge.build import _split_keywords
        words = _split_keywords("深度学习;深度学习；机器学习")
        self.assertEqual(sorted(words), ["机器学习", "深度学习"])

    # ---- V2-008：金额分箱边界与标签一致 ----

    def test_v2_008_bin_labels_match_bounds(self):
        """分箱标签必须与左右边界一致：[0,20) 不能标 ≤20。"""
        import re
        src = (PROJECT_ROOT / "analysis" / "analyze.py").read_text(encoding="utf-8")
        # 只检查 labels 赋值那一行（注释里提到旧标签是正常的）
        m = re.search(r'^\s*labels\s*=\s*\[(.*?)\]', src, re.M | re.S)
        self.assertIsNotNone(m, "找不到分箱 labels 定义")
        labels_line = m.group(1)
        self.assertNotIn("≤20", labels_line, "[0,20) 区间标注 ≤20 会误导：20 恰有 8,221 条")
        self.assertNotIn(">500", labels_line, "[500,∞) 区间标注 >500 会误导")
        self.assertIn("0-20", labels_line)
        self.assertIn("500+", labels_line)

    def test_v2_008_avg_uses_valid_n(self):
        """分组均值必须用金额有效 N，缺失不能当隐式零。"""
        src = (PROJECT_ROOT / "analysis" / "analyze.py").read_text(encoding="utf-8")
        # strength_by_type 必须带 count（有效 N）而非用全组行数
        self.assertIn('"count"', src)
        self.assertIn("dropna(subset=[\"amount_wan\"])", src,
                      "分组强度计算必须先 dropna 金额，否则缺失被当零拉低均值")

    # ---- V2-006：grant_type_raw 保留原始标签 ----

    def test_v2_006_raw_label_preserved(self):
        """grant_type_raw 必须保留来源原始标签，不能被规范化值覆盖。"""
        import sqlite3
        con = sqlite3.connect(f"file:{PROJECT_ROOT / 'data' / 'unified.db'}?mode=ro", uri=True)
        try:
            # 原始标签里存在「青年科学基金项目」「数学天元基金」等被规范化的写法，
            # 修后 raw 应保留它们；当前全库 raw == 规范名说明被覆盖了
            n = con.execute(
                "SELECT count(*) FROM unified_projects WHERE grant_type_raw != grant_type"
            ).fetchone()[0]
            self.assertGreater(n, 0, "全库 grant_type_raw == grant_type：原始标签被规范化值覆盖")
        finally:
            con.close()

    def test_v2_006_amount_marker_follows_value(self):
        """amount_inferred 标记必须与 amount_wan 同源（同一条记录选出来）。"""
        import sqlite3
        con = sqlite3.connect(f"file:{PROJECT_ROOT / 'data' / 'unified.db'}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT provenance FROM unified_projects "
                "WHERE amount_wan IS NOT NULL ORDER BY rowid LIMIT 5000"
            ).fetchall()
            mismatch = 0
            for (raw,) in rows:
                prov = json.loads(raw or "{}")
                amt_src = prov.get("amount_wan")
                inf_src = prov.get("amount_inferred")
                if amt_src and inf_src and amt_src != inf_src:
                    mismatch += 1
            self.assertEqual(mismatch, 0,
                             f"金额与推断标记来源不一致 {mismatch} 条（抽样 5,000）")
        finally:
            con.close()

    # ---- V2-003：学科榜先按范围过滤再排名 ----

    def test_v2_003_ranking_filters_before_topk(self):
        """top_subjects 必须先按学部范围过滤再取 TopK，不能全局截断后过滤。"""
        src = (PROJECT_ROOT / "analysis" / "analyze.py").read_text(encoding="utf-8")
        # 旧的实现是 .sort_values(...).head(20) 后再在前端过滤
        self.assertNotIn('sort_values("count", ascending=False).head(20)', src,
                         "全局 Top20 截断后再按学部过滤：小 学部的榜单不完整")
        # 应有按范围分组的聚合
        self.assertIn("groupby", src)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
