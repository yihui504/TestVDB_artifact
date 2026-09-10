# Defect 9: drop 不存在集合静默成功（code 200）vs load 同场景正确报 code 100——面内不对称

## Metadata
- Defect ID: TESTVDB-MILVUS-9（vein_drop_idempotent_004）
- Type: Type2_PoorDiagnostics
- Severity: Low（Type2 推断）
- Endpoint: POST /v2/vectordb/collections/drop（对照 collections/load）
- Param: collectionName
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/drop" \
  -H "Content-Type: application/json" -d '{"collectionName":"nope_not_exist"}'
# 实测: HTTP 200 code 200（静默成功）
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/load" \
  -H "Content-Type: application/json" -d '{"collectionName":"nope_not_exist"}'
# 对照: HTTP 200 code 100（正确 not-found）
```

## Expected vs Actual
- Expected: 请求侧可判定的 not-found 客户端错误应如 load 面一样返回错误码（契约 v1 面明文 'drop non-existent -> error code 100'，milvus_behavioral_drop_001）
- Actual: 同一不存在集合，drop=200+code:200 成功信封吞掉 not-found，load=200+code:100 正确报错

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_behavioral_drop_001（assertion: `drop non-existent collection -> error code 100`；A=NEUTRAL——断言 endpoint 为 v1 而实测打 v2，进灰区；'泛锚'：v2/drop 契约沉默）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_MISMATCH（content_consistency FAIL——v1 面有明文承诺、v2 面无条文；源码证实 v2 与 v1 走同一 rootcoord 幂等 drop）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_drop_idempotent_004.py
  - log_pattern: `load nonexistent code=100; drop nonexistent code=200`（code 值由脚本直接断言输出；摘要级 log，错误消息体未逐字留存——如实降级）
- Log: debate_logs/output_vein_drop_idempotent_004.log
- 源码: internal/rootcoord/drop_collection_task.go:58-63
  ```go
  collMeta, err := t.core.meta.GetCollectionByName(...)
  if errors.Is(err, merr.ErrCollectionNotFound) {
      // make dropping collection idempotent.
      log.Warn("drop non-existent collection", ...); return nil
  }
  ```
  显式幂等设计（注释原话），v2 REST handler_v2.go:481-494 零干预透传成功信封。auditor：机械 B=CONFIRMED（信封语义违反）定案，幂等注释不推翻。

## Impact
集合名 typo 的 drop 操作返回"成功"，用户以为删对了目标集合（实际目标集合仍存活、误打的同名不存在集合被静默确认）——破坏性操作无 not-found 反馈是高危误导；与 load 面的不对称使错误处理逻辑无法统一。
