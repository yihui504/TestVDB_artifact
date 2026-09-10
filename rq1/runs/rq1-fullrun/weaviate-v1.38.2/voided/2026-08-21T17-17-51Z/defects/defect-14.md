# Defect 14: PUT /schema/{class}/shards/{shard} status 枚举外值 'NOTASTATUS' 返回 500 而非 4xx

## Metadata
- Defect ID: TESTVDB-WEAVIATE-14
- defect_id: vein_shardstatus_500_invalidstatus_04
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断）
- Param: body.status
- Endpoint: PUT /v1/schema/{className}/shards/{shardName}
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X PUT "http://localhost:8080/v1/schema/{class}/shards/{shard}" \
  -H "Content-Type: application/json" -d '{"status":"NOTASTATUS"}'
# → HTTP 500 {"error":[{"message":"updating db: TYPE_UPDATE_SHARD_STATUS: NOTASTATUS: invalid storage status"}]}
# control status=READONLY: 200
```

## Expected vs Actual
- Expected: status 不在合法枚举集合（READY/READONLY/INDEXING/LOADING/LAZY_LOADING/SHUTDOWN）属 caller 输入错误，应 4xx。
- Actual: 枚举校验存在且检出（"invalid storage status"）但以 HTTP 500 返回；合法值 200——枚举外值被归 server fault。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: vein_validation_error_channel（vein 探索性约束——"请求体中的非法枚举值应返回 4xx 客户端错误"；机械B 枚举闭集 CONFIRMED，源码枚举即值域声称）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — status 合法值域 = 源码 entities/storagestate/status.go 枚举，与文档一致
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_shardstatus_500_invalidstatus_04.py
- Log: debate_logs/output_vein_shardstatus_500_invalidstatus_04.log（log_pattern: "invalid status: 500 {...NOTASTATUS: invalid storage status...}"，grade B，多脚本稳定触发）
- 源码 entities/storagestate/status.go L33-42：ValidateStatus switch default → ErrInvalidStatus（校验存在）；adapters/repos/db/shard_status.go L100-103 错误冒泡为普通 error；adapters/handlers/rest/handlers_schema.go L438-447 handler 错误 switch 仅区分 Forbidden，default → NewSchemaObjectsShardsUpdateInternalServerError()（500）。对照同文件 createTenants L474 有 UnprocessableEntity 分支。

## Impact
运维脚本传错 status 值触发 5xx 通道：自动化运维误判服务故障、触发告警/回滚；枚举校验已检出却选错错误类别，修复仅需 handler 增加 ErrInvalidUserInput→422 映射。
