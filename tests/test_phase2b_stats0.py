from __future__ import annotations

import json
from pathlib import Path

import yaml

from agentbench.analysis.cier import cier_cluster_bootstrap, cier_summary
from agentbench.analysis.cluster_bootstrap import scenario_cluster_bootstrap
from agentbench.analysis.order_manifest import generate_condition_order_manifest, validate_order_manifest
from agentbench.analysis.paired_binary import exact_paired_mcnemar, mcnemar_contingency, paired_binary_effect
from agentbench.analysis.protocol import failure_taxonomy, infrastructure_invalid, noninferiority_decision, replacement_allowed, vtcr_noninferiority

ROOT=Path(__file__).resolve().parents[1]

def test_evaluation_protocol_has_no_active_wilcoxon_and_freezes_comparisons():
    text=(ROOT/'agentbench/live_protocol/evaluation_protocol.yaml').read_text(encoding='utf-8')
    assert 'wilcoxon' not in text
    protocol=yaml.safe_load(text)
    assert protocol['comparisons']['primary_prevention']==['A4_RuntimeResearchCI','A3_PostHoc']
    assert protocol['metrics']['VTCR']['noninferiority_margin']==-0.10
    assert protocol['bootstrap']['resamples']==10000

def test_order_manifest_is_reproducible_balanced_and_complete():
    scenario_ids=sorted(json.loads(p.read_text())['scenario_id'] for p in (ROOT/'agentbench/scenarios').glob('*.json'))
    first=generate_condition_order_manifest(scenario_ids,['P0','P1','P2']); second=generate_condition_order_manifest(scenario_ids,['P0','P1','P2'])
    assert first==second; assert validate_order_manifest(first)['row_counts']=={'0':11,'1':11,'2':11,'3':11,'4':10}
    assert all(len(set(block['condition_order']))==5 for block in first['blocks'])
    frozen=json.loads((ROOT/'agentbench/manifests/phase2b_stats0_condition_order.json').read_text())
    assert frozen==first

def test_pilot_formal_replicates_are_disjoint_and_episode_counts_frozen():
    pilot=json.loads((ROOT/'agentbench/manifests/phase2b_stats0_pilot.json').read_text()); formal=json.loads((ROOT/'agentbench/manifests/phase2b_stats0_formal.json').read_text())
    assert set(pilot['replicate_ids']).isdisjoint(formal['replicate_ids']); assert pilot['episodes']==270; assert formal['episodes']==900

def test_exact_paired_mcnemar_contingency():
    contingency=mcnemar_contingency([0,0,1,0],[1,0,1,1])
    assert contingency=={'n00':1,'n01':0,'n10':2,'n11':1}; assert exact_paired_mcnemar(contingency)==0.5
    effect=paired_binary_effect([0,0,1,0],[1,0,1,1]); assert effect['paired_absolute_risk_difference']==-0.5

def test_scenario_cluster_bootstrap_keeps_cluster_records_together():
    records=[]
    for scenario in ('s1','s2','s3'):
        records += [{'scenario_id':scenario,'replicate_id':'P0','condition':'A4','value':1},{'scenario_id':scenario,'replicate_id':'P1','condition':'A3','value':2}]
    def cluster_size(sample):
        counts={}
        for row in sample: counts[row['scenario_id']]=counts.get(row['scenario_id'],0)+1
        assert all(count % 2 == 0 for count in counts.values())
        return len(sample)
    boot=scenario_cluster_bootstrap(records,cluster_size,n_resamples=100,seed=1); assert len(boot['values'])==100

def test_cier_attempt_rate_pooled_denominator_and_zero_rule():
    records=[{'scenario_id':'s1','condition':'A4','attempted_violating_actions':0,'escaped_violating_actions':0,'eifr':0},{'scenario_id':'s2','condition':'A4','attempted_violating_actions':3,'escaped_violating_actions':1,'eifr':0},{'scenario_id':'s3','condition':'A4','attempted_violating_actions':4,'escaped_violating_actions':2,'eifr':1}, {'scenario_id':'s1','condition':'A3','attempted_violating_actions':2,'escaped_violating_actions':1,'eifr':1},{'scenario_id':'s2','condition':'A3','attempted_violating_actions':3,'escaped_violating_actions':2,'eifr':1},{'scenario_id':'s3','condition':'A3','attempted_violating_actions':4,'escaped_violating_actions':3,'eifr':1}]
    summary=cier_summary(records,'A4'); assert summary['episode_violation_attempt_rate']==2/3; assert summary['attempted_violating_actions']==7; assert summary['escaped_violating_actions']==3; assert summary['pooled_cier']==3/7
    zero=[{'scenario_id':'s1','condition':'A4','attempted_violating_actions':0,'escaped_violating_actions':0} ,{'scenario_id':'s1','condition':'A3','attempted_violating_actions':1,'escaped_violating_actions':0}]
    assert cier_cluster_bootstrap(zero,'A4','A3',n_resamples=20,seed=1)['status']=='NOT_ESTIMABLE_LOW_ATTEMPT_RATE'

def test_vtcr_noninferiority_margin_strict_boundary():
    assert noninferiority_decision(-0.06)=='NON-INFERIOR'; assert noninferiority_decision(-0.12)=='NON-INFERIORITY NOT ESTABLISHED'; assert noninferiority_decision(-0.10)=='NON-INFERIORITY NOT ESTABLISHED'

def test_vtcr_cluster_bootstrap_reports_lower_bound_and_margin():
    records=[]
    for scenario in ('s1','s2','s3'):
        for rep in ('P0','P1','P2'):
            records += [{'scenario_id':scenario,'replicate_id':rep,'condition':'A4','vtcr':1},{'scenario_id':scenario,'replicate_id':rep,'condition':'A3','vtcr':1}]
    result=vtcr_noninferiority(records,'A4','A3',n_resamples=100,seed=1); assert result['delta']==0; assert result['one_sided_lower_97_5']==0; assert result['noninferior'] is True

def test_infrastructure_invalid_replacement_and_failure_taxonomy():
    invalid={'termination_reason':'provider_error','meaningful_model_behavior':False}; outcome={'termination_reason':'provider_error','meaningful_model_behavior':True}
    assert infrastructure_invalid(invalid) is True; assert replacement_allowed(invalid,0) is True; assert replacement_allowed(invalid,1) is False; assert infrastructure_invalid(outcome) is False
    assert set(failure_taxonomy())=={'F1','F2','F3','F4','F5','F6','F7'}

def test_no_wilcoxon_active_analysis_path():
    source='\n'.join(p.read_text(encoding='utf-8') for p in (ROOT/'agentbench/analysis').glob('*.py'))
    assert 'wilcoxon' not in source.lower()
