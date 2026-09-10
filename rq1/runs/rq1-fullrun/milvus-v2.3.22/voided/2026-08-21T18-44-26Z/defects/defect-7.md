# Defect 7: v2 entities/query 非法 filter 表达式被归类 65535 UnexpectedError 而非参数错误码族

## Metadata
- Defect ID: TESTVDB-MILVUS-7（semantic_filter_expr_05）
- Type: Type2_PoorDiagnostics
- Severity: Low（Type2 推断）
- Endpoint: POST /v2/vectordb/entities/query（对照 entities/search）
- Param: filter
- Novelty: NOVEL（no_known_hits, confidence: HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/query" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","filter":"score >>> 5","outputFields":["id"]}'
# 实测: HTTP 200 {"code":65535,"message":"cannot parse expression: score >>> 5, error: line 1:8 extraneous input '>' expecting {'(', '[', EXISTS, '+', '-', '~', NOT, ...}"}
```

## Expected vs Actual
- Expected: 契约 milvus_behavioral_query_001：invalid filter → 1804-family 参数/数据错误码
- Actual: 请求侧可判定的非法 filter（parser 明确报 cannot parse expression）被归为 65535 UnexpectedError（服务端意外错误族）——用户输入错误被当作服务端内部错误

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_behavioral_query_001（assertion: `invalid filter -> 1804-family error; ... code 1804 for invalid boolean expr`；A=NEUTRAL 引文含混，B 机械兜底定案）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_MISMATCH（content_consistency FAIL / endpoint_precision FAIL——契约把 v1 观察到的 1804 行为外推到 v2，doc 层漂移即争点；chain_broken_at: doc）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: semantic_scripts/semantic_filter_expr_05.py
  - 主观测: invalid_filter 200 code 65535（parser 详情在 message 中）
  - 对照: eq15/range/in 合法 filter 全部正确返回；bad_field nonexistent_field==1 也报 65535；search_filter 正常
- Log: debate_logs/output_semantic_filter_expr_05.log
- 源码: internal/distributed/proxy/httpserver/handler_v2.go:568-573
  ```go
  resp, err := wrapperProxy(ctx, c, req, h.checkAuth, false,
      "/milvus.proto.milvus.MilvusService/Query", func(...) { ... return h.proxy.Query(...) })
  ```
  v2 对底层 expr 解析错误无本地映射、原样透传；65535 来自底层 merr UnexpectedError 族，无 1804 重编码代码。auditor：BDP-4 锚点仅覆盖 'REST 全 200' 形态，不覆盖错误码归类错位，SUPPORTS_DEFECT 由 B 主导定案。

## Impact
客户端错误处理逻辑（按 1804-family 分支做参数重试/提示）永远收不到预期错误码，65535 触发的是告警/重试/上报服务端 bug 的路径——错误分类体系失真放大运维噪音并误导排障方向。
