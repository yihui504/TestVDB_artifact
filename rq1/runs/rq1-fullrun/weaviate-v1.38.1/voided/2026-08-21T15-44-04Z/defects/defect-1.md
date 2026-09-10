# Defect 1: shardingConfig.desiredCount 负值被 200 接受（phantom 成功，readback None）

## Metadata
- defect_id: boundary_sharding_desiredCount_001
- type: Type1_IllegalSuccess
- param: shardingConfig.desiredCount
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A/B/C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndShardNeg","vectorizer":"none","shardingConfig":{"desiredCount":-1}}'
# -> HTTP 200；随后 GET /v1/schema/BndShardNeg 返回 None（phantom）
# 对照：desiredCount=0 -> 422 "invalid sharding state: physical shards unavailable"
# 对照：desiredCount=1.5 -> 422 "parse sharding config: desiredCount: strconv.ParseInt ... invalid syntax"
# 对照：desiredCount=1 -> 200 readback=1（正常）
```

## Expected vs Actual
- Expected: desiredCount=-1（违反 desiredCount >= 1）应返回 4xx；0/1.5 均正确 422 证明错误通道存在。
- Actual: -1 与 -100 均返回 200，但 schema readback 为 None——索引未真正建立，客户端收到假成功。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_range_sharding_desired_count_001（assertion: `shardingConfig.desiredCount >= 1`）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（source_url 为 go-func 引用 usecases/sharding/config/config.go validate()，非 http URL，无法 WebFetch 验证；本地 clone 已核对）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_sharding_desiredCount_001.py
- Log: debate_logs/output_boundary_sharding_desiredCount_001.log（log_pattern: `[neg] desiredCount=-1 -> create=200 readback=None`）
- 源码 文件:行号+摘录: usecases/sharding/config/config.go L53-70 `validate()` 仅校验 Key=='_id' / Strategy=='hash' / Function=='murmur3'，对 DesiredCount 无任何 >=1 或上限校验；L104-108 `optionalIntFromMap(asMap, "desiredCount", ...)` 直接赋值。负值绕过 cluster/schema/reader.go L106 的 "physical shards unavailable" 检查（该检查仅 0/正数不足时触发）→ 200 phantom。

## Impact
客户端以为分片配置成功，实际集合未正确建立（readback None），后续写入/查询将失败或行为未定义；错误通道选择不一致（0/1.5 得 422，-1/-100 得 200）增加排障成本。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
