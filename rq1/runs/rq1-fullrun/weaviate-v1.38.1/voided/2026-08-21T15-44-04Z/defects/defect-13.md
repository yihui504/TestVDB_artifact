# Defect 13: bm25 minimumOrTokensMatch=-5 静默接受且等价 unset（无阈值）

## Metadata
- defect_id: vein_bm25_motm_negative_3
- type: Type1_IllegalSuccess
- param: bm25.searchOperator.minimumOrTokensMatch
- novelty: NOVEL
- Endpoint: POST /graphql (bm25 searchOperator minimumOrTokensMatch)
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE LLM 兜底 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Get { VeinMotm(bm25: {query: [\"apple\",\"banana\",\"cherry\"], operator: Or, minimumOrTokensMatch: -5}) { txt } }"}'
# -> HTTP 200；返回全部 5 条（-5 与 unset 结果逐条相同——无阈值）
# 对照：unset -> 全部 5 条；minimumOrTokensMatch=1 -> 全部 5 条（数据集每条至少命中 1 token，合法）
```

## Expected vs Actual
- Expected: MOTM 是"最少需匹配的 token 数"（计数参数，下界 0），-5 语义非法应被拒绝。
- Actual: -5 静默接受，GraphQL 层与执行层双点零校验，行为等价于未设阈值（返回全部）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（vein_numeric_boundary；实际引用 common_filters/bm25.go:52 字段描述 "The minimum number of tokens that should match (only for OR operator)"）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（版本匹配 PASS；MOTM 无契约专项约束，语义来自源码 GraphQL schema 描述）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_bm25_motm_negative_3.py
- Log: vein_scripts/output_vein_bm25_motm_negative_3.log（negative(-5) 与 unset 结果逐条相同）
- 源码 文件:行号+摘录: adapters/handlers/graphql/local/common_filters/bm25.go:49-54 graphql 字段定义无 MinValue 约束，:85-87 解析处负值原样透传；adapters/repos/db/inverted/bm25_searcher.go:363-386 负值直接成为全局门槛；adapters/repos/db/lsmkv/search_segment.go:146 `if topKHeap.ShouldEnqueue(...) && termsMatched >= minimumOrTokensMatch`——termsMatched >= -5 恒真 → 无阈值全部入堆。全树 grep 'MinimumOrTokensMatch <' 零校验命中。

## Impact
OR 检索的精确性约束被静默绕过：预期"至少匹配 N 个词"的查询返回全部候选，召回噪声不可控，且无任何错误提示。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true; precision LOW)
