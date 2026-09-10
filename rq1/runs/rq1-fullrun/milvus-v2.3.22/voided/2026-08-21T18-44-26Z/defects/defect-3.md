# Defect 3: v2 create collection metricType 空串/None 绕过 7 值枚举校验（v1/v2 行为分裂）

## Metadata
- Defect ID: TESTVDB-MILVUS-3（boundary_metric_enum_002）
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Endpoint: POST /v2/vectordb/collections/create（对照 v1/vector/collections/create）
- Param: metricType
- Novelty: NOVEL（no_known_hits, HIGH, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t_metric","metricType":""}'
# 实测: HTTP 200 {"code":200,"data":{}}
```

## Expected vs Actual
- Expected: 契约 milvus_type_create_collection_001：metricType ∈ 7 值枚举 [L2, IP, COSINE, HAMMING, JACCARD, SUBSTRUCTURE, SUPERSTRUCTURE]；''/None 不在枚举内
- Actual: v2 metric='' 与 None 均 HTTP 200 + code 200 静默接受（回退 DefaultMetricType=COSINE）；对照 v1 metric='' → 65535 拒绝——同一非法值两面行为分裂；错误消息枚举只列 4 值（HnswMetrics），与契约 7 值错位

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_create_collection_001（assertion: `metricType in [L2, IP, COSINE, HAMMING, JACCARD, SUBSTRUCTURE, SUPERSTRUCTURE]`；本地源码 metric_type.go:18-39 逐字一致）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link/version/content/endpoint 全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_metric_enum_002.py
  - 主观测: `[v2 metric=''] http=200 body={"code":200,"data":{}}`
  - 对照: v2 None→200；v1 ''→65535 但 v1 None→200；'l2'/'cosine'/'euclidean'/'L3'/'HAMMING '/'L3;DROP'→65535；123→1801；控制集 IP 创建正常
- Log: debate_logs/output_boundary_metric_enum_002.log
- 源码: internal/distributed/proxy/httpserver/handler_v2.go:1117-1119
  ```go
  if len(httpReq.MetricType) == 0 {
      httpReq.MetricType = DefaultMetricType   // = metric.COSINE, constant.go:119
  }
  ```
  空值在进入 indexparamcheck 前被替换，永不触发枚举拒绝；checker 侧 constraints.go:42 METRICS 仅 3 值、:48 HnswMetrics 5 值（错误消息来源），与 metric_type.go 7 值枚举错位。auditor 备注：契约断言未含 '缺省即合法' 例外，A 定案不被推翻。

## Impact
用户传空串/None 会拿到未预期默认 COSINE 度量的集合且无任何告警（metric 选错直接决定检索正确性）；v1/v2 对 '' 分裂（拒/收）与 4/7 值错误消息错位进一步误导排障。
