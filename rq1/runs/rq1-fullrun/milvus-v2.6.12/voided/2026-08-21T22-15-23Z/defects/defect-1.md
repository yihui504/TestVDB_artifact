# Defect 1: Search 顶层 metricType 对 L2 集合任意值静默接受（accept-and-ignore）

## Metadata
- defect_id: boundary_s05_search_metric_mismatch
- type: Type1_IllegalSuccess（混合 Type2 诊断缺失：同参数面 searchParams 路径以 65535 拒绝）
- param: metric_type
- novelty: NOVEL（gate: no_known_hits, confidence HIGH, endorsement=true）

## Reproduction (curl)
对 L2 度量集合执行 search，请求顶层携带冲突 `metricType`：

```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<L2_collection>","data":[[0.1,...x8]],"limit":1,"metricType":"IP"}'
# 同法复现 COSINE / BOGUS / 42 / "l2"
```

## Expected vs Actual
- **Expected**: 与 searchParams.metric_type 路径同参数面冲突一致——拒绝（HTTP 200 + code 65535 "metric type not match: expected=L2, actual=IP"）。
- **Actual**: 全部 `status=200 ok=True | {"code":0,...,"topks":[1]}`，结果与不传 metricType 的 baseline **逐字节相同**（`{"distance":0,"id":1}`）——值被完全忽略。整数 `metricType:42` 也未触发 1801 JSON 错误（字段为 Go string，gin/json 宽松解码）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（契约 33 constraints 无 metricType 冲突断言；语义锚点为源码 `internal/util/segcore/plan.go:109` 的 metric type not match 严格比对）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（link/version PARTIAL；无 REST 文档页断言，语义仅存在于源码 segcore/plan.go:109）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_s05_search_metric_mismatch.py
- Log: output_boundary_s05_search_metric_mismatch.log

源码 `internal/util/segcore/plan.go:107-113`：
```go
metricTypeInPlan := plan.GetMetricType()
if len(metricType) != 0 && metricType != metricTypeInPlan {
    plan.delete()
    return nil, merr.WrapErrParameterInvalid(metricTypeInPlan, metricType, "metric type not match")
}
```
`internal/distributed/proxy/httpserver/request_v2.go:637` 附近：`MetricType string \`json:"metricType"\``（SearchReqV2 顶层字段）。搜索计划路径（searchParams.metric_type → segcore 严格比对）与顶层字段消费路径分叉——顶层字段疑似未被搜索计划消费，任何值 code:0。

chain-auditor 终判：机械 B=CONFIRMED（HTTP 语义恒真）→ **DEFECT**。

## Impact
用户以为指定了 IP/COSINE 度量实则被忽略，返回的是 L2 结果——错误的相似度语义且零告警。同一 API 两种传参位置一种被拒一种静默通过，破坏参数一致性预期并造成调试误导（Type2 面）。
