# Defect 7: GraphQL limit=-1 返回全部数据；REST limit=-1 返回 200 空体

## Metadata
- defect_id: boundary_gql_limit_negative_009
- type: Type1_IllegalSuccess
- param: limit
- novelty: NOVEL
- Endpoint: POST /v1/graphql (+ REST GET /v1/objects)
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE 机械 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
# GraphQL 通道
curl -s -X POST "http://localhost:8080/v1/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Get { BndLimit(limit: -1) { txt } }"}'
# -> HTTP 200；返回全部 3 行 [doc0, doc1, doc2]（负 limit = 无限查询）
# 对照：limit=0 -> 200 + errors "explorer: list cla..."
#       limit=2147483647 -> 200 + errors（超 QUERY_MAXIMUM_RESULTS，正确）

# REST 通道
curl -s "http://localhost:8080/v1/objects?limit=-1"
# -> HTTP 200, content-length=0（空体畸形响应）
```

## Expected vs Actual
- Expected: 负 limit 应报错（REST get.go 错误文案自证："If you've supplied a negative offset or limit, this may be an underflow error"）；0 与 INT_MAX 正确报错证明值域检查通道存在。
- Actual: GraphQL 负 limit 被特判为"未设置"→ 200 返回全部数据（无界查询）；REST 负 limit 绕过上限检查返回 200 空体。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（族级：entities/filters/pagination.go L40 'limit.(int) < 0' 处理 + REST get.go 错误文案 "If you've supplied a negative offset or limit, this may be an underflow error"）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（源码锚本地核对；limit 值域无专属 constraint）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_gql_limit_negative_009.py
- Log: debate_logs/output_boundary_gql_limit_negative_009.log（GraphQL 4 变体 + REST 1 变体）
- 源码 文件:行号+摘录: entities/filters/pagination.go L39-42 `limit, limitOk := args["limit"]; if !limitOk || limit.(int) < 0 { limit = LimitFlagNotSet }`——负 limit 显式等价"未设置"→无限查询；usecases/objects/get.go L245-252 `localOffsetLimit` 仅检查 offset+limit > QueryMaximumResults（负 limit 使总和变小绕过检查）→ 空集 → REST 200 空体。

## Impact
无界查询：大表上 limit=-1 等价全表扫描（性能/内存风险）；REST 侧 200 空体让客户端误以为无数据（静默错误）。pagination.go 的负值特判疑为 nearXXX 距离搜索设计，但无条件吞掉普通 Get 请求。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
