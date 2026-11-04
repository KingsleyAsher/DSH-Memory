"""Field-local mutation intent. Unchanged references never create barriers."""
import re
from .contract import EXAMPLE,normalize
from .extraction_base import anchors,local_kind

ALIASES={'reminder_time':r'提醒|通知|简报|日报|钟点|时刻','archive_path':r'归档|目录|路径|文件夹','service_port':r'端口|监听','contact_phone':r'电话|手机|联系方式'}
UNKNOWN_VALUE=r'待定|未定|没有.{0,4}(?:具体|准确|完整|新).{0,3}(?:号|值|路径|时间)|尚未确定|还没定|没有定|没定|尚未定|还没.{0,3}(?:定|选)|未.{0,3}(?:确定|给出)|尚不明确'
CHANGE=r'更正|改(?:成|到|为|用)|调整(?:为|到)|换(?:成|到)|更换|要换|要更换|准备改|以.+为准|定(?:为|到|下)|撤销|撤掉|取消|暂停|停止|不再用'
UNCHANGED=r'不变|照旧|沿用|保持|仍是|仍用|还是.{0,8}(?:那一项|那个|原来)|没有改|没改'
INSTRUCTION=r'别把|不要把|不能把|不应把|不要因为|不能因为|不等于|不代表'

def mutations(text):
    actions={}
    for sentence in re.split(r'[。！？\n]',text):
        context=[]
        for clause in re.split(r'[，,；;]',sentence):
            if re.search(INSTRUCTION,clause):continue
            if re.search(r'(?:不是|并非|不要|不应|不能).{0,10}(?:待定|未定|未知)|(?:没有|并未|未).{0,3}(?:撤回|收回|取消|撤销)',clause):continue
            found=[f for f,p in ALIASES.items() if re.search(p,clause)]
            if found:context=found
            fields=found or context
            if not fields:continue
            if re.search(EXAMPLE,sentence) and not re.search(r'实际|正式|现场|生产',sentence):continue
            if re.search(UNCHANGED,clause):
                for f in fields:
                    if actions.get(f)!='set':actions[f]='unchanged'
                continue
            if re.search(UNKNOWN_VALUE,clause):
                for f in fields:actions[f]='pending'
            elif re.search(CHANGE,clause):
                literals=anchors(sentence)
                for f in fields:
                    values=[a for a in literals if a['field']==f and a['kind']=='fact' and a['value_text'] in clause]
                    actions[f]='set' if f=='reminder_time' and normalize(f,clause)=='__unset__' else 'planned' if values and all(a['epistemic']=='planned' for a in values) else 'set' if values else actions.get(f,'pending')
    return actions
