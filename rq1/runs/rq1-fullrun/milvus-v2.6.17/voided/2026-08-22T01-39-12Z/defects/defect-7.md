# Defect 7: REST createCollection 完全不识别 numShards 参数，越界值 0/-1/17 全部旁路校验

## Metadata
- defect_id: TESTVDB-MILVUS-007 (boundary_collections_name_length_011)
- type: Type1_IllegalSuccess
- param: numShards (0 / -1 / 17)
- novelty: NOVEL

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","dimension":4,"numShards":17}'
# 观测: {"code":0,"data":{}}  (期望 1100；numShards 0/-1 同样 code:0)
```

## Expected vs Actual
- Expected: 契约断言 numShards <= 16（proxy.maxShardNum）；计数类参数下界 >= 1。
- Actual: numShards 0/-1/17 均 code:0 建表成功。名称长度对照组（255 code:0 / 256 1100 / empty 1802 / NUL 1100）全部正确——defect 域收窄 numShards 单参数成立。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_range_collections_create_005
  - assertion: "numShards <= 16 (proxy.maxShardNum)"（链引文括号注释非原子串 → quote_mismatch → GREY_ZONE；B 数值下界兜底 CONFIRMED → DEFECT）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED
  - limitations.md 原文在页："Shard | 16"
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_collections_name_length_011.py
- Log: output_boundary_collections_name_length_011.log
- 源码 request_v2.go CollectionReq 无 numShards 字段（grep numShards/NumShards 在 httpserver 目录零命中）；handler_v2.go L2000-2007 REST 层只识别 params.shardsNum；task.go:395 上界校验 `if t.ShardsNum > Params.ProxyCfg.MaxShardNum` 恒验默认值——客户端顶层 "numShards" 键落入 Params map 但从不映射 ShardsNum，旁路全部校验。verification_outcome: validation_absent。

## Impact
REST 用户按 SDK/gRPC 惯例发送 numShards 会被静默忽略并按默认分片数建表，无任何未知参数告警；越界值（0/-1/17）不触发任何校验。属 REST API 面缺口 + 校验未接线复合问题。
