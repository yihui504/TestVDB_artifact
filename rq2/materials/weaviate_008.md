=== 候选缺陷 weaviate_008 ===
[vendor=weaviate version=1.38.0 defect_type=param_validation endpoint=/schema/{className}/tenants]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [c1] POST schema TestTenant (multi-tenancy enabled) -> http=200
- [c2] control: create tenant with activityStatus='ACTIVE' -> http=200
- [c3] create tenant with activityStatus='' -> http=200

执行日志全文（output_weaviate_008.log）：
=== REQ 1 ===
DELETE http://localhost:18080/v1/schema/TestTenant
=== RESP 1 ===
status: 200
body: 

=== REQ 2 ===
POST http://localhost:18080/v1/schema
payload: {"class": "TestTenant", "multiTenancyConfig": {"enabled": true}}
=== RESP 2 ===
status: 200
body: {"class":"TestTenant","invertedIndexConfig":{"bm25":{"b":0.75,"k1":1.2},"cleanupIntervalSeconds":60,"stopwords":{"additions":null,"preset":"en","removals":null},"usingBlockMaxWAND":true},"multiTenancyConfig":{"autoTenantActivation":false,"autoTenantCreation":false,"enabled":true},"properties":null,"shardingConfig":{"virtualPerPhysical":0,"desiredCount":0,"actualCount":0,"desiredVirtualCount":0,"actualVirtualCount":0,"key":"","strategy":"","function":""},"vectorIndexConfig":{"skip":false,"cleanupIntervalSeconds":300,"maxConnections":32,"efConstruction":128,"ef":-1,"dynamicEfMin":100,"dynamicEfMax":500,"dynamicEfFactor":8,"vectorCacheMaxObjects":1000000000000,"flatSearchCutoff":40000,"distance":"cosine","pq":{"enabled":false,"bitCompression":false,"segments":0,"centroids":256,"trainingLimit":100000,"encoder":{"type":"kmeans","distribution":"log-normal"}},"bq":{"enabled":false},"sq":{"enabled":false,"trainingLimit":100000,"rescoreLimit":20},"rq":{"enabled":false,"bits":8,"rescoreLimit":20},"filterStrategy":"acorn","multivector":{"enabled":false,"muvera":{"enabled":false,"ksim":4,"dprojections":16,"repetitions":10},"aggregation":"maxSim"},"skipDefaultQuantization":false,"trackDefaultQuantization":false},"vectorIndexType":"hnsw","vectorizer":"none","replicationConfig":{"deletionStrategy":"TimeBasedResolution","factor":1,"asyncEnabled":false}}


=== REQ 3 ===
POST http://localhost:18080/v1/schema/TestTenant/tenants
payload: [{"name": "tenant_valid", "activityStatus": "ACTIVE"}]
=== RESP 3 ===
status: 200
body: [{"activityStatus":"HOT","name":"tenant_valid"}]


=== REQ 4 ===
POST http://localhost:18080/v1/schema/TestTenant/tenants
payload: [{"name": "tenant_empty", "activityStatus": ""}]
=== RESP 4 ===
status: 200
body: [{"name":"tenant_empty"}]




--- 契约依据（expected，来自该版本 API 契约） ---
约束条目（12 条，来自 weaviate 1.38.0 契约，endpoint=/schema/{className}/tenants）：
{"constraint_id": "weaviate_type_schema_create_001", "endpoint": "/schema POST", "type": "type_constraint", "description": "class field must be CamelCase", "assertion": "properties.class matches /^[A-Z][a-zA-Z0-9]*$/", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_type_schema_create_002", "endpoint": "/schema POST", "type": "type_constraint", "description": "vectorIndexType must be one of allowed index types", "assertion": "properties.vectorIndexType in {hnsw, flat, dynamic, bwes}", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_type_schema_create_003", "endpoint": "/schema POST", "type": "type_constraint", "description": "properties[].tokenization must be a valid enum value", "assertion": "properties.properties[].tokenization in {word, lowercase, whitespace, field, trigram, gse, kagome_kr, kagome_ja, gse_ch}", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_type_tenants_create_001", "endpoint": "/schema/{className}/tenants POST", "type": "type_constraint", "description": "Tenant.activityStatus on create must be ACTIVE or INACTIVE", "assertion": "body[].activityStatus in {ACTIVE, INACTIVE}", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_type_tenants_update_001", "endpoint": "/schema/{className}/tenants PUT", "type": "type_constraint", "description": "Tenant.activityStatus on update must be ACTIVE, INACTIVE, or OFFLOADED", "assertion": "body[].activityStatus in {ACTIVE, INACTIVE, OFFLOADED}", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_range_schema_replication_001", "endpoint": "/schema POST", "type": "range_constraint", "description": "replicationConfig.factor is an integer (default 1)", "assertion": "replicationConfig.factor >= 1", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.85}
{"constraint_id": "weaviate_state_schema_delete_001", "endpoint": "/schema/{className} DELETE", "type": "state_constraint", "description": "deleting a collection permanently deletes all data objects in the collection", "assertion": "after DELETE /schema/{className}, GET /objects?class={className} returns empty", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"constraint_id": "weaviate_state_tenants_delete_001", "endpoint": "/schema/{className}/tenants DELETE", "type": "state_constraint", "description": "deleting tenants permanently deletes all tenant data", "assertion": "after DELETE tenants, GET tenant returns 404 and its data is gone", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.9}
{"constraint_id": "weaviate_state_schema_update_001", "endpoint": "/schema/{className} PUT", "type": "state_constraint", "description": "PUT does NOT add properties (use POST /schema/{className}/properties) and does NOT rename", "assertion": "PUT /schema/{className} does not change properties count or names", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.9}
{"assertion_id": "weaviate_behavioral_schema_create_001", "endpoint": "/schema POST", "description": "creating collection with disallowed vectorIndexType returns 422 RestrictionViolationResponse", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"assertion_id": "weaviate_behavioral_schema_create_002", "endpoint": "/schema POST", "description": "exceeding collections/shards usage limit returns 429 UsageLimitExceededResponse", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"assertion_id": "weaviate_behavioral_tenants_create_001", "endpoint": "/schema/{className}/tenants POST", "description": "exceeding tenant usage limit returns 429 with limit: tenants", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}

相关契约段（关键词定位 4 条）：
{"endpoint": "/schema/{className}/tenants POST", "kind": "type_constraints", "description": "Tenant.activityStatus on create must be ACTIVE or INACTIVE", "assertion": "body[].activityStatus in {ACTIVE, INACTIVE}", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "/schema/{className}/tenants PUT", "kind": "type_constraints", "description": "Tenant.activityStatus on update must be ACTIVE, INACTIVE, or OFFLOADED", "assertion": "body[].activityStatus in {ACTIVE, INACTIVE, OFFLOADED}", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}
{"endpoint": "/schema/{className}/tenants DELETE", "kind": "state_constraints", "description": "deleting tenants permanently deletes all tenant data", "assertion": "after DELETE tenants, GET tenant returns 404 and its data is gone", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.9}
{"endpoint": "/schema/{className} DELETE", "kind": "state_constraints", "description": "deleting a collection permanently deletes all data objects in the collection", "assertion": "after DELETE /schema/{className}, GET /objects?class={className} returns empty", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "confidence": 0.95}

API 模板：endpoint=/schema/{className}/tenants doc_quote='Update tenants (activityStatus on update: ACTIVE|INACTIVE|OFFLOADED)' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)

--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---
{"constraint_id": "weaviate_type_tenants_create_001", "endpoint": "/schema/{className}/tenants POST", "description": "Tenant.activityStatus on create must be ACTIVE or INACTIVE", "assertion": "body[].activityStatus in {ACTIVE, INACTIVE}", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_tenants_update_001", "endpoint": "/schema/{className}/tenants PUT", "description": "Tenant.activityStatus on update must be ACTIVE, INACTIVE, or OFFLOADED", "assertion": "body[].activityStatus in {ACTIVE, INACTIVE, OFFLOADED}", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_range_schema_replication_001", "endpoint": "/schema POST", "description": "replicationConfig.factor is an integer (default 1)", "assertion": "replicationConfig.factor >= 1", "type": "range_constraint", "confidence": 0.85, "evidence_tier": "inferred_from_example", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_range_replication_scale_001", "endpoint": "/replication/scale GET", "description": "replicationFactor must be at least 1", "assertion": "replicationFactor >= 1", "type": "range_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_schema_create_001", "endpoint": "/schema POST", "description": "class field must be CamelCase", "assertion": "properties.class matches /^[A-Z][a-zA-Z0-9]*$/", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_schema_create_002", "endpoint": "/schema POST", "description": "vectorIndexType must be one of allowed index types", "assertion": "properties.vectorIndexType in {hnsw, flat, dynamic, bwes}", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_schema_create_003", "endpoint": "/schema POST", "description": "properties[].tokenization must be a valid enum value", "assertion": "properties.properties[].tokenization in {word, lowercase, whitespace, field, trigram, gse, kagome_kr, kagome_ja, gse_ch}", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_state_schema_update_001", "endpoint": "/schema/{className} PUT", "description": "PUT does NOT add properties (use POST /schema/{className}/properties) and does NOT rename", "assertion": "PUT /schema/{className} does not change properties count or names", "type": "state_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_objects_create_001", "endpoint": "/objects POST", "description": "id field must be valid UUID format", "assertion": "body.id is null OR matches UUID format", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_objects_create_002", "endpoint": "/objects POST", "description": "vector takes precedence over vectorizer module", "assertion": "if body.vector provided, it overrides vectorizer-generated vector", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_references_add_001", "endpoint": "/objects/{className}/{id}/references/{propertyName} POST", "description": "beacon format must be weaviate://localhost/{uuid}", "assertion": "body.beacon matches /^weaviate:\\/\\/localhost\\/[0-9a-f-]{36}$/", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_batch_references_001", "endpoint": "/batch/references POST", "description": "from beacon format must include className/uuid/propertyName", "assertion": "from matches /^weaviate:\\/\\/localhost\\/{ClassName}\\/{uuid}\\/{propertyName}$/", "type": "type_constraint", "confidence": 0.9, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
{"constraint_id": "weaviate_type_graphql_001", "endpoint": "/graphql POST", "description": "GraphQL is case-sensitive", "assertion": "query string case must match schema exactly", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://weaviate.io/developers/weaviate/api/graphql", "source_status": "reachable"}
{"constraint_id": "weaviate_type_backups_create_001", "endpoint": "/backups/{backend} POST", "description": "backup id must be URL-safe (lowercase, numbers, underscore, minus only)", "assertion": "body.id matches /^[a-z0-9_-]+$/", "type": "type_constraint", "confidence": 0.95, "evidence_tier": "explicit", "source_url": "https://github.com/weaviate/weaviate/blob/v1.38.0/openapi-specs/schema.json", "source_status": "reachable"}
