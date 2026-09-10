# Defect 5: VarChar PK ids 接受任意数值类型静默 %v 转换（与 Int64 侧 1100 严格性不对称 + ids/data 距离不一致）

## Metadata
- defect_id: semantic_search_ids_mode_002
- type: Type4_StateLogicViolation（类型恒真违规：VarChar PK 数值 id 被 fmt %v 静默字符串化）
- param: ids
- novelty: NOVEL（gate: no_known_hits, confidence HIGH, endorsement=true）

## Reproduction (curl)
```bash
# VarChar PK 集合（pk 值 "42"）传数值 id
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<varchar_pk_collection>","ids":[42],"limit":2}'
# 对照 Int64 PK 集合传小数 id（1.5）→ 1100（契约 search_003）
```

## Expected vs Actual
- **Expected**: 与 Int64 侧对称的类型严格性——契约 `milvus_type_entities_search_003` 证明 Int64 pk + 小数 id 被强制 1100；VarChar pk + 数值 id 应同样拒绝类型混用。
- **Actual**: `{"code":0,"cost":0,"data":[{"distance":0,"pk":"42"}],"topks":[1]}`——数值 42 经 fmt %v 静默转 "42" 命中。附加主观测 A：ids 模式距离与 data 模式对同一 pk 不一致（pk=2: ids 0 vs data 1.1999999；pk=1 反向），原始行为 `topks:[2,2]` 每 id 独立分组交叉排列。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（无 VarChar 侧断言；参照 milvus_type_entities_search_003 'int64 pk AND id has fractional part (e.g. 1.5) => code==1100'——同 API 两侧类型严格性不对称的核心证据）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（search_002/search_003 本地 clone 验证一致但不覆盖 VarChar 数值 id 面；REST 文档未找到 ids 模式距离分组语义说明）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/semantic_search_ids_mode_002.py（多脚本稳定触发，grade A）
- Log: output_semantic_search_ids_mode_002.log

源码 `internal/distributed/proxy/httpserver/utils.go:219-231`（convertIDsToSchemapbIDs VarChar 分支）：
```go
case schemapb.DataType_VarChar:
    stringIDs := make([]string, 0, len(ids))
    for i, id := range ids {
        var stringID string
        switch v := id.(type) {
        case string:
            stringID = v
        case int64, int, float64:
            // Convert number to string
            stringID = fmt.Sprintf("%v", v)
```
对照 Int64 分支 utils.go:191-197：float64 带小数即报 'invalid int64 id ... has fractional part'。`internal/proxy/impl.go:3446-3464` handleIfSearchByPK：ids 非空转 PK 查询，每 id 独立查询向量组 → 距离分组现象来源。

chain-auditor 终判：LLM B=CONFIRMED（类型恒真）→ **DEFECT**。

## Impact
用户传数值 id 永远不获类型错误而是静默字符串化命中；Int64/VarChar 两侧不一致的行为契约使跨 schema 迁移代码隐坏。ids/data 模式对同一 pk 返回不同 distance 且无文档说明，加重语义混淆与结果可信度问题。
