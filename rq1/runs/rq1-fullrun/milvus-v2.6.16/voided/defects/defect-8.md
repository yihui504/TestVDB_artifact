# Defect 8: consistencyLevel='' 空 enum 串未被拒（契约断言非 enum 应 1100）+ query 端点 limit/offset 零负值静默通过

## Metadata
- Defect ID: TESTVDB-MILVUS-8 (boundary_r2_query_zero_23)
- Type: Type1_IllegalSuccess
- Param: consistencyLevel（query/search 双端点复现）
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: entities+query, entities+search, entities+get
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
curl -s -X POST ".../v2/vectordb/entities/query" -H "Content-Type: application/json" \
  -d '{"collectionName":"c","filter":"id >= 0","consistencyLevel":"","limit":10}'
# → 200 {"code":0,"cost":0,"data":[]}   （主观测：空 enum 串 code:0；search 端点同值同结果）
# 同端点: query limit=0 / limit=-1 / offset=-1 → 全部 200 code:0（search 端点同值返回 65535）
```

## Expected vs Actual
- Expected（契约 milvus_type_entities_search_001）: `consistencyLevel IN {Strong,Session,Bounded,Eventually,Customized} else code==1100`（message: consistencyLevel can only be [...], default: Bounded）
- Actual: consistencyLevel=''（不属于 enum）在 query 与 search 双端点均返回 code:0 而非 1100——空串落入 convertConsistencyLevel 的默认分支而非 else 拒绝分支；另 query 端点 limit=0/-1、offset=-1 均 code:0 静默通过（search 端点同值 65535，跨端点分叉）

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_entities_search_001（violates=true 依赖把 '' 算入 'else'——源码把空串定义为默认 Bounded，契约措辞与实现存在解释空间；机械A=CONFIRMED 定案，无权翻案）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_MISMATCH（link/version PASS；content_consistency FAIL——契约断言文本与实测行为不一致，doc/实现/契约三方不一致本身是记录点）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/boundary_r2_query_zero_23.py（单脚本，consistencyLevel='' 于 query+search 双端点脚本内复现）
- Log: output_boundary_r2_query_zero_23.log（`[query consistencyLevel=''] 200 {"code":0,...} -> DEFECT_FOUND`；副观察 search 同值 / query limit=0、-1、offset=-1 / get outputFields=[] 全 DEFECT_FOUND 行）
- 源码 文件:行号+摘录:
  - `utils.go:1739-1749` — `func convertConsistencyLevel(reqConsistencyLevel string) { if reqConsistencyLevel != "" { level, ok := ...; if !ok { return err }; return level }; // ConsistencyLevel_Bounded default in PyMilvus return commonpb.ConsistencyLevel_Bounded, true, nil }` — 空串显式定义为默认 Bounded（模仿 PyMilvus 语义，注释明言）；非空非 enum 串才报错
  - `handler_v2.go:1092-1097`（query 路径）— `if httpReq.Offset > 0 {...}` / `if httpReq.Limit > 0 {...}` — 零/负 limit/offset 被条件过滤静默丢弃，task_query.go getQueryParams 收不到 LimitKey 即无校验
  - 对照 search 路径 `handler_v2.go:1537-1538` 无条件追加 TopK/Offset → search_util 拒绝——跨端点不对称是结构性差异

## Impact
契约断言的 enum 否定分支在空串处不生效，客户端拼写遗漏（空串）得到静默默认而非显式错误；query 与 search 端点对 limit/offset 零负值行为分叉进一步加剧不一致。最终判 DEFECT（机械A=CONFIRMED：契约 enum 断言非 enum 应 1100，实测空串 code:0 双端点）。
