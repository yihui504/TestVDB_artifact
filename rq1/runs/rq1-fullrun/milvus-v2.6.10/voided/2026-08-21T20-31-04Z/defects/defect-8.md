# Defect 8: entities/search — searchParams.ef 六类非法值全部静默替换默认值（结果与默认逐位一致）

## Metadata
- Defect ID: TESTVDB-MILVUS-8
- defect_id (script): vein_searchparams_silent_default_3
- Type: Type2_PoorDiagnostics（类型恒真）
- Endpoint: POST /v2/vectordb/entities/search
- Param: searchParams.ef（param_name: searchParams.ef）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<HNSW 已加载>","data":[[...]],"limit":5,"searchParams":{"params":{"ef":-1}},"outputFields":["id"]}'
```

## Expected vs Actual
- Expected: ef 非法值（负数/0/浮点/bool/非数字字符串/超大值）应报错或产生可观测差异
- Actual: `PASS ef_neg_silent_code0 {'code':0,'cost':0,'data':[...5 rows...]}` + `PASS ef_neg_same_as_default 'invalid ef silently ignored, results identical to default'`
- 六种非法值（-1/0/16.7/true/"16"/1e12）全部 code:0 且 same_as_default 断言全过

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: vein_searchparams_silent_default（vein 自生；官方契约对 searchParams.ef 无任何校验断言——覆盖缺口如实记）
  - assertion: `searchParams.params.ef 为索引语义参数，非法值应报错或至少产生可观测差异，不得静默替换为默认值`；api_violates_assertion=true（6/6 全谱否定）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（官方 SDK 文档有 ef 建议 range [topk, dim]，未在本 contract source_url 集内）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_searchparams_silent_default_3.py（13 断言含逐值 same_as_default 对照；多脚本稳定触发）
- Log: vein_scripts/output_vein_searchparams_silent_default_3.log

### 源码 文件:行号+摘录
- utils.go L2076-2134 generateSearchParams：仅校验 params 是 dict + 消歧；任意 key/value 序列化进 KeyValuePair 透传：`bs, _ := json.Marshal(paramsMap); searchParams = append(...)`
- core/query/PlanProto.cpp L63-66：`search_info.search_params_ = nlohmann::json::parse(...)`——无 ef 键校验
- knowhere 为 FetchContent 外部依赖（本 clone 无源码），其默认值容错行为无法本地取证（如实记）
- verification_outcome: validation_absent

## Impact
HNSW 索引核心调优参数 ef 的任意非法值被无声替换为默认，检索质量调优完全失效且不可发现：用户传 ef=1e12 或 ef=true 以为在调参，实际跑的是默认配置。比 2xx+业务码更彻底的静默（纯 200+code:0），无任何错误通道。
