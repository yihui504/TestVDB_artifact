# Defect 12: Dynamic field cross-type drift within a column — upsert rewrites Int to String with zero rejection signal

## Metadata
- Defect ID: boundary_r2b_dyn_crosstype_02
- Type: Type4_StateLogicViolation（跨行/跨请求状态一致性）
- Param / Trigger: 同一动态字段 key 跨 6 种类型连续写入（Int/Float/Bool/String/Array/Object），及 upsert 将 Int 改写为 String
- Novelty: NOVEL

## Reproduction (curl)
```
# 1. write same dynamic key with 6 different types across requests — all accepted
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/insert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","data":[{"id":1,"vector":[...],"meta":42}]}'      # → 200 code:0
#   ... repeat with "meta": 3.14 / true / "s" / [1,2] / {"k":1}                    # → 200 code:0 each

# 2. upsert rewrites the field to a different type — accepted
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/upsert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","data":[{"id":1,"vector":[...],"meta":"now-a-string"}]}'
# → HTTP 200, {"code":0, ...}
```

## Expected vs Actual
- Expected: a schema-ful system either enforces per-key type stability across rows/requests, or documents and signals the reinterpretation; type-changing upsert at minimum produces a warning or a typed readback contract.
- Actual: same key across 6 types all 200/code:0 with zero rejection signal; upsert Int→String rewrite returns code:0 silently. No cross-row type comparison exists anywhere in the write path.

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（回滚版无动态字段跨行类型断言）
- Ring 2 (Document Reference 文档引用) doc_verification: NOT_VERIFIED（R2b 盲注轮无在线核验；by-design 抗辩存留记入疑义，供主进程人工复核）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/boundary_r2b_dyn_crosstype_02.py
- Log: debate_logs/output_boundary_r2b_dyn_crosstype_02.log
- 源码: `fillDynamicRow` 按行独立转换、无跨行/跨请求类型比对——源码确证零校验路径。

## Verdict Aggregation
- A (contract): NEUTRAL — GAP
- B (physical): CONFIRMED — objective_constraint_class: HTTP语义恒真
- C (behavioral): CONFIRMED
- D (cognition): NO_SIGNAL
- Final: A=NEUTRAL(GAP)→灰区；机械B=CONFIRMED→DEFECT（采信不改判）

## Impact
同一字段键的类型可被任意后续写入（含 upsert）静默改写，类型漂移无任何信号；下游按类型消费该字段的客户端会在无告警情况下读到改型后的数据，属状态一致性/静默数据改型问题。R2b 纯盲注独立发现，2026-08-22。
