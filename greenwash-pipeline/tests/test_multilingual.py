# Traditional (Taiwan) and Simplified (mainland) Chinese support, plus English regression guards.
import unittest

from greenwash import lang
from greenwash.claims import extract_claims, fields_for
from greenwash.tables import claim_segments, parse_tables

HANT = "本公司承諾於2030年前減少碳排放40%，並以2019年為基準年。"
HANS = "本公司承诺于2030年前减少碳排放40%，并以2019年为基准年。"


class LanguageTests(unittest.TestCase):
    def test_script_detection(self):
        self.assertEqual(lang.script_of("Scope 1 emissions fell."), "en")
        self.assertEqual(lang.script_of(HANT), "zh-hant")
        self.assertEqual(lang.script_of(HANS), "zh-hans")
        self.assertEqual(lang.script_of(""), "en")

    def test_roc_years_convert(self):
        self.assertEqual(lang.roc_to_ce(111), 2022)
        self.assertEqual(lang.years_in("民國111年度永續報告書"), [2022])
        self.assertEqual(lang.years_in("中华民国113年"), [2024])

    def test_years_next_to_chinese_are_found(self):
        # \b would fail here: both the digit and the Chinese character are word characters.
        self.assertEqual(lang.years_in("承諾2050年淨零"), [2050])
        self.assertEqual(lang.years_in("以2030年為目標，較2019年基準"), [2030, 2019])

    def test_bare_digits_are_not_roc_years(self):
        self.assertEqual(lang.years_in("第111頁"), [])
        self.assertEqual(lang.strip_years("民國111年度 2022 2021").strip(), "")

    def test_unit_multipliers(self):
        self.assertEqual(lang.unit_to_tonnes("公噸"), 1.0)
        self.assertEqual(lang.unit_to_tonnes("千公噸"), 1e3)
        self.assertEqual(lang.unit_to_tonnes("萬公噸"), 1e4)
        self.assertEqual(lang.unit_to_tonnes("万公吨"), 1e4)
        self.assertEqual(lang.unit_to_tonnes("百萬噸"), 1e6)
        self.assertEqual(lang.unit_to_tonnes("億噸"), 1e8)
        self.assertEqual(lang.unit_to_tonnes("ktCO2e"), 1e3)

    def test_scope_labels_in_three_scripts(self):
        self.assertEqual(lang.scope_numbers("Scope 2 emissions"), [2])
        self.assertEqual(lang.scope_numbers("範疇一 排放量"), [1])
        self.assertEqual(lang.scope_numbers("范围三"), [3])
        self.assertEqual(lang.scope_numbers("間接排放"), [2])
        self.assertEqual(lang.scope_numbers("範疇一及範疇二"), [1, 2])


class ChineseTableTests(unittest.TestCase):
    def test_traditional_table_with_chinese_units(self):
        rows, warnings = parse_tables(
            "項目 單位 2022 2021 2020\n"
            "範疇一 公噸CO2e 12,345 11,111 10,000\n"
            "範疇二 公噸CO2e 67,890 70,000 71,000")
        got = [(r['metric'], r['year'], r['value']) for r in rows]
        want = [('scope1', 2022, 12345.0), ('scope1', 2021, 11111.0), ('scope1', 2020, 10000.0),
                ('scope2', 2022, 67890.0), ('scope2', 2021, 70000.0), ('scope2', 2020, 71000.0)]
        self.assertEqual(warnings, [])
        self.assertEqual(got, want)

    def test_simplified_table(self):
        rows, _ = parse_tables("项目 单位 2024 2023\n范围一 公吨CO2e 1,000 2,000")
        got = [(r['metric'], r['year'], r['value']) for r in rows]
        self.assertEqual(got, [('scope1', 2024, 1000.0), ('scope1', 2023, 2000.0)])

    def test_roc_year_header(self):
        rows, _ = parse_tables("項目 單位 民國111年 民國110年\n範疇一 公噸CO2e 12,345 11,111")
        self.assertEqual([(r['year'], r['value']) for r in rows], [(2022, 12345.0), (2021, 11111.0)])

    def test_magnitude_units_are_not_guessed(self):
        rows, _ = parse_tables("項目 單位 2024 2023\n範疇一 萬公噸CO2e 3 4")
        self.assertEqual([r['value'] for r in rows], [30000.0, 40000.0])

    def test_combined_scope_label_abstains(self):
        rows, _ = parse_tables("項目 單位 2024 2023\n範疇一及範疇二 公噸CO2e 100 200")
        self.assertEqual(rows, [])

    def test_chinese_claim_segment_not_dropped(self):
        # A whitespace word count would drop every Chinese segment; twelve characters is the bar.
        text = "本公司積極推動減碳，溫室氣體排放量較基準年下降百分之三十"
        self.assertEqual(len(list(claim_segments(text))), 1)


class ChineseClaimTests(unittest.TestCase):
    def test_target_versus_baseline_year_in_both_scripts(self):
        for text in (HANT, HANS):
            f, _ = fields_for(text)
            self.assertEqual(f['claim_type'], 'future_target', text)
            self.assertEqual(f['target_year'], 2030, text)
            self.assertEqual(f['baseline_year'], 2019, text)

    def test_realized_outranks_target_noun_in_chinese(self):
        f, _ = fields_for("本公司已達成2030年減碳目標，較2019年減少40%。")
        self.assertEqual(f['claim_type'], 'realized_result')

    def test_adverse_movement_in_chinese_is_a_candidate(self):
        block = dict(text="本公司碳排放量較去年增加百分之五，溫室氣體排放持續上升。",
                     raw_text="", block_id='p1-b1', page=1, bbox=None)
        claims = extract_claims([block], "")
        self.assertEqual(len(claims), 1)
        # Chinese does not mark tense, so a bare 增加/上升 is captured but stays unclassified
        # rather than being asserted as a realized result the sentence does not state.
        self.assertIn(claims[0]['fields']['claim_type'], {'realized_result', 'unclassified'})

    def test_marked_adverse_movement_in_chinese_is_realized(self):
        block = dict(text="本公司碳排放量已增加了百分之五，較基準年上升了。",
                     raw_text="", block_id='p1-b1', page=1, bbox=None)
        self.assertEqual(extract_claims([block], "")[0]['fields']['claim_type'], 'realized_result')

    def test_negation_in_chinese(self):
        _, flags = fields_for("本公司尚未達成減碳目標，溫室氣體排放量未達預期。")
        self.assertIn('NEGATION_REVIEW', flags)

    def test_assurance_in_chinese(self):
        f, _ = fields_for("本公司溫室氣體排放量已取得第三方查證，碳排放數據經認證。")
        self.assertEqual(f['claim_type'], 'assurance')

    def test_intensity_in_chinese(self):
        f, _ = fields_for("每單位產品溫室氣體排放強度較基準年下降。")
        self.assertEqual(f['metric'], 'intensity')


class EnglishRegressionTests(unittest.TestCase):
    def test_english_claim_fields_unchanged(self):
        f, _ = fields_for("We reduced our carbon emissions 30% against 2019.")
        self.assertEqual(f['claim_type'], 'realized_result')
        self.assertEqual(f['baseline_year'], 2019)
        f, _ = fields_for('Our target is to reduce emissions 30% by 2030.')
        self.assertEqual((f['claim_type'], f['target_year']), ('future_target', 2030))

    def test_english_table_unchanged(self):
        rows, _ = parse_tables("KPI Unit 2024 2023\nScope 1 tonnes CO2e 1 2")
        self.assertEqual([r['value'] for r in rows], [1.0, 2.0])


if __name__ == '__main__':
    unittest.main()
