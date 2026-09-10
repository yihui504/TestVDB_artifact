=== 候选缺陷 milvus_019 ===
[vendor=milvus version=2.6.16 defect_type=behavior endpoint=collections+get_stats]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] get_stats after insert+load -> http=200, code=0, rowCount=0
- [c1_q] query after insert+load -> http=200, code=0, returned 5 rows (id 0-4)

执行日志全文（output_milvus_019.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_rowcount", "dbName": "default"}
=== RESP 1 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_rowcount", "dimension": 4}
=== RESP 2 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_rowcount", "data": [{"id": 0, "value": 0, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 1, "value": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 2, "value": 2, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 3, "value": 3, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 4, "value": 4, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 3 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":5,"insertIds":[0,1,2,3,4]}}

=== REQ 4 ===
POST http://localhost:19530/v2/vectordb/collections/load
payload: {"collectionName": "test_rowcount", "dbName": "default"}
=== RESP 4 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 5 ===
POST http://localhost:19530/v2/vectordb/collections/get_stats
payload: {"collectionName": "test_rowcount"}
=== RESP 5 ===
status: 200
body: {"code":0,"data":{"rowCount":0}}

=== REQ 6 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_rowcount", "filter": "id>=0", "outputFields": ["id"]}
=== RESP 6 ===
status: 200
body: {"code":0,"cost":0,"data":[{"id":0},{"id":1},{"id":2},{"id":3},{"id":4}]}


=== REQ 7 ===
POST http://localhost:19530/v2/vectordb/collections/drop
payload: {"collectionName": "test_rowcount", "dbName": "default"}
=== RESP 7 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 8 ===
POST http://localhost:19530/v2/vectordb/collections/create
payload: {"collectionName": "test_rowcount", "dimension": 4}
=== RESP 8 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 9 ===
POST http://localhost:19530/v2/vectordb/entities/insert
payload: {"collectionName": "test_rowcount", "data": [{"id": 0, "value": 0, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 1, "value": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 2, "value": 2, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 3, "value": 3, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 4, "value": 4, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 9 ===
status: 200
body: {"code":0,"cost":0,"data":{"insertCount":5,"insertIds":[0,1,2,3,4]}}

=== REQ 10 ===
POST http://localhost:19530/v2/vectordb/collections/load
payload: {"collectionName": "test_rowcount", "dbName": "default"}
=== RESP 10 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 11 ===
POST http://localhost:19530/v2/vectordb/collections/get_stats
payload: {"collectionName": "test_rowcount"}
=== RESP 11 ===
status: 200
body: {"code":0,"data":{"rowCount":0}}

=== REQ 12 ===
POST http://localhost:19530/v2/vectordb/entities/query
payload: {"collectionName": "test_rowcount", "filter": "id>=0", "outputFields": ["id"]}
=== RESP 12 ===
status: 200
body: {"code":0,"cost":0,"data":[{"id":0},{"id":1},{"id":2},{"id":3},{"id":4}]}




--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（1 条，来自 milvus 2.6.16 契约，endpoint=collections+get_stats）：
{"assertion_id": "milvus_behavioral_collections_get_stats_001", "endpoint": "collections+get_stats", "description": "Get stats returns row count and statistics", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}

API 模板：endpoint=collections+load doc_quote='200 on success; 404 if collection not found; 400 if no index exists on collection' source=None


--- 维护者态度参考（developer_cognition，vendor=milvus） ---
以下为该 vendor 维护者在历史 issue 中对同类现象的明确 by-design 表态（供判定参考；与本案是否相关由你判断）：
- [相关 issues: [50192]] Concurrent rename+create idempotent semantics: rename(dst) racing with create(dst) both returning success is tolerated—rename to an existing-name target is treated as idempotent no-op when parameters match（维护者原话: "sounds like a by designed. Milvus returns success if creating a collection with the same name and parameters."）
- [相关 issues: [50193]] get_stats rowCount reflects flushed data only: rowCount=0 after insert before flush is expected (query returns full rows; stats lag by design)（维护者原话: "This is by design. The entities number in collection stats only shows the data that flushed. Please retry with flush() after insert()."）
- [相关 issues: [50319]] REST v2 quick-create mode semantics: creating via quick/fast mode (dimension-only) auto-loads and does not enforce full schema/load-state checks; search on such collections succeeding is expected（维护者原话: "The behavior described here appears to come from REST v2 quick/fast collection creation mode, not from search/query bypassing the collection load-stat"）
- [相关 issues: [50351]] REST v2 create ignores unconsumed top-level fields: params not consumed by quick-create (e.g. top-level shardsNum) are silently ignored rather than rejected; consumed via params.shardsNum（维护者原话: "I think this is by design. The payload in this issue uses top-level shardsNum, but this field is not consumed by the REST v2 create API. shardsNum is "）

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
