"""Language mechanics for the three scripts the reports arrive in.

Hong Kong and US issuers file in English. Taiwan (TWSE/TPEx) files in Traditional Chinese and
mainland issuers file in Simplified Chinese. This module holds only the mechanics the rest of
the package needs, so the rules stay in one auditable place and the package keeps its
standard-library-only promise.

Three things the rest of the code relies on:

* ``years_in`` / ``strip_years`` read 民國 (ROC) years and never use ``\\b``, which Python's
  ``re`` treats as a boundary only between word characters: in ``2050淨零`` the digit and the
  Chinese character are both word characters, so ``\\b`` finds nothing and the year is lost.
* ``scope_numbers`` reads the scope label in all three scripts (Scope 2, 範疇二, 范围二) and
  returns every scope it sees, so "Scope 1 and 2" still abstains.
* ``unit_to_tonnes`` converts a disclosed unit to tonnes CO2e, including the Chinese
  千/萬/百萬/億 prefixes.
"""
import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# CO2e, with both the ASCII 2 and the subscript ₂ that PDFs emit, plus the written-out Chinese
# form. The trailing "e" is required: a bare CO2 is not a CO2e figure and must not be counted.
CO2E = r"(?:(?:CO2|CO\u2082)\s*-?\s*e|二氧化碳當量|二氧化碳当量)"

_GREG = r"(?<![0-9])(?:19|20)\d{2}(?![0-9])"
_ROC = r"(?:中華民國|中华民国|民國|民国)\s*(\d{2,3})\s*(?:年度|年)?"
YEAR = re.compile(_GREG)
YEAR_ANY = re.compile(f"(?:{_GREG})|(?:{_ROC})")
ROC_OFFSET = 1911

_SCOPE_WORD = {**{"一": 1, "二": 2, "三": 3}, **{"1": 1, "2": 2, "3": 3}}
_SCOPE_EN = re.compile(r"\bscope\s*([123])\b", re.I)
_SCOPE_ZH = re.compile(r"(?:範疇|范畴|范围)\s*([一二三123])")
_SCOPE_FLOW = re.compile(r"(直接排放|間接排放|间接排放)")
_FLOW_SCOPE = {"直接排放": 1, "間接排放": 2, "间接排放": 2}

UNIT_EN = (
    r"(?:thousand\s+(?:metric\s+)?tonnes?\s+(?:of\s+)?{c}"
    r"|million\s+(?:metric\s+)?(?:tonnes?|t)\s+(?:of\s+)?{c}"
    r"|(?:metric\s+)?tonnes?\s+(?:of\s+)?{c}"
    r"|kt{c}|Mt{c}|t{c})"
).format(c=CO2E)
# The magnitude prefix and 公 can both appear: 公噸, 萬公噸, 百萬公噸. Longer prefixes first so
# 百萬 is not read as 萬 followed by an unmatched 百. Taiwan reports also write the unit joined
# to its meaning with a dash, as in 公噸－二氧化碳當量, so the separator is optional.
UNIT_ZH = r"(?:(?:百萬|百万|億|亿|萬|万|千)?公?[噸吨](?:\s*[-\u2013\u2014\uff0d]?\s*{c})?)".format(c=CO2E)
UNIT = r"(?:{en}|{zh})".format(en=UNIT_EN, zh=UNIT_ZH)


def has_cjk(text):
    """True if the text contains any Chinese character."""
    return bool(CJK_RE.search(text or ""))


# Characters used to tell the two Chinese scripts apart. These are common in ESG reports and
# differ between the scripts; counting them is cheap and needs no full converter.
HANT_ONLY = set("資標諾實達認為體溫室該計畫際風險機會萬億噸範疇圍強單產營績虧損罰違規訴訟減電廠綠淨續報節約區總額環境檢測驗證機構標準化轉型趨勢執行落實營運財務獲利")
HANS_ONLY = set("资标诺实达认为体温室该计划际风险机会万亿吨范畴围强单产营绩亏损罚违规诉讼减电厂绿净续报节约区总额环境检测验证机构标准化转型趋势执行落实营运财务获利")


def script_of(text):
    """'en', 'zh-hant', 'zh-hans', 'zh' or 'mixed' for a block of report text."""
    if not text:
        return "en"
    cjk = len(CJK_RE.findall(text))
    if cjk == 0:
        return "en"
    hant = sum(1 for ch in text if ch in HANT_ONLY)
    hans = sum(1 for ch in text if ch in HANS_ONLY)
    if hant == hans == 0:
        latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
        return "mixed" if latin > cjk else "zh"
    return "zh-hant" if hant > hans else "zh-hans"


def roc_to_ce(roc_year):
    """Convert a 民國 (Republic of China) year to the Gregorian year."""
    return int(roc_year) + ROC_OFFSET


def years_in(text, roc=True):
    """Gregorian years in order of appearance, including converted, marked 民國 years.

    Only explicitly marked ROC years convert: a bare "111" is a page number or a figure.
    """
    out = []
    for match in YEAR_ANY.finditer(text or ""):
        if match.group(1):
            out.append(roc_to_ce(int(match.group(1))))
        else:
            out.append(int(match.group(0)))
    return out


def strip_years(text):
    """Remove every recognised year token, leaving the rest of the line for header checks."""
    return YEAR_ANY.sub("", text or "")


def scope_numbers(text):
    """Every scope number mentioned, in order of appearance, across the three scripts."""
    found = []
    for match in _SCOPE_EN.finditer(text or ""):
        found.append((match.start(), int(match.group(1))))
    for match in _SCOPE_ZH.finditer(text or ""):
        found.append((match.start(), _SCOPE_WORD[match.group(1)]))
    for match in _SCOPE_FLOW.finditer(text or ""):
        found.append((match.start(), _FLOW_SCOPE[match.group(1)]))
    return [scope for _, scope in sorted(found)]


def unit_to_tonnes(unit_text):
    """Canonicalise a disclosed unit to tonnes CO2e without guessing the magnitude."""
    compact = re.sub(r"[\s\u00a0]", "", (unit_text or "").lower())
    if compact.startswith("million") or compact.startswith("mt") or compact.startswith("百万") or compact.startswith("百萬"):
        return 1e6
    if compact.startswith("thousand") or compact.startswith("kt") or compact.startswith("千"):
        return 1e3
    if compact.startswith("亿") or compact.startswith("億"):
        return 1e8
    if compact.startswith("万") or compact.startswith("萬"):
        return 1e4
    return 1.0
