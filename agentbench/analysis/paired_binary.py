"""Paired binary effects and exact paired McNemar support."""
from __future__ import annotations
from math import comb
from typing import Any


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
