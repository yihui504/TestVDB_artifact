=== 候选缺陷 milvus_039 ===
[vendor=milvus version=3.0.0 defect_type=type_coercion endpoint=entities+upsert]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] REST upsert string PK '100' -> http=200, code=0
- [c1_q] query id=100 after string-PK upsert -> http=200, code=0, data: id=100 vector=[0.9,0.9,0.9,0.9]
- [c1_grpc] gRPC upsert string PK -> DataNotMatchException code=1, message: id field should be int64, got str

执行日志全文（output_milvus_039.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_upsert_pk", "dbName": "default"}
=== RESP 1 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_upsert_pk", "dimension": 4}
=== RESP 2 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_upsert_pk", "data": [{"id": 100, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 3 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[100]}}

=== REQ 4 ===
POST http://localhost:19530/v2/vectordb/entities/upsert
payload: {"collectionName": "test_upsert_pk", "data": [{"id": "100", "vector": [0.9, 0.9, 0.9, 0.9]}]}
=== RESP 4 ===
status: 200
body: {"code":0,"cost":0,"data":{"upsertCount":1,"upsertIds":[100]}}

=== REQ 5 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_upsert_pk", "filter": "id==100", "outputFields": ["id", "vector"]}
=== RESP 5 ===
status: 200
body: {"code":0,"cost":0,"data":[{"id":100,"vector":[0.9,0.9,0.9,0.9]}]}


=== REQ 6 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_upsert_pk", "dbName": "default"}
=== RESP 6 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 7 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_upsert_pk", "dimension": 4}
=== RESP 7 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 8 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_upsert_pk", "data": [{"id": 100, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 8 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[100]}}

=== REQ 9 ===
POST http://localhost:19530/v2/vectordb/entities/upsert
payload: {"collectionName": "test_upsert_pk", "data": [{"id": "100", "vector": [0.9, 0.9, 0.9, 0.9]}]}
=== RESP 9 ===
status: 200
body: {"code":0,"cost":0,"data":{"upsertCount":1,"upsertIds":[100]}}

=== REQ 10 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_upsert_pk", "filter": "id==100", "outputFields": ["id", "vector"]}
=== RESP 10 ===
status: 200
body: {"code":0,"cost":0,"data":[{"id":100,"vector":[0.9,0.9,0.9,0.9]}]}




--- 契约依据（expected，来自该版本 API 契约） ---
[契约中无 endpoint=entities+upsert 的约束条目]

相关契约段（关键词定位 4 条）：
{"endpoint": "collection+create", "kind": "state_constraints", "description": "Primary key constraint", "assertion": "Exactly one primary field per collection with type Int64 or VarChar", "source_url": "https://milvus.io/docs/schema.md", "confidence": 0.95}
{"endpoint": "collections+fields+add", "kind": "type_constraints", "description": "INT64 scalar data type", "assertion": "dataType == Int64", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}
{"endpoint": "collection+create", "kind": "type_constraints", "description": "Valid dataType value: INT64", "assertion": "dataType == 'INT64'", "source_url": "https://milvus.io/docs/schema.md", "confidence": 0.95}
{"endpoint": "collections+create", "kind": "assertion", "description": "Primary key must be Int64 or VarChar", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}

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
