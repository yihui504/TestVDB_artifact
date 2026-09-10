# Defect 1: v2 create collection 接受契约枚举外的 idType='int64'（大小写容错面内部不一致）

## Metadata
- Defect ID: TESTVDB-MILVUS-1（boundary_idtype_datatype_003）
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Endpoint: POST /v2/vectordb/collections/create
- Param: idType
- Novelty: NOVEL（match_type: no_known_hits, confidence: HIGH, endorsement: true）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t_idtype","schema":{"fields":[{"fieldName":"id","dataType":"Int64","isPrimary":true,"idType":"int64"}]}}'
# 实测: HTTP 200 {"code":200,"data":{}}
```

## Expected vs Actual
- Expected: 契约断言 `idType in [Int64, VarChar]`，'int64' 不在枚举内应被业务码拒绝（错误消息自身也宣称 "idType can only be [Int64, VarChar]"）
- Actual: HTTP 200 + code 200 静默接受。容错面内部不一致：'int64' 与 'VarChar'/'Varchar' 被归一化接受，'INT64'/'varchar'/'Int32' 却走 default 报 code 1100

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_v2_create_collection_001（assertion: `idType in [Int64, VarChar]`；源码本地核对一致 handler_v2.go:951-963；官方测试 handler_v2_test.go:512 同样只期望 unknown 被拒）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link PASS / version PASS / content PASS / endpoint PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_idtype_datatype_003.py
  - 主观测 log_pattern: `[idType='int64'] http=200 body={"code":200,"data":{}}`
  - 对照: 'varchar'→1100, 'INT64'→1100, 'Int32'→1100, ''→200, None→200, 123→1801, dataType='int64'→1100（dataType 侧大小写严格，与 idType 侧不一致）
- Log: debate_logs/output_boundary_idtype_datatype_003.log
- 源码: internal/distributed/proxy/httpserver/handler_v2.go:951-963
  ```go
  switch httpReq.IDType {
  case "VarChar", "Varchar": ...
  case "", "Int64", "int64": httpReq.IDType = "Int64"
  default: err := merr.WrapErrParameterInvalid("Int64, Varchar", httpReq.IDType,
      "idType can only be [Int64, VarChar], default: Int64")
  ```
  request_v2.go:261 IDType 无 binding 枚举校验。chain-auditor 备注：源码归一化属 by-design 容错（E2 规则下不推翻 A 定案），建议人工复核。

## Impact
用户按错误消息宣称的枚举传 'int64' 会静默成功，传 'INT64' 却被拒——同一参数的容错规则不可预测，且契约/错误消息/实现三方枚举漂移，误导 schema 设计与自动化客户端生成。
