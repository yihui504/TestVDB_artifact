# Defect 2: 空串 distance 绕过 5 值枚举，静默默认 cosine

## Metadata
- Defect ID: TESTVDB-WEAVIATE-002 (boundary_schema_distance_empty_009)
- Type: Type1_IllegalSuccess
- Severity: Medium
- Endpoint: POST /v1/schema
- Param: vectorIndexConfig.distance
- Novelty: NOVEL (gate, HIGH confidence, no_known_hits) — 对应官方 open issue #11732（注意：GT issue 描述 null 静默默认；本链攻击值为空串 "" 持久化。null 语义链 distance_null_semantics 被 auditor 判 NOT_DEFECT by-design，pending 人工盲评双确认）
- Discovered: 2026-08-21

## Description
`distance` 在 OpenAPI spec (v1.38.0) 中为 5 值枚举（cosine, l2-squared, dot, manhattan, hamming）。发送 `distance=""` 返回 HTTP 200，集合以默认 `cosine` 创建，空串被静默吞掉。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"Def2DistEmpty","vectorIndexConfig":{"distance":""}}'
# 实际: HTTP 200, readback distance='cosine'
# 期望: HTTP 422, 枚举违反
```

## Expected vs Actual
- Expected: 422 拒绝（空串非枚举成员）
- Actual: 200 成功，默认 cosine 应用

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `boundary_scripts/boundary_schema_distance_empty_009.py`
- Log: `output_boundary_schema_distance_empty_009.log`
- 源码: `entities/vectorindex/common/config.go` L31 `DefaultDistanceMetric = DistanceCosine` — 空串被当作"未指定"触发默认；schema 创建路径无 distance 枚举校验
- Ring 1 (Contract Clause 契约条款) constraint_id: constraint `vectorIndexConfig.distance` 5 值枚举断言
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（全 PASS）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/boundary_schema_distance_empty_009.json`

## Impact
距离度量决定向量检索的数学语义；静默替换为 cosine 使用户在 dot/l2 场景下得到系统性错误的相似度排序，且无任何警告。
