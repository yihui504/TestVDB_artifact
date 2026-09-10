# Defect 5: get_stats rowCount 恒 0——insert N 行后计数不变式违反（boundary 首证链）

## Metadata
- Defect ID: TESTVDB-MILVUS-5（boundary_stats_rowcount_016）
- Type: Type4_StateLogicViolation
- Severity: Low（Type4 推断）
- Endpoint: POST /v2/vectordb/collections/get_stats
- Param: rowCount
- Novelty: NOVEL（no_known_hits, HIGH, endorsement: true）

## Reproduction (curl)
```bash
# 1. insert 5 rows (autoID, v1 collection) → 200 {"code":200,"data":{"insertCount":5,"insertIds":[468539281520724799,...,803]}}
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/get_stats" \
  -H "Content-Type: application/json" -d '{"collectionName":"<same>"}'
# 实测: HTTP 200 {"code":200,"data":{"rowCount":0}}
```

## Expected vs Actual
- Expected: 契约不变式 milvus_inv_count_consistency：insert N entities → get_stats data.rowCount == N
- Actual: insert 5 行成功（服务器返回 5 个真实 insertIds）后 rowCount=0；脚本在 insert/flush/load/reload 多状态探测后均恒 0

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_inv_count_consistency（assertion: `insert N entities -> rowCount == N (get_stats)`，契约原文）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（source_url handler_v2.go v2.3.22 可达，endpoint 与源码 getCollectionStat:417 一致）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_stats_rowcount_016.py
  - grade A，raw HTTP+body 全行逐字；多脚本稳定触发（三方独立复现：boundary_stats_rowcount_016 / vein_stats_rowcount_001 / semantic_visibility_04）
  - 附带复证: describe POST→404、describe missing→code 100、list 恶 dbName→code 800（契约信封模型 PASS 方向）
- Log: debate_logs/output_boundary_stats_rowcount_016.log
- 源码: internal/datacoord/services.go:356-357 + internal/datacoord/meta.go:253-262
  ```go
  // meta.go:257
  if isSegmentHealthy(segment) && segment.GetCollectionID() == collectionID { ret += segment.GetNumOfRows() }
  ```
  rowCount 仅累加 datacoord 元数据中 healthy segment 的 NumOfRows，不反映 query path 可见行。auditor：机制为 by-design 但认知模型无 count 类 by_design 锚点，B 兜底 CONFIRMED 定案。

## Impact
用户以 get_stats 做容量监控/迁移校验/计费统计会得到恒 0 的错值（成功信封 code 200 返回错误数据），且 flush/load/reload 均不自愈——统计面与查询面架构性分歧无任何文档披露。
