# Defect 7: dynamicEfMin=500 > dynamicEfMax=100 被 200 接受并 verbatim 持久化

## Metadata
- Defect ID: TESTVDB-WEAVIATE-007 (vein_dynamic_ef_minmax_1)
- Type: Type1_IllegalSuccess
- Severity: Medium
- Endpoint: POST/PUT /v1/schema (vectorIndexConfig)
- Param: vectorIndexConfig.dynamicEfMin
- Novelty: NOVEL (gate, LOW precision, no_known_hits)
- Discovered: 2026-08-21

## Description
hnsw 配置约束 `dynamicEfMin <= dynamicEfMax`（契约 weaviate_range_create_collection_001，源自 go 源码字段配对）无服务端校验：POST 接受 inverted (500,100)，PUT 亦接受 (9999,1)，负值 (-100,-50) 也持久化。control (50,500) verbatim 存储证明无任何方向的规范化。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"Def7Ef","vectorIndexConfig":{"ef":128,"dynamicEfMin":500,"dynamicEfMax":100}}'
# 实际: HTTP 200, readback dynamicEfMin=500 > dynamicEfMax=100
# 期望: HTTP 422 invalid hnsw config
```

## Expected vs Actual
- Expected: 422（Min<=Max 不变式违反）
- Actual: 200 接受，值逐字持久化

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `vein_scripts/vein_dynamic_ef_minmax_1.py`
- Log: `output_vein_dynamic_ef_minmax_1.log`
- 源码: `entities/vectorindex/hnsw/config.go` L189-193（OptionalIntFromMap 无界写入）；L260-281 validate() 仅校验 maxConnections/efConstruction/filterStrategy——DynamicEFMin/Max 零交叉校验（全库 grep 零命中）
- Ring 1 (Contract Clause 契约条款): weaviate_range_create_collection_001 'dynamicEfMin <= dynamicEfMax'
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（全 PASS，本地源码核实）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/vein_dynamic_ef_minmax_1.json`

## Impact
Min>Max 使动态 ef 扩展逻辑处于未定义状态，检索 recall/延迟行为不可预测；负值同族被接受（见 defect-8），根因同一 validate() 封闭校验集合缺口。
