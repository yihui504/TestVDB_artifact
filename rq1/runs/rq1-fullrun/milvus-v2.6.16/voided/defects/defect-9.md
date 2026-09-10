# Defect 9: shardsNum=0/-1 建集合 code:0——rootcoord 静默默认化无回显（同请求 dim=-1 被拒）

## Metadata
- Defect ID: TESTVDB-MILVUS-9 (boundary_r2_create_zero_20)
- Type: Type1_IllegalSuccess
- Param: shardsNum
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: POST /v2/vectordb/collections/create
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
curl -s -X POST ".../v2/vectordb/collections/create" -H "Content-Type: application/json" \
  -d '{"collectionName":"bnd_r2_z_20c","schema":{...},"params":{"shardsNum":0}}'
# → 200 {"code":0,"data":{}}；describe 证实集合真实建成（shardsNum=-1 同型 code:0）
# 同请求体 dim=-1 → 65535 "invalid dimension: -1. should be in range 2 ~ 32768"（对照：range 校验活着）
```

## Expected vs Actual
- Expected: shardsNum 非法零/负值应被拒绝或至少回显告警（同端点 dim 有完整范围校验）
- Actual: shardsNum=0/-1 以 HTTP 200+code:0 接受并真实建集合（describe 复核通过）；同请求 dim=-1 则 65535——同端点选择性校验；rootcoord 将 <=0 静默替换为默认值，无任何回显

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（最近邻 milvus_range_collections_create_005 断言仅上界 `numShards <= 16`，0/-1 满足该断言故 violates=false——契约缺下界断言（shardsNum>=1），gap 由候选发现）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（link/version/content PARTIAL——契约源 component_param.go maxShardNum 本地 clone 已 Read，无下界锚点）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/boundary_r2_create_zero_20.py（单脚本；含 dim 对照组 + 建后 describe 复核）
- Log: output_boundary_r2_create_zero_20.log（`[create shardsNum=0] 200 code=0 -> DEFECT_FOUND`；`[describe after accept] 200 {...,"collectionName":"bnd_r2_z_20c",...}` 集合建成；dim=-1 对照 65535）
- 源码 文件:行号+摘录:
  - `internal/proxy/task.go:395-397`（createCollectionTask.PreExecute）— `if t.ShardsNum > Params.ProxyCfg.MaxShardNum.GetAsInt32() { return fmt.Errorf("maximum shards's number should be limited to %d", ...) }` — 仅上界校验，无 <=0 检查
  - `internal/rootcoord/ddl_callbacks_create_collection.go:47-49` — `if req.GetShardsNum() <= 0 { req.ShardsNum = common.DefaultShardsNum }` — 非正 shardsNum 在 rootcoord 被静默替换为默认值（与 rootcoord_mock_test.go:433-436 测试语义一致，源码显式行为）
  - 调用链: REST shardsNum=0/-1 → proxy 仅查上界（通过）→ rootcoord 替换为 DefaultShardsNum → 集合以默认 shard 数建成 → code:0

## Impact
用户显式请求的非法 shard 数被无声改写为默认值，无回显/警告，用户不可感知实际拓扑与请求不符（影响容量规划与写入路由预期）；同端点 dim 校验严格而 shardsNum 完全放行，选择性校验成立。by-design 静默默认化抗辩已记录（行为等价于省略参数），机械B=CONFIRMED 定案。最终判 DEFECT。
