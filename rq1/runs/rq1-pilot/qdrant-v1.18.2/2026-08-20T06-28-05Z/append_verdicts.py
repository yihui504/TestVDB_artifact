import json
with open("debate_logs/chain_verdicts.json", "r", encoding="utf-8") as f: data = json.load(f)
new = []
new.append({"defect_id": "vein_query_filter_validation_1", "verdict": "DEFECT", "fp_evidence_source": None, "perspective_analysis": {"contract": {"verdict_A": "NEUTRAL", "agent_suspects_contract_wrong": False}, "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"}, "behavioral": {"verdict_C": "CONFIRMED"}, "cognition": {"verdict_D": "SUPPORTS_DEFECT", "matched_pattern": "Parameter validation on filter/condition APIs", "developer_quote": None}, "aggregation_applied": "A=NEUTRAL, B=NEUTRAL, C=CONFIRMED, D=SUPPORTS_DEFECT"}, "chain_broken_at": None, "root_cause_if_fp": None, "rationale": "Type1_IllegalSuccess", "rework_order": None})
