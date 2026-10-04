"""Deterministic Latin-square condition order manifest."""
from __future__ import annotations
import hashlib
from typing import Any

CONDITIONS=("A0_NoCheck","A1_Schema","A2_Provenance","A3_PostHoc","A4_RuntimeResearchCI")

def generate_condition_order_manifest(scenario_ids:list[str], replicate_ids:list[str])->dict[str,Any]:
    rotations=[list(CONDITIONS[i:]+CONDITIONS[:i]) for i in range(len(CONDITIONS))]
    blocks=[]
    for scenario in sorted(scenario_ids):
        for replicate in replicate_ids:
            block_hash="sha256:"+hashlib.sha256(("ResearchCI-Phase2-order-v1"+scenario+replicate).encode()).hexdigest()
            blocks.append({"scenario_id":scenario,"replicate_id":replicate,"block_hash":block_hash})
    blocks.sort(key=lambda b:b["block_hash"])
    for index,block in enumerate(blocks):
        row=index%len(rotations); block["latin_row"]=row; block["condition_order"]=rotations[row]
    return {"version":"phase2b-stats0-order-v1","hash_input_prefix":"ResearchCI-Phase2-order-v1","canonical_conditions":list(CONDITIONS),"blocks":blocks}


def validate_order_manifest(manifest:dict[str,Any])->dict[str,Any]:
    blocks=manifest["blocks"]; conditions=set(CONDITIONS)
    if any(set(b["condition_order"])!=conditions or len(b["condition_order"])!=5 for b in blocks): raise ValueError("each block must contain each condition once")
    positions={condition:[i for b in blocks for i,x in enumerate(b["condition_order"]) if x==condition] for condition in CONDITIONS}
    return {"blocks":len(blocks),"position_counts":{str(i):sum(pos.count(i) for pos in positions.values()) for i in range(5)},"row_counts":{str(i):sum(b["latin_row"]==i for b in blocks) for i in range(5)},"valid":True}
