# Defect 10: nearVector certainty/distance 越域值（1.5/-0.5/-2.0/5.0）全 200 静默

## Metadata
- defect_id: boundary_nearVector_certainty_010
- type: Type1_IllegalSuccess
- param: nearVector.certainty
- novelty: NOVEL
- Endpoint: POST /v1/graphql
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE 机械 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Get { BndCert(nearVector: {vector: [0.1,0.2], certainty: 1.5}) { txt } }"}'
# -> HTTP 200 rows=0（certainty 1.5 超域，过滤被静默收紧→零结果）
# certainty: -0.5 -> 200 rows=3（负 certainty 等价无过滤，返回全部）
# distance: -2.0 -> 200 rows=0；distance: 5.0 -> 200 rows=3（cosine distance 域 [0,2]，5.0 超域仍全量）
# 对照：certainty: 0.0 -> 200 rows=3（正常）
```

## Expected vs Actual
- Expected: certainty ∈ [0,1]（源码自证：REST 侧 `validateCertaintyOrWeight` 返回 "must be between 0 and 1"）；越域应报错。
- Actual: 四个越界值全部 200 静默接受，无 errors 字段；过滤条件被静默放松（全量）或收紧（零结果）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（族级：traverser_schema_search_params.go L62-68 'must be between 0 and 1'）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（源码锚本地核对；certainty 值域无专属 constraint）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_nearVector_certainty_010.py
- Log: debate_logs/output_boundary_nearVector_certainty_010.log（5 变体确定性）
- 源码 文件:行号+摘录: usecases/traverser/traverser_schema_search_params.go L62-68 `validateCertaintyOrWeight` 仅在 REST 端 SearchParams.Validate (L50) 调用；GraphQL 路径 adapters/handlers/graphql/local/common_filters/near_vector.go L33-42 `certainty, certaintyOK := source["certainty"]; if certaintyOK { args.Certainty = certainty.(float64) }`——裸类型断言赋值，无 [0,1] 检查；仅 L44 检查 certainty/distance 互斥。现成校验函数未挂 GraphQL 路径。

## Impact
查询结果静默错误：certainty=-0.5 变全量扫描（失去相似度过滤），certainty=1.5 返回空集（用户误以为无匹配）；同仓 REST 路径有现成校验未复用，校验不对称。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
