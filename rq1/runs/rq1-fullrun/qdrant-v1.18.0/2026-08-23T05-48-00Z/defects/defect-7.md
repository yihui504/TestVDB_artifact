# Defect 7: min_should with empty conditions and min_count>=1 silently matches ENTIRE collection (count/scroll/query) instead of match-none

## Metadata
- Defect ID: TESTVDB-QDRANT-7
- Candidate ID: vein_compound_or_min_should_15
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断，人工分流参考）
- Endpoint: POST /collections/{collection_name}/points/count (+ /points/scroll, /points/query)
- Discovered: 2026-08-23T17:54:53Z（R4-b2 批）
- Chain verdict: DEFECT（C=CONFIRMED + D=SUPPORTS_DEFECT：优化器静默丢弃子句；v1.19 已改 match-none；认知盲区字面点名 min_should 校验）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: （空 — vein 派生候选；chunks.json 0 个 min_should 命中，契约结构性空白，chain_broken_at=contract）
- **contract_assertion**（doc+source 双补位）: 文档 should 语义 "When using should, the clause becomes true if at least one condition listed inside should is satisfied. In this sense, should is equivalent to the operator OR."（min_count=1 是其最小特例）；源码 in-tree 注释 v1.18.0 query_estimator.rs:156-160 "Estimate cardinality for min_should (at least min_count conditions). Returns zero immediately when min_count exceeds the number of estimations, which matches filter semantics"
- **expected_behavior**: `{"min_should":{"conditions":[],"min_count":1}}` 语义上不可满足（0 个条件中至少匹配 1 个），对每个点应为 false → 返回 0 结果（v1.19.0 上游已改为 Ok(false)）
- **source_url**: https://qdrant.tech/documentation/concepts/filtering/

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://qdrant.tech/documentation/concepts/filtering/（live 页 301 重定向至 /documentation/search/filtering/，可达）
- **doc_version**: live 页为 current（含 v1.19.0 特性 Prefix Match/Slice，非 1.18.0 钉版）；v1.18 时代本地抽取 concepts_filtering.txt 同文
- **doc_quote**: "When using should, the clause becomes true if at least one condition listed inside should is satisfied."（min_should 本身无 prose 文档——live 与 v1.18 快照均 0 次提及，仅经 REST/OpenAPI schema 暴露）
- **url_status**: degraded（WebFetch domain_blocked，经 alternate web reader 抓取成功）
- **version_match**: mismatched（live 为 current 版；should 语义两版一致）

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: `POST {db_base}/collections/vein_c15/points/count`，body `{"exact": true, "filter": {"min_should": {"conditions": [], "min_count": 1}}}`（另发 /points/scroll limit=100 与 /points/query 同 filter；3 组对照）（db_base 以原脚本 DB_URL 为准）
- **HTTP Response**: `200 {"count": 10}` 且 scroll 返回全部 id [0..9]（集合共 10 点 = match-all）；query 同 filter `200 n=10`
- **Container Logs**: output_vein_compound_or_min_should_15.log
  ```
  min_should empty conditions min_count=1: status=200 count=10 ids=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
  control min_count=0 empty: status=200 count=10
  control 2 real conds min_count=2: count=1 ids=[8] (expect [8])
  control 3 real conds min_count=1: count=7 ids=[1, 2, 4, 5, 7, 8, 9] (union of cat=a and num>=8)
  query with empty min_should: status=200 n=10
  VERDICT: DEFECT_FOUND — min_should with conditions=[] and min_count=1 returns the ENTIRE collection (match-all) on count/scroll/query, though it is unsatisfiable; real-condition controls behave correctly, isolating the empty-conditions edge
  ```
  对照组证明服务端正确解析并求值了真条件 min_should（min_count=2 恰 [8]、min_count=1 恰 7 元素并集），缺陷被隔离在空 conditions 边界。
- **reproduced_at**: 2026-08-23（R4 执行窗口；log 已落盘，待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/lib/segment/src/index/query_optimization/optimizer.rs#L59-L79
- **code_snippet**（链内取证 — ROOT CAUSE）:
  ```rust
  // optimizer.rs:59-79 (v1.18.0)
  min_should: if let Some(MinShould { conditions, min_count }) = filter.min_should.as_ref()
      && !conditions.is_empty()          // <-- 空 conditions：整个 min_should 子句被丢弃，min_count 被无视
  { … Some(OptimizedMinShould { … }) } else { None },
  // optimized_filter.rs:27-32 + 49-52: check_min_should: None => true  // 丢弃的子句对每个点恒真
  // 对照（同树三处正确语义）：query_checker.rs:56-75 精确检查 0==1 => false
  //   query_estimator.rs:161-169 min_count>len => exact(0) "matches filter semantics"
  //   v1.19.0 optimized_filter.rs check(): "Not enough conditions to match min_count" => Ok(false)
  ```
  MinShould 结构体仅 nested-validate conditions，无 min_count<=len 校验 → 无 400 拒绝可能；优化路径是唯一判错的分支且 v1.19.0 已修复为 match-none。

## Completeness Check
- Ring 1: MISSING（契约/chunks 均无 min_should 条目；doc should 语义 + 源码三处 in-tree 语义锚补位）
- Ring 2: DEGRADED（min_should 无 prose 文档，0 提及——undocumented-feature 边缘）
- Ring 3: PRESENT（主观测 + 3 组数学正确对照 + 跨 3 端点复现）
- **Overall**: INCOMPLETE_EVIDENCE（契约环缺失；源码三方矛盾 + 上游 v1.19 修复佐证缺陷定性）

## Reproduction Steps
1. 建集合 vein_c15 写入 10 点。
2. `POST /points/count` exact=true，body filter `{"min_should":{"conditions":[],"min_count":1}}` → `200 count=10`（应为 0）。
3. 同 filter 发 /points/scroll → 返回全部 10 点；/points/query → n=10。
4. 对照：真条件 min_count=2 → 恰 [8]；min_count=1 → 恰 7 元素并集（真条件路径正确）。

## Impact Analysis
程序化构造 filter 的客户端（ORM/查询构建器把空数组折叠进 min_should）会得到"全库匹配"——方向性最危险的失败模式：本应过滤到 0 的查询返回全量数据，下游按"全命中"处理造成误删、误批、全量推送。三端点（count/scroll/query）同错，无错误码无告警。v1.19.0 上游已把该边界改为 match-none，确认 v1.18.0 行为非预期。

## Original Execution Log
- Log: `output_vein_compound_or_min_should_15.log`（含 VERDICT 行）
- Script: `vein_scripts/vein_compound_or_min_should_15.py`

## MRE
- Script: `defect-7-script.py`（reporter-mre Agent 产出）
- Run: `python defect-7-script.py`
