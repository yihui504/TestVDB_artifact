# Defect 2: GraphQL Get limit=-1 绕过值域校验返回 200+数据（0 与 10001 均被拒绝）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-2
- defect_id: boundary_bd_gql_limit_07
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Param: limit
- Endpoint: POST /v1/graphql (Get limit)
- Novelty: NOVEL
- Discovered: 2026-08-21T17:17:51Z session

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Get { BdGqlLimit(limit: -1) { _additional { id } } } }"}'
# → HTTP 200 {"data":{"Get":{"BdGqlLimit":[{"_additional":{"id":"6821b771-f0fc-45ff-a8b0-132dfb2c84f7"}}]}}
# 对照 limit:0 → errors "invalid default limit: 0"；limit:10001 → errors "query maximum results exceeded"
```

## Expected vs Actual
- Expected: limit 有非负值域（0 与超上限 10000 均被服务端拒绝证明值域约束存在）；负值应同样被拒绝。
- Actual: limit=-1 返回 200+数据，连 GraphQL errors 字段都没有；同端点 limit=0 与 10001 均被 errors 拒绝。附带观测：offset=-1 错误消息泄漏 Go runtime "slice bounds out of range [-1:]"。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（boundary，range_constraints 类——"limit 非负、offset+limit ≤ QUERY_MAXIMUM_RESULTS"；0/10001 被拒为值域存在的端点内自证）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — GraphQL limit 文档 + QUERY_MAXIMUM_RESULTS 上限，endpoint_registry 含 /graphql，版本匹配 PASS
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_bd_gql_limit_07.py
- Log: debate_logs/output_boundary_bd_gql_limit_07.log（log_pattern: 'limit=-1: 200 {"data":{"Get":{...}}}'，grade A）
- 源码 adapters/repos/db/search.go L481-497：
  ```go
  func (db *DB) getTotalLimit(...) (int, error) {
    totalLimit := pagination.Offset + db.getLimit(pagination.Limit)
    if totalLimit == 0 { return 0, fmt.Errorf("invalid default limit: ...") }
    if !addl.ReferenceQuery && totalLimit > int(db.config.QueryMaximumResults) { ... }
    return totalLimit, nil
  }
  ```
  无任何 limit<0 显式校验；offset=0 时 totalLimit=-1 ≠0 且 ≤max，两个边界检查均不触发 → -1 传入下游分页切片。

## Impact
负 limit 绕过已证实的分页值域校验，传入下游切片运算（offset=-1 已观测 runtime panic 消息泄漏）；客户端分页 bug 被静默放大为非确定性结果集而非早期拒绝。
