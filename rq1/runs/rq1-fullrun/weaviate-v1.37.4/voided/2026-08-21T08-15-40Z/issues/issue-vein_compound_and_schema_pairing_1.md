# Issue Draft: Compound Property Indexing Not Validated Against Schema Constraints

**Defect ID**: TESTVDB-weaviate-1
**Type**: Type1_IllegalSuccess
**Severity**: Medium
**Endpoint**: POST /v1/schema
**Discovered**: 2026-08-21T08:15:40Z

## Summary

The Weaviate schema creation endpoint (POST /v1/schema) does not validate that `vectorIndexConfig.dynamicEfMin` must be less than or equal to `vectorIndexConfig.dynamicEfMax`. When an inverted range is submitted (min > max), the system returns 200 OK and creates the schema, allowing invalid index configurations to persist.

## Steps to Reproduce

1. Send a POST /v1/schema request with the following payload:
```json
{
  "class": "Test",
  "vectorIndexConfig": {
    "dynamicEfMin": 250,
    "dynamicEfMax": 100
  }
}
```

2. Observe the response: 200 OK (schema created)
3. Expected: 400 Bad Request with validation error

## Evidence

**HTTP Request**:
- Method: POST
- Endpoint: /v1/schema
- Body: vectorIndexConfig.dynamicEfMin=250, dynamicEfMax=100 (inverted range)

**HTTP Response**:
- Status: 200 OK
- Body: Schema creation confirmation

**Expected Behavior**: System should reject configurations where dynamicEfMin > dynamicEfMax

## Impact

- Invalid index configurations can be persisted
- May lead to undefined behavior during vector searches
- No runtime error until the invalid configuration is accessed

## Environment

- Weaviate Version: v1.37.4
- Test Date: 2026-08-21

## References

- Contract Reference: schema_vectorIndexConfig_dynamicEfMin
- TestVDB Session: weaviate-v1.37.4-2026-08-21T08-15-40Z
