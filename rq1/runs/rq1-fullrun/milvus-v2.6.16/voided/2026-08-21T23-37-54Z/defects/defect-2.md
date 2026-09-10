# Defect 2: 合法值 large_topk 于 create 被静默丢弃——属性无效、下游误诊

## Metadata
- Defect ID: TESTVDB-MILVUS-2 (boundary_querymode_02)
- Type: Type1_IllegalSuccess（含 Type2_PoorDiagnostics 次生面）
- Param: query_mode
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: POST /v2/vectordb/collections/create（耦合 GET entities+search）
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
# create 携带合法属性
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"c1","schema":{...},"properties":{"query_mode":"large_topk"}}'
# → 200 {"code":0,"data":{}}
# 随后 search limit=100000
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -d '{"collectionName":"c1","data":[...],"limit":100000}'
# → 200 {"code":65535,"message":"topk [100000] is invalid, it should be in range [1, 16384], but got 100000"}
```

## Expected vs Actual
- Expected（契约 create_009 + range_entities_search_003 耦合）: create 设置 query_mode=large_topk 后，TopK 上限升至 1000000（1<=limit<=1000000）
- Actual: create 返回 code 0 但 describe 读回无该属性（仅 timezone），search limit=100000 仍被 16384 上限拒绝；错误消息指向 topk 而非被丢弃的属性（误诊）；alter 路径同操作成功（control）

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_009（coupled: milvus_range_entities_search_003 `query_mode==large_topk: 1 <= limit <= 1000000 ... live v2.6.16 confirmed`；create 路径有效性声明被违反，violates=true）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（quota_param.go LargeTopKLimit/LargeMaxQueryResultWindow=1000000 + common.go 本地 clone v2.6.16，全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_querymode_02.py（多脚本稳定触发：boundary_querymode_02 + semantic_large_topk_1 独立复现含 describe 读回）
- Log: output_boundary_querymode_02.log（create code 0 → search 65535 `[1, 16384]` → VERDICT: DEFECT_FOUND）
- 源码 文件:行号+摘录:
  - `internal/proxy/task_search.go:171` — `t.largeTopKEnabled = collectionInfo.queryMode == common.QueryModeLargeTopK` — 升窗依赖**持久化**的 collection 属性
  - `internal/distributed/proxy/httpserver/handler_v2.go:2019-2049` — 不转发 query_mode → 属性永不持久化 → largeTopKEnabled=false → 16384 cap
  - `request_v2.go:643-656` — CollectionReq 无 Properties 字段（与 defect-1 同根因）
  - 调用链: create properties 丢弃 → 无持久化属性 → search largeTopKEnabled=false → quota 16384 → limit=100000 报 65535

## Impact
用户按文档在 create 时开启 large_topk，看似成功（code 0）实则完全未生效，大 limit 查询失败且错误消息误导（指向 topk 而非配置丢失）；需改走 alter 路径才能恢复预期行为。最终判 DEFECT（机械B=CONFIRMED）。
