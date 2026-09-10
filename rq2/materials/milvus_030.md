=== 候选缺陷 milvus_030 ===
[vendor=milvus version=2.6.17 defect_type=doc_mismatch endpoint=users+create]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] users/create with all-lowercase password 'abcdefgh' -> http=200, code=0
- [c2] control: users/create with complex password 'ValidP@ss1' -> http=200, code=0
- [c3] users/create with short password 'a' -> http=200, code=1100

执行日志全文（output_milvus_030.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/users/create
payload: {"userName": "testuser8char", "password": "abcdefgh"}
=== RESP 1 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/users/create
payload: {"userName": "testuservalid", "password": "ValidP@ss1"}
=== RESP 2 ===
status: 200
body: {"code":0,"data":{}}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/users/create
payload: {"userName": "testuser1ch", "password": "a"}
=== RESP 3 ===
status: 200
body: {"code":1100,"message":"invalid password length: invalid parameter[1 out of range 6 \u003c= value \u003c= 72]"}



--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（3 条，来自 milvus 2.6.17 契约，endpoint=users+create）：
{"constraint_id": "milvus_type_users_create_001", "endpoint": "users+create", "type": "type_constraint", "description": "userName must be a non-empty string", "assertion": "userName is non-empty string", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"constraint_id": "milvus_range_users_create_001", "endpoint": "users+create", "type": "range_constraint", "description": "password must be 8-64 characters", "assertion": "8 <= len(password) <= 64", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"assertion_id": "milvus_behavioral_users_create_001", "endpoint": "users+create", "description": "Create user returns 400 if password too weak or user already exists", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}

相关契约段（关键词定位 4 条）：
{"endpoint": "users+create", "kind": "range_constraints", "description": "password must be 8-64 characters", "assertion": "8 <= len(password) <= 64", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"endpoint": "entities+insert", "kind": "type_constraints", "description": "data must contain field values matching collection schema data types", "assertion": "data field types match collection schema", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}
{"endpoint": "collections+drop", "kind": "state_constraints", "description": "Drop is irreversible; all data in the collection is permanently deleted", "assertion": "drop is irreversible AND all data is permanently deleted", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "confidence": 1.0}
{"endpoint": "users+create", "kind": "assertion", "description": "Create user returns 400 if password too weak or user already exists", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}

API 模板：endpoint=users+create doc_quote='200 on success; 400 if user already exists or password too weak' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"assertion_id": "milvus_behavioral_collections_create_001", "endpoint": "collections+create", "description": "Create collection returns 200 on success", "category": "behavioral", "expected_behavior": "returns 200 with code: 0 and empty data object", "confidence": 1.0, "defect_type_if_violated": "Type1_IllegalSuccess", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "doc_version": "2.6.x"}
{"constraint_id": "milvus_type_entities_insert_001", "endpoint": "entities+insert", "description": "data must contain field values matching collection schema data types", "assertion": "data field types match collection schema", "type": "type_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_type_entities_search_001", "endpoint": "entities+search", "description": "data must be array of float arrays, annsField must be a vector field, limit must be positive integer", "assertion": "data is array[array[float]] AND annsField is a vector field AND limit > 0", "type": "type_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "source_status": "reachable"}
{"constraint_id": "milvus_type_entities_upsert_001", "endpoint": "entities+upsert", "description": "Primary key field must be specified in data for upsert", "assertion": "data contains primary key field", "type": "type_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_range_entities_insert_001", "endpoint": "entities+insert", "description": "Max 100 entities per single insert call via REST API", "assertion": "len(data) <= 100", "type": "range_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"constraint_id": "milvus_range_entities_search_001", "endpoint": "entities+search", "description": "vector dimensions in data must match collection vector dimension", "assertion": "vector dimension == collection dimension", "type": "range_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_collections_create_001", "endpoint": "collections+create", "description": "Collection creation is atomic; collection name must be unique within a database", "assertion": "collection creation is atomic AND collectionName is unique within dbName", "type": "state_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_collections_drop_001", "endpoint": "collections+drop", "description": "Drop is irreversible; all data in the collection is permanently deleted", "assertion": "drop is irreversible AND all data is permanently deleted", "type": "state_constraint", "confidence": 1.0, "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "source_status": "reachable"}
{"constraint_id": "milvus_state_databases_drop_001", "endpoint": "databases+drop", "description": "Cannot drop the default database; database must be empty (no collections)", "assertion": "dbName != '_default' AND database has no collections", "type": "state_constraint", "confidence": 1.0, "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "source_status": "reachable"}
{"assertion_id": "milvus_behavioral_collections_drop_001", "endpoint": "collections+drop", "description": "Drop collection returns 200 on success, 404 if not found", "category": "behavioral", "expected_behavior": "returns 200 with empty data on success; returns 404 with message 'collection not found' if collection does not exist", "confidence": 1.0, "defect_type_if_violated": "Type2_PoorDiagnostics", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "doc_version": "2.6.x"}
{"assertion_id": "milvus_behavioral_entities_insert_001", "endpoint": "entities+insert", "description": "Insert returns insert count and IDs on success", "category": "behavioral", "expected_behavior": "returns 200 with insertCount and insertIds in data", "confidence": 1.0, "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "doc_version": "2.6.17"}
{"assertion_id": "milvus_behavioral_collections_has_001", "endpoint": "collections+has", "description": "Has collection returns boolean indicating existence", "category": "behavioral", "expected_behavior": "returns 200 with data.has as boolean: true if exists, false if not", "confidence": 1.0, "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "doc_version": "2.6.17"}
{"assertion_id": "milvus_behavioral_collections_get_stats_001", "endpoint": "collections+get_stats", "description": "Get stats returns row count and statistics", "category": "behavioral", "expected_behavior": "returns 200 with data.rowCount showing the number of entities in the collection", "confidence": 1.0, "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "doc_version": "2.6.17"}
{"assertion_id": "milvus_behavioral_collections_create_002", "endpoint": "collections+create", "description": "Create collection returns 400 on invalid parameters or duplicate name", "category": "behavioral", "expected_behavior": "returns 400 with descriptive error message on invalid parameters or duplicate collection name", "confidence": 1.0, "defect_type_if_violated": "Type2_PoorDiagnostics", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Create.md", "doc_version": "2.6.x"}
