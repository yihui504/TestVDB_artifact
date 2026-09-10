# Defect 6: createCollection quick/full 模式互斥参数同传被接受

## Metadata
- defect_id: TESTVDB-MILVUS-006 (boundary_datatype_enum_016)
- type: Type1_IllegalSuccess
- param: dimension + schema.fields（互斥参数）
- novelty: NOVEL

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","dimension":8,"schema":{"fields":[{"fieldName":"id","dataType":"Int64","isPrimaryKey":true},{"fieldName":"vec","dataType":"FloatVector","dimension":4}]}}'
# 观测: {"code":0,"data":{}}  (期望 1100)
```

## Expected vs Actual
- Expected: 契约断言 NOT(dimension set AND schema set) else code==1100（quick 模式与 full schema 模式冲突）。
- Actual: dimension:8 与 schema.fields 同传 → code:0 建表成功。dataType 枚举对照（'FloatVector32'/''/'int64'/null/missing 全部 1100 正确拒绝）完整。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_003
  - assertion: "NOT(dimension set AND schema set) else code==1100 (quick mode and full schema mode conflict -> code 1100 invalid parameter)"
  - 注：链引文含解释性后缀非契约原子串（quote_mismatch）→ A=NEUTRAL → GREY_ZONE；B 互斥参数类 LLM 兜底 CONFIRMED → final=DEFECT。
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_datatype_enum_016.py
- Log: output_boundary_datatype_enum_016.log
- 源码 internal/distributed/proxy/httpserver/handler_v2.go L1796-1998 createCollection：模式选择唯一依据 `if len(httpReq.Schema.Fields) == 0`——quick 分支只查 Dimension==0，full 分支全程不读 httpReq.Dimension；两分支均无互斥校验。verification_outcome: validation_absent。

## Impact
同时携带 dimension 与 schema 的矛盾请求静默成功，dimension 被无声忽略——用户以为 quick 参数生效，实际建表结构由 schema 决定，语义歧义且违反契约互斥断言。跨版本三现（#9/#11），与"从未实现"一致。
