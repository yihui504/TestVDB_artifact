# Defect 1: Datetime range filter silently accepts integer (UNIX-timestamp) bounds with divergent indexed/unindexed semantics

## Metadata
- Defect ID: TESTVDB-QDRANT-1
- Candidate ID: vein_type_mismatch_datetime_range_8
- Type: Type2_PoorDiagnostics
- Severity: Low（ADR-0008：severity 由 Type 推断，Type2→Low，人工分流参考）
- Endpoint: POST /collections/{collection_name}/points/count
- Discovered: 2026-08-23T15:04:30Z（R2/R3 audit 窗口，session qdrant-1180-r1）
- Chain verdict: DEFECT（chain-auditor，类型恒真：文档 RFC3339-only 却静默接受 integer 界限，indexed/unindexed 同请求分叉 193 vs 0）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: （空 — structured_contract.json 58 条约束中无 datetime range 界限类型条目，契约结构性缺失，chain_broken_at=contract）
- **contract_assertion**（文档锚补位）: 契约上游 raw_knowledge.md:1017 "Range: {lt?, gt?, gte?, lte?} numbers; datetime range supports RFC 3339 [DOC filtering]"；官方文档原文 "The datetime range is a unique range condition, used for datetime payloads, which supports RFC 3339 formats. You do not need to convert dates to UNIX timestamps."
- **expected_behavior**: datetime range 界限应为 RFC 3339 字符串；integer（UNIX timestamp）界限不在文档声明的合法值域内，应被拒绝或至少两条求值路径语义一致，而非无错接受且结果分叉
- **source_url**: https://qdrant.tech/documentation/search/filtering/

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://qdrant.tech/documentation/search/filtering/
- **doc_version**: 1.18.x（versioned，endpoint_registry 匹配 PASS）
- **doc_quote**: "The datetime range is a unique range condition, used for datetime payloads, which supports RFC 3339 formats. You do not need to convert dates to UNIX timestamps."
- **url_status**: degraded（WebFetch 对 api.qdrant.tech/qdrant.tech 均被网络策略拦截；builder 改经 mcp web-reader 成功抓取官方 canonical 页核验原文）
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: `POST {db_base}/collections/{c}/points/count`，body `{"exact": true, "filter": {"must": [{"key": "ts", "range": {"gte": 1767312000000000}}]}}`（integer 界限，对 indexed datetime 字段 ts 与 unindexed datetime 字段 raw 各发一次；对照组 string 界限 "2026-01-02T00:00:00Z"）（db_base 以原脚本 DB_URL 为准，qdrant 默认 6333）
- **HTTP Response**: indexed ts + integer 界限 → `200 {"count": 193}`；unindexed raw + 同一 integer 界限 → `200 {"count": 0}`；string RFC3339 基线两字段均 `200 {"count": 193}`
- **Container Logs**: output_vein_type_mismatch_datetime_range_8.log
  ```
  indexed ts  int:    status=200 count=193
  unindexed raw int:  status=200 count=0
  indexed ts  string: status=200 count=193
  unindexed raw str:  status=200 count=193
  VERDICT: DEFECT_FOUND — integer datetime range silently accepted with divergent semantics: indexed=193 vs unindexed=0 (string RFC3339 baseline both agree)
  ```
- **reproduced_at**: 2026-08-23（R2/R3 执行窗口；log 已落盘，reporter 本次调用无执行工具，未做 live 复跑 — 待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/lib/segment/src/types.rs#L2704-L2765
- **code_snippet**（v1.18.0 db3fca3，链内取证）:
  ```rust
  // lib/segment/src/types.rs:2704-2765
  #[serde(untagged)]
  pub enum RangeInterface { Float(Range<OrderedFloat<FloatPayloadType>>), DateTime(Range<DateTimePayloadType>) }
  // custom Deserialize: 仅当 bound 是 string 才走 DateTime；integer JSON number 落到 Float 分支，从不查询字段 schema
  ```
  未索引路径 condition_checker.rs:226-237 `Range<DateTimePayloadType>` 只对字符串 payload 生效 → integer 界限遇字符串 payload 静默不匹配（count=0）；索引路径 condition_converter.rs:346-377 integer 界限按数值与 datetime 索引内部 epoch-microseconds 同量纲比较 → count=193。两条通路无统一类型校验（validation_absent）。

## Completeness Check
- Ring 1: MISSING（契约无对应条目；以文档原文 + 源码双锚补位，chain-auditor 已终判 DEFECT）
- Ring 2: DEGRADED（domain_blocked，alternate reader 核验）
- Ring 3: PRESENT
- **Overall**: INCOMPLETE_EVIDENCE（仅 Ring 1 契约环缺失；doc/script/log/source 四环完整互洽）

## Reproduction Steps
1. 建集合，payload 含 datetime 字段 ts（建 payload index）与 datetime 字段 raw（不建索引），写入 200 点 RFC3339 字符串（匹配子集 193）。
2. `POST /collections/{c}/points/count` exact=true，filter range.gte=1767312000000000（integer）对 ts → 200 count=193。
3. 同请求对 raw → 200 count=0。
4. 对照：range.gte="2026-01-02T00:00:00Z"（string）两字段均 200 count=193（基线一致，排除环境/索引时序）。

## Impact Analysis
用户按文档"不需转 UNIX timestamp"的相反方向传 integer 界限时得不到任何错误：indexed 字段返回与字符串基线巧合一致的正确计数（193），unindexed 字段静默返回 0 —— 同一请求在两个字段上结果相反且均无告警。基于 unindexed 字段的过滤管道会静默丢数据（假阴性），且无日志/错误码可诊断，属正确性 + 诊断性双重缺失。

## Original Execution Log
- Log: `output_vein_type_mismatch_datetime_range_8.log`（含 VERDICT 行）
- Script: `vein_scripts/vein_type_mismatch_datetime_range_8.py`

## MRE
- Script: `defect-1-script.py`（reporter-mre Agent 产出）
- Run: `python defect-1-script.py`
