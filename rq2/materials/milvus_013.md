=== 候选缺陷 milvus_013 ===
[vendor=milvus version=2.6.16 defect_type=param_validation endpoint=collections+list]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] Request-Timeout=3.5 (float) header -> http=200, code=0
- [c2] Request-Timeout=abc (string) header -> http=200, code=0
- [c3] control: Request-Timeout=10 (integer) -> http=200, code=0

执行日志全文（output_milvus_013.log）：
=== REQ 1 ===
POST http://localhost:19530/v2/vectordb/collections/list
headers: {"Request-Timeout": "3.5"}
payload: {}
=== RESP 1 ===
status: 200
body: {"code":0,"data":[]}

=== REQ 2 ===
POST http://localhost:19530/v2/vectordb/collections/list
headers: {"Request-Timeout": "abc"}
payload: {}
=== RESP 2 ===
status: 200
body: {"code":0,"data":[]}

=== REQ 3 ===
POST http://localhost:19530/v2/vectordb/collections/list
headers: {"Request-Timeout": "10"}
payload: {}
=== RESP 3 ===
status: 200
body: {"code":0,"data":[]}



--- 契约依据（expected，来自该版本 API 契约） ---
[契约中无 endpoint=collections+list 的约束条目]

相关契约段（关键词定位 4 条）：
{"endpoint": "collections+drop", "kind": "type_constraints", "description": "collectionName must be a non-empty string", "assertion": "collectionName is non-empty string", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Drop.md", "confidence": 1.0}
{"endpoint": "collections+load", "kind": "type_constraints", "description": "collectionName must be a non-empty string for load", "assertion": "collectionName is non-empty string", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Load.md", "confidence": 1.0}
{"endpoint": "collections+rename", "kind": "type_constraints", "description": "collectionName and newCollectionName must be non-empty strings", "assertion": "collectionName is non-empty string AND newCollectionName is non-empty string", "source_url": "https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20(v2)/Rename.md", "confidence": 1.0}
{"endpoint": "partitions+create", "kind": "type_constraints", "description": "partitionName must be a non-empty string", "assertion": "partitionName is non-empty string", "source_url": "https://github.com/milvus-io/milvus/blob/v2.6.17/internal/distributed/proxy/httpserver/constant.go", "confidence": 1.0}


--- 补充契约依据（文档考古补全，同版本契约） ---
{"constraint_id": "milvus_type_request_timeout_001", "endpoint": "entities+query", "description": "Request-Timeout header must be an integer", "assertion": "header Request-Timeout matches ^[0-9]+$ (non-integer rejected)", "type": "state_constraint", "evidence_tier": "explicit", "source_url": "https://milvus.io/api-reference/restful/v2.3.x/v2/Vector%20(v2)/Query.md", "_provenance": "doc-archaeology 2026-08-20: issue #49890 (2026-05-18) — API reference documents Request-Timeout as integer type; float 3.5 silently truncated, string \"abc\" silently ignored."}

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
