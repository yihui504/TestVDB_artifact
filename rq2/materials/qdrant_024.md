# 候选缺陷 qdrant_024

[vendor=qdrant version=1.19.0 endpoint=recommend]

--- 观察到的行为（observed） ---

重放环境:qdrant v1.19.0 container (port 6338);证据来源:container replay,HTTP interactions captured verbatim。

=== DELETE /collections/main ===
-> 200 {"result":false,"status":"ok","time":0.000107115}
=== DELETE /collections/lookup8 ===
-> 200 {"result":false,"status":"ok","time":0.000073157}
=== PUT /collections/main ===
{"vectors": {"size": 4, "distance": "Euclid"}}
-> 200 {"result":true,"status":"ok","time":0.257165763}
=== PUT /collections/main/points?wait=true ===
{"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 2, "vector": [0.4, 0.3, 0.2, 0.1]}]}
-> 200 {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.003787025}
=== PUT /collections/lookup8 ===
{"vectors": {"size": 8, "distance": "Euclid"}}
-> 200 {"result":true,"status":"ok","time":0.254043806}
=== PUT /collections/lookup8/points?wait=true ===
{"points": [{"id": 100, "vector": [0.9, 0, 0, 0, 0, 0, 0, 0]}]}
-> 200 {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.004065926}
=== POST /collections/main/points/recommend ===
{"positive": [100], "limit": 2, "lookup_from": {"collection": "lookup8"}}
-> 400 {"status":{"error":"Wrong input: Vector dimension error: expected dim: 4, got 8"},"time":0.001524875}
=== POST /collections/main/points/recommend ===
{"positive": [[0.1, 0.2, 0.3, 0.4]], "negative": [100], "limit": 3, "lookup_from": {"collection": "lookup8"}}
-> 200 {"result":[{"id":1,"version":1,"score":0.9643651},{"id":2,"version":1,"score":1.3674794}],"status":"ok","time":0.000321475}

--- 契约依据（expected，来自该版本 API 契约） ---

{"constraint_id": "qdrant_range_recommend_009", "endpoint": "collections+{collection_name}+points+recommend", "description": "strategy must be one of: average_vector, best_score, sum_scores", "assertion": "strategy IN (average_vector, best_score, sum_scores)", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}

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
