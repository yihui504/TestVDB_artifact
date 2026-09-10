=== 候选缺陷 weaviate_009 ===
[vendor=weaviate version=1.38.2 defect_type=behavior endpoint=POST /batch/objects]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] POST schema BatchVectorBugRepro -> http=200
- [c2] control: singular POST with vector=[] -> http=200
- [c3] batch with empty-vector item -> http=200, per-item statuses=None

执行日志全文（output_weaviate_009.log）：
=== REQ 1 ===
DELETE http://localhost:18080/v1/schema/BatchVectorBugRepro
=== RESP 1 ===
status: 200
body: 

=== REQ 2 ===
POST http://localhost:18080/v1/schema
payload: {"class": "BatchVectorBugRepro", "vectorizer": "none", "vectorIndexType": "hnsw", "vectorIndexConfig": {"distance": "cosine"}}
=== RESP 2 ===
status: 200
body: {"class":"BatchVectorBugRepro","invertedIndexConfig":{"bm25":{"b":0.75,"k1":1.2},"cleanupIntervalSeconds":60,"stopwords":{"additions":null,"preset":"en","removals":null},"usingBlockMaxWAND":true},"multiTenancyConfig":{"autoTenantActivation":false,"autoTenantCreation":false,"enabled":false},"properties":null,"shardingConfig":{"virtualPerPhysical":128,"desiredCount":1,"actualCount":1,"desiredVirtualCount":128,"actualVirtualCount":128,"key":"_id","strategy":"hash","function":"murmur3"},"vectorIndexConfig":{"skip":false,"cleanupIntervalSeconds":300,"maxConnections":32,"efConstruction":128,"ef":-1,"dynamicEfMin":100,"dynamicEfMax":500,"dynamicEfFactor":8,"vectorCacheMaxObjects":1000000000000,"flatSearchCutoff":40000,"distance":"cosine","pq":{"enabled":false,"bitCompression":false,"segments":0,"centroids":256,"trainingLimit":100000,"encoder":{"type":"kmeans","distribution":"log-normal"}},"bq":{"enabled":false},"sq":{"enabled":false,"trainingLimit":100000,"rescoreLimit":20},"rq":{"enabled":false,"bits":8,"rescoreLimit":20},"filterStrategy":"acorn","multivector":{"enabled":false,"muvera":{"enabled":false,"ksim":4,"dprojections":16,"repetitions":10},"aggregation":"maxSim"},"skipDefaultQuantization":false,"trackDefaultQuantization":false},"vectorIndexType":"hnsw","vectorizer":"none","replicationConfig":{"deletionStrategy":"TimeBasedResolution","factor":1,"asyncEnabled":false}}


=== REQ 3 ===
POST http://localhost:18080/v1/objects
payload: {"class": "BatchVectorBugRepro", "properties": {"name": "control-singular"}, "vector": []}
=== RESP 3 ===
status: 200
body: {"class":"BatchVectorBugRepro","creationTimeUnix":1786647802626,"id":"472773d8-7342-495c-9ea5-8d57c46fee08","lastUpdateTimeUnix":1786647802626,"properties":{"name":"control-singular"}}


=== REQ 4 ===
POST http://localhost:18080/v1/batch/objects
payload: {"objects": [{"class": "BatchVectorBugRepro", "id": "11111111-1111-4111-8111-111111111111", "properties": {"name": "valid-item"}, "vector": [0.1, 0.2, 0.3, 0.4]}, {"class": "BatchVectorBugRepro", "id": "22222222-2222-4222-8222-222222222222", "properties": {"name": "bad-empty-vector"}, "vector": []}]}
=== RESP 4 ===
status: 200
body: [{"class":"BatchVectorBugRepro","creationTimeUnix":1786647802646,"id":"11111111-1111-4111-8111-111111111111","lastUpdateTimeUnix":1786647802646,"properties":{"name":"valid-item"},"vector":[0.1,0.2,0.3,0.4],"deprecations":null,"result":{"status":"SUCCESS"}},{"class":"BatchVectorBugRepro","creationTimeUnix":1786647802646,"id":"22222222-2222-4222-8222-222222222222","lastUpdateTimeUnix":1786647802646,"properties":{"name":"bad-empty-vector"},"deprecations":null,"result":{"status":"SUCCESS"}}]




--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（6 条，来自 weaviate 1.38.2 契约，endpoint=POST /batch/objects）：
{"constraint_id": "weaviate_type_object_id_001", "endpoint": "POST /objects", "type": "type_constraint", "description": "id must be valid UUID format (v4 or v7)", "assertion": "id matches UUID regex (version 4 or 7)", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_type_object_vector_001", "endpoint": "POST /objects", "type": "type_constraint", "description": "vector must be array of floats", "assertion": "vector is array of number (float)", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_state_batch_idempotent_001", "endpoint": "POST /batch/objects", "type": "state_constraint", "description": "idempotent by UUID -- existing UUIDs overwritten (PUT semantics per item)", "assertion": "batch create is idempotent; existing UUIDs are replaced", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_state_batch_reject_all_001", "endpoint": "POST /batch/objects", "type": "state_constraint", "description": "429 WHOLE BATCH rejected (no partial fill)", "assertion": "usage limit exceeded rejects entire batch, no partial success", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"assertion_id": "weaviate_behavioral_post_object_exists_001", "endpoint": "POST /objects", "description": "POST fails with error if id already exists (use PUT to replace or PATCH to update)", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"assertion_id": "weaviate_behavioral_batch_reject_partial_001", "endpoint": "POST /batch/objects", "description": "429 WHOLE BATCH rejected (no partial fill)", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}

相关契约段（关键词定位 4 条）：
{"endpoint": "POST /batch/objects", "kind": "state_constraints", "description": "429 WHOLE BATCH rejected (no partial fill)", "assertion": "usage limit exceeded rejects entire batch, no partial success", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "POST /batch/objects", "kind": "state_constraints", "description": "idempotent by UUID -- existing UUIDs overwritten (PUT semantics per item)", "assertion": "batch create is idempotent; existing UUIDs are replaced", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "DELETE /schema/{className}", "kind": "state_constraints", "description": "permanently deletes all data objects and references (cascade delete)", "assertion": "deleting collection cascades to all objects and references", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "POST /batch/objects", "kind": "assertion", "description": "429 WHOLE BATCH rejected (no partial fill)", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "weaviate_range_schema_replication_001", "endpoint": "/schema POST", "description": "replicationConfig.factor is an integer (default 1)", "assertion": "replicationConfig.factor >= 1", "type": "range_constraint", "confidence": 0.85, "evidence_tier": "inferred_from_example", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_range_replication_scale_001", "endpoint": "/replication/scale GET", "description": "replicationFactor must be at least 1", "assertion": "replicationFactor >= 1", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"contract_id": "weaviate_bc_put_replace_atomic", "description": "PUT replaces object atomically; schema-validated; lastUpdateTimeUnix updated", "scenario": "PUT /objects/{className}/{id} with full body; GET returns new values", "expected_behavior": "after 200, GET reflects all new field values; invalid schema returns 422 (no partial update)", "related_endpoints": ["/objects/{className}/{id} PUT", "/objects/{className}/{id} GET"], "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json"}
{"constraint_id": "weaviate_type_objects_create_001", "endpoint": "/objects POST", "description": "id field must be valid UUID format", "assertion": "body.id is null OR matches UUID format", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_objects_create_002", "endpoint": "/objects POST", "description": "vector takes precedence over vectorizer module", "assertion": "if body.vector provided, it overrides vectorizer-generated vector", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_references_add_001", "endpoint": "/objects/{className}/{id}/references/{propertyName} POST", "description": "beacon format must be weaviate://localhost/{uuid}", "assertion": "body.beacon matches /^weaviate:\\/\\/localhost\\/[0-9a-f-]{36}$/", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_range_objects_list_001", "endpoint": "/objects GET", "description": "offset+limit must not exceed QUERY_MAXIMUM_RESULTS (default 10000)", "assertion": "offset + limit <= 10000", "type": "range_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_range_batch_delete_001", "endpoint": "/batch/objects DELETE", "description": "max deletions per request is QUERY_MAXIMUM_RESULTS (default 10000)", "assertion": "results.matches + results.failed + results.successful <= 10000", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_state_objects_list_001", "endpoint": "/objects GET", "description": "after cursor is mutually exclusive with offset and sort", "assertion": "(after provided) implies (offset == 0 and sort not provided)", "type": "state_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_state_batch_objects_001", "endpoint": "/batch/objects POST", "description": "batch is idempotent by UUID; existing UUIDs are overwritten (PUT semantics per item)", "assertion": "POST /batch/objects with existing UUID overwrites rather than errors", "type": "state_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_state_objects_create_001", "endpoint": "/objects POST", "description": "POST fails if id already exists; use PUT/PATCH to update", "assertion": "POST /objects returns error if id exists; PUT/PATCH required to update", "type": "state_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_state_schema_delete_001", "endpoint": "/schema/{className} DELETE", "description": "deleting a collection permanently deletes all data objects in the collection", "assertion": "after DELETE /schema/{className}, GET /objects?class={className} returns empty", "type": "state_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"assertion_id": "weaviate_behavioral_objects_create_001", "endpoint": "/objects POST", "description": "POST with existing id fails; should return error not overwrite", "category": "behavioral", "expected_behavior": "error response (not 200 overwrite); use PUT/PATCH to update", "confidence": 0.95, "evidence_tier": "explicit", "defect_type_if_violated": "Type1_IllegalSuccess", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "doc_version": "1.38.0"}
{"assertion_id": "weaviate_behavioral_objects_create_002", "endpoint": "/objects POST", "description": "exceeding object count usage limit returns 429", "category": "behavioral", "expected_behavior": "429 UsageLimitExceededResponse", "confidence": 0.95, "evidence_tier": "explicit", "defect_type_if_violated": "Type1_IllegalSuccess", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "doc_version": "1.38.0"}
