# Defect 5: consistencyLevel 空串/null 绕过枚举闭集校验

## Metadata
- defect_id: TESTVDB-MILVUS-005 (boundary_search_consistency_enum_015)
- type: Type1_IllegalSuccess
- param: consistencyLevel ('' / null)
- novelty: NOVEL

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","data":[[0.1,0.2]],"consistencyLevel":"","annsField":"vec"}'
# 观测: {"code":0,"cost":0,"data":[{"distance":0,"id":1}],"topks":[1]}  (期望 1100)
```

## Expected vs Actual
- Expected: 契约闭集 {Strong,Session,Bounded,Eventually,Customized}，非成员 → code 1100。
- Actual: '' 与 null 均 code:0；同域对照 'Foo' 与小写 'strong' 均正确 1100（"can only be [Strong, Session, Bounded, Eventually, Customized]"）——空值形态绕过枚举，可判定性自洽性被破坏。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_entities_search_001
  - assertion: "consistencyLevel IN {Strong,Session,Bounded,Eventually,Customized} else code==1100"
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（枚举五值+default Bounded 消息原文 live 复现）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_search_consistency_enum_015.py
- Log: output_boundary_search_consistency_enum_015.log
- 源码 internal/distributed/proxy/httpserver/utils.go L1739-1751 convertConsistencyLevel：`if reqConsistencyLevel != "" { ...查表失败 1100... } // ConsistencyLevel_Bounded default in PyMilvus; return Bounded, true, nil` —— 空串显式回退默认 Bounded；JSON null 经 Go 解码为 ""，同路径。verification_outcome: by_design_in_source（源码注释援引 PyMilvus 对齐为 by-design 抗辩；契约闭集无空值豁免，聚合按 A 定案 DEFECT）。

## Impact
空值与非法非空串行为不一致：'Foo' 被拒而 ''/null 静默回退 Bounded。用户拼写失误导致的空值无法被发现，一致性语义被隐式降级。次缺陷面：searchParams（nprobe -1/0/1e9/'abc' 等）完全无校验。
