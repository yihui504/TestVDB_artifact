# Defect 10: v2 identical 重复创建同名集合静默成功，违反契约 "duplicate name -> already-exists error"

## Metadata
- Defect ID: TESTVDB-MILVUS-10（vein_dupcreate_msg_006）
- Type: Type2_PoorDiagnostics
- Severity: Low（Type2 推断）
- Endpoint: POST /v2/vectordb/collections/create（对照 v1/vector/collections/create）
- Param: collectionName
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
# 集合已存在后，用完全相同 payload 再次创建:
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"vei","schema":{...identical...}}'
# 实测: HTTP 200 code 200（静默成功）
# 对照 v1 同操作: HTTP 200 code 65535 "create duplicate collection with different parameters, collection: vei"
```

## Expected vs Actual
- Expected: 契约 milvus_state_create_collection_001：duplicate name → already-exists error
- Actual: v2 identical dup 静默 200；diff-param dup 在 v2 被拒（证明 v2 具备查重能力却在 identical 情形放行）；v1 面 identical dup 报 65535 duplicate——同操作两面相反信封

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_state_create_collection_001（assertion: `...duplicate name -> already-exists error`；A=CONFIRMED 机械定案）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（v1/create 条目明文锚点；v2/create 无重复创建条文）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_dupcreate_msg_006.py
  - log_pattern: `identical dup: v2 code=200, v1 code=65535 ('create duplicate collection with different parameters, collection: vei')`
  - ctrl diff-param dup: v2=True v1=True 均报错（对照证明查重能力存在）；摘要级 log，v1 消息体已由脚本摘要逐字带出；派发 prompt 的 'CreateIndex failed 误导消息' 子主张未取证（不采信）
- Log: debate_logs/output_vein_dupcreate_msg_006.log
- 源码: internal/rootcoord/create_collection_task.go:470-481
  ```go
  existedCollInfo, err := t.core.meta.GetCollectionByName(...)
  if err == nil {
      equal := existedCollInfo.Equal(*clone)
      if !equal { return fmt.Errorf("create duplicate collection with different parameters, collection: %s", ...) }
      // make creating collection idempotent.
      log.Warn("add duplicate collection", ...); return nil
  }
  ```
  幂等创建为注释明文设计；auditor 按 E2 规则不推翻 A 定案（C=WEAK_REFUTED 但 A=CONFIRMED 机械主导）。

## Impact
用户/自动化脚本重复执行 create 得到成功却无任何"已存在"提示——无法区分"新建成功"与"命中已有集合"；v1/v2 两面相反信封进一步使跨版本迁移的幂等语义不可预测。
