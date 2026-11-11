import tempfile
import unittest
from pathlib import Path
from greenwash.tables import parse_tables
from greenwash.claims import fields_for,extract_claims
from greenwash.layout import normalize,pdf_blocks
from greenwash.pipeline import extract


class RobustnessTests(unittest.TestCase):
    def test_realized_verb_outranks_bare_target_noun(self):
        for text in ("We achieved our target of reducing emissions by 30% against 2019.",
                     "Our emissions reduction target was achieved in 2024."):
            f,flags=fields_for(text)
            self.assertEqual(f['claim_type'],'realized_result',text)

    def test_target_noun_without_modal_is_still_a_future_target(self):
        f,_=fields_for('Our target is to reduce emissions 30% by 2030.')
        self.assertEqual(f['claim_type'],'future_target')
        self.assertEqual(f['target_year'],2030)

    def test_adverse_movement_becomes_a_candidate(self):
        for text in ('Our carbon emissions rose 5% across the reporting year.',
                     'Carbon emissions increased steadily across the reporting year.',
                     'Our emissions intensity fell by 4% across the reporting year.'):
            claims=extract_claims([dict(text=text,raw_text=text,block_id='p1-b1',page=1,bbox=None)],text)
            self.assertEqual(len(claims),1,text)
            self.assertEqual(claims[0]['fields']['claim_type'],'realized_result',text)

    def test_short_claim_is_reported_not_silently_dropped(self):
        # Short statements, including adverse ones, stay below the review threshold but must
        # still be reported rather than disappearing.
        for text in ('We cut emissions 40%.','Emissions rose 5% in 2024.'):
            skipped=[]
            claims=extract_claims([dict(text=text,raw_text=text,block_id='p1-b1',page=1,bbox=None)],text,skipped)
            self.assertEqual(claims,[],text)
            self.assertEqual([s['reason'] for s in skipped],['SHORT_SENTENCE_BELOW_REVIEW_THRESHOLD'],text)

    def test_quantified_sentence_without_action_verb_is_reported(self):
        text='The fleet accounted for 12% of total carbon output in the reporting year.'
        skipped=[]
        extract_claims([dict(text=text,raw_text=text,block_id='p1-b1',page=1,bbox=None)],text,skipped)
        self.assertEqual([s['reason'] for s in skipped],['QUANTIFIED_ENV_SENTENCE_WITHOUT_ACTION_VERB'])

    def test_block_dump_is_not_reported_as_sentence(self):
        text='Carbon emissions 2024 2023 '+('■ 512,412 91,738 '*40)
        skipped=[]
        extract_claims([dict(text=text,raw_text=text,block_id='p1-b1',page=1,bbox=None)],text,skipped)
        self.assertEqual(skipped,[])

    def test_descending_years_and_unicode_units(self):
        rows,w=parse_tables('Indicator Unit 2024 2023\nDirect emissions (Scope 1) tonnes CO₂e 1,234 2,345')
        self.assertEqual([(r['year'],r['value']) for r in rows],[(2024,1234),(2023,2345)])
        self.assertEqual(w,[])

    def test_thousand_units(self):
        rows,_=parse_tables('Year 2023 2024\nScope 2 thousand tonnes CO2-e 1.2 1.5')
        self.assertEqual([r['value'] for r in rows],[1200,1500])

    def test_combined_scope_not_scope1(self):
        rows,_=parse_tables('Year 2023 2024\nScope 1 and 2 tonnes CO2e 100 200')
        self.assertEqual(rows,[])

    def test_co2_not_assumed_co2_equivalent(self):
        rows,_=parse_tables('Year 2023 2024\nScope 1 tonnes CO2 100 200')
        self.assertEqual(rows,[])

    def test_malformed_number_abstains(self):
        for cell in ('12,34','1.234,56','(123)','1 234'):
            rows,w=parse_tables('Year 2023 2024\nScope 1 tonnes CO2e '+cell+' 200')
            self.assertEqual(rows,[])
            self.assertTrue(w)

    def test_prose_years_not_header(self):
        rows,w=parse_tables('Our metrics changed between 2023 and 2024.\nScope 1 tonnes CO2e 100 200')
        self.assertEqual(rows,[])
        self.assertEqual(w[0]['code'],'TABLE_MISSING_YEAR_HEADER')

    def test_future_years_explicit(self):
        f,flags=fields_for('We aim to reduce absolute carbon emissions by 30% by 2030 against 2020.')
        self.assertEqual((f['baseline_year'],f['target_year']),(2020,2030))
        self.assertEqual(f['claim_type'],'future_target')
        self.assertEqual(f['assessment_status'],'not_assessed')

    def test_negative_result_not_positive_achievement(self):
        f,flags=fields_for('We have not reduced our carbon emissions compared to 2020.')
        self.assertEqual(f['claim_type'],'unclassified')
        self.assertIn('NEGATION_REVIEW',flags)

    def test_mixed_metric_abstains(self):
        f,flags=fields_for('We reduced carbon intensity while absolute emissions increased this year.')
        self.assertIsNone(f['metric'])
        self.assertIn('MIXED_METRIC_NEEDS_SPLIT',flags)

    def test_fragment_is_flagged(self):
        _,flags=fields_for('We aim to reduce our carbon emissions through a')
        self.assertIn('INCOMPLETE_SENTENCE',flags)

    def test_traceable_multiline_quote(self):
        raw='We reduced emissions intensity by\n20% compared to 2020.'
        text=normalize(raw)
        block=dict(text=text,raw_text=raw,block_id='p1-b1',page=1,bbox=None)
        claims=extract_claims([block],text)
        self.assertEqual(len(claims),1)
        c=claims[0]
        self.assertEqual(text[c['char_start']:c['char_end']],c['quote'])
        self.assertEqual(c['fields']['metric'],'intensity')

    def test_unknown_publication_and_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'empty.txt';p.write_text('This report contains no relevant financial or environmental information.')
            b=extract(p,'D',None,'2026-10-03')
            self.assertIsNone(b['document']['published_at'])
            self.assertFalse(b['quality_summary']['scoring_ready'])
            codes={w['code'] for w in b['warnings']}
            self.assertIn('PUBLICATION_DATE_UNKNOWN_NO_POINT_IN_TIME_ELIGIBILITY',codes)
            self.assertIn('NO_NUMERIC_OBSERVATIONS_NOT_ZERO_EMISSIONS',codes)

    def test_spatial_columns_remain_separate(self):
        try: import fitz
        except ImportError: self.skipTest('PDF optional dependency not installed')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'columns.pdf'
            doc=fitz.open();page=doc.new_page(width=600,height=800)
            page.insert_textbox(fitz.Rect(30,80,270,190),'We reduced our carbon emissions by 20% compared to 2020.',fontsize=12)
            page.insert_textbox(fitz.Rect(330,80,570,190),'We aim to reduce absolute carbon emissions by 2030 against 2020.',fontsize=12)
            doc.save(p);doc.close()
            blocks=pdf_blocks(p)[0]
            candidates=extract_claims(blocks,'')
            self.assertEqual(len(candidates),2)
            self.assertTrue(all(c['block']['bbox'][2]-c['block']['bbox'][0]<300 for c in candidates))
            self.assertFalse(any('We reduced' in c['quote'] and 'We aim' in c['quote'] for c in candidates))

    def test_target_heading_context_is_explicit(self):
        header=dict(text='Our 2030 SBTs, based on 2019 base year levels, are:',raw_text='',block_id='h',page=1,bbox=[20,20,250,40])
        body=dict(text='Railway: Reduce carbon emissions by 46.2% per passenger kilometre.',raw_text='',block_id='b',page=1,bbox=[25,50,250,90])
        result=extract_claims([header,body],'')[0]
        self.assertEqual(result['fields']['target_year'],2030)
        self.assertEqual(result['fields']['baseline_year'],2019)
        self.assertEqual(result['context_evidence']['block_id'],'h')

    def test_investment_properties_heading_not_claim(self):
        text='Investment Properties (Scope 1 and Scope 2 Emissions)'
        self.assertEqual(extract_claims([dict(text=text,bbox=None)],''),[])

    def test_supporting_city_target_not_issuer_target(self):
        f,flags=fields_for("As we support the city's journey to carbon neutrality by 2050, we are committed to improvements.")
        self.assertIsNone(f['target_year'])
        self.assertIn('TARGET_ACTOR_UNRESOLVED',flags)

    def test_not_only_is_not_negative_achievement(self):
        _,flags=fields_for('We reduced not only our carbon emissions but also energy consumption.')
        self.assertNotIn('NEGATION_REVIEW',flags)
