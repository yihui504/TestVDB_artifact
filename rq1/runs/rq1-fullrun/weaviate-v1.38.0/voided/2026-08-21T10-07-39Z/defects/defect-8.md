# Defect 8: flatSearchCutoff=-50000 负值被 200 持久化

## Metadata
- Defect ID: TESTVDB-WEAVIATE-008 (vein_flat_search_cutoff_2)
- Type: Type1_IllegalSuccess
- Severity: Medium
- Endpoint: POST /v1/schema (vectorIndexConfig.flatSearchCutoff)
- Param: vectorIndexConfig.flatSearchCutoff
- Novelty: NOVEL (gate, LOW precision, no_known_hits)
- Discovered: 2026-08-21

## Description
`flatSearchCutoff` 是"段内对象数阈值"（默认 40000，隐含非负域）。负值 -50000 以 200 接受并持久化，使阈值比较语义退化（任何段大小都大于负阈值——flat/HNSW 搜索分支选择被破坏性偏置）。control：默认 40000 未被触碰，排除 readback 伪影。另观测 ef=10 < dynamicEfMin=500 亦无交叉校验。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"Def8Cutoff","vectorIndexConfig":{"flatSearchCutoff":-50000}}'
# 实际: HTTP 200, readback flatSearchCutoff=-50000
# 期望: HTTP 422（非负域违反）
```

## Expected vs Actual
- Expected: 422 拒绝负值
- Actual: 200 持久化

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `vein_scripts/vein_flat_search_cutoff_2.py`
- Log: `output_vein_flat_search_cutoff_2.log`
- 源码: `entities/vectorindex/hnsw/config.go` L201-205（OptionalIntFromMap 直写）；L34 `DefaultFlatSearchCutoff = 40000`；validate() L260-323 无 FlatSearchCutoff 条目（全库 grep 仅定义/默认/解析/序列化）
- Ring 1 (Contract Clause 契约条款): 无专属 constraint（同族 weaviate_range_create_collection_001 仅覆盖 dynamicEf；violates 基于语义域，权重低于 defect-7）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link/version PASS, content PARTIAL）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/vein_flat_search_cutoff_2.json`

## Impact
负 cutoff 破坏 flat-search 降级机制的方向性，检索策略选择静默异常；与 defect-7 同根因（validate() 封闭集合缺失），一条修复可同时覆盖。
