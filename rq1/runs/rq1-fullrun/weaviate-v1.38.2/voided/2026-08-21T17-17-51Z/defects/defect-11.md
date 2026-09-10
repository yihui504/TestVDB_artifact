# Defect 11: POST /schema desiredCount=-1/-5 返回 200 空体但 GET schema 404——幻影成功（状态不一致）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-11
- defect_id: semantic_shardcount_02
- Type: Type4_StateLogicViolation
- Severity: Low（Type4 推断；叠加数值下界违例）
- Param: shardingConfig.desiredCount
- Endpoint: POST /schema
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" -H "Content-Type: application/json" \
  -d '{"class":"X","shardingConfig":{"desiredCount":-1}}'
# → HTTP 200（空体）
curl -s "http://localhost:8080/v1/schema/X"
# → HTTP 404（集合不存在）
# desiredCount=-5 同样复现；对照 desiredCount=0: 422 "physical shards unavailable"
```

## Expected vs Actual
- Expected: desiredCount >= 1（weaviate_range_sharding_desired_count_001）；state invariant weaviate_state_collection_creation_001："Collection exists in GET /schema response after POST /schema"。
- Actual: -1/-5 create 返回 200 空体，随后 GET /schema/{name} 404——POST 200 与状态未落地并存（幻影成功），-5 复现排除最终一致性窗口（cache_delay 已排除：创建后即时 GET，404 永久不可见）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_range_sharding_desired_count_001 + weaviate_state_collection_creation_001（辅）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — api_endpoints shardingConfig.desiredCount integer（config.go#L22）；state invariant source 为 openapi schema.json（契约 source 列表，核验端点存在）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/semantic_shardcount_02.py
- Log: debate_logs/output_semantic_shardcount_02.log（log_pattern: "[desiredCount=-1] create status=200 body= / GET schema status=404"，grade B，多脚本稳定触发）
- 源码 usecases/sharding/config/config.go L59-71：validate() 无 DesiredCount 下界校验 → 下游分片创建对负数静默不产生物理分片但整个 add-class 未回滚/未报错 → 200；schema 状态未写入 → 后续 GET 404。

## Impact
比单纯 200 接受更严重：客户端认定创建成功（200）但集合永久不存在，后续写入全部 404，错误延迟暴露且根因难定位；2xx+状态不一致违反 POST /schema 状态不变量。
