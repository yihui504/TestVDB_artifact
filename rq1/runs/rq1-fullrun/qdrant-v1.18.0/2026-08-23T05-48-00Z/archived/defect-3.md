# Defect 3: Approximate count (exact=false) returns N/2 constant for type-mismatched match values where exact path returns 0

## Metadata
- Defect ID: TESTVDB-QDRANT-3
- Candidate ID: vein_type_mismatch_points_count_2
- Type: Type2_PoorDiagnostics
- Severity: Low（Type2 推断，人工分流参考）
- Endpoint: POST /collections/{collection_name}/points/count (exact=false, filter.must[].match.value type-mismatched vs field index schema)
- Discovered: 2026-08-23T15:04:30Z（R2/R3 audit 窗口）
- Chain verdict: DEFECT（类型恒真：integer 字段接受字符串 '50' 匹配且 approx 返回 100=truth 0 的 N/2；同类型对照两路径一致排除环境因素，validation_absent）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: qdrant_behavioral_points_count_001
- **contract_assertion**: "count with exact=true gives exact count; 200 {count}; 404 collection missing"（category: HTTP 200 {count}; source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points）+ 源码 doc comment（lib/shard/src/count.rs CountRequestInternal）：exact=false = "count approximate number of points faster"，仅豁免 "unreliable during the indexing process"
- **expected_behavior**: approximate 是同一 filter 语义的更快近似路径；对永不可能命中的合法输入（类型错配 match 值，Match value 契约域 string|int64|bool）应返回保守估计（邻近可行实现为 0），不得返回与 exact/scroll 结构性矛盾的半总量 N/2
- **source_url**: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points
- **doc_version**: 1.18.x（versioned，== 1.18.0）
- **doc_quote**: "count approximate number of points faster" / "Approximate count might be unreliable during the indexing process"（仅索引期豁免）；filtering 文档 Match oneOf value (string|int64|bool) — 契约允许任意标量类型
- **url_status**: degraded（WebFetch 两文档域 domain_blocked；本地契约上游 raw_knowledge.md（1.18.x）+ 源码 doc comment 佐证）
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: `POST {db_base}/collections/{c}/points/count`，body `{"exact": false, "filter": {"must": [{"key": "num", "match": {"value": "50"}}]}}`（integer 索引字段 num 传字符串；同型 bool→int、int→keyword 两方向交叉）（db_base 以原脚本 DB_URL 为准）
- **HTTP Response**: num match '50' (str) → exact 路径 `200 {"count": 0}`（scroll 交叉亦 0），approximate `200 {"count": 100}`（= N/2，N=200）；三方向错配全部 exact=0 / approx=100
- **Container Logs**: output_vein_type_mismatch_points_count_2.log
  ```
  num match '50' (str): exact=0 approx=100
  num match true (bool): exact=0 approx=100
  cat match 5 (int): exact=0 approx=100
  CONTROL num match 50 (int): exact=4 approx=4
  VERDICT: DEFECT_FOUND — approximate count silently returns ~N/2 for type-mismatched match values where exact path and scroll return 0
  ```
- **reproduced_at**: 2026-08-23（R2/R3 执行窗口；log 已落盘，待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/lib/segment/src/index/field_index/mod.rs#L68-L96
- **code_snippet**（链内取证）:
  ```rust
  // field_index/mod.rs:82-96
  pub const fn unknown(total: usize) -> Self {
      CardinalityEstimation { primary_clauses: vec![], min: 0, exp: total / 2, max: total }  // <-- N/2
  }
  // map_index/mod.rs:794-805 (keyword MapIndex estimate_cardinality): Integer(_)/Bool(_) => None
  // struct_payload_index.rs:445-448: .unwrap_or_else(|| CardinalityEstimation::unknown(self.available_point_count()))
  // shard_ops.rs:384-387 (count, exact=false): estimate_cardinality(...).map(|c| c.exp)  // .exp 直接作为 count 返回
  ```
  调用链：map_index estimate_cardinality 对类型不符变体返回 None → 上层 unknown(total).exp=total/2 静默替换 → 直接作为 count。对照组（同类型匹配）走 match_cardinality → exact(count)。观测 100 = 200/2 精确吻合，机制闭环。

## Completeness Check
- Ring 1: PRESENT（qdrant_behavioral_points_count_001，机械 A 引文核对一致）
- Ring 2: DEGRADED
- Ring 3: PRESENT（脚本内 3 个独立错配方向 + 对照组）
- **Overall**: COMPLETE

## Reproduction Steps
1. 建集合 200 点（num randint 0-100 integer 索引，cat keyword 索引）。
2. `POST /points/count` exact=true，num match "50"（字符串）→ `200 count=0`。
3. 同 filter exact=false → `200 count=100`。
4. 对照 num match 50（int，真值 4）→ exact=4 approx=4；bool→int、int→keyword 方向同型复现。

## Impact Analysis
调用方以 exact=false 做快速计数（容量规划、监控、分页估算）时，任何类型错配的 filter 值都得到"约一半数据匹配"的常数估计——与真值 0 完全无关。错误方向是系统性高估（最多 100×），且 HTTP 200 正常返回，无任何告警。同文件存在保守 0 估计先例（match_cardinality miss 的 unwrap_or(0)），精确 0 是邻近可行实现。

## Original Execution Log
- Log: `output_vein_type_mismatch_points_count_2.log`（含 VERDICT 行）
- Script: `vein_scripts/vein_type_mismatch_points_count_2.py`

## MRE
- Script: `defect-3-script.py`（reporter-mre Agent 产出）
- Run: `python defect-3-script.py`
