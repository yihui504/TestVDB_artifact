# Defect 4: v1 search 默认返回 JSON 数字 id，违反契约"默认字符串、header 控制"

## Metadata
- Defect ID: TESTVDB-MILVUS-4（boundary_search_required_005）
- Type: Type2_PoorDiagnostics（契约-实现版本漂移类）
- Severity: Low（Type2 推断）
- Endpoint: POST /v1/vector/search（header: Accept-Type-Allow-Int64）
- Param: vector（id 编码默认值语义）
- Novelty: NOVEL（no_known_hits, HIGH, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v1/vector/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","vector":[0.1,0.2,...]}'
# 实测: HTTP 200 {"code":200,"data":[{"distance":0,"id":468539281520724797}]}  ← id 为 JSON 数字
```

## Expected vs Actual
- Expected: 契约 milvus_type_v1_search_001：Accept-Type-Allow-Int64 header 控制 int64 id 编码，默认返回字符串（防 JS Number 精度丢失）
- Actual: 默认（无 header）即返回原生 JSON 数字 int64；default 与显式 header 两条路径 id 类型完全相同（差异为零）

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_v1_search_001（assertion: `Accept-Type-Allow-Int64 header controls int64 id JSON encoding (number vs string)`，description 明示 default returns strings）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link PASS；version/content PARTIAL——契约描述与 v2.3.22 实现不符，即漂移本体）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_search_required_005.py
  - 主观测: `[id types] default=468539281520724797(int) header=468539281520724797(int)`
  - 对照: missing vector→1802（必填校验正确执行）；vector=string/number/nested/str-array→1801（类型校验严格）
- Log: debate_logs/output_boundary_search_required_005.log
- 源码: pkg/util/paramtable/http_param.go:40-47
  ```go
  p.AcceptTypeAllowInt64 = ParamItem{ Key: "proxy.http.acceptTypeAllowInt64",
      DefaultValue: "true", Version: "2.3.2", ... }
  ```
  service.go:196-203 中间件 ParseBool 失败时按服务端默认注入 header 'true' → handler_v1.go:915 allowJS=true → buildQueryResp 返回数字。契约文本未随 v2.3.2 默认值翻转更新。

## Impact
按契约默认预期字符串 id 的 JS/TS 客户端在 v2.3.2+ 上静默收到超出 Number.MAX_SAFE_INTEGER 精度的数字 id，精度丢失且无报错——静默数据损坏面；契约与实现漂移使该行为对用户不可发现。
