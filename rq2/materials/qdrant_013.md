=== 候选缺陷 qdrant_013 ===
[vendor=qdrant version=1.18.2 defect_type=param_validation endpoint=collections+{collection_name}+points]

--- 观察到的行为（observed） ---

执行日志全文（output_qdrant_013.log）：
=== REQ 1 ===
DELETE http://localhost:6333/collections/test_qnull
=== RESP 1 ===
status: 200
body: {"result":false,"status":"ok","time":0.000057056}

=== REQ 2 ===
PUT http://localhost:6333/collections/test_qnull
payload: {"vectors": {"size": 4, "distance": "Cosine"}}
=== RESP 2 ===
status: 200
body: {"result":true,"status":"ok","time":0.312722759}

=== REQ 3 ===
PUT http://localhost:6333/collections/test_qnull/points
payload: {"points": [{"id": 10, "vector": [0.5, 0.5, 0.5, 0.5]}, {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 5, "vector": [0.3, 0.3, 0.3, 0.3]}]}
=== RESP 3 ===
status: 200
body: {"result":{"operation_id":1,"status":"acknowledged"},"status":"ok","time":0.000351114}

=== REQ 4 ===
POST http://localhost:6333/collections/test_qnull/points/query
payload: {"query": null, "limit": 5}
=== RESP 4 ===
status: 200
body: {"result":{"points":[{"id":1,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0},{"id":10,"version":0,"score":1.0}]},"status":"ok","time":0.000267233}

=== REQ 5 ===
DELETE http://localhost:6333/collections/test_qnull
=== RESP 5 ===
status: 200
body: {"result":false,"status":"ok","time":0.000062432}

=== REQ 6 ===
PUT http://localhost:6333/collections/test_qnull
payload: {"vectors": {"size": 4, "distance": "Cosine"}}
=== RESP 6 ===
status: 200
body: {"result":true,"status":"ok","time":0.435276999}

=== REQ 7 ===
PUT http://localhost:6333/collections/test_qnull/points
payload: {"points": [{"id": 10, "vector": [0.5, 0.5, 0.5, 0.5]}, {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 5, "vector": [0.3, 0.3, 0.3, 0.3]}]}
=== RESP 7 ===
status: 200
body: {"result":{"operation_id":1,"status":"acknowledged"},"status":"ok","time":0.000135858}

=== REQ 8 ===
POST http://localhost:6333/collections/test_qnull/points/query
payload: {"query": null, "limit": 5}
=== RESP 8 ===
status: 200
body: {"result":{"points":[{"id":1,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0},{"id":10,"version":0,"score":1.0}]},"status":"ok","time":0.000260289}



--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（36 条，来自 qdrant 1.18.2 契约，endpoint=collections+{collection_name}+points）：
{"constraint_id": "qdrant_type_create_collection_001", "endpoint": "collections+{collection_name}", "type": "type_constraint", "description": "collection_name is string", "assertion": "collection_name type is string", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_type_update_collection_002", "endpoint": "collections+{collection_name}", "type": "type_constraint", "description": "All update fields are optional; at least one must be provided", "assertion": "At least one update field must be provided.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "type": "type_constraint", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"constraint_id": "qdrant_type_overwrite_payload_004", "endpoint": "collections+{collection_name}+points+payload", "type": "type_constraint", "description": "Overwrite replaces entire payload, not merged", "assertion": "PUT payload replaces the entire payload; it does not merge.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 0.9}
{"constraint_id": "qdrant_range_create_collection_001", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "shard_number minimum=1", "assertion": "shard_number >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_002", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "replication_factor minimum=1", "assertion": "replication_factor >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_003", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "write_consistency_factor minimum=1", "assertion": "write_consistency_factor >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_004", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "timeout minimum=1", "assertion": "timeout >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_scroll_points_005", "endpoint": "collections+{collection_name}+points+scroll", "type": "range_constraint", "description": "limit default=10 (adjustable)", "assertion": "limit default=10", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_range_search_points_006", "endpoint": "collections+{collection_name}+points+search", "type": "range_constraint", "description": "hnsw_ef applicable when exact=false", "assertion": "hnsw_ef parameter is applicable only when exact=false.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "confidence": 0.9}
{"constraint_id": "qdrant_range_search_groups_007", "endpoint": "collections+{collection_name}+points+search+groups", "type": "range_constraint", "description": "group_size >= 1; limit >= 1", "assertion": "group_size >= 1 AND limit >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_range_query_points_008", "endpoint": "collections+{collection_name}+points+query", "type": "range_constraint", "description": "limit default=10", "assertion": "limit default=10 for query endpoint.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_range_recommend_009", "endpoint": "collections+{collection_name}+points+recommend", "type": "range_constraint", "description": "strategy must be one of: average_vector, best_score, sum_scores", "assertion": "strategy IN (average_vector, best_score, sum_scores)", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_create_collection_001", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Collection creation accepts configuration literally; a collection created without vector config is valid for payload-only use, vector errors surface on first vector operation", "assertion": "After 200 response the collection exists with the configuration as submitted; collections without vector config support payload-only operations (vector insert returns an error at use time)", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_state_update_collection_002", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Blocking operation - waits for current optimizations to complete", "assertion": "Update blocks until current optimizations complete.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 0.9}
{"constraint_id": "qdrant_state_delete_collection_003", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Destructive operation - permanently deletes collection and all its data", "assertion": "Collection deletion permanently removes the collection and all its data.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_upsert_points_004", "endpoint": "collections+{collection_name}+points", "type": "state_constraint", "description": "Atomic batch upsert - all points inserted or none", "assertion": "Batch upsert is atomic: all points are inserted or none.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"constraint_id": "qdrant_state_delete_points_005", "endpoint": "collections+{collection_name}+points+delete", "type": "state_constraint", "description": "Deletion is atomic for the matched set", "assertion": "Point deletion is atomic for the matched set.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_set_payload_006", "endpoint": "collections+{collection_name}+points+payload", "type": "state_constraint", "description": "Atomic - all matched points get the payload", "assertion": "Payload set is atomic: all matched points receive the payload.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload", "confidence": 1.0}
{"constraint_id": "qdrant_state_batch_update_007", "endpoint": "collections+{collection_name}+points+batch", "type": "state_constraint", "description": "Batch operations are NOT promised to be atomic; on error, operations may be none, partially, or fully applied; writes are idempotent and clients should retry", "assertion": "Batch update operations may be partially applied on failure; atomicity is not guaranteed; clients must retry to reach a consistent state", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_count_points_008", "endpoint": "collections+{collection_name}+points+count", "type": "state_constraint", "description": "exact=true performs full scan; exact=false uses segment statistics", "assertion": "exact=true performs a full scan; exact=false uses segment statistics.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_search_points_009", "endpoint": "collections+{collection_name}+points+search", "type": "state_constraint", "description": "If exact=true, performs brute-force search (slow but accurate); if exact=false, uses HNSW for approximate search", "assertion": "When exact=true, search uses brute-force; when exact=false, search uses HNSW.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "confidence": 1.0}
{"constraint_id": "qdrant_state_query_points_010", "endpoint": "collections+{collection_name}+points+query", "type": "state_constraint", "description": "prefetch queries execute first, then final query runs on combined results", "assertion": "prefetch queries execute first, then the final query runs on combined results.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_001", "endpoint": "collections+{collection_name}", "description": "200 on success; 4XX on invalid params or collection already exists", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_002", "endpoint": "collections+{collection_name}", "description": "200 on success; 404 if collection not found", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_003", "endpoint": "collections+{collection_name}", "description": "200 with collection info; 404 if not found", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_005", "endpoint": "collections+{collection_name}+points", "description": "200 on success; 4XX on validation error", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_006", "endpoint": "collections+{collection_name}+points", "description": "200 with matching points (missing IDs are silently omitted)", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_007", "endpoint": "collections+{collection_name}+points+delete", "description": "200 on success; 400 if neither points nor filter provided", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_008", "endpoint": "collections+{collection_name}+points+search", "description": "200 with ranked results descending by score; 4XX on invalid params", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_009", "endpoint": "collections+{collection_name}+points+scroll", "description": "200 with points list and next_page_offset for pagination", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_010", "endpoint": "collections+{collection_name}+points+count", "description": "200 with count result", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_011", "endpoint": "collections+{collection_name}+points+query", "description": "200 with result points; supports multi-stage query pipeline via prefetch", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_012", "endpoint": "collections+{collection_name}+points+recommend", "description": "200 with ranked results", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_016", "endpoint": "collections+{collection_name}+points+payload", "description": "200 on success; 400 if no points or filter specified", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_017", "endpoint": "collections", "description": "200 with list of collections", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}

相关契约段（关键词定位 4 条）：
{"endpoint": "collections+{collection_name}+points", "kind": "state_constraints", "description": "Atomic batch upsert - all points inserted or none", "assertion": "Batch upsert is atomic: all points are inserted or none.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"endpoint": "collections+{collection_name}+points+payload", "kind": "state_constraints", "description": "Atomic - all matched points get the payload", "assertion": "Payload set is atomic: all matched points receive the payload.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload", "confidence": 1.0}
{"endpoint": "collections+{collection_name}+points+search", "kind": "range_constraints", "description": "hnsw_ef applicable when exact=false", "assertion": "hnsw_ef parameter is applicable only when exact=false.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "confidence": 0.9}
{"endpoint": "collections+{collection_name}", "kind": "state_constraints", "description": "Destructive operation - permanently deletes collection and all its data", "assertion": "Collection deletion permanently removes the collection and all its data.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}

API 模板：endpoint=collections+{collection_name}+points doc_quote='Get points by IDs' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "qdrant_range_scroll_points_005", "endpoint": "collections+{collection_name}+points+scroll", "description": "limit default=10 (adjustable)", "assertion": "limit default=10", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_search_groups_007", "endpoint": "collections+{collection_name}+points+search+groups", "description": "group_size >= 1; limit >= 1", "assertion": "group_size >= 1 AND limit >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_query_points_008", "endpoint": "collections+{collection_name}+points+query", "description": "limit default=10", "assertion": "limit default=10 for query endpoint.", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_query_points_010", "endpoint": "collections+{collection_name}+points+query", "description": "prefetch queries execute first, then final query runs on combined results", "assertion": "prefetch queries execute first, then the final query runs on combined results.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_create_index_011", "endpoint": "collections+{collection_name}+index", "description": "Index creation is async; query optimization applies after index is built", "assertion": "Index creation is asynchronous; query optimization applies after the index is built.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_011", "endpoint": "collections+{collection_name}+points+query", "description": "200 with result points; supports multi-stage query pipeline via prefetch", "category": "behavioral", "expected_behavior": "Returns 200 with array of scored points.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "doc_version": "1.18.x", "source_verified": true}
{"contract_id": "qdrant_behavioral_create_query_visibility", "description": "Create collection then query it - collection should be visible immediately", "scenario": "Create a collection via PUT /collections/{name}, then get it via GET /collections/{name}. The collection should be fully initialized and visible immediately after 200 response.", "expected_behavior": "After a successful 200 response from create collection, a subsequent GET collection info request returns 200 with the collection configuration.", "related_endpoints": ["collections+{collection_name}", "collections+{collection_name}"], "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection"}
{"constraint_id": "qdrant_range_recommend_009", "endpoint": "collections+{collection_name}+points+recommend", "description": "strategy must be one of: average_vector, best_score, sum_scores", "assertion": "strategy IN (average_vector, best_score, sum_scores)", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_008", "endpoint": "collections+{collection_name}+points+search", "description": "200 with ranked results descending by score; 4XX on invalid params", "category": "behavioral", "expected_behavior": "Returns 200 with array of scored points (descending by score); returns 4XX on invalid params.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_012", "endpoint": "collections+{collection_name}+points+recommend", "description": "200 with ranked results", "category": "behavioral", "expected_behavior": "Returns 200 with array of scored points.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_create_collection_001", "endpoint": "collections+{collection_name}", "description": "collection_name is string", "assertion": "collection_name type is string", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_update_collection_002", "endpoint": "collections+{collection_name}", "description": "All update fields are optional; at least one must be provided", "assertion": "At least one update field must be provided.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_overwrite_payload_004", "endpoint": "collections+{collection_name}+points+payload", "description": "Overwrite replaces entire payload, not merged", "assertion": "PUT payload replaces the entire payload; it does not merge.", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
