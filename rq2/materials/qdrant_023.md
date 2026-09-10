# 候选缺陷 qdrant_023

[vendor=qdrant version=1.19.0 endpoint=snapshot]

--- 观察到的行为（observed） ---

重放环境:qdrant v1.19.0 container (port 6338);证据来源:container replay,HTTP interactions captured verbatim。

=== DELETE /collections/demo ===
-> 200 {"result":true,"status":"ok","time":0.008931534}
=== PUT /collections/demo ===
{"vectors": {"size": 4, "distance": "Euclid"}}
-> 200 {"result":true,"status":"ok","time":0.223161745}
=== PUT /collections/demo/points?wait=true ===
{"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}, {"id": 2, "vector": [0.2, 0.3, 0.4, 0.5]}, {"id": 3, "vector": [0.3, 0.4, 0.5, 0.6]}]}
-> 200 {"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.003837353}
=== POST /collections/demo/snapshots?wait=true ===
-> 200 {"result":{"name":"demo-8799445405866919-2026-09-09-08-58-50.snapshot","creation_time":"2026-09-09T08:58:50","size":139264,"checksum":"63f8d98b0eb47ff72931db5c9aecaa27c0c83956da254f8e88da64a160a911b5"},"status":"ok","time":0.167109493}
=== PUT /collections/demo/points?wait=true ===
{"points": [{"id": 50, "vector": [0.9, 0.9, 0.9, 0.9]}]}
-> 200 {"result":{"operation_id":2,"status":"completed"},"status":"ok","time":0.002972055}
=== PUT /collections/demo/snapshots/recover?wait=true ===
{"location": "file:///qdrant/snapshots/demo/demo-8799445405866919-2026-09-09-08-58-50.snapshot", "priority": "replica"}
-> 200 {"result":true,"status":"ok","time":0.122351839}
=== POST /collections/demo/points/count ===
{"exact": true}
-> 200 {"result":{"count":3},"status":"ok","time":0.000518211}

--- 契约依据（expected，来自该版本 API 契约） ---

(endpoint introduced after the pinned contract extraction; documented semantics quoted inside the transcript)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "qdrant_state_count_points_008", "endpoint": "collections+{collection_name}+points+count", "description": "exact=true performs full scan; exact=false uses segment statistics", "assertion": "exact=true performs a full scan; exact=false uses segment statistics.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"assertion_id": "qdrant_behavioral_010", "endpoint": "collections+{collection_name}+points+count", "description": "200 with count result", "category": "behavioral", "expected_behavior": "Returns 200 with object containing 'count' field (integer).", "confidence": 1.0, "evidence_tier": "explicit", "defect_type_if_violated": "Type3_RuntimeFailure", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "doc_version": "1.18.x", "source_verified": true}
{"contract_id": "qdrant_behavioral_upsert_count_consistency", "description": "Upsert points and count - count should reflect the exact number of upserted points", "scenario": "Upsert N points via PUT /collections/{name}/points, then count points via POST /collections/{name}/points/count with exact=true. The count should equal N.", "expected_behavior": "After upserting N points successfully, exact count returns N.", "related_endpoints": ["collections+{collection_name}+points", "collections+{collection_name}+points+count"], "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points"}
{"constraint_id": "qdrant_range_search_points_006", "endpoint": "collections+{collection_name}+points+search", "description": "hnsw_ef applicable when exact=false", "assertion": "hnsw_ef parameter is applicable only when exact=false.", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_state_search_points_009", "endpoint": "collections+{collection_name}+points+search", "description": "If exact=true, performs brute-force search (slow but accurate); if exact=false, uses HNSW for approximate search", "assertion": "When exact=true, search uses brute-force; when exact=false, search uses HNSW.", "type": "state_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/search/points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_search_groups_007", "endpoint": "collections+{collection_name}+points+search+groups", "description": "group_size >= 1; limit >= 1", "assertion": "group_size >= 1 AND limit >= 1", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_type_upsert_points_003", "endpoint": "collections+{collection_name}+points", "description": "id is integer (uint64) or UUID string; vector is array of floats or object of named vectors; payload is key-value object", "assertion": "id type is integer (uint64) or UUID string; vector type is array of floats or object of named vectors; payload type is key-value object.", "type": "type_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
{"constraint_id": "qdrant_range_recommend_009", "endpoint": "collections+{collection_name}+points+recommend", "description": "strategy must be one of: average_vector, best_score, sum_scores", "assertion": "strategy IN (average_vector, best_score, sum_scores)", "type": "range_constraint", "confidence": 1.0, "evidence_tier": "explicit", "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference", "source_status": "reachable", "doc_version": "1.18.x", "source_verified": true}
