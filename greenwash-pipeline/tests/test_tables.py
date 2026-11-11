import unittest
from pathlib import Path
from greenwash.tables import parse_tables, claim_segments


class TableTests(unittest.TestCase):
    def test_mtr_fifteen_gold_cells(self):
        text = (Path(__file__).parent/'fixtures/mtr-page92.txt').read_text()
        rows, warnings = parse_tables(text)
        expected = {
            'scope1': [40949,40611,42188,42466,51776],
            'scope2': [976574,1035654,1012456,1075885,1048178],
            'scope3': [7290,3137,3003,1512482,1514495],
        }
        actual = {(r['metric'],r['year']):r['value'] for r in rows}
        gold = {(m,y):v for m,vs in expected.items() for y,v in zip(range(2020,2025),vs)}
        self.assertEqual(actual,gold)
        self.assertEqual(len(rows),15)
        self.assertEqual(warnings,[])
        self.assertTrue(all(r['header_quote'] and r['raw_cell'] for r in rows))

    def test_repeated_entity_years_abstain(self):
        rows,warnings=parse_tables('KPI Unit 2023 2024 2023 2024\nScope 1 tonnes CO2e 1 2 3 4')
        self.assertEqual(rows,[])
        self.assertEqual(warnings[0]['code'],'AMBIGUOUS_MULTI_ENTITY_YEAR_HEADER')

    def test_missing_cell_is_not_zero(self):
        rows,_=parse_tables('KPI Unit 2023 2024\nScope 1 tonnes CO2e n/a 100')
        self.assertIsNone(rows[0]['value'])
        self.assertEqual(rows[1]['year'],2024)

    def test_count_mismatch_abstain(self):
        rows,w=parse_tables('KPI Unit 2022 2023 2024\nScope 1 tonnes CO2e 1 2')
        self.assertEqual(rows,[])
        self.assertEqual(w[0]['code'],'TABLE_COLUMN_MISMATCH')

    def test_footnote_does_not_become_value(self):
        rows,_=parse_tables('KPI Unit 2023 2024\nScope 1 tonnes CO2e 123[2] 456[3]')
        self.assertEqual([r['value'] for r in rows],[123,456])

    def test_unit_inside_label_and_million_tonnes(self):
        rows,w=parse_tables('Environmental 2024 2023 2022\n'
                            'Direct (Scope 1) GHG emissions (million T of CO2e) [4]   6.05   6.64   6.77')
        self.assertEqual([(r['year'],r['value']) for r in rows],
                         [(2024,6050000.0),(2023,6640000.0),(2022,6770000.0)])
        self.assertEqual(w,[])

    def test_million_and_mega_tonne_forms(self):
        for line in ('Scope 1 emissions million tonnes CO2e 1.2 1.5',
                     'Scope 1 emissions MtCO2e 1.2 1.5'):
            rows,_=parse_tables('KPI Unit 2024 2023\n'+line)
            self.assertEqual([r['value'] for r in rows],[1200000.0,1500000.0],line)

    def test_short_caption_headers_but_sentences_do_not(self):
        rows,_=parse_tables('Environmental 2024 2023 2022\nScope 1 tonnes CO2e 1 2 3')
        self.assertEqual([r['value'] for r in rows],[1.0,2.0,3.0])
        rows,w=parse_tables('In 2020, 2021 and 2022 we cut emissions.\nScope 1 tonnes CO2e 100 200')
        self.assertEqual(rows,[])
        self.assertEqual(w[0]['code'],'TABLE_MISSING_YEAR_HEADER')

    def test_columns_not_concatenated(self):
        text='We aim to reduce our absolute carbon emissions further.          Our renewable energy projects are still in early development.'
        segments=list(claim_segments(text))
        self.assertEqual(len(segments),2)
        self.assertTrue(all(not ('further.' in s and 'projects' in s) for _,s in segments))

    def test_index_is_not_company_claim(self):
        text='An issuer shall reduce its carbon emissions over the reporting period.\nContent Index for Sustainability Reporting'
        self.assertEqual(list(claim_segments(text)),[])

    def test_heading_reference_dropped(self):
        self.assertEqual(list(claim_segments('Reducing Greenhouse Gas Emissions                 59')),[])
