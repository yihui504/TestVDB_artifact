# Defect 11: v2 entities/query limit=0 返回全量 11 行——非法 limit 变无限制读取（vein 链）

## Metadata
- Defect ID: TESTVDB-MILVUS-11（vein_query_limit0_002）
- Type: Type2_PoorDiagnostics（兼 Type1 形态：非法值被接受）
- Severity: Low（Type2 推断）
- Endpoint: POST /v2/vectordb/entities/query（对照 entities/search）
- Param: limit
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/query" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","filter":"id >= 0","limit":0,"outputFields":["*"]}'
# 实测: HTTP 200 {"code":200,"data":[...全部 11 行...]}
# 对照: control limit=1 → 1 rows; search limit=0 → 被拒绝
```

## Expected vs Actual
- Expected: limit=0 应返回空集或被业务码拒绝（search 面同参数被拒）
- Actual: HTTP 200 + code 200 返回全量 11 行（limit=0 被静默当作"未提供"→无限制读取）

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚 milvus_bc_error_envelope（'泛锚'：契约 endpoint_registry 列 limit 可选但无 0 值语义条文；A=NEUTRAL 灰区，主张形态=契约缺口+同参数两面矛盾；与 defect-2 的重锚约束 milvus_range_v2_query_limit_001 同根因互证）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（link/version/endpoint PASS，content PARTIAL——契约沉默）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_query_limit0_002.py
  - log_pattern: `control limit=1 -> 1 rows; limit=0 -> code=200, 11 rows`；Detail 行: "limit=0 silently treated as unbounded: returns all 11 rows instead of 0 rows or a rejection"
  - ⚠️ 摘要级 log：search 被拒错误码未逐字留存；跨脚本互证见 boundary_limit_offset_008（raw 逐字）
- Log: debate_logs/output_vein_query_limit0_002.log
- 源码: internal/distributed/proxy/httpserver/handler_v2.go:565-567
  ```go
  if httpReq.Limit > 0 && !matchCountRule(httpReq.OutputFields) {
      req.QueryParams = append(req.QueryParams, &commonpb.KeyValuePair{Key: ParamLimit, ...})
  }
  ```
  limit==0 时不追加 limit 参数→底层 Query 视为无 topK 限制全量返回；对照 search :879 无条件写 TopK=0 被底层校验拒绝。v1 query (handler_v1.go:446) 同为 >0 判断，同病。verification_outcome: validation_absent。

## Impact
非法 limit=0 触发全量读取（资源放大/DoS 面）；query 与 search 同参数语义相反使客户端无法建立一致的 limit 心智模型。
