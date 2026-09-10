# Defect 14: searchParams unknown keys silently ignored — misspelled 'nprobes' yields zero diagnostics

## Metadata
- Defect ID: semantic_r2b_nprobe_diag_05
- Type: Type2_PoorDiagnostics（参数校验诊断缺失）
- Param / Trigger: `searchParams` 未知键 `'nprobes'`（正确为 `nprobe`）及空串键
- Novelty: NOVEL

## Reproduction (curl)
```
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/search" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<r2b_col>","data":[[...]],
       "searchParams":{"nprobes":16, "": 4},          # misspelled key + empty-string key
       "limit":10}'
# → HTTP 200, {"code":0, ...normal results...}

# baseline: same endpoint, out-of-range limit gets an explicit error message
# (milvus_range_entities_search_001) — diagnostic granularity is inconsistent
```

## Expected vs Actual
- Expected: 拼写错误的参数键（'nprobes' vs 'nprobe'）至少产生警告或被拒绝；同端点其他参数越界（limit）有显式文案，诊断粒度应一致。
- Actual: `searchParams` 未知键 'nprobes' 与空串键均 200/code:0 且正常返回结果（VERDICT 0/6 触发），拼写错误零提示；searchParams 整体静默丢弃/忽略，用户以为调优生效实际参数从未生效。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（回滚版无 searchParams 键校验断言）
- Ring 2 (Document Reference 文档引用) doc_verification: NOT_VERIFIED（R2b 盲注轮无在线核验；BDP-4 表明 200 信封 by design，但本链违规在参数校验诊断缺失而非信封形态）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: scripts/semantic_r2b_nprobe_diag_05.py
- Log: debate_logs/output_semantic_r2b_nprobe_diag_05.log
- 源码: searchParams 透传路径无未知键校验（无键白名单/黑名单检查）；对照同端点 limit 越界的显式报错文案（milvus_range_entities_search_001 基线）。

## Verdict Aggregation
- A (contract): NEUTRAL — GAP
- B (physical): CONFIRMED — objective_constraint_class: HTTP语义恒真
- C (behavioral): CONFIRMED
- D (cognition): SUPPORTS_NOT_DEFECT（200 信封 by design，不推翻 B）
- Final: A=NEUTRAL(GAP)→灰区；机械B=CONFIRMED→DEFECT（采信不改判，D 不能推翻 B）

## Impact
参数拼写错误（性能调优最常见的低级错误）被静默吞掉，用户以为 nprobe 生效而实际搜索始终用默认参数——性能问题不可诊断；同端点对 limit 有显式诊断、对 searchParams 零诊断的不一致加剧迷惑。R2b 纯盲注独立发现，2026-08-22。
