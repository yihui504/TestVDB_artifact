# Defect 2: Geo filter with exact pole latitude ±90 silently returns 0 results on indexed path (geohash bit-collapse)

## Metadata
- Execution Log: `output_vein_geo_filter_scroll_order_6.log`（全文首个 output_*.log 引用 — 主验证 log，含 VERDICT 行）
- Execution Script: `vein_scripts/vein_geo_filter_scroll_order_6.py`
- Defect ID: TESTVDB-QDRANT-2
- Candidate ID: vein_geo_filter_scroll_order_6
- Type: Type2_PoorDiagnostics
- Severity: Low（Type2 推断；chain-auditor + builder 双双建议人工复核 — 极点边界 bug 信号强）
- Endpoint: POST /collections/{collection_name}/points/count + POST /collections/{collection_name}/points/scroll（filter: geo_bounding_box / geo_polygon，geo payload index present）
- Discovered: 2026-08-23T15:04:30Z（R2 窗口；round2 补证 2026-08-23T13:45:44Z）
- Chain verdict: DEFECT（C=CONFIRMED；D 认知盲区 "Filter condition validation gaps" 现象级命中；根因 geohash 位折叠）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: （NONE — geo filter lat 数值域未结构化入契约，结构性缺失，chain_broken_at=contract；工单明示勿再向契约要锚点）
- **contract_assertion**（doc+source 双补位）: raw_knowledge.md L1018 "GeoBoundingBox {top_left:{lon,lat}, bottom_right:{lon,lat}}; GeoRadius {center:{lon,lat}, radius: meters}; GeoPolygon {exterior:{points:[GeoPoint]}, interiors?}"；L1013 "geo ({lon, lat} doubles)"；源码 types.rs:1919-1930 `GeoPoint::validate` 闭区间 `(min_lat..=max_lat).contains(&lat)`，min/max=±90.0 → lat=90.0 是显式接受的合法输入
- **expected_behavior**: 合法闭区间 lat=90 的 geo_bounding_box/geo_polygon 查询应返回与 unindexed 路径一致的正确结果（bbox 10/50、polygon 40/50）
- **source_url**: https://qdrant.tech/documentation/concepts/filtering/

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://qdrant.tech/documentation/concepts/filtering/（endpoint_registry: api.qdrant.tech/v-1-18-x/.../count-points）
- **doc_version**: 1.18.x（versioned）
- **doc_quote**: "GeoBoundingBox {top_left:{lon,lat}, bottom_right:{lon,lat}} … GeoPolygon {exterior:{points:[GeoPoint]}, interiors?}"（DOC filtering 节）；"geo ({lon, lat} doubles)"（DOC payload 节）— 文档将 lat 定义为普通 double，未排除 ±90 端点
- **url_status**: degraded（api.qdrant.tech 直连 domain_blocked；endpoint_registry 查表 + raw_knowledge.md 原文核对一致）
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)

**主观测（原 attack 脚本，机械验证目标 log）**：
- **HTTP Request**: `POST {db_base}/collections/vein_r2c6/points/count`，body `{"exact": true, "filter": {"must": [{"key": "loc", "geo_bounding_box": {"top_left": {"lon": 10.0, "lat": 90.0}, "bottom_right": {"lon": 14.0, "lat": 40.0}}}]}}`（geo index 已建；polygon 顶点 lat=90.0 同型；对照 lat=89.9999）（db_base 以原脚本 DB_URL 为准）
- **HTTP Response**: indexed bbox lat=90.0 → `200 {"count": 0}`；对照 lat=89.9999 → `200 {"count": 10}`；indexed polygon pole → `200 {"count": 0}` vs 对照 `200 {"count": 40}`
- **Container Logs（主验证 log，含标准 VERDICT 行）**: `output_vein_geo_filter_scroll_order_6.log` 全文观测行：
  ```
  bbox top lat=90.0: 200 count=0
  bbox top lat=89.9999 (control): 200 count=10
  polygon pole vertex lat=90.0: 200 count=0
  polygon pole vertex 89.9999 (control): 200 count=40
  VERDICT: DEFECT_FOUND — geo bbox/polygon with exact north-pole latitude 90.0 (valid input) returns 0; 89.9999 returns all matches
  ```
  与 evidence_chain/vein_geo_filter_scroll_order_6.json 的 execution_evidence.log_pattern（"bbox top lat=90.0: 200 count=0（主违规观测：indexed 路径，集合 vein_r2c6，geo payload index 已建）"）一致。

**补证观测（builder rework2 脚本，无标准 VERDICT 行 — 非机械验证目标）**：
- `output_rework2_vein_geo_filter_scroll_order_6.log`（16 组请求：2 集合 × {count,scroll} × {box,box_ctl,poly,poly_ctl}，含服务端 payload_schema 双向验证 `[vein_r2c6_unidx] payload_schema = {}` / `[vein_r2c6_idx2] payload_schema = {"loc": {"data_type": "geo", "points": 50}}`）关键行：
  ```
  == (1) UNINDEXED control (no geo payload index) ==
  unindexed count box_pole: 200 count=10
  unindexed count poly_pole: 200 count=40
  == (2) scroll ground truth on UNINDEXED ==
  unindexed scroll box_pole: 200 points=10
  unindexed scroll poly_pole: 200 points=40
  == (3) INDEXED (geo payload index present) re-run + scroll ==
  indexed count box_pole: 200 count=0
  indexed count poly_pole: 200 count=0
  == (4) scroll on INDEXED ==
  indexed scroll box_pole: 200 points=0
  indexed scroll poly_pole: 200 points=0
  ```
  即：unindexed 路径 count/scroll 均返回正确 10/40（地面真值），indexed 路径同请求归零 — 缺陷为 geo index 路径专属，独立集合（vein_r2c6_idx2）重建后同模式复现。
- **reproduced_at**: 2026-08-23（R2 原始执行 + rework2 补证双轮；两份 log 均已落盘，主验证 log 的 VERDICT 行待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/lib/segment/src/index/field_index/geo_hash.rs#L50-L69
- **code_snippet**（链内取证）:
  ```rust
  // geo_hash.rs:57-58 — 开区间，==90 不修正
  const LAT_RANGE: Range<f64> = -90.0..90.0;
  // GeohashBoundingBox::from (343-358): north_west = encode_max_precision(min_lon, max_lat=90.0)
  //   → geohash 0.13.1 encode 归一化 lat*0.0055…+1.5 == 2.0 越出位提取假定域 [1,2)，位折叠 lat32=0
  //   （数值复算：lat=90 与 lat=-90 同产退化 hash '80bh2n0p0581'；89.9999 lat32=4294964909 正常）
  ```
  indexed 分支 geo_index/mod.rs:544-583 filter → rectangle_hashes/polygon_hashes → 候选网格不覆盖数据点 → iterator 空 → count/scroll 均 0；unindexed 分支 condition_checker.rs:245-296 ValueChecker 直接 check_point（types.rs:2880-2891 对 top=90/数据 40-44 判真）→ 正确 10/40。三层语义不一致：validate 闭区间接受 / LAT_RANGE 开区间不修正 / geohash 位提取假定 [1,2)。

## Completeness Check
- Ring 1: MISSING（契约无 geo lat 域条目；doc 结构 + GeoPoint::validate 闭区间语义补位）
- Ring 2: DEGRADED
- Ring 3: PRESENT（主观测 log 含 VERDICT 行 + rework2 补证 16 组对照）
- **Overall**: INCOMPLETE_EVIDENCE（仅契约环缺失；doc/script/log/source 双分支闭环自洽，chain-auditor 终判 DEFECT）

## Reproduction Steps
1. 建两集合（vein_r2c6 indexed / vein_r2c6_unidx unindexed），各 50 点 geo payload（lon 10-14, lat 40-44），其一建 `{"data_type":"geo"}` payload index。
2. `POST /points/count` exact=true，geo_bounding_box top_left.lat=90.0（含数据区）→ indexed `200 count=0`，unindexed `200 count=10`。
3. geo_polygon 外环顶点含 lat=90.0 → indexed `200 count=0`，unindexed `200 count=40`。
4. 对照 lat=89.9999：两集合均返回正确 10/40；scroll 同型（indexed 0 / unindexed 10,40）；独立集合重建复现（rework2 (3)(4) 段）。

## Impact Analysis
任何覆盖极点的合法 bbox/polygon 查询（极地数据、全球包围盒 top=90 是最常见写法）在字段建了 geo index 后静默返回空集/零计数——假阴性无错误、无日志。同数据去掉索引反而正确，用户无从诊断。影响 count 与 scroll（同源 filter 路径），数据不可见可能导致上层逻辑误判"无数据"。

## Original Execution Log
- Log: `output_vein_geo_filter_scroll_order_6.log`（**主验证 log，含标准 VERDICT 行 — verify_defects.py 机械验证以此文件为准**）
- Script: `vein_scripts/vein_geo_filter_scroll_order_6.py`（原 attack 脚本）
- 补证（非机械验证目标，不产标准 VERDICT 行）: `vein_scripts/rework2_vein_geo_filter_scroll_order_6.py` + `output_rework2_vein_geo_filter_scroll_order_6.log`（builder round2 补证：unindexed 对照 + scroll 地面真值 + 独立集合复现）

## MRE
- Script: `defect-2-script.py`（reporter-mre Agent 产出）
- Run: `python defect-2-script.py`
