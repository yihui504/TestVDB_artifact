=== 候选缺陷 qdrant_016 ===
[vendor=qdrant version=1.18.2 defect_type=behavior endpoint=collections+{collection_name}+points+query]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] lookup referencing non-existent collection -> status=200, 3 results
- [c2] control: lookup referencing valid collection -> status=200

执行日志全文（output_qdrant_016.log）：
=== REQ 1 ===
DELETE http://localhost:6333/collections/test_lookup_source
=== RESP 1 ===
status: 200
body: {"result":false,"status":"ok","time":0.00276579}

=== REQ 2 ===
PUT http://localhost:6333/collections/test_lookup_source
payload: {"vectors": {"size": 4, "distance": "Cosine"}}
=== RESP 2 ===
status: 200
body: {"result":true,"status":"ok","time":0.321462371}

=== REQ 3 ===
PUT http://localhost:6333/collections/test_lookup_source/points?wait=true
payload: {"points": [{"id": 0, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"tag": "t0"}}, {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"tag": "t1"}}, {"id": 2, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"tag": "t2"}}, {"id": 3, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"tag": "t3"}}, {"id": 4, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"tag": "t4"}}]}
=== RESP 3 ===
status: 200
body: {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.010886418}

=== REQ 4 ===
DELETE http://localhost:6333/collections/test_lookup_target
=== RESP 4 ===
status: 200
body: {"result":false,"status":"ok","time":0.000072588}

=== REQ 5 ===
PUT http://localhost:6333/collections/test_lookup_target
payload: {"vectors": {"size": 4, "distance": "Cosine"}}
=== RESP 5 ===
status: 200
body: {"result":true,"status":"ok","time":0.296707869}

=== REQ 6 ===
PUT http://localhost:6333/collections/test_lookup_target/points?wait=true
payload: {"points": [{"id": 0, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 2, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 3, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 4, "vector": [0.1, 0.2, 0.3, 0.4]}]}
=== RESP 6 ===
status: 200
body: {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.005122177}

=== REQ 7 ===
POST http://localhost:6333/collections/test_lookup_source/points/query
payload: {"query": [0.3, 0.3, 0.3, 0.3], "limit": 3, "lookup_from": {"collection": "nonexistent_collection_xyz", "vector": "default"}}
=== RESP 7 ===
status: 200
body: {"result":{"points":[{"id":4,"version":1,"score":0.91287094},{"id":0,"version":1,"score":0.91287094},{"id":3,"version":1,"score":0.91287094}]},"status":"ok","time":0.004096501}

=== REQ 8 ===
POST http://localhost:6333/collections/test_lookup_source/points/query
payload: {"query": [0.3, 0.3, 0.3, 0.3], "limit": 3, "lookup_from": {"collection": "test_lookup_target", "vector": "default"}}
=== RESP 8 ===
status: 200
body: {"result":{"points":[{"id":4,"version":1,"score":0.91287094},{"id":0,"version":1,"score":0.91287094},{"id":3,"version":1,"score":0.91287094}]},"status":"ok","time":0.000313989}



--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（22 条，来自 qdrant 1.18.2 契约，endpoint=collections+{collection_name}+points+query）：
{"constraint_id": "qdrant_type_create_collection_001", "endpoint": "collections+{collection_name}", "type": "type_constraint", "description": "collection_name is string", "assertion": "collection_name type is string", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_type_update_collection_002", "endpoint": "collections+{collection_name}", "type": "type_constraint", "description": "All update fields are optional; at least one must be provided", "assertion": "At least one update field must be provided.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "type": "type_constraint", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_001", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "shard_number minimum=1", "assertion": "shard_number >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_002", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "replication_factor minimum=1", "assertion": "replication_factor >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_003", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "write_consistency_factor minimum=1", "assertion": "write_consistency_factor >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_create_collection_004", "endpoint": "collections+{collection_name}", "type": "range_constraint", "description": "timeout minimum=1", "assertion": "timeout >= 1", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_range_query_points_008", "endpoint": "collections+{collection_name}+points+query", "type": "range_constraint", "description": "limit default=10", "assertion": "limit default=10 for query endpoint.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_create_collection_001", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Collection creation accepts configuration literally; a collection created without vector config is valid for payload-only use, vector errors surface on first vector operation", "assertion": "After 200 response the collection exists with the configuration as submitted; collections without vector config support payload-only operations (vector insert returns an error at use time)", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"constraint_id": "qdrant_state_update_collection_002", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Blocking operation - waits for current optimizations to complete", "assertion": "Update blocks until current optimizations complete.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 0.9}
{"constraint_id": "qdrant_state_delete_collection_003", "endpoint": "collections+{collection_name}", "type": "state_constraint", "description": "Destructive operation - permanently deletes collection and all its data", "assertion": "Collection deletion permanently removes the collection and all its data.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_upsert_points_004", "endpoint": "collections+{collection_name}+points", "type": "state_constraint", "description": "Atomic batch upsert - all points inserted or none", "assertion": "Batch upsert is atomic: all points are inserted or none.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"constraint_id": "qdrant_state_delete_points_005", "endpoint": "collections+{collection_name}+points+delete", "type": "state_constraint", "description": "Deletion is atomic for the matched set", "assertion": "Point deletion is atomic for the matched set.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"constraint_id": "qdrant_state_query_points_010", "endpoint": "collections+{collection_name}+points+query", "type": "state_constraint", "description": "prefetch queries execute first, then final query runs on combined results", "assertion": "prefetch queries execute first, then the final query runs on combined results.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_001", "endpoint": "collections+{collection_name}", "description": "200 on success; 4XX on invalid params or collection already exists", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_002", "endpoint": "collections+{collection_name}", "description": "200 on success; 404 if collection not found", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_003", "endpoint": "collections+{collection_name}", "description": "200 with collection info; 404 if not found", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_005", "endpoint": "collections+{collection_name}+points", "description": "200 on success; 4XX on validation error", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_006", "endpoint": "collections+{collection_name}+points", "description": "200 with matching points (missing IDs are silently omitted)", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_007", "endpoint": "collections+{collection_name}+points+delete", "description": "200 on success; 400 if neither points nor filter provided", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_011", "endpoint": "collections+{collection_name}+points+query", "description": "200 with result points; supports multi-stage query pipeline via prefetch", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}
{"assertion_id": "qdrant_behavioral_017", "endpoint": "collections", "description": "200 with list of collections", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 1.0}

相关契约段（关键词定位 3 条）：
{"endpoint": "collections+{collection_name}+points+search", "kind": "range_constraints", "description": "hnsw_ef applicable when exact=false", "assertion": "hnsw_ef parameter is applicable only when exact=false.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "confidence": 0.9}
{"endpoint": "cluster+peer+{peer_id}", "kind": "state_constraints", "description": "Destructive cluster operation; force=true only when peer is unreachable", "assertion": "force=true should only be used when peer is unreachable.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "confidence": 0.9}
{"endpoint": "collections+{collection_name}+points+search", "kind": "state_constraints", "description": "If exact=true, performs brute-force search (slow but accurate); if exact=false, uses HNSW for approximate search", "assertion": "When exact=true, search uses brute-force; when exact=false, search uses HNSW.", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "confidence": 1.0}

API 模板：endpoint=collections+{collection_name}+points+query doc_quote='Universal Query API with multi-stage pipeline support' source=None


--- 补充契约依据（文档考古补全，同版本契约） ---
{"constraint_id": "qdrant_type_lookup_from_001", "endpoint": "collections+points+query", "description": "lookup_from.collection must reference an existing collection (non-existent -> 400/404)", "assertion": "lookup_from.collection exists in collections registry", "type": "state_constraint", "evidence_tier": "explicit", "source_url": "https://github.com/qdrant/qdrant/blob/v1.18.2/docs/redoc/master/openapi.json", "_provenance": "doc-archaeology 2026-08-20: issue #9522 (2026-06-20) — OpenAPI defines lookup_from.collection as required cross-collection reference; non-existent ref silently returns 200 with source results."}

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "qdrant_type_create_collection_001", "endpoint": "collections+{collection_name}", "description": "collection_name is string", "assertion": "collection_name type is string", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_update_collection_002", "endpoint": "collections+{collection_name}", "description": "All update fields are optional; at least one must be provided", "assertion": "At least one update field must be provided.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_overwrite_payload_004", "endpoint": "collections+{collection_name}+points+payload", "description": "Overwrite replaces entire payload, not merged", "assertion": "PUT payload replaces the entire payload; it does not merge.", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_create_collection_001", "endpoint": "collections+{collection_name}", "description": "shard_number minimum=1", "assertion": "shard_number >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_create_collection_002", "endpoint": "collections+{collection_name}", "description": "replication_factor minimum=1", "assertion": "replication_factor >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_create_collection_003", "endpoint": "collections+{collection_name}", "description": "write_consistency_factor minimum=1", "assertion": "write_consistency_factor >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_create_collection_004", "endpoint": "collections+{collection_name}", "description": "timeout minimum=1", "assertion": "timeout >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_scroll_points_005", "endpoint": "collections+{collection_name}+points+scroll", "description": "limit default=10 (adjustable)", "assertion": "limit default=10", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_search_points_006", "endpoint": "collections+{collection_name}+points+search", "description": "hnsw_ef applicable when exact=false", "assertion": "hnsw_ef parameter is applicable only when exact=false.", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_search_groups_007", "endpoint": "collections+{collection_name}+points+search+groups", "description": "group_size >= 1; limit >= 1", "assertion": "group_size >= 1 AND limit >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_query_points_008", "endpoint": "collections+{collection_name}+points+query", "description": "limit default=10", "assertion": "limit default=10 for query endpoint.", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_recommend_009", "endpoint": "collections+{collection_name}+points+recommend", "description": "strategy must be one of: average_vector, best_score, sum_scores", "assertion": "strategy IN (average_vector, best_score, sum_scores)", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_create_collection_001", "endpoint": "collections+{collection_name}", "description": "Atomic collection creation: after 200 response, collection is fully initialized and ready for operations", "assertion": "Atomic collection creation. After 200 response, collection is fully initialized and ready for operations.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
