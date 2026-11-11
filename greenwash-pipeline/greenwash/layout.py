"""Position-aware evidence blocks. Does not infer missing text or read images."""
from collections import Counter
import re


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def pdf_blocks(path):
    try:
        import fitz
    except ImportError as exc:
        raise ValueError("PDF paragraph mode requires PyMuPDF; install requirements-pdf.txt") from exc
    pages = []
    margin_text = Counter()
    with fitz.open(path) as doc:
        for page in doc:
            blocks = []
            for bi, block in enumerate(page.get_text('dict', flags=fitz.TEXTFLAGS_TEXT)['blocks']):
                if block['type'] != 0:
                    continue
                # Native blocks can contain more than one column. Split discontinuous lines.
                groups, group = [], []
                for line in block['lines']:
                    if not line.get('spans'):
                        continue
                    if group:
                        prev = group[-1]
                        x0,y0,x1,y1 = line['bbox']
                        px0,py0,px1,py1 = prev['bbox']
                        overlap = min(x1,px1)-max(x0,px0)
                        height = max(py1-py0, y1-y0, 1)
                        if overlap <= 0 or y0 < py0-2 or y0-py1 > 1.6*height:
                            groups.append(group)
                            group=[]
                    group.append(line)
                if group:
                    groups.append(group)
                for gi, lines in enumerate(groups):
                    raw = '\n'.join(''.join(s['text'] for s in line['spans']) for line in lines)
                    bbox = [min(l['bbox'][0] for l in lines), min(l['bbox'][1] for l in lines),
                            max(l['bbox'][2] for l in lines), max(l['bbox'][3] for l in lines)]
                    margin = bbox[1] < 0.05*page.rect.height or bbox[3] > 0.95*page.rect.height
                    item = {'block_id': f'p{page.number+1}-b{bi}-g{gi}', 'page': page.number+1,
                            'bbox': [round(x,2) for x in bbox], 'raw_text': raw,
                            'text': normalize(raw), 'in_margin': margin}
                    blocks.append(item)
                    if margin:
                        margin_text[item['text']] += 1
            pages.append(blocks)
    for blocks in pages:
        for block in blocks:
            block['is_boilerplate'] = block['in_margin'] and (
                margin_text[block['text']] >= 3 or bool(re.fullmatch(r'\d+', block['text'])))
        blocks.sort(key=lambda b: (b['bbox'][1], b['bbox'][0]))
    return pages


def text_blocks(pages):
    result=[]
    for pn,page in enumerate(pages,1):
        blocks=[]
        # TXT fallback: separated paragraphs only; no pretend spatial coordinates.
        for bi, raw in enumerate(re.split(r'\n\s*\n',page)):
            if raw.strip():
                blocks.append({'block_id':f'p{pn}-b{bi}', 'page':pn, 'bbox':None,
                               'raw_text':raw, 'text':normalize(raw), 'is_boilerplate':False})
        result.append(blocks)
    return result
