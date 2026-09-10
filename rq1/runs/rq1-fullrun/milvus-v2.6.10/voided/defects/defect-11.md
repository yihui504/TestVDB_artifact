# Defect 11: Insert accepts row-field names outside the queryable identifier grammar — data written but unqueryable by name

## Metadata
- Defect ID: boundary_r2b_rowfield_names_01
- Type: Type1_IllegalSuccess（写入侧非法成功）
- Param / Trigger: dynamic row-field keys `1abc` / `my-key` / `a b` / `$` / 中文（Plan.g4 Identifier 文法闭域之外）
- Novelty: NOVEL

## Reproduction (curl)
Insert rows whose dynamic field keys contain characters outside the identifier grammar, then issue a query naming those fields.

```
# 1. write (accepted)
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/insert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","data":[{"id":1,"vector":[...],"1abc":"v1","my-key":"v2","a b":"v3","$":"v4","字段":"v5"}]}'
# → HTTP 200, {"code":0, ...}

# 2. read back by name (fails)
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/query" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","filter":"id == 1","outputFields":["1abc"]}'
# → HTTP 200, {"code":65535, "message":"parse output field name failed"}
```

## Expected vs Actual
- Expected: either the insert is rejected (write-side validation consistent with read-side grammar), or the field is queryable by name after a successful write.
- Actual: insert returns 200/code:0 for all five out-of-grammar keys; subsequent query naming any of them fails with code 65535 `parse output field name failed`. Data is stored but can never be point-named for retrieval.

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（回滚版无行键命名断言）
- Ring 2 (Document Reference 文档引用) doc_verification: NOT_VERIFIED（R2b 盲注轮未做在线文档核验；无编造引用）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/boundary_r2b_rowfield_names_01.py
- Log: debate_logs/output_boundary_r2b_rowfield_names_01.log
- 源码: `internal/distributed/handlerenv`（REST handler）— 写侧 `utils.go:592` 无行键校验直接接受；读侧解析走 `Plan.g4:139` 的 `Identifier` 文法闭域，闭域之外的键在写入即不可点名检索。写侧接受集合 ⊋ 读侧可检索集合，读写不对称。

## Verdict Aggregation
- A (contract): NEUTRAL — constraint_absent（回滚契约无该域断言）
- B (physical): CONFIRMED — objective_constraint_class: 枚举闭集
- C (behavioral): CONFIRMED
- D (cognition): NO_SIGNAL
- Final: A=NEUTRAL(GAP)→灰区；B=CONFIRMED(LLM兜底)→DEFECT

## Impact
非法行键写入即不可读：用户经 REST 成功写入的动态字段永久无法通过 query/search 按名检索，静默数据不可用（write-accepted read-unreachable），无任何写入期告警。R2b 纯盲注独立发现，2026-08-22。
