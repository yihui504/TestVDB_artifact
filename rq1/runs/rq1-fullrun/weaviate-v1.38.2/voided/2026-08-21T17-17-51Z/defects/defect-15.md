# Defect 15: PUT /schema/{class}/shards/{shard} 不存在的 shard 返回 200 回显请求体（幻影 no-op 成功）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-15
- defect_id: vein_shardstatus_phantom_03
- Type: Type4_StateLogicViolation
- Severity: Low（Type4 推断）
- Param: shardName
- Endpoint: PUT /v1/schema/{className}/shards/{shardName}
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X PUT "http://localhost:8080/v1/schema/{class}/shards/PhantomShard" \
  -H "Content-Type: application/json" -d '{"status":"READONLY"}'
# → HTTP 200 {"status":"READONLY"}（回显请求体）
# 随后核验真实 shard 状态: 仍 READY（未变）
# control 非法 status: 500; control 类不存在: 500 "cannot update shard status to a non-exi..."
```

## Expected vs Actual
- Expected: 对不存在资源（shard）的写操作应返回 4xx 错误，不得返回 200 成功（REST PUT 语义）。
- Actual: 拼错的 shard 名 → 200 + 回显请求体；真实 shard 状态未变（READY）。类不存在与非法 status 均报错——三种输入错误仅 shard 存在性被静默吞掉。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: vein_phantom_resource_silent_ok（vein 探索性约束——"对不存在资源的写操作应 4xx"；机械B 类型恒真 CONFIRMED）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — REST PUT 语义：更新不存在资源应报错；endpoint_registry 含该端点
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_shardstatus_phantom_03.py
- Log: debate_logs/output_vein_shardstatus_phantom_03.log（log_pattern: "phantom shard update: 200 {\"status\":\"READONLY\"}"，grade B）
- 源码 adapters/repos/db/index.go L3539-3551：
  ```go
  func (i *Index) updateShardStatus(ctx context.Context, shardName, targetStatus string) error {
    isOwner := false
    if err := i.schemaReader.Read(..., func(_ *models.Class, state *sharding.State) error {
      if state != nil { isOwner = state.IsLocalShard(shardName) }
      return nil
    }); err != nil { return err }
    if !isOwner { return nil }   // ← 幻影 shard：非本节点 shard 直接返回 nil（成功）
  ```
  handlers_schema.go L435-453: err==nil 即 NewSchemaObjectsShardsUpdateOK().WithPayload(params.Body)（回显请求体）。单节点部署下 IsLocalShard 对任意幻影名恒 false → 恒 200 no-op。

## Impact
运维入口对拼错 shard 名返回虚假成功（回显体更具误导性）：操作者以为已切 READONLY/SHUTDOWN 完成维护，实际状态未变——维护窗口误判风险。多节点 by_design 疑点已记录（!isOwner-静默可能为 cluster 委托设计），建议主进程人工复核多节点语义；单节点回显误导性行为独立成立。
