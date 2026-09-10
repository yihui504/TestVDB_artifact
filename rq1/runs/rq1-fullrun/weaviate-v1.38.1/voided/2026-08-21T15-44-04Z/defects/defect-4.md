# Defect 4: dynamicEfMin=500 x dynamicEfMax=100 跨字段配对违规 verbatim 持久化（vein 交叉验证）

## Metadata
- defect_id: vein_hnsw_dynamic_ef_cross_1
- type: Type1_IllegalSuccess
- param: vectorIndexConfig.dynamicEfMin x vectorIndexConfig.dynamicEfMax
- novelty: NOVEL
- Endpoint: POST /schema (vectorIndexConfig.dynamicEfMin x dynamicEfMax)
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE 兜底, B/C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"VeinEfCross","vectorizer":"none","vectorIndexType":"hnsw","vectorIndexConfig":{"dynamicEfMin":500,"dynamicEfMax":100}}'
# -> HTTP 200；readback stored min=500 max=100
# 对照：efConstruction=1 -> 422 "invalid hnsw"
# 对照：maxConnections=1 -> 422 "invalid hnsw"
```

## Expected vs Actual
- Expected: stored min(500) > max(100) 违反 `dynamicEfMin <= dynamicEfMax` 应被 422 拒绝；同一 validate() 管辖的 efConstruction/maxConnections 单字段非法值正确 422。
- Actual: 200 接受且 verbatim 持久化——选择性缺校验。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_range_create_collection_001（assertion: `dynamicEfMin <= dynamicEfMax`，evidence_tier: inferred，source_url: go-struct entities/vectorindex/hnsw/config.go）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link_reachability/version_match/content_consistency/endpoint_precision 全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_hnsw_dynamic_ef_cross_1.py
- Log: vein_scripts/output_vein_hnsw_dynamic_ef_cross_1.log（attack: status=200 stored min=500 max=100；controls 422）
- 源码 文件:行号+摘录: entities/vectorindex/hnsw/config.go:260-289 `UserConfig.validate()` 四项校验（MaxConnections/EFConstruction/FilterStrategy×2）中无任何 DynamicEFMin/DynamicEFMax/DynamicEFFactor 检查（字段定义 :54-56，默认 :91-92）；跨字段 min<=max 校验在文件中零出现。

## Impact
与 defect-3 同根因的独立脚本交叉证实：HNSW 动态搜索宽度以 min>max 的矛盾状态持久化，搜索语义未定义；用户无从得知配置无效。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true; precision LOW)
