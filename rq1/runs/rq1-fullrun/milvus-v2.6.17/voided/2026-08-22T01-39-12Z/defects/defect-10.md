# Defect 10: 声明 Array 字段读出泄漏 proto 包装结构 {"Data":{"StringData":{...}}}

## Metadata
- defect_id: TESTVDB-MILVUS-010 (vein_array_readout_proto_leak_002)
- type: Type2_PoorDiagnostics
- param: entities+get / entities+query 响应中的 Array 字段序列化
- novelty: NOVEL

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/get" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","id":1,"outputFields":["tags","tags_dyn"]}'
# 观测: {"data":[{"id":1,"tags":{"Data":{"StringData":{"data":["a","b"]}}},"tags_dyn":["x","y"]}]}
```

## Expected vs Actual
- Expected: Array 字段应以纯 JSON 数组返回（同响应内动态字段 tags_dyn 即 ["x","y"]）。
- Actual: 同一行同一响应内：声明字段 tags 返回 proto oneof 包装 {"Data":{"StringData":{"data":[...]}}}，动态字段 tags_dyn 为纯 JSON 数组——内部形态分裂即观测。get 与 query 双端点同型复现。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（契约库无 readout 序列化 constraint；vein 内部一致性命题）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（未单独核 readout 专项页）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_array_readout_proto_leak_002.py
- Log: output_vein_array_readout_proto_leak_002.log
- 源码 httpserver/utils.go L1623-1637 BuildQueryResp Array 分支：`row[fieldName] = fieldDataList[j].GetScalars().GetArrayData().GetData()[i]` —— 直接把 schemapb.ScalarField（oneof 包装结构体）塞进 row，json.Marshal 输出其导出字段名；动态字段走 JSON 分支（json.Unmarshal 到 map 再平铺）天然纯 JSON。缺一个 ArrayData[i] -> []interface{} 展开步骤，对照分支有该展开。verification_outcome: validation_absent。

## Impact
REST 客户端无法直接消费声明 Array 字段：必须手工剥 {"Data":{"StringData":{"data":...}}} 包装，且同响应内两种形态并存使解析逻辑不可统一；proto 内部结构泄漏到公共 API 契约面。D=blindspot（认知库无 readout 序列化陈述）。
