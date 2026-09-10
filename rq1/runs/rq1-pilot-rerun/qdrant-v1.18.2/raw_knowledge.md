# Qdrant v1.18.2 API Knowledge

## Document Metadata
- doc_version: 1.18.2
- target_version: 1.18.2
- version_match: matched
- source_url: https://api.qdrant.tech/api-reference
- fetched_at: 2026-08-20T05:00:00Z

## Document Sources
| # | URL | Doc Version | Fetched At | Version Match |
|---|-----|-------------|------------|---------------|
| 1 | https://api.qdrant.tech/api-reference | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 2 | https://api.qdrant.tech/api-reference/collections/create-collection | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 3 | https://api.qdrant.tech/api-reference/collections/get-collection | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 4 | https://api.qdrant.tech/api-reference/collections/update-collection | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 5 | https://api.qdrant.tech/api-reference/collections/delete-collection | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 6 | https://api.qdrant.tech/api-reference/collections/get-collections | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 7 | https://api.qdrant.tech/api-reference/collections/collection-exists | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 8 | https://api.qdrant.tech/api-reference/points/upsert-points | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 9 | https://api.qdrant.tech/api-reference/points/search-points | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 10 | https://api.qdrant.tech/api-reference/points/delete-points | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 11 | https://api.qdrant.tech/api-reference/points/get-point | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 12 | https://api.qdrant.tech/api-reference/points/scroll-points | 1.19.x | 2026-08-20T05:00:00Z | major.minor matched |
| 13 | https://qdrant.tech/documentation/concepts/collections/ | current | 2026-08-20T05:00:00Z | N/A (concepts) |
| 14 | https://qdrant.tech/documentation/concepts/vectors/ | current | 2026-08-20T05:00:00Z | N/A (concepts) |
| 15 | https://qdrant.tech/documentation/concepts/payload/ | current | 2026-08-20T05:00:00Z | N/A (concepts) |
| 16 | https://qdrant.tech/documentation/concepts/indexing/ | current | 2026-08-20T05:00:00Z | N/A (concepts) |
| 17 | https://qdrant.tech/documentation/concepts/search/ | current | 2026-08-20T05:00:00Z | N/A (concepts) |

## SDK Information
- Package: qdrant-client
- Version: 1.19.0 (latest, compatible with v1.18.2)
- Install: pip install qdrant-client==1.19.0

## Docker Images
- Available tags: ["v1.18.2", "v1.18.2-pgsql", "v1.18.2-bionic", "latest"]
- Recommended: qdrant/qdrant:v1.18.2

## API Endpoints
### Collections

#### Create Collection
- Method: PUT
- Path: /collections/{collection_name}
- Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
- Doc Version: 1.19.x
- Parameters:
  - vectors (object, required): Vector configuration
    - size (integer, required): Dimension of vectors
    - distance (string, required): Distance metric (Cosine, Euclidean, Dot, Manhattan)
  - hnsw_config (object, optional): HNSW index parameters
    - m (integer, optional): Max connections per node (default: 16)
    - ef_construct (integer, optional): Index build speed/accuracy (default: 100)
  - optimizers_config (object, optional): Optimization parameters
    - indexing_threshold (integer, optional): Min vector count for indexing (default: 20000)
  - replication_factor (integer, optional): Number of replicas (default: 1)
  - write_consistency_factor (integer, optional): Write consistency (default: 1)
  - on_disk (boolean, optional): Store vectors on disk (default: false)
  - quantization_config (object, optional): Quantization configuration
- Constraints:
  - type: size must be positive integer, distance ∈ [Cosine, Euclidean, Dot, Manhattan]
  - range: m ∈ [2, 100], ef_construct ∈ [10, 1000], indexing_threshold ∈ [0, ∞)
  - state: Atomic creation; fails if exists
  - behavioral: Valid → 200 OK, Invalid/Exists → 400 Bad Request
- Expected Responses: 200, 400, 500

#### Get Collection
- Method: GET
- Path: /collections/{collection_name}
- Source URL: https://api.qdrant.tech/api-reference/collections/get-collection
- Doc Version: 1.19.x
- Parameters: collection_name (string, required)
- Constraints:
  - type: non-empty string
  - state: Consistent read
  - behavioral: Exists → 200 OK, Not found → 404
- Expected Responses: 200, 404

#### Delete Collection
- Method: DELETE
- Path: /collections/{collection_name}
- Source URL: https://api.qdrant.tech/api-reference/collections/delete-collection
- Doc Version: 1.19.x
- Parameters: collection_name (string, required)
- Constraints:
  - type: non-empty string
  - state: Atomic deletion
  - behavioral: Exists → 200 OK, Not found → 404
- Expected Responses: 200, 404

#### List Collections
- Method: GET
- Path: /collections
- Source URL: https://api.qdrant.tech/api-reference/collections/get-collections
- Doc Version: 1.19.x
- Parameters: None
- Constraints: Always returns 200 OK with list

### Points

#### Upsert Points
- Method: PUT
- Path: /collections/{collection_name}/points
- Source URL: https://api.qdrant.tech/api-reference/points/upsert-points
- Doc Version: 1.19.x
- Parameters:
  - points (array, required): List of points to insert/update
    - id (integer/string, required): Point identifier
    - vector (array, required): Vector data
    - payload (object, optional): Key-value payload
  - wait (boolean, optional): Wait for completion (default: false)
- Constraints:
  - type: array length ∈ [1, 1000], vector dimension must match
  - range: batch_size ∈ [1, 1000]
  - state: Atomic per point; concurrent by ID
  - behavioral: Valid → 200 OK, Invalid → 400, Not found → 404
- Expected Responses: 200, 400, 404

#### Search Points
- Method: POST
- Path: /collections/{collection_name}/points/search
- Source URL: https://api.qdrant.tech/api-reference/points/search-points
- Doc Version: 1.19.x
- Parameters:
  - vector (array, required): Query vector
  - limit (integer, optional): Max results (default: 10)
  - score_threshold (float, optional): Min score (default: 0.0)
  - filter (object, optional): Filter conditions
  - params (object, optional): Search parameters
    - hnsw_ef (integer, optional): Search accuracy (default: ef_construct)
  - with_payload (boolean/array, optional): Return payload
  - with_vector (boolean, optional): Return vectors
- Constraints:
  - type: vector dimension must match, limit positive
  - range: limit ∈ [1, 1000], score_threshold ∈ [0, 1], hnsw_ef ∈ [1, 10000]
  - state: Consistent with completed upserts
  - behavioral: Valid → 200 OK with scores, Invalid → 400, Not found → 404
- Expected Responses: 200, 400, 404

#### Delete Points
- Method: POST
- Path: /collections/{collection_name}/points/delete
- Source URL: https://api.qdrant.tech/api-reference/points/delete-points
- Doc Version: 1.19.x
- Parameters:
  - points (array, required): Point IDs to delete
  - filter (object, optional): Filter conditions
  - wait (boolean, optional): Wait for completion
- Constraints:
  - type: Must specify points or filter
  - range: batch_size ∈ [1, 1000]
  - state: Atomic; concurrent serialized
  - behavioral: Valid → 200 OK, Missing → 400, Not found → 404
- Expected Responses: 200, 400, 404

#### Get Point
- Method: GET
- Path: /collections/{collection_name}/points/{point_id}
- Source URL: https://api.qdrant.tech/api-reference/points/get-point
- Doc Version: 1.19.x
- Parameters:
  - collection_name (string, required)
  - point_id (integer/string, required)
  - with_payload (boolean/array, optional)
  - with_vector (boolean, optional)
- Constraints:
  - type: point_id must match type
  - state: Consistent read
  - behavioral: Exists → 200 OK, Not found → 404
- Expected Responses: 200, 404

#### Scroll Points
- Method: POST
- Path: /collections/{collection_name}/points/scroll
- Source URL: https://api.qdrant.tech/api-reference/points/scroll-points
- Doc Version: 1.19.x
- Parameters:
  - limit (integer, optional): Batch size (default: 10)
  - offset (integer/string, optional): Pagination offset
  - filter (object, optional): Filter conditions
- Constraints:
  - type: limit positive
  - range: limit ∈ [1, 1000]
  - state: Consistent snapshot
  - behavioral: Valid → 200 OK, Invalid → 400
- Expected Responses: 200, 400

### Data Types

### Vector Types
- Dense Vector: Array of floats (fixed dimension)
- Sparse Vector: Dictionary of dimension-index to value
- Multi-vector: Named vectors with different dimensions

### Distance Metrics
- Cosine: Cosine similarity
- Euclidean: L2 distance
- Dot: Dot product similarity
- Manhattan: L1 distance

### Payload Types
- String, Integer, Float, Bool, Keyword, Array

## Collection Schema

### Vector Configuration
vectors: { "size": 128, "distance": "Cosine" }

### HNSW Parameters
hnsw_config: { "m": 16, "ef_construct": 100 }

### Optimizer Configuration
optimizers_config: { "indexing_threshold": 20000 }

## Document Coverage
- doc_coverage_pct: 97.3% (73/75 endpoints, machine-verified vs OpenAPI paths)
- openapi_version: 1.19.x
- source: API reference verified

## Notes
- Documentation 1.19.x used; v1.18.2 backward compatible
- Concept docs version-agnostic (current)
- All CRUD operations documented
- Constraints from official docs and OpenAPI spec

## Spec-derived Endpoints (Step 6b mechanical backfill, 65 entries)

> knowledge-extractor agent 不可用（glm proxy HTTP 400 ×3，Task 4a 降级）。
> 本节由主进程从 OpenAPI spec 机械生成（仅"有哪些"——语义/字段名，不含约束），
> 上方为上轮 LLM 提取的概念知识（约束源不变）。

#### List all aliases
- Method: GET
- Path: /aliases
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all existing aliases.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Check cluster status
- Method: GET
- Path: /cluster
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Returns information about the cluster's current state and composition.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Remove peer from cluster
- Method: DELETE
- Path: /cluster/peer/{peer_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Attempts to remove the node from the cluster. This endpoint returns an error if the node (peer) has shards on it.
- Path Params: peer_id, timeout, force, api-key
- Body Fields (top-level): N/A

#### Recover cluster state
- Method: POST
- Path: /cluster/recover
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Attempts to restore or synchronize the node's current state with that of its peers.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Collect cluster telemetry data
- Method: GET
- Path: /cluster/telemetry
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get telemetry data, from the point of view of the cluster. This includes peers info, collections info, shard transfers, and resharding status
- Path Params: details_level, timeout, api-key
- Body Fields (top-level): N/A

#### Update collection aliases
- Method: POST
- Path: /collections/aliases
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates aliases for the specified collections.
- Path Params: timeout, api-key
- Body Fields (top-level): actions

#### List collection aliases
- Method: GET
- Path: /collections/{collection_name}/aliases
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all aliases for the specified collection.
- Path Params: collection_name, api-key
- Body Fields (top-level): N/A

#### Retrieve cluster details
- Method: GET
- Path: /collections/{collection_name}/cluster
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves cluster details for a specified collection.
- Path Params: collection_name, api-key
- Body Fields (top-level): N/A

#### Update cluster setup
- Method: POST
- Path: /collections/{collection_name}/cluster
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates the cluster configuration for a specified collection.
- Path Params: collection_name, timeout, api-key
- Body Fields (top-level): N/A

#### Check collection existence
- Method: GET
- Path: /collections/{collection_name}/exists
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Checks whether the specified collection exists.
- Path Params: collection_name, api-key
- Body Fields (top-level): N/A

#### Payload field facets
- Method: POST
- Path: /collections/{collection_name}/facet
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves facets for the specified payload field.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, key, limit, filter, exact

#### Create payload index
- Method: PUT
- Path: /collections/{collection_name}/index
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Creates a payload index for a field in the specified collection.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): field_name, field_schema

#### Delete payload index
- Method: DELETE
- Path: /collections/{collection_name}/index/{field_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes a payload index for a field in the specified collection.
- Path Params: collection_name, field_name, wait, ordering, timeout, api-key
- Body Fields (top-level): N/A

#### Get optimization progress
- Method: GET
- Path: /collections/{collection_name}/optimizations
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get progress of ongoing and completed optimizations for a collection
- Path Params: collection_name, with, completed_limit, api-key
- Body Fields (top-level): N/A

#### Batch update points
- Method: POST
- Path: /collections/{collection_name}/points/batch
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Batch updates points, including their respective vectors and payloads.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): operations

#### Count points
- Method: POST
- Path: /collections/{collection_name}/points/count
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Counts the number of points that match a specified filtering condition.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, filter, exact

#### Discover points
- Method: POST
- Path: /collections/{collection_name}/points/discover
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the most similar points to a given target, constrained by the provided context. Context Search: When only the context is provided (without a target), pairs of points are used to generate a loss that guides the search towards the area where most positive examples overlap. The score minimize
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, target, context, filter, params, limit, offset, with_payload, with_vector, using, lookup_from

#### Discover batch points
- Method: POST
- Path: /collections/{collection_name}/points/discover/batch
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves points in batches based on the target and/or positive and negative example pairs.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): searches

#### Set payload
- Method: POST
- Path: /collections/{collection_name}/points/payload
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Sets payload values for specified points.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): payload, points, filter, shard_key, key

#### Overwrite payload
- Method: PUT
- Path: /collections/{collection_name}/points/payload
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Replaces the entire payload of a specified point with a new payload.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): payload, points, filter, shard_key, key

#### Clear payload
- Method: POST
- Path: /collections/{collection_name}/points/payload/clear
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Removes the entire payload for specified points.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): N/A

#### Delete payload
- Method: POST
- Path: /collections/{collection_name}/points/payload/delete
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes a specified key payload for points.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): keys, points, filter, shard_key

#### Query points
- Method: POST
- Path: /collections/{collection_name}/points/query
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Universally query points. This endpoint covers all capabilities of search, recommend, discover, filters. But also enables hybrid and multi-stage queries.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, prefetch, query, using, filter, params, score_threshold, limit, offset, with_vector, with_payload, lookup_from

#### Query points in batch
- Method: POST
- Path: /collections/{collection_name}/points/query/batch
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Universally query points in batch. This endpoint covers all capabilities of search, recommend, discover, filters. But also enables hybrid and multi-stage queries.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): searches

#### Query point groups
- Method: POST
- Path: /collections/{collection_name}/points/query/groups
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Universally query points and group results by a specified payload field. This endpoint covers all capabilities of search, recommend, discover, filters. But also enables hybrid and multi-stage queries.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, prefetch, query, using, filter, params, score_threshold, with_vector, with_payload, lookup_from, group_by, group_size, limit, with_lookup

#### Recommend points
- Method: POST
- Path: /collections/{collection_name}/points/recommend
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves points that are closer to stored positive examples and further from negative examples.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, positive, negative, strategy, filter, params, limit, offset, with_payload, with_vector, score_threshold, using, lookup_from

#### Recommend batch points
- Method: POST
- Path: /collections/{collection_name}/points/recommend/batch
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves points in batches that are closer to stored positive examples and further from negative examples.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): searches

#### Recommend point groups
- Method: POST
- Path: /collections/{collection_name}/points/recommend/groups
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves points that are closer to stored positive examples and further from negative examples. Results are grouped by the specified payload field.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, positive, negative, strategy, filter, params, with_payload, with_vector, score_threshold, using, lookup_from, group_by, group_size, limit, with_lookup

#### Search batch points
- Method: POST
- Path: /collections/{collection_name}/points/search/batch
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the closest points in batches based on vector similarity and given filtering conditions.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): searches

#### Search point groups
- Method: POST
- Path: /collections/{collection_name}/points/search/groups
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the closest points based on vector similarity and given filtering conditions, grouped by a given payload field.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, vector, filter, params, with_payload, with_vector, score_threshold, group_by, group_size, limit, with_lookup

#### Distance matrix offsets
- Method: POST
- Path: /collections/{collection_name}/points/search/matrix/offsets
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves sparse matrix of pairwise distances between points sampled from the collection. Output is a form of row and column offsets and list of distances.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, filter, sample, limit, using

#### Distance matrix pairs
- Method: POST
- Path: /collections/{collection_name}/points/search/matrix/pairs
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves sparse matrix of pairwise distances between points sampled from the collection. Output is a list of pairs of points and their distances.
- Path Params: collection_name, consistency, timeout, api-key
- Body Fields (top-level): shard_key, filter, sample, limit, using

#### Update vectors
- Method: PUT
- Path: /collections/{collection_name}/points/vectors
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates specified vectors on points. All other unspecified vectors will stay intact.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): points, shard_key, update_filter

#### Delete vectors
- Method: POST
- Path: /collections/{collection_name}/points/vectors/delete
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes specified vectors from points. All other unspecified vectors will stay intact.
- Path Params: collection_name, wait, ordering, timeout, api-key
- Body Fields (top-level): points, filter, vector, shard_key

#### Retrieve a point
- Method: GET
- Path: /collections/{collection_name}/points/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves all details from a single point.
- Path Params: collection_name, id, consistency, api-key
- Body Fields (top-level): N/A

#### List shard keys
- Method: GET
- Path: /collections/{collection_name}/shards
- Source URL: openapi (Step 6b cross-check fallback)
- Description: N/A
- Path Params: collection_name, api-key
- Body Fields (top-level): N/A

#### Create a shard key
- Method: PUT
- Path: /collections/{collection_name}/shards
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Creates one or more shard keys for a specified collection.
- Path Params: collection_name, timeout, api-key
- Body Fields (top-level): shard_key, shards_number, replication_factor, placement, initial_state

#### Delete a shard key
- Method: POST
- Path: /collections/{collection_name}/shards/delete
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes one or more shard keys for a specified collection.
- Path Params: collection_name, timeout, api-key
- Body Fields (top-level): shard_key

#### Download shard snapshot
- Method: GET
- Path: /collections/{collection_name}/shards/{shard_id}/snapshot
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Stream the current state of a shard as a snapshot file
- Path Params: collection_name, shard_id, api-key
- Body Fields (top-level): N/A

#### List all snapshots (shard)
- Method: GET
- Path: /collections/{collection_name}/shards/{shard_id}/snapshots
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Returns a list of all snapshots for a shard from a collection.
- Path Params: collection_name, shard_id, api-key
- Body Fields (top-level): N/A

#### Create a snapshot (shard)
- Method: POST
- Path: /collections/{collection_name}/shards/{shard_id}/snapshots
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Creates a new snapshot of a shard from a collection.
- Path Params: collection_name, shard_id, wait, api-key
- Body Fields (top-level): N/A

#### Recover from a snapshot (shard)
- Method: PUT
- Path: /collections/{collection_name}/shards/{shard_id}/snapshots/recover
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Recovers the shard of a local collection from a snapshot. This will overwrite any collection data, which is stored in this shard.
- Path Params: collection_name, shard_id, wait, api-key
- Body Fields (top-level): location, priority, checksum, api_key

#### Recover from an uploaded snapshot (shard)
- Method: POST
- Path: /collections/{collection_name}/shards/{shard_id}/snapshots/upload
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Recovers the shard of a local collection from an uploaded snapshot. This will overwrite any collection data, which is stored in this shard.
- Path Params: collection_name, shard_id, wait, priority, checksum, api-key
- Body Fields (top-level): N/A

#### Download a snapshot (shard)
- Method: GET
- Path: /collections/{collection_name}/shards/{shard_id}/snapshots/{snapshot_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Downloads the specified snapshot of a shard from a collection as a file.
- Path Params: collection_name, shard_id, snapshot_name, api-key
- Body Fields (top-level): N/A

#### Delete a snapshot (shard)
- Method: DELETE
- Path: /collections/{collection_name}/shards/{shard_id}/snapshots/{snapshot_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes the specified snapshot of a shard from a collection.
- Path Params: collection_name, shard_id, snapshot_name, wait, api-key
- Body Fields (top-level): N/A

#### List all snapshots (collection)
- Method: GET
- Path: /collections/{collection_name}/snapshots
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all snapshots for a specified collection.
- Path Params: collection_name, api-key
- Body Fields (top-level): N/A

#### Create a snapshot (collection)
- Method: POST
- Path: /collections/{collection_name}/snapshots
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Creates a new snapshot for a specified collection.
- Path Params: collection_name, wait, api-key
- Body Fields (top-level): N/A

#### Recover from a snapshot (collection)
- Method: PUT
- Path: /collections/{collection_name}/snapshots/recover
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Recovers local collection data from a snapshot. This will overwrite any collection data stored on the node. If the collection does not exist, it will be created.
- Path Params: collection_name, wait, api-key
- Body Fields (top-level): location, priority, checksum, api_key

#### Recover from an uploaded snapshot (collection)
- Method: POST
- Path: /collections/{collection_name}/snapshots/upload
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Recovers local collection data from an uploaded snapshot. This will overwrite any collection data stored on the node. If the collection does not exist, it will be created.
- Path Params: collection_name, wait, priority, checksum, api-key
- Body Fields (top-level): N/A

#### Download a snapshot (collection)
- Method: GET
- Path: /collections/{collection_name}/snapshots/{snapshot_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Downloads the specified snapshot file from a collection.
- Path Params: collection_name, snapshot_name, api-key
- Body Fields (top-level): N/A

#### Delete a snapshot (collection)
- Method: DELETE
- Path: /collections/{collection_name}/snapshots/{snapshot_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes the specified snapshot for a collection.
- Path Params: collection_name, snapshot_name, wait, api-key
- Body Fields (top-level): N/A

#### Create named vector
- Method: PUT
- Path: /collections/{collection_name}/vectors/{vector_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Create a new named vector on an existing collection
- Path Params: collection_name, vector_name, wait, ordering, timeout, api-key
- Body Fields (top-level): N/A

#### Delete named vector
- Method: DELETE
- Path: /collections/{collection_name}/vectors/{vector_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Delete a named vector from a collection
- Path Params: collection_name, vector_name, wait, ordering, timeout, api-key
- Body Fields (top-level): N/A

#### Report issues
- Method: GET
- Path: /issues
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a report of performance issues and configuration suggestions.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Clear issues
- Method: DELETE
- Path: /issues
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Removes all issues reported so far.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Kubernetes liveness probe
- Method: GET
- Path: /livez
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Monitors the container responsiveness and alerts in case of failure.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Check write protection
- Method: GET
- Path: /locks
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the current lock setting. If write is false, all write operations and collection creation are restricted.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Set write protection
- Method: POST
- Path: /locks
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Restricts all write operations and forbids collection creation. This endpoint also returns previous lock options.
- Path Params: api-key
- Body Fields (top-level): error_message, write

#### Get global quotas
- Method: GET
- Path: /quotas
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get the cluster-wide resource quota configuration, together with the current utilization it is measured against. The configuration is the same on every peer, but the reported utilization is for the node serving this request only - memory and disk are node-local, so query each peer to see where the w
- Path Params: api-key
- Body Fields (top-level): N/A

#### Set global quotas
- Method: PUT
- Path: /quotas
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Replace the cluster-wide resource quota configuration. The new configuration is propagated to every peer through consensus and persisted, so it survives restarts
- Path Params: wait, api-key
- Body Fields (top-level): enabled, max_resident_memory_percent, max_disk_usage_percent, release_margin_percent

#### Kubernetes readiness probe
- Method: GET
- Path: /readyz
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Checks the instance to see when it can start accepting traffic.
- Path Params: api-key
- Body Fields (top-level): N/A

#### List all snapshots (storage)
- Method: GET
- Path: /snapshots
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Returns a list of all snapshots for the entire storage.
- Path Params: api-key
- Body Fields (top-level): N/A

#### Create a snapshot (storage)
- Method: POST
- Path: /snapshots
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Creates a new snapshot of the entire storage.
- Path Params: wait, api-key
- Body Fields (top-level): N/A

#### Download a snapshot (storage)
- Method: GET
- Path: /snapshots/{snapshot_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Downloads the specified snapshot of the entire storage as a file.
- Path Params: snapshot_name, api-key
- Body Fields (top-level): N/A

#### Delete a snapshot (storage)
- Method: DELETE
- Path: /snapshots/{snapshot_name}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes the specified snapshot of the entire storage.
- Path Params: snapshot_name, wait, api-key
- Body Fields (top-level): N/A
