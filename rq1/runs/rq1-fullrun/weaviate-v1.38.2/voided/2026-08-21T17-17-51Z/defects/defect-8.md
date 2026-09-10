# Defect 8: POST /schema desiredCount=-1 被接受（0 值被 422 拒绝）——同类非法值一拒一收

## Metadata
- Defect ID: TESTVDB-WEAVIATE-8
- defect_id: boundary_bd_shardcount_03
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Param: shardingConfig.desiredCount
- Endpoint: POST /schema
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" -H "Content-Type: application/json" \
  -d '{"class":"BdShardCtl","shardingConfig":{"desiredCount":-1}}'
# → HTTP 200（read-back desiredCount = None）
# 对照 desiredCount=0: 422 "...invalid sharding state: physical shards unavailable"
# 对照 desiredCount=1: 200 正常
```

## Expected vs Actual
- Expected: 契约断言 "shardingConfig.desiredCount >= 1"（shard count must be a positive integer；GT issue #11729 通道）。
- Actual: -1 被创建 200 接受；0 值被运行时 422 拒绝（但报错为存储层错误而非参数校验）——同为非法值，-1 过 0 拒，行为不一致。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_range_sharding_desired_count_001（evidence_tier=inferred, source_verified=true；机械B 数值下界 CONFIRMED）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — api_endpoints shardingConfig.desiredCount integer（go-struct: usecases/sharding/config/config.go#L22，clone 可达并核验）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/boundary_bd_shardcount_03.py
- Log: debate_logs/output_boundary_bd_shardcount_03.log（log_pattern: "desiredCount=-1: create -> 200 / read-back desiredCount = None"，grade B，多脚本稳定触发）
- 源码 usecases/sharding/config/config.go L46-71：validate() 仅校验 key=="_id"/strategy=="hash"/function=="murmur3"，无任何 DesiredCount 正整数校验；0 的 422 来自下游索引创建（存储层），-1 因负值循环不执行未触发同样拒绝 → 200。

## Impact
负 shard 计数被静默接受，read-back desiredCount=None（见 Defect 9 状态不一致叠加）；用户配置错误零反馈，集群分片拓扑进入未定义状态。
