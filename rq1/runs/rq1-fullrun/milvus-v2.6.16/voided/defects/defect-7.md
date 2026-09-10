# Defect 7: search 参数零/负值静默成功——nprobe/ef 0/-1、groupSize=0 全 2xx+code:0

## Metadata
- Defect ID: TESTVDB-MILVUS-7 (boundary_r2_search_zero_22)
- Type: Type1_IllegalSuccess
- Param: nprobe（同型：ef、groupSize）
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: POST /v2/vectordb/entities/search
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
curl -s -X POST ".../v2/vectordb/entities/search" -H "Content-Type: application/json" \
  -d '{"collectionName":"c","data":[...],"searchParams":{"metricType":"COSINE","params":{"nprobe":0}},"limit":3}'
# → 200 {"code":0,"cost":0,"data":[]}   （nprobe=-1 / ef=0 / ef=-1 / groupSize=0 同型全 code:0）
# 同端点对照: limit=0 → 65535 "topk [0] is invalid ... [1, 16384]"
```

## Expected vs Actual
- Expected: searchParams 数值参数应拒绝非法零/负下界（同端点 limit/offset 越界即被 65535 拒绝，证明端点具备参数校验能力与意图）
- Actual: nprobe=0/-1、ef=0/-1、groupSize=0 全部 HTTP 200 + code:0 静默成功；对照 limit=0/-1、offset=-1 正确返回 65535——同端点选择性校验

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（constraint_id 'boundary' 不存在于 structured_contract.json——契约 gap；最近邻 milvus_range_entities_search_001 仅覆盖 limit/offset 窗口，该部分被正确执行故 violates=false；缺口在契约与 REST 校验本身，候选即由此发现）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（link/version/content PARTIAL——契约源均指本地 clone 已 Read，无 nprobe/ef/groupSize 下界断言可锚）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/boundary_r2_search_zero_22.py（单脚本，含三组 limit/offset 对照自证 invalid）
- Log: output_boundary_r2_search_zero_22.log（`[nprobe=0] 200 {"code":0,"cost":0,"data":[]} -> DEFECT_FOUND` + 同型行；对照行 limit=0/-1、offset=-1 均 65535 NO_DEFECT）
- 源码 文件:行号+摘录:
  - `internal/distributed/proxy/httpserver/utils.go:2192-2204`（generateSearchParams）— 仅校验 searchParams.params 必须是 dict，nprobe/ef 等键原样转 KeyValuePair 透传，无数值范围校验
  - `handler_v2.go:1542-1544` — `if httpReq.GroupByField != "" && httpReq.GroupSize > 0 { searchParams = append(...) }` — GroupSize=0 被静默丢弃（不追加、不报错）
  - `request_v2.go:352` — `SearchParams map[string]interface{}` 无 binding 校验
  - 调用链: HTTP body → SearchReqV2.SearchParams(无校验) → generateSearchParams(仅 dict 类型校验) → 下游 segcore；limit/offset 走 handler_v2.go:1537-1538 无条件追加 TopK/Offset 后被 search_util validateLimit 拒——与 log 对照行为一致

## Impact
非法检索参数静默成功：用户传入 nprobe=0/ef=-1 等无意义值时得到空结果而非错误，无法察觉配置错误，排查"为什么查不到"时缺乏任何诊断信号；下游引擎可能将其视为未设置走默认值（by-design 抗辩已记录，机械B=CONFIRMED 定案）。最终判 DEFECT。
