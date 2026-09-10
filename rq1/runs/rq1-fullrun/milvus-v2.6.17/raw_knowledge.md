# milvus v2.6.17 API Knowledge

knowledge_path: source-derived derived-chain (v2.6.16 knowledge base + directory diff .milvus-src-2616 vs .milvus-src-2617 on internal/distributed/proxy/httpserver/, internal/proxy/, internal/parser/, pkg/common/, cross-validated against live v2.6.17 instance)
KNOWLEDGE_DEGRADED: false (source-derived, exact-tag trees; v2.6.17 checkout is release tag v2.6.17, commit 1d584f5 "fix: [cp2.6] revert nullable vector support (#49838)"; v2.6.16 tree is release v2.6.16, commit c4e3955)
doc_coverage_pct: N/A (spec unavailable — milvus has no fetchable OpenAPI spec rule; endpoints derived from source route registration, cross-validated against live instance)

## Document Metadata
- doc_version: v2.6.17 (source tree, release v2.6.17)
- target_version: v2.6.17
- version_match: matched (source == target, exact; pkg/common/version.go Version = semver "2.6.17")
- source_url: .milvus-src-2617/internal/distributed/proxy/httpserver/ (local source checkout, release v2.6.17)
- fetched_at: 2026-08-22T00:00:00Z
- live_validation: http://localhost:19530 (Bearer root:Milvus) running v2.6.17; healthz :9091 OK ("OK"); all NEW 2.6.17 behaviors live-confirmed (see below)
- derived_from: results/milvus/v2.6.16/raw_knowledge.md (source-derived, same-series diff mode; v2.6.16 itself derived from v2.6.12 via v2.6.12→v2.6.10 chain)

## Document Sources
| # | URL / Path | Doc Version | Fetched At | Version Match |
|---|------------|-------------|------------|---------------|
| 1 | .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go | v2.6.17 | 2026-08-22 | matched (diff vs 2616: entities/upsert + v1 upsert now parse FieldOps via buildFieldPartialUpdateOps; NO route changes) |
| 2 | .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v1.go | v2.6.17 | 2026-08-22 | matched (diff: single-upsert merge now carries FieldOps) |
| 3 | .milvus-src-2617/internal/distributed/proxy/httpserver/request_v2.go | v2.6.17 | 2026-08-22 | matched (diff: NEW fieldOps []FieldPartialUpdateOpReq on upsert structs; NEW parseFieldPartialUpdateOp op enum {REPLACE,ARRAY_APPEND,ARRAY_REMOVE}) |
| 4 | .milvus-src-2617/internal/distributed/proxy/httpserver/request.go | v2.6.17 | 2026-08-22 | matched (v1 upsert structs gain FieldOps mirror) |
| 5 | .milvus-src-2617/internal/proxy/task_upsert_partial_op.go | v2.6.17 | 2026-08-22 | matched (NEW FILE: validateFieldPartialUpdateOps — full op validation surface) |
| 6 | .milvus-src-2617/internal/proxy/task_upsert.go | v2.6.17 | 2026-08-22 | matched (PreExecute calls validateFieldPartialUpdateOps; non-REPLACE op implies partialUpdate=true) |
| 7 | .milvus-src-2617/internal/proxy/task_index.go | v2.6.17 | 2026-08-22 | matched (hybrid index: user-specified low/high cardinality index types now overridden by server config — "Does not allow the user to specify the index type for hybrid index. This is by design.") |
| 8 | .milvus-src-2617/internal/parser/planparserv2/Plan.g4 + parser_visitor.go | v2.6.17 | 2026-08-22 | matched (grammar: LIKE/TEXTMATCH/PHRASEMATCH/ST* args generalized StringLiteral → expr; parseStringLiteralOrTemplate accepts template variables) |
| 9 | .milvus-src-2617/pkg/common/common.go | v2.6.17 | 2026-08-22 | matched (MaximumScalarIndexEngineVersion=3 + ClampScalarIndexVersion; HybridLow/HighCardinalityIndexTypeKey; query_mode family unchanged) |
| 10 | .milvus-src-2617/internal/distributed/proxy/httpserver/timeout_middleware.go + constant.go | v2.6.17 | 2026-08-22 | matched (HTTPHeaderRequestTimeout="Request-Timeout" per-request timeout override, unchanged vs 2616) |
| 11 | live instance http://localhost:19530 | v2.6.17 | 2026-08-22 | matched (all new behaviors live-confirmed) |

## SDK Information
- Package: pymilvus
- Version: 2.6.x series (server 2.6.17; use latest 2.6.x)
- Install: `pip install "pymilvus>=2.6.0,<2.7"`

## Docker Images
- Available tags (locally verified): v2.3.22, v2.6.10, v2.6.12, v2.6.16, v2.6.17, v2.6.18, v2.6.19, v3.0.0
- Recommended: v2.6.17

## Error Envelope Model (CRITICAL — unchanged from v2.6.16, live re-confirmed on v2.6.17)

**v2 RESTful API (`/v2/vectordb/*`)** — envelope `{code, message}` on error, `{code, data}` on success:
- Success code = 0. Live confirmed v2.6.17: `collections/create` → `{"code":0,"data":{}}`.
- HTTP status 200 for business responses including errors (live confirmed v2.6.17: fieldOps unsupported op 1100, array-op-on-non-array 1100, quick-create missing dimension 1100, topk 65535, alter query_mode bogus 65535, alter-with-index 702).
- Missing required parameter → 1802; malformed JSON → 1801; resource not found → 100; DB not found → 800; true HTTP non-200 only for unknown route (404) and auth rejections.
- Many parameter-validation errors surface as 65535 (generic ErrParameterInvalid) or 1100 — live confirmed v2.6.17: `topk [20000] is invalid` → 65535; `unsupported partial update op: BOGUS` → 1100.

**v1 RESTful (`/v1/vector/*`)** — legacy envelope, mixed model, unchanged.

**Key merr codes:** 0 success; 100 collection not found; 101 not loaded; 1100/65535 invalid parameter; 1801/1802 format/missing; 702 index duplicate (alter query_mode blocked by vector index); 800 database not found.

## Route Trees (source: handler_v2.go mount points — NO route changes vs v2.6.16)

Three HTTP surfaces on port 19530:
1. `/api/v1/*` — legacy management API (~47 routes, no diff)
2. `/v1/vector/*` — v1 RESTful data API (10 routes, no diff)
3. `/v2/vectordb/*` — v2 RESTful API (primary target, **88 POST routes — unchanged count; no new/removed routes in v2.6.17**)

## NEW in v2.6.17 (vs v2.6.16)

### entities/upsert fieldOps — NEW parameter + validation surface (REST)
- Request: `entities/upsert` (and v1 upsert) body gains optional `fieldOps: [{fieldName, op}]` (request_v2.go FieldPartialUpdateOpReq).
- Op parsing at HTTP layer (parseFieldPartialUpdateOp, strings.ToUpper+TrimSpace): accepted ops = `REPLACE`, `ARRAY_APPEND`, `ARRAY_REMOVE`; anything else → **1100** `unsupported partial update op: BOGUS: invalid parameter` (live confirmed).
- Deeper validation in proxy (task_upsert_partial_op.go validateFieldPartialUpdateOps), all → 1100 merr parameter-invalid family:
  - empty fieldName → `FieldPartialUpdateOp.field_name is required`
  - duplicate op for same field → `duplicate partial-update op for field "x"`
  - op field is the primary key → `field "x" is the primary key and cannot carry a partial-update op`
  - field not in schema → `field "x" not found in collection schema`
  - ARRAY_APPEND/ARRAY_REMOVE on non-Array field → `op ARRAY_APPEND requires Array field, but field "vector" is FloatVector` (live confirmed)
  - op field not present in payload / payload not Array / element type mismatch → parameter-invalid (1100)
- Behavior: a non-REPLACE op implicitly promotes request to partial_update=true (users need not set both); ARRAY_APPEND additionally checks payload stays within field max capacity (1100 if exceeded).

### Filter expression grammar (planparserv2) — LIKE/TEXTMATCH/PHRASEMATCH/ST* argument generalization
- Plan.g4: `expr LIKE StringLiteral` → `expr LIKE expr`; TEXTMATCH/PHRASEMATCH/ST*(spatial predicates) second/third args generalized from StringLiteral to expr.
- parser_visitor.go: new parseStringLiteralOrTemplate — the argument must be a string literal OR a template variable (`{name}` used with filter template params); non-string literal (e.g. int) → parameter-invalid error.
- Live confirmed v2.6.17 (semantic checks still enforced behind generalized grammar): `id like 123` → 1100 `like operation on non-string or no-json field is unsupported`; `text_match(id, 123)` → 1100 `text match operation on non-string is unsupported`; like pattern via template variable also passes grammar then hits the same field-type semantic check.
- Template variables are now accepted in LIKE patterns / TEXTMATCH queries (placeholder propagated to plan).

### Hybrid index params (by-design)
- task_index.go: user-specified `hybrid_low_cardinality_index_type` / `hybrid_high_cardinality_index_type` in index params are silently overridden by server config — "Does not allow the user to specify the index type for hybrid index. This is by design." (by-design, not a defect surface).
- pkg/common: MaximumScalarIndexEngineVersion = 3 (scalar index engine versioning/clamping — internal rolling-upgrade machinery, no REST contract).

### nullable vector revert
- Release commit 1d584f5 is "revert nullable vector support" — no REST parameter surface added/removed by this knowledge cut.

## Unchanged vs v2.6.16 (reused from v2.6.16 knowledge; diff-verified no relevant change, live spot-checked on v2.6.17)
- All 88 v2 routes; v1 and legacy routes; envelope model.
- query_mode family: alter_properties `query_mode:"bogus"` → 65535 `invalid query_mode value "bogus", valid values: [large_topk]` (live re-confirmed v2.6.17); alter blocked 702 when vector index exists (live re-confirmed: `can not alter query_mode if the collection already has a vector index... index duplicates[indexName=vector]`); note quick-create `params`/`properties` query_mode keys are NOT forwarded to collection properties by the create handler (whitelist forwarding only) — create-side validation of query_mode is not reachable via REST create.
- Coupled large_topk quota (live re-confirmed v2.6.17): normal collection limit 20000 → 65535 `topk [20000] is invalid, it should be in range [1, 16384]`; limit 0 → 65535; query_mode=large_topk collection limit 1000001 → 65535 range [1, 1000000].
- entities/query limit=-1 → code 0 (returns rows, negative limit tolerated on query path — live confirmed v2.6.17).
- users/create password rule (live re-confirmed v2.6.17): len<6 → 1100 `invalid password length: invalid parameter[5 out of range 6 <= value <= 72]`; valid 16-char → code 0. Bound: 6 <= len(password) <= 72.
- entities/insert filter: body key `filter` is NOT in the v2 insert struct — accepted and ignored (live: insert with `"filter":"id > 0"` → code 0, insertCount correct). Filter expressions are only parsed on query/delete/search/get paths.
- Request-Timeout HTTP header: parsed by timeout middleware (strconv seconds; unparseable value ignored, falls back to server default) — accepted on any request incl. entities/insert; valid values effectively unvalidated at parse layer (live: "1" and "bogus" both accepted, code 0). Exceeding the (very large) server-side hard cap yields HTTP 408 RequestTimeout.
- entities/insert ignores extra body keys (nprobe/searchParams); collections/create accepts extra params/properties keys unvalidated (live: query_mode in params/properties at create → code 0, property not stored).
- IS NULL/IS NOT NULL on array element access rejected (1100); field name rules ^[A-Za-z_][A-Za-z0-9_]*$ <=255; dim <= 32768; BinaryVector dim %8==0; max 64 fields / 4 vector fields / 16 shards; ConsistencyLevel enum; warmup family; defaultValue fill; aliases/list lenient binding; dbName 800.

## Data Types (unchanged)
- Scalar: Bool, Int8-64, Float, Double, VarChar, JSON, Array; Vector: FloatVector, BinaryVector, Float16Vector, BFloat16Vector, SparseFloatVector
- EmbList metrics: MAX_SIM_COSINE, MAX_SIM_L2, MAX_SIM_IP, MAX_SIM_HAMMING, MAX_SIM_JACCARD

## Diff vs v2.6.16 (directory diff .milvus-src-2616 vs .milvus-src-2617, API-relevant dirs)
1. **No endpoint additions/removals** (88 v2 routes, 10 v1, ~47 legacy — unchanged)
2. **entities/upsert fieldOps (NEW)**: op enum {REPLACE, ARRAY_APPEND, ARRAY_REMOVE}; unknown op → 1100; ARRAY_* requires Array field (1100); PK/duplicate/missing-field/payload-shape checks → 1100; non-REPLACE implies partialUpdate=true; v1 upsert mirrors the field
3. **parser grammar generalization**: LIKE/TEXTMATCH/PHRASEMATCH/ST* args now expr; string-literal-or-template enforced at visitor; semantic field-type checks unchanged
4. **hybrid index by-design override** of user-specified low/high cardinality index types
5. task_upsert.go: per-row array partial-op application path (internal execution)
6. GT-relevant live behaviors confirmed on v2.6.17: fieldOps unknown op 1100 + ARRAY_APPEND-on-FloatVector 1100; Request-Timeout header tolerant; insert filter ignored; password 6..72; search topk coupled 16384/1000000; query limit -1 tolerated; query_mode alter 65535/702

## Missing Endpoints
None — full route registration reviewed (no diff vs v2.6.16); all new 2.6.17 behaviors live-confirmed.
