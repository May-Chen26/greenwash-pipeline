"""Offline, conservative candidate extraction and explicit human review."""
import argparse
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from . import lang
from .tables import parse_tables
from .layout import pdf_blocks, text_blocks
from .claims import extract_claims

VERSION = "rules-0.5.0"
KEYWORDS = re.compile(r"emission|scope\s*[123]|carbon|climate|renewable|net.zero|sbti|re100"
                      r"|能源|排放|碳|減排|减排|淨零|净零|碳中和|溫室氣體|温室气体|再生能源|綠電|绿电"
                      r"|氣候|气候|營收|营收|revenue", re.I)
CLAIM = re.compile(r"reduc|decreas|target|aim|pledge|commit|net.zero|renewable|certif|assur|减|目标|承诺|认证|净零|下降", re.I)
NUMBER = r"(?P<value>\d[\d,]*(?:\.\d+)?)"

# Observation rows written as prose rather than as a table. The Chinese forms follow the same
# discipline as the English ones: an explicit scope label, a separator, a number and a unit.
_ZH_UNIT = (r"(?P<unit>百萬公噸|百万公吨|億公噸|亿公吨|萬公噸|万公吨|千公噸|千公吨|公噸|公吨|" 
            r"百萬噸|百万吨|億噸|亿吨|萬噸|万吨|千噸|千吨|噸|吨)"
            r"\s*(?:CO2e|CO₂e|二氧化碳當量|二氧化碳当量)?")
PATTERNS = [
    ("scope1", re.compile(r"scope\s*1(?:\s+(?:GHG|emissions?))*\s*[:=]\s*" + NUMBER + r"\s*(?P<unit>ktCO2e|tCO2e|tonnes?\s+CO2e)\b", re.I)),
    ("scope2", re.compile(r"scope\s*2\s*\((?P<method>location-based|market-based)\)(?:\s+emissions?)?\s*[:=]\s*" + NUMBER + r"\s*(?P<unit>ktCO2e|tCO2e|tonnes?\s+CO2e)\b", re.I)),
    ("revenue", re.compile(r"revenue\s*[:=]\s*(?P<currency>USD)\s*" + NUMBER + r"\s*(?P<unit>million|billion)\b", re.I)),
    ("scope1", re.compile(r"(?:範疇\s*一|范畴\s*一|范围\s*一|直接排放(?:量)?)\s*(?:排放量)?\s*[:：]?\s*" + NUMBER + r"\s*" + _ZH_UNIT, re.I)),
    ("scope2", re.compile(r"(?:範疇\s*二|范畴\s*二|范围\s*二|間接排放(?:量)?|间接排放(?:量)?)\s*(?:排放量)?\s*[:：]?\s*" + NUMBER + r"\s*" + _ZH_UNIT, re.I)),
]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def read_pages(path):
    path = Path(path).resolve()
    if path.suffix.lower() == ".pdf":
        if not shutil.which("pdftotext"):
            raise ValueError("PDF input requires Poppler pdftotext. TXT input needs only Python.")
        proc = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=120)
        if proc.returncode:
            raise ValueError("PDF conversion failed: " + proc.stderr.decode(errors="replace")[:500])
        text = proc.stdout.decode("utf-8")
    elif path.suffix.lower() in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
    else:
        raise ValueError("Supported inputs: text-based PDF, UTF-8 TXT/MD. OCR is not implemented.")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def check_page_alignment(pages, blocks):
    # pdftotext supplies the page text, PyMuPDF supplies the positioned blocks. If the two
    # disagree, indexing blocks[page_no-1] would silently attach claims to the wrong page.
    if len(blocks) != len(pages):
        raise ValueError(
            "Page count mismatch between text and layout extraction "
            f"({len(pages)} text pages vs {len(blocks)} layout pages); refusing to align records by index"
        )


def extract(path, company, published_at, as_of, synthetic=False):
    if published_at is not None:
        published_at = date.fromisoformat(published_at).isoformat()
    as_of = date.fromisoformat(as_of).isoformat()
    if published_at is not None and published_at > as_of:
        raise ValueError("Document publication is later than as_of.")
    content_hash = digest(Path(path).read_bytes())
    document_id = digest((company + content_hash + (published_at or "unknown")).encode())[:24]
    pages = read_pages(path)
    blocks = pdf_blocks(path) if Path(path).suffix.lower() == ".pdf" else text_blocks(pages)
    check_page_alignment(pages, blocks)
    records, passages, warnings, skipped = [], [], [], []
    if published_at is None:
        warnings.append({"code": "PUBLICATION_DATE_UNKNOWN_NO_POINT_IN_TIME_ELIGIBILITY"})
    for page_no, text in enumerate(pages, 1):
        if len(text.strip()) < 30:
            warnings.append({"page": page_no, "code": "LOW_TEXT_REQUIRES_INSPECTION_OR_OCR"})
        lines = text.splitlines()
        for line_no, line in enumerate(lines, 1):
            if not KEYWORDS.search(line):
                continue
            quote = line.strip()
            evidence = {"document_id": document_id, "page": page_no, "line": line_no, "quote": quote}
            context = "\n".join(lines[max(0, line_no-3):min(len(lines), line_no+2)])
            passages.append({"evidence": evidence, "context": context})
            years = sorted(set(lang.years_in(quote)))
            # Never propagate a report year or nearby header as the metric year.
            year = int(years[0]) if len(years) == 1 else None
            base = {"company_id": company, "evidence": evidence, "context": context,
                    "review_status": "pending", "available_at": published_at}
            for metric, pattern in PATTERNS:
                for match in pattern.finditer(quote):
                    unit = match.group("unit").lower()
                    value = float(match.group("value").replace(",", ""))
                    if metric == "revenue":
                        value *= 1e6 if unit == "million" else 1e9
                        canonical_unit = "USD"
                    else:
                        value *= lang.unit_to_tonnes(unit)
                        canonical_unit = "tCO2e"
                    fields = {"metric": metric, "value": value, "unit": canonical_unit,
                              "year": year, "geography": None, "organizational_boundary": None,
                              "scope2_method": match.groupdict().get("method", None),
                              "period_basis": None}
                    rid = digest(f"{document_id}:{page_no}:{line_no}:{metric}:{match.start()}".encode())[:24]
                    records.append(dict(base, id=rid, kind="observation", fields=fields))
        table_rows, table_warnings = parse_tables(text)
        warnings.extend(dict(w, page=page_no) for w in table_warnings)
        for row in table_rows:
            evidence = {"document_id": document_id, "page": page_no, "line": row['line'],
                        "quote": row['quote'], "header_line": row['header_line'],
                        "header_quote": row['header_quote'], "raw_cell": row['raw_cell']}
            # Adjacent-page notes are candidates only, never propagated as facts.
            related_notes = []
            for offset in (0, 1):
                if page_no - 1 + offset < len(pages):
                    nt = pages[page_no - 1 + offset]
                    if '\nNotes\n' in nt or '\n Notes\n' in nt:
                        part = re.split(r'\n\s*Notes\s*\n', nt, maxsplit=1)[-1]
                        related_notes.append({"page": page_no + offset, "text": part})
            rid = digest(f"{document_id}:{page_no}:{row['line']}:{row['year']}:table".encode())[:24]
            fields = {"metric": row['metric'], "value": row['value'], "unit": row['unit'],
                      "year": row['year'], "geography": None, "organizational_boundary": None,
                      "scope2_method": None, "period_basis": None}
            records.append({"id": rid, "kind": "observation", "company_id": company,
                            "evidence": evidence, "context": text,
                            "section_hint": row['section_hint'], "related_notes": related_notes,
                            "review_status": "pending", "available_at": published_at,
                            "extraction_method": "explicit_year_table", "fields": fields})
        page_skipped = []
        for item in extract_claims(blocks[page_no-1], text, page_skipped):
            block, quote = item['block'], item['quote']
            evidence = {"document_id": document_id, "page": page_no, "line": None,
                        "quote": quote, "block_id": block['block_id'], "bbox": block['bbox'],
                        "normalized_source_text": block['text'], "raw_source_text": block['raw_text'],
                        "char_start": item['char_start'], "char_end": item['char_end']}
            if item.get('context_evidence'):
                evidence['context_evidence'] = item['context_evidence']
            if block['text'][item['char_start']:item['char_end']] != quote:
                raise ValueError("Claim source span failed validation")
            rid = digest(f"{document_id}:{block['block_id']}:{item['char_start']}:claim".encode())[:24]
            records.append({"id": rid, "kind": "claim", "company_id": company,
                            "evidence": evidence, "context": block['text'],
                            "review_status": "pending", "available_at": published_at,
                            "extraction_method": "positioned_block_sentence" if block['bbox'] else "text_paragraph_sentence",
                            "needs_context_review": True, "quality_flags": item['flags'],
                            "percentages_mentioned": item['percentages'], "fields": item['fields'],
                            "duplicate_group": digest(quote.casefold().encode())[:16]})
        skipped.extend(dict(entry, page=page_no) for entry in page_skipped)
    # A sentence that was already captured as a numeric observation is not an omission.
    observed_quotes = {}
    for record in records:
        if record['kind'] == 'observation':
            observed_quotes.setdefault(record['evidence']['page'], []).append(record['evidence']['quote'] or '')
    skipped = [entry for entry in skipped
               if not any(entry['quote'] and entry['quote'] in quote
                          for quote in observed_quotes.get(entry['page'], []))]
    observations = [r for r in records if r['kind']=='observation']
    claims = [r for r in records if r['kind']=='claim']
    if not observations:
        warnings.append({"code": "NO_NUMERIC_OBSERVATIONS_NOT_ZERO_EMISSIONS"})
    if not claims:
        warnings.append({"code": "NO_CLAIM_CANDIDATES_NOT_NO_GREENWASHING"})
    if skipped:
        # Never let an omission look like an absence of evidence.
        warnings.append({"code": "CLAIM_SENTENCES_OMITTED_FROM_REVIEW_QUEUE", "count": len(skipped)})
    return {"schema_version": "1.2", "extractor_version": VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(), "as_of": as_of,
            "document": {"id": document_id, "company_id": company, "filename": Path(path).name,
                         "sha256": content_hash, "published_at": published_at,
                         "publication_date_source": "user_supplied_not_independently_verified" if published_at else "unknown",
                         "synthetic": synthetic},
            "pages": [{"page": i, "text": p} for i, p in enumerate(pages, 1)],
            "passages": passages, "records": records, "warnings": warnings,
            "skipped_candidates": skipped,
            "quality_summary": {"pages": len(pages), "observation_candidates": len(observations),
                                "claim_candidates": len(claims),
                                "claims_needing_context_review": len(claims),
                                "incomplete_claim_candidates": sum('INCOMPLETE_SENTENCE' in r['quality_flags'] for r in claims),
                                "skipped_claim_candidates": len(skipped),
                                "missing_numeric_values": sum(r['fields']['value'] is None for r in observations),
                                "accuracy_measured": False, "scoring_ready": False,
                                "publication_date_supplied_not_verified": published_at is not None},
            "limitations": ["Heuristic candidates, not exhaustive extraction or verified facts.",
                            "No OCR, multi-entity table inference, network fetch, or LLM calls.",
                            "Claim segments may be incomplete; context and boundary need review.",
                            "No B/G scores produced; claims still need independent evidence assessment."]}


def review_html(bundle):
    # Escaping prevents document text from becoming executable HTML/script.
    rows = []
    for r in bundle["records"]:
        ev = r["evidence"]
        # Claims carry no line number (they are located by block_id), so never render "None".
        location = (f"p{ev['page']}:{ev['line']}" if ev.get('line') is not None
                    else f"p{ev['page']} · {ev.get('block_id', 'block')}")
        details = html.escape(json.dumps({"header": ev.get('header_quote'),
                                         "section_hint": r.get('section_hint'),
                                         "related_notes": r.get('related_notes', []),
                                         "quality_flags": r.get('quality_flags', []),
                                         "bbox": ev.get('bbox')}, ensure_ascii=False, indent=2))
        rows.append(f'''<article data-id="{r['id']}"><h3>{r['kind']} · {location}</h3>
<blockquote>{html.escape(ev['quote'])}</blockquote><details><summary>上下文</summary><pre>{html.escape(r['context'])}</pre></details>
<details><summary>表头、分组与待复核脚注</summary><pre>{details}</pre></details>
<label>提取复核 <select><option value="pending">待复核</option><option value="accepted">确认提取</option><option value="rejected">拒绝候选</option></select></label>
<p>修改下方 JSON；未知字段保留 null。确认提取不代表声明真实。</p>
<textarea rows="13">{html.escape(json.dumps(r['fields'], ensure_ascii=False, indent=2))}</textarea>
<input class="note" placeholder="修改原因／复核说明"></article>''')
    omitted = bundle.get("skipped_candidates") or []
    shown = omitted[:200]
    omitted_html = ""
    if omitted:
        items = "\n".join(f'<li><code>p{o["page"]}</code> {html.escape(o["reason"])}<br>{html.escape(o["quote"])}</li>'
                          for o in shown)
        tail = (f'<p>另有 {len(omitted) - len(shown)} 条未在此列出，完整清单见 candidates.json 的 skipped_candidates。</p>'
                if len(omitted) > len(shown) else "")
        omitted_html = (f'<section><h2>未进入复核队列（{len(omitted)} 条）</h2>'
                        '<p>这些句子含环境词与数字或未达候选门槛，因此不能接受或拒绝。列出以便复核者知晓漏提范围。</p>'
                        f'<ul>{items}</ul>{tail}</section>')
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>报告候选复核</title>
<style>body{max-width:960px;margin:40px auto;padding:0 20px;font:16px system-ui;color:#173042;background:#f4f7fa}article{background:white;padding:24px;margin:20px 0;border:1px solid #ccd7e0;border-radius:10px}textarea{width:100%;font:14px monospace;box-sizing:border-box}input{padding:10px;margin:10px 0;width:90%}button,select{padding:10px}pre{white-space:pre-wrap}blockquote{border-left:4px solid #187a7a;padding-left:14px}header{background:#e0f0ec;padding:20px}</style>
<header><h1>报告候选复核</h1><p>离线规则基线 · 所有候选均需复核 · 无真实公司评分</p><p>下载修改结果后运行 apply-review。页面刷新不会自动保存。</p>
<input id="reviewer" placeholder="复核人（必填）"><button id="download">下载 decisions.json</button><p id="message"></p></header>
''' + "\n".join(rows) + omitted_html + '''<script>
const documentId = "''' + bundle["document"]["id"] + '''";
document.getElementById('download').onclick=()=>{try{
const reviewer=document.getElementById('reviewer').value.trim();if(!reviewer)throw Error('请输入复核人');
const decisions=[...document.querySelectorAll('article')].map(a=>({id:a.dataset.id,status:a.querySelector('select').value,fields:JSON.parse(a.querySelector('textarea').value),note:a.querySelector('.note').value}));
const data={document_id:documentId,reviewer,decisions};
const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
const link=document.createElement('a');link.href=url;link.download='decisions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
document.getElementById('message').textContent='已导出；运行 apply-review 校验并生成正式数据。';
}catch(e){document.getElementById('message').textContent=e.message;}};
</script></html>'''


def validate_fields(kind, f):
    if kind == "observation":
        if f.get("metric") not in {"scope1", "scope2", "scope3", "revenue"}:
            raise ValueError("Unsupported observation metric")
        expected = "USD" if f["metric"] == "revenue" else "tCO2e"
        if f.get("unit") != expected:
            raise ValueError("Metric/unit mismatch")
        value = f.get("value")
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError("Value must be a finite nonnegative number")
        if f["metric"] == "revenue" and value == 0:
            raise ValueError("Revenue must be positive")
        if type(f.get("year")) is not int or not 1900 <= f["year"] <= 2100:
            raise ValueError("A verified metric year is required")
        for key in ("geography", "organizational_boundary", "period_basis"):
            if not isinstance(f.get(key), str) or not f[key].strip():
                raise ValueError(f"Verified {key} is required")
        if f["metric"] == "scope2" and f.get("scope2_method") not in {"location-based", "market-based"}:
            raise ValueError("Scope 2 method is required")
    else:
        if f.get("claim_type") not in {"future_target", "realized_result", "investment", "assurance", "promotional", "unclassified"}:
            raise ValueError("Unknown claim type")
        if f.get("assessment_status") != "not_assessed":
            raise ValueError("Extraction review cannot adjudicate a claim's truth")
        for key in ("baseline_year", "target_year"):
            if f.get(key) is not None and (type(f[key]) is not int or not 1900 <= f[key] <= 2100):
                raise ValueError("Invalid claim year")


def apply_review(bundle, review):
    if review.get("document_id") != bundle["document"]["id"]:
        raise ValueError("Review belongs to another document")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Reviewer required")
    lookup = {r["id"]: r for r in bundle["records"]}
    decisions, seen = [], set()
    for d in review.get("decisions", []):
        rid = d.get("id")
        if rid not in lookup or rid in seen:
            raise ValueError("Unknown or duplicate record ID")
        seen.add(rid)
        original = lookup[rid]
        if d.get("status") not in {"pending", "accepted", "rejected"}:
            raise ValueError("Invalid review status")
        fields = d.get("fields", original["fields"])
        if not isinstance(fields, dict) or set(fields) != set(original["fields"]):
            raise ValueError("Review must preserve field schema")
        if d["status"] == "accepted":
            validate_fields(original["kind"], fields)
        decisions.append(dict(original, fields=fields, review_status=d["status"],
                              review={"reviewer": reviewer, "note": d.get("note", ""),
                                      "original_fields": original["fields"]}))
    decisions.extend(r for r in bundle["records"] if r["id"] not in seen)
    result = dict(bundle, records=decisions, reviewed_at=datetime.now(timezone.utc).isoformat())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    ext = subs.add_parser("extract")
    ext.add_argument("file", type=Path)
    ext.add_argument("--company", required=True)
    ext.add_argument("--published-at", help="Verified publication date if known; omit rather than invent a date")
    ext.add_argument("--as-of", required=True)
    ext.add_argument("--out", type=Path, required=True)
    ext.add_argument("--synthetic", action="store_true")
    rev = subs.add_parser("apply-review")
    rev.add_argument("bundle", type=Path)
    rev.add_argument("decisions", type=Path)
    rev.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        # New directories prevent accidental replacement of an earlier human review.
        if args.out.exists():
            raise ValueError("Output directory already exists; choose a new run directory")
        if args.command == "extract":
            bundle = extract(args.file, args.company, args.published_at, args.as_of, args.synthetic)
            args.out.mkdir(parents=True)
            save(args.out / "candidates.json", bundle)
            (args.out / "review.html").write_text(review_html(bundle), encoding="utf-8")
        else:
            original = json.loads(args.bundle.read_text(encoding="utf-8"))
            review = json.loads(args.decisions.read_text(encoding="utf-8"))
            bundle = apply_review(original, review)
            args.out.mkdir(parents=True)
            save(args.out / "reviewed.json", bundle)
            for kind, name in (("observation", "observations.json"), ("claim", "claims.json")):
                save(args.out / name, {"schema_version": bundle["schema_version"], "document": bundle["document"],
                     "as_of": bundle["as_of"], "scoring_ready": False,
                     "records": [r for r in bundle["records"] if r["kind"] == kind and r["review_status"] == "accepted"]})
        print(json.dumps({"output": str(args.out), "records": len(bundle["records"]),
                          "warnings": bundle["warnings"]}, ensure_ascii=False))
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
