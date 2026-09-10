# Defect 5: text[] 上 Equal+valueString 静默返回空集无 errors

## Metadata
- Defect ID: TESTVDB-WEAVIATE-005 (semantic_graphql_diag_03)
- Type: Type2_PoorDiagnostics
- Severity: Low
- Endpoint: POST /v1/graphql（where filter on text[] property）
- Param: graphql.query.errors
- Novelty: NOVEL (gate, LOW precision, no_known_hits)
- Discovered: 2026-08-21

## Description
在 `text[]` 数组属性上使用 `operator: Equal` + `valueString: "x"`（非数组操作符）时，返回 200 + 空 data + 无 errors——静默通过。对照实验 8 例中 7 例（不存在属性/坏操作符/类型混淆/值类型错/语法错）均正确报错，唯 array-prop 案静默，同函数内严格性不一致。历史文档规定数组属性须用 ContainsAny/ContainsAll/ContainsNone + valueText[]。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Get { SemGqlDiag03(where: {path: [\"tags\"], operator: Equal, valueString: \"x\"}) { id } } }"}'
# 实际: 200 {"data":{"Get":{"SemGqlDiag03":[]}}} 无 errors
# 期望: 200 + errors[]（operator 数组性违反，应提示用 ContainsAny 等）
```

## Expected vs Actual
- Expected: errors[] 指出 Equal 不能用于 text[]，应使用 ContainsAny/ContainsAll
- Actual: 静默空结果集

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `scripts/semantic_graphql_diag_03.py`
- Log: `output_semantic_graphql_diag_03.log`
- 源码: `entities/filters/filters_validator.go` L162-174 — 数组基类型检查只验 value 类型不验 operator 数组性；string 是 text 别名使 valueString 通过
- Ring 1 (Contract Clause 契约条款): 脚本引用的 weaviate_behavioral_graphql_query_001 不存在（contract 环断链，行为自证）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（domain_blocked）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/semantic_graphql_diag_03.json`

## Impact
用户查询静默返回空集，无法区分"无匹配数据"与"查询非法"——数组分词过滤场景下产生系统性假阴性。
