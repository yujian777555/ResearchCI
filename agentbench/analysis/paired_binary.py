"""Paired binary effects and exact paired McNemar support."""
from __future__ import annotations
from math import comb
from typing import Any
from .cluster_bootstrap import scenario_cluster_bootstrap, percentile_interval
from .eligibility import is_infra_invalid, is_efficacy_eligible


def mcnemar_contingency(treatment: list[int], comparator: list[int]) -> dict[str,int]:
    if len(treatment) != len(comparator): raise ValueError("paired outcomes must have equal length")
    if any(x not in (0,1) for x in treatment+comparator): raise ValueError("binary outcomes must be 0/1")
    return {"n00":sum(t==0 and c==0 for t,c in zip(treatment,comparator)),"n01":sum(t==1 and c==0 for t,c in zip(treatment,comparator)),"n10":sum(t==0 and c==1 for t,c in zip(treatment,comparator)),"n11":sum(t==1 and c==1 for t,c in zip(treatment,comparator))}


def exact_paired_mcnemar(contingency: dict[str,int]) -> float:
    n01,n10=contingency["n01"],contingency["n10"]; n=n01+n10
    if n==0: return 1.0
    k=min(n01,n10); tail=sum(comb(n,i) for i in range(k+1))/(2**n)
    return min(1.0,2*tail)


def paired_binary_effect(treatment: list[int], comparator: list[int]) -> dict[str,Any]:
    c=mcnemar_contingency(treatment,comparator); n=len(treatment)
    return {"treatment_rate":sum(treatment)/n if n else None,"comparator_rate":sum(comparator)/n if n else None,"paired_absolute_risk_difference":(sum(treatment)-sum(comparator))/n if n else None,"discordant":c,"exact_mcnemar_p":exact_paired_mcnemar(c),"n_pairs":n}


def build_eligible_pairs(records: list[dict[str, Any]], treatment: str, comparator: str, endpoint: str) -> dict[str, Any]:
    grouped: dict[tuple[Any, str, str], dict[str, dict[str, Any]]] = {}
    dropped: dict[tuple[Any, str], dict[str, dict[str, Any]]] = {}
    for record in records:
        key=(record.get("__bootstrap_cluster_instance"), record["scenario_id"], record["replicate_id"])
        grouped.setdefault(key, {})[record["condition"]]=record
    pairs=[]; dropped_infra=0; missing=0; treatment_infra=0; comparator_infra=0
    for values in grouped.values():
        t=values.get(treatment); c=values.get(comparator)
        if t is None or c is None:
            missing += 1; continue
        if not is_efficacy_eligible(t) or not is_efficacy_eligible(c):
            dropped_infra += 1; treatment_infra += int(is_infra_invalid(t)); comparator_infra += int(is_infra_invalid(c)); continue
        pairs.append((t,c))
    return {"pairs":pairs,"eligible_pairs":len(pairs),"dropped_pairs_infra_invalid":dropped_infra,"dropped_pairs_missing_member":missing,"treatment_infra_invalid_count":treatment_infra,"comparator_infra_invalid_count":comparator_infra,"infra_invalid_excluded_records":treatment_infra+comparator_infra}


def analyze_eifr_paired(records: list[dict[str, Any]], treatment: str, comparator: str, *, n_resamples: int=10000, seed: int=20261004) -> dict[str, Any]:
    def statistic(sample):
        built=build_eligible_pairs(sample,treatment,comparator,"eifr")
        if not built["pairs"]: return None
        return (sum(t.get("eifr", t.get("episode_integrity_failure",0)) for t,c in built["pairs"])-sum(c.get("eifr", c.get("episode_integrity_failure",0)) for t,c in built["pairs"]))/len(built["pairs"])
    built=build_eligible_pairs(records,treatment,comparator,"eifr")
    tv=[int(t.get("eifr",t.get("episode_integrity_failure",0))) for t,c in built["pairs"]]; cv=[int(c.get("eifr",c.get("episode_integrity_failure",0))) for t,c in built["pairs"]]
    effect=paired_binary_effect(tv,cv) if tv else {"treatment_rate":None,"comparator_rate":None,"paired_absolute_risk_difference":None,"discordant":{"n00":0,"n01":0,"n10":0,"n11":0},"exact_mcnemar_p":None,"n_pairs":0}
    boot=scenario_cluster_bootstrap(records,statistic,n_resamples=n_resamples,seed=seed)
    result={"treatment":treatment,"comparator":comparator,**effect,**{k:built[k] for k in built if k!="pairs"},"bootstrap_resamples":n_resamples,"bootstrap_seed":seed,"cluster_unit":"scenario_id_cluster","percentile_ci_95":percentile_interval(boot["values"]) if boot["values"] else None}
    return result
