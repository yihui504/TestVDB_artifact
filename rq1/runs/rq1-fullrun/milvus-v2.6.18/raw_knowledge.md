# milvus v2.6.18 API Knowledge

knowledge_path: source-derived derived-chain (v2.6.17 knowledge base + directory diff .milvus-src-2617 vs .milvus-src-2618 on internal/distributed/proxy/httpserver/, internal/proxy/, internal/parser/, pkg/common/, cross-validated against live v2.6.18 instance)
KNOWLEDGE_DEGRADED: false (source-derived, exact-tag trees; v2.6.18 checkout is release tag v2.6.18, commit 5aee61b "enhance: Bump milvus & proto to v2.6.18 (#50254)"; v2.6.17 tree is release v2.6.17, commit 1d584f5)
doc_coverage_pct: N/A (spec unavailable — milvus has no fetchable OpenAPI spec rule; endpoints derived from source route registration, cross-validated against live instance)

## Document Metadata
- doc_version: v2.6.18 (source tree, release v2.6.18)
- target_version: v2.6.18
- version_match: matched (source == target, exact; live docker image milvusdb/milvus:v2.6.18 confirmed via docker ps; healthz :9091 "OK")
- source_url: .milvus-src-2618/internal/distributed/proxy/httpserver/ (local source checkout, release v2.6.18)
- fetched_at: 2026-08-22T00:00:00Z
- live_validation: http://localhost:19530 (Bearer root:Milvus) running v2.6.18; all NEW 2.6.18 behaviors below live-confirmed unless marked source-only
- derived_from: results/milvus/v2.6.17/raw_knowledge.md (source-derived, same-series diff mode; chain: v2.6.12 → v2.6.16 → v2.6.17 → v2.6.18)

## Document Sources
| # | URL / Path | Doc Version | Fetched At | Version Match |
|---|------------|-------------|------------|---------------|
| 1 | .milvus-src-2618/internal/distributed/proxy/httpserver/handler_v2.go | v2.6.18 | 2026-08-22 | matched (diff vs 2617: grant/revoke_privilege_v2 hook fullMethod → OperatePrivilegeV2 (fix #48115); NO route changes — 88 v2 routes unchanged) |
| 2 | .milvus-src-2618/internal/proxy/task.go | v2.6.18 | 2026-08-22 | matched (addCollectionFieldTask: vector fields NOW ALLOWED; added field must be nullable; nullable vector must have dimension in TypeParams; vector field count < MaxVectorFieldNum(4); clustering-key type check on create) |
| 3 | .milvus-src-2618/internal/parser/planparserv2/parser_visitor.go | v2.6.18 | 2026-08-22 | matched (NEW: IsNull/IsNotNull on vector fields rejected) |
| 4 | .milvus-src-2618/internal/proxy/task_search.go | v2.6.18 | 2026-08-22 | matched (NEW: hybrid search on ArrayOfVector anns field: radius (range search), group_by, iterator each → parameter-invalid 1100) |
| 5 | .milvus-src-2618/internal/proxy/task_index.go | v2.6.18 | 2026-08-22 | matched (ArrayOfVector index metric validation refined per element type: float/binary/int metric whitelists; non-EmbList metric on AoV falls back to element-type checking) |
| 6 | .milvus-src-2618/internal/proxy/task_upsert.go + httpserver/utils.go | v2.6.18 | 2026-08-22 | matched (partial update: missing field vs explicit null now distinguished via validDataMap; partial-op on missing pk → "upsert pk %v not found in query result" 1100) |
| 7 | .milvus-src-2618/internal/distributed/proxy/httpserver/timeout_middleware.go | v2.6.18 | 2026-08-22 | matched (full rewrite of response recorder; observable REST behavior unchanged: timeout → HTTP 408 "request timeout"; Request-Timeout header semantics unchanged) |
| 8 | .milvus-src-2618/pkg/common/common.go | v2.6.18 | 2026-08-22 | matched (CurrentScalarIndexEngineVersion 2→3; CollectionTTLConfigKey="collection.ttl.seconds"; MaxTTLSeconds=3155760000) |
| 9 | .milvus-src-2618/internal/proxy/validate_util.go + task_query.go | v2.6.18 | 2026-08-22 | matched (nullable vector row-count validation via ValidData — internal execution path, no REST contract change) |
| 10 | live instance http://localhost:19530 (milvusdb/milvus:v2.6.18) | v2.6.18 | 2026-08-22 | matched (all live probes below) |

## SDK Information
- Package: pymilvus
- Version: 2.6.x series (server 2.6.18; use latest 2.6.x)
- Install: `pip install "pymilvus>=2.6.0,<2.7"`

## Docker Images
- Available tags (locally verified): v2.3.22, v2.6.10, v2.6.12, v2.6.16, v2.6.17, v2.6.18, v2.6.19, v3.0.0
- Recommended: v2.6.18

## Error Envelope Model (CRITICAL — unchanged from v2.6.17, live re-confirmed on v2.6.18)

**v2 RESTful API (`/v2/vectordb/*`)** — envelope `{code, message}` on error, `{code, data}` on success:
- Success code = 0. Live confirmed v2.6.18: `collections/create` quick → `{"code":0,"data":{}}`.
- HTTP status 200 for business responses including errors (live confirmed v2.6.18: quick-create missing dimension 1100; describe nonexistent 100; TTL alter non-integer/out-of-range 1100; fields/add violations 1100/1802; IS NULL on vector 1100).
- Missing required parameter → 1802 (live: fields/add without `schema` key → 1802 "Field validation for 'Schema' failed on the 'required' tag"); malformed JSON → 1801; resource not found → 100; DB not found → 800; true HTTP non-200 only for unknown route (404) and auth rejections.
- Many parameter-validation errors surface as 65535 (generic ErrParameterInvalid) or 1100.

**v1 RESTful (`/v1/vector/*`)** — legacy envelope, mixed model, unchanged.

**Key merr codes:** 0 success; 100 collection not found; 101 not loaded; 1100/65535 invalid parameter; 1801/1802 format/missing; 702 index duplicate; 800 database not found.

## Route Trees (source: handler_v2.go mount points — NO route changes vs v2.6.17)

Three HTTP surfaces on port 19530:
1. `/api/v1/*` — legacy management API (~47 routes, no diff)
2. `/v1/vector/*` — v1 RESTful data API (10 routes, no diff)
3. `/v2/vectordb/*` — v2 RESTful API (primary target, **88 POST routes — unchanged count; no new/removed routes in v2.6.18**)

## NEW in v2.6.18 (vs v2.6.17)

### collections/fields/add — vector fields now ALLOWED (behavior change; was rejected in ≤2.6.17)
- ≤2.6.17: adding a vector field → 1100 "not support to add vector field".
- v2.6.18 task.go addCollectionFieldTask validation order (all → 1100 unless noted):
  - field count >= MaxFieldNum(64) → "The number of fields has reached the maximum value 64"
  - adding a vector field when vectorFields >= MaxVectorFieldNum(4) → "maximum vector field's number should be limited to 4"
  - reserved/system field name (RowID/TimeStamp/$meta/namespace), PK field, partition-key field → 1100
  - **added field must be nullable** → 1100 "added field must be nullable, please check it, field name = v2" (live confirmed: non-nullable FloatVector add rejected)
  - **nullable vector field (Float/Float16/BFloat16/Binary/Int8) with no TypeParams (dimension) → 1100 "vector field must have dimension specified, field name = v4"** (live confirmed; dimension is supplied via `schema.elementTypeParams.dim`, NOT a top-level `dimension` key — top-level dim key does not populate TypeParams and also hits this 1100; live confirmed v5 with top-level dim → 1100)
  - AutoID true on non-PK add → 1100; clustering-key type check.
- Live confirmed success path: `{"collectionName":"fv_probe2","schema":{"fieldName":"v6","dataType":"FloatVector","nullable":true,"elementTypeParams":{"dim":8}}}` → code 0, field visible in describe.
- Request binding: body key is `schema` (CollectionFieldReqWithSchema, binding required) — NOT `field` (live: `field` key → 1802 Schema required).

### IS NULL / IS NOT NULL on vector fields — NEW rejection
- parser_visitor.go: `IsNull/IsNotNull operations are not supported on vector fields` (live confirmed v2.6.18: `filter:"vector IS NULL"` on entities/query → 1100 "cannot parse expression"). Scalar-field IS NULL still works (live: `id IS NULL` → code 0 empty).

### Hybrid search on ArrayOfVector (embedding list) fields — NEW restrictions
- task_search.go (hybrid path, source-verified; anns field dataType==ArrayOfVector):
  - searchParams containing `radius` (range search) → 1100 "range search is not supported for vector array (embedding list) fields in hybrid search"
  - group_by (rankParams groupByFieldId > 0) → 1100 "group by search is not supported for vector array (embedding list) fields in hybrid search"
  - iterator request → 1100 "search iterator is not supported for vector array (embedding list) fields in hybrid search"

### ArrayOfVector index metric validation refined
- task_index.go: metric whitelist now checked per element type (FloatVectorMetrics for float elements, BinaryVectorMetrics for binary, IntVectorMetrics for int); AoV with non-EmbList metric type falls back to element-type index checking (effectiveDataType) instead of blanket rejection. (source-verified; no REST route change)

### grant_privilege_v2 / revoke_privilege_v2 hook path fix (#48115)
- handler_v2.go: hook interceptor fullMethod now "OperatePrivilegeV2" (was legacy "OperatePrivilege"); denyAPI-capable hooks now see the v2 privilege op. Route, request, and response shapes unchanged.

### Partial-update semantics sharpened (insert/upsert)
- httpserver utils.go: partial update distinguishes missing field (skip) from explicit JSON null (update-to-null for nullable fields) via validDataMap; column length mismatch → error "column %s has length %d, expected %d".
- task_upsert.go: partial-op (ARRAY_APPEND/ARRAY_REMOVE) on a pk not present in existing data → 1100 "upsert pk %v not found in query result" (message changed from "primary key not found in exist data mapping").

### Internal / no REST contract change
- timeout_middleware.go fully rewritten (response recorder, context-key propagation) — observable behavior unchanged: timeout → HTTP 408 + "request timeout"; Request-Timeout header parse tolerant.
- pkg/common: CurrentScalarIndexEngineVersion 2→3 (rolling-upgrade machinery).
- validate_util/task_query: nullable vector row counting via ValidData (execution path).
- create collection: clustering key field with unsupported data type now rejected at create (schema illegal).

## GT-relevant parameter faces (contract-mandatory, B7 completeness)

### collection.ttl.seconds (collections/alter_properties path)
- Property key `collection.ttl.seconds`; value is a STRING-encoded integer (properties map).
- Validation (task.go validateCollectionTTL, live confirmed v2.6.18 on alter_properties):
  - non-integer (e.g. "abc") → 1100 "collection TTL is not a valid positive integer"
  - out of range → 1100 "collection TTL is out of range, expect [-1, 3155760000], got N"
  - **valid domain: -1 <= ttl <= 3155760000**; -1 accepted, persisted and visible in describe properties (live confirmed).
- Same validator runs on collections/create property path (task.go line 464 create / 1465 alter).

### autoID (entities/upsert path)
- `autoID` is a first-class body parameter on collections/create (CollectionReq.AutoID, default DisableAutoID) and inside schema (CollectionSchema.AutoId); it is NOT a field of the upsert request struct (CollectionDataReq = dbName/collectionName/partitionName/data/partialUpdate/fieldOps only) — an `autoID` key in upsert body is accepted and ignored (live: upsert with autoID:true → code 0).
- Live confirmed v2.6.18 behavior on autoID=true collection: upsert with user-supplied `id` in data → **code 0, NEW auto-generated id returned (upsertIds differs every call)** — user pk is ignored, each upsert inserts a new row (autoID collection cannot be true-updated via REST upsert).

## Unchanged vs v2.6.17 (reused from v2.6.17 knowledge; diff-verified no relevant change)
- All 88 v2 routes; v1 and legacy routes; envelope model.
- entities/upsert fieldOps surface: op enum {REPLACE, ARRAY_APPEND, ARRAY_REMOVE}; unknown op → 1100; ARRAY_* requires Array field (1100); PK/duplicate/missing-field/payload checks → 1100; non-REPLACE implies partialUpdate=true; v1 upsert mirrors the field.
- Filter grammar: LIKE/TEXTMATCH/PHRASEMATCH/ST* generalized args + string-literal-or-template; semantic field-type checks behind grammar unchanged.
- Hybrid index by-design override of user-specified low/high cardinality index types.
- query_mode family: alter_properties query_mode:"bogus" → 65535; alter blocked 702 with vector index; create-side query_mode not forwarded.
- Coupled large_topk quota: normal limit+offset <= 16384; large_topk <= 1000000 (live re-confirmed series).
- entities/query limit=-1 tolerated (code 0).
- users/create password 6 <= len <= 72.
- entities/insert filter key ignored; extra body keys ignored on insert/create.
- Request-Timeout header tolerant parse.
- dim <= 32768; BinaryVector dim %8==0; max 64 fields / 4 vector fields / 16 shards; ConsistencyLevel enum; warmup family; defaultValue fill; aliases/list lenient; dbName 800.

## Data Types (unchanged)
- Scalar: Bool, Int8-64, Float, Double, VarChar, JSON, Array; Vector: FloatVector, BinaryVector, Float16Vector, BFloat16Vector, SparseFloatVector, Int8Vector; ArrayOfVector (embedding list)
- EmbList metrics: MAX_SIM_COSINE, MAX_SIM_L2, MAX_SIM_IP, MAX_SIM_HAMMING, MAX_SIM_JACCARD

## Diff vs v2.6.17 (directory diff .milvus-src-2617 vs .milvus-src-2618, API-relevant dirs)
1. **No endpoint additions/removals** (88 v2 routes, 10 v1, ~47 legacy — unchanged)
2. **collections/fields/add allows vector fields (NEW)**: must be nullable (1100), nullable vector must carry dimension in elementTypeParams (1100), vector field cap 4, system/PK/partition-key adds rejected; body key is `schema`
3. **IS NULL/IS NOT NULL on vector fields → 1100 (NEW)**
4. **hybrid search on ArrayOfVector: radius/group_by/iterator → 1100 (NEW, source-verified)**
5. ArrayOfVector index metric checks per element type (refinement)
6. grant/revoke_privilege_v2 hook fullMethod → OperatePrivilegeV2 (#48115 fix)
7. partial update: missing-vs-null distinction; pk-not-found message change
8. timeout middleware rewrite (no observable REST change); CurrentScalarIndexEngineVersion 2→3
9. GT faces live-confirmed: collection.ttl.seconds [-1, 3155760000] string-integer (1100 outside); autoID face — upsert on autoID collection ignores user pk, generates new id per call (code 0)

## Missing Endpoints
None — full route registration reviewed (no diff vs v2.6.17); new 2.6.18 behaviors live-confirmed (fields/add vector rules, IS NULL vector, TTL domain, autoID upsert) or source-verified (AoV hybrid restrictions).
