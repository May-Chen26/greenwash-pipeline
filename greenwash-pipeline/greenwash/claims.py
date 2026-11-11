"""Claim candidates with linguistic cues, explicit abstention and source spans."""
import re

from . import lang

# Chinese entries carry both scripts in one alternative (減|减) because Taiwan files in
# Traditional and the mainland files in Simplified. Splitting them into two lists would mean
# two definitions of the same concept that can drift apart.
ENV = re.compile(r'\bemissions?\b|\bcarbon\b|\bclimate\b|\brenewable\b|\benergy\b|\bnet.zero\b'
                 r'|排放|減排|减排|碳|溫室氣體|温室气体|氣候|气候|可再生|能源|綠電|绿电'
                 r'|淨零|净零|碳中和|減碳|减碳',re.I)
# Movement verbs, not only "good news" verbs: an adverse movement must also become a
# candidate, otherwise deterioration is systematically under-captured.
ACTION = re.compile(r'\breduc\w*|\bdecreas\w*|\bdeclin\w*|\bfall\w*|\bfell\b|\bdrop\w*|\bcut\b'
                     r'|\brise\w*|\brose\b|\bincreas\w*|\bgrow\w*|\bgrew\b|\bsurg\w*|\bimprov\w*|\bmet\b'
                     r'|\btarget\w*|\baim\w*|\bpledge\w*|\bcommit\w*|\bachiev\w*|\bnet.zero\b'
                     r'|\bcertif\w*|\bvalidat\w*|\binvest(?:ed|ing|s)?\b|\bsav\w*'
                     r'|減|减|減少|减少|下降|下跌|上升|增加|增長|增长|降低|提升'
                     r'|目標|目标|承諾|承诺|實現|实现|達成|达成|完成|投入|認證|认证|設定|设定',re.I)
# Explicit forward-looking markers. A bare "target" noun alone is NOT enough; see TARGET_NOUN.
FUTURE_CUE = re.compile(r'\b(?:will|shall|aim|aims|plan|plans|intend|intends|pledge|pledges'
                        r'|commit|commits|committed|expect|expects|targeting)\b'
                        r'|\bon\s+(?:track|course)\b'
                        r'|承諾|承诺|計劃|计划|規劃|规划|將|将|預計|预计|擬|拟|期許|期许',re.I)
TARGET_NOUN = re.compile(r'\btargets?\b|\bgoal\w*\b|\bcommitments?\b|目標|目标|承諾|承诺',re.I)
# Realized outcomes, including adverse movements; a realized verb outranks a bare target noun.
REALIZED = re.compile(r'\b(?:reduced|reduces|decreased|decreases|declined|declines|fell|falls|dropped|drops|cut|cuts'
                        r'|achieved|achieves|attained|met|meets|saved|saves|delivered|recorded|completed'
                        r'|increased|increases|rose|rises|grew|grows|improved|improves)\b'
                        r'|已實現|已实现|已減少|已减少|已達成|已达成|已降低|已完成'
                        r'|下降了|下跌了|上升了|增加了',re.I)
# Only a hard quantitative marker is worth surfacing when no movement/target verb was found;
# an unrelated digit (a year, a currency amount) is not evidence that a claim was missed.
QUANTIFIED = re.compile(r'\d\s*(?:%|percent)|\b(?:tCO2-?e|CO2-?e|CO₂e|MWh|kWh|GWh|tonnes?)\b'
                        r'|公噸|公吨|萬噸|万吨|千噸|千吨|百萬噸|百万吨|億噸|亿吨|噸|吨'
                        r'|二氧化碳當量|二氧化碳当量',re.I)


def sentences(text):
    # Decimal numbers and abbreviations without whitespace remain intact.
    start=0
    for match in re.finditer(r'[.!?。！？](?:[”"’])?(?=\s+|$)',text):
        end=match.end()
        if end>start:
            value=text[start:end].strip()
            begin=text.find(value,start,end)
            if value: yield begin,end,value
        start=end
    if text[start:].strip():
        value=text[start:].strip()
        yield text.find(value,start),len(text),value


def fields_for(text):
    future=bool(FUTURE_CUE.search(text))
    target_noun=bool(TARGET_NOUN.search(text))
    realized=bool(REALIZED.search(text))
    negated=bool(re.search(r'\b(?:no|not(?! only)|never|without)\b|尚未|沒有|没有|未能|未達|未达',text,re.I))
    if negated:
        realized=False
    # A realized verb outranks a bare "target" noun, so "we achieved our target" is a result.
    # Only an explicit forward-looking marker makes a sentence a future target.
    if realized and not future:
        ctype='realized_result'
    elif future or target_noun:
        ctype='future_target'
    else:
        ctype='unclassified'
    if not future and re.search(r'\b(?:certified|validated|assured)\b|核證|核证|認證|认证|驗證|验证|查證|查证|確信|确信',text,re.I): ctype='assurance'
    intensity=bool(re.search(r'\bintensity\b|\bper\s+(?:passenger|pkm|square|sqm|unit|revenue)|強度|强度|每單位|每单位|單位產品|单位产品',text,re.I))
    absolute=bool(re.search(r'\babsolute\b|絕對|绝对|總量|总量',text,re.I))
    metric='intensity' if intensity and not absolute else 'absolute_emissions' if absolute and not intensity else None
    base=re.findall(r'(?:against|compared (?:with|to)|relative to)\s+(?:the\s+)?((?:19|20)\d{2})'
                    r'|((?:19|20)\d{2})\s+(?:base\s*year|baseline)'
                    r'|(?:相較|相较|較|较|比)\s*(?:於|于)?\s*((?:19|20)\d{2})'
                    r'|((?:19|20)\d{2})\s*(?:年)?\s*(?:基準年|基准年|為基準|为基准)',text,re.I)
    base_years={int(y) for group in base for y in group if y}
    # A sentence that carries a target noun is still a target statement even without a modal verb.
    target_like=future or target_noun
    if target_like:
        targets={int(v) for v in re.findall(r'\bby\s+((?:19|20)\d{2})\b',text,re.I)}
        # Chinese target years are written "2030 年" or "於 2030 年前", with or without a space.
        targets|={int(v) for v in re.findall(r'((?:19|20)\d{2})\s*年(?:前|以前|之前)?',text)}
        # A baseline year is not a target year: "以 2019 年為基準，2030 年減碳 40%" has one target.
        targets-=base_years
    else:
        targets=set()
    result={'claim_type':ctype,'metric':metric,
            'baseline_year':next(iter(base_years)) if len(base_years)==1 else None,
            'target_year':next(iter(targets)) if len(targets)==1 else None,
            'geography':None,'organizational_boundary':None,'assessment_status':'not_assessed'}
    flags=[]
    if re.search(r'\b(?:support|supports|supporting)\b.*\b(?:journey|ambition|goal|target)',text,re.I):
        result['target_year']=None
        flags.append('TARGET_ACTOR_UNRESOLVED')
    if intensity and absolute: flags.append('MIXED_METRIC_NEEDS_SPLIT')
    if future and realized: flags.append('MIXED_TIME_OR_TARGET_STATUS')
    if not re.search(r'[.!?。！？][”"’]?$',text): flags.append('INCOMPLETE_SENTENCE')
    if negated:flags.append('NEGATION_REVIEW')
    if re.search(r'\b(?:could|may|expected|estimated|approximately|about)\b|預計|预计|估計|估计|預估|预估|可能|約|约',text,re.I):flags.append('QUALIFIED_OR_ESTIMATED')
    return result,flags


def target_context(block, blocks):
    """A nearby explicit target heading in the same column; never guess from report year."""
    box=block.get('bbox')
    if not box:return None
    eligible=[]
    for prior in blocks:
        pb=prior.get('bbox')
        if not pb or pb[3]>box[1]+1 or box[1]-pb[3]>150:continue
        if abs(pb[0]-box[0])>20:continue
        text=prior['text']
        if text.endswith(':') and re.search(r'\b(?:targets|SBTs)\b|目標|目标',text,re.I) and lang.years_in(text):
            eligible.append(prior)
    return max(eligible,key=lambda p:p['bbox'][3]) if eligible else None


def extract_claims(blocks, page_text, skipped=None):
    if re.search(r'Content Index for Sustainability Reporting|^\s*CONTENTS\s*$',page_text,re.I|re.M):
        return []
    output=[]

    def omit(block,sentence,reason):
        # Sentences that never reach the review queue are still reported, so a reviewer can
        # see the omission instead of trusting an incomplete queue.
        if skipped is None:
            return
        # A block with no sentence punctuation is yielded whole by sentences(); such a dump
        # is page text, not a claim sentence, and would only add noise to the review aid.
        if len(sentence) > 600:
            return
        skipped.append({'block_id':block['block_id'],'quote':sentence,'reason':reason})

    for block in blocks:
        text=block['text']
        if block.get('is_boilerplate') or not ENV.search(text): continue
        # Avoid reporting requirements and navigation labels, not issuer assertions.
        if re.search(r'\b(?:an issuer|the entity) shall\b',text,re.I):continue
        context=target_context(block,blocks)
        for start,end,sentence in sentences(text):
            if not ENV.search(sentence):continue
            if not ACTION.search(sentence):
                if QUANTIFIED.search(sentence):
                    omit(block,sentence,'QUANTIFIED_ENV_SENTENCE_WITHOUT_ACTION_VERB')
                continue
            if len(sentence.split())<8 and len(re.findall(r'[\u4e00-\u9fff]',sentence))<12:
                omit(block,sentence,'SHORT_SENTENCE_BELOW_REVIEW_THRESHOLD')
                continue
            if re.search(r'\.{3,}\s*\d+\s*$',sentence):continue
            fields,flags=fields_for(sentence)
            if context and re.search(r'\bReduce\b|減|减',sentence) and fields['claim_type']=='unclassified':
                cf,_=fields_for(context['text'])
                # Only the years that sit next to a target marker count: a heading such as
                # "Our 2030 SBTs, based on 2019 base year levels" names one target year.
                years={int(v) for v in re.findall(r'\b(20\d{2})\s+(?:SBTs|targets)\b',context['text'],re.I)}
                years|={int(v) for v in re.findall(r'((?:19|20)\d{2})\s*(?:年)?\s*(?:SBTs|目標|目标)',context['text'])}
                fields['claim_type']='future_target'
                fields['baseline_year']=cf['baseline_year']
                fields['target_year']=int(next(iter(years))) if len(years)==1 else None
                flags.append('TARGET_FIELDS_FROM_NEARBY_HEADING_REVIEW')
            if re.search(r'\d\s*%',sentence) and not fields['metric']:flags.append('METRIC_BASIS_UNRESOLVED')
            output.append({'block':block, 'quote':sentence, 'char_start':start,'char_end':end,
                           'fields':fields,'flags':flags,'context_evidence':context,
                           'percentages':re.findall(r'\d+(?:\.\d+)?\s*%',sentence)})
    return output
