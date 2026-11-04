"""Recover source-contiguous capability/location relations, not world facts."""
import re
from .extraction_base import make_fact,local_kind

def deployment_frames(text,facts):
    records=[];context=''
    state=r'已经部署|已经上线|已部署|已上线|尚未部署|仍未部署|未部署|还没有上线|还没上线|尚未上线|仍未上线|未上线|计划部署|计划上线|只在|仅在'
    for paragraph in re.finditer(r'[^。！？\n]+[。！？]?',text):
        if not re.search(state,paragraph.group()):continue
        chunks=list(re.finditer(r'[^；;]+[；;]?',paragraph.group()));groups=[]
        for chunk in chunks:
            raw=chunk.group();m=re.match(r'\s*(?:另外|而|至于|目前|现在)?\s*([\u4e00-\u9fffA-Za-z0-9]{1,16}?)('+state+')',raw)
            name=m.group(1) if m else ''
            if not m:
                if groups:groups[-1]['end']=paragraph.start()+chunk.end()
                continue
            is_area=bool(re.search(r'(?:区|台|站|库|间|点|车间|节点|终端|号炉)$',name)) and not bool(re.search(r'告警|报警|监控|自动|功能|系统',name))
            if is_area and context:name=context
            else:context=name
            start=paragraph.start()+chunk.start();end=paragraph.start()+chunk.end()
            if groups and groups[-1]['name']==name:groups[-1]['end']=end
            else:groups.append(dict(name=name,start=start,end=end))
        for group in groups:
            if records and records[-1]['name']==group['name'] and text[records[-1]['end']:group['start']].strip('。；;\n ' )=='':records[-1]['end']=group['end']
            else:records.append(group)
    if not records:return facts
    out=[f for f in facts if f['field']!='deployment_state' or not any(f['quote'] in text[r['start']:r['end']] or text[r['start']:r['end']] in f['quote'] for r in records)]
    for r in records:
        quote=text[r['start']:r['end']];state_value='planned' if re.search(r'计划部署|计划上线',quote) and not re.search(r'已部署|已上线',quote) else 'stated'
        out.append(make_fact('deployment_state',quote,quote,topic=r['name'],kind=local_kind(text,quote),epistemic=state_value))
    return out
