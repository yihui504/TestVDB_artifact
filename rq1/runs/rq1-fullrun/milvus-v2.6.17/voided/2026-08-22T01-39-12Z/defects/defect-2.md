# Defect 2: fieldOps 对主键字段与不存在字段的 REPLACE 操作旁路全部结构校验

## Metadata
- defect_id: TESTVDB-MILVUS-002 (boundary_fieldops_pk_structural_005)
- type: Type1_IllegalSuccess
- param: fieldOps[].fieldName (op on pk field / field absent from schema)
- novelty: NOVEL

## Reproduction (curl)
```bash
# op on pk field
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/upsert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","data":{"id":99,"id":1},"fieldOps":[{"fieldName":"id","op":"REPLACE"}]}'
# 观测: {"code":0,"cost":0,"data":{"upsertCount":1,"upsertIds":[1]}}  (期望 1100)
# field absent from schema: fieldName:"ghost" 同样 code:0 被当动态字段接受
```

## Expected vs Actual
- Expected: 契约断言 op on primary-key field 与 field absent from schema 属结构违规 → code 1100。
- Actual: 两者均 code:0 且行被修改。empty fieldName / duplicate ops 对照正确 1100。另有次观测：'row not in data' 被 1100 拒绝后发现 title 已被改为 'x'（state leak 子 claim 因果归属存疑，builder 自标，建议人工复核）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_state_entities_upsert_fieldops_001
  - assertion: "any(fieldOps structural violation) => code 1100, no rows modified"
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_fieldops_pk_structural_005.py
- Log: output_boundary_fieldops_pk_structural_005.log
- 源码 internal/proxy/task_upsert_partial_op.go L132-148：`if op == schemapb.FieldPartialUpdateOp_REPLACE { // Accept silently — no further validation needed. continue }` —— PK 检查与 findFieldSchemaByName 均在 REPLACE continue 之后，REST 的 op:"REPLACE"/缺省都映射 REPLACE，故 pk-field op 与 absent-field op 直接旁路全部结构校验。verification_outcome: by_design_in_source（源码注释显式 by-design 抗辩；按聚合规则 E2 不改 verdict，记 rationale 供人工复核）。

## Impact
主键字段可被 fieldOps 声明性改写、不存在字段被静默当动态字段接受，均违背契约结构违规条款。by-design 抗辩（源码注释）与契约条文存在分歧，需上游确认意图；实际后果是非法 upsert 结构无差别落盘。
