# Defect 10: DELETE /batch/objects match 整体缺失/五变体全 500（直击 verified 级契约）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-10
- defect_id: semantic_match_missing_01
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
# 五变体: match 缺失 / match:null / match:{} / 缺 where / 缺 class → 全部 500
# diagnosis_quality_score(match.where missing): 3/3 — 错误消息可定位字段，但通道错误
```

## Expected vs Actual
- Expected: verified 级契约 weaviate_type_batch_delete_match_001："match.class AND match.where present, else 4xx"（description 注明 GT issue #12041）。
- Actual: match 缺失/null/缺 where/缺 class/空对象 5 变体全部 HTTP 500；constraint 的 else 4xx 分支被系统性违反。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_type_batch_delete_match_001（evidence_tier=verified, source_verified=true，机械A CONFIRMED）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED — api_endpoints match required=true（go-struct entities/models/batch_delete.go#L39-L40），四层全 PASS
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/semantic_match_missing_01.py
- Log: debate_logs/output_semantic_match_missing_01.log（log_pattern: "[match_missing_entirely] status=500 body={\"error\":[{\"message\":\"validate: empty match clause\"}]}"，grade A，五行 status=500 原文）
- 源码 usecases/objects/batch_delete.go L122-137 三分支裸 errors.New ↔ 5 变体一一对应（match:null 与顶层缺失同走 match==nil；{} 走 len(Class)==0）；handlers_batch_objects.go L189-202 类型匹配失败 → 500。

## Impact
verified 级契约被系统性违反：所有 match 缺失形态触发 5xx；与 PR#11497 已修正的 class-not-found 422 构成同函数通道分裂，属 #12041 同族遗留。
