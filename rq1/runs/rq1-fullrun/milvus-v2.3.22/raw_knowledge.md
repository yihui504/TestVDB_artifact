# milvus v2.3.22 API Knowledge

## Document Metadata
- doc_version: v2.3.22 (source tag v2.3.22, local source tree)
- target_version: v2.3.22
- version_match: matched (exact source-tree anchoring)
- source_url: https://github.com/milvus-io/milvus/tree/v2.3.22 (local mirror: .milvus-src-2322)
- fetched_at: 2026-08-22T00:00:00Z
- knowledge_path: source-derived - routes/params/enums extracted mechanically from internal/distributed/proxy/httpserver/ in release v2.3.22 source; behavioral facts verified against live standalone instance (localhost:19530, v2.3.22). No OpenAPI spec (fetch has no milvus rule) - doc_coverage_pct: N/A (spec unavailable), gate degraded to source-route enumeration + live-probe verification.
- openapi_unavailable: true

## Document Sources
| # | URL / Source | Doc Version | Fetched At | Version Match |
|---|-----|-------------|------------|---------------|
| 1 | .milvus-src-2322/internal/distributed/proxy/httpserver/handler_v1.go (RegisterRoutesToV1) | v2.3.22 | 2026-08-22 | matched (source tag) |
| 2 | .milvus-src-2322/internal/distributed/proxy/httpserver/handler_v2.go (RegisterRoutesToV2) | v2.3.22 | 2026-08-22 | matched (source tag) |
| 3 | .milvus-src-2322/internal/distributed/proxy/httpserver/request.go (v1 request structs) | v2.3.22 | 2026-08-22 | matched |
| 4 | .milvus-src-2322/internal/distributed/proxy/httpserver/request_v2.go (v2 request structs) | v2.3.22 | 2026-08-22 | matched |
| 5 | .milvus-src-2322/internal/distributed/proxy/httpserver/constant.go (paths/params/defaults) | v2.3.22 | 2026-08-22 | matched |
| 6 | .milvus-src-2322/pkg/util/metric/metric_type.go (metric enums) | v2.3.22 | 2026-08-22 | matched |
| 7 | live probe: http://localhost:19530/v1/... (standalone v2.3.22, Bearer root:Milvus) | v2.3.22 | 2026-08-22 | matched (runtime) |
| 8 | https://milvus.io/docs/v2.3.x/ (not fetched - source route registry used as mechanical anchor per no-spec strategy) | v2.3.x | - | N/A |

## SDK Information
- Package: pymilvus
- Version: 2.3.8 (latest 2.3.x on PyPI; no pymilvus 2.3.22 exists - SDK and server version lines diverge; 2.3.x SDK targets 2.3.x server)
- Install: pip install pymilvus==2.3.8

## Docker Images
- Repo: milvusdb/milvus
- Available tags: v2.3.22 (existence proven by live running container built from v2.3.22; Docker Hub anonymous API rate-limited during check - re-verify with docker manifest inspect milvusdb/milvus:v2.3.22 if re-pull needed)
- Recommended: v2.3.22

## Auth Model
- Authorization: Bearer username:password header (default creds root:Milvus)
- With authorization enabled: missing auth -> HTTP 401 (code: ErrNeedAuthenticate); insufficient privilege -> HTTP 403 (checkAuthorization, handler_v1.go:38-51)
- Non-existent database -> HTTP 200 with error body (code: ErrDatabaseNotFound, message: database not found + db name) (checkDatabase, handler_v1.go:54-79); db default skips the check
- Live probe: request without Authorization header to /v1/vector/collections returned HTTP 200 with empty data list on this instance (authorization disabled in standalone default config) - auth enforcement is config-dependent

## Response Envelope (all v1/v2 endpoints)
- Success: HTTP 200, body with code 200 and data field
- Business error: HTTP 200 with nonzero merr code in body - milvus REST reports most errors with HTTP 200 + nonzero code, NOT 4xx/5xx. Only auth (401/403), timeout middleware and unmatched-route 404 fall outside this.
- Known codes (live-verified): 100 = collection not found; 1802 = missing required parameters / invalid search params; 1804 = invalid data (parameter-invalid family)

## API Endpoints

### RESTful v1 (prefix /v1) - 10 endpoints (source: handler_v1.go:121-131)

#### listCollections
- Method: GET; Path: /v1/vector/collections
- Params: dbName (query/header DB-Name, optional, default "default")
- Behavioral: 200 with data as name array; empty -> empty array (never null)
- Live-verified: returned test1 after create

#### createCollection
- Method: POST; Path: /v1/vector/collections/create
- Body: collectionName (string, required), dimension (int32, required, must be non-zero), dbName (opt, default "default"), metricType (opt, default "L2"), primaryField (opt, default "id"), vectorField (opt, default "vector"), description (opt), enableDynamicField (opt, default true)
- Behavioral chain (source handler_v1.go:164-273): CreateCollection(shards=1, consistency=Bounded) then CreateIndex(auto index on vectorField, indexName vector_idx, metric=metricType) then LoadCollection. Composite: each step failure surfaces its own error code, all HTTP 200.
- State: v1 quick-create forces autoID=true on Int64 PK; schema fixed Int64 PK + FloatVector only
- Constraints:
  - range: dimension required and non-zero; missing/0 -> code 1802 with message: required parameters: [collectionName, dimension] (live-verified)
  - type: metricType enum L2 / IP / COSINE / HAMMING / JACCARD / SUBSTRUCTURE / SUPERSTRUCTURE (pkg/util/metric)
  - state: collection auto-loaded after create; duplicate name -> already-exists error path
- Live-verified: create with dimension 4 -> code 200

#### getCollectionDetails (describe)
- Method: GET; Path: /v1/vector/collections/describe with query param collectionName
- Params: collectionName (required)
- Behavioral: 200 with dbName/collectionName/description/fields[{name,dataType,isPrimary,autoId}]/indexes[{indexName,metricType,fieldName}]/load; not found -> code 100, message: collection not found[database=default][collection=nope] (live-verified)
- Note: GET only - POST with JSON body returns HTTP 404 page not found (route not registered) - live-verified

#### dropCollection
- Method: POST; Path: /v1/vector/collections/drop
- Body: collectionName (required), dbName (opt)
- Behavioral: 200 code 200; non-existent -> error code 100. Live-verified drop-after-create OK.

#### query
- Method: POST; Path: /v1/vector/query
- Body: collectionName (required), filter (string, required, boolean expr), outputFields (array, opt, default star), limit (int32, opt), offset (int32, opt), dbName, partitionNames
- Behavioral: 200 with rows; invalid filter -> 1804-family; limit+offset compose into topK

#### get
- Method: POST; Path: /v1/vector/get
- Body: collectionName (required), id (scalar, required - int64 or string by PK type), outputFields (opt)
- Behavioral: 200 with row; not found -> empty data array

#### delete
- Method: POST; Path: /v1/vector/delete
- Body: collectionName (required), id (opt) OR filter (opt) - exactly one required
- Behavioral: 200 code 200 empty data

#### insert
- Method: POST; Path: /v1/vector/insert
- Body: collectionName (required), data (array of objects, required)
- Behavioral: 200 with insertCount and insertIds
- State constraint (live-verified, key finding): v1-created collections have autoID=true -> explicit id in data fails with code 1804 and message: fail to deal the insert data, error: invalid parameter[expected=][actual=set primary key but autoID == true]; insert WITHOUT id succeeds, server generates id (live example: 468539281520724237)

#### upsert
- Method: POST; Path: /v1/vector/upsert
- Body: same as insert
- Behavioral: 200 with upsertCount and upsertIds; same autoID PK constraint

#### search
- Method: POST; Path: /v1/vector/search
- Body: collectionName (required), vector (array float32, required - single vector, nq fixed 1), filter (opt), limit (int32, opt, default 100), offset (opt, default 0), outputFields (opt), params (object of numeric values, opt; keys radius, range_filter)
- Constraints (source handler_v1.go:830-928):
  - range: missing collectionName or vector -> code 1802, required parameters: [collectionName, vector]
  - behavioral: range_filter without radius is rejected -> code 1802 invalid search params (rangeFilterOk requires radiusOk)
  - consistency hard-coded Bounded; round_decimal hard-coded -1
  - vector dim must equal collection dim -> else 1804-family
  - empty result (TopK==0) -> code 200 with empty array (live-verified on empty collection)
- Live-verified: search after 1 insert returns single hit with distance 0 (L2 self-match)
- Header Accept-Type-Allow-Int64: true -> int64 ids as JSON numbers; default as strings

### RESTful v2 (prefix /v2/vectordb) - 44 endpoints (source: handler_v2.go:49-125; all POST JSON)

#### Collections (10)
- /v2/vectordb/collections/list - body dbName -> data as name array
- /v2/vectordb/collections/has - collectionName (req) -> data {has: bool}
- /v2/vectordb/collections/describe - collectionName (req) -> full schema + indexes + load state
- /v2/vectordb/collections/get_stats - collectionName (req) -> data {rowCount}
- /v2/vectordb/collections/get_load_state - collectionName (req), partitionNames (opt) -> data {loadState: NotLoad|Loading|Loaded, loadProgress: int (-1 on err)}; NotExist mapped to collection-not-found error (source 432-480)
- /v2/vectordb/collections/create - CollectionReq: collectionName (req); EITHER dimension (quick-create: idType Int64|VarChar default Int64; metricType default COSINE in v2; params.max_length for VarChar) OR schema {fields:[{fieldName (req), dataType (req, case-sensitive), isPrimary, isPartitionKey, elementTypeParams {dim, max_length}}], autoID, enableDynamicField}, plus indexParams, params
  - type: idType enum [Int64, VarChar]; invalid -> error message: idType can only be [Int64, VarChar], default: Int64 (source:959)
  - type: field dataType case-sensitive - error message: data type X is invalid (case sensitive) (source:1020)
- /v2/vectordb/collections/drop - collectionName (req)
- /v2/vectordb/collections/rename - collectionName (req), newCollectionName (req), newDbName
- /v2/vectordb/collections/load - collectionName (req) - async; poll get_load_state
- /v2/vectordb/collections/release - collectionName (req)

#### Entities (6)
- /v2/vectordb/entities/query - collectionName (req), filter (req), outputFields, limit, offset, partitionNames
- /v2/vectordb/entities/get - collectionName (req), id (req), outputFields
- /v2/vectordb/entities/delete - collectionName (req), filter (req) OR id
- /v2/vectordb/entities/insert - collectionName (req), data (req array)
- /v2/vectordb/entities/upsert - collectionName (req), data (req)
- /v2/vectordb/entities/search - SearchReqV2: collectionName (req), data (req array - supports multiple vectors, unlike v1), annsField, filter, limit, offset, outputFields, params (map string->float64, numeric only)

#### Partitions (7)
- /v2/vectordb/partitions/list|has|stats|create|drop|load|release - collectionName (req); partitionName (req) for has/stats/create/drop; partitionNames (req array) for load/release

#### Users (7)
- /v2/vectordb/users/list|describe|create|update_password|drop|grant_role|revoke_role - PasswordReq {userName (req), password (req)}; NewPasswordReq adds newPassword (req)

#### Roles (6)
- /v2/vectordb/roles/list|describe|create|drop|grant_privilege|revoke_privilege - GrantReq {roleName (req), objectType (req), objectName (req), privilege (req), dbName}

#### Indexes (4)
- /v2/vectordb/indexes/list - collectionName (req) -> [{indexName, fieldName, state}]
- /v2/vectordb/indexes/describe - collectionName (req), indexName (req) -> {metricType, indexType, totalRows, pendingRows, indexedRows, state, failReason}
- /v2/vectordb/indexes/create - collectionName (req), indexParams (req): [{fieldName (req), indexName (req), metricType (req), params {index_type, M, efConstruction, nlist, ...}}]
- /v2/vectordb/indexes/drop - collectionName (req), indexName (req)

#### Aliases (5)
- /v2/vectordb/aliases/list|describe|create|drop|alter - aliasName (req); collectionName (req) for create/alter

Live-verified: POST /v2/vectordb/collections/list with empty body -> code 200 with collection list (HTTP 200).

### Management / health
- GET http://localhost:9091/healthz -> OK (live-verified)

## Key Domains

### Metric types (enum, pkg/util/metric/metric_type.go)
L2 (euclidean), IP (inner product), COSINE, HAMMING, JACCARD, SUBSTRUCTURE, SUPERSTRUCTURE. v1 default L2; v2 quick-create default COSINE.

### Consistency levels (commonpb.ConsistencyLevel)
Strong, Bounded, Session, Eventually - REST v1 hard-codes Bounded for create/search (source lines 228, 852); not exposed as request parameter on v1/v2 REST in 2.3.x.

### Load state machine
NotExist -> NotLoad -> Loading -> Loaded. get_load_state returns loadProgress (0-100); >=100 -> LoadStateLoaded. Search/query require Loaded state (v1 quick-create auto-loads). Release returns to NotLoad.

### Index build states (describeIndex output)
indexState: InProgress | Finished | Failed | Retry; failReason populated on Failed. v1 auto index name vector_idx.

### PK semantics (high-value contract)
- v1 create: autoID always true -> client-supplied id in insert/upsert rejected (code 1804); v2 explicit schema: autoID default false -> client must supply id
- idType Int64 (JSON number or string per Accept-Type-Allow-Int64 header) or VarChar (string, max_length from params)

### Boolean filter expressions (DslType BoolExprV1)
==, !=, >, >=, <, <=, in [...], like, and/or/not, JSON field access field[key], array contains. query: required; delete: one of id/filter; search: optional pre-filter.

## Data Types
Int64, VarChar (max_length), FloatVector (dim), BinaryVector (dim), Bool, Float, Double, JSON, Array (elementType) - v2 REST dataType strings are case-sensitive

## Collection / Table Schema
- v1 quick-create (fixed): id Int64 PK autoID=true + vector FloatVector (dim=dimension); enableDynamicField default true; shards=1; consistency=Bounded; auto index vector_idx (metric); auto-loaded
- v2 explicit schema: arbitrary fields, autoID controllable, indexParams at create; dimension in elementTypeParams.dim

## Document Coverage (OpenAPI cross-check)
- doc_coverage_pct: N/A (spec unavailable)
- openapi_unavailable: true - no milvus OpenAPI spec (fetch config has no milvus rule). Cross-check performed instead against source route registry: 10 v1 routes + 44 v2 routes extracted mechanically from gin router registration (exhaustive by construction).
- Gate degraded to: source-route enumeration (mechanical anchor) + live-probe behavioral verification (9 probes, all consistent with source-predicted behavior)

## Missing Endpoints
None - all routes registered in RegisterRoutesToV1/RegisterRoutesToV2 are enumerated above. Note v1 describe is GET-only (POST returns HTTP 404).
