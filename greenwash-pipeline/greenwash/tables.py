"""Conservative parser for one-series, explicitly headed year tables."""
import re
import unicodedata

from . import lang

# Units come from lang so English, Traditional Chinese and Simplified Chinese row labels share
# one definition; a Taiwan report states the same table as 範疇一 公噸CO2e.
UNIT = lang.UNIT
ROW = re.compile(r"^(?P<label>\S.*?)\s+(?P<unit>"+UNIT+r")\s+(?P<cells>.+)$", re.I)
# Some reports put the unit inside the row label, e.g.
# "Direct (Scope 1) GHG emissions (million T of CO2e) [4]    6.05   6.64", or the Chinese
# "範疇一（公噸－二氧化碳當量） 註1   2,004,841   2,151,937". Full-width brackets and the
# 註 footnote marker are Taiwan/mainland conventions, not typos.
ROW_LABELLED_UNIT = re.compile(r"^(?P<label>\S.*?)\s*[（(](?P<unit>"+UNIT+r")[）)]"
                               r"\s*(?:\[\d+\]|註\s*\d+)?\s+(?P<cells>.+)$", re.I)
CELL = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\[\d+\])?|n/a|[-–]", re.I)


def unit_multiplier(unit_text):
    """Canonicalise a disclosed unit to tonnes of CO2e without guessing."""
    return lang.unit_to_tonnes(unit_text)


def parse_tables(text):
    lines = text.splitlines()
    header = None
    group = None
    rows, warnings = [], []
    for number, line in enumerate(lines, 1):
        normalized = unicodedata.normalize('NFKC',line)
        years = lang.years_in(normalized)
        # Explicit column header, not an arbitrary sentence mentioning years.
        header_residue = lang.strip_years(normalized)
        residue = re.sub(r'\b(?:KPI|Unit|Indicator|Metric|Year|FY|Fiscal|Reporting|Period)s?\b','',header_residue,flags=re.I)
        # Chinese headers label the columns with words, not just years: 項目/單位/年度. \b does
        # not apply between Chinese characters, so these are stripped without word boundaries.
        residue = re.sub(r'(?:項目|项目|單位|单位|年度|年份|指標|指标|數據|数据|類別|类别)','',residue)
        residue_words = re.findall(r"[A-Za-z\u4e00-\u9fff]+", residue)
        ordered = years == sorted(years) or years == sorted(years, reverse=True)
        # A short leading caption ("Environmental 2024 2023 2022") is still a column header;
        # a sentence that merely mentions years is not.
        is_header = len(years)>=2 and (not residue_words or (len(years)>=3 and len(residue_words)<=2 and ordered))
        if is_header:
            header = (number, line, years)
            group = None
            continue
        # A row is a candidate when it carries a scope label in any script (Scope 2, 範疇二,
        # 范围二, 間接排放); the unit requirement is inside ROW itself.
        match = None
        scope_number = None
        if lang.scope_numbers(normalized):
            match = ROW.match(normalized.strip()) or ROW_LABELLED_UNIT.match(normalized.strip())
        if match:
            label_scopes = lang.scope_numbers(match.group('label'))
            # "Scope 1 and 2" and "範疇一及範疇二" name two scopes and must abstain.
            combined_en = re.search(r'scope\s*[123]\s*(?:and|&|\+|,|、|及|與|与)\s*[123]',
                                    match.group('label'), re.I)
            if combined_en or len(label_scopes) != 1:
                match = None
            else:
                scope_number = label_scopes[0]
        if not match:
            stripped = re.sub(r"\[\d+\]", '', line).strip()
            if header and stripped and not re.search(r"\d", stripped) and not re.search(r"\s{3,}", stripped):
                group = stripped.lstrip('# ').strip()
            continue
        if not header:
            warnings.append({"line": number, "code": "TABLE_MISSING_YEAR_HEADER"})
            continue
        hline, htext, years = header
        if len(years) < 2 or len(years) != len(set(years)) or (years != sorted(years) and years != sorted(years,reverse=True)):
            warnings.append({"line": number, "code": "AMBIGUOUS_MULTI_ENTITY_YEAR_HEADER"})
            continue
        tail = match.group('cells').strip()
        cells = re.split(r'\s+',tail)
        if len(cells) != len(years) or not all(CELL.fullmatch(c) for c in cells):
            warnings.append({"line": number, "code": "TABLE_COLUMN_MISMATCH"})
            continue
        for year, cell in zip(years, cells):
            missing = cell.lower() in {'n/a', '-', '–'}
            value = None if missing else float(re.sub(r"\[\d+\]", '', cell).replace(',', ''))
            if value is not None:
                value *= unit_multiplier(match.group('unit'))
            rows.append({"line": number, "header_line": hline, "header_quote": htext.strip(),
                         "quote": line.strip(), "section_hint": group,
                         "metric": 'scope' + str(scope_number), "year": year,
                         "value": value, "unit": 'tCO2e', "raw_cell": cell})
    return rows, warnings


def claim_segments(text):
    """Split large horizontal gaps; never join neighbouring columns as one claim."""
    if re.search(r"Content Index for Sustainability Reporting|^\s*CONTENTS\s*$", text, re.I | re.M):
        return
    for number, line in enumerate(text.splitlines(), 1):
        if re.search(r"Sustainability Report\s+20\d{2}", line, re.I):
            continue
        for segment in re.split(r"\s{5,}", line.strip()):
            # Drop page references, short titles and numeric table rows.
            if re.search(r"\s\d{1,3}\s*$", segment):
                continue
            # English needs eight words; Chinese says the same in twelve characters, and a
            # whitespace token count would drop every Chinese segment.
            if len(segment.split()) < 8 and len(lang.CJK_RE.findall(segment)) < 12:
                continue
            yield number, segment
