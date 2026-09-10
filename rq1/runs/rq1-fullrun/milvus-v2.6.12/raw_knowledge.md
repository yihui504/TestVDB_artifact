# milvus v2.6.12 API Knowledge

knowledge_path: source-derived (v2.6.10 base + git diff v2.6.10..v2.6.12 on httpserver/, internal/proxy/, internal/parser/, pkg/common/, cross-validated against live v2.6.12 instance)
KNOWLEDGE_DEGRADED: false (source-derived, exact-tag diff; no version drift — source checkout == release v2.6.12, commit fe3558a "Bump milvus & proto to v2.6.12 (#48063)")
doc_coverage_pct: N/A (spec unavailable — milvus has no fetchable OpenAPI spec rule; endpoints derived from source route registration, cross-validated against live instance)

## Document Metadata
- doc_version: v2.6.12 (source tree, release v2.6.12)
- target_version: v2.6.12
- version_match: matched (source == target, exact)
- source_url: .milvus-src-2612/internal/distributed/proxy/httpserver/ (local source checkout, release v2.6.12)
- fetched_at: 2026-08-22T00:00:00Z
- live_validation: http://localhost:19530 (Bearer root:Milvus) running v2.6.12; healthz :9091 OK
- derived_from: results/milvus/v2.6.10/raw_knowledge.md (source-derived, same-series diff mode)

## Document Sources
| # | URL / Path | Doc Version | Fetched At | Version Match |
|---|------------|-------------|------------|---------------|
| 1 | .milvus-src-2612/internal/distributed/proxy/httpserver/handler.go | v2.6.12 | 2026-08-22 | matched |
| 2 | .milvus-src-2612/internal/distributed/proxy/httpserver/handler_v1.go | v2.6.12 | 2026-08-22 | matched |
| 3 | .milvus-src-2612/internal/distributed/proxy/httpserver/handler_v2.go | v2.6.12 | 2026-08-22 | matched (diff vs v2.6.10 reviewed line-by-line) |
| 4 | .milvus-src-2612/internal/distributed/proxy/httpserver/request_v2.go | v2.6.12 | 2026-08-22 | matched (diff reviewed: SearchReqV2 ids field) |
| 5 | .milvus-src-2612/internal/distributed/proxy/httpserver/constant.go | v2.6.12 | 2026-08-22 | matched (diff reviewed: TruncateAction, HTTPWarmupKey) |
| 6 | .milvus-src-2612/internal/distributed/proxy/httpserver/utils.go | v2.6.12 | 2026-08-22 | matched (diff reviewed: convertIDsToSchemapbIDs) |
| 7 | .milvus-src-2612/internal/distributed/proxy/httpserver/wrapper.go | v2.6.12 | 2026-08-22 | matched (no diff) |
| 8 | .milvus-src-2612/pkg/util/merr/errors.go | v2.6.12 | 2026-08-22 | matched |
| 9 | .milvus-src-2612/pkg/common/common.go | v2.6.12 | 2026-08-22 | matched (warmup policy consts + ValidateWarmupPolicy) |
| 10 | .milvus-src-2612/internal/distributed/proxy/service.go | v2.6.12 | 2026-08-22 | matched |
| 11 | .milvus-src-2612/internal/proxy/validate_util.go | v2.6.12 | 2026-08-22 | matched (diff reviewed: default-value valid-data adaptation) |
| 12 | .milvus-src-2612/internal/proxy/task.go, task_search.go, task_upsert.go | v2.6.12 | 2026-08-22 | matched (diffs reviewed) |
| 13 | .milvus-src-2612/internal/parser/planparserv2/parser_visitor.go, rewriter/entry.go | v2.6.12 | 2026-08-22 | matched (diffs reviewed) |
| 14 | live instance http://localhost:19530 | v2.6.12 | 2026-08-22 | matched (all new behaviors live-confirmed) |

## SDK Information
- Package: pymilvus
- Version: 2.6.x series (server 2.6.12; pymilvus releases track server patch versions, use latest 2.6.x)
- Install: `pip install "pymilvus>=2.6.0,<2.7"`

## Docker Images
- Available tags (locally verified `docker images`): v2.3.22, v2.6.10, v2.6.12, v2.6.16, v2.6.17, v2.6.18, v2.6.19, v3.0.0
- Recommended: v2.6.12

## Error Envelope Model (CRITICAL — unchanged from 2.6.10)

**v2 RESTful API (`/v2/vectordb/*`)** — envelope `{code, message}` on error, `{code, data}` on success:
- Success code = 0. Live confirmed v2.6.12: `collections/list` → `{"code":0,"data":[]}`.
- HTTP status is 200 for almost ALL business responses including errors (live confirmed again for all new 2.6.12 error paths — every new error below returned HTTP 200 with non-zero code).
- Missing required parameter → 1802; malformed JSON / wrong content type → 1801; resource not found → 100; true HTTP non-200 only for unknown route (404) and auth middleware rejections.

**v1 RESTful (`/v1/vector/*`)** — legacy envelope code **200** for success, merr codes for errors (mixed model, unchanged).

**Key merr codes (unchanged scheme):** 0 success; 100 collection not found; 101 not loaded; 104 already loaded; 1100 invalid parameter; 1101 missing parameter; 1400/1800 auth; 1600-1602 alias; 1700 field not found; 1801 incorrect parameter format; 1802 missing required parameters; 700 index not found.

## Route Trees (source: service.go mount points — unchanged in 2.6.12)

Three HTTP surfaces on port 19530:
1. `/api/v1/*` — legacy management API (~47 routes, no diff)
2. `/v1/vector/*` — v1 RESTful data API (10 routes, no diff)
3. `/v2/vectordb/*` — v2 RESTful API (**primary target, 88 POST routes** — 87 from 2.6.10 + 1 new `collections/truncate`)

## API Endpoints — v2 RESTful (`/v2/vectordb/*`)

All v2 endpoints are POST with JSON body. Base: v2.6.10 knowledge (reused verbatim for unchanged parts); every 2.6.12 diff verified against source + live.

### NEW in v2.6.12

#### collections/truncate (NEW endpoint)
- Method: POST /v2/vectordb/collections/truncate
- Source: handler_v2.go truncateCollection (new route registration) → milvuspb.TruncateCollectionRequest
- Body: CollectionNameReq {dbName?, collectionName (required)}
- Behavioral contracts (ALL live-confirmed on v2.6.12):
  - valid collection → `{"code":0,"data":{}}`; row count reset to 0 (get_stats → rowCount:0 after truncate), schema/index/load state preserved
  - nonexistent collection → `{"code":100,"message":"collection not found[database=default][collection=...]"}`
  - missing collectionName → `{"code":1802,"message":"missing required parameters, error: Key: 'CollectionNameReq.CollectionName' ..."}`
- Constraint: collectionName validated by validateCollectionName (same name rules as elsewhere)

#### entities/search — search by primary keys (NEW input mode)
- Method: POST /v2/vectordb/entities/search
- Source: request_v2.go SearchReqV2 (data binding relaxed from required → optional; new `ids []interface{}` field) + handler_v2.go search() + utils.go convertIDsToSchemapbIDs
- Body: SearchReqV2 {dbName?, collectionName (required), **data? OR ids? — exactly one required (NEW)**, annsField?, partitionNames?, filter?, limit (default 100 when omitted), offset?, outputFields?, searchParams{}, consistencyLevel?, exprParams?, functionScore?}
- NEW behavioral contracts (ALL live-confirmed):
  - both ids and data provided → `{"code":1100,"message":"primary keys (ids) and query vectors (data) are mutually exclusive. Please provide either 'ids' or 'data', not both"}`
  - neither provided → `{"code":1802,"message":"either 'ids' (for primary key search) or 'data' (for vector search) must be provided"}` (empty array `ids:[]` counts as not provided — live confirmed same 1802)
  - ids-only search on loaded collection → success, returns ranked hits with distance (live: ids [1,2] limit 1 → hits id 1/2 with distance ~1.0 cosine-style scores)
  - int64 pk with fractional id (e.g. 1.5) → `{"code":1100,"message":"invalid parameter, error: invalid int64 id at index 0: 1.5 has fractional part"}`
  - id type conversion rules (source convertIDsToSchemapbIDs): int64 pk accepts int/float64-without-fraction/numeric-string; VarChar pk accepts string/non-empty, and numbers auto-converted to string (int/float → "1"); empty string id → error "empty string id at index %d"; unsupported pk DataType (e.g. non-Int64/VarChar pk) → "unsupported primary key type: %s"
  - collection with no primary key field + ids search → 1100 "collection has no primary key field"
  - when searching by ids, annsField only set in search params if non-empty (v2.6.10 always set it, even empty)
- Unchanged: limit+offset ∈ [1, 16384] (topK); invalid consistencyLevel → 1100.

#### collections/create — warmup params (NEW accepted params)
- Source: handler_v2.go createCollection now forwards four collection-level warmup keys from `params` into collection properties: `warmup.scalarField`, `warmup.scalarIndex`, `warmup.vectorField`, `warmup.vectorIndex`
- NEW constraints (source pkg/common.ValidateWarmupPolicy + proxy task.go; live-confirmed):
  - warmup policy value must be `"disable"` or `"sync"`; anything else → 1100 `invalid warmup value for key {key}: invalid warmup policy: {value}, must be 'disable' or 'sync'` (live: warmup.scalarField:"bogus" → exactly this)
  - bare `warmup` key is field-level only; at collection level must use the four granular keys (alter path enforces "warmup key '%s' is only allowed at field level..." — create path with bare `warmup` is passed through without validation in this diff, live: `params:{warmup:"bogus"}` create succeeded code 0 — potential gap, note for attack)
  - alter_properties on loaded collection: altering warmup props while loaded → ErrCollectionLoaded "can not alter warmup properties if collection loaded" (new distinct message vs mmap's)

#### indexes/describe — warmup in response (NEW output field)
- describeIndex now surfaces `warmup` value from index params in indexInfo map (HTTPWarmupKey). Cosmetic/output change.

### Insert/upsert default-value nullable adaptation (validation behavior change)
- Source: validate_util.go fillWithValue + task_upsert.go — fields with `defaultValue` (not just nullable) now get ValidData auto-filled with `true` when SDK omits valid data; upsert missing rows for default-value fields use FillWithDefaultValue instead of FillWithNullValue.
- Behavioral: partial rows omitting a defaultValue column are now valid on insert/upsert (previously could produce invalid field data). Error surface unchanged.

### Filter expression parser changes (planparserv2)
- JSON array literals in `in [...]` expressions: mixed int/float values are now unified to floats (int mixed with float → int promoted to float) instead of type-mismatch error.
- Constant-folded boolean expressions (`1==1` parsed to ValueExpr(bool)) are now normalized to AlwaysTrueExpr/AlwaysFalseExpr — expressions that previously errored or matched nothing may now be accepted.
- Source: parser_visitor.go visitValues JSON branch; rewriter/entry.go visitValueExpr.

### ArrayOfVector metric mapping (autoindex)
- When user does not specify metric_type on an ArrayOfVector field, autoindex config element-level metrics are mapped to EmbList metrics: COSINE→MAX_SIM_COSINE, L2→MAX_SIM_L2, IP→MAX_SIM_IP, HAMMING→MAX_SIM_HAMMING, JACCARD→MAX_SIM_JACCARD. Sparse ArrayOfVector without user metric → not supported.

### Unchanged categories (reused from v2.6.10 knowledge, verified no httpserver diff)
- Collections (now 20 with truncate): list/has/describe/get_stats/get_load_state/create/drop/rename/load/refresh_load/release/alter_properties/drop_properties/compact/get_compaction_state/flush/add_function/alter_function/drop_function + fields/{add,alter_properties}
- Databases (7), Entities (8, search updated above), Partitions (7), Indexes (6), Aliases (5), Users/Roles/PrivilegeGroups/RBAC (~20), Import Jobs (4), Resource Groups (6), Segments/Quota/Analyzer (3), v1 `/v1/vector/*` (10), legacy `/api/v1/*` (~47)
- Full endpoint details (params/constraints/envelopes) identical to results/milvus/v2.6.10/raw_knowledge.md sections "API Endpoints — v2 RESTful", "v1 RESTful", "legacy management" — those route registrations have zero diff between v2.6.10 and v2.6.12 except items listed above.

## Global Constraints (paramtable + validate_util — no diff vs 2.6.10)
- Names: letters/digits/underscores, first char letter/underscore, max 255
- Vector dim max 32768; BinaryVector dim multiple of 8
- VarChar max_length default 65535; max 64 fields; max 4 vector fields; max 16 shards
- topK (limit+offset) ≤ 16384; ConsistencyLevel enum Strong|Session|Bounded|Eventually|Customized
- Warmup policy values: `disable` | `sync` only (NEW enforced surface)

## Data Types (unchanged)
- Scalar: Bool, Int8-64, Float, Double, VarChar, JSON, Array; Vector: FloatVector, BinaryVector, Float16Vector, BFloat16Vector, SparseFloatVector
- EmbList metrics (2.6.12 surfaced): MAX_SIM_COSINE, MAX_SIM_L2, MAX_SIM_IP, MAX_SIM_HAMMING, MAX_SIM_JACCARD

## Diff vs v2.6.10 (source git diff v2.6.10..v2.6.12, httpserver 6 files)
1. **+1 endpoint**: POST /v2/vectordb/collections/truncate (88 v2 routes total)
2. **search input contract changed**: data no longer binding-required; new `ids` field; mutual-exclusion + at-least-one validation (1100/1802); ids→schemapb.IDs conversion with per-type validation (int64 fractional / empty string / unsupported pk type errors)
3. **warmup property family**: create accepts warmup.{scalarField,scalarIndex,vectorField,vectorIndex} in params; values restricted to disable|sync; alter blocked when loaded; describeIndex returns warmup
4. **default-value field adaptation**: fillWithValue covers defaultValue fields (insert/upsert partial rows)
5. **parser**: JSON in-array int/float unification; ValueExpr bool → AlwaysTrue/False normalization
6. **autoindex ArrayOfVector** metric mapping to EmbList metrics
7. No ef/nprobe upper-bound validation changes landed in 2.6.12 (47752 fix is 2.6.14+); search param validation surface unchanged

## Missing Endpoints
None — full route registration diff extracted from source; all new behaviors live-confirmed.
