import copy
import tempfile
import unittest
from pathlib import Path

from greenwash.pipeline import (extract, apply_review, review_html, validate_fields,
                                check_page_alignment)

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_report.txt"


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.bundle = extract(SAMPLE, "DEMO", "2025-04-01", "2026-10-03", True)

    def test_units_and_scope2_are_separate(self):
        obs = [r for r in self.bundle["records"] if r["kind"] == "observation"]
        self.assertEqual(len(obs), 5)
        self.assertEqual(next(r["fields"]["value"] for r in obs if r["fields"]["metric"] == "revenue"), 200000000)
        self.assertEqual({r["fields"]["scope2_method"] for r in obs if r["fields"]["metric"] == "scope2"}, {"location-based", "market-based"})

    def test_missing_year_not_filled_from_header(self):
        r = next(r for r in self.bundle["records"] if r["kind"] == "observation" and r["fields"]["value"] == 9000)
        self.assertIsNone(r["fields"]["year"])

    def test_future_and_intensity(self):
        claims = [r for r in self.bundle["records"] if r["kind"] == "claim"]
        self.assertTrue(any(r["fields"]["claim_type"] == "future_target" for r in claims))
        self.assertTrue(any(r["fields"]["metric"] == "intensity" for r in claims))
        self.assertTrue(all(r["fields"]["assessment_status"] == "not_assessed" for r in claims))

    def test_point_in_time_gate(self):
        with self.assertRaises(ValueError):
            extract(SAMPLE, "DEMO", "2025-04-01", "2024-12-31")

    def decision(self):
        r = self.bundle["records"][0]
        fields = dict(r["fields"], geography="global", organizational_boundary="consolidated_group", period_basis="calendar_year")
        return {"document_id": self.bundle["document"]["id"], "reviewer": "test reviewer",
                "decisions": [{"id": r["id"], "status": "accepted", "fields": fields}]}

    def test_review_preserves_evidence_and_original(self):
        result = apply_review(self.bundle, self.decision())
        self.assertEqual(result["records"][0]["evidence"], self.bundle["records"][0]["evidence"])
        self.assertIsNone(result["records"][0]["review"]["original_fields"]["geography"])
        self.assertEqual(self.bundle["records"][0]["review_status"], "pending")
        self.assertEqual(sum(r["review_status"] == "accepted" for r in result["records"]), 1)

    def test_missing_boundary_blocked(self):
        d = self.decision()
        d["decisions"][0]["fields"]["geography"] = None
        with self.assertRaises(ValueError):
            apply_review(self.bundle, d)

    def test_wrong_document_and_duplicate_blocked(self):
        d = self.decision()
        d["document_id"] = "wrong"
        with self.assertRaises(ValueError):
            apply_review(self.bundle, d)
        d = self.decision()
        d["decisions"].append(copy.deepcopy(d["decisions"][0]))
        with self.assertRaises(ValueError):
            apply_review(self.bundle, d)

    def test_nonfinite_and_wrong_unit_blocked(self):
        for value, unit in [(float("nan"), "tCO2e"), (True, "tCO2e"), (5, "USD")]:
            f = self.decision()["decisions"][0]["fields"]
            f.update(value=value, unit=unit)
            with self.assertRaises(ValueError):
                validate_fields("observation", f)

    def test_claim_review_cannot_assert_truth(self):
        claim = next(r for r in self.bundle["records"] if r["kind"] == "claim")
        f = dict(claim["fields"], assessment_status="supported")
        with self.assertRaises(ValueError):
            validate_fields("claim", f)

    def test_html_escapes_document_content(self):
        self.bundle["records"][0]["evidence"]["quote"] = '<script>alert("bad")</script>'
        page = review_html(self.bundle)
        self.assertNotIn('<script>alert("bad")</script>', page)
        self.assertIn("&lt;script&gt;", page)

    def test_claim_location_is_not_rendered_as_none(self):
        # Claims are located by block_id and carry no line number.
        self.assertIsNone(next(r for r in self.bundle["records"] if r["kind"] == "claim")["evidence"]["line"])
        self.assertNotIn(":None", review_html(self.bundle))

    def test_page_alignment_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            check_page_alignment(["a", "b", "c"], [["block"], ["block"]])

    def test_captured_observation_is_not_reported_as_skipped(self):
        # "2024 Scope 1 emissions: 12,000 tCO2e." is captured as an observation by PATTERNS;
        # it must not also appear as an omission.
        self.assertEqual(self.bundle["skipped_candidates"], [])
        self.assertNotIn("CLAIM_SENTENCES_OMITTED_FROM_REVIEW_QUEUE",
                         {w["code"] for w in self.bundle["warnings"]})

    def test_omitted_sentences_are_surfaced_to_the_reviewer(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "omitted.txt"
            p.write_text("Waste accounted for 12% of carbon output in the reporting year.\n", encoding="utf-8")
            b = extract(p, "D", "2025-01-01", "2025-01-02")
            self.assertEqual(len(b["skipped_candidates"]), 1)
            self.assertEqual(b["quality_summary"]["skipped_claim_candidates"], 1)
            self.assertIn("CLAIM_SENTENCES_OMITTED_FROM_REVIEW_QUEUE",
                          {w["code"] for w in b["warnings"]})
            page = review_html(b)
            self.assertIn("未进入复核队列", page)
            self.assertIn("Waste accounted for 12%", page)

    def test_stable_ids(self):
        other = extract(SAMPLE, "DEMO", "2025-04-01", "2026-10-03", True)
        self.assertEqual([r["id"] for r in self.bundle["records"]], [r["id"] for r in other["records"]])

    def test_page_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "pages.txt"
            p.write_text("First page no metrics\f2024 Scope 1 emissions: 1 ktCO2e.", encoding="utf-8")
            b = extract(p, "D", "2025-01-01", "2025-01-02")
            self.assertEqual(b["records"][0]["evidence"]["page"], 2)
            self.assertEqual(b["records"][0]["fields"]["value"], 1000)


if __name__ == "__main__":
    unittest.main()
