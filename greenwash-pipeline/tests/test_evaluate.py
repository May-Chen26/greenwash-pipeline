import unittest
from greenwash.evaluate import evaluate


class EvaluationTests(unittest.TestCase):
    def test_duplicate_predictions_do_not_inflate_recall(self):
        f=dict(metric='scope1',year=2024,unit='tCO2e',value=10)
        r=dict(kind='observation',evidence=dict(page=1),fields=f)
        b=dict(document=dict(sha256='a'),records=[r,r])
        g=dict(document_sha256='a',annotated_pages=[1],annotated_metrics=['scope1'],observations=[dict(f,page=1)])
        result=evaluate(b,g)
        self.assertEqual(result['precision'],0.5)
        self.assertEqual(result['recall'],1)

    def test_mismatched_document_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(dict(document=dict(sha256='a')),dict(document_sha256='b'))
