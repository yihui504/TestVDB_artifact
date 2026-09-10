# Defect 2: v2 entities/query 非法 limit（0/-1）被静默接受并全量返回

## Metadata
- Defect ID: TESTVDB-MILVUS-2（boundary_limit_offset_008）
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Endpoint: POST /v2/vectordb/entities/query（对照 v1/vector/search）
- Param: limit
- Novelty: NOVEL（no_known_hits, HIGH, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/query" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","filter":"id >= 0","limit":0,"outputFields":["id","vector"]}'
# 实测: HTTP 200 {"code":200,"data":[{...全部 2 行...}]}
```

## Expected vs Actual
- Expected: 契约 milvus_range_v2_query_limit_001（R2 重锚新增）：v2 entities/query limit ∈ [1,16384]，否则业务码拒绝（同 v1 topk）
- Actual: limit=0 与 limit=-1 均 HTTP 200 + code 200 且返回全部数据行（非法 limit 变无限制全量读取）；对照 v1 search 同参数 code 65535 "topk [0] is invalid, top k should be in range [1, 16384]"

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_range_v2_query_limit_001（assertion: `v2 entities/query limit >= 1 且 <= 16384，否则业务码拒绝（同 v1 topk）`；R2 消解 CONFLICT 重锚，引文为契约原文）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（source=go-func handler_v2.go:565 vs :879，reachable，版本精确匹配 v2.3.22）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_limit_offset_008.py
  - 主观测: `[v2 query limit=0] http=200 body={"code":200,"data":[{"id":468539281520724788,...},{"id":468539281520724789,...}]}`
  - 对照组: limit=-1 同样全量 2 行；v1 limit=0→65535, limit=-1→65535, offset=-5→65535, limit=16385→65535, limit=INT32_MAX→65535, '3'/1.5→1801
  - 互证: vein_query_limit0_002 跨脚本独立触发同一模式
- Log: debate_logs/output_boundary_limit_offset_008.log
- 源码: internal/distributed/proxy/httpserver/handler_v2.go:562-567
  ```go
  if httpReq.Limit > 0 && !matchCountRule(httpReq.OutputFields) {
      req.QueryParams = append(req.QueryParams, &commonpb.KeyValuePair{Key: ParamLimit, ...})
  }
  ```
  request_v2.go:75 `Limit int32` 无 binding 校验；limit<=0 时 ParamLimit 整个被省略→下游无 limit 全量返回。对照 search handler_v2.go:879 无条件写 TopK=0 被底层拒绝——同参数两 handler 相反处理。

## Impact
客户端传 0/-1（typo 或默认值漏改）不报错反而触发全表扫描式读取，大集合上可造成意外内存/带宽放大与性能雪崩；且与 search 面同参数语义矛盾，行为不可预测。
