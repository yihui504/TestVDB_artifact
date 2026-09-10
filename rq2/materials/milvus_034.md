=== 候选缺陷 milvus_034 ===
[vendor=milvus version=3.0.0 defect_type=semantics endpoint=entities+upsert]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] REST upsert bare string into JSON field -> http=200, code=0
- [c1_q] query meta after REST upsert -> http=200, code=101, message: collection not loaded
- [c1_grpc_get] gRPC get id=0 -> code=101, message: collection not loaded
- [c1b] gRPC upsert plain string -> DataNotMatchException code=1, message: Invalid JSON string

执行日志全文（output_milvus_034.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_json", "dbName": "default"}
=== RESP 1 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_json", "schema": {"autoId": false, "enableDynamicField": false, "fields": [{"fieldName": "id", "dataType": "Int64", "isPrimary": true}, {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}}, {"fieldName": "meta", "dataType": "JSON"}]}}
=== RESP 2 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/indexes/create
payload: {"collectionName": "test_json", "indexParams": [{"fieldName": "vector", "metricType": "COSINE", "indexType": "AUTOINDEX"}]}
=== RESP 3 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 4 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_json", "data": [{"id": 0, "vector": [0.1, 0.2, 0.3, 0.4], "meta": {"important": "data"}}]}
=== RESP 4 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[0]}}

=== REQ 5 ===
POST http://localhost:19530/v2/vectordb/entities/upsert
payload: {"collectionName": "test_json", "data": [{"id": 0, "vector": [0.9, 0.9, 0.9, 0.9], "meta": "invalid_json"}]}
=== RESP 5 ===
status: 200
body: {"code":0,"cost":0,"data":{"upsertCount":1,"upsertIds":[0]}}

=== REQ 6 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_json", "filter": "id in [0,1]", "outputFields": ["meta"]}
=== RESP 6 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359099811365880]"}

=== REQ 7 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_json", "filter": "id==1", "outputFields": ["meta"]}
=== RESP 7 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359099811365880]"}

=== REQ 8 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_json", "dbName": "default"}
=== RESP 8 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 9 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_json", "schema": {"autoId": false, "enableDynamicField": false, "fields": [{"fieldName": "id", "dataType": "Int64", "isPrimary": true}, {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}}, {"fieldName": "meta", "dataType": "JSON"}]}}
=== RESP 9 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 10 ===
POST http://localhost:19530/v2/vectordb/indexes/create
payload: {"collectionName": "test_json", "indexParams": [{"fieldName": "vector", "metricType": "COSINE", "indexType": "AUTOINDEX"}]}
=== RESP 10 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 11 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_json", "data": [{"id": 0, "vector": [0.1, 0.2, 0.3, 0.4], "meta": {"important": "data"}}]}
=== RESP 11 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":1,"insertIds":[0]}}

=== REQ 12 ===
POST http://localhost:19530/v2/vectordb/entities/upsert
payload: {"collectionName": "test_json", "data": [{"id": 0, "vector": [0.9, 0.9, 0.9, 0.9], "meta": "invalid_json"}]}
=== RESP 12 ===
status: 200
body: {"code":0,"cost":0,"data":{"upsertCount":1,"upsertIds":[0]}}

=== REQ 13 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_json", "filter": "id in [0,1]", "outputFields": ["meta"]}
=== RESP 13 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359869996729341]"}

=== REQ 14 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_json", "filter": "id==1", "outputFields": ["meta"]}
=== RESP 14 ===
status: 200
body: {"code":101,"message":"failed to query: collection not loaded[collection=468359869996729341]"}



--- 契约依据（expected，来自该版本 API 契约） ---
[契约中无 endpoint=entities+upsert 的约束条目]

相关契约段（关键词定位 4 条）：
{"endpoint": "collection+create", "kind": "type_constraints", "description": "Valid dataType value: JSON", "assertion": "dataType == 'JSON'", "source_url": "https://milvus.io/docs/schema.md", "confidence": 0.95}
{"endpoint": "collections+fields+add", "kind": "type_constraints", "description": "JSON scalar data type", "assertion": "dataType == JSON", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}
{"endpoint": "collection+create", "kind": "type_constraints", "description": "Supported data type: JSON", "assertion": "dataType == 'JSON'", "source_url": "https://milvus.io/docs/schema.md", "confidence": 0.95}
{"endpoint": "entities+insert", "kind": "assertion", "description": "Inserting valid data succeeds", "source_url": "https://milvus.io/docs/schema.md", "confidence": 1.0}

API 模板：endpoint=entities+get doc_quote='Get entities' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "milvus_state_entities_insert_001", "endpoint": "entities+insert", "description": "Collection must exist and be loaded; if autoID is disabled, primary key must be provided", "assertion": "collection exists AND is loaded AND (autoID OR primary key provided)", "type": "state_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
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
