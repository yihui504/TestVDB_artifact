# Defect 12: 不存在分片 + 非法状态 PUT 200 逐字回显请求体（双缺陷点）

## Metadata
- defect_id: vein_shard_status_echo_2
- type: Type1_IllegalSuccess
- param: status
- novelty: NOVEL
- Endpoint: PUT /schema/{className}/shards/{shardName}
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE LLM 兜底 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
# 不存在的分片 + 非法状态
curl -s -X PUT "http://localhost:8080/v1/schema/VeinShard/shards/BOGUS_SHARD" \
  -H "Content-Type: application/json" \
  -d '{"status":"NOT_A_STATUS"}'
# -> HTTP 200；body={"status": "NOT_A_STATUS"}（请求体逐字回显，无任何处理痕迹）
# 对照：真分片 + 同一非法状态
#   -> 422 {"error":[{"message":"updating db: TYPE_UPDATE_SHARD_STATUS: NOT_A_STATUS: invalid storage status"}]}
```

## Expected vs Actual
- Expected: 不存在的分片应 404；非法状态（非 READY/READONLY）应 422（对照组证明 422 机制存在且可达）。
- Actual: 双重失败（bogus shard + bogus status）反而短路成 200，响应体逐字回显请求——运维操作被虚假确认。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（vein_failure_path_state；实际引用 openapi PUT /schema/{className}/shards/{shardName} 状态枚举语义：openapi-specs/schema.json:8941-8943 "Update a shard status ... sets it to `READY` or `READONLY`"）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link/version/content/endpoint 全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_shard_status_echo_2.py
- Log: vein_scripts/output_vein_shard_status_echo_2.log（attack 200 回显；control 真分片 422）
- 源码 文件:行号+摘录: adapters/repos/db/index.go:3539-3551 `Index.updateShardStatus()`: `if !isOwner { return nil }`——不存在的分片静默成功（无 404 无状态校验）；仅真分片走到 `shard.UpdateStatus(...)` 枚举校验 → 422。adapters/handlers/rest/handlers_schema.go:431-452 handler 成功路径 `payload := params.Body; return schema.NewSchemaObjectsShardsUpdateOK().WithPayload(payload)`——直接把请求体原样回显。双缺陷点逐行定位。

## Impact
运维在集群维护（如备份前设 READONLY）时对错误分片名操作会得到成功确认，实际什么都没发生——数据一致性操作被静默跳过，是运维事故级缺陷。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true; precision LOW)
