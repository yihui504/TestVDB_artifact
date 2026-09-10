# 候选缺陷 qdrant_026

[vendor=qdrant version=1.19.0 endpoint=groups]

--- 观察到的行为（observed） ---

重放环境:qdrant v1.19.0 container (port 6338);证据来源:container replay,HTTP interactions captured verbatim。

=== DELETE /collections/gdemo ===
-> 200 {"result":true,"status":"ok","time":0.014015108}
=== PUT /collections/gdemo ===
{"vectors": {"size": 4, "distance": "Euclid"}}
-> 200 {"result":true,"status":"ok","time":0.243744152}
=== PUT /collections/gdemo/points?wait=true ===
{"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "a"}}, {"id": 2, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "b"}}, {"id": 3, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "a"}}, {"id": 4, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "b"}}, {"id": 5, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "a"}}, {"id": 6, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "b"}}, {"id": 7, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "a"}}, {"id": 8, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "b"}}]}
-> 200 {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.004632063}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":3,"version":0,"score":1.0},{"id":1,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0}],"id":"a"},{"hits":[{"id":6,"version":0,"score":1.0},{"id":2,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0}],"id":"b"}]},"status":"ok","time":0.001400367}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":5,"version":0,"score":1.0},{"id":1,"version":0,"score":1.0},{"id":3,"version":0,"score":1.0}],"id":"a"},{"hits":[{"id":2,"version":0,"score":1.0},{"id":6,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0}],"id":"b"}]},"status":"ok","time":0.000778015}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":1,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0},{"id":3,"version":0,"score":1.0}],"id":"a"},{"hits":[{"id":2,"version":0,"score":1.0},{"id":6,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0}],"id":"b"}]},"status":"ok","time":0.000834957}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":1,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0},{"id":3,"version":0,"score":1.0}],"id":"a"},{"hits":[{"id":2,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0},{"id":6,"version":0,"score":1.0}],"id":"b"}]},"status":"ok","time":0.000723067}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":5,"version":0,"score":1.0},{"id":1,"version":0,"score":1.0},{"id":3,"version":0,"score":1.0}],"id":"a"},{"hits":[{"id":6,"version":0,"score":1.0},{"id":2,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0}],"id":"b"}]},"status":"ok","time":0.000920347}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":4,"version":0,"score":1.0},{"id":6,"version":0,"score":1.0},{"id":2,"version":0,"score":1.0}],"id":"b"},{"hits":[{"id":3,"version":0,"score":1.0},{"id":1,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0}],"id":"a"}]},"status":"ok","time":0.000743167}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":6,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0},{"id":2,"version":0,"score":1.0}],"id":"b"},{"hits":[{"id":3,"version":0,"score":1.0},{"id":1,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0}],"id":"a"}]},"status":"ok","time":0.000485072}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":1,"version":0,"score":1.0},{"id":3,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0}],"id":"a"},{"hits":[{"id":6,"version":0,"score":1.0},{"id":2,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0}],"id":"b"}]},"status":"ok","time":0.000327518}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":6,"version":0,"score":1.0},{"id":2,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0}],"id":"b"},{"hits":[{"id":1,"version":0,"score":1.0},{"id":3,"version":0,"score":1.0},{"id":5,"version":0,"score":1.0}],"id":"a"}]},"status":"ok","time":0.000777721}
=== POST /collections/gdemo/points/query/groups ===
{"group_by": "grp", "limit": 2, "group_size": 3}
-> 200 {"result":{"groups":[{"hits":[{"id":5,"version":0,"score":1.0},{"id":3,"version":0,"score":1.0},{"id":1,"version":0,"score":1.0}],"id":"a"},{"hits":[{"id":6,"version":0,"score":1.0},{"id":2,"version":0,"score":1.0},{"id":4,"version":0,"score":1.0}],"id":"b"}]},"status":"ok","time":0.000849965}
[STDOUT]
10 identical requests -> 10 distinct member-set signatures
[[null, [1, 3, 5]], [null, [6, 2, 4]]]
[[null, [1, 5, 3]], [null, [2, 4, 6]]]
[[null, [1, 5, 3]], [null, [2, 6, 4]]]
[[null, [3, 1, 5]], [null, [6, 2, 4]]]
[[null, [4, 6, 2]], [null, [3, 1, 5]]]
[[null, [5, 1, 3]], [null, [2, 6, 4]]]
[[null, [5, 1, 3]], [null, [6, 2, 4]]]
[[null, [5, 3, 1]], [null, [6, 2, 4]]]
[[null, [6, 2, 4]], [null, [1, 3, 5]]]
[[null, [6, 4, 2]], [null, [3, 1, 5]]]

--- 契约依据（expected，来自该版本 API 契约） ---

{"constraint_id": "qdrant_range_search_groups_007", "endpoint": "collections+{collection_name}+points+search+groups", "description": "group_size >= 1; limit >= 1", "assertion": "group_size >= 1 AND limit >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "qdrant_range_search_groups_007", "endpoint": "collections+{collection_name}+points+search+groups", "description": "group_size >= 1; limit >= 1", "assertion": "group_size >= 1 AND limit >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_scroll_points_005", "endpoint": "collections+{collection_name}+points+scroll", "description": "limit default=10 (adjustable)", "assertion": "limit default=10", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_query_points_008", "endpoint": "collections+{collection_name}+points+query", "description": "limit default=10", "assertion": "limit default=10 for query endpoint.", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_recommend_009", "endpoint": "collections+{collection_name}+points+recommend", "description": "strategy must be one of: average_vector, best_score, sum_scores", "assertion": "strategy IN (average_vector, best_score, sum_scores)", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_008", "endpoint": "collections+{collection_name}+points+search", "description": "200 with ranked results descending by score; 4XX on invalid params", "category": "behavioral", "expected_behavior": "Returns 200 with array of scored points (descending by score); returns 4XX on invalid params.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_011", "endpoint": "collections+{collection_name}+points+query", "description": "200 with result points; supports multi-stage query pipeline via prefetch", "category": "behavioral", "expected_behavior": "Returns 200 with array of scored points.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_012", "endpoint": "collections+{collection_name}+points+recommend", "description": "200 with ranked results", "category": "behavioral", "expected_behavior": "Returns 200 with array of scored points.", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"contract_id": "qdrant_behavioral_upsert_search_consistency", "description": "Upsert points and search - search should find the upserted points", "scenario": "Upsert a point with a known vector, then search for that vector. The upserted point should appear in the search results.", "expected_behavior": "After upserting a point, a search with the same vector returns the point among results (subject to eventual consistency if not waited).", "related_endpoints": ["collections+{collection_name}+points", "collections+{collection_name}+points+search"], "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points"}
{"constraint_id": "qdrant_type_create_collection_001", "endpoint": "collections+{collection_name}", "description": "collection_name is string", "assertion": "collection_name type is string", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_update_collection_002", "endpoint": "collections+{collection_name}", "description": "All update fields are optional; at least one must be provided", "assertion": "At least one update field must be provided.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_overwrite_payload_004", "endpoint": "collections+{collection_name}+points+payload", "description": "Overwrite replaces entire payload, not merged", "assertion": "PUT payload replaces the entire payload; it does not merge.", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_create_collection_001", "endpoint": "collections+{collection_name}", "description": "shard_number minimum=1", "assertion": "shard_number >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_create_collection_002", "endpoint": "collections+{collection_name}", "description": "replication_factor minimum=1", "assertion": "replication_factor >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
