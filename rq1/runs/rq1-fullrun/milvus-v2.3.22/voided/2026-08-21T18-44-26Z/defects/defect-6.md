# Defect 6: v2 entities/search params null 值绕过 map<string,float64> 类型约束并被静默丢弃

## Metadata
- Defect ID: TESTVDB-MILVUS-6（boundary_v2_params_types_007）
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Endpoint: POST /v2/vectordb/entities/search
- Param: params
- Novelty: NOVEL（no_known_hits, HIGH, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","data":[[0.1,0.2,...]],"params":{"level":null}}'
# 实测: HTTP 200 {"code":200,"data":[]}
```

## Expected vs Actual
- Expected: 契约 milvus_type_v2_search_001：params is map<string, float64>, numeric values only；null 不是 numeric 值应被拒绝
- Actual: null 值以 HTTP 200 + code 200 通过且被静默丢弃；对照 string/array/object/bool 全部 1801 拒绝——唯一放行 null

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_v2_search_001（assertion: `params is map<string, float64> numeric values only`；源码 request_v2.go:120 逐字一致）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link/version/content/endpoint 全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_v2_params_types_007.py
  - 主观测: `[params={'level': None}] http=200 body={"code":200,"data":[]}`
  - 对照: 'not-a-number-str'→1801, [1,2]→1801, {'nested':1}→1801, True→1801, 数值控制→200
- Log: debate_logs/output_boundary_v2_params_types_007.log
- 源码: internal/distributed/proxy/httpserver/request_v2.go:120
  ```go
  Params map[string]float64 `json:"params"`
  ```
  Go encoding/json 特性：JSON null 解码到 float64 不报错（保持零值），其他类型报 unmarshal 错；handler_v2.go:840-846 generateSearchParams 仅处理 radius/range_filter 两键，其他键（如 level）完全忽略、无值域校验。verification_outcome: validation_absent。

## Impact
客户端把 search 参数误传为 null（如序列化 bug）会得到"成功但参数未生效"的静默结果——检索行为与请求意图不符且无任何诊断；类型校验矩阵的 null 空洞使 API 契约与实现不一致。
