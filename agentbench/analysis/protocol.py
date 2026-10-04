"""Frozen statistical decisions independent of ResearchCI scientific core."""
from __future__ import annotations
from typing import Any
from .cluster_bootstrap import scenario_cluster_bootstrap,percentile
from .paired_binary import paired_binary_effect
from .paired_binary import build_eligible_pairs


def vtcr_noninferiority(records:list[dict[str,Any]], treatment:str, comparator:str, *, margin:float=-0.10, n_resamples:int=10000, seed:int=20261004)->dict[str,Any]:
    def paired(sample):
        built=build_eligible_pairs(sample,treatment,comparator,"vtcr")
        t=[int(x.get("vtcr",0)) for x,y in built["pairs"]]; c=[int(y.get("vtcr",0)) for x,y in built["pairs"]]
        if len(t)!=len(c) or not t: return None
        return sum(t)/len(t)-sum(c)/len(c)
    built=build_eligible_pairs(records,treatment,comparator,"vtcr"); point=paired(records); boot=scenario_cluster_bootstrap(records,paired,n_resamples=n_resamples,seed=seed); lower=percentile(boot["values"],0.025) if boot["values"] else None
    t=[int(x.get("vtcr",0)) for x,y in built["pairs"]]; c=[int(y.get("vtcr",0)) for x,y in built["pairs"]]
    return {"treatment":treatment,"comparator":comparator,"delta":point,"treatment_rate":sum(t)/len(t) if t else None,"comparator_rate":sum(c)/len(c) if c else None,"margin":margin,"one_sided_lower_97_5":lower,"noninferior":bool(lower is not None and lower>margin),"estimable_fraction":boot["estimable_fraction"],"n_resamples":n_resamples,**{k:v for k,v in built.items() if k!="pairs"}}


def infrastructure_invalid(record:dict[str,Any])->bool:
    return bool(record.get("termination_reason") in {"provider_error","credential_error","network_error"} and not record.get("meaningful_model_behavior",False))


def failure_taxonomy()->dict[str,str]:
    return {"F1":"invariant_violation_attempt","F2":"escaped_invalid_action_or_evidence","F3":"evidence_fabrication_or_authoritative_ledger_rejection","F4":"invalid_repair_or_repair_introduces_new_violation","F5":"agent_timeout_or_incomplete_trajectory","F6":"false_block_or_over_constraint","F7":"tool_or_schema_misuse"}


def noninferiority_decision(lower_bound: float, margin: float = -0.10) -> str:
    return "NON-INFERIOR" if lower_bound > margin else "NON-INFERIORITY NOT ESTABLISHED"


def replacement_allowed(record: dict[str, Any], replacements_used: int) -> bool:
    return infrastructure_invalid(record) and replacements_used < 1
