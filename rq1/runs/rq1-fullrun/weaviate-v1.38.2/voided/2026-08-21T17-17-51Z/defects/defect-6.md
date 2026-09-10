# Defect 6: DELETE /batch/objects class 空串 500，与 nonexistent class 422 形成语义断层；未知字段 resources 静默 200

## Metadata
- Defect ID: TESTVDB-WEAVIATE-6
- defect_id: boundary_bd_match_resources_09
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断）
- Param: match.class（次观测：额外字段 resources）
- Endpoint: DELETE /batch/objects
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X DELETE "http://localhost:8080/v1/batch/objects" -H "Content-Type: application/json" \
  -d '{"match":{"class":"","where":{"operator":"Equal","path":["name"],"valueText":"x"}}}'
# → 500 {"error":[{"message":"validate: empty match.class clause"}]}
# 对照 nonexistent class: 422 "validate: failed to get class: NopeDoesNotExist"
# 额外字段 resources (string/array/null/empty): 200 静默忽略
```

## Expected vs Actual
- Expected: class 空串 = match.class 缺失 → 4xx（契约 else 4xx 分支）。
- Actual: class="" → 500；同类输入错误 nonexistent class → 422（PR#11497 已修正）；未知字段 resources 多种类型 → 200 静默忽略（次观测，Go json 默认忽略未知字段）。三通道（500/422/200）语义层级不一致。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_batch_delete_match_001（verified 级，机械A CONFIRMED）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — match.class required=true（go-struct entities/models/batch_delete.go#L132-L134），版本匹配 PASS
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/boundary_bd_match_resources_09.py
- Log: debate_logs/output_boundary_bd_match_resources_09.log（log_pattern: "class empty string: 500 {...empty match.class clause...}"，grade A）
- 源码 usecases/objects/batch_delete.go L127-147：class-empty 分支裸 errors.New("empty match.class clause")→500；紧随其后的 GetCachedClass 失败分支用 NewErrInvalidUserInput("failed to get class: %s")→422——同为调用方输入错误分属 4xx/5xx。resources：models.BatchDeleteMatch 无 Resources 定义，Go json 静默忽略 → 200。

## Impact
同函数内同类错误 422/500 分裂；class 空串触发 5xx 通道重试/告警误归因；未知字段静默吞掉使用户拼写错误的 filter 参数（如误把 where 内容放 resources）零反馈删除"成功"。
