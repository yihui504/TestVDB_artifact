# Defect 3: dynamicEfMin=200/dynamicEfMax=100 逆序配对 verbatim 持久化（无校验）

## Metadata
- defect_id: boundary_hnsw_dynamicEfMin_004
- type: Type1_IllegalSuccess
- param: vectorIndexConfig.dynamicEfMin
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A/B/C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndEfMin","vectorizer":"none","vectorIndexType":"hnsw","vectorIndexConfig":{"dynamicEfMin":200,"dynamicEfMax":100}}'
# -> HTTP 200；readback 持久化 min=200 max=100（verbatim 逆序）
# 对照：vectorIndexConfig={"maxConnections":-1,"EF":64} -> 422 "invalid hnsw conf"
#       （证明同一 validate() 通道存在且对 maxConnections 生效）
```

## Expected vs Actual
- Expected: 违反 `dynamicEfMin <= dynamicEfMax` 配对约束应 422；负值（min=-10 / max=-5）同理。
- Actual: swap/minneg/maxneg/bothzero 全部 200 且 verbatim 持久化；同 validate() 管辖的 maxConnections 却正确 422——校验选择性缺失。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_range_create_collection_001（assertion: `dynamicEfMin <= dynamicEfMax`，evidence_tier: inferred）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（source_url=go-struct entities/vectorindex/hnsw/config.go，本地 clone 核对：该配对约束在 validate() 中确实不存在——契约描述应有行为，源码缺失即缺陷面）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_hnsw_dynamicEfMin_004.py
- Log: debate_logs/output_boundary_hnsw_dynamicEfMin_004.log（6 组 vic 变体：swap/minneg/maxneg/bothzero 全 200；mc_neg 对照 422）
- 源码 文件:行号+摘录: entities/vectorindex/hnsw/config.go L189-193 `OptionalIntFromMap(asMap, "dynamicEfMin", ...)` 赋值；L260-285 `validate()` 仅校验 MaxConnections(L262-274)/EFConstruction(L276-281)/FilterStrategy(L283-285)——DynamicEFMin/DynamicEFMax/EF/FlatSearchCutoff 零校验。L30-31 默认 100/500。

## Impact
HNSW 搜索宽度参数以非法状态（min>max、负值、全 0）持久化，运行时搜索行为未定义；用户配置被静默接受为坏配置，性能回退难以归因。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
