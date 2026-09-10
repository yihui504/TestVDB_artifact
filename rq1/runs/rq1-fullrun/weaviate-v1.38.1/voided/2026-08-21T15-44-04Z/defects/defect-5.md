# Defect 5: flatSearchCutoff=-1/10^10 verbatim 200；字符串 '100' 静默归 0

## Metadata
- defect_id: boundary_flatSearchCutoff_005
- type: Type1_IllegalSuccess
- param: vectorIndexConfig.flatSearchCutoff
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A/B/C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndFlatCut","vectorizer":"none","vectorIndexType":"hnsw","vectorIndexConfig":{"flatSearchCutoff":-1}}'
# -> HTTP 200；readback persisted=-1（verbatim）
# huge: flatSearchCutoff=10000000000 -> 200 persisted=10000000000
# str:  flatSearchCutoff="100"       -> 200 persisted=0（字符串被静默丢弃归 0，非 4xx）
# 对照: flatSearchCutoff=40000 -> 200 persisted=40000（正常）
```

## Expected vs Actual
- Expected: -1（值域违规）与字符串 "100"（type=integer 违规）应 4xx。
- Actual: 负值/巨值 verbatim 200 持久化；字符串类型错配静默变换为 0 而非拒绝。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_create_collection_003（assertion: `flatSearchCutoff is integer`）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（source_url=entities/vectorindex/hnsw/config.go，本地核对：类型由 OptionalIntFromMap 保证，但值域无校验）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_flatSearchCutoff_005.py
- Log: debate_logs/output_boundary_flatSearchCutoff_005.log（5 组变体确定性）
- 源码 文件:行号+摘录: entities/vectorindex/hnsw/config.go L201-205 `OptionalIntFromMap(asMap, "flatSearchCutoff", ...)` 赋值后 validate() L260-323 无 FlatSearchCutoff 检查（L34 默认 40000）；entities/vectorindex/common/config.go L45-73 `OptionalIntFromMap` 的 type switch 仅处理 json.Number/float64，字符串不命中 case 且无 default 报错 → setFn 不调用 → 静默丢弃。

## Impact
cutoff=-1 会使 flat 搜索短路逻辑进入未定义区间；字符串输入被静默归 0（关闭 flat 搜索）而非报错，用户意图无声丢失。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
