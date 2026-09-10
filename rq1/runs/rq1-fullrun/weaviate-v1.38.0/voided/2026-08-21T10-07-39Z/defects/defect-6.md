# Defect 6: 空 match 子句的 DELETE /batch/objects 报 500 而非 422

## Metadata
- Defect ID: TESTVDB-WEAVIATE-006 (state_batch_partial_002)
- Type: Type3_RuntimeFailure（错误通道：客户端错误以 5xx 返回）
- Severity: High
- Endpoint: DELETE /v1/batch/objects
- Param: objects（body 无 match 子句）
- Novelty: NOVEL (gate, LOW precision, no_known_hits)
- Discovered: 2026-08-21

## Description
向 DELETE /batch/objects 发送 objects 数组 body（无 match/where 子句）——这是客户端校验错误——服务端返回 HTTP 500 `{"error":[{"message":"validate: empty match clause"}]}` 而非 422。同函数相邻失败路径（GetCachedClass 失败、where 解析失败）已被开发者显式归类为 ErrInvalidUserInput→422，唯 match==nil 分支仍是裸 errors.New→500，错误通道不一致。

## Reproduction (curl)
```bash
curl -s -w "\n%{http_code}" -X DELETE "http://localhost:8080/v1/batch/objects" \
  -H "Content-Type: application/json" \
  -d '{"objects":[{"id":"<uuid>","className":"Def6Class"}]}'
# 实际: 500 {"error":[{"message":"validate: empty match clause"}]}
# 期望: 422（客户端输入错误）
# 对照: 正确 match body → 200 {"deletionTimeUnixMilli":...}
```

## Expected vs Actual
- Expected: 422 UnprocessableEntity
- Actual: 500 InternalServerError

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `state_scripts/state_batch_partial_002.py`
- Log: `output_state_batch_partial_002.log`
- 源码: `usecases/objects/batch_delete.go` L124-137 `validateBatchDelete()` — `match == nil` 返回裸 `errors.New("empty match clause")`；对照同文件 L146/L153-156 维护者注释："classify it as ErrInvalidUserInput — otherwise the REST handler maps the parse/validation failure to a 500 instead of a 422"（证明同类错误通道已知且已被修过，此分支漏掉）
- Ring 1 (Contract Clause 契约条款): structured_contract 无 batch-delete 约束（state_constraints=[]）；violates 基于 REST 惯例 + 同函数分支不一致
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（domain_blocked；raw_knowledge.md L230-234 记录端点）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/state_batch_partial_002.json`

## Impact
500 触发客户端重试逻辑与运维告警（服务端故障误报），监控噪声 + 延迟重放必然再失败；错误分类体系被单个分支破坏。
