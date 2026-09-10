# Defect 6: 数值/浮点 id 对 VarChar PK 全类型静默命中（42.0 → '42' 证明 fmt %v 宽松格式化）

## Metadata
- defect_id: vein_ids_conversion_chain_002
- type: Type4_StateLogicViolation（类型恒真违规）
- param: ids
- novelty: NOVEL（gate: no_known_hits, confidence HIGH, endorsement=true）

## Reproduction (curl)
```bash
# VarChar PK 集合（pk 值 "42"、"42.5"）
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<varchar_pk_collection>","ids":[42.0],"limit":2}'
```

## Expected vs Actual
- **Expected**: 数值类型 id 对字符串 PK 应类型拒绝（与 Int64 侧小数 id 1100 的严格性对称）。
- **Actual**: 全部 200+code:0 命中：B 数值 42 → 命中 pk "42"；C 42.5 → 命中 pk "42.5"；**E 42.0 → 命中 pk "42"（非 "42.0"）**——决定性证据：Go fmt %v 对 42.0 输出 "42"，证明是宽松 %v 格式化而非 strconv 精确转换。A 案 Int64 pk ids=['42'] 字符串反向 coercion 属 documented 行为对照。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（契约无 VarChar pk 数值 id 断言；参照 milvus_type_entities_search_003 'int64 pk AND id has fractional part => code==1100'——Int64 严格/VarChar 无对称约束）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（search_003 仅覆盖 Int64 小数；同族契约环缺失）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_ids_conversion_chain_002.py（多脚本稳定触发，grade A）
- Log: output_vein_ids_conversion_chain_002.log

源码 `internal/distributed/proxy/httpserver/utils.go:222-228`（VarChar 分支）：
```go
switch v := id.(type) {
case string:
    stringID = v
case int64, int, float64:
    // Convert number to string
    stringID = fmt.Sprintf("%v", v)
```
`internal/proxy/impl.go:3446-3460` handleIfSearchByPK：ids → NewIDsChecker → PK 查询。调用链：JSON ids → convertIDsToSchemapbIDs %v 格式化 → PK 查询。E 案（42.0→'42'）排除 strconv.FormatFloat 固定格式解释。

chain-auditor 终判：LLM B=CONFIRMED（类型恒真：42/42.5/42.0 全类型静默命中）→ **DEFECT**。与 semantic_search_ids_mode_002 同根因、独立取证。

## Impact
数值 id 与字符串 PK 之间的隐式宽松转换面：用户错误类型的请求静默成功且结果依赖 %v 格式化细节（42.0 与 42 不可区分），无任何错误提示；文档化程度未证实。
