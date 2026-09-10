# Defect 9: DELETE /batch/objects 响应 deletionTimeUnixMilli=-62135596800000（Go 零值哨兵泄漏到契约字段）

## Metadata
- Defect ID: TESTVDB-WEAVIATE-9
- defect_id: semantic_deletetime_04
- Type: Type2_PoorDiagnostics
- Severity: Low（Type2 推断）
- Param: deletionTimeUnixMilli
- Endpoint: DELETE /v1/batch/objects
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X DELETE "http://localhost:8080/v1/batch/objects" -H "Content-Type: application/json" \
  -d '{"match":{"class":"C","where":{"operator":"Equal","path":["name"],"valueText":"target"}}}'
# → HTTP 200，响应含 "deletionTimeUnixMilli":-62135596800000
# 该值 = Go time.Time{} 零值（0001-01-01T00:00:00Z）的 UnixMilli，非真实删除时刻
# 合理窗口示例: [1787333685070, 1787333685119]（2026 epoch 毫秒）
```

## Expected vs Actual
- Expected: 响应模型源码注释（= OpenAPI 描述）明示 "Timestamp of deletion in milliseconds since epoch UTC"（entities/models/batch_delete_response.go L35）。
- Actual: 调用方未传可选参数 deletionTimeUnixMilli 时，响应序列化零值 -62135596800000——删除本身成功（200），字段语义失真（内部哨兵外泄到契约字段）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: search_correctness — "deletionTimeUnixMilli 应为删除时刻的 epoch UTC 毫秒时间戳（模型注释原文）"
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED — entities/models/batch_delete_response.go L35（模型=OpenAPI 来源），link_reachability PASS
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_scripts/semantic_deletetime_04.py
- Log: debate_logs/output_semantic_deletetime_04.log（log_pattern: "deletionTimeUnixMilli=-62135596800000  plausible window=[1787333685070, 1787333685119]"，grade B，多脚本稳定触发）
- 源码 usecases/objects/batch_delete.go L94-96：
  ```go
  var deletionTime time.Time            // 未传时保持零值 0001-01-01
  if deletionTimeUnixMilli != nil { deletionTime = time.UnixMilli(*deletionTimeUnixMilli) }
  ```
  adapters/repos/db/batch.go L234-239 零值原样返回；handlers_batch_objects.go L236-244 无条件 input.DeletionTime.UnixMilli() 序列化 → 公开 API 输出 -62135596800000。

## Impact
客户端按字段语义消费删除时间戳（审计、TTL、增量同步）会得到 0001-01-01 哨兵值；SDK 类型系统不报错（合法 int64），错误静默扩散。修复常规做法：字符串哨兵或字段省略。
