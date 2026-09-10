# Defect 5: DELETE /batch/objects 空 match/空对象/null 四退化变体全 500（同端点错类型 400、坏 operator 422）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-5
- defect_id: boundary_bd_match_empty_08
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断）
- Param: match
- Endpoint: DELETE /batch/objects
- Novelty: NOVEL
- Discovered: 2026-08-21T17:17-51Z session

## Reproduction (curl)
```bash
curl -s -X DELETE "http://localhost:8080/v1/batch/objects" -H "Content-Type: application/json" -d '{}'
# → 500 {"error":[{"message":"validate: empty match clause"}]}
curl ... -d '{"match":{}}'   # → 500 "empty match.class clause"
curl ... -d '{"match":null}' # → 500 "empty match clause"
curl ... -d '{"match":{"class":"C","where":null}}' # → 500 "empty match.where clause"
# 对照: match 为 string → 400; where 坏 operator → 422; where 空对象 → 422
```

## Expected vs Actual
- Expected: 退化 body（空对象/null/缺字段）属用户输入错误，应 4xx（契约 "match.class AND match.where present, else 4xx"）。
- Actual: 四退化变体全 500；同端点类型错误→400、where 解析错误→422、枚举校验→422，语义层级对照完备，仅 empty-match 族落 500。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_batch_delete_match_001（verified 级，机械A CONFIRMED）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — match/match.class/match.where 均 required=true（go-struct entities/models/batch_delete.go#L39-L40），版本匹配 PASS
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/boundary_bd_match_empty_08.py
- Log: debate_logs/output_boundary_bd_match_empty_08.log（log_pattern: "empty object: 500 {\"error\":[{\"message\":\"validate: empty match clause\"}]}"，grade A，四 DEFECT-SIGNAL 5xx 行 + 三条 4xx 对照行）
- 源码 usecases/objects/batch_delete.go L122-137 validateBatchDelete：match==nil / len(Class)==0 / Where==nil 三分支均裸 errors.New；handlers_batch_objects.go L194-202 三个裸 error 均不匹配 ErrInvalidUserInput → NewBatchObjectsDeleteInternalServerError(500)。

## Impact
所有 match 退化输入（空对象、null、缺字段）均触发 5xx——客户端 SDK 重试、监控误报 server 故障、API 网关熔断风险；与 400/422 通道的分裂使错误处理不可预测。
