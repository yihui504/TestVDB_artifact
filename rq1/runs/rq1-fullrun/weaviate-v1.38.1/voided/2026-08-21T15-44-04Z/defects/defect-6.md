# Defect 6: replicationFactor 文档键任意值 200 静默丢生 factor=1；别名键 factor=3 却 422

## Metadata
- defect_id: boundary_replicationFactor_003
- type: Type1_IllegalSuccess
- param: replicationConfig.replicationFactor
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A/B/C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndRep","vectorizer":"none","replicationConfig":{"replicationFactor":3}}'
# -> HTTP 200；readback persisted_factor=1（3 被静默丢弃）
# 同样 200+factor=1：replicationFactor=-1 / 1.5 / "3" / 16384 / null
# 对照：replicationConfig={"factor":3} -> 422
#   "init sharding state: could not find enough weaviate nodes for replication: 1 availa..."
```

## Expected vs Actual
- Expected: 文档键 replicationFactor 应受类型校验（integer）；非法类型/非法值应 4xx。
- Actual: 该键任意值（float/str/负数/巨值/null）全部 200 且不生效（factor=1）；同域别名键 factor=3 走节点数校验 422——同域两键校验不对称。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_create_collection_004（assertion: `replicationFactor is integer`）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（REST 模型 entities/models/replication_config.go 仅定义 json:"factor"；json:"replicationFactor" 仅存在于内部 usecases/sharding/state.go——文档键与 REST 模型键不一致，键名混淆被如实记录）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_replicationFactor_003.py
- Log: debate_logs/output_boundary_replicationFactor_003.log（7 变体全 silent-drop，确定性）
- 源码 文件:行号+摘录: entities/models/replication_config.go L35-38 `Factor int64 \`json:"factor,omitempty"\``；usecases/sharding/state.go L40 `ReplicationFactor int64 \`json:"replicationFactor"\``（仅内部 state）、L292 "could not find enough weaviate nodes for replication" 校验。go-swagger 模型反序列化无 additionalProperties:false 拒绝 → 未知键 replicationFactor 静默丢弃 → factor 保持默认 1。

## Impact
按文档写 replicationFactor 的用户会静默失去复制意图（单副本运行而无任何告警），高可用假设失效；副本数意图丢失在生产环境是数据耐久性风险。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
