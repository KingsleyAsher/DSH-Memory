"""Versioned deterministic policy; settings are not learned weights."""
from dataclasses import dataclass,asdict
import math
HISTORY=r'最初|最开始|最早|第一版|初版|首次|一开始|初始|原始|修改前|更正前|第一次|初次|调整前|更改前|更换前|迁移前|(?:更改|调整|更正|更新).{0,4}(?:之前|以前)'
CURRENT=r'(?:别|不要|不是|不想).{0,5}(?:旧版|以前|历史|原来)|(?:只|仅).{0,4}(?:当前|现在|最新|现行)'
EXAMPLE=r'示例|演示|说明书|说明文档|文档里|样例|举例|手册|示范'
ACTUAL=r'(?:别|不要|不是|不看).{0,6}(?:示例|演示|样例)|(?:只|仅).{0,5}(?:实际|正式|现场|真实|生产)'
VALUE_FIELDS={'reminder_time','archive_path','service_port','contact_phone'}
SCOPED_FIELDS={'incident_cause','incident_solution','incident_rule','deployment_state'}
FIELD_LABELS={'reminder_time':'通知时间','archive_path':'归档目录','service_port':'监听端口','contact_phone':'联系电话','other':'其他事实','preference':'答复偏好','deployment_state':'部署状态','incident_cause':'原因','incident_solution':'有效处理','incident_rule':'防错要求'}
@dataclass(frozen=True)
class Config:
    semantic:bool=False
    view_cap:int=4
    vector_budget_bytes:int=64*1024*1024
    candidate_limit:int=160
    path_limit:int=16
    max_rounds:int=2
    memory_tokens:int=768
    max_units:int=4
    knowledge_enabled:bool=False
    max_extract_attempts:int=2
    answer_tokens:int=640
    query_planner:str='rules'
    ranking_weights:tuple=(.65,.20,.10,.05,.25)
    raw_recall:bool=True
    semantic_state:bool=True
    candidate_review:bool=False
    extraction_mode:str='token_threshold'
    extraction_threshold_tokens:int=256000
    extraction_retry_seconds:int=60
    consolidation_wire:str='compact'
    consolidation_input_tokens:int=2200
    consolidation_output_tokens:int=1400
    consolidation_context_tokens:int=4096
    consolidation_max_sources:int=6
    consolidation_max_batches:int=8
    raw_max_chunks:int=4
    raw_tokens:int=1200
    def __post_init__(self):
        if self.extraction_mode not in ['before_compact','immediate','token_threshold']:raise ValueError('invalid extraction mode')
        if type(self.extraction_threshold_tokens) is not int or not 1<=self.extraction_threshold_tokens<=2000000:raise ValueError('invalid extraction threshold')
        if type(self.extraction_retry_seconds) is not int or not 0<=self.extraction_retry_seconds<=86400:raise ValueError('invalid extraction retry interval')
        if self.consolidation_wire not in ['full','compact','operations']:raise ValueError('invalid consolidation wire')
        if type(self.consolidation_context_tokens) is not int or not 2048<=self.consolidation_context_tokens<=131072:raise ValueError('invalid consolidation context capability')
        if not 1200<=self.consolidation_input_tokens<=65536 or not 512<=self.consolidation_output_tokens<=8192:raise ValueError('invalid consolidation token budget')
        if self.consolidation_input_tokens+self.consolidation_output_tokens+256>self.consolidation_context_tokens:raise ValueError('consolidation exceeds declared context allowance')
        if not 1<=self.consolidation_max_sources<=24 or not 1<=self.consolidation_max_batches<=32:raise ValueError('invalid consolidation batch budget')
        if type(self.candidate_review) is not bool:raise ValueError('invalid candidate review flag')
        if self.view_cap not in [1,2,3,4] or self.max_rounds not in [1,2]:raise ValueError('unsupported view/round budget')
        if not 128<=self.memory_tokens<=2048 or not 1<=self.max_units<=8:raise ValueError('invalid context budget')
        if not 16<=self.candidate_limit<=512 or not 1<=self.path_limit<=64:raise ValueError('invalid candidate budget')
        if self.vector_budget_bytes<4096:raise ValueError('vector budget too small')
        if self.query_planner not in ['rules','local']:raise ValueError('unsupported planner')
        if not 1<=self.raw_max_chunks<=6 or not 256<=self.raw_tokens<=1800:raise ValueError('invalid original-text budget')
        if len(self.ranking_weights)!=5 or any(not isinstance(w,(int,float)) or not math.isfinite(w) or w<0 for w in self.ranking_weights) or sum(self.ranking_weights)<=0:raise ValueError('invalid ranking weights')
        object.__setattr__(self,'ranking_weights',tuple(self.ranking_weights))
    def to_dict(self):return asdict(self)
