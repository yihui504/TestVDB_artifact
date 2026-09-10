# Defect 6: 16x HTTP 500 on points/query and points+upsert during collection delete/recreate lifecycle race (no 404 mapping, timing-dependent)

## Metadata
- Defect ID: TESTVDB-QDRANT-6
- Candidate ID: state_collections_delete_004
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断，人工分流参考；chain-auditor 建议 human_review）
- Endpoint: collections+delete (lifecycle driver); failing calls on points+query (15/16) and points+upsert (1/16)
- Discovered: 2026-08-23T17:54:53Z（R4-b1 批）
- Chain verdict: DEFECT（D==SUPPORTS_DEFECT：认知盲区 "Concurrent worker safety(55)/try_join_all cancellation" 现象级命中；race 窗口 16 次 500 为真实服务端行为）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: （空 — 派发 constraint_id 为空串；契约 22 state_constraints + 6 state_invariants + 5 behavioral_contracts 均不覆盖 delete/recreate 生命周期中的并发 query/upsert 行为，chain_broken_at=contract）
- **contract_assertion**（最近邻约束，均不覆盖主观测）: qdrant_state_collections_delete_001 "DELETE existing => 200; DELETE missing => 404"；qdrant_state_collections_get_001 "GET unknown collection => HTTP 404"；qdrant_inv_collection_gone_after_delete_001 "delete => 200 THEN collections+get => 404" — 三者只管 DELETE/GET 状态码，5xx on query/upsert mid-race 无任何断言
- **expected_behavior**: 访问线程在 delete/recreate 竞态窗口内应得到 200 或 404（collection 缺席时的规范映射），而非 500 服务端内部错误
- **source_url**: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection（脚本内嵌引用）

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
- **doc_version**: 1.18.x（versioned，URL 正确钉版；endpoint_registry 四个涉事端点 verified_at 2026-08-23T05:20:00Z）
- **doc_quote**: （无契约断言覆盖并发生命周期行为——文档层同样空白；引用仅证明端点与版本钉定）
- **url_status**: degraded（WebFetch domain_blocked；endpoint_registry 管线期验证背书）
- **version_match**: matched（URL 钉版正确，页面内容未能独立抓取）

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: lifecycle 线程 8 轮 DELETE→PUT recreate 循环，10 个访问线程（t0..t9）各 40 轮 `POST {db_base}/collections/{c}/points/query` / count / 条件 upsert（db_base 以原脚本 DB_URL 为准）
- **HTTP Response**: 15 次 `500 {"status":{"error":"Service internal error: Expected at least one response for one query"}}`（query）+ 1 次 `500 {"status":{"error":"Service internal error: Failed to apply operation to at least one `Active` replica. Consistency of this update is not guaranteed. Please ret…"}}`（upsert）；赛前 seed 与赛后 recreate/upsert/count 全部 200（count=25 精确），无僵尸状态
- **Container Logs**: output_state_collections_delete_004.log（ERROR_CENSUS: 16 events，阈值 2）
  ```
  ERROR_CENSUS: 16 events (threshold for DEFECT: 2)
    error_event: ('query[t3]', 500, '{"status":{"error":"Service internal error: Expected at least one response for one query"},…}')
    error_event: ('upsert[t8]', 500, '{"status":{"error":"Service internal error: Failed to apply operation to at least one `Active` replica…Please ret')
  …
  post-race recreate: 200 / post-race upsert: 200 / post-race count: 200 {"result":{"count":25}}
  VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 16 5xx/transport errors during lifecycle race (>=2 confirms)
  ```
  同 run 姊妹脚本 state_collections_delete_005 / _010 均 ERROR_CENSUS: 0（窗口 timing-dependent 的旁证）。
- **reproduced_at**: 2026-08-23（R4 执行窗口；log 已落盘，待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/src/actix/api/query_api.rs#L78-L95
- **code_snippet**（链内取证）:
  ```rust
  // query_api.rs:78-95 — 单查询 REST handler
  .query_batch(...).await?.pop()
  .ok_or_else(|| StorageError::service_error("Expected at least one response for one query"))?  // → 500
  // toc/point_ops.rs:366-388 — 唯一 404 门：get_collection 名称解析
  //   （mid-lifecycle TOC 条目仍可解析而 shard 正在拆除/重建 → 唯一 404 门不触发）
  // replica_set/update.rs:608-617 — 无 Active replica 应用操作时
  //   service_error("Failed to apply operation to at least one `Active` replica … Please retry.")  // → 500
  ```
  两个 500 消息均为显式编码的 fallback（非崩溃）；名称解析后没有任何路径把 mid-lifecycle 缺席映射为 404。upsert 消息自带 "Please retry"（设计者明知窗口存在）。

## Completeness Check
- Ring 1: MISSING（契约与文档双层空白；"应 200/404 非 5xx" 期望仅存在于脚本 docstring，chain-auditor 以视角 D 认知盲区锚定 DEFECT 并建议人工复核）
- Ring 2: DEGRADED
- Ring 3: PRESENT（16 事件 census + 赛前赛后健康对照）
- **Overall**: INCOMPLETE_EVIDENCE（契约环缺失；现象本身证据充分，human_review_recommended=true）

## Reproduction Steps
1. 建集合并 seed 25 点。
2. 线程 A 循环 8 次：DELETE /collections/{c} → PUT 重建；线程 B..K（10 线程）各 40 轮 query/count/upsert。
3. 统计访问调用中 status>=500 或传输层 0 的事件：竞态窗口内出现 15 次 query 500 "Expected at least one response for one query" + 1 次 upsert 500 "Failed to apply … Active replica"。
4. 赛后确定性检查：recreate/upsert/count 全 200（count=25）——服务健康，失败仅在窗口内。

## Impact Analysis
运维脚本或编排器高频 delete/recreate 集合时，并发读写会得到 5xx：重试型客户端可自愈（"Please retry"），但把 500 当作服务故障告警的监控会误报，且 500 语义上"服务端错误"与实际情况（集合正在重建，应为 404/不可用语义）不符。窗口 timing-dependent（姊妹脚本 0 事件），属并发正确性灰区——chain-auditor 建议人工复核是否定性为已知 transient。

## Original Execution Log
- Log: `output_state_collections_delete_004.log`（含 VERDICT 行）
- Script: `state_collections_delete_004.py`（state 派发脚本；链记录位于 debate_logs/state_collections_delete_004.py）

## MRE
- Script: `defect-6-script.py`（reporter-mre Agent 产出）
- Run: `python defect-6-script.py`
