# -*- coding: utf-8 -*-
"""合并层核心规则的单元测试。不依赖外部数据库，只测纯函数与合并策略。

运行：
  python -m unittest discover -s tests -t . -v
"""

import json
import unittest

from merge.build import (
    MERGE_FIELDS,
    Record,
    _classify_conflict,
    _normalize_date,
    _pkg_amount,
    _split_keywords,
    _undouble,
    canonize_grant_type,
    complete_division,
    load_subject_names,
    make_subject_filler,
    merge,
)


class TestNormalizeDate(unittest.TestCase):
    """各来源的日期写法都要归一到可比形式。"""

    def test_variants(self):
        cases = [
            ("2016-01", "2016-01"),          # atria 只到月
            ("2016.01", "2016-01"),          # pkg 导出表
            ("2016.1", "2016-01"),
            ("2012-1-1", "2012-01-01"),
            ("2012/1/1", "2012-01-01"),
            ("2014-01-01 00:00:00", "2014-01-01"),   # pkg 时间戳
            ("201601", "2016-01"),           # 6 位连写
            ("", None),
            (None, None),
            ("未知", "未知"),                 # 无法解析保留原值
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_normalize_date(raw), want)


class TestAmountConversion(unittest.TestCase):
    """累计主表金额按单位折算为万元；单位缺失按量级推断。"""

    def test_units(self):
        class Row(dict):
            def __getitem__(self, k):
                return self.get(k)
        self.assertEqual(_pkg_amount(Row(funding_amount=48, funding_unit="万元")), (48.0, False))
        self.assertEqual(_pkg_amount(Row(funding_amount=48, funding_unit="万（导出表原文）")), (48.0, False))
        self.assertEqual(_pkg_amount(Row(funding_amount=920000, funding_unit="元")), (92.0, False))
        self.assertEqual(_pkg_amount(Row(funding_amount=60, funding_unit=None)), (60.0, True))
        self.assertEqual(_pkg_amount(Row(funding_amount=2000000, funding_unit=None)), (200.0, True))
        self.assertEqual(_pkg_amount(Row(funding_amount=None, funding_unit="万元")), (None, False))


class TestGrantTypeLabels(unittest.TestCase):
    """同一类别的现行/历史名称不记为冲突，但不同类别不能并。"""

    def test_canonize(self):
        self.assertEqual(canonize_grant_type("青年科学基金项目"), "青年科学基金项目（C类）")
        self.assertEqual(canonize_grant_type("青年基金"), "青年科学基金项目（C类）")
        self.assertEqual(canonize_grant_type("青年科学基金项目（C类）"), "青年科学基金项目（C类）")
        self.assertEqual(canonize_grant_type("国际(地区)合作与交流项目"), "国际（地区）合作与交流项目")
        self.assertEqual(canonize_grant_type("数学天元基金"), "数学天元基金项目")
        self.assertEqual(canonize_grant_type("面上项目"), "面上项目")

    def test_title_pollution_stripped(self):
        # 来源把题目拼进了类别字段
        self.assertEqual(
            canonize_grant_type("重点项目/水产养殖生物的繁育及经济性状形成机制"),
            "重点项目",
        )

    def test_different_categories_not_merged(self):
        # 专项基金项目与专项项目在门户自身也分列，不合
        self.assertEqual(canonize_grant_type("专项基金项目"), "专项基金项目")
        self.assertEqual(canonize_grant_type("专项项目"), "专项项目")

    def test_canonical_implies_equal(self):
        # 规范化后等价的标签，在合并比较里也判为相等（见 TestMerge 的用例）
        self.assertEqual(canonize_grant_type("青年科学基金项目"),
                         canonize_grant_type("青年科学基金项目（C类）"))
        self.assertEqual(canonize_grant_type("数学天元基金"),
                         canonize_grant_type("数学天元基金项目"))
        self.assertNotEqual(canonize_grant_type("专项基金项目"),
                            canonize_grant_type("专项项目"))


class TestDivisionCompletion(unittest.TestCase):
    """学部代码只接受 A–H 与 L；来源脏值不冒充学部。"""

    def test_from_subject_code(self):
        rec = Record("1", "pkg", 2, {"subject_code": "G0119"})
        complete_division(rec)
        self.assertEqual(rec.fields["division_code"], "G")
        self.assertEqual(rec.fields["division_name"], "管理科学部")

    def test_dirty_codes_rejected(self):
        for code in ("M01", "Z01"):
            rec = Record("1", "pkg", 2, {"subject_code": code})
            complete_division(rec)
            self.assertIsNone(rec.fields["division_code"])

    def test_descriptive_string_extracts_l3(self):
        rec = Record("1", "atria", 1,
                     {"subject_code": "一级：C05，二级：C0501，三级：C050101"})
        complete_division(rec)
        self.assertEqual(rec.fields["subject_code"], "C050101")
        self.assertEqual(rec.fields["division_code"], "C")

    def test_L_is_not_a_division_name(self):
        rec = Record("1", "grok", 0, {"division_code": "L", "division_name": "L"})
        complete_division(rec)
        self.assertEqual(rec.fields["division_code"], "L")
        self.assertEqual(rec.fields["division_name"], "L")


class TestSubjectNames(unittest.TestCase):
    """申请代码 → 学科名富化。名称只在来源没给时才由代码推导。"""

    def setUp(self):
        self.names = (
            {"A01": "代数与几何", "H18": "肿瘤学"},
            {"A0103": "几何学", "A0108": "偏微分方程"},
            {"A010301": "几何基础"},
        )
        self.fill = make_subject_filler(self.names)

    def test_l2_code_fills_l1_and_l2(self):
        rec = Record("1", "grok", 0, {"subject_code": "A0108"})
        self.assertTrue(self.fill(rec))
        self.assertEqual(rec.fields["subject_l1"], "代数与几何")
        self.assertEqual(rec.fields["subject_l2"], "偏微分方程")

    def test_l3_code_fills_all_three(self):
        rec = Record("1", "grok", 0, {"subject_code": "A010301"})
        self.fill(rec)
        self.assertEqual(rec.fields["subject_l1"], "代数与几何")
        self.assertEqual(rec.fields["subject_l2"], "几何学")
        self.assertEqual(rec.fields["subject_l3"], "几何基础")

    def test_source_name_not_overwritten(self):
        rec = Record("1", "atria", 1, {"subject_code": "A0108", "subject_l1": "数学"})
        # subject_l1 保留来源给的，subject_l2 仍由代码推导补上
        self.assertTrue(self.fill(rec))
        self.assertEqual(rec.fields["subject_l1"], "数学")
        self.assertEqual(rec.fields["subject_l2"], "偏微分方程")

    def test_unmappable_code(self):
        rec = Record("1", "grok", 0, {"subject_code": "C1307"})
        self.assertFalse(self.fill(rec))
        self.assertNotIn("subject_l1", rec.fields)

    def test_l_code_has_no_l2(self):
        """L 开头是联合基金，不编入八大学科，一/二级学科名都留空。"""
        rec = Record("1", "grok", 0, {"subject_code": "L04"})
        self.assertFalse(self.fill(rec))
        self.assertNotIn("subject_l1", rec.fields)

    def test_no_code(self):
        rec = Record("1", "grok", 0, {})
        self.assertFalse(self.fill(rec))

    def test_l1_level_code_only_fills_l1(self):
        """3 字符代码是一级学科，只有 L1 名，没有 L2 可填。"""
        rec = Record("1", "grok", 0, {"subject_code": "H18"})
        self.fill(rec)
        self.assertEqual(rec.fields["subject_l1"], "肿瘤学")
        self.assertNotIn("subject_l2", rec.fields)

    def test_undouble(self):
        self.assertEqual(_undouble("æ\x95°å­¦"), "数学")
        # 已经正常的字符串不被破坏
        self.assertEqual(_undouble("数学"), "数学")

    def test_name_conflicts_folded_into_code_conflict(self):
        """名称冲突是代码冲突的下游症状，折叠掉只留根因。"""
        recs = [
            Record("11926306", "grok", 0, {"subject_code": "A0108", "subject_l1": "代数与几何"}),
            Record("11926306", "atria", 1, {"subject_code": "A010301", "subject_l1": "数学"}),
        ]
        _, conflicts = merge(recs)
        fields = {c["field"] for c in conflicts}
        self.assertIn("subject_code", fields)
        self.assertNotIn("subject_l1", fields)


class TestNstrsLinks(unittest.TestCase):
    """NSTRS 报告只补字段不新增项目；三元组匹配要三者全同。"""

    def setUp(self):
        import merge.build as mb
        mb._PI_TITLE_INDEX.clear()
        mb._INSTITUTION_INDEX.clear()

    def tearDown(self):
        import merge.build as mb
        mb._PI_TITLE_INDEX.clear()
        mb._INSTITUTION_INDEX.clear()

    def _index(self, mapping, institutions=None):
        import merge.build as mb
        for (pi, title), nos in mapping.items():
            mb._PI_TITLE_INDEX[(pi, title)] = list(nos)
        for no, inst in (institutions or {}).items():
            mb._INSTITUTION_INDEX[no] = inst

    def test_strict_link_used(self):
        self._index({("张三", "题目甲"): ["11500001"]}, {"11500001": "甲大学"})
        import merge.build as mb
        rows = [{"linked_approval_number": "11500001", "title_zh": "题目甲",
                 "pi": "张三", "institution": "甲大学", "keywords_zh": "k1;k2",
                 "official_report_landing_url": "https://x/y", "program": "面上项目"}]
        links = mb.load_nstrs_links_from_rows(rows, {"11500001"})
        self.assertEqual(links["11500001"]["report_keywords"], "k1;k2")
        self.assertEqual(links["11500001"]["nstrs_rule"], "strict")

    def test_triple_match_only_when_all_three_agree(self):
        # pi+标题能唯一命中，但单位不同 → 不关联
        self._index({("张三", "题目甲"): ["11500001"]}, {"11500001": "甲大学"})
        import merge.build as mb
        rows = [{"linked_approval_number": None, "title_zh": "题目甲",
                 "pi": "张三", "institution": "别的大学", "keywords_zh": "k",
                 "official_report_landing_url": "https://x", "program": "面上"}]
        links = mb.load_nstrs_links_from_rows(rows, {"11500001"})
        self.assertEqual(links, {})

    def test_triple_match_all_agree_links(self):
        # 三者全同才关联（正向用例）
        self._index({("张三", "题目甲"): ["11500001"]}, {"11500001": "甲大学"})
        import merge.build as mb
        rows = [{"linked_approval_number": None, "title_zh": "题目甲",
                 "pi": "张三", "institution": "甲大学", "keywords_zh": "k",
                 "official_report_landing_url": "https://x", "program": "面上"}]
        links = mb.load_nstrs_links_from_rows(rows, {"11500001"})
        self.assertEqual(links["11500001"]["nstrs_rule"], "pi_title_unit")

    def test_ambiguous_not_linked(self):
        self._index({("张三", "题目甲"): ["11500001", "11500002"]},
                    {"11500001": "甲大学", "11500002": "甲大学"})
        import merge.build as mb
        rows = [{"linked_approval_number": None, "title_zh": "题目甲",
                 "pi": "张三", "institution": "甲大学", "keywords_zh": "k",
                 "official_report_landing_url": "https://x", "program": "面上"}]
        links = mb.load_nstrs_links_from_rows(rows, {"11500001", "11500002"})
        self.assertEqual(links, {})

    def test_unknown_grant_not_linked(self):
        # 严格关联指向库内不存在的批准号 → 丢弃（报告不新增项目）
        import merge.build as mb
        rows = [{"linked_approval_number": "99999999", "title_zh": None,
                 "pi": None, "institution": None, "keywords_zh": "k",
                 "official_report_landing_url": "https://x", "program": "面上"}]
        links = mb.load_nstrs_links_from_rows(rows, {"11500001"})
        self.assertEqual(links, {})


class TestMerge(unittest.TestCase):
    """冲突裁决：门户 > LetPub > 第三方交付包；值不同不丢弃，全部登记。"""

    def _pkg(self, no, **kw):
        base = {"title": "题目", "pi": "张三", "institution": "甲大学",
                "award_year": 2015, "grant_type": "面上项目"}
        base.update(kw)
        return Record(no, "pkg", 2, base)

    def _grok(self, no, **kw):
        base = {"title": "题目", "pi": "张三", "institution": "甲大学",
                "award_year": 2015, "grant_type": "面上项目"}
        base.update(kw)
        return Record(no, "grok", 0, base)

    def test_single_source(self):
        merged, conflicts = merge([self._pkg("11500001")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["grant_no"], "11500001")
        self.assertEqual(merged[0]["sources"], '["pkg"]')
        self.assertEqual(conflicts, [])

    def test_same_values_no_conflict(self):
        merged, conflicts = merge([
            self._grok("11500001"), self._pkg("11500001"),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_count"], 2)
        self.assertEqual(conflicts, [])

    def test_conflict_resolved_by_tier_and_logged(self):
        merged, conflicts = merge([
            self._pkg("11500001", institution="乙大学"),
            self._grok("11500001", institution="甲大学"),
        ])
        # grok 层级更高，选中甲大学；乙大学进冲突表，不丢弃
        self.assertEqual(merged[0]["institution"], "甲大学")
        prov = json.loads(merged[0]["provenance"])
        self.assertEqual(prov["institution"], "grok")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["field"], "institution")
        self.assertEqual(conflicts[0]["selected"], "甲大学")
        alts = json.loads(conflicts[0]["alternatives"])
        self.assertEqual(alts[0]["value"], "乙大学")
        self.assertEqual(alts[0]["from"], "pkg")

    def test_label_variance_not_a_conflict(self):
        merged, conflicts = merge([
            self._grok("11500001", grant_type="青年科学基金项目（C类）"),
            self._pkg("11500001", grant_type="青年科学基金项目"),
        ])
        self.assertEqual(merged[0]["grant_type"], "青年科学基金项目（C类）")
        self.assertEqual(merged[0]["grant_type_raw"], "青年科学基金项目（C类）")
        self.assertEqual(conflicts, [])

    def test_date_precision_difference_not_a_conflict(self):
        merged, conflicts = merge([
            Record("11500001", "atria", 1, {"begin_date": "2016-01"}),
            Record("11500001", "pkg", 2, {"begin_date": "2016-01-01"}),
        ])
        self.assertEqual(merged[0]["begin_date"], "2016-01")
        self.assertEqual(conflicts, [])

    def test_amount_close_not_a_conflict(self):
        merged, conflicts = merge([
            self._grok("11500001", amount_wan=48.0),
            self._pkg("11500001", amount_wan=48.02),
        ])
        self.assertEqual(merged[0]["amount_wan"], 48.0)
        self.assertEqual(conflicts, [])

    def test_fields_aligned_to_merge_vocab(self):
        merged, _ = merge([self._pkg("11500001")])
        for f in MERGE_FIELDS:
            self.assertIn(f, merged[0])


class TestReviewFixtures(unittest.TestCase):
    """V2-002 / V2-006 / V2-007 的纯函数与合并级回归。"""

    def _pkg(self, no, **kw):
        base = {"title": "题目", "pi": "张三", "institution": "甲大学",
                "award_year": 2015, "grant_type": "面上项目"}
        base.update(kw)
        return Record(no, "pkg", 2, base)

    def _grok(self, no, **kw):
        base = {"title": "题目", "pi": "张三", "institution": "甲大学",
                "award_year": 2015, "grant_type": "面上项目"}
        base.update(kw)
        return Record(no, "grok", 0, base)

    # ---- V2-002 关键词拆分 ----

    def test_split_keywords_chinese_and_english_semicolons(self):
        self.assertEqual(_split_keywords("甲词；乙词;丙词"), ["甲词", "乙词", "丙词"])

    def test_split_keywords_dedup_within_project(self):
        self.assertEqual(_split_keywords("甲词;甲词；乙词; 甲词"), ["甲词", "乙词"])

    def test_split_keywords_keeps_comma_inside_term(self):
        # 科学名称里的逗号不能当分隔符
        self.assertEqual(_split_keywords("水稻,小麦"), ["水稻,小麦"])

    # ---- V2-006 raw 保留与金额标记同源 ----

    def test_grant_type_raw_keeps_source_label(self):
        merged, _ = merge([self._grok("11500001", grant_type="青年科学基金项目")])
        self.assertEqual(merged[0]["grant_type"], "青年科学基金项目（C类）")
        self.assertEqual(merged[0]["grant_type_raw"], "青年科学基金项目")

    def test_amount_marker_follows_amount_source(self):
        # grok 有金额但无推断标记；pkg 标了推断——标记必须跟随金额的胜出源 grok，而非 pkg
        pkg = Record("11500001", "pkg", 2, {"amount_wan": 600000.0, "amount_inferred": 1,
                                            "title": "题目", "pi": "张三",
                                            "institution": "甲大学", "grant_type": "面上项目"})
        merged, _ = merge([self._grok("11500001", amount_wan=60.0), pkg])
        self.assertEqual(merged[0]["amount_wan"], 60.0)
        self.assertEqual(merged[0]["amount_inferred"], 0)
        prov = json.loads(merged[0]["provenance"])
        self.assertEqual(prov.get("amount_inferred"), "grok")

    # ---- V2-007 冲突逐条分类 ----

    def test_classify_code_prefix_all(self):
        cls = _classify_conflict("subject_code", "A01", [{"value": "A0101"}, {"value": "A0102"}])
        self.assertEqual(cls, "代码层级差（前缀关系，待核语义）")

    def test_classify_code_mixed_falls_back_to_pending(self):
        # 一个候选是前缀、另一个不是 → 更保守的分类
        cls = _classify_conflict("subject_code", "A01", [{"value": "A0101"}, {"value": "B99"}])
        self.assertIn("待核", cls)
        self.assertNotIn("前缀", cls)

    def test_classify_institution_marks_spotty_evidence(self):
        cls = _classify_conflict("institution", "甲大学", [{"value": "乙大学"}])
        self.assertIn("已抽查部分", cls)

    def test_classify_never_claims_non_error(self):
        for field in ("subject_code", "institution", "title", "grant_type", "pi", "unknown_field"):
            cls = _classify_conflict(field, "甲", [{"value": "乙"}])
            self.assertNotIn("不是错误", cls)
            self.assertNotIn("非错误", cls)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
