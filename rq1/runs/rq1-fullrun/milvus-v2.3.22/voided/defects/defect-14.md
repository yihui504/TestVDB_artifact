# Defect 14: release 竞态下 in-flight search 返回 200+code 65535（非规范信封码，delegator 文案）

## Metadata
- Defect ID: TESTVDB-MILVUS-14（state_r2_release_inflight_004）
- Type: Type3_RuntimeFailure（错误信封违规）
- Severity: High（Type3 推断）
- Endpoint: POST /v2/vectordb/collections/release（+ in-flight v2/vectordb/entities/search）
- Param: release
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
# 5x load/release 循环 × 15 并发 in-flight search；竞态窗口内:
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" -d '{"collectionName":"t","data":[[...]]}'
# 首跑主观测: HTTP 200 {"code":65535,"message":"failed to search/query delegator ... collection not found..."}
# 复跑（未复现竞态）: HTTP 200 {"code":101,"message":"failed to search: collection not loaded[collection=468539281521155132]"}
```

## Expected vs Actual
- Expected: 契约 milvus_bc_error_envelope：业务错误 HTTP 200 + body code ∈ {100 collection not found, 1802, 1804}；仅 auth/timeout/404 为非 200
- Actual: 竞态窗口内 in-flight search 返回 200 + code 65535（errUnexpected 兜底码，不在枚举内），message 含 lb_policy delegator wrap 文案

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_bc_error_envelope（assertion: `business errors use HTTP 200 + nonzero body code; expected: body code in {100, 1802, 1804}`）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（errors.go / endpoint_registry v2.3.22 全 reachable，版本精确匹配）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/state_r2_release_inflight_004.py
  - 主观测（首跑，claim 转述，未固化于归档 log——如实降级 grade C/flaky）: 4x http=200 code=65535 "failed to search/query delegator ... collection not found"，与同窗口规范 101 混出
  - 归档复跑 log: 101x45 / 200x15（未复现竞态）；旁证 output_state_partition_load_06.log:11 同结构 65535 delegator 错误（不同 root cause），证明该形态非孤例
- Log: debate_logs/output_state_r2_release_inflight_004.log
- 源码: internal/proxy/lb_policy.go:186-190 + pkg/util/merr/errors.go:49,153
  ```go
  // lb_policy.go:188
  lastErr = errors.Wrapf(err, "failed to search/query delegator %d for channel %s", targetNode, workload.channel)
  // errors.go:153
  errUnexpected = newMilvusError("unexpected error", (1<<16)-1, false)  // 65535
  ```
  release 竞态中 shard workload.exec 失败 → wrap 后错误若非 milvusError，merr.Code() default 分支落 65535——与主观测文案精确吻合。auditor：主观测 raw 未固化已降级，但机械 B 触发无改判空间。

## Impact
release/滚动重启等常规运维窗口内客户端收到 65535 意外错误（非规范 not-loaded 101），触发错误的告警/重试升级路径；竞态窗口窄导致问题间歇出现、难复现、难归因。
