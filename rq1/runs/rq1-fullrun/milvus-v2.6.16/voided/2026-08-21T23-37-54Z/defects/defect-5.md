# Defect 5: 已建索引 collection 上 alter query_mode 返回 code 0（契约断言应 702）+ 702 门单向

## Metadata
- Defect ID: TESTVDB-MILVUS-5 (state_query_mode_alter_1)
- Type: Type4_StateLogicViolation
- Param: query_mode
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: collections+alter_properties / indexes+create
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
# B: 建索引后 alter query_mode
curl -s -X POST ".../v2/vectordb/indexes/create"  -d '{"collectionName":"st_qm_alter_1","indexParams":[...]}'
curl -s -X POST ".../v2/vectordb/collections/alter" -d '{"collectionName":"st_qm_alter_1","properties":{"query_mode":"large_topk"}}'
# → 200 {"code":0,"data":{}}  （契约断言应 702）
# D2 前向绕过: 先 create(带 large_topk 的合法路径 alter) → 再建索引 → 200 code 0（索引创建不受限）
```

## Expected vs Actual
- Expected（契约 querymode_001）: collection 已有 vector index 且 alter 改 query_mode => code 702, message `can not alter query_mode if the collection already has a vector index. Please drop the index first: index duplicates[indexName=...]`
- Actual: B alter（有索引）code 0 被接受；D2 前向（在 large_topk collection 上建索引）也 code 0——门是单向的；D 对照（bogus 值）65535 枚举校验活着；C 删索引后 alter code 0（门在删除后恢复）

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_range_collections_querymode_001（观察 B squarely 在域内，violates=true，机械A=CONFIRMED 定案不可翻）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（task.go detectQueryModeChange/alterCollectionTask 本地 clone 验证，全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: state_scripts/state_query_mode_alter_1.py（单脚本；B 主观测 + C/D/D2 对照全链）
- Log: output_state_query_mode_alter_1.log（B create index code 0 / B alter(with index) code 0 / DEFECT: 'alter query_mode on indexed collection ACCEPTED (expected 702)'）
- 源码 文件:行号+摘录:
  - `internal/proxy/task.go:1515-1530` — `if isoChanged || queryModeChanged { if vecField, err := checkVectorIndexExist(...); err != nil {...} else if vecField != "" { if queryModeChanged { return merr.WrapErrIndexDuplicate(vecField, "can not alter "+common.QueryModeKey+" ...") } } }` — 702 门以 **changed** 为条件
  - `task.go:1356`（detectQueryModeChange）— 仅 oldQueryMode != newQueryMode 时置 changed；同值重复 alter 按源码逻辑合法绕过 702
  - index create 路径 grep query_mode 零命中 — 前向（对 large_topk collection 建索引）完全无门，匹配 D2
  - 链内诚实记录的微观疑点：(a) log 未显示 B 请求的具体值，可能为同值重复（changed=false）；(b) checkVectorIndexExist 可能未看到异步刚建的索引。机械A 定案 DEFECT，人工复核建议保留
- 副观察 E: D2 后 load 报 700 index not found——索引状态异常，链内记录未裁决

## Impact
状态不变量（query_mode 与 vector index 互斥）在 REST alter 路径上未被可靠执行，且门单向（前向建索引完全无检查）；同值重复与异步可见性疑点提示实现脆弱。最终判 DEFECT（verdict_A=CONFIRMED 机械定案，LLM 无权改判；链内附人工复核建议）。
