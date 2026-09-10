# Defect 12: get_stats rowCount=0 vs count(*)=10 且 query 返回 10 行——三方对照直接违反计数不变式（vein 链）

## Metadata
- Defect ID: TESTVDB-MILVUS-12（vein_stats_rowcount_001）
- Type: Type4_StateLogicViolation
- Severity: Low（Type4 推断）
- Endpoint: POST /v2/vectordb/collections/get_stats
- Param: rowCount
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
# 前置: 插入 10 行，wait >10s，loaded 集合，release/reload 循环后:
#   query count(*)  → 10 行
#   query 返回       → 10 行
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/get_stats" \
  -H "Content-Type: application/json" -d '{"collectionName":"<same>"}'
# 实测: HTTP 200 {"code":200,"data":{"rowCount":0}}
```

## Expected vs Actual
- Expected: 契约不变式 milvus_inv_count_consistency：insert N rows → get_stats rowCount == N（此处 N=10）
- Actual: count(*)=10 / query_rows=10 / rowCount=0 三方对照一行汇总；wait>10s + release/reload 循环机械排除一致性滞后与状态窗口解释

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_inv_count_consistency（assertion: `insert N entities -> rowCount == N (get_stats)`，violates=True 无含混）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（endpoint_registry v2 get_stats 'data {rowCount}' 与源码 handler_v2.go:417-428 一致；source_url v2.3.22 可达）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_stats_rowcount_001.py
  - grade A，log_pattern: `count(*)=10 query_rows=10 get_stats.rowCount=0`；多脚本稳定触发
  - ⚠️ 本链自身 log 为摘要行；raw 逐字证据由同根因组 boundary_stats_rowcount_016（defect-5）与 semantic_visibility_04（defect-8）补强
- Log: debate_logs/output_vein_stats_rowcount_001.log
- 源码: internal/datacoord/meta.go:253-261（getNumRowsOfCollectionUnsafe 仅累加 healthy segment NumOfRows）+ internal/proxy/task_statistic.go:591-671（v2 REST 实际走旧版 getCollectionStatisticsTask）+ internal/datacoord/services.go:340-360。auditor：release/reload 后仍 0 说明非单纯 growing-segment 窗口；认知模型无 count 类 by_design 锚点，B 兜底定案。

## Impact
rowCount 统计与真实数据量（count(*)、query 实测）持久分裂且 load/reload 不自愈；依赖 get_stats 的容量规划、监控告警、迁移校验全部失真，且以成功信封返回错值（静默错误数据）。
