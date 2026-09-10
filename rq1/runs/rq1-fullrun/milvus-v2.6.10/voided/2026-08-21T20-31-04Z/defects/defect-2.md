# Defect 2: collections/create — 顶层 shardsNum 未知参数被静默丢弃，numShards 上限校验完全旁路

## Metadata
- Defect ID: TESTVDB-MILVUS-2
- defect_id (script): boundary_shards_16_010
- Type: Type1_IllegalSuccess
- Endpoint: POST /v2/vectordb/collections/create
- Param: numShards（param_name: numShards）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"bnd_shards_<ts>","dimension":8,"shardsNum":17}'
```

## Expected vs Actual
- Expected: numShards=17 > MaxShardNum(16) 应被拒（task.go:393 校验存在）
- Actual: `numShards=17 -> http=200 code=0 raw={"code":0,"data":{}}`；另 64/1000/0/-1/'16'/1.5/None 全部 code=0

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_range_collections_create_005
  - assertion: `numShards <= 16`；api_violates_assertion=true（语义意图被静默丢弃层面）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（link PASS / version PASS / content PARTIAL / endpoint_precision PARTIAL——REST 顶层参数名与契约定位偏差）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_shards_16_010.py
  - grade B；numShards=17/64/1000/0/-1 全 code:0；describe 回读被截断 300 字符，持久化值取证缺失（记疑义）
- Log: debate_logs/output_boundary_shards_16_010.log

### 源码 文件:行号+摘录
- handler_v2.go L1914-1921：`shardsNum := int32(ShardNumDefault); if shardsNumStr, ok := httpReq.Params["shardsNum"]; ok { ... }`——REST 只接受 params.shardsNum，顶层 shardsNum 不在 CollectionReq（request_v2.go L630-643）结构体中被 Go json 反序列化静默丢弃
- internal/proxy/task.go L392-395 MaxShardNum 校验存在且有效（params.shardsNum 路径会拒），constant.go L103 ShardNumDefault=1
- verification_outcome: by_design_in_source（未知键丢弃），surviving=「顶层未知参数静默丢弃无任何告警」

## Impact
客户端按直觉在顶层传 shardsNum（含非法值 17/1000/0/-1）得到 code:0 成功，实际集合以默认 1 分片创建——语义意图被无声吞并，上限校验被参数放置位置旁路。无 strict unknown-field rejection，配置错误不可发现。
