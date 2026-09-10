# Issue Draft: hnsw_config.ef_construct Parameter Validation Missing

**Status**: Novel Defect
**Defect ID**: TESTVDB-QDRANT-002
**Grade**: NOVEL (Novelty Gate: HIGH confidence, no known hits)
**Target**: qdrant v1.18.2
**Endpoint**: PUT /collections/{name}

---

## Summary

The Qdrant REST API for creating collections fails to validate that the hnsw_config.ef_construct parameter (index construction precision) falls within the documented valid range of [1, 1000]. The API accepts invalid values (e.g., ef_construct=1, ef_construct=10000) and returns HTTP 200 OK with success status, violating the contract assertion.

## Expected Behavior

Per the API documentation contract:
```
hnsw_config.ef_construct ∈ [1, 1000]
```

**Expected HTTP Response for Invalid Values:**
- Status: 400 Bad Request or 422 Unprocessable Entity
- Body: Validation error explaining that ef_construct must be in [1, 1000]

## Actual Behavior

**Observed for multiple invalid values:**

1. Lower Bound Violation (ef_construct=1):
   - Request: PUT /collections with hnsw_config.ef_construct=1
   - Response: HTTP 200 OK
   - Expected: HTTP 400/422

2. Upper Bound Violation (ef_construct=10000):
   - Request: PUT /collections with hnsw_config.ef_construct=10000
   - Response: HTTP 200 OK
   - Expected: HTTP 400/422

## Evidence Chain

- **Contract Assertion**: hnsw_config.ef_construct ∈ [1, 1000]
- **Documentation**: API reference explicitly states valid range
- **Observed Behavior**: API accepts values outside [1, 1000] with HTTP 200
- **HTTP Semantics**: Parameter validation errors should return 4xx

## Impact

- **User Impact**: Invalid HNSW configuration accepted silently may lead to degraded recall during search operations
- **Data Integrity**: Collections created with extreme ef_construct values may fail in production workloads
- **System Stability**: Poor index build quality could affect performance

## Reproduction

```bash
# Test lower bound
curl -X PUT "http://localhost:6333/collections/test_ef_invalid" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {"size": 128, "distance": "Cosine"},
    "hnsw_config": {"ef_construct": 1}
  }'

# Test upper bound
curl -X PUT "http://localhost:6333/collections/test_ef_invalid2" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {"size": 128, "distance": "Cosine"},
    "hnsw_config": {"ef_construct": 10000}
  }'
```

## Related Test Scripts

- boundary_collections_create_007.py (ef_construct=1)
- boundary_collections_create_008.py (ef_construct=10000)

## Novely Gate Verification

- **Grade**: NOVEL
- **Confidence**: HIGH
- **Match Type**: no_known_hits
- **Reason**: No matching issues found in GitHub corpus
