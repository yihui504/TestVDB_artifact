=== 候选缺陷 milvus_042 ===
[vendor=milvus version=3.0.0 defect_type=type_coercion endpoint=entities+insert]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] REST insert string-encoded vector -> http=200, code=0
- [c1_s] search after string-vector insert -> http=200, code=0, data: id=0 distance=1
- [c1_grpc] gRPC insert string vector -> DataNotMatchException code=1, message: vector field should be float_vector, got str

执行日志全文（output_milvus_042.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_vec_str", "dbName": "default"}
=== RESP 1 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_vec_str", "dimension": 4}
=== RESP 2 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_vec_str", "data": [{"id": 0, "vector": "[0.1,0.2,0.3,0.4]"}]}
=== RESP 3 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[0]}}

=== REQ 4 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_vec_str", "data": [[0.1, 0.2, 0.3, 0.4]], "annsField": "vector", "limit": 5, "outputFields": ["id"]}
=== RESP 4 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":1,"id":0}],"topks":[1]}


=== REQ 5 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_vec_str", "dbName": "default"}
=== RESP 5 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 6 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_vec_str", "dimension": 4}
=== RESP 6 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 7 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_vec_str", "data": [{"id": 0, "vector": "[0.1,0.2,0.3,0.4]"}]}
=== RESP 7 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[0]}}

=== REQ 8 ===
POST http://localhost:19530/v2/vectordb/entities/search
payload: {"collectionName": "test_vec_str", "data": [[0.1, 0.2, 0.3, 0.4]], "annsField": "vector", "limit": 5, "outputFields": ["id"]}
=== RESP 8 ===
status: 200
body: {"code":0,"cost":0,"data":[{"distance":1,"id":0}],"topks":[1]}




--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（3 条，来自 milvus 3.0.0 契约，endpoint=entities+insert）：
{"constraint_id": "milvus_state_insert_collection_001", "endpoint": "entities+insert", "type": "state_constraint", "description": "Insert requires existing collection", "assertion": "collection MUST exist before insert", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}
{"assertion_id": "milvus_behavioral_insert_then_get_001", "endpoint": "entities+insert", "description": "Inserted entities should be retrievable", "source_url": "https://milvus.io/docs/insert-update.md", "confidence": 1.0}
{"assertion_id": "milvus_assert_insert_success_001", "endpoint": "entities+insert", "description": "Inserting valid data succeeds", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}

API 模板：endpoint=entities+insert doc_quote='Insert entities' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "milvus_type_entities_search_001", "endpoint": "entities+search", "description": "data must be array of float arrays, annsField must be a vector field, limit must be positive integer", "assertion": "data is array[array[float]] AND annsField is a vector field AND limit > 0", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_entities_search_001", "endpoint": "entities+search", "description": "Collection must be loaded; index must exist on annsField", "assertion": "collection is loaded AND index exists on annsField", "type": "state_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "source_status": "reachable"}
{"assertion_id": "milvus_behavioral_collections_create_001", "endpoint": "collections+create", "description": "Create collection returns 200 on success", "category": "behavioral", "expected_behavior": "returns 200 with code: 0 and empty data object", "confidence": 1.0, "defect_type_if_violated": "Type1_IllegalSuccess", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "doc_version": "2.6.x"}
{"constraint_id": "milvus_type_collections_create_001", "endpoint": "collections+create", "description": "collectionName must be a string", "assertion": "collectionName is of type string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_collections_drop_001", "endpoint": "collections+drop", "description": "collectionName must be a non-empty string", "assertion": "collectionName is non-empty string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_collections_load_001", "endpoint": "collections+load", "description": "collectionName must be a non-empty string for load", "assertion": "collectionName is non-empty string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Load.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_collections_rename_001", "endpoint": "collections+rename", "description": "collectionName and newCollectionName must be non-empty strings", "assertion": "collectionName is non-empty string AND newCollectionName is non-empty string", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Rename.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_collections_create_001", "endpoint": "collections+create", "description": "Collection creation is atomic; collection name must be unique within a database", "assertion": "collection creation is atomic AND collectionName is unique within dbName", "type": "state_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "source_status": "reachable"}
{"invariant_id": "milvus_invariant_create_queryable_001", "description": "After a collection is created, it must be describable and appear in the collection list", "assertion": "create(collection) -> describe(collection) must return 200 AND list() must contain collectionName", "scope": "per_collection", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md"}
{"constraint_id": "milvus_type_entities_insert_001", "endpoint": "entities+insert", "description": "data must contain field values matching collection schema data types", "assertion": "data field types match collection schema", "type": "type_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_type_entities_upsert_001", "endpoint": "entities+upsert", "description": "Primary key field must be specified in data for upsert", "assertion": "data contains primary key field", "type": "type_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_range_entities_insert_001", "endpoint": "entities+insert", "description": "Max 100 entities per single insert call via REST API", "assertion": "len(data) <= 100", "type": "range_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_range_entities_search_001", "endpoint": "entities+search", "description": "vector dimensions in data must match collection vector dimension", "assertion": "vector dimension == collection dimension", "type": "range_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_collections_drop_001", "endpoint": "collections+drop", "description": "Drop is irreversible; all data in the collection is permanently deleted", "assertion": "drop is irreversible AND all data is permanently deleted", "type": "state_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "source_status": "reachable"}
