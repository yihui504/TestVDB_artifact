# Defect 4: PUT /collections accepts illegal datatype values (int4/null/123) with 200 — serde untagged fallback swallows enum error

## Metadata
- Defect ID: TESTVDB-QDRANT-4
- Candidate ID: boundary_collections_create_03
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断，人工分流参考）
- Endpoint: PUT /collections/{collection_name}
- Discovered: 2026-08-23T15:04:30Z（R2/R3 audit 窗口）
- Chain verdict: DEFECT（机械 A=CONFIRMED：constraint qdrant_type_collections_create_007 引文原文一致，datatype='int4' 200 接受 → implied_verdict=DEFECT 定案；serde untagged 回退吞枚举错误，validation_absent）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: qdrant_type_collections_create_007
- **contract_assertion**: "datatype IN {float32, uint8, float16, turbo4}; turbo4 NOT allowed for sparse vectors"（evidence_tier=explicit，source_url=qdrant.tech/documentation/concepts/vectors/）
- **expected_behavior**: datatype 不在枚举集（如 'int4'）应被 4xx 拒绝；不得以 200 建立集合并静默丢弃该配置
- **source_url**: https://qdrant.tech/documentation/concepts/vectors/

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://qdrant.tech/documentation/concepts/vectors/
- **doc_version**: 页面为 latest（含 v1.19.0 才引入的 Turbo4 段落）与 target v1.18.0 宽松匹配（major.minor 向上漂移）
- **doc_quote**: "configure a per-vector datatype: Float32 (default), Float16, Uint8, or Turbo4" / "The turbo4 datatype is only supported for dense vectors. It cannot be used to configure sparse vectors."；v1.18.0 本地 openapi.json Datatype enum 仅 {float32,uint8,float16}——按 v1.18.0 正式契约口径 'int4' 依旧是非法值，Type1 判定不受版本漂移影响
- **url_status**: verified（builder curl 200 可达；api.qdrant.tech v-1-18-x create-collection 渲染页亦 200 可达）
- **version_match**: mismatched（doc latest 含 turbo4 vs v1.18.0 openapi 不含；枚举集差异已在判定中按 v1.18.0 口径处理）

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: `PUT {db_base}/collections/bnd_crt_sp_1`，body `{"vectors": {"size": 4, "distance": "Cosine"}, "datatype": "int4"}`（单向量模式；另测 datatype=null / 123）（db_base 以原脚本 DB_URL 为准）
- **HTTP Response**: `200 {"result": true, "status": "ok", "time": 0.272372254}`；DESCRIBE 回读 config.params.vectors 不含 datatype 字段（值未持久化，静默丢弃，回落 float32 默认）
- **Container Logs**: output_boundary_collections_create_03.log
  ```
  CASE datatype=int4 invalid: status=200 body={"result":true,"status":"ok","time":0.220516008}
  VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — datatype=int4 invalid accepted with 200
  ```
  对照（同 v1.18.0 实例）：Multi 模式 vectors.v.datatype="zzz" → `400 "data did not match any variant of untagged enum VectorsConfig"`；sparse index.datatype="turbo4" → `400 "unknown variant turbo4, expected one of float32, uint8, float16"`——枚举校验在类型化路径存在、在 untagged 回退路径被吞。
- **reproduced_at**: 2026-08-23（R2/R3 执行窗口；builder 本机 v1.18.0 commit db3fca3 复测同结果；log 已落盘，待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/lib/collection/src/operations/types.rs#L1468-L1473
- **code_snippet**（链内取证）:
  ```rust
  // operations/types.rs:1468-1473
  #[serde(rename_all = "snake_case", untagged)]
  pub enum VectorsConfig { Single(VectorParams), Multi(BTreeMap<VectorNameBuf, VectorParams>) }
  // types.rs:1361-1371 VectorParams.datatype: Option<Datatype>（Datatype enum 仅 Float32/Uint8/Float16）
  ```
  机制：Single 变体含非法 datatype 时反序列化失败 → untagged 回退尝试 → 非法枚举值在回退路径被吞，datatype=None，200 建库。全仓库 deny_unknown_fields 命中 0 处（次观测 sp.distance/size 静默丢弃同源）。非显式 default 逻辑（对比 boundary_02 convert(None)=>OneBit 有明确意图），属 serde untagged 意外回退副作用：既未拒绝也未有意默认——"非法输入被当成功接受"。

## Completeness Check
- Ring 1: PRESENT（qdrant_type_collections_create_007，机械 A 判 CONFIRMED 定案）
- Ring 2: PRESENT（verified；version 漂移已披露）
- Ring 3: PRESENT（含 Multi/sparse 类型化路径 400 对照）
- **Overall**: COMPLETE

## Reproduction Steps
1. `PUT /collections/t1` body `{"vectors":{"size":4,"distance":"Cosine"},"datatype":"int4"}` → `200 result:true`。
2. `GET /collections/t1` → config.params.vectors 无 datatype 字段（配置被丢弃）。
3. 对照：`PUT /collections/t2` body `{"vectors":{"v":{"size":4,"distance":"Cosine","datatype":"zzz"}}}` → `400 untagged enum VectorsConfig`（同值在 Multi 模式被正确拒绝）。

## Impact Analysis
用户显式请求的存储类型配置（如 uint8 省内存场景拼错为 "unit8"）被静默忽略并以默认 float32 建库：无错误、无告警、DESCRIBE 里配置消失。存储占用与预期不符（float32 4 字节 vs uint8 1 字节），且错误在创建时不可发现。多向量模式同值却 400，行为分叉加深迷惑。

## Original Execution Log
- Log: `output_boundary_collections_create_03.log`（含 VERDICT 行）
- Script: `boundary_collections_create_03.py`（boundary 派发脚本，会话脚本区）

## MRE
- Script: `defect-4-script.py`（reporter-mre Agent 产出）
- Run: `python defect-4-script.py`
