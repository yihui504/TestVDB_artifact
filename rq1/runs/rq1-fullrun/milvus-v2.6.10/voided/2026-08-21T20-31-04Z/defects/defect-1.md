# Defect 1: collections/create — dimension 与 schema 同传冲突未拒绝（互斥断言失效）

## Metadata
- Defect ID: TESTVDB-MILVUS-1
- defect_id (script): boundary_quick_schema_conflict_003
- Type: Type1_IllegalSuccess
- Endpoint: POST /v2/vectordb/collections/create
- Param: dimension+schema（param_name: dimension）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"bnd_mode_conflict_1787345663","dimension":8,"schema":{"fields":[{"fieldName":"id","dataType":"Int64","isPrimary":true},{"fieldName":"vec","dataType":"FloatVector","dimension":8}]}}'
```

## Expected vs Actual
- Expected: code==1100（互斥断言：NOT(dimension set AND schema set)）
- Actual: `http=200 raw={"code":0,"data":{}}`；describe 回读集合真实存在，schema 模式字段生效

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_003
  - assertion: `NOT(dimension set AND schema set) else code==1100`；api_violates_assertion=true
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link_reachability PASS / version_match PASS / content_consistency PASS / endpoint_precision PASS；source_url 指向本地 clone handler_v2.go v2.6.10 checkout）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_quick_schema_conflict_003.py
  - grade B；`conflict payload -> http=200 {"code":0,"data":{}}`；claim_alignment=aligned；script_error=false
- Log: debate_logs/output_boundary_quick_schema_conflict_003.log

### 源码 文件:行号+摘录
- internal/distributed/proxy/httpserver/handler_v2.go L1719-1741（createCollection L1708-1910）：
  `if len(httpReq.Schema.Fields) == 0 { ... dimension quick-mode ... } else { /* full schema mode: 顶层 httpReq.Dimension 从未被读取或比对 */ }`
- verification_outcome: **validation_absent**——handler_v2.go 无 dimension+schema 冲突校验，contract 声称的 1100 校验在源码中不存在
- call chain: HTTP collections/create -> createCollection -> schema.fields==0 ? quick : full-schema(忽略 dimension) -> CreateCollection RPC；无 conflict check 函数

## Impact
客户端同时提供 dimension 与 schema 时，冲突输入被静默接受（code:0），实际生效 schema 模式、顶层 dimension 被丢弃。违反契约互斥断言，用户无任何告警即得到与请求意图不符的集合结构（quick/silent 参数吞并），属非法成功类缺陷。
