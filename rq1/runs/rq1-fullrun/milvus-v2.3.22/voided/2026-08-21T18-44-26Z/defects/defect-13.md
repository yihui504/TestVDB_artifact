# Defect 13: 未知字段 filter 被静默吞成空结果（code 200），同参数类型错却报 65535——错误语义内部矛盾

## Metadata
- Defect ID: TESTVDB-MILVUS-13（vein_typo_filter_003）
- Type: Type2_PoorDiagnostics
- Severity: Low（Type2 推断）
- Endpoint: POST /v2/vectordb/entities/query + entities/search
- Param: filter
- Novelty: NOVEL（no_known_hits, HIGH, precision: LOW, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/query" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","filter":"nonexistent_field == 1","outputFields":["id"]}'
# 本链实测: HTTP 200 {"code":200,"data":[]}（query 与 search 均静默空结果）
# 对照: 类型不匹配 filter → HTTP 200 code 65535 显式报错
```

## Expected vs Actual
- Expected: 契约 milvus_behavioral_query_001：invalid filter（含未知字段引用的非法 boolean expr）→ 1804-family 报错
- Actual: 未知字段 filter 以 200+code:200+空 data 返回（用户 typo 产出误导性"无结果"）；同参数下类型错却 65535——两条分支同参数并存于同一 REST 面

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_behavioral_query_001（assertion: `invalid filter -> 1804-family error`；A=NEUTRAL 灰区，B 机械定案）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（契约 FilterExpr 条目未规定未知字段语义——沉默即缺口）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_typo_filter_003.py
  - log_pattern: `valid filter rows=5; type-mismatch code=65535; nonexistent-field query code=200, search code=200`
  - ⚠️ 摘要级 log；与 semantic_filter_expr_05（defect-7）bad_field 65535 的表面冲突由表达式形态/plan 路径分歧解释（auditor 认定两链合一覆盖矛盾两面，Type2 主张存活）
- Log: debate_logs/output_vein_typo_filter_003.log
- 源码: internal/distributed/proxy/httpserver/handler_v2.go:556/:896
  ```go
  Expr: httpReq.Filter          // query
  Dsl:  httpReq.Filter, DslType: commonpb.DslType_BoolExprV1   // search
  ```
  query 与 search 都把 filter 原文交底层 plan/parser，REST 层零字段名校验（validation_absent）；未知列在部分 plan 路径下被当作恒假谓词返回空集而非报错，与 parse error 路径（65535）同参数共存。

## Impact
字段名 typo 的查询静默返回空集——用户把"查错了字段"误判为"数据不存在"，是检索系统最典型的误导性无结果；同参数错误有时报错有时吞掉，使客户端无法依赖统一错误语义。
