# Defect 3: entities/search — 未 load 集合 search 返回 code:0 空结果而非 101（double load 亦无 104）

## Metadata
- Defect ID: TESTVDB-MILVUS-3
- defect_id (script): boundary_load_double_021
- Type: Type2_PoorDiagnostics
- Endpoint: POST /v2/vectordb/entities/search（+ collections/load）
- Param: load_state（param_name: load_state）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
# 前置：quick-create 集合 bnd_load_<ts>（dim=8），不调用 load
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"bnd_load_<ts>","data":[[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8]],"limit":3,"outputFields":["id"]}'
```

## Expected vs Actual
- Expected: 未 load 状态 search => code==101（ErrCollectionNotLoaded）；double load => code==104
- Actual: `search before load -> http=200 code=0 raw={"code":0,"cost":0,"data":[]}`；`double load -> http=200 code=0 raw={"code":0,"data":{}}`

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_state_collections_load_002（+ load_001 double load => 104）
  - assertion: `state!=Loaded AND (search|query) => code==101`；api_violates_assertion=true
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（errors.go:66 ErrCollectionNotLoaded=101 / :69 ErrCollectionLoaded=104 与 state_constraints 一致；behavioral_contract milvus_bc_load_release_001 场景逐字覆盖）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_load_double_021.py（与 semantic_loadcycle_03.py 双脚本互证，grade A，多脚本稳定触发）
- Log: debate_logs/output_boundary_load_double_021.log

### 源码 文件:行号+摘录
- internal/querycoordv2/services.go L230-237：already-loaded 分支 `return merr.Success(), nil`——重复 load 显式按 ignored-by-design 返回 code 0 而非 104
- handler_v2.go search L1533：`if searchResp.Results.TopK == 0 { HTTPReturn(code 0, data []) }`——未加载 search 经 wrapperProxyWithLimit（L486-549）→ lb_policy GetShard retry on ErrCollectionNotLoaded 耗尽后降级为空结果集，HTTP 层映射 code:0 空数组；101 定义存在但未透出到该 REST 路径
- 抗辩记录：源码 TopK==0 降级为 by-design 抗辩，机械 grade A 定案不翻案

## Impact
用户对未加载集合 search 得到"成功 + 空结果"，误以为集合为空或数据丢失，无法区分"没数据"与"没加载"——典型诊断缺失；错误码 101/104 在源码有定义但该路径不触发，契约 state 断言失效。
