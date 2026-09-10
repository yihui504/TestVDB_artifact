# Defect 7: DELETE /batch/objects 缺必填 match.where 返回 500（grade A，合法 match 200 对照）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-7
- defect_id: boundary_bd_match_where_01
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断）
- Param: match.where
- Endpoint: DELETE /batch/objects
- Novelty: NOVEL
- Discovered: 2026-08-21T17:17-51Z session

## Reproduction (curl)
```bash
curl -s -X DELETE "http://localhost:8080/v1/batch/objects" -H "Content-Type: application/json" \
  -d '{"match":{"class":"BoundaryBdWhere1"}}'
# → HTTP 500 {"error":[{"message":"validate: empty match.where clause"}]}
# CONTROL 合法 match（class+where Equal）→ 200，deletionTimeUnixMilli/dryRun/match 回显正常
```

## Expected vs Actual
- Expected: 缺 required 字段 match.where → 4xx（契约 "match.class AND match.where present, else 4xx"；GT issue #12041 通道）。
- Actual: HTTP 500；同端点合法 match 200（排除环境/类不存在因素），同 handler 内 ErrInvalidUserInput 正确映射 422。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_batch_delete_match_001（verified 级，evidence_tier=verified, source_verified=true；机械B HTTP语义恒真 CONFIRMED）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — match.where required=true，source_url go-struct: entities/models/batch_delete.go#L137-L139（clone 可达）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/boundary_bd_match_where_01.py
- Log: debate_logs/output_boundary_bd_match_where_01.log（log_pattern: "ATTACK match.where missing: 500 / Body: {\"error\":[{\"message\":\"validate: empty match.where clause\"}]}"，grade A）
- 源码 usecases/objects/batch_delete.go L122-137：match.Where==nil → 裸 errors.New("empty match.where clause")；handlers_batch_objects.go L189-202 错误映射：ErrInvalidUserInput→422 / ErrMultiTenancy→422 / Forbidden→403 / else→500。class-not-found 分支（PR#11497 注释 'classify other lookup failures as caller input (→ 422)'）已改用 NewErrInvalidUserInput，empty-match 三分支遗漏同款修正。

## Impact
缺 where 的批量删除请求触发 500：客户端误判为服务端故障重试、SLO/告警误归因；与 422 兄弟错误构成校验通道分裂，错误处理契约不可预测。
