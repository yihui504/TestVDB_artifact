# Defect 3: Create 路径 warmup.vectorIndex=ASYNC 被接受（违反枚举闭集 {disable,sync}，create/alter 校验不对称）

## Metadata
- defect_id: state_alter_props_loaded_003
- type: Type4_StateLogicViolation
- param: properties.warmup.vectorIndex
- novelty: NOVEL（gate: no_known_hits, confidence HIGH, endorsement=true）

## Reproduction (curl)
```bash
# create 路径（主观测）
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"c_warm","schema":{...},"properties":[{"key":"warmup.vectorIndex","value":"ASYNC"}]}'
# alter 路径对照（同值）
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/alter" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<released_collection>","properties":[{"key":"warmup.vectorIndex","value":"ASYNC"}]}'
```

## Expected vs Actual
- **Expected**: 契约 `milvus_type_collections_create_007`：warmup 值 NOT IN {disable, sync} => code==1100。
- **Actual**: create 返回 `{"code":0,"data":{}}`；alter 路径同值返回 `{"code":1100,"message":"invalid warmup value for key warmup.vectorIndex: invalid warmup policy: ASYNC, must be 'disable' or 'sync'..."}`；field 级 BOGUS 在 create 也被 1100 拒——双对照证明观测有效且校验存在但 create 集合级路径未调用。loaded 态 alter warmup → 104（符合 alter_properties_001）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_007（断言 `warmup.{...|vectorIndex} value NOT IN {disable, sync} => code==1100`，violates=true；机械 A 判 quote_mismatch 系引文意译，语义与契约原文一致）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（common.go ValidateWarmupPolicy 存在，全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/state_alter_props_loaded_003.py（多脚本稳定触发，grade A；vein_scripts/vein_warmup_bare_key_001.py C 行同观测）
- Log: output_state_alter_props_loaded_003.log

源码 `internal/proxy/task.go:459-468`（校验只在 alter 链生效，create 时不执行）：
```go
// Validate warmup policy for all warmup keys
if hasWarmupProp(t.GetProperties()...) {
    for _, prop := range t.GetProperties() {
        if common.IsCollectionWarmupKey(prop.GetKey()) {
            if err := common.ValidateWarmupPolicy(prop.GetValue()); err != nil {
                return merr.WrapErrParameterInvalidMsg("invalid warmup value for key %s: %s", ...)
```
`pkg/common/common.go:357-362`：ValidateWarmupPolicy 值域 {disable,sync}。全部 7 个调用点（task.go:466/1359/1632、util.go:635/694/709、index_type.go:108）均不在 create 的 collection-props 路径上 → ASYNC 在 create 放行。

## Impact
非法 warmup 策略名（如拼写 ASYNC）在 create 被静默接受，实际 warmup 行为未定义/未生效；用户在 alter 时才发现同值非法，需重建集合才能修正。
