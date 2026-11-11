"""Evaluate numeric candidates ONLY on explicitly annotated pages and metrics."""
import argparse
from collections import Counter
import json
from pathlib import Path


def evaluate(bundle,gold):
    if bundle['document']['sha256'] != gold['document_sha256']:
        raise ValueError('Gold belongs to a different document')
    pages=set(gold['annotated_pages'])
    metrics=set(gold['annotated_metrics'])
    def key(r):
        return (r['page'],r['metric'],r['year'],r['unit'],r['value'])
    expected=Counter(key(r) for r in gold['observations'])
    predicted=Counter()
    for record in bundle['records']:
        if record['kind']!='observation':continue
        f=record['fields'];page=record['evidence']['page']
        if page in pages and f['metric'] in metrics:
            predicted[key(dict(f,page=page))]+=1
    correct=sum((expected & predicted).values())
    found=sum(predicted.values());total=sum(expected.values())
    return {'scope':'exact metric/year/unit/value on explicitly annotated pages only; not whole-report accuracy',
            'gold_cells':total,'predicted_cells':found,'correct_cells':correct,
            'precision':correct/found if found else None,'recall':correct/total if total else None,
            'missing':[list(k)+[v] for k,v in (expected-predicted).items()],
            'incorrect_or_duplicate':[list(k)+[v] for k,v in (predicted-expected).items()],
            'claims_evaluated':False, 'boundaries_evaluated':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('bundle',type=Path);p.add_argument('gold',type=Path)
    a=p.parse_args()
    print(json.dumps(evaluate(json.loads(a.bundle.read_text()),json.loads(a.gold.read_text())),indent=2))


if __name__=='__main__':main()
