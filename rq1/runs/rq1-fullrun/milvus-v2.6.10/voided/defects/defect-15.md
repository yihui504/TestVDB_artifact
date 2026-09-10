# Defect 15: nprobe out-of-domain values silently neutralized — float/negative/INT_MAX all behave as default

## Metadata
- Defect ID: semantic_r2b_nprobe_domain_01
- Type: Type1_IllegalSuccess（参数域非法成功）
- Param / Trigger: `searchParams.nprobe` = 4.5（float 传 int 参数）/ -1 / 0 / INT_MAX
- Novelty: NOVEL

## Reproduction (curl)
```
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","data":[[...]],
       "searchParams":{"nprobe":4.5},
       "limit":10}'
# → HTTP 200, {"code":0}, results bit-identical to baseline nprobe=4

# repeat with "nprobe": -1 / 0 / 2147483647
# → all 200/code:0, results identical to baseline
```

## Expected vs Actual
- Expected: int 参数收到 float（4.5）或域外值（-1/0/INT_MAX）应被类型/域校验拒绝或至少告警。
- Actual: 全部 200/code:0，且搜索结果与 baseline nprobe=4 完全一致——透传层无校验，域外值被无声无效化（回落默认/被底层忽略），类型恒真触发客观成立。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（回滚版无 nprobe 参数域断言；候选标签 type_coercion 为派发侧噪声）
- Ring 2 (Document Reference 文档引用) doc_verification: NOT_VERIFIED（R2b 盲注轮无在线核验；疑义：-1 结果与基线一致符合 HNSW 负值 sentinel 先例，knowhere 消费层不在源码树，建议主进程人工复核该单点）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/semantic_r2b_nprobe_domain_01.py
- Log: debate_logs/output_semantic_r2b_nprobe_domain_01.log
- 源码: searchParams 透传层无校验（源码确证）；nprobe 未做 int 收窄与值域检查即透传至执行层。

## Verdict Aggregation
- A (contract): NEUTRAL — GAP（候选标签 type_coercion 为派发侧噪声）
- B (physical): CONFIRMED — objective_constraint_class: 类型恒真
- C (behavioral): CONFIRMED
- D (cognition): NO_SIGNAL
- Final: A=NEUTRAL(GAP)→灰区；机械B=CONFIRMED→DEFECT（采信不改判）

## Impact
召回率/延迟调优参数可被任意域外值无声无效化：用户设 nprobe=0 或 2147483647 得到与默认完全一致的结果，无法察觉参数未生效，性能与精度调优失效不可诊断。R2b 纯盲注独立发现，2026-08-22。
