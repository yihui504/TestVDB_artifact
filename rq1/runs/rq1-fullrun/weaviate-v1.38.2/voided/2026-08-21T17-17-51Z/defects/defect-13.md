# Defect 13: DELETE /batch/objects 五组缺失/null match 变体全 500（源码注释自证 422 兄弟通道漏改）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-13
- defect_id: vein_batchdelete_validation_channel_01
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断）
- Param: match
- Endpoint: DELETE /v1/batch/objects
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X DELETE "http://localhost:8080/v1/batch/objects" -H "Content-Type: application/json" -d '{"match":{}}'
# 五变体全 HTTP 500:
#   no_match / match_null        → "validate: empty match clause"
#   match_empty                  → "validate: empty match.class clause"
#   match_class_only / where_null → "validate: empty match.where clause"
# control nonexistent class: 422 {"error":[{"message":"validate: failed to get class: NoSuchClassVein"}]}
```

## Expected vs Actual
- Expected: 契约 weaviate_type_batch_delete_match_001："match.class AND match.where present, else 4xx"。
- Actual: 5 组 caller-input 变体全 500；同端点类不存在为 422——双通道分裂，500 把 caller 错误标记为 server fault。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_batch_delete_match_001（机械A CONFIRMED，引文一致）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — source_url openapi 回退（非直链），assertion 与 OpenAPI 契约方向一致，版本匹配 PASS
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_batchdelete_validation_channel_01.py
- Log: debate_logs/output_vein_batchdelete_validation_channel_01.log（log_pattern: "no_match: HTTP 500 msg=validate: empty match clause"，grade B，多脚本稳定触发）
- 源码 usecases/objects/batch_delete.go L126-136 三个裸 errors.New 分支 vs L140-146 GetCachedClass 失败路径 NewErrInvalidUserInput("failed to get class: %s")→422；handlers_batch_objects.go L183-197 错误映射 switch 无匹配 → default 500。源码 L140/L142 注释本身承认 caller-input 需 NewErrInvalidUserInput 否则 REST 映射 500，但 L128/132/136 三处漏改。

## Impact
同函数内校验通道分裂；所有 match 缺失形态 5xx 触发重试/误告警；源码注释自证为已知模式的漏改（PR#11497 同款遗留）。
