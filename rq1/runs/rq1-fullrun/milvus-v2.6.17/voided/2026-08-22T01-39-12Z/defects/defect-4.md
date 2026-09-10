# Defect 4: insert 动态字段名完全绕过命名规则校验（七类非法形态全接受）

## Metadata
- defect_id: TESTVDB-MILVUS-004 (boundary_fieldname_rules_018)
- type: Type1_IllegalSuccess
- param: 动态字段名（insert-time field name rules）
- novelty: NOVEL

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/insert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","data":[{"id":1,"1abc":"v"}]}'
# 观测: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[1]}}  (期望 1100)
```

## Expected vs Actual
- Expected: 契约断言字段名 ^[A-Za-z_][[A-Za-z0-9_]*$、长度<=255、insert-time 强制（dynamic fields included）。
- Actual: 七类非法形态——'1abc'（数字开头）、'a-b'、'a.b'、'$x'、'a b'、空串、256 长、NUL 字段名——全部 http=200 code:0 接受并持久化；合法对照 '_ok'/'x'/255 长 code:0 正常。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_field_name_rules_001
  - assertion: "field names: ^[A-Za-z_][A-Za-z0-9_]*$, length<=255, enforced at insert-time (dynamic fields included)"
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED
  - limitations.md 原文在页："A resource name must start with a letter or an underscore (_). | Field | 255 characters"
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_fieldname_rules_018.py
- Log: output_boundary_fieldname_rules_018.log
- 源码 internal/proxy/util.go L362-396 validateFieldName 完整实现规则，但 grep 全仓调用点仅 task.go:485（createCollectionTask）与 task.go:638（addField）——insert 路径零调用。REST 动态字段入口 httpserver/utils.go L666-690：动态循环唯一被拒的键名是字面 '$meta'，其余任意键直接进入 reallyData。verification_outcome: validation_absent（校验存在但不在该路径）。

## Impact
任意非法键名（含 NUL、空串、超长、特殊字符）可经动态字段写入并持久化，违反文档明示的命名规则；下游按名字过滤/查询这些字段的行为不可预期，且 '$meta' 特判说明作者考虑过键名问题却只挡了一个。
