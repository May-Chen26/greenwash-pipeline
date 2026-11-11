# Guards that make the package safe to depend on: one version, a stable surface, stdlib-only import.
import importlib.metadata
import subprocess
import sys
import unittest

import greenwash
from greenwash import pipeline


class VersionTests(unittest.TestCase):
    def test_package_and_rules_version_agree(self):
        # Two copies of a version drifted apart once already (module 0.4.0, pyproject 0.5.0).
        self.assertEqual(pipeline.VERSION, "rules-" + greenwash.__version__)

    def test_installed_metadata_matches_module(self):
        try:
            installed = importlib.metadata.version("greenwash-pipeline")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("running from a source tree, not an installed distribution")
        self.assertEqual(installed, greenwash.__version__)


class PublicSurfaceTests(unittest.TestCase):
    def test_exports_are_callable(self):
        for name in ("extract", "apply_review", "review_html", "EXTRACTOR_VERSION"):
            self.assertTrue(hasattr(greenwash, name), name)
        self.assertTrue(callable(greenwash.extract))
        self.assertTrue(callable(greenwash.apply_review))
        self.assertTrue(callable(greenwash.review_html))

    def test_import_does_not_pull_in_pymupdf(self):
        # The core must stay standard library only; PyMuPDF is an optional PDF extra.
        code = "import sys, greenwash; print('fitz' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
