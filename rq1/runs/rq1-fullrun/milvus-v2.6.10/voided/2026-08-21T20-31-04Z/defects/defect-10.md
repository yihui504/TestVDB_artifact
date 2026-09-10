# Defect 10: entities/hybrid_search — 子搜索 params 非法 ef 静默替换默认，同请求 rerank 非法值却 65535（校验不对称）

## Metadata
- Defect ID: TESTVDB-MILVUS-10
- defect_id (script): vein_hybrid_subsearch_params_7
- Type: Type2_PoorDiagnostics（类型恒真）
- Endpoint: POST /v2/vectordb/entities/advanced_search（hybrid）
- Param: search[].params.ef（param_name: search）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/advanced_search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<hybrid>","search":[{"data":[[...]],"annsField":"vec","limit":5,"params":{"ef":"abc"}}],"rerank":{"strategy":"bogus"}}'
```

## Expected vs Actual
- Expected: 子搜索 params 非法值（"abc"/-3）应与 rerank 参数同等校验报错
- Actual: `PASS subsearch_ef_str_silent_code0 {'code':0,'cost':0,'data':[...]}` + `PASS subsearch_ef_str_same_as_valid 'identical to valid-ef results = silently substituted default'`（ef="abc"）；`PASS subsearch_ef_neg_silent_code0`（ef=-3）
- 同请求对照：`PASS control_bad_rerank_errors {'code':65535,'message':'unsupported rank type bogus'}`

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: vein_hybrid_subsearch_params（vein 自生；官方契约对 2.6 hybrid 子搜索 params 无断言——覆盖缺口记）
  - assertion: `hybrid 子搜索 searchParams 非法值应与 rerank 参数同等校验报错，不得静默替换默认值`；api_violates_assertion=true（同请求内对照直接否定）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（endpoint registry 含 hybrid/advanced_search；rerank 侧校验由行为直证）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_hybrid_subsearch_params_7.py（五断言含 rerank 同请求对照；多脚本稳定触发）
- Log: vein_scripts/output_vein_hybrid_subsearch_params_7.log

### 源码 文件:行号+摘录
- handler_v2.go L1615-1635（advancedSearch 子搜索）：`for _, subReq := range httpReq.Search { searchParams, err := generateSearchParams(subReq.SearchParams) ... append(TopKKey/OffsetKey...) }`——复用无 ef 校验的透传函数
- internal/util/function/rerank/function_score.go L190-200：`rankTypeStr, err := funcutil.GetAttrByKeyFromRepeatedKV(...); if _, ok := rankTypeMap[rankTypeStr]; !ok { return nil, fmt.Errorf("unsupported rank type %s", rankTypeStr) }`——rerank 白名单显式校验
- 根因：子搜索 params 与 rerank params 走完全不同校验函数，2.6 hybrid 新路径复用无校验透传（validation_absent）

## Impact
同一 hybrid 请求内两类参数校验标准割裂：子搜索 ef 任意非法值静默替换默认（调优失效不可发现），rerank 非法值立即 65535。2.6 新路径继承单搜索的透传缺口，混合检索质量参数实际不可控。
