# Defect 8: insert+delete 复合链后 get_stats rowCount 恒 0（search 证实数据存在，统计读 0）

## Metadata
- Defect ID: TESTVDB-MILVUS-8（semantic_visibility_04）
- Type: Type4_StateLogicViolation
- Severity: Low（Type4 推断）
- Endpoint: POST /v2/vectordb/collections/get_stats + v2/vectordb/entities/delete
- Param: rowCount
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
# create → insert 3 rows (ids 1/2/3) → search 证实 3 行可检索 → delete 1 行 (filter) → search2 只剩 2/3 →
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/get_stats" \
  -H "Content-Type: application/json" -d '{"collectionName":"<same>"}'
# 实测（两个时点）: HTTP 200 {"code":200,"data":{"rowCount":0}}  （插入后期望 3，删除后期望 2，实测均 0）
```

## Expected vs Actual
- Expected: 契约不变式 milvus_inv_count_consistency：insert N rows → get_stats rowCount == N（删 1 行后应为 2）
- Actual: 插入 3 行后 rowCount=0；删除 1 行后仍 rowCount=0——search 面证实数据真实存在且删除真实生效，唯统计面恒 0

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_inv_count_consistency（assertion: `insert N entities -> rowCount == N (get_stats)`）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（content/endpoint PARTIAL：rowCount 语义原文一致；附带发现契约 delete id 可选声称与源码 binding:required 漂移）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: semantic_scripts/semantic_visibility_04.py
  - grade A，raw HTTP 逐字；多脚本稳定触发（与 vein_stats_rowcount_001 / boundary_stats_rowcount_016 三方独立复现）
  - 关键对照链：search1 返回 3 行（排除数据丢失）；delete_by_id 1802 拒绝；delete_by_filter 200 成功；search2 剩 id 2/3（删除生效）；get_stats2 仍 0——复合操作排除状态窗口解释
- Log: debate_logs/output_semantic_visibility_04.log
- 源码: internal/datacoord/meta.go:253-262（getNumRowsOfCollectionUnsafe 逐 healthy segment 累加 NumOfRows）+ internal/proxy/task_statistic.go:591-671（v2 REST 实际走旧版 getCollectionStatisticsTask 路径）+ handler_v2.go:417-430。auditor：datacoord 机制不构成认知锚点级 by_design 辩护（by_design_patterns 无 count/stats 条目），B/D 兜底定案。

## Impact
监控/审计/迁移校验依赖 get_stats 的用户得到与真实数据量无关的恒 0 计数；与 search/count(*) 的持久分歧无文档披露，属状态/统计逻辑违反契约不变式。
