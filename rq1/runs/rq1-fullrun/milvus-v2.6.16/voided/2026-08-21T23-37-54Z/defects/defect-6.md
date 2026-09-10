# Defect 6: create vs alter 跨端点校验不对称——两套 REST struct 一松一严 + alter 持久化任意 junk 键

## Metadata
- Defect ID: TESTVDB-MILVUS-6 (vein_query_mode_maturity_1)
- Type: Type1_IllegalSuccess
- Param: properties.query_mode
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: collections+create / collections+alter_properties
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
# CONTROL: alter 非法值 → 正确拒绝
curl -s -X POST ".../v2/vectordb/collections/alter" -d '{"collectionName":"c","properties":{"query_mode":"bogus"}}'
# → 200 {"code":65535,"message":"invalid query_mode value \"bogus\", valid values: [large_topk]"}
# T1: create 同值 → 静默接受
curl -s -X POST ".../v2/vectordb/collections/create" -d '{"collectionName":"c2","schema":{...},"properties":{"query_mode":"bogus"}}'
# → 200 {"code":0,"data":{}}
# T2: alter 写入任意 junk 键 → 原样持久化
# describe 读回: [...{"key":"junk_key_abc","value":"junk_value"},{"key":"query_mod","value":"large_topk"},{"key":"nprobe","value":"0"}]
```

## Expected vs Actual
- Expected（create_009）: create 路径 properties.query_mode 非枚举 => 65535
- Actual: T1 create bogus code 0 vs CONTROL alter 同值 65535；T2 经 alter 可把 junk/拼写错键原样写入 collection 元数据；T3 create 时 junk 不持久化（create 忽略、alter 持久化——双向不对称）

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_009（T1 直接违反，violates=true；T2 无专属约束=契约 gap 如实记录；T3 为 synthesis 级）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（create_009 + alter 路径源码 task.go/common.go 本地 clone 验证，全 PASS；不对称断言本身不在任何单一约束内，tier 如实标注）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_query_mode_maturity_1.py（多脚本稳定触发：vein_query_mode_maturity_1 / boundary_querymode_01 / boundary_querymode_03；脚本内配对 control + describe 读回）
- Log: output_vein_query_mode_maturity_1.log（CONTROL 65535 vs T1 code 0；T2 junk 持久化；T3 create 不持久化；DEFECT: cross-endpoint validation asymmetry）
- 源码 文件:行号+摘录:
  - `request_v2.go:80-84` — CollectionReqWithProperties（alter 路由绑定，DbName/CollectionName/Properties map）→ alterCollectionTask → detectQueryModeChange → common.ValidateQueryMode (task.go:1351-1353) 严格校验（EqualFold @ common.go:521-522 连拼写错都能拦）
  - `request_v2.go:643-656` — CollectionReq（create 路由绑定）无 Properties 字段 + 白名单不含 query_mode → create 静默接受一切
  - alter 侧未知非保留键无白名单 → 原样 raw persist
  - 结论：不对称由两-struct 架构完全解释

## Impact
同一参数族跨端点行为割裂：无效配置在 create 被吞、在 alter 被拒、junk 键经 alter 可污染元数据（持久化 nprobe:'0' 等可能干扰后续读取方）。用户无法建立统一的心智模型，配置错误难以发现。最终判 DEFECT（机械B=CONFIRMED）。
