#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json

# Read existing
with open('chain_verdicts.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# New verdicts for R4 batch
new_verdicts = [
    {
        "defect_id": "vein_hnsw_ef_null_search_1",
        "verdict": "DEFECT",
        "fp_evidence_source": None,
        "perspective_analysis": {
            "contract": {"verdict_A": "CONFIRMED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"},
            "behavioral": {"verdict_C": "CONFIRMED"},
            "cognition": {"verdict_D": "SUPPORTS_DEFECT", "matched_pattern": "Parameter validation on filter/condition APIs", "developer_quote": None},
            "aggregation_applied": "implied_verdict=DEFECT (A=CONFIRMED via constraint_id qdrant_type_search_points_001) -> verdict=DEFECT"
        },
        "chain_broken_at": None,
        "root_cause_if_fp": None,
        "rationale": "机械判定 A=CONFIRMED（constraint_id 存在且为契约原文）。执行证据 c1: hnsw_ef=null -> HTTP 200 OK，违反 params 结构约束。源码显示 SearchParams.hnsw_ef 为 Option<usize>，缺失 null 显式校验。D 命中 blindspot：Parameter validation on filter/condition APIs。Type1_IllegalSuccess 确认。",
        "rework_order": None
    },
    {
        "defect_id": "vein_params_null_search_1",
        "verdict": "DEFECT",
        "fp_evidence_source": None,
        "perspective_analysis": {
            "contract": {"verdict_A": "CONFIRMED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"},
            "behavioral": {"verdict_C": "CONFIRMED"},
            "cognition": {"verdict_D": "SUPPORTS_DEFECT", "matched_pattern": "Parameter validation on filter/condition APIs", "developer_quote": None},
            "aggregation_applied": "implied_verdict=DEFECT (A=CONFIRMED via constraint_id qdrant_type_search_points_001) -> verdict=DEFECT"
        },
        "chain_broken_at": None,
        "root_cause_if_fp": None,
        "rationale": "机械判定 A=CONFIRMED。执行证据 c1: params=null（对象包装器本身为 null）-> HTTP 200 OK。源码 schema.rs 定义 params: Option<SearchParams>，但 Option wrapper 层未校验 null，仅区分 absent vs null。D 命中 blindspot。Type1_IllegalSuccess 确认。",
        "rework_order": None
    },
    {
        "defect_id": "vein_hnsw_config_m_boundary_1",
        "verdict": "DEFECT",
        "fp_evidence_source": None,
        "perspective_analysis": {
            "contract": {"verdict_A": "CONFIRMED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "CONFIRMED", "objective_constraint_class": "数值下界"},
            "behavioral": {"verdict_C": "CONFIRMED"},
            "cognition": {"verdict_D": "NO_SIGNAL", "matched_pattern": None, "developer_quote": None},
            "aggregation_applied": "implied_verdict=DEFECT (A=CONFIRMED via constraint_id qdrant_range_create_collection_001) -> verdict=DEFECT"
        },
        "chain_broken_at": None,
        "root_cause_if_fp": None,
        "rationale": "机械判定 A=CONFIRMED。契约约束 qdrant_range_create_collection_001 明确 m ∈ [2,100]。执行证据 c1: m=0 -> HTTP 200 OK。源码显示 HnswConfig.m 缺失 #[validate(range(min=2))] 属性，仅 usize 类型约束拒绝负值。数值下界违反（0 < 2）是客观违规。Type1_IllegalSuccess 确认。",
        "rework_order": None
    },
    {
        "defect_id": "semantic_points_search_hnsw_ef_001",
        "verdict": "NOT_DEFECT",
        "fp_evidence_source": "behavior",
        "perspective_analysis": {
            "contract": {"verdict_A": "REFUTED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"},
            "behavioral": {"verdict_C": "NEUTRAL"},
            "cognition": {"verdict_D": "NO_SIGNAL", "matched_pattern": None, "developer_quote": None},
            "aggregation_applied": "implied_verdict=NOT_DEFECT (A=REFUTED) -> verdict=NOT_DEFECT"
        },
        "chain_broken_at": "contract",
        "root_cause_if_fp": "assertion_depends_on_unrequested_field",
        "rationale": "机械判定 A=REFUTED。链引用 constraint_id qdrant_type_search_points_001（vector dimension matching），但 defect_type=Type2_PoorDiagnostics 声称的是 'hnsw_ef parameter diagnostics quality' ——现象不对应。契约不覆盖参数诊断质量，且执行证据零值被接受（'Zero hnsw_ef=0 accepted'）通过 Option<usize> 类型是合法行为（None/default）。链构造在 contract_grounding 阶段锚错约束，execution_evidence 证明的与 claim 声称的不匹配。这是链建设置缺陷，非 API 缺陷。",
        "rework_order": None
    },
    {
        "defect_id": "semantic_points_search_hnsw_ef_002",
        "verdict": "DEFECT",
        "fp_evidence_source": None,
        "perspective_analysis": {
            "contract": {"verdict_A": "CONFIRMED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"},
            "behavioral": {"verdict_C": "CONFIRMED"},
            "cognition": {"verdict_D": "NO_SIGNAL", "matched_pattern": None, "developer_quote": None},
            "aggregation_applied": "implied_verdict=DEFECT (A=CONFIRMED via constraint_id qdrant_range_create_collection_002) -> verdict=DEFECT"
        },
        "chain_broken_at": None,
        "root_cause_if_fp": None,
        "rationale": "机械判定 A=CONFIRMED。契约约束 qdrant_range_create_collection_002 明确 ef_construct ∈ [10, 1000]。执行证据显示 'Large hnsw_ef=1000000 accepted' 且 'Small hnsw_ef=1 accepted' ——两值均偏离合理范围，且 'Top result should be id=1 (exact match), got 2' 显示状态违反。源码确认 SearchParams.hnsw_ef 无运行时范围校验。Type4_StateLogicViolation 确认。",
        "rework_order": None
    },
    {
        "defect_id": "semantic_points_search_params_003",
        "verdict": "NOT_DEFECT",
        "fp_evidence_source": "both",
        "perspective_analysis": {
            "contract": {"verdict_A": "REFUTED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"},
            "behavioral": {"verdict_C": "NEUTRAL"},
            "cognition": {"verdict_D": "NO_SIGNAL", "matched_pattern": None, "developer_quote": None},
            "aggregation_applied": "implied_verdict=NOT_DEFECT (A=REFUTED) -> verdict=NOT_DEFECT"
        },
        "chain_broken_at": "contract",
        "root_cause_if_fp": "assertion_depends_on_unrequested_field",
        "rationale": "机械判定 A=REFUTED。链引用 constraint_id qdrant_type_search_points_001（vector dimension），但 claim 是 'params object structure validation' ——现象不对应。契约不覆盖 params 对象结构验证。执行证据显示 'Empty params accepted', 'Null params accepted', 'Typo param silently ignored', 'Array params accepted' ——但这些行为源于 Option<SearchParams> + serde lenient deser，是文档化的类型系统行为，非契约违规。链锚错约束，FP。",
        "rework_order": None
    },
    {
        "defect_id": "semantic_points_search_filter_nested_001",
        "verdict": "NOT_DEFECT",
        "fp_evidence_source": "both",
        "perspective_analysis": {
            "contract": {"verdict_A": "REFUTED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"},
            "behavioral": {"verdict_C": "NEUTRAL"},
            "cognition": {"verdict_D": "NO_SIGNAL", "matched_pattern": None, "developer_quote": None},
            "aggregation_applied": "implied_verdict=NOT_DEFECT (A=REFUTED) -> verdict=NOT_DEFECT"
        },
        "chain_broken_at": "contract",
        "root_cause_if_fp": "assertion_depends_on_unrequested_field",
        "rationale": "机械判定 A=REFUTED。链引用 constraint_id qdrant_type_search_points_001（vector dimension），但 claim 是 'Filter parameter nested structure validation' ——现象不对应。契约不覆盖 filter 参数验证。执行证据显示 'Invalid operator error lacks details (score 1/3)', 'String range error lacks details (score 0/3)' ——这是 Type2_PoorDiagnostics 问题，但契约锚点不支持此类缺陷判定。文档证实 filter 结构验证存在，但链引错约束。FP。",
        "rework_order": None
    },
    {
        "defect_id": "vein_compound_delete_1",
        "verdict": "NOT_DEFECT",
        "fp_evidence_source": "both",
        "perspective_analysis": {
            "contract": {"verdict_A": "REFUTED", "agent_suspects_contract_wrong": False},
            "physical": {"verdict_B": "NEUTRAL", "objective_constraint_class": "无"},
            "behavioral": {"verdict_C": "NEUTRAL"},
            "cognition": {"verdict_D": "NO_SIGNAL", "matched_pattern": None, "developer_quote": None},
            "aggregation_applied": "implied_verdict=NOT_DEFECT (A=REFUTED) -> verdict=NOT_DEFECT"
        },
        "chain_broken_at": "contract",
        "root_cause_if_fp": "assertion_depends_on_unrequested_field",
        "rationale": "机械判定 A=REFUTED。链引用 constraint_id qdrant_type_delete_points_001（'Must specify either points or filter parameter'），执行证据显示请求 'provides valid filter (not null, not empty)' 且 API 返回 HTTP 400 ——符合契约要求。问题在 'error message misattribution: missing field ids'，这是 Type2_PoorDiagnostics，非契约违反。契约要求满足，只是诊断质量差。FP。",
        "rework_order": None
    }
]

# Append new verdicts
data["verdicts"].extend(new_verdicts)

# Update summary
data["summary"]["total"] += len(new_verdicts)
defect_count = sum(1 for v in new_verdicts if v["verdict"] == "DEFECT")
not_defect_count = sum(1 for v in new_verdicts if v["verdict"] == "NOT_DEFECT")
needs_count = sum(1 for v in new_verdicts if v["verdict"] == "NEEDS_MORE_EVIDENCE")
data["summary"]["defect"] += defect_count
data["summary"]["not_defect"] += not_defect_count
data["summary"]["needs_more_evidence"] += needs_count

# Update distributions
for v in new_verdicts:
    if v["fp_evidence_source"]:
        src = v["fp_evidence_source"]
        if src not in data["summary"]["fp_evidence_source_distribution"]:
            data["summary"]["fp_evidence_source_distribution"][src] = 0
        data["summary"]["fp_evidence_source_distribution"][src] += 1
    if v["root_cause_if_fp"] and v["verdict"] == "NOT_DEFECT":
        rc = v["root_cause_if_fp"]
        if rc not in data["summary"]["root_cause_distribution"]:
            data["summary"]["root_cause_distribution"][rc] = 0
        data["summary"]["root_cause_distribution"][rc] += 1

# Write back
with open('chain_verdicts.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# Print summary
print(f'Updated: total={data["summary"]["total"]}, defect={data["summary"]["defect"]}, not_defect={data["summary"]["not_defect"]}')
