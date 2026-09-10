# Defect 1: POST /schema dynamicEfMin 字符串类型被静默 coerce 为 0，覆盖 documented default 100

## Metadata
- Defect ID: TESTVDB-WEAVIATE-1
- defect_id: boundary_bd_ef_types_05b
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断）
- Param: vectorIndexConfig.dynamicEfMin
- Endpoint: POST /schema
- Novelty: NOVEL
- Discovered: 2026-08-21T17:17:51Z session

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BdEfDrop2","vectorIndexConfig":{"dynamicEfMin":"100"}}'
# → HTTP 200（接受）
curl -s "http://localhost:8080/v1/schema/BdEfDrop2"
# → 读回 dynamicEfMin = 0（既非请求值也非默认 100）
```

## Expected vs Actual
- Expected: dynamicEfMin 为 int（契约断言 "dynamicEfMin is integer"）；字符串 '100' 应 422 拒绝；即使拒绝失败也不得落为非法值 0（default 100）。对照：float 100.7 被正确 422。
- Actual: 200 接受，读回 dynamicEfMin=0，无任何诊断；insert/nearVector 仍 200（检索语义退化——dynamic EF 失效，documented default 100 被覆盖）。同族 05 契约线：string/array/object/null 全 200→读回 0。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_create_collection_001 — "dynamicEfMin is integer"（机械A CONFIRMED，引文为契约原文）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — api_endpoints POST /schema dynamicEfMin type=int default_value=100（DefaultDynamicEFMin=100），source_url go-struct: entities/vectorindex/hnsw/config.go（clone 可达，版本匹配 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_bd_ef_types_05b.py
- Log: debate_logs/output_boundary_bd_ef_types_05b.log（log_pattern: "ATTACK dynamicEfMin='100' (string): 200 / read-back dynamicEfMin = 0"，grade B，多脚本稳定触发）
- 源码 entities/vectorindex/common/config.go L57-75 OptionalIntFromMap：
  ```go
  switch typed := value.(type) {
  case json.Number: asInt64, err = typed.Int64()
  case float64:     asInt64 = int64(typed)
  }  // 无 default：string 等类型落到此处 asInt64=0, err=nil
  setFn(int(asInt64))  // → setFn(0) 覆盖默认 100
  ```
  hnsw/config.go L91-93 setDefaults: DynamicEFMin=100 被显式键后的 setFn(0) 覆盖；validate()（L260-289）无 EF 下界检查 → 200 且读回 0。

## Impact
用户以字符串（常见于 YAML/env 配置序列化）传 dynamicEfMin 时集合创建"成功"，但 dynamic EF 语义静默退化为 0（默认应为 100），检索召回质量下降且无任何告警；类型校验漏洞同样适用于其他经 OptionalIntFromMap 解析的整型配置字段。
