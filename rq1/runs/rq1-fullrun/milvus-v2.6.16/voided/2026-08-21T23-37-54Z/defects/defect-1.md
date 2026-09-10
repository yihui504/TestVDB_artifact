# Defect 1: REST create 静默丢弃非法枚举 properties.query_mode（HTTP 200 code 0）

## Metadata
- Defect ID: TESTVDB-MILVUS-1 (boundary_querymode_01)
- Type: Type1_IllegalSuccess
- Param: query_mode
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: POST /v2/vectordb/collections/create
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"bnd_qm_01","schema":{...},"properties":{"query_mode":"bogus"}}'
```

## Expected vs Actual
- Expected（契约 create_009）: `properties/params.query_mode NOT IN {unset,'large_topk'}` => code 65535, message `invalid query_mode value "bogus", valid values: [large_topk]`
- Actual: `HTTP 200 {"code":0,"data":{}}` — 非法枚举值被静默接受为成功，无任何错误/警告

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_009（断言原文：`properties/params.query_mode NOT IN {unset, 'large_topk'} => code 65535 message "invalid query_mode value \"X\", valid values: [large_topk]" (live-confirmed v2.6.16: 'bogus' rejected)`；violates=true）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link/version/content/endpoint 全 PASS；源 local clone pkg/common/common.go v2.6.16 checkout，ValidateQueryMode @ common.go:513-526 产出与断言完全一致的消息；注：断言中 "live-confirmed bogus rejected" 来自 alter 路径实测，create 路径行为与之相悖——正是本缺陷）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_querymode_01.py（多脚本稳定触发：boundary_querymode_01 / boundary_querymode_03 (params 载体) / vein_query_mode_maturity_1 (T1)；CONTROL 同服务器 alter 同值返回 65535）
- Log: output_boundary_querymode_01.log（`Status: 200 / Raw: {"code":0,"data":{}} / VERDICT: DEFECT_FOUND`）
- 源码 文件:行号+摘录:
  - `internal/distributed/proxy/httpserver/request_v2.go:643-656` — CollectionReq struct **无 Properties 字段**（仅 DbName/CollectionName/Dimension/…/Params/Description）
  - `internal/distributed/proxy/httpserver/handler_v2.go:1786-1792` — req.Properties 初始化为空；`handler_v2.go:2019-2049` — params 转发白名单仅 ttlSeconds/partitionKeyIsolation/MmapEnabledKey/warmup.* 四键，query_mode 不在其中
  - `internal/proxy/task.go:448-451` — `if err := common.ValidateQueryMode(t.GetProperties()...); err != nil { return err }` — 校验存在但对此键在 REST create 路径不可达（dead code）
  - `pkg/common/common.go:516-517` — `if kv.Value != QueryModeLargeTopK { return fmt.Errorf("invalid query_mode value %q, ...") }`
  - 调用链: gin binding（properties 键静默丢弃）→ handler 白名单转发（排除 query_mode）→ proxy.CreateCollection → createCollectionTask.PreExecute 校验不可达 → code 0

## Impact
用户经 REST create 提交的非法 query_mode 被无声吞掉：客户端认为配置成功，实际属性从未生效；同一值走 alter 路径却被 65535 拒绝，形成跨端点校验不对称，破坏 API 可预期性并制造排障困难。最终判 DEFECT（机械B=CONFIRMED，HTTP 2xx+code 0 且契约声称 65535 拒绝）。
