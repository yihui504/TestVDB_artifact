=== 候选缺陷 milvus_016 ===
[vendor=milvus version=2.6.16 defect_type=param_validation endpoint=entities+search]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] HNSW search with ef=-1 -> http=200, code=0
- [c2] HNSW search with ef=0 -> http=200, code=0
- [c3] IVF_FLAT search with nprobe=0 -> http=200, code=0

执行日志全文（output_milvus_016.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_hnsw_ef", "dbName": "default"}
=== RESP 1 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_ivf_nprobe", "dbName": "default"}
=== RESP 2 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_hnsw_ef", "dimension": 4, "metricType": "L2"}
=== RESP 3 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 4 ===
POST http://localhost:19530/v2/vectordb/indexes/create
payload: {"collectionName": "test_hnsw_ef", "indexParams": [{"fieldName": "vector", "metricType": "L2", "indexType": "HNSW", "params": {"M": 16, "efConstruction": 128}}]}
=== RESP 4 ===
status: 200
body: {"code":65535,"message":"CreateIndex failed: at most one distinct index is allowed per field"}

=== REQ 5 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_hnsw_ef", "data": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 5 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[1]}}

=== REQ 6 ===
POST http://localhost:19530/v2/vectordb/collections/load
payload: {"collectionName": "test_hnsw_ef", "dbName": "default"}
=== RESP 6 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 7 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_ivf_nprobe", "dimension": 4, "metricType": "L2"}
=== RESP 7 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 8 ===
POST http://localhost:19530/v2/vectordb/indexes/create
payload: {"collectionName": "test_ivf_nprobe", "indexParams": [{"fieldName": "vector", "metricType": "L2", "indexType": "IVF_FLAT", "params": {"nlist": 128}}]}
=== RESP 8 ===
status: 200
body: {"code":65535,"message":"CreateIndex failed: at most one distinct index is allowed per field"}

=== REQ 9 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_ivf_nprobe", "data": [{"id": 0, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 9 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":2,"insertIds":[0,1]}}

=== REQ 10 ===
POST http://localhost:19530/v2/vectordb/collections/load
payload: {"collectionName": "test_ivf_nprobe", "dbName": "default"}
=== RESP 10 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 11 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_hnsw_ef", "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5, "searchParams": {"ef": -1}}
=== RESP 11 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":0,"id":1}],"topks":[1]}


=== REQ 12 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_hnsw_ef", "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5, "searchParams": {"ef": 0}}
=== RESP 12 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":0,"id":1}],"topks":[1]}


=== REQ 13 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_ivf_nprobe", "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5, "searchParams": {"nprobe": 0}}
=== RESP 13 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":0,"id":0},{"distance":0,"id":1}],"topks":[2]}


=== REQ 14 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_hnsw_ef", "dbName": "default"}
=== RESP 14 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 15 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_ivf_nprobe", "dbName": "default"}
=== RESP 15 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 16 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_hnsw_ef", "dimension": 4, "metricType": "L2"}
=== RESP 16 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 17 ===
POST http://localhost:19530/v2/vectordb/indexes/create
payload: {"collectionName": "test_hnsw_ef", "indexParams": [{"fieldName": "vector", "metricType": "L2", "indexType": "HNSW", "params": {"M": 16, "efConstruction": 128}}]}
=== RESP 17 ===
status: 200
body: {"code":65535,"message":"CreateIndex failed: at most one distinct index is allowed per field"}

=== REQ 18 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_hnsw_ef", "data": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 18 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[1]}}

=== REQ 19 ===
POST http://localhost:19530/v2/vectordb/collections/load
payload: {"collectionName": "test_hnsw_ef", "dbName": "default"}
=== RESP 19 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 20 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_ivf_nprobe", "dimension": 4, "metricType": "L2"}
=== RESP 20 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 21 ===
POST http://localhost:19530/v2/vectordb/indexes/create
payload: {"collectionName": "test_ivf_nprobe", "indexParams": [{"fieldName": "vector", "metricType": "L2", "indexType": "IVF_FLAT", "params": {"nlist": 128}}]}
=== RESP 21 ===
status: 200
body: {"code":65535,"message":"CreateIndex failed: at most one distinct index is allowed per field"}

=== REQ 22 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_ivf_nprobe", "data": [{"id": 0, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 22 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":2,"insertIds":[0,1]}}

=== REQ 23 ===
POST http://localhost:19530/v2/vectordb/collections/load
payload: {"collectionName": "test_ivf_nprobe", "dbName": "default"}
=== RESP 23 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 24 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_hnsw_ef", "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5, "searchParams": {"ef": -1}}
=== RESP 24 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":0,"id":1}],"topks":[1]}


=== REQ 25 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_hnsw_ef", "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5, "searchParams": {"ef": 0}}
=== RESP 25 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":0,"id":1}],"topks":[1]}


=== REQ 26 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_ivf_nprobe", "data": [[0.1, 0.2, 0.3, 0.4]], "limit": 5, "searchParams": {"nprobe": 0}}
=== RESP 26 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":0,"id":0},{"distance":0,"id":1}],"topks":[2]}




--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（10 条，来自 milvus 2.6.16 契约，endpoint=entities+search）：
{"constraint_id": "milvus_type_entities_delete_001", "endpoint": "entities+delete", "type": "type_constraint", "description": "filter must be a valid boolean expression string", "assertion": "filter is a valid boolean expression", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"constraint_id": "milvus_type_entities_get_001", "endpoint": "entities+get", "type": "type_constraint", "description": "id must match the collection primary key type (Int64 or VarChar)", "assertion": "id type matches collection primary key type", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Get.md", "confidence": 1.0}
{"constraint_id": "milvus_type_entities_search_001", "endpoint": "entities+search", "type": "type_constraint", "description": "data must be array of float arrays, annsField must be a vector field, limit must be positive integer", "assertion": "data is array[array[float]] AND annsField is a vector field AND limit > 0", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "confidence": 1.0}
{"constraint_id": "milvus_range_entities_search_001", "endpoint": "entities+search", "type": "range_constraint", "description": "vector dimensions in data must match collection vector dimension", "assertion": "vector dimension == collection dimension", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "confidence": 1.0}
{"constraint_id": "milvus_range_entities_search_002", "endpoint": "entities+search", "type": "range_constraint", "description": "limit + offset must be < 16384", "assertion": "limit + offset < 16384", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "confidence": 1.0}
{"constraint_id": "milvus_state_entities_delete_001", "endpoint": "entities+delete", "type": "state_constraint", "description": "Deleted entities cannot be recovered", "assertion": "delete is irreversible", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"constraint_id": "milvus_state_entities_search_001", "endpoint": "entities+search", "type": "state_constraint", "description": "Collection must be loaded; index must exist on annsField", "assertion": "collection is loaded AND index exists on annsField", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "confidence": 1.0}
{"assertion_id": "milvus_behavioral_entities_search_001", "endpoint": "entities+search", "description": "Search returns 400 on vector dimension mismatch", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "confidence": 1.0}
{"assertion_id": "milvus_behavioral_entities_delete_001", "endpoint": "entities+delete", "description": "Delete returns 400 on invalid filter expression", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"assertion_id": "milvus_behavioral_entities_get_001", "endpoint": "entities+get", "description": "Get entities returns 400 if id type mismatches collection schema", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Get.md", "confidence": 1.0}

相关契约段（关键词定位 3 条）：
{"endpoint": "entities+search", "kind": "type_constraints", "description": "data must be array of float arrays, annsField must be a vector field, limit must be positive integer", "assertion": "data is array[array[float]] AND annsField is a vector field AND limit > 0", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "confidence": 1.0}
{"endpoint": "entities+query", "kind": "range_constraints", "description": "limit + offset must be < 16384", "assertion": "limit + offset < 16384", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"endpoint": "entities+search", "kind": "range_constraints", "description": "limit + offset must be < 16384", "assertion": "limit + offset < 16384", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "confidence": 1.0}

API 模板：endpoint=collections+create doc_quote='200 on success; 400 on invalid parameters; 404 if database does not exist' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"assertion_id": "milvus_behavioral_collections_create_001", "endpoint": "collections+create", "description": "Create collection returns 200 on success", "category": "behavioral", "expected_behavior": "returns 200 with code: 0 and empty data object", "confidence": 1.0, "defect_type_if_violated": "Type1_IllegalSuccess", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "doc_version": "2.6.x"}
{"constraint_id": "milvus_type_collections_create_001", "endpoint": "collections+create", "description": "collectionName must be a string", "assertion": "collectionName is of type string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_collections_drop_001", "endpoint": "collections+drop", "description": "collectionName must be a non-empty string", "assertion": "collectionName is non-empty string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_collections_load_001", "endpoint": "collections+load", "description": "collectionName must be a non-empty string for load", "assertion": "collectionName is non-empty string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Load.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_collections_rename_001", "endpoint": "collections+rename", "description": "collectionName and newCollectionName must be non-empty strings", "assertion": "collectionName is non-empty string AND newCollectionName is non-empty string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Rename.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_collections_create_001", "endpoint": "collections+create", "description": "Collection creation is atomic; collection name must be unique within a database", "assertion": "collection creation is atomic AND collectionName is unique within dbName", "type": "state_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "source_status": "reachable"}
{"invariant_id": "milvus_invariant_create_queryable_001", "description": "After a collection is created, it must be describable and appear in the collection list", "assertion": "create(collection) -> describe(collection) must return 200 AND list() must contain collectionName", "scope": "per_collection", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md"}
{"constraint_id": "milvus_type_entities_insert_001", "endpoint": "entities+insert", "description": "data must contain field values matching collection schema data types", "assertion": "data field types match collection schema", "type": "type_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_type_entities_search_001", "endpoint": "entities+search", "description": "data must be array of float arrays, annsField must be a vector field, limit must be positive integer", "assertion": "data is array[array[float]] AND annsField is a vector field AND limit > 0", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_entities_upsert_001", "endpoint": "entities+upsert", "description": "Primary key field must be specified in data for upsert", "assertion": "data contains primary key field", "type": "type_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_range_entities_insert_001", "endpoint": "entities+insert", "description": "Max 100 entities per single insert call via REST API", "assertion": "len(data) <= 100", "type": "range_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_range_entities_search_001", "endpoint": "entities+search", "description": "vector dimensions in data must match collection vector dimension", "assertion": "vector dimension == collection dimension", "type": "range_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_collections_drop_001", "endpoint": "collections+drop", "description": "Drop is irreversible; all data in the collection is permanently deleted", "assertion": "drop is irreversible AND all data is permanently deleted", "type": "state_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_databases_drop_001", "endpoint": "databases+drop", "description": "Cannot drop the default database; database must be empty (no collections)", "assertion": "dbName != '_default' AND database has no collections", "type": "state_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
