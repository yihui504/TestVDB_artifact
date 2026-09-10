# Defect 4: Create 裸 warmup key 与 warmup.vectorIndex=ASYNC 双重静默通过（机械契约 CONFIRMED）

## Metadata
- defect_id: vein_warmup_bare_key_001
- type: Type4_StateLogicViolation
- param: properties.warmup
- novelty: NOVEL（gate: no_known_hits, confidence HIGH, endorsement=true）

## Reproduction (curl)
```bash
# B 裸 key
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"vn_warm1","schema":{...},"properties":[{"key":"warmup","value":"sync"}]}'
# C 非法 policy
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"vn_warm2","schema":{...},"properties":[{"key":"warmup.vectorIndex","value":"ASYNC"}]}'
```

## Expected vs Actual
- **Expected**: 契约 `milvus_type_collections_create_007`：`values restricted to disable|sync`——warmup.vectorIndex=ASYNC 应 1100（引文逐字一致，机械 A=CONFIRMED）。
- **Actual**: B 裸 key create `{"code":0,"data":{}}`；C ASYNC create `{"code":0,"data":{}}`。对照：A alter 裸 warmup（loaded 态）→ 104 拦截链存在；D field 级 warmup=BOGUS create → `{"code":1100,"message":"invalid warmup policy for field vec: ... must be 'disable' or 'sync'..."}`——field 级 create 有校验、collection 级 create 无。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_007（机械 A=CONFIRMED：id+quote 逐字一致，warmup.vectorIndex=ASYNC violates；裸 key 半由 create_008 显式记载为 KNOWN GAP pass-through）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（create_007/create_008 本地 clone 验证，common.go 可达，全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_warmup_bare_key_001.py（多脚本稳定触发，grade A）
- Log: output_vein_warmup_bare_key_001.log

源码 `internal/proxy/task.go:461-465`：
```go
if common.IsFieldWarmupKey(prop.GetKey()) {
    return merr.WrapErrParameterInvalidMsg("warmup key '%s' is only allowed at field level, use warmup.scalarField/... at collection level", ...)
}
if common.IsCollectionWarmupKey(prop.GetKey()) {
    if err := common.ValidateWarmupPolicy(prop.GetValue()); err != nil { ... }
```
`pkg/common/common.go:268`：`WarmupKey = "warmup"`。field 级 BOGUS 被 1100 拒对应 proxy/util.go:635/694/709（fillFieldInfo 提取 field TypeParams 时校验）；collection 级 warmup.vectorIndex=ASYNC 在 create 放行：ValidateWarmupPolicy 调用点均不在该路径。裸 'warmup' key 在 alter 先被 104 loaded 拦（A），create 完全无拦截（B）。

chain-auditor 终判：机械 A=CONFIRMED → **DEFECT**（C 与 create_007 矛盾为定案半；B 与 create_008 一致为契约已知 pass-through）。

## Impact
create/alter 与 collection级/field级双重校验不对称：非法 policy 与裸 key 在 create 静默通过，warmup 配置实际未按用户意图生效（静默丢弃），直到 alter 才暴露非法。
