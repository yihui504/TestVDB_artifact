# Defect 2: Create 同时传 schema 与 dimension 静默成功（互斥校验缺失，跨版本重现）

## Metadata
- defect_id: boundary_s10_quick_full_conflict
- type: Type1_IllegalSuccess
- param: dimension
- novelty: NOVEL（gate: no_known_hits, confidence HIGH, endorsement=true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"c1","dimension":4,"schema":{"fields":[...全量 schema...]}}'
```

## Expected vs Actual
- **Expected**: 契约 `milvus_type_collections_create_003`：`NOT(dimension set AND schema set) else code==1100`。
- **Actual**: `{"code":0,"data":{}}`——同时携带 schema 与 dimension 返回成功，dimension 被无声跳过。附加：schema 全量模式下同传 idDataType 也未拒绝（code:0）。对照组证明校验体系存在：dim=0 → 1100 'dimension is required for quickly create collection'；dim=-4 → 65535 范围错误。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_003（断言 `NOT(dimension set AND schema set) else code==1100`，机械 A=CONFIRMED，id+quote 逐字匹配，violates=true）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（source=handler_v2.go 本地 clone 可达，link/version/content/endpoint 全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_s10_quick_full_conflict.py
- Log: output_boundary_s10_quick_full_conflict.log

源码 `internal/distributed/proxy/httpserver/handler_v2.go:1795-1812`：
```go
if len(httpReq.Schema.Fields) == 0 {
    ...
    if httpReq.Dimension == 0 {
        err := merr.WrapErrParameterInvalid("collectionName & dimension", "collectionName",
            "dimension is required for quickly create collection(...)")
```
quick-create 快路径整体包在 `len(httpReq.Schema.Fields)==0` 内；schema 非空时走全量路径，`httpReq.Dimension` 不再被读取且无互斥校验（validation_absent）。与 2.6.10 session #9 同款跨版本重现。

## Impact
用户在全量 schema 请求中误留 dimension 字段时得到成功响应，实际生效的 schema 与请求中 dimension 暗示的配置可能不一致——静默的配置歧义，无任何告警。
