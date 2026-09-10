=== 候选缺陷 qdrant_007 ===
[vendor=qdrant version=1.18.2 defect_type=behavior endpoint=collections+{collection_name}+points+batch]

--- 观察到的行为（observed） ---

执行日志全文（output_qdrant_007.log）：
=== REQ 1 ===
DELETE http://localhost:6333/collections/test_batch2
=== RESP 1 ===
status: 200
body: {"result":false,"status":"ok","time":0.001802436}

=== REQ 2 ===
PUT http://localhost:6333/collections/test_batch2
payload: {"vectors": {"size": 4, "distance": "Cosine"}}
=== RESP 2 ===
status: 200
body: {"result":true,"status":"ok","time":0.313413442}

=== REQ 3 ===
PUT http://localhost:6333/collections/test_batch2/points?wait=true
payload: {"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8]}, {"id": 3, "vector": [0.9, 0.9, 0.9, 0.9]}]}
=== RESP 3 ===
status: 200
body: {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.00865381}

=== REQ 4 ===
POST http://localhost:6333/collections/test_batch2/points/count
payload: {"exact": true}
=== RESP 4 ===
status: 200
body: {"result":{"count":3},"status":"ok","time":0.001314561}

=== REQ 5 ===
POST http://localhost:6333/collections/test_batch2/points/batch
payload: {"operations": [{"upsert": {"points": [{"id": 4, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 5, "vector": [0.5, 0.6, 0.7, 0.8]}, {"id": 6, "vector": [0.1, 0.2, 0.3]}]}}]}
=== RESP 5 ===
status: 400
body: {"status":{"error":"Wrong input: Vector dimension error: expected dim: 4, got 3"},"time":0.000021096}

=== REQ 6 ===
POST http://localhost:6333/collections/test_batch2/points/count
payload: {"exact": true}
=== RESP 6 ===
status: 200
body: {"result":{"count":3},"status":"ok","time":0.000092489}

=== REQ 7 ===
DELETE http://localhost:6333/collections/test_batch2
=== RESP 7 ===
status: 200
body: {"result":false,"status":"ok","time":0.000070651}

=== REQ 8 ===
PUT http://localhost:6333/collections/test_batch2
payload: {"vectors": {"size": 4, "distance": "Cosine"}}
=== RESP 8 ===
status: 200
body: {"result":true,"status":"ok","time":0.289524464}

=== REQ 9 ===
PUT http://localhost:6333/collections/test_batch2/points?wait=true
payload: {"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8]}, {"id": 3, "vector": [0.9, 0.9, 0.9, 0.9]}]}
=== RESP 9 ===
status: 200
body: {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.003470479}

=== REQ 10 ===
POST http://localhost:6333/collections/test_batch2/points/count
payload: {"exact": true}
=== RESP 10 ===
status: 200
body: {"result":{"count":3},"status":"ok","time":0.00014049}

=== REQ 11 ===
POST http://localhost:6333/collections/test_batch2/points/batch
payload: {"operations": [{"upsert": {"points": [{"id": 4, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 5, "vector": [0.5, 0.6, 0.7, 0.8]}, {"id": 6, "vector": [0.1, 0.2, 0.3]}]}}]}
=== RESP 11 ===
status: 400
body: {"status":{"error":"Wrong input: Vector dimension error: expected dim: 4, got 3"},"time":0.00001256}

=== REQ 12 ===
POST http://localhost:6333/collections/test_batch2/points/count
payload: {"exact": true}
=== RESP 12 ===
status: 200
body: {"result":{"count":3},"status":"ok","time":0.000164095}



--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（20 条，来自 qdrant 1.18.2 契约，endpoint=collections+{collection_name}+points+batch）：
{"constraint_id": "qdrant_type_create_collection_001", "endpoint": "collections+{collection_name}", "type": "type_constraint", "description": "collection_name is string", "assertion": "collection_name type is string", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_type_update_collection_002", "endpoint": "collections+{collection_name}", "type": "type_constraint", "description": "All update fields are optional; at least one must be provided", "assertion": "At least one update field must be provided.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "type": "type_constraint", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_001", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "shard_number minimum=1", "assertion": "shard_number >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_002", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "replication_factor minimum=1", "assertion": "replication_factor >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_003", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "write_consistency_factor minimum=1", "assertion": "write_consistency_factor >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_004", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "timeout minimum=1", "assertion": "timeout >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_state_create_collection_001", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Collection creation accepts configuration literally; a collection created without vector config is valid for payload-only use, vector errors surface on first vector operation", "assertion": "After 200 response the collection exists with the configuration as submitted; collections without vector config support payload-only operations (vector insert returns an error at use time)", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_state_update_collection_002", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Blocking operation - waits for current optimizations to complete", "assertion": "Update blocks until current optimizations complete.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 0.9}
{"constraint_id": "qdrant_state_delete_collection_003", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Destructive operation - permanently deletes collection and all its data", "assertion": "Collection deletion permanently removes the collection and all its data.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_upsert_points_004", "endpoint": "collections+{collection_name}+points", "type": "state_constraint", "description": "Atomic batch upsert - all points inserted or none", "assertion": "Batch upsert is atomic: all points are inserted or none.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"constraint_id": "qdrant_state_delete_points_005", "endpoint": "collections+{collection_name}+points+delete", "type": "state_constraint", "description": "Deletion is atomic for the matched set", "assertion": "Point deletion is atomic for the matched set.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_batch_update_007", "endpoint": "collections+{collection_name}+points+batch", "type": "state_constraint", "description": "Batch operations are NOT promised to be atomic; on error, operations may be none, partially, or fully applied; writes are idempotent and clients should retry", "assertion": "Batch update operations may be partially applied on failure; atomicity is not guaranteed; clients must retry to reach a consistent state", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_001", "endpoint": "collections+{collection_name}", "description": "200 on success; 4XX on invalid params or collection already exists", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_002", "endpoint": "collections+{collection_name}", "description": "200 on success; 404 if collection not found", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_003", "endpoint": "collections+{collection_name}", "description": "200 with collection info; 404 if not found", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_005", "endpoint": "collections+{collection_name}+points", "description": "200 on success; 4XX on validation error", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_006", "endpoint": "collections+{collection_name}+points", "description": "200 with matching points (missing IDs are silently omitted)", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_007", "endpoint": "collections+{collection_name}+points+delete", "description": "200 on success; 400 if neither points nor filter provided", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_017", "endpoint": "collections", "description": "200 with list of collections", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}

相关契约段（关键词定位 4 条）：
{"endpoint": "collections+{collection_name}+points", "kind": "state_constraints", "description": "Atomic batch upsert - all points inserted or none", "assertion": "Batch upsert is atomic: all points are inserted or none.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"endpoint": "collections+{collection_name}+points+batch", "kind": "state_constraints", "description": "All operations in batch are executed atomically", "assertion": "Batch update operations are executed atomically.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"endpoint": "collections+{collection_name}", "kind": "state_constraints", "description": "Atomic collection creation: after 200 response, collection is fully initialized and ready for operations", "assertion": "Atomic collection creation. After 200 response, collection is fully initialized and ready for operations.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"endpoint": "collections+{collection_name}+points+payload", "kind": "state_constraints", "description": "Atomic - all matched points get the payload", "assertion": "Payload set is atomic: all matched points receive the payload.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload", "confidence": 1.0}

API 模板：endpoint=collections+{collection_name}+points+batch doc_quote='Batch update points (mixed operations)' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "qdrant_state_count_points_008", "endpoint": "collections+{collection_name}+points+count", "description": "exact=true performs full scan; exact=false uses segment statistics", "assertion": "exact=true performs a full scan; exact=false uses segment statistics.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_010", "endpoint": "collections+{collection_name}+points+count", "description": "200 with count result", "category": "behavioral", "expected_behavior": "Returns 200 with object containing 'count' field (integer).", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "doc_version": "1.18.x", "source_verified": true}
{"contract_id": "qdrant_behavioral_upsert_count_consistency", "description": "Upsert points and count - count should reflect the exact number of upserted points", "scenario": "Upsert N points via PUT /collections/{name}/points, then count points via POST /collections/{name}/points/count with exact=true. The count should equal N.", "expected_behavior": "After upserting N points successfully, exact count returns N.", "related_endpoints": ["collections+{collection_name}+points", "collections+{collection_name}+points+count"], "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points"}
{"constraint_id": "qdrant_range_search_points_006", "endpoint": "collections+{collection_name}+points+search", "description": "hnsw_ef applicable when exact=false", "assertion": "hnsw_ef parameter is applicable only when exact=false.", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_search_points_009", "endpoint": "collections+{collection_name}+points+search", "description": "If exact=true, performs brute-force search (slow but accurate); if exact=false, uses HNSW for approximate search", "assertion": "When exact=true, search uses brute-force; when exact=false, search uses HNSW.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_create_collection_001", "endpoint": "collections+{collection_name}", "description": "Atomic collection creation: after 200 response, collection is fully initialized and ready for operations", "assertion": "Atomic collection creation. After 200 response, collection is fully initialized and ready for operations.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_batch_update_007", "endpoint": "collections+{collection_name}+points+batch", "description": "All operations in batch are executed atomically", "assertion": "Batch update operations are executed atomically.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_update_aliases_012", "endpoint": "collections+aliases", "description": "All alias operations in a single request are applied atomically", "assertion": "All alias operations in a single request are applied atomically.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_015", "endpoint": "collections+aliases", "description": "200 on success; 4XX on invalid operations", "category": "behavioral", "expected_behavior": "Returns 200 on success; returns 4XX on invalid alias operations.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type2_PoorDiagnostics", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_search_groups_007", "endpoint": "collections+{collection_name}+points+search+groups", "description": "group_size >= 1; limit >= 1", "assertion": "group_size >= 1 AND limit >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_upsert_points_004", "endpoint": "collections+{collection_name}+points", "description": "Atomic batch upsert - all points inserted or none", "assertion": "Batch upsert is atomic: all points are inserted or none.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_005", "endpoint": "collections+{collection_name}+points", "description": "200 on success; 4XX on validation error", "category": "behavioral", "expected_behavior": "Returns 200 on success; returns 4XX on validation error.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type1_IllegalSuccess", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_recommend_009", "endpoint": "collections+{collection_name}+points+recommend", "description": "strategy must be one of: average_vector, best_score, sum_scores", "assertion": "strategy IN (average_vector, best_score, sum_scores)", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
