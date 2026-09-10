# Defect 7: Int32 字段接受字符串 default_value='77'，默认值从未生效且 insert 期报 1804

## Metadata
- defect_id: semantic_default_value_fill_003
- type: Type4_StateLogicViolation（类型恒真违规：Int32 字段 default_value 字符串 '77' 被 create 接受；混合 Type2 误导诊断面）
- param: defaultValue
- novelty: NOVEL（gate: no_known_hits, confidence HIGH, endorsement=true）

## Reproduction (curl)
```bash
# 1. create：Int32 字段 default_value 传字符串
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"c_def","schema":{"fields":[{"fieldName":"score","dataType":"Int32","isPrimary":false,"defaultValue":"77"},...]}}'
# 2. insert 省略该字段 → 触发默认值填充路径
```

## Expected vs Actual
- **Expected**: create 侧 convertDefaultValue 对 Int32 的字符串形态应拒绝（源码行为约定 utils.go:1755-1762 'cannot use "%v"(type: %T) as int default value'）。
- **Actual**: `create: {"code":0,"data":{}}` → `insert 省略字段: {"code":1804,"message":"fail to deal the insert data, error: unable to cast \"\" of type string to int32: invalid parameter[expected=Int32][actual=]"}`——默认值从未生效，驻留形态是空字符串。对照：数值形态 defaultValue create code:0，insert 省略后 query 返回 score:77（默认值正常生效）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（契约 33 constraints 无 defaultValue 类型断言；参照源码 convertDefaultValue 的类型拒绝路径）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（无契约断言；utils.go/handler_v2.go 本地 clone 可达）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/semantic_default_value_fill_003.py
- Log: output_semantic_default_value_fill_003.log

源码 `internal/distributed/proxy/httpserver/utils.go:1741-1762`：
```go
func convertDefaultValue(value interface{}, dataType schemapb.DataType) (*schemapb.ValueField, error) {
    if value == nil { return nil, nil }
    switch dataType {
    ...
    case schemapb.DataType_Int8, schemapb.DataType_Int16, schemapb.DataType_Int32:
        // all passed number is float64 type
        v, ok := value.(float64)
        if !ok {
            return nil, merr.WrapErrParameterInvalidMsg(`cannot use ""%v"(type: %T) as int default value`, value, value)
        }
```
`handler_v2.go:1932-1937`（create 调用点，err → 1100）；`utils.go:939`（insert 侧缺省 continue）。调用链分析：字符串 '77' 对 Int32 本应走 !ok 分支，但 log 显示 code:0——create 期类型校验被绕过（宽松序列化路径），默认值以坏形态（空串）驻留 schema，insert 期 proxy cast 拿到 "" → 1804。

chain-auditor 终判：LLM B=CONFIRMED（类型恒真）→ **DEFECT**。

## Impact
双重伤害：create 成功给出虚假安全感；真实失败延迟到 insert 且错误信息指向 insert（'unable to cast "" to int32'）而非 create 的坏默认值——误导用户排查方向（Type2 诊断面）。默认值静默不生效意味着省略该字段的行永远无法写入。
