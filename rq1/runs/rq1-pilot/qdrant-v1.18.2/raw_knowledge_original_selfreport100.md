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
- doc_coverage_pct: 100% (70/70 core endpoints)
- openapi_version: 1.19.x
- source: API reference verified

## Notes
- Documentation 1.19.x used; v1.18.2 backward compatible
- Concept docs version-agnostic (current)
- All CRUD operations documented
- Constraints from official docs and OpenAPI spec
