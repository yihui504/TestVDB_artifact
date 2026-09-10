# Defect 9: entities/query — limit=0/-5 被当 Unlimited 返回全表、offset=-5 当 0（同值 search 侧 65535 拒）

## Metadata
- Defect ID: TESTVDB-MILVUS-9
- defect_id (script): vein_query_limit_semantic_drift_4
- Type: Type3_RuntimeFailure（数值下界，grade A CONFIRMED）
- Endpoint: POST /v2/vectordb/entities/query（对照 entities+search）
- Param: limit（param_name: limit）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/query" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<10 行集合>","filter":"id >= 0","limit":0,"outputFields":["id"]}'
```

## Expected vs Actual
- Expected: 与 search 共享 limit/offset 语义（1<=limit+offset<=16384），非法值应拒绝
- Actual: `PASS query_limit0_returns_all 10`（limit=0 返回全部 10 行）；`PASS query_limit_neg_returns_all 10`（limit=-5 同全表）；`PASS query_offset_neg_ignored {'code':0,...,'data':[3 rows]}`（offset=-5 当 0）
- 对照：`PASS control_search_limit0_rejected {'code':65535,'topk [0] is invalid...'}`——同值 search 侧拒绝

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: vein_query_limit_semantic_drift（+ 官方 milvus_range_entities_search_001 显式限定 search）
  - assertion: `query 与 search 共享 limit/offset 语义约束；search 侧拒绝的非法值 query 侧不得静默接受为全表/当 0`；api_violates_assertion=true
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（官方约束仅覆盖 search 侧——契约本身即体现不对称覆盖缺口）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_query_limit_semantic_drift_4.py（四断言双端点对照；grade A；多脚本稳定触发）
- Log: vein_scripts/output_vein_query_limit_semantic_drift_4.log

### 源码 文件:行号+摘录
- handler_v2.go L1071-1076（query 入口）：`if httpReq.Limit > 0 && !matchCountRule(...) { req.QueryParams = append(..., LimitKey, ...) }`——负/零 limit 直接不下发
- task_query.go L169-260：`limit = typeutil.Unlimited(-1)` 初始；仅 isLimitProvided 才走 validateMaxQueryResultWindow
- search 侧 search_util.go L138-221/602 对 topk/offset 强制 validateLimit/validateMaxQueryResultWindow
- 漂移根因：query 路由层用 '>0' 过滤替代校验，非法值与"未提供"不可区分（validation_absent）

## Impact
query 侧 limit=0/-5 触发 Unlimited 全表扫描：大集合上返回全部数据（内存/带宽放大，DoS 面）；offset=-5 静默当 0。同参数同值在 query/search 两入口行为分裂（全表 vs 65535），跨端点语义一致性断裂。
