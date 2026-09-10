# Defect 9: 失败创建（422）后幻影类残留——读写通道状态分裂无回滚

## Metadata
- Defect ID: TESTVDB-WEAVIATE-009 (vein_phantom_class_failed_create_4)
- Type: Type4_StateLogicViolation
- Severity: High
- Endpoint: POST /v1/schema (shardingConfig.desiredCount=0) + GET /v1/schema/{class} + POST /v1/objects
- Param: shardingConfig.desiredCount
- Novelty: NOVEL (gate, LOW precision, no_known_hits)
- Discovered: 2026-08-21

## Description
POST /schema 带 `desiredCount=0` 正确返回 422，但 schema 条目已写入 raft/schema 层且未回滚：GET /schema/{class} 返回 200（类"存在"，desiredCount=0），而向该类 POST /objects 返回 500 `import into non-existing index`。读写两通道对"类存在性"判定源不同（schema 层 vs index 层），失败路径无补偿删除。control（desiredCount=1 全成功）排除普遍性失败。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"VeinGhost4","shardingConfig":{"desiredCount":0}}'
# → HTTP 422（正确拒绝）
curl -s "http://localhost:8080/v1/schema/VeinGhost4"
# 实际: HTTP 200（幻影类残留） 期望: 404
curl -s -X POST "http://localhost:8080/v1/objects" \
  -H "Content-Type: application/json" \
  -d '{"class":"VeinGhost4","properties":{}}'
# 实际: HTTP 500 "import into non-existing index for VeinGhost4"
```

## Expected vs Actual
- Expected: 创建失败后类不可见（404），状态不变式"成功创建才可见"保持
- Actual: GET 200 / 写 500 的状态分裂

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `vein_scripts/vein_phantom_class_failed_create_4.py`
- Log: `output_vein_phantom_class_failed_create_4.log`
- 源码: `cluster/schema/reader.go` L93-113 `checkShardingState()`（physical shards unavailable 读路径拒绝源）；`adapters/repos/db/crud.go` L41-47（`db.GetIndex` nil → import into non-existing index，写 500 源）
- Ring 1 (Contract Clause 契约条款): state_invariant 'Collection exists in GET /schema response after POST /schema'（语义反演适用）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（全 PASS）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/vein_phantom_class_failed_create_4.json`

## Impact
幻影类占据命名空间（同名重建被拒或行为未定义），schema 视图与真实可用性背离，用户无法从 API 区分可用类与幻影类；需要手工清理。
