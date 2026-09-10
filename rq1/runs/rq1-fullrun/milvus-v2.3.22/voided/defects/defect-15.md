# Defect 15: 并发 upsert/delete 竞态触发 C++ Assert 运行时失败，且断言宏实参与内部通道名透出到 REST message

## Metadata
- Defect ID: TESTVDB-MILVUS-15（state_r2_upsert_delete_race_007）
- Type: Type3_RuntimeFailure + Type2_PoorDiagnostics（单一响应双缺陷载体）
- Severity: High（Type3 推断）
- Endpoint: POST /v2/vectordb/entities/delete（+ concurrent upsert/search）
- Param: delete_id
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
# 并发 upsert/delete/search 载荷下，delete 中途:
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/delete" \
  -H "Content-Type: application/json" -d '{"collectionName":"t","filter":"id in [0]"}'
# 实测: HTTP 200 {"code":65535,"message":"failed to search/query delegator 1 for channel by-dev-rootcoord-dml_11_468539281521155193v0: Assert \"std::max(data_barrier, "}
```

## Expected vs Actual
- Expected: 契约 milvus_bc_error_envelope：body code ∈ {100, 1802, 1804}；message 为用户可理解的错误描述，不含内部实现细节
- Actual: HTTP 200 + code 65535（非枚举码）且 message 透出三段内部细节：C++ Assert 宏实参原文 `std::max(data_barrier,`、内部 dml channel 名 `by-dev-rootcoord-dml_11_<collectionID>v0`、delegator 节点号——log:3-4 逐字固化

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_bc_error_envelope（assertion: `... body code in {100 collection not found, 1802 missing/invalid params, 1804 invalid data}`；violates=True 无域外抗辩空间）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（errors.go / handler_v2.go v2.3.22 reachable，版本精确匹配）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/state_r2_upsert_delete_race_007.py
  - log:3-4 逐字: `('delete', 0, 200, 65535, '{"code":65535,"message":"failed to search/query delegator 1 for channel by-dev-rootcoord-dml_11_468539281521155193v0: Assert \"std::max(data_barrier, '}`；VERDICT: DEFECT_FOUND
  - 对照: final rowCount=0 query_count=50 expected=50——并发窗口过后数据集完整，运行时失败未致数据丢失
- Log: debate_logs/output_state_r2_upsert_delete_race_007.log
- 源码: internal/core/src/query/visitors/ExecExprVisitor.cpp:322-326 + internal/core/src/common/EasyAssert.h:110-133 + internal/proxy/lb_policy.go:188 + pkg/util/merr/errors.go:153
  ```cpp
  // ExecExprVisitor.cpp:325
  AssertInfo(std::max(data_barrier, indexing_barrier) == num_chunk,
             "max(data_barrier, index_barrier) not equal to num_chunk");
  ```
  透出链全闭合：AssertInfo 宏 (#expr, EasyAssert.h:122) 将宏实参原文打入异常 → FailureCStatus strdup(ex->what()) 逐字传出 C 层 → Go lb_policy.go:188 Wrapf（channel 名注入）→ merr.Code() 兜底 65535 → HTTP 200 body。Type2 诊断泄露是代码结构保证的，非偶然字符串。

## Impact
(a) Type3：并发写删下 delete 请求运行时失败（segcore 断言不成立），正常负载组合即可触发；(b) Type2：C++ 断言原文、内部 channel 命名、节点拓扑经公开 REST 接口外泄——既暴露实现细节（攻击面信息），又产出对用户完全不可解析的错误消息。
