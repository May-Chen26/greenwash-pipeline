"""Evidence-first report extraction. No company scoring or truth adjudication.

The package reads English, Traditional Chinese (Taiwan) and Simplified Chinese (mainland)
sustainability reports and returns *candidates* with page, quote and a source span. It never
decides whether a claim is true and never produces a score.

Public surface (everything else is internal and may move):

* ``extract(path, company, published_at, as_of, synthetic=False)`` — one document to a bundle.
* ``apply_review(bundle, review)`` — merge a reviewer's decisions into a bundle.
* ``review_html(bundle)`` — the review page for that bundle.
* ``EXTRACTOR_VERSION`` — the rules version stamped into every bundle.

Only the standard library is required. PDF input additionally needs the ``pdf`` extra.
"""

from greenwash.pipeline import VERSION as EXTRACTOR_VERSION
from greenwash.pipeline import apply_review, extract, review_html

# The single source of truth for the package version: pyproject.toml reads it from here.
__version__ = "0.5.0"

__all__ = ["EXTRACTOR_VERSION", "__version__", "apply_review", "extract", "review_html"]
