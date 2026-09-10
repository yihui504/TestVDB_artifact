=== 候选缺陷 weaviate_010 ===
[vendor=weaviate version=1.38.2 defect_type=behavior endpoint=DELETE /batch/objects]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] POST schema BoundaryTestBatchDelete -> http=200
- [c2] batch delete with class but missing where -> http=500, body: validate: empty match.where clause
- [c3] batch delete with empty match {} -> http=500, body: validate: empty match.class clause

执行日志全文（output_weaviate_010.log）：
=== REQ 1 ===
DELETE http://localhost:18080/v1/schema/BoundaryTestBatchDelete
=== RESP 1 ===
status: 200
body: 

=== REQ 2 ===
POST http://localhost:18080/v1/schema
payload: {"class": "BoundaryTestBatchDelete", "vectorizer": "none", "properties": [{"name": "title", "dataType": ["text"]}]}
=== RESP 2 ===
status: 200
body: {"class":"BoundaryTestBatchDelete","invertedIndexConfig":{"bm25":{"b":0.75,"k1":1.2},"cleanupIntervalSeconds":60,"stopwords":{"additions":null,"preset":"en","removals":null},"usingBlockMaxWAND":true},"multiTenancyConfig":{"autoTenantActivation":false,"autoTenantCreation":false,"enabled":false},"properties":[{"dataType":["text"],"indexFilterable":true,"indexRangeFilters":false,"indexSearchable":true,"name":"title","tokenization":"word"}],"shardingConfig":{"virtualPerPhysical":128,"desiredCount":1,"actualCount":1,"desiredVirtualCount":128,"actualVirtualCount":128,"key":"_id","strategy":"hash","function":"murmur3"},"vectorIndexConfig":{"skip":false,"cleanupIntervalSeconds":300,"maxConnections":32,"efConstruction":128,"ef":-1,"dynamicEfMin":100,"dynamicEfMax":500,"dynamicEfFactor":8,"vectorCacheMaxObjects":1000000000000,"flatSearchCutoff":40000,"distance":"cosine","pq":{"enabled":false,"bitCompression":false,"segments":0,"centroids":256,"trainingLimit":100000,"encoder":{"type":"kmeans","distribution":"log-normal"}},"bq":{"enabled":false},"sq":{"enabled":false,"trainingLimit":100000,"rescoreLimit":20},"rq":{"enabled":false,"bits":8,"rescoreLimit":20},"filterStrategy":"acorn","multivector":{"enabled":false,"muvera":{"enabled":false,"ksim":4,"dprojections":16,"repetitions":10},"aggregation":"maxSim"},"skipDefaultQuantization":false,"trackDefaultQuantization":false},"vectorIndexType":"hnsw","vectorizer":"none","replicationConfig":{"deletionStrategy":"TimeBasedResolution","factor":1,"asyncEnabled":false}}


=== REQ 3 ===
DELETE http://localhost:18080/v1/batch/objects
payload: {"match": {"class": "BoundaryTestBatchDelete"}, "output": "minimal"}
=== RESP 3 ===
status: 500
body: {"error":[{"message":"validate: empty match.where clause"}]}


=== REQ 4 ===
DELETE http://localhost:18080/v1/batch/objects
payload: {"match": {}, "output": "minimal"}
=== RESP 4 ===
status: 500
body: {"error":[{"message":"validate: empty match.class clause"}]}




--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（1 条，来自 weaviate 1.38.2 契约，endpoint=DELETE /batch/objects）：
{"constraint_id": "weaviate_range_batch_delete_001", "endpoint": "DELETE /batch/objects", "type": "range_constraint", "description": "max deletions per request = QUERY_MAXIMUM_RESULTS (default 10000)", "assertion": "deleted count <= QUERY_MAXIMUM_RESULTS", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}

相关契约段（关键词定位 4 条）：
{"endpoint": "POST /schema", "kind": "type_constraints", "description": "class field must be CamelCase (capital first letter, alphanumeric only)", "assertion": "class matches regex ^[A-Z][a-zA-Z0-9]*$", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "POST /schema", "kind": "type_constraints", "description": "properties[].dataType must be array of valid types or class references", "assertion": "properties[].dataType is array of strings; first-capital values are class references", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "POST /batch/objects", "kind": "state_constraints", "description": "idempotent by UUID -- existing UUIDs overwritten (PUT semantics per item)", "assertion": "batch create is idempotent; existing UUIDs are replaced", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "POST /batch/objects", "kind": "state_constraints", "description": "429 WHOLE BATCH rejected (no partial fill)", "assertion": "usage limit exceeded rejects entire batch, no partial success", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "weaviate_range_schema_replication_001", "endpoint": "/schema POST", "description": "replicationConfig.factor is an integer (default 1)", "assertion": "replicationConfig.factor >= 1", "type": "range_constraint", "confidence": 0.85, "evidence_tier": "inferred_from_example", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_range_replication_scale_001", "endpoint": "/replication/scale GET", "description": "replicationFactor must be at least 1", "assertion": "replicationFactor >= 1", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_schema_create_001", "endpoint": "/schema POST", "description": "class field must be CamelCase", "assertion": "properties.class matches /^[A-Z][a-zA-Z0-9]*$/", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_objects_create_001", "endpoint": "/objects POST", "description": "id field must be valid UUID format", "assertion": "body.id is null OR matches UUID format", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_references_add_001", "endpoint": "/objects/{className}/{id}/references/{propertyName} POST", "description": "beacon format must be weaviate://localhost/{uuid}", "assertion": "body.beacon matches /^weaviate:\\/\\/localhost\\/[0-9a-f-]{36}$/", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_batch_references_001", "endpoint": "/batch/references POST", "description": "from beacon format must include className/uuid/propertyName", "assertion": "from matches /^weaviate:\\/\\/localhost\\/{ClassName}\\/{uuid}\\/{propertyName}$/", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_graphql_001", "endpoint": "/graphql POST", "description": "GraphQL is case-sensitive", "assertion": "query string case must match schema exactly", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://weaviate.io/developers/weaviate/api/graphql", "source_status": "reachable"}
{"constraint_id": "weaviate_type_backups_create_001", "endpoint": "/backups/{backend} POST", "description": "backup id must be URL-safe (lowercase, numbers, underscore, minus only)", "assertion": "body.id matches /^[a-z0-9_-]+$/", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_namespaces_create_001", "endpoint": "/namespaces/{namespace_id} POST", "description": "namespace name must be lowercase letters, digits, hyphens; 3-36 chars; start/end with letter or digit", "assertion": "namespace_id matches /^[a-z0-9][a-z0-9-]{1,34}[a-z0-9]$/", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_range_batch_delete_001", "endpoint": "/batch/objects DELETE", "description": "max deletions per request is QUERY_MAXIMUM_RESULTS (default 10000)", "assertion": "results.matches + results.failed + results.successful <= 10000", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_schema_create_002", "endpoint": "/schema POST", "description": "vectorIndexType must be one of allowed index types", "assertion": "properties.vectorIndexType in {hnsw, flat, dynamic, bwes}", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_schema_create_003", "endpoint": "/schema POST", "description": "properties[].tokenization must be a valid enum value", "assertion": "properties.properties[].tokenization in {word, lowercase, whitespace, field, trigram, gse, kagome_kr, kagome_ja, gse_ch}", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_state_schema_update_001", "endpoint": "/schema/{className} PUT", "description": "PUT does NOT add properties (use POST /schema/{className}/properties) and does NOT rename", "assertion": "PUT /schema/{className} does not change properties count or names", "type": "state_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_objects_create_002", "endpoint": "/objects POST", "description": "vector takes precedence over vectorizer module", "assertion": "if body.vector provided, it overrides vectorizer-generated vector", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
