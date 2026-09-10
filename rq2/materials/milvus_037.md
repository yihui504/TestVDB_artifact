=== 候选缺陷 milvus_037 ===
[vendor=milvus version=3.0.0 defect_type=type_coercion endpoint=entities+insert]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] REST insert string '123' into INT64 field -> http=200, code=0
- [c1_q] query int64_f -> http=200, code=101, message: collection not loaded
- [c2] REST insert int 123 into VarChar field -> http=200, code=0
- [c2_q] query varchar_f -> http=200, code=101, message: collection not loaded
- [c3] REST insert string 'true' into BOOL field -> http=200, code=0
- [c3_q] query bool_f -> http=200, code=101, message: collection not loaded

执行日志全文（output_milvus_037.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_coerce", "data": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "int64_f": "123"}]}
=== RESP 1 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[1]}}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_coerce", "filter": "id==1", "outputFields": ["int64_f"]}
=== RESP 2 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359099812566979]"}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_coerce", "data": [{"id": 2, "vector": [0.1, 0.2, 0.3, 0.4], "varchar_f": 123}]}
=== RESP 3 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[2]}}

=== REQ 4 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_coerce", "filter": "id==2", "outputFields": ["varchar_f"]}
=== RESP 4 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359099812566979]"}

=== REQ 5 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_coerce", "data": [{"id": 3, "vector": [0.1, 0.2, 0.3, 0.4], "bool_f": "true"}]}
=== RESP 5 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[3]}}

=== REQ 6 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_coerce", "filter": "id==3", "outputFields": ["bool_f"]}
=== RESP 6 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359099812566979]"}

=== REQ 7 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_coerce", "data": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "int64_f": "123"}]}
=== RESP 7 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[1]}}

=== REQ 8 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_coerce", "filter": "id==1", "outputFields": ["int64_f"]}
=== RESP 8 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359869997930433]"}

=== REQ 9 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_coerce", "data": [{"id": 2, "vector": [0.1, 0.2, 0.3, 0.4], "varchar_f": 123}]}
=== RESP 9 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[2]}}

=== REQ 10 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_coerce", "filter": "id==2", "outputFields": ["varchar_f"]}
=== RESP 10 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359869997930433]"}

=== REQ 11 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_coerce", "data": [{"id": 3, "vector": [0.1, 0.2, 0.3, 0.4], "bool_f": "true"}]}
=== RESP 11 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[3]}}

=== REQ 12 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_coerce", "filter": "id==3", "outputFields": ["bool_f"]}
=== RESP 12 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359869997930433]"}



--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（3 条，来自 milvus 3.0.0 契约，endpoint=entities+insert）：
{"constraint_id": "milvus_state_insert_collection_001", "endpoint": "entities+insert", "type": "state_constraint", "description": "Insert requires existing collection", "assertion": "collection MUST exist before insert", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}
{"assertion_id": "milvus_behavioral_insert_then_get_001", "endpoint": "entities+insert", "description": "Inserted entities should be retrievable", "source_url": "https://milvus.io/docs/insert-update.md", "confidence": 1.0}
{"assertion_id": "milvus_assert_insert_success_001", "endpoint": "entities+insert", "description": "Inserting valid data succeeds", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}

相关契约段（关键词定位 4 条）：
{"endpoint": "collection+create", "kind": "state_constraints", "description": "Primary key constraint", "assertion": "Exactly one primary field per collection with type Int64 or VarChar", "source_url": "https://milvus.io/docs/schema.md", "confidence": 0.95}
{"endpoint": "collections+fields+add", "kind": "type_constraints", "description": "INT64 scalar data type", "assertion": "dataType == Int64", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}
{"endpoint": "collections+fields+add", "kind": "type_constraints", "description": "BOOL scalar data type", "assertion": "dataType == Bool", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}
{"endpoint": "collections+fields+add", "kind": "type_constraints", "description": "VARCHAR scalar data type", "assertion": "dataType == VARCHAR", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}

API 模板：endpoint=entities+insert doc_quote='Insert entities' source=None

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
