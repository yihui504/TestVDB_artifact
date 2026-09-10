# Defect 4: entities/query — filter 引用不存在字段在 dynamic 集合返回 code:0 空结果（静态集合 1100 拒）

## Metadata
- Defect ID: TESTVDB-MILVUS-4
- defect_id (script): semantic_filterdiag_04
- Type: Type1_IllegalSuccess
- Endpoint: POST /v2/vectordb/entities/query
- Param: filter（param_name: filter）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
# 前置：quick-create（EnableDynamicField 默认 true）+ load + insert 1 行
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/query" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"sem_fdiag_04_<ts>","filter":"nonexistent_field == 1","limit":10,"outputFields":["id"]}'
```

## Expected vs Actual
- Expected: code 1100 'field nonexistent_field not exist'（filter 必须是合法 boolean 表达式）
- Actual: `HTTP=200 code=0 raw={"code":0,"cost":0,"data":[]}`（集合内无该字段）
- 对照（同表达式 no-dyn 集合）：`code:1100 'failed to create query plan: cannot parse expression: no_such_field_xyz > 5, error: field no_such_field_xyz not exist'`

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_entities_delete_001
  - assertion: `filter != null AND is valid boolean expr`；api_violates_assertion=true（REST 观测层面）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（errors.go:168 ErrFieldNotFound=1700；对照组实测证明校验存在）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/semantic_filterdiag_04.py（与 vein_scripts/vein_unknown_field_silent_accept_1.py 同根因双脚本互证，grade A）
- Log: debate_logs/output_semantic_filterdiag_04.log

### 源码 文件:行号+摘录
- internal/parser/planparserv2/plan_parser_v2.go：字段存在性检查依赖 collSchema.EnableDynamicField（constant.go L105 EnableDynamic=true）
- dynamic 集合：未知字段视为合法动态字段引用 → 运行时取值 NULL → NULL==1 为 false → 空结果 code:0；static 集合：同输入报 1100
- 抗辩记录：dyn 集合 NULL 匹配为 by_design 抗辩与静态 1100 对照记疑义，机械 A 定案不翻案

## Impact
filter 字段名拼写错误（或字段已被删除）在 dynamic 集合上静默返回空结果而非报错，用户无从发现过滤条件从未生效——数据正确性伪装成"无匹配"。同输入在静态/动态集合行为分裂，契约 'valid boolean expr' 断言在 dyn 路径失效。
