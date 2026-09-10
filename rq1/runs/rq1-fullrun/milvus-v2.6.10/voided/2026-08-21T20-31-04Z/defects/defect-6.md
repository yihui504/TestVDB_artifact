# Defect 6: entities/search — topk limit 数值下界校验缺口（None 默认注入路径绕过）

## Metadata
- Defect ID: TESTVDB-MILVUS-6
- defect_id (script): boundary_topk_limit_013
- Type: Type1_IllegalSuccess
- Endpoint: POST /v2/vectordb/entities/search
- Param: limit（param_name: limit）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<loaded>","data":[[...]],"limit":null,"offset":0,"outputFields":["id"]}'
```

## Expected vs Actual
- Expected: 1 <= limit+offset <= 16384（TopKLimit），显式越界应 65535
- Actual: `limit=None offset=0 -> http=200 code=0 raw={"code":0,"cost":0,"data":[{"distance":1,"id":1}],"topks":[1]}`
- 对照：limit=0/-1 -> 65535 "topk [0] is invalid, it should be in range [1, 16384], but got 0"；16384 -> code:0；16385 -> 65535；offset 越界同拒；limit='100'/1.5 -> 1801

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_range_entities_search_001
  - assertion: `topK limit: limit+offset must be in [1, TopKLimit=16384]; 1 <= limit + offset <= 16384 else error 'it should be in range [1, 16384], but got %d'`
  - api_violates_assertion=true（机械 B=CONFIRMED 数值下界采信不得改判）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（source_url 指向本地 clone paramtable component_param.go；断言与源码 util.go:196-201 消息模板逐字一致）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_topk_limit_013.py（多脚本稳定触发：与 vein_query_limit_semantic_drift_4 search 侧对照、semantic_limitdefault_08 同族）
- Log: debate_logs/output_boundary_topk_limit_013.log

### 源码 文件:行号+摘录
- internal/proxy/util.go L180-201：validateMaxQueryResultWindow + validateLimit（含消息模板）
- 调用点仅 search 链（search_util.go L138/192/213/221/602）；handler_v2.go:251-254 SearchReqV2{Limit:100} 默认注入——显式值经校验，None/null 走 Go 零值/默认路径绕过
- verification_outcome: validation_present（对显式值）；None 注入为契约 002 允许的默认路径边界
- 疑义记录（主进程复核）：trigger 引 -1 被接受与 log（-1 -> 65535 拒）不符；None 默认 100 为契约 002 允许

## Impact
校验对显式越界值生效但对显式 null 绕过，同参数在"显式提供/省略/null"三态下行为不一致；与 query 侧（Defect 8）无校验形成 cross-endpoint 分裂。用户以 null 表达"无限制"意图时被静默替换为 100，结果截断不可发现。
