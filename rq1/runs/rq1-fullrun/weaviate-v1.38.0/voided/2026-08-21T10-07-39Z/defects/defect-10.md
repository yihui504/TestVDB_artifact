# Defect 10: asyncEnabled=true 被 200 接受后读回 false——输入静默丢弃

## Metadata
- Defect ID: TESTVDB-WEAVIATE-010 (vein_replication_async_silent_flip_3)
- Type: Type2_PoorDiagnostics（语义级静默改写；severity Low）
- Severity: Low
- Endpoint: POST/GET /v1/schema (replicationConfig.asyncEnabled)
- Param: replicationConfig.asyncEnabled
- Novelty: NOVEL (gate, LOW precision, no_known_hits)
- Discovered: 2026-08-21

## Description
POST /schema 带 `replicationConfig: {factor:1, asyncEnabled:true}` 返回 200，但 GET 读回 `asyncEnabled: false`——输入被服务端单方面改写且无错误/警告。根因精确：`models.ReplicationConfig` 请求模型本身无 AsyncEnabled 字段（body 解析层即丢弃），而响应的 AsyncEnabled 是包装器派生值 `factor > 1 && !asyncReplicationGloballyDisabled`。control（显式 false 读回 false）证明 flip 是输入依赖而非序列化默认。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"Def10Async","replicationConfig":{"factor":1,"asyncEnabled":true}}'
# → HTTP 200
curl -s "http://localhost:8080/v1/schema/Def10Async"
# 实际: replicationConfig={'factor':1,'asyncEnabled':false}
# 期望: 422 拒绝 asyncEnabled（factor=1 时无意义），或读回如实反映/警告
```

## Expected vs Actual
- Expected: 拒绝或告知（async 复制在 factor=1 时物理无意义，静默改写有工程理由——by-design 抗辩并存，归 auditor 裁量为 DEFECT）
- Actual: 200 接受 + 读回 false，零反馈

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `vein_scripts/vein_replication_async_silent_flip_3.py`
- Log: `output_vein_replication_async_silent_flip_3.log`
- 源码: `adapters/handlers/rest/restcompat/wrappers.go` L34-42 `wrapReplicationConfig()` — `AsyncEnabled: rc.Factor > 1 && !asyncReplicationGloballyDisabled.Load()`；`flag.go` L19-26 镜像 ASYNC_REPLICATION_DISABLED 环境变量；全库 grep AsyncEnabled 仅此两处+输出（输入侧模型无字段）
- Ring 1 (Contract Clause 契约条款): 无专属 constraint；读回一致性由 state_invariants 精神覆盖（doc/contract 双弱，behavior+source 强替代锚）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（domain_blocked，raw_knowledge 零命中）
- source_grounding: by_design_in_source（显式派生公式，但接受即丢弃不告知构成语义漂移）
- Evidence chain: `evidence_chain/vein_replication_async_silent_flip_3.json`

## Impact
用户以为启用了异步复制，实际未启用；单节点场景危害有限，多节点迁移/灾难恢复假设被静默破坏——数据持久性预期与实际不符。
