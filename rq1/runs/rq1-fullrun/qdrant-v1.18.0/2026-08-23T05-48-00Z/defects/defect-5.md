# Defect 5: Vector components beyond f32 range accepted (200), stored as inf/NaN, read back as null and ranked top with null score

## Metadata
- Defect ID: TESTVDB-QDRANT-5
- Candidate ID: vein_f32_overflow_vector_13
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断，人工分流参考）
- Endpoint: PUT /collections/{collection_name}/points + POST /collections/{collection_name}/points/query + POST /collections/{collection_name}/points (read-back)
- Discovered: 2026-08-23T15:04:30Z（R2/R3 audit 窗口）
- Chain verdict: DEFECT（机械 B=CONFIRMED：HTTP 语义恒真 — 200 接受超 f32 分量而契约 query_001 声称 400；score null 违反 required+number 且排第一）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: qdrant_behavioral_points_query_001（builder 手动绑定 — 派发条目 constraint_id 为空串，机械提取未绑定）+ data_types.DenseVector
- **contract_assertion**: "200 QueryResponse {result: [ScoredPoint], next_page_offset?}; 400 invalid query; 404 collection"（endpoint points+query，source_url https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points，doc_version 1.18.x versioned）；data_types.DenseVector: "fixed-length float array matching collection size; float32 default"
- **expected_behavior**: ScoredPoint.score 为 required number（OpenAPI schema）；超出 f32 表示范围的请求分量（f64 合法 JSON number）应被 400 拒绝或至少不产生违反自身 schema 的 null 输出
- **source_url**: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://qdrant.tech/documentation/concepts/vectors/（concepts 快照 tmp_gen/qdrant118/，契约构建期抓取）
- **doc_version**: 1.18.x（concepts 同批；OpenAPI spec.json info.version=1.0.0 系 qdrant 惯例无法精确钉版本 → PARTIAL）
- **doc_quote**: concepts_vectors.txt L1717 "By default, Qdrant stores each vector dimension as a 32-bit floating-point number." / L1722 "It is a 32-bit (4 bytes) floating point number."；OpenAPI ScoredPoint: score {type: number, format: double}, required: [id, version, score]；VectorStruct oneOf 第一支 {type: array, items: {type: number, format: double}} — 请求侧 1e300 是合法 JSON number
- **url_status**: degraded（WebFetch 两域 domain_blocked；以契约构建期本地快照 + raw_knowledge 佐证）
- **version_match**: mismatched（PARTIAL：concepts 匹配，OpenAPI 版本号无法钉定；doc 对超 f32 范围输入行为为纯空白——无 reject/clamp/saturate 任何字样）

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: `PUT {db_base}/collections/{c}/points` body `{"points":[{"id":999,"vector":[1e300,1e300,1e300,1e300]}]}`（wait=true；对照点 id=0 正常向量）；随后 `POST /points` read-back with_vector 与 `POST /points/query` 正常查询向量（db_base 以原脚本 DB_URL 为准）
- **HTTP Response**: upsert → `200 (accepted)`；read-back id=999 → vector `[null, null, null, null]`（对照 id=0 数值正常，同响应内对照）；正常查询 top3 → `[(999, null), (5, 0.9892007), (1, 0.970391)]` — null score 点排在真实匹配之上
- **Container Logs**: output_vein_f32_overflow_vector_13.log
  ```
  upsert with 1e300 components: 200 (accepted)
  read-back id=999 vector: [None, None, None, None]
  read-back id=0   vector (control): [0.47472346, 0.20748034, 0.7965247, 0.31166944]
  normal query top3: [(999, None), (5, 0.9892007), (1, 0.970391)]
  query [1e300 x4] scores: [None, None, None]
  query at f32max scores: [None, 0.0, 0.0] | 3.5e38 scores: [None, None, None]
  VERDICT: DEFECT_FOUND — vector components beyond f32 range silently accepted (stored as inf), read back as null components, and produce null scores ranked above exact matches; score schema violated
  ```
  边界吻合：f32::MAX=3.4028235e38 处 score=0.0 正常，超界（3.5e38）全 null。
- **reproduced_at**: 2026-08-23（R2/R3 执行窗口；log 已落盘，待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/lib/api/src/rest/schema.rs#L48-L59
- **code_snippet**（链内取证）:
  ```rust
  // rest/schema.rs L48-59 — REST 层唯一向量内容校验，Dense 分支完全放行
  impl Validate for Vector {
      fn validate(&self) -> Result<(), validator::ValidationErrors> {
          match self { Vector::Dense(_) => Ok(()),   // <-- 无 finite/range/NaN 检查
  // spaces/simple.rs:228-235 cosine_preprocess: [inf x4] → length=inf → inf/inf = NaN（静默产生 NaN 存储）
  // common/types.rs:14-25 ScoredPointOffset Ord = OrderedFloat（ordered-float 5.3.0 总序：NaN 视为最大）
  //   → FixedLengthPriorityQueue(BinaryHeap) NaN score 点排 top 第一
  ```
  写入三道关卡全部无分量值校验：(a) REST Validate Dense→Ok(())；(b) check_vector_against_config 只查维度；(c) cosine_preprocess 对溢出无防护。全 lib 树 is_finite 仅在 quantization/formula-scorer/测试，不在 upsert 校验或 cosine 路径。输出侧 score 为非 Option f32 且无 non-finite 守卫 → NaN 经 serde_json 序列化为 null。

## Completeness Check
- Ring 1: PRESENT（qdrant_behavioral_points_query_001 + DenseVector，builder 手动绑定、auditor 复核）
- Ring 2: DEGRADED（快照佐证；OpenAPI 版本钉定 PARTIAL）
- Ring 3: PRESENT（upsert/read-back/query/边界四组观测互相印证）
- **Overall**: COMPLETE

## Reproduction Steps
1. 建集合（size=4, Cosine），正常写入若干点 + `PUT /points` id=999 vector=[1e300 x4] → `200`。
2. `POST /points` with_vector 读回 id=999 → `[null,null,null,null]`。
3. `POST /points/query` 以正常向量查询 top3 → 第一名 (999, null)，压过真实匹配。
4. 边界：查询向量取 f32::MAX x4 → score 0.0 正常；取 3.5e38 x4 → 全 null。

## Impact Analysis
上游数据管道一旦送入超 f32 范围分量（f64 合法值，如未归一化的原始特征、爆炸的 embedding），毒点被 200 接受且此后的每次查询都被它污染：null score 排第一名，真实 top-K 被挤出。读回的 null 分量违反自身 OpenAPI schema（vector array of number），客户端反序列化可能直接崩溃。全程无错误信号，污染不可诊断。

## Original Execution Log
- Log: `output_vein_f32_overflow_vector_13.log`（含 VERDICT 行）
- Script: `vein_scripts/vein_f32_overflow_vector_13.py`

## MRE
- Script: `defect-5-script.py`（reporter-mre Agent 产出）
- Run: `python defect-5-script.py`
