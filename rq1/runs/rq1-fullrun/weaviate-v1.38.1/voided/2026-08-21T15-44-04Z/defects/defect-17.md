# Defect 17: properties[].indexNullState 错位键 200 静默丢弃，IsNull 运行时报错

## Metadata
- defect_id: vein_schema_silent_drop_nested_4
- type: Type1_IllegalSuccess
- param: properties[].indexNullState
- novelty: NOVEL
- Endpoint: POST /schema (properties[].indexNullState 错位键)
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE LLM 兜底 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
# 错位：indexNullState 放在属性级（正确定位是类级 invertedIndexConfig）
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"VeinNull","vectorizer":"none","properties":[{"name":"num","dataType":["int"],"indexNullState":true}]}'
# -> HTTP 200（无警告）
# readback: property 无 indexNullState 字段；class 级 indexNullState=None（null-state 索引未生效）
# 运行时 IsNull 查询：
#   -> 200 + errors [{"message": "shard JwA4H67fePEZ: retrieve doc IDs from se..."}]
# 对照：类级 invertedIndexConfig.indexNullState=true 的同类 IsNull 查询 -> 200 count=1（正常）
```

## Expected vs Actual
- Expected: 错位键应 422 指出 indexNullState 不属于 properties[]（openapi 定义它属于类级 InvertedIndexConfig）。
- Actual: 200 无警告 + 属性级字段静默丢弃 + 类级 null-state 未激活 + 运行时 IsNull 查询报错——错误延迟到查询期，且报错文案（"Add indexNullState: true to the invertedIndexConfig"）与用户已发送过的配置意图形成误导闭环。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（vein_silent_substitution；实际引用 openapi-specs/schema.json:1122-1125 InvertedIndexConfig.indexNullState 类级定义 "Index each object with the null state (default: `false`)"）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link/version/content/endpoint 全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_schema_silent_drop_nested_4.py
- Log: vein_scripts/output_vein_schema_silent_drop_nested_4.log（create 200 + readback 无字段 + IsNull 运行时报错 + 类级对照 count=1）
- 源码 文件:行号+摘录: entities/models/inverted_index_config.go:40 `IndexNullState bool \`json:"indexNullState,omitempty"\``（仅类级）；entities/models/property.go:33-73 Property struct json tags 无 indexNullState → Go 解码静默丢弃属性级错位键；adapters/repos/db/inverted/prop_value_pairs.go:349-350 `if pv.operator == filters.OperatorIsNull && !pv.Class.InvertedIndexConfig.IndexNullState { return nil, errors.Errorf("Nullstate must be indexed to be filterable! Add \`indexNullState: true\` to the invertedIndexConfig") }`——运行时守卫报错点。同类错位场景（virtualPerPhysical 更新）有显式报错，此处沉默非一致设计。

## Impact
用户按直觉把 indexNullState 放在属性级（常见配置错误），得到创建成功但 null 过滤功能完全不可用，且要到首次查询才暴露；报错文案暗示用户"忘了配"，实际是配置被静默丢弃。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true; precision LOW)
