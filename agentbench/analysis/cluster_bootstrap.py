"""Scenario-cluster bootstrap with pairing preserved."""
from __future__ import annotations
import random
from copy import deepcopy
from collections import defaultdict
from typing import Any, Callable


def scenario_cluster_bootstrap(records:list[dict[str,Any]], statistic:Callable[[list[dict[str,Any]]],Any], *, n_resamples:int=10000, seed:int=20261004) -> dict[str,Any]:
    clusters=defaultdict(list)
    for record in records: clusters[record["scenario_id"]].append(record)
    scenario_ids=sorted(clusters)
    if not scenario_ids: raise ValueError("records must contain scenario clusters")
    rng=random.Random(seed); values=[]; non_estimable=0
    for _ in range(n_resamples):
        selected=[rng.choice(scenario_ids) for _ in scenario_ids]
        sample=materialize_cluster_draw(records, selected)
        value=statistic(sample)
        if value is None: non_estimable+=1
        else: values.append(float(value))
    return {"values":values,"n_resamples":n_resamples,"estimable":len(values),"non_estimable":non_estimable,"estimable_fraction":len(values)/n_resamples}


def materialize_cluster_draw(records:list[dict[str,Any]], selected:list[str]) -> list[dict[str,Any]]:
    clusters=defaultdict(list)
    for record in records: clusters[record["scenario_id"]].append(record)
    sample=[]
    for instance, scenario in enumerate(selected):
        for record in clusters[scenario]:
            copied=deepcopy(record); copied["__bootstrap_cluster_instance"]=instance; sample.append(copied)
    return sample


def percentile(values:list[float], q:float) -> float:
    if not values: raise ValueError("no estimable bootstrap draws")
    ordered=sorted(values); position=(len(ordered)-1)*q; lower=int(position); upper=min(lower+1,len(ordered)-1); fraction=position-lower
    return ordered[lower]+(ordered[upper]-ordered[lower])*fraction


def percentile_interval(values:list[float], confidence:float=0.95)->tuple[float,float]:
    alpha=(1-confidence)/2; return percentile(values,alpha),percentile(values,1-alpha)
