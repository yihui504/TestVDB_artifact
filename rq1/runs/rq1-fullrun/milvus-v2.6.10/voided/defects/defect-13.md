# Defect 13: Upsert accepts Int64 primary key as JSON string — permissive scalar cast violates row-type assertion

## Metadata
- Defect ID: boundary_r2b_upsert_rowface_03
- Type: Type1_IllegalSuccess（类型非法成功）
- Param / Trigger: upsert 行将 Int64 主键以字符串形式传入（`"id": "1"`）
- Novelty: NOVEL

## Reproduction (curl)
```
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/upsert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","data":[{"id":"1","vector":[...]}]}'   # id is Int64 in schema
# → HTTP 200, {"code":0, "data":{"upsertIds":[1], ...}}

# control: vector as string is rejected
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/upsert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","data":[{"id":1,"vector":"[0.1, ...]"}]}'
# → rejected with code 1804
```

## Expected vs Actual
- Expected: 行类型断言要求数值标量按声明类型传入；Int64 主键以字符串传入应被类型校验拒绝。
- Actual: upsert 接受字符串形式的 Int64 主键，返回 200/code:0 且 `upsertIds:[1]`；对照组 vector 以字符串传入被 1804 拒绝——同一请求内类型校验非对称，证明校验能力存在但对标量放行。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_entities_insert_001（引文一致，api_violates_assertion=true）
- Ring 2 (Document Reference 文档引用) doc_verification: VERIFIED_VIA_CHAIN_GROUNDING（check_chain_grounding: 引文一致且断言被违反）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/boundary_r2b_upsert_rowface_03.py
- Log: debate_logs/output_boundary_r2b_upsert_rowface_03.log
- 源码: `utils.go:442` — `json.Number` 显式 permissive cast，字符串标量被宽松转换为声明类型，源码定位。

## Verdict Aggregation
- A (contract): CONFIRMED — 机械 implied_verdict=DEFECT
- B (physical): CONFIRMED — objective_constraint_class: 类型恒真
- C (behavioral): CONFIRMED
- D (cognition): NO_SIGNAL
- Final: verdict_A=CONFIRMED（机械 implied_verdict=DEFECT）→ final=DEFECT

## Impact
主键类型约束可被字符串绕过，"1" 与 1 被视为同一行，弱类型客户端的错误数据形态被静默接纳而非在入口拒绝；vector/标量校验不对称使开发者对 REST 类型保证产生错误预期。R2b 纯盲注独立发现，2026-08-22。
