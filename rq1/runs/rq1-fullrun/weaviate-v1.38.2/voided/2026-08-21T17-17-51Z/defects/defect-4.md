# Defect 4: DELETE /batch/objects 缺 match.class 返回 500 而非 4xx

## Metadata
- Defect ID: TESTVDB-WEAVIATE-4
- defect_id: boundary_bd_match_class_02
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断）
- Param: match.class
- Endpoint: DELETE /batch/objects
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X DELETE "http://localhost:8080/v1/batch/objects" \
  -H "Content-Type: application/json" \
  -d '{"match":{"where":{"operator":"Equal","path":["name"],"valueText":"target"}}}'
# → HTTP 500 {"error":[{"message":"validate: empty match.class clause"}]}
```

## Expected vs Actual
- Expected: 契约断言 "DELETE /batch/objects: match.class AND match.where present, else 4xx"；match.class required=true。
- Actual: HTTP 500（server fault 语义）+ "validate: empty match.class clause"；同函数 class-not-found 分支已用 NewErrInvalidUserInput→422（PR#11497），class-empty 分支遗留 500 通道。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_batch_delete_match_001（verified 级，机械A CONFIRMED，引文一致）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — api_endpoints match.class required=true，source_url go-struct: entities/models/batch_delete.go#L132-L134（clone 可达，版本匹配 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/boundary_bd_match_class_02.py
- Log: debate_logs/output_boundary_bd_match_class_02.log（log_pattern: "ATTACK match.class missing: 500 / Body: {\"error\":[{\"message\":\"validate: empty match.class clause\"}]}"，grade A，多脚本稳定触发）
- 源码 usecases/objects/batch_delete.go L127-130：
  ```go
  if len(match.Class) == 0 {
    return nil, 0, errors.New("empty match.class clause")  // 裸 error → 500
  }
  ```
  handlers_batch_objects.go L194-202：handler 仅映射 ErrInvalidUserInput(422)/ErrMultiTenancy(422)/Forbidden(403)，裸 errors.New 走 NewBatchObjectsDeleteInternalServerError→500。

## Impact
用户输入错误（缺 required 字段）被归为 server fault：触发客户端重试逻辑、误导告警/监控归因；同端点同函数内 422/500 通道分裂使错误处理契约不可预测。
