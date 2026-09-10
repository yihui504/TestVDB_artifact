# Phase 1 统计验证报告（2026-08-13）

## 验证方法

对 124 个 issue 中标注 TP_FIXED 的 32 个逐一核查关闭原因，证据来源：
1. **issue comments**（maintainer/bot 的关闭说明）
2. **issue events**（closed 事件的 actor）
3. **issue timeline**（cross-referenced 事件 → 关联 PR 编号）

## 验证结论：TP_FIXED=32 被高估

原判据 `closed+completed+bug label` 混入了 4 类非"修复"关闭。修正后：

| 新分类 | 数量 | 判据 |
|---|---|---|
| **TP_FIXED_PR** | **10** | timeline 有 cross-ref PR 或 maintainer 明说 "fixed via PR" |
| TP_ACK_CLOSED_NOFIX | 2 | maintainer 确认 bug，关闭时无 PR |
| TP_DUP_TRACKED | 4 | maintainer "closed as dup"（bug 确认但归母 issue） |
| STALE_NO_FIX | 6 | stale[bot] 自动关，无修复证据 |
| FP_BY_DESIGN | 8 | maintainer 反驳为设计行为/非 bug |
| FP_NOT_REPRO | 2 | maintainer 无法复现 |

## TP_FIXED_PR 硬清单（10 个，均有 PR 证据）

| issue | 修复证据 | 关闭者 |
|---|---|---|
| milvus 47763 | maintainer "final fix I made: Relaxed dynamic field key validation" | xiaofan-luan |
| milvus 49890 | PR #50195 "fix: validate REST request timeout header" | sre-ci-robot |
| milvus 51084 | maintainer "i have made a pr to fix it" | yanliang567 |
| milvus 51085 | maintainer "i had pr to fix it" | yanliang567 |
| qdrant 9017 | "Fixed via PR #9320" | timvisee |
| qdrant 9039 | PR #9058 "fix: validate vector dimensions before WAL write" | generall |
| qdrant 9045 | "Fixed in PR #9070, included in Qdrant 1.18.1" | timvisee |
| qdrant 9149 | "already covered by PR #9178" | timvisee |
| weaviate 11729 | PR #11824 "fix(sharding): reject negative desiredCount" | trengrj |
| weaviate 12041 | PR #12049 "gh-12041 return 422 for batch delete" | dirkkul |

## 关键观察（分 vendor）

- **qdrant 11 个 TP_FIXED → 4 修复 + 5 FP_BY_DESIGN + 2 无法复现**。9416-9420 五连发被 coszio 一批次判 "fine and expected / breaking change"——一个集中 FP 簇（named vectors CRUD / payload filter 语义误解）。
- **weaviate 3 个 → 2 修复 + 1 by-design**。bug 质量最高。
- **milvus 18 个 → 4 修复 + 2 确认未修 + 4 dup + 6 stale + 2 by-design**。stale 率最高（6/18，含两个"2.3 版本太旧请升级"）。
- 新发批次（52307-52325，10 个）中 4 个被 dup 关（52307/52308/52310/52312），其余 6 个散在 ACK_OPEN/PENDING。

## 待补

1. ~~dup 母 issue 状态~~ → **已查（2026-08-13）**：52308/52310/52312 的母 issue 为 #52314（open，REST parser type-coercion 合并跟踪，无 cross-ref PR，未修复）。maintainer 三处 triage 均确认 bug（"Confirmed RESTful API type-validation issue"）。TP_DUP_TRACKED=3 口径维持，论文数字不变。
2. **FP_NOT_REPRO 二次确认**：9255/9373 无法复现可能是环境差异，可重跑确认（并入 Phase 2）。

## 人工核对后硬口径（126 条 = 124 issues + 2 PRs，2026-08-13 人工核对版）

- 真修复（PR 证据）：**28**（milvus 12 + qdrant 8 + weaviate 8）
- 自提修复 PR：**2**（均修复 #47729）
- bug 确认未修复：8 open + 6 closed-nofix + 3 dup = **17**
- FP（by-design + 无法复现）：16 + 8 + 2 = **26**
- 未决（pending + self-closed + stale + open-no-label）：26 + 25 + 1 + 1 = **53**

## 28 个 TP_FIXED_PR 完整 PR 证据表（timeline cross-reference 抓证）

### milvus (12)

| issue | PR | PR 标题 |
|---|---|---|
| 47763 | #47782 | fix: Validate dynamic field names and optimize static field check |
| 49890 | #50195 | fix: validate REST request timeout header |
| 51084 | #51088, #51168 | fix: Validate REST quick-create enum fields |
| 51085 | #51088 | fix: Validate REST quick-create enum fields |
| 50355 | #3513, #3514 | Clarify upsert behavior with autoID（文档修复）|
| 52309 | #52346 | fix: stop the REST group-by knobs from being silently swallowed |
| 52311 | #52346 | 同上 |
| 52313 | #52261 | fix: stop the REST API from rewriting the values a caller sends |
| 52315 | #52261 | 同上 |
| 52325 | #52346 | 同上 |
| 52307 | #52261 | 同上 |
| 49843 | #50714, #50731 | fix: validate REST v2 collection TTL properties (#49843) |

### qdrant (8)

| issue | PR | PR 标题 |
|---|---|---|
| 9017 | #9320 | （timvisee 明说 Fixed via #9320）|
| 9039 | #9058 | fix: validate vector dimensions before WAL write |
| 9045 | #9070 | （included in Qdrant 1.18.1）|
| 9149 | #9178 | （already covered by #9178）|
| 9421 | #9431, #9442 | fix: return 400 instead of 500 when cluster ops run in standalone mode |
| 9520 | #9526 | fix: add upper-bound validation for shard_number to prevent crash |
| 9522 | #9531 | fix: validate lookup_from collection for query and recommend APIs |
| 10120 | #10128, #10141 | fix: stop underestimating is_empty / not-null cardinality by 1/3 |

### weaviate (8)

| issue | PR | PR 标题 |
|---|---|---|
| 11729 | #11824 | fix(sharding): reject negative desiredCount (gh-11729) |
| 12041 | #12049 | gh-12041 return 422 for batch delete |
| 11399 | #11439 | gh-11399 validate hnsw vectorIndexConfig numeric ranges |
| 11400 | #11439 | 同 PR 覆盖 flatSearchCutoff |
| 11401 | #11429, #11543 | gh-11401 reject negative replicationFactor |
| 11730 | #11975 | Reject explicit empty tokenization values |
| 11732 | #12457 | gh-11732 fix silent acceptance of null/wrong-type vectorIndexConfig |
| 11741 | #11967 | gh-11741 reject empty tenant activity status |

另按人工核对：milvus 47635/47766/49059/50018 从 STALE_NO_FIX 转 TP_ACK_CLOSED_NOFIX（TP 确认未修）；52307 从 DUP 转 TP_FIXED_PR（fix PR 引用）。

## 自提 PR（milvus 63 = 61 issues + 2 PRs）

| PR | 状态 | 内容 |
|---|---|---|
| #47785 | closed（stale[bot] 关，未 merge）| "fix: add nprobe parameter validation for IVF index search"，Fixes #47729，第一版 |
| #51809 | **open** | rewrite 版（"Rewritten per reviewer feedback"），knowhere `Config::Load` 方案；**xiaofan-luan 两轮深度 review**（"happy to review again" → "Thanks for sticking with this through the rewrite"），CI 多轮全绿，按 maintainer sketch 实现 plan-level routing，待 final approve |

**论文价值**：#47729（TP_ACK_OPEN）不仅有 maintainer triage/accepted，还有我们自己提交、被 maintainer 深度 review 的修复 PR——"acknowledged" 证据链的强升级。

## 分 vendor 分布（126 条，人工核对后）

| 分类 | milvus | qdrant | weaviate | 合计 |
|---|---|---|---|---|
| TP_FIXED_PR | 12 | 8 | 8 | **28** |
| TP_ACK_OPEN | 8 | 0 | 0 | 8 |
| TP_ACK_CLOSED_NOFIX | 6 | 0 | 0 | 6 |
| TP_DUP_TRACKED | 3 | 0 | 0 | 3 |
| BY_DESIGN | 12 | 3 | 1 | 16 |
| FP_BY_DESIGN | 2 | 5 | 1 | 8 |
| FP_NOT_REPRO | 0 | 2 | 0 | 2 |
| STALE_NO_FIX | 1 | 0 | 0 | 1 |
| PENDING_SELF_LABELED | 0 | 11 | 15 | 26 |
| SELF_CLOSED | 17 | 3 | 5 | 25 |
| OPEN_NO_LABEL | 0 | 1 | 0 | 1 |
| SELF_PR_OPEN | 1 | 0 | 0 | 1 |
| SELF_PR_CLOSED | 1 | 0 | 0 | 1 |
| **合计** | **63** | 33 | 30 | **126** |
