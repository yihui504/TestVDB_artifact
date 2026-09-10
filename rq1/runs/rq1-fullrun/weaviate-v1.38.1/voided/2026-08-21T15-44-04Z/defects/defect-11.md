# Defect 11: 非法 distance 度量静默归一 cosine；合法值 dot 也被替换

## Metadata
- defect_id: boundary_distance_metric_enum_008
- type: Type1_IllegalSuccess
- param: vectorIndexConfig.distance.name
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE LLM 兜底 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndDist","vectorizer":"none","vectorIndexType":"hnsw","vectorIndexConfig":{"distance":{"name":"invalid"}}}'
# -> HTTP 200；readback persisted_distance='cosine'（非法枚举静默归一）
# distance.name="" -> 200 persisted='cosine'
# distance.name="dot" -> 200 persisted='cosine'（合法值 dot 也被替换为 cosine！）
# 对照：vectorIndexType='invalid' -> 422 "unrecognized or unsupported vectorIndexType"
#       vectorIndexType='HNSW' -> 422（枚举拒绝机制存在且生效）
```

## Expected vs Actual
- Expected: distance ∈ {cosine, dot, l2-squared, manhattan, hamming}（shard_init_vector.go L75 'choose one of [...]'）；非法值应 422（vectorIndexType 对照证明拒绝机制存在）。
- Actual: 非法枚举 200 静默归一 cosine；合法值 dot 被静默替换为 cosine——用户指定的相似度度量被静默改变。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（枚举：entities/vectorindex/common/config.go L22-27 Distance 常量集 + shard_init_vector.go 错误文案）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（源码锚本地核对；校验时序错位——唯一校验点在 shard init，但持久化层已先归一 cosine）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_distance_metric_enum_008.py
- Log: debate_logs/output_boundary_distance_metric_enum_008.log（5 变体确定性，含合法值被替换的强观测）
- 源码 文件:行号+摘录: entities/vectorindex/common/config.go L95-107 `OptionalStringFromMap`: `asString, ok := value.(string); if !ok { return nil }`——非字符串（如嵌套 map {name:...}）静默返回不报错；hnsw/config.go L213-217 distance 赋值后 validate() 无枚举检查（L96 默认 DefaultDistanceMetric=cosine）；shard_init_vector.go L61-77 switch 的 "" case 显式映射 cosine，无效值在到达 default 分支前已被归一持久化。

## Impact
数据正确性面：指定 dot 的集合实际按 cosine 计算/存储相似度，检索结果系统性偏差且无任何告警；嵌套对象结构（distance:{name:...}）被静默丢弃加剧混淆。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
