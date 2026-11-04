"""Small polarity-preserving equivalences; no general entailment claim."""
import re

def canonical(text):
    # Normalize the attested output/result constructions in both word orders.
    text=re.sub(r'([^，,；;。:：]{1,30}?)(?:没有|尚未|未|没)(?:生成|产生|产出)(?=$|[，,；;。])',r'未产出\1',text)
    text=re.sub(r'(?:没有|尚未|未|没)(?:生成|产生|产出)', '未产出',text)
    text=re.sub(r'^(?:此前|之前)','',text)
    text=text.replace('已经','已').replace('已不再','不再').replace('尚未部署','未部署').replace('还没部署','未部署')
    return re.sub(r'[\W_]+','',text.lower())

def strip_presentation(text,citations=()):
    ids='|'.join(re.escape(s) for s in citations if isinstance(s,str))
    if ids:text=re.sub(r'[（(]来源\s*(?:'+ids+r')(?:[，,]\s*(?:明确记录为当前实际值|当前实际记录|当前实际值))?[）)]','',text)
    return re.sub(r'^(?:已确认|已确定|已经确认|已经确定|已核实|已核对|已列齐)[：:。]\s*(?=\S)','',text)

def pattern_matches(pattern,text):
    if re.search(pattern,text) or re.search(pattern,canonical(text)):return True
    for alternative in pattern.split('|'):
        if alternative and not re.search(r'[\\.^$*+?{}\[\]()]',alternative) and canonical(alternative) in canonical(text):return True
    return False

def deployment_parent(source,child,parent):
    if not parent or not child or child==parent:return False
    if not re.search(r'(?:区|台|站|库|间|点|车间|节点|终端|号炉)$',child):return False
    for paragraph in re.split(r'[。！？\n]',source):
        if re.search(re.escape(parent)+r'(?:已|已经|只|目前|尚未)',paragraph) and child in paragraph and paragraph.find(parent)<paragraph.find(child):return True
    return False
