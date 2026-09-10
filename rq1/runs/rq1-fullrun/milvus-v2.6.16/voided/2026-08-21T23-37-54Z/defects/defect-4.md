# Defect 4: create 时 large_topk 属性未持久化，search limit=20000 仍受 16384 cap

## Metadata
- Defect ID: TESTVDB-MILVUS-4 (semantic_large_topk_1)
- Type: Type1_IllegalSuccess
- Param: properties.query_mode
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: collections+create / entities+search
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
curl -s -X POST ".../v2/vectordb/collections/create" -d '{"collectionName":"sm_ltk_large","schema":{...},"properties":{"query_mode":"large_topk"}}'
# → 200 {"code":0,"data":{}}
curl -s -X POST ".../v2/vectordb/collections/describe" -d '{"collectionName":"sm_ltk_large"}'
# → properties 仅 [{"key":"timezone","value":"UTC"}] — query_mode 缺失（persisted: False）
curl -s -X POST ".../v2/vectordb/entities/search" -d '{"collectionName":"sm_ltk_large","data":[...],"limit":20000}'
# → 200 {"code":65535,"message":"topk [20000] is invalid, it should be in range [1, 16384], but got 20000"}
```

## Expected vs Actual
- Expected（range_entities_search_003 + create_009）: query_mode==large_topk 时 1<=limit<=1000000 且 1<=limit+offset<=1000000
- Actual: create 携带合法 large_topk 后 search limit=20000 仍报 65535 [1,16384]；CONTROL alter 路径同 collection 改设 large_topk 后 limit=20000 code 0，且 alter 路径双边界（offset+limit==1000000 通过 / ==1000001 拒绝）与契约精确一致

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_range_entities_search_003（coupled create_009；create 载体前置条件未兑现，violates=true）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（quota_param.go v2.6.14+ 存在于 2.6.16 clone；全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: semantic_scripts/semantic_large_topk_1.py（多脚本稳定触发：semantic_large_topk_1 + boundary_querymode_02 独立复现；含 describe 读回 + 双边界 + alter control 三角验证）
- Log: output_semantic_large_topk_1.log（F create code 0 / F persisted False / A normal limit=20000 → 65535 [1,16384] / VERDICT: DEFECT_FOUND）
- 源码 文件:行号+摘录:
  - `task_search.go:171` — `t.largeTopKEnabled = collectionInfo.queryMode == common.QueryModeLargeTopK`
  - `common.go:528-531` — IsQueryModeLargeTopK 读持久化属性 kvs；属性持久化仅发生在 alter 路径（CollectionReqWithProperties @ request_v2.go:80-84 绑定 alter_properties 路由，create 绑定 CollectionReq @ handler_v2.go:183）
  - 调用链: create properties → gin 反序列化进 CollectionReq（无 Properties 字段）→ 丢弃；alter_properties → CollectionReqWithProperties → alterCollectionTask → 持久化 → largeTopKEnabled=true

## Impact
功能级静默失效：文档宣称的 create 载体路径完全不承载 large_topk，用户必须知道"隐形规则"（只能用 alter）才能启用大窗口查询；否则在运行期以误导性 topk 错误失败。最终判 DEFECT（机械B=CONFIRMED）。
