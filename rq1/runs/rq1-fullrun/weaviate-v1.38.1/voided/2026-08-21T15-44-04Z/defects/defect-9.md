# Defect 9: EF=-1/0/10^9 全 200 无校验；合法值 64（大写键）也被静默丢弃

## Metadata
- defect_id: boundary_hnsw_EF_006
- type: Type1_IllegalSuccess
- param: vectorIndexConfig.EF
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE 机械 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndEf","vectorizer":"none","vectorIndexType":"hnsw","vectorIndexConfig":{"EF":-1}}'
# -> HTTP 200；readback persisted_ef=-1
# EF=0 / EF=1000000000 -> 同样 200 无 4xx
# 关键对照：EF=64（合法值）-> 200 persisted_ef=-1（大写键不匹配被静默丢弃！）
```

## Expected vs Actual
- Expected: EF 负值/0/巨值应经校验拒绝（同 validate() 对 maxConnections/efConstruction 均 422）。
- Actual: 非法值全部 200；更严重的是合法值 64 因大写键 'EF' 不匹配小写 json tag "ef" 也被静默丢弃——用户意图全面丢失，校验缺席为主观测。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（weaviate_type_create_collection_001 同族 hnsw UserConfig 类型约束；EF 无专属 constraint）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（source_url=entities/vectorindex/hnsw/config.go，本地核对 EF 无校验且大写键不在键列表）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_hnsw_EF_006.py
- Log: debate_logs/output_boundary_hnsw_EF_006.log（4 组值全部一致：200 + persisted_ef=-1）
- 源码 文件:行号+摘录: entities/vectorindex/hnsw/config.go L171-175 `OptionalIntFromMap(asMap, "ef", func(v int){ uc.EF = v })`（只查小写 "ef"）；L29 `DefaultEF = -1 // indicates "let Weaviate pick"`；L53 `EF int \`json:"ef"\``；validate() L260-323 对 EF 无任何校验。大写 'EF' 键不匹配 → 输入被丢弃 → 恒持久化默认 -1。

## Impact
按文档常见写法传大写 EF 的用户其搜索宽度配置被完全忽略（退回 "let Weaviate pick"）；小写路径的非法值（-1/0/10^9）同样无校验接受，性能调优静默失效。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
