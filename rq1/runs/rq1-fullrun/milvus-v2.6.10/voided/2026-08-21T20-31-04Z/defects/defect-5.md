# Defect 5: entities/search — create 后未 load 即 search 返回 code:0 空结果而非 101（load 周期 P1）

## Metadata
- Defect ID: TESTVDB-MILVUS-5
- defect_id (script): semantic_loadcycle_03
- Type: Type4_StateLogicViolation
- Endpoint: POST /v2/vectordb/entities/search
- Param: load_state（param_name: load_state）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
# 前置：drop 尝试 -> quick-create 集合 sem_load_03（dim=8），脚本内无任何 load 调用
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"sem_load_03","data":[[...8 dims...]],"limit":3,"outputFields":["id"]}'
```

## Expected vs Actual
- Expected: code==101（state!=Loaded AND search => 101；behavioral_contract milvus_bc_load_release_001 场景 'create -> search (not loaded)' 期望 101）
- Actual: `P1 search-not-loaded: 200 {"code":0,"cost":0,"data":[]}`
- 脚本在 P1 code!=101 后 sys.exit(1)，P2/P3 未执行

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_state_collections_load_002（+ milvus_bc_load_release_001 双锚定）
  - assertion: `state!=Loaded AND (search|query) => code==101`；api_violates_assertion=true
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（errors.go:66 定义 101；四环一致）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/semantic_loadcycle_03.py（grade A；与 boundary_load_double_021 为同一观测的独立双脚本——不同集合名、独立创建路径；脚本前置 drop + 专属集合名，无 prior 时序污染）
- Log: debate_logs/output_semantic_loadcycle_03.log

### 源码 文件:行号+摘录
- handler_v2.go L1532-1534：`if searchResp.Results.TopK == int64(0) { HTTPReturn(c, http.StatusOK, gin.H{HTTPReturnCode: merr.Code(nil), HTTPReturnData: []interface{}{}, ...}) }`
- 101（ErrCollectionNotLoaded）在 get_load_state（impl.go L1976-1991）/ lb_policy（L111-117）中使用，但 search REST 路径未透出
- 抗辩记录：源码降级路径（by_design 抗辩）不翻案

## Impact
集合生命周期状态违规（未加载即检索）以 200+code:0 空结果静默呈现。与 Defect 3 同机制独立复现，确认为 2.6.10 REST search 路径系统性诊断缺失：用户无法通过返回码感知 load 状态错误。
