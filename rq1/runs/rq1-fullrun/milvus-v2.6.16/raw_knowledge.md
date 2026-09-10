# milvus v2.6.16 API Knowledge

knowledge_path: source-derived derived-chain (v2.6.12 knowledge base + directory diff .milvus-src-2612 vs .milvus-src-2616 on internal/distributed/proxy/httpserver/, internal/proxy/, internal/parser/, pkg/common/, cross-validated against live v2.6.16 instance)
KNOWLEDGE_DEGRADED: false (source-derived, exact-tag trees; no version drift — v2.6.16 checkout is release tag v2.6.16, commit c4e3955 "fix: [2.6] fix build bug for json stats with lack-of-binlog (#49673)"; v2.6.12 tree is release v2.6.12)
doc_coverage_pct: N/A (spec unavailable — milvus has no fetchable OpenAPI spec rule; endpoints derived from source route registration, cross-validated against live instance)

## Document Metadata
- doc_version: v2.6.16 (source tree, release v2.6.16)
- target_version: v2.6.16
- version_match: matched (source == target, exact)
- source_url: .milvus-src-2616/internal/distributed/proxy/httpserver/ (local source checkout, release v2.6.16)
- fetched_at: 2026-08-22T00:00:00Z
- live_validation: http://localhost:19530 (Bearer root:Milvus) running v2.6.16; healthz :9091 OK ("OK")
- derived_from: results/milvus/v2.6.12/raw_knowledge.md (source-derived, same-series diff mode; v2.6.12 itself derived from v2.6.10)

## Document Sources
| # | URL / Path | Doc Version | Fetched At | Version Match |
|---|------------|-------------|------------|---------------|
| 1 | .milvus-src-2616/internal/distributed/proxy/httpserver/handler.go | v2.6.16 | 2026-08-22 | matched (no route diff vs 2612) |
| 2 | .milvus-src-2616/internal/distributed/proxy/httpserver/handler_v1.go | v2.6.16 | 2026-08-22 | matched (diff: checkAndSetData return-order refactor only, no behavior change) |
| 3 | .milvus-src-2616/internal/distributed/proxy/httpserver/handler_v2.go | v2.6.16 | 2026-08-22 | matched (diff reviewed line-by-line: hook API refactor, ginCtx.Set, no new routes) |
| 4 | .milvus-src-2616/internal/distributed/proxy/httpserver/request_v2.go | v2.6.16 | 2026-08-22 | matched (diff reviewed: GetCollectionName() getters added; no new request fields) |
| 5 | .milvus-src-2616/internal/distributed/proxy/httpserver/constant.go | v2.6.16 | 2026-08-22 | matched (diff: +ContextResponse const for hook response pass-through) |
| 6 | .milvus-src-2616/internal/distributed/proxy/httpserver/utils.go | v2.6.16 | 2026-08-22 | matched (diff reviewed: function-output-field validation moved to proxy) |
| 7 | .milvus-src-2616/internal/distributed/proxy/httpserver/timeout_middleware.go | v2.6.16 | 2026-08-22 | matched (diff: timeout flag → atomic.Bool, timeout code now merr.TimeoutCode; no API change) |
| 8 | .milvus-src-2616/pkg/common/common.go | v2.6.16 | 2026-08-22 | matched (query_mode family: QueryModeKey/QueryModeLargeTopK/ValidQueryModes/ValidateQueryMode, PkFilter consts) |
| 9 | .milvus-src-2616/pkg/util/paramtable/quota_param.go | v2.6.16 | 2026-08-22 | matched (LargeTopKLimit=1000000, LargeMaxQueryResultWindow=1000000, Version 2.6.14) |
| 10 | .milvus-src-2616/internal/proxy/task.go | v2.6.16 | 2026-08-22 | matched (query_mode validation in create; alter blocked when vector index exists) |
| 11 | .milvus-src-2616/internal/proxy/search_util.go, util.go | v2.6.16 | 2026-08-22 | matched (validateLimit/validateMaxQueryResultWindow largeTopKEnabled branch) |
| 12 | .milvus-src-2616/internal/parser/planparserv2/parser_visitor.go | v2.6.16 | 2026-08-22 | matched (IsNull/IsNotNull on array element access rejected) |
| 13 | live instance http://localhost:19530 | v2.6.16 | 2026-08-22 | matched (all new behaviors live-confirmed) |

## SDK Information
- Package: pymilvus
- Version: 2.6.x series (server 2.6.16; use latest 2.6.x)
- Install: `pip install "pymilvus>=2.6.0,<2.7"`

## Docker Images
- Available tags (locally verified): v2.3.22, v2.6.10, v2.6.12, v2.6.16, v2.6.17, v2.6.18, v2.6.19, v3.0.0
- Recommended: v2.6.16

## Error Envelope Model (CRITICAL — unchanged from 2.6.12)

**v2 RESTful API (`/v2/vectordb/*`)** — envelope `{code, message}` on error, `{code, data}` on success:
- Success code = 0. Live confirmed v2.6.16: `collections/create` → `{"code":0,"data":{}}`.
- HTTP status 200 for business responses including errors (live confirmed for new 2.6.16 paths: query_mode invalid (65535), topk limit (65535), alter query_mode with index (702), dbName not found (800)).
- Missing required parameter → 1802; malformed JSON → 1801; resource not found → 100; DB not found → 800; true HTTP non-200 only for unknown route (404) and auth rejections.
- Note: many parameter-validation errors surface as code **65535** (generic ErrParameterInvalid) rather than 1100 — live confirmed: `topk [20000] is invalid` → 65535; `invalid query_mode value "bogus"` → 65535; `primary key is not specified` → 65535.

**v1 RESTful (`/v1/vector/*`)** — legacy envelope, mixed model, unchanged.

**Key merr codes:** 0 success; 100 collection not found; 101 not loaded; 104 already loaded; 1100/65535 invalid parameter; 1101 missing parameter; 1400/1800 auth; 1600-1602 alias; 1700 field not found; 1801 incorrect parameter format; 1802 missing required parameters; 700 index not found; 702 index duplicate (new surface: alter query_mode blocked by existing vector index); 800 database not found.

## Route Trees (source: service.go mount points — NO route changes vs 2.6.12)

Three HTTP surfaces on port 19530:
1. `/api/v1/*` — legacy management API (~47 routes, no diff)
2. `/v1/vector/*` — v1 RESTful data API (10 routes, no diff)
3. `/v2/vectordb/*` — v2 RESTful API (primary target, **88 POST routes — unchanged count; no new/removed routes in 2.6.16**)

## NEW in v2.6.16 (vs v2.6.12)

### query_mode collection property (NEW validation surface — landed 2.6.14+, present in 2.6.16)
- Source: pkg/common/common.go `QueryModeKey="query_mode"`, `ValidQueryModes = "large_topk"`, `ValidateQueryMode`; internal/proxy/task.go (create-task validate + alter-collection detectQueryModeChange).
- Accepted at: `collections/create` (params/properties), `collections/alter_properties` (properties), `collections/drop_properties` (removal key).
- Constraints (ALL live-confirmed on v2.6.16):
  - query_mode value must be `"large_topk"` (only valid mode); anything else → 65535 `invalid query_mode value "bogus", valid values: [large_topk]` (live: `"bogus"` → exactly this, code 65535)
  - altering `query_mode` on a collection that already has a vector index → code **702** `can not alter query_mode if the collection already has a vector index. Please drop the index first: index duplicates[indexName=vec]` (live confirmed; note auto-created index on quick-create collections triggers this)
  - cannot provide both DeleteKeys and ExtraParams in one alter call (source: detectQueryModeChange duplicate guard)
- Effect when set to large_topk: search/query limit quotas switch from TopKLimit=16384 / MaxQueryResultWindow=16384 to LargeTopKLimit=1000000 / LargeMaxQueryResultWindow=1000000 (quota_param.go, Version 2.6.14).

### large_topk search/query limits (NEW range constraint — coupled with query_mode)
- Live-confirmed v2.6.16:
  - normal collection (no query_mode): `limit: 20000` → 65535 `topk [20000] is invalid, it should be in range [1, 16384], but got 20000`
  - query_mode=large_topk collection: `limit: 100000` → success `{"code":0,...,"topks":[1]}`; `limit: 1000001` → 65535 `topk [1000001] is invalid, it should be in range [1, 1000000], but got 1000001`
- Coupled constraint (rule 2.6): `limit+offset <= (query_mode==large_topk ? 1000000 : 16384)` — the bound depends on collection-level query_mode property, NOT a standalone constant.

### dbName validation (live-confirmed, GT surface)
- `collections/create` with `dbName` referencing nonexistent DB → code **800** `database not found[database=no_such_db]` (live confirmed v2.6.16).

### entities/insert — GT parameter surface note
- `entities/insert` accepts and ignores extra body keys such as `nprobe` (live: insert with `"nprobe":0` and with `searchParams:{nprobe:-5}` both → code 0, insertCount correct). These are NOT validated insert parameters (documented as ignored pass-through — attack surface: no constraint enforcement on this path).
- `entities/search` exposes `searchParams` object (e.g. `{"nprobe": N}`) — forwarded to proxy as key-value params; nprobe has no REST-side range validation (unchanged from 2.6.12; ef/nprobe upper-bound validation still absent at REST layer).

### collections/create — GT parameter surface note
- `collections/create` accepts extra body key `searchParams` (e.g. `{"nprobe":0}`) and `params` with arbitrary keys (live: both create calls → code 0). Unvalidated pass-through, same family as the 2.6.12 bare-`warmup` create gap.
- Quick-create path (dimension/idType/...) auto-creates a vector index; schema-mode path (`schema.fields[].elementTypeParams.dim`) does not — this gates the query_mode alter behavior above (live confirmed both).

### aliases/list — GT parameter surface note
- `aliases/list` body `{dbName?, collectionName?, aliasName?}` — both names optional in binding; live: `{"collectionName":"x","aliasName":"y"}` → code 0 `{"data":[]}`; single-name and empty-body calls also accepted (filters applied server-side). No binding-required enforcement.

### Function output field insert validation moved (behavior change)
- utils.go checkAndSetData: HTTP layer previously rejected any data provided for a function output field ("not allowed to provide input data for function output field"); in 2.6.16 the HTTP layer skips output fields when no data provided and defers validation to proxy when data IS provided. Error surface for the reject case moves downstream (message/behavior may differ from 2.6.12).

### Filter expression parser (planparserv2)
- NEW: `IS NULL` / `IS NOT NULL` on array element access (e.g. `array_field[0] IS NULL`) → rejected with 1100 `IsNull/IsNotNull operations are not supported on array element access, got: %s` (parser_visitor.go).
- Template flag propagation for JSON contains expressions; assorted De Morgan-style rewrites of negated conjunctions — internal, no new user-facing constraint extracted.
- fill_expression_value.go changed (exprParams handling) — no new user-facing contract isolated.

### Timeout middleware (internal)
- Timeout responses now use merr.TimeoutCode; timeout flag atomic. No API contract change.

## Unchanged vs v2.6.12 (reused from v2.6.12 knowledge, verified no relevant diff)
- All 88 v2 routes incl. collections/truncate; entities/search ids-vs-data mutual exclusion (1100/1802); ids conversion rules; warmup property family (disable|sync, alter-when-loaded blocked); default-value field adaptation; JSON in-array int/float unification; ArrayOfVector metric mapping; insert/upsert/search/query/delete parameter shapes; RBAC; import; resource groups; v1 and legacy routes.
- Global constraints: names ^[A-Za-z_][A-Za-z0-9_]*$ ≤255; dim ≤ 32768; BinaryVector dim %8; max 64 fields / 4 vector fields / 16 shards; topK ≤ 16384 (normal mode — see coupled large_topk rule above); ConsistencyLevel enum.

## Data Types (unchanged)
- Scalar: Bool, Int8-64, Float, Double, VarChar, JSON, Array; Vector: FloatVector, BinaryVector, Float16Vector, BFloat16Vector, SparseFloatVector
- EmbList metrics: MAX_SIM_COSINE, MAX_SIM_L2, MAX_SIM_IP, MAX_SIM_HAMMING, MAX_SIM_JACCARD

## Diff vs v2.6.12 (directory diff .milvus-src-2612 vs .milvus-src-2616)
1. **No endpoint additions/removals** (88 v2 routes, 10 v1, ~47 legacy — unchanged)
2. **query_mode property family (new)**: value ∈ {large_topk} else 65535; alter blocked (702) when vector index exists; validated at create and alter
3. **large_topk quota coupling (new)**: limit/offset window 16384 → 1000000 when collection query_mode=large_topk (landed 2.6.14)
4. **function output field insert validation** moved from HTTP layer to proxy
5. **parser**: IS NULL/IS NOT NULL on array element access now rejected (1100)
6. request_v2.go: GetCollectionName() interface getters added (internal); timeout middleware atomic; hook API refactor — no user-facing change
7. GT-relevant live behaviors confirmed: dbName 800; insert ignores nprobe/searchParams extras (code 0); create accepts searchParams/params extras (code 0); aliases/list accepts 0/1/2 of the name filters

## Missing Endpoints
None — full route registration reviewed (no diff vs 2.6.12); all new 2.6.16 behaviors live-confirmed.
