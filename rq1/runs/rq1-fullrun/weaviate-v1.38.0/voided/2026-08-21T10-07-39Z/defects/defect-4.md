# Defect 4: 多属性 groupBy 报 "missing an argument" 误导诊断

## Metadata
- Defect ID: TESTVDB-WEAVIATE-004 (semantic_aggregate_math_06)
- Type: Type2_PoorDiagnostics
- Severity: Low
- Endpoint: POST /v1/graphql（Aggregate { groupBy: ["cat","intVal"] }）
- Param: graphql.Aggregate.groupBy
- Novelty: NOVEL (gate, LOW precision, no_known_hits)
- Discovered: 2026-08-21

## Description
GraphQL Aggregate 多属性 groupBy（数组两个元素）不被支持可以接受，但报错是 `could not extract groupBy path: missing an argument after 'intVal'`——把列表第二元素误判为残缺 filter path，用户会去检查不存在的"语法缺失"。根因：groupBy 复用为 where-filter 跨类引用路径设计的 path 解析器。对照 T1-T4（单属性 groupBy、全局统计、分组均值/计数）数学全部正确。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Aggregate { SemAgg06(groupBy: [\"cat\",\"intVal\"]) { groupedBy { value } } } }"}'
# 实际: 200 + errors[]: "could not extract groupBy path: missing an argument after 'intVal'"
# 期望: 错误指出真实原因——多属性 groupBy 不支持/仅支持单路径
```

## Expected vs Actual
- Expected: errors[] 明示"多属性 groupBy 不支持"
- Actual: errors[] 报 "missing an argument after 'intVal'"（filter-path 语义错位）

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `scripts/semantic_aggregate_math_06.py`
- Log: `output_semantic_aggregate_math_06.log`
- 源码: `adapters/handlers/graphql/local/aggregate/resolver.go` L96-99 → `entities/filters/path.go` L114-118（错误产地：按 (class, prop) 步长 2 消费，奇数剩余触发 "missing an argument"）
- Ring 1 (Contract Clause 契约条款): 无 groupBy 语义断言（弱锚）；Type2 主张由行为自证
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（domain_blocked，groupBy 语义无文档）
- source_grounding: by_design_in_source（复用解析器为设计，但诊断错位是缺陷）
- Evidence chain: `evidence_chain/semantic_aggregate_math_06.json`

## Impact
错误消息把用户引向完全不存在的语法问题；多属性分组分析需求无法实现且无法从报错推断原因。
