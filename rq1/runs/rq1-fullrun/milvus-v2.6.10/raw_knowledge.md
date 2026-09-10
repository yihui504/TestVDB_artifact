# milvus v2.6.10 API Knowledge

knowledge_path: source-derived
doc_coverage_pct: N/A (spec unavailable — milvus has no fetchable OpenAPI spec rule; endpoints derived from source route registration, cross-validated against live instance)

## Document Metadata
- doc_version: v2.6.10 (source tree, release v2.6.10)
- target_version: v2.6.10
- version_match: matched (source == target, exact)
- source_url: .milvus-src-2610/internal/distributed/proxy/httpserver/ (local source checkout, release v2.6.10)
- fetched_at: 2026-08-22T00:00:00Z
- live_validation: http://localhost:19530 (Bearer root:Milvus) running v2.6.10; healthz :9091 OK

## Document Sources
| # | URL / Path | Doc Version | Fetched At | Version Match |
|---|------------|-------------|------------|---------------|
| 1 | .milvus-src-2610/internal/distributed/proxy/httpserver/handler.go | v2.6.10 | 2026-08-22 | matched |
| 2 | .milvus-src-2610/internal/distributed/proxy/httpserver/handler_v1.go | v2.6.10 | 2026-08-22 | matched |
| 3 | .milvus-src-2610/internal/distributed/proxy/httpserver/handler_v2.go | v2.6.10 | 2026-08-22 | matched |
| 4 | .milvus-src-2610/internal/distributed/proxy/httpserver/request_v2.go | v2.6.10 | 2026-08-22 | matched |
| 5 | .milvus-src-2610/internal/distributed/proxy/httpserver/constant.go | v2.6.10 | 2026-08-22 | matched |
| 6 | .milvus-src-2610/internal/distributed/proxy/httpserver/wrapper.go | v2.6.10 | 2026-08-22 | matched |
| 7 | .milvus-src-2610/pkg/util/merr/errors.go | v2.6.10 | 2026-08-22 | matched |
| 8 | .milvus-src-2610/pkg/util/merr/utils.go | v2.6.10 | 2026-08-22 | matched |
| 9 | .milvus-src-2610/internal/distributed/proxy/service.go | v2.6.10 | 2026-08-22 | matched |
| 10 | .milvus-src-2610/pkg/util/paramtable/component_param.go | v2.6.10 | 2026-08-22 | matched |
| 11 | .milvus-src-2610/pkg/util/paramtable/quota_param.go | v2.6.10 | 2026-08-22 | matched |
| 12 | .milvus-src-2610/internal/proxy/util.go | v2.6.10 | 2026-08-22 | matched |
| 13 | live instance http://localhost:19530 | v2.6.10 | 2026-08-22 | matched |

## SDK Information
- Package: pymilvus
- Version: 2.6.10 (exists on PyPI; server-compatible series 2.6.x)
- Install: `pip install pymilvus==2.6.10`

## Docker Images
- Available tags (locally verified): v2.6.10, v2.6.12, v2.6.16, v2.6.17 (Docker Hub API anonymous rate-limited; `docker manifest inspect` blocked in sandbox — tags verified via local `docker images`, v2.6.10 image id 6c5de1c9b3b5)
- Recommended: v2.6.10

## Error Envelope Model (CRITICAL — differs from 2.3 knowledge)

**v2 RESTful API (`/v2/vectordb/*`)** — envelope is `{code, message}` on error, `{code, data}` on success:
- **Success code = 0** (`merr.Code(nil)` returns 0), NOT 200. Confirmed live: `collections/list` → `{"code":0,"data":[]}`.
- **HTTP status is 200 for almost ALL business responses including errors** (handler uses `HTTPAbortReturn(gCtx, http.StatusOK, ...)` for binding failures; business errors also returned with HTTP 200 + non-zero code in most paths). Error discrimination must use the JSON `code` field, not HTTP status.
- Missing required parameter → HTTP 200, `{"code":1802,"message":"missing required parameters, error: ..."}` (live confirmed)
- Malformed JSON / wrong content type → HTTP 200, `{"code":1801,"message":"can only accept json format request, ..."}` (live confirmed)
- Resource not found (collection etc.) → HTTP 200, `{"code":100,"message":"can't find collection[database=default][collection=...]"}` (live confirmed)
- True HTTP non-200 only for: unknown route (404 `page not found`), auth middleware rejections (1800 ErrNeedAuthenticate / 1400 not authenticated), and legacy v1 wrapper internal errors.

**v1 RESTful API (`/v1/vector/*`)** — legacy envelope still uses code **200** for success (live confirmed: `GET /v1/vector/collections` → `{"code":200,"data":[]}`) and **0/1802-style** merr codes for errors via v2-style binding (live: `POST /v1/vector/collections/create {}` → `{"code":1802,...}`). Mixed model — do not assume one envelope for both.

**Key merr code enums (pkg/util/merr/errors.go, 2.6.10):**
- 0 success (v2); 1 service not ready; 2 service unavailable; 4 too many requests; 8 rate limit
- 100 collection not found; 101 collection not loaded; 102 collection num limit exceeded; 103 not fully loaded; 104 collection already loaded; 105 illegal collection schema; 109 schema mismatch
- 200 partition not found; 201/202 partition not loaded / not fully loaded
- 700 index not found; 800 database not found; 802 invalid database name
- 1100 invalid parameter; 1101 missing parameter; 1102 parameter too large
- 1400 not authenticated; 1401 privilege not permitted
- 1600 alias not found; 1601 alias/collection name conflict; 1602 alias already exist
- 1700 field not found; 1701 field name invalid
- 1800 user hasn't authenticated; 1801 incorrect parameter format (non-JSON); 1802 missing required parameters
- 10000 canceled; 10001 timeout

## Route Trees (source: service.go mount points)

Three HTTP surfaces on port 19530:
1. `/api/v1/*` — legacy management API (handler.go, ~47 routes: /collection, /partition, /alias, /index, /entities, /search, /query, /persist, /import, /credential, etc.)
2. `/v1/vector/*` — v1 RESTful data API (10 routes, see below)
3. `/v2/vectordb/*` — v2 RESTful API (**primary target**, 87 POST routes)

## API Endpoints — v2 RESTful (`/v2/vectordb/*`)

All v2 endpoints are **POST** with JSON body. Source: handler_v2.go RegisterRoutesToV2 + constant.go.

### Collections (19)
#### list
- Path: POST /v2/vectordb/collections/list; Body: DatabaseReq {dbName?}
- Success: {"code":0,"data":[names]}; empty list when no collections
#### has
- Path: POST /v2/vectordb/collections/has; Body: CollectionNameReq (collectionName required)
- 1802 if collectionName missing; returns {has: bool}
#### describe
- Path: POST /v2/vectordb/collections/describe; Body: CollectionNameReq
- Constraints: collection must exist else code 100 (live confirmed)
#### get_stats
- Path: POST /v2/vectordb/collections/get_stats; Body: CollectionNameReq
- Returns row_count
#### get_load_state
- Path: POST /v2/vectordb/collections/get_load_state; Body: CollectionNameReq (+partitionNames? for per-partition load state)
- LoadState enum: LoadStateNotExist/LoadStateNotLoad/LoadStateLoading/LoadStateLoaded
#### create
- Path: POST /v2/vectordb/collections/create; Body: CollectionReq
- Params: dbName?, collectionName (required), dimension?, idType?, autoID (default false), metricType?, primaryFieldName?, vectorFieldName?, schema{fields,functions,autoID,enableDynamicField}?, indexParams[], params?, description?
- Two modes: quick mode (dimension+primaryFieldName+vectorFieldName) or full schema mode; conflicting modes → 1100
- FieldSchema: fieldName (req), dataType (req, string enum: Int64/VarChar/FloatVector/BinaryVector/Float16Vector/BFloat16Vector/SparseFloatVector/Bool/Int8/Int16/Int32/Float/Double/Array/JSON), elementDataType?, isPrimary?, isPartitionKey?, isClusteringKey?, elementTypeParams{dim,max_length,...}?, nullable?, defaultValue?
#### drop / truncate / rename / load / refresh_load / release
- drop|rename|load|release: Body CollectionNameReq; rename adds newCollectionName (required)
- release before drop not required in v2 (drop is atomic); load on already-loaded → 104; release/search on not-loaded → 101
#### alter_properties / drop_properties / compact / get_compaction_state / flush
- alter_properties: {collectionName, properties{}}; compact: {collectionName}; flush: {collectionNames[]}
#### add_function / alter_function / drop_function
- Body: collectionName + FunctionSchema (add), functionName+FunctionSchema (alter), FunctionName (drop — note capital-F json tag "FunctionName" in DropFunction struct, source quirk)

### Collection Fields (2)
#### POST /v2/vectordb/collections/fields/alter_properties — Body: CollectionFieldReqWithParams
#### POST /v2/vectordb/collections/fields/add — Body: CollectionFieldReqWithSchema (dynamic schema field add, new in 2.6 line)

### Databases (6)
- POST /v2/vectordb/databases/{create,drop,drop_properties,list,describe,alter,alter_properties}
- create/drop/describe: dbName required (drop/describe use DatabaseReqRequiredName); list: EmptyReq {}

### Entities (8) — core data plane
#### insert / upsert
- Path: POST /v2/vectordb/entities/{insert,upsert}; Body: CollectionDataReq {dbName?, collectionName (req), partitionName?, data (req, []object), partialUpdate? (upsert only)}
- Invalid row data (missing pk/vector, wrong dim) → merr.ErrInvalidInsertData; returns {insertCount, insertIds}
#### delete
- Path: POST /v2/vectordb/entities/delete; Body: CollectionFilterReq {collectionName (req), filter (req), partitionName?, exprParams?}
- filter and id are mutually exclusive in older 2.4; in 2.6 filter is the required field (id removed from v2 struct)
#### query / get
- query: Body CollectionFilterReq-variant + outputFields, limit, offset, orderBy; get: CollectionIDReq {collectionName (req), id (req), outputFields (default ["*"] as DefaultOutputFields), consistencyLevel?}
- filter required for query; consistencyLevel invalid → 1100 with message "consistencyLevel can only be [Strong, Session, Bounded, Eventually, Customized], default: Bounded"
#### search
- Path: POST /v2/vectordb/entities/search; Body: SearchReqV2 {dbName?, collectionName (req), data (req, vectors), annsField?, partitionNames?, filter?, groupingField?, groupSize?, strictGroupSize?, limit (default 100 when omitted — server injects 100), offset?, outputFields?, searchParams{} (nprobe/ef/radius/range_filter/level etc.), consistencyLevel?, exprParams?, functionScore?}
- Constraint: limit+offset must be in [1, TopKLimit=16384] (`quotaAndLimits.limits.topK` default 16384) — else error "it should be in range [1, 16384], but got %d"
- Invalid consistencyLevel → code 1100
#### advanced_search / hybrid_search
- Body: HybridSearchReq {collectionName (req), search: []SubSearchReq{data (req), annsField?, metricType?, filter?, limit?, params?}, rerank{strategy,params}, limit (default 100), offset?, ...}
- Both aliases route to same handler (HybridSearch)

### Partitions (7)
- POST /v2/vectordb/partitions/{list,has,get_stats,create,drop,load,release}
- list/has(create/drop uses PartitionReq {collectionName (req), partitionName (req)}; load/release use PartitionsReq {collectionName, partitionNames[] (both required)}

### Indexes (6)
- POST /v2/vectordb/indexes/{list,describe,create,drop,alter_properties,drop_properties}
- create: IndexParamReq {collectionName (req), indexParams[]: IndexParam{fieldName (req), indexName?, metricType?, indexType?, params{M,efConstruction,nlist,...}}}
- describe/drop: IndexReq {collectionName (req), indexName (req), timestamp?}
- Index building is async: create returns immediately, poll describe/index state; index not found → 700

### Aliases (5)
- POST /v2/vectordb/aliases/{list,describe,create,drop,alter}
- create/alter: AliasCollectionReq {collectionName (req), aliasName (req)}; describe/drop: AliasReq {aliasName (req)}
- alias already exist → 1602; alias not found → 1600; alias==collectionName conflict → 1601

### Users / Roles / PrivilegeGroups / RBAC (~20)
- POST /v2/vectordb/users/{list,describe,create,update_password,drop,grant_role,revoke_role}
- POST /v2/vectordb/roles/{list,describe,create,drop,grant_privilege,revoke_privilege,grant_privilege_v2,revoke_privilege_v2}
- POST /v2/vectordb/privilege_groups/{create,drop,list,add_privileges_to_group,remove_privileges_from_group}
- Password constraints: min 6 (proxy.minPasswordLength), max 72 (bcrypt); username max 32

### Import Jobs (4)
- POST /v2/vectordb/jobs/import/{list,create,get_progress,describe} — get_progress deprecated in favor of describe

### Resource Groups (6)
- POST /v2/vectordb/resource_groups/{create,drop,alter,describe,list,transfer_replica}

### Segments / Quota / Analyzer (3)
- POST /v2/vectordb/segments/describe (GetSegmentsInfoReq)
- POST /v2/vectordb/quotacenter/describe
- POST /v2/vectordb/common/run_analyzer (analyzer for full-text BM25 pipeline)

## API Endpoints — v1 RESTful (`/v1/vector/*`) — legacy, still mounted in 2.6.10
- GET  /v1/vector/collections — success envelope code **200** (live confirmed)
- POST /v1/vector/collections/create — required [collectionName, dimension] (missing → code 1802)
- GET  /v1/vector/collections/describe?collectionName=
- POST /v1/vector/collections/drop
- POST /v1/vector/{insert,upsert,search,get,query,delete}
- v1 search requires [collectionName, vector]

## API Endpoints — legacy management (`/api/v1/*`) — 47 routes (handler.go)
Key routes: POST/DELETE /api/v1/collection, GET /api/v1/collection/existence, POST/DELETE /api/v1/collection/load, GET /api/v1/collections, partitions CRUD/load, alias create/drop/alter, index CRUD + /index/state + /index/progress, POST /api/v1/entities (insert), DELETE /api/v1/entities, POST /api/v1/search, POST /api/v1/query, /api/v1/persist (flush), /api/v1/import*, /api/v1/credential*, /api/v1/replicas, /api/v1/metrics, /api/v1/compaction*, /api/v1/load-balance, GET /health, POST /dummy.
Envelope: v1 wrapper uses commonpb.Status {errorCode, reason} with HTTP 400 (IllegalArgument/bad request) or 500 (UnexpectedError); success 200.

## Global Constraints (paramtable + validate_util)
- Names (collection/partition/alias/db/field): pattern letters/digits/underscores, first char must be letter/underscore, max length **255** (proxy.maxNameLength)
- Vector dimension: max **32768** (proxy.maxDimension) for FloatVector; BinaryVector dim must be multiple of 8
- VarChar max_length default **65535** (proxy.maxVarCharLength, 2.4.19+ hotfix value)
- Max fields per collection: **64** (proxy.maxFieldNum); max vector fields: **4** (proxy.maxVectorFieldNum, 2.6 raised from 2.3's 1/2)
- Max shards: **16** (proxy.maxShardNum)
- Search topK (limit+offset): ≤ **16384** (quotaAndLimits.limits.topK)
- ConsistencyLevel enum: Strong|Session|Bounded|Eventually|Customized; invalid → 1100
- dbName default "default"; can also come from header (HTTPHeaderDBName)
- Auth: Authorization Bearer user:pass or Basic auth; unauthenticated → 1800/1400
- load/release state machine: search/query on not-loaded collection → 101; load on loaded → 104; get_load_state per-collection and per-partition

## Data Types (schema dataType strings)
- Scalar: Bool, Int8, Int16, Int32, Int64, Float, Double, VarChar, JSON, Array (with elementDataType)
- Vector: FloatVector, BinaryVector, Float16Vector, BFloat16Vector, SparseFloatVector (2.6 supports all in REST schema creation)
- Index types (indexType): AUTOINDEX, HNSW, DISKANN, IVF_FLAT, IVF_SQ8, GPU_IVF_* etc.; params: {M, efConstruction, nlist}; search params: {nprobe, ef, level, radius, range_filter}

## Diff vs v2.3.22 (API surface)
- **Success code semantic changed/clarified**: v2 API success `code:0`; v1 vector API `code:200`. The v2.3.22 knowledge (v1-only, code 200) must not be reused for v2 endpoints.
- v2 `/v2/vectordb` surface massively expanded in 2.6: 87 routes across 14 categories incl. databases, roles/privilege_groups/grant_privilege_v2, import jobs, resource groups, segments/quotacenter describe, run_analyzer, collections/truncate + functions (add/alter/drop_function for BM25/embedding functions), fields/add (dynamic schema), collections/refresh_load
- v2.6 data-plane additions vs 2.4/2.3-era v2: partialUpdate (upsert), functionScore, groupingField/groupSize/strictGroupSize, exprParams, hybrid_search alias, sparse/float16/bfloat16 vectors, sparse float vector JSON input format
- Legacy `/api/v1` management routes unchanged in shape (still mounted); `/v1/vector` legacy data API retained
- Error codes stable numbering (merr 100/101/1100/1800/1801/1802 etc. — same scheme since 2.2/2.3), but v2 HTTP-status behavior: nearly all business errors return HTTP 200

## Missing Endpoints
None — full route registration extracted from source; live spot-checks confirmed envelope behavior.
