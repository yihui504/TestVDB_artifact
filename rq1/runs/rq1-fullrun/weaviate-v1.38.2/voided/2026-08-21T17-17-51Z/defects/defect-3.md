# Defect 3: POST /schema 接受 efMin=500 > efMax=100 倒置对并原样持久化

## Metadata
- Defect ID: TESTVDB-WEAVIATE-3
- defect_id: boundary_bd_hnsw_pair_04
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Param: vectorIndexConfig.dynamicEfMin（成对约束 dynamicEfMin <= dynamicEfMax）
- Endpoint: POST /schema
- Novelty: NOVEL
- Discovered: 2026-08-21T17:17:51Z session

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"...","vectorIndexConfig":{"dynamicEfMin":500,"dynamicEfMax":100}}'
# → HTTP 200
curl -s "http://localhost:8080/v1/schema/{class}"
# → 读回 efMin=500, efMax=100（倒置对原样持久化）
```

## Expected vs Actual
- Expected: 契约断言 "dynamicEfMin <= dynamicEfMax"（paired constraint from go source, default 100/500）；倒置对应 422 拒绝。
- Actual: 200 接受，GET /schema/{class} read-back 原样返回倒置值——非临时接受而是持久化，无任何错误/警告体。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_range_create_collection_001 — "dynamicEfMin <= dynamicEfMax"
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — api_endpoints POST /schema dynamicEfMin(int, default 100)/dynamicEfMax(int, default 500)，source_url go-struct: entities/vectorindex/hnsw/config.go（clone 可达）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/boundary_bd_hnsw_pair_04.py
- Log: debate_logs/output_boundary_bd_hnsw_pair_04.log（log_pattern: "ATTACK efMin=500 > efMax=100: 200 / read-back efMin=500 efMax=100"，grade B，互斥参数类）
- 源码 entities/vectorindex/hnsw/config.go L183-192：dynamicEfMax/dynamicEfMin 经 OptionalIntFromMap 分别独立赋值，无交叉比较；L260-289 UserConfig.validate() 仅校验 maxConnections(上下界)/efConstruction(下界)/filterStrategy——无任何 DynamicEFMin<=DynamicEFMax 检查 → 倒置对原样入库。

## Impact
HNSW dynamic EF 的 min/max 倒置配置静默生效，运行时 ef 窗口语义未定义（min>max），检索召回/延迟行为不可预测；配置错误无反馈，排障成本高。
