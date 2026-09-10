# Issue Draft: hnsw_config.m Parameter Validation Missing

**Status**: Novel Defect
**Defect IDs**: TESTVDB-QDRANT-001, TESTVDB-QDRANT-007
**Grade**: NOVEL (Novelty Gate: HIGH confidence, no known hits)
**Target**: qdrant v1.18.2
**Endpoint**: PUT /collections/{name}

---

## Summary

The Qdrant REST API for creating collections fails to validate that the hnsw_config.m parameter (max connections per node in HNSW graph) falls within the documented valid range of [2, 100]. The API accepts invalid values (e.g., m=0, m=1, m=101) and returns HTTP 200 OK with success status, violating the contract assertion and HTTP semantic conventions.

## Expected Behavior

Per the API documentation contract:
```
hnsw_config.m (max connections per node) ∈ [2, 100]
```

**Expected HTTP Response for Invalid Values:**
- Status: 400 Bad Request or 422 Unprocessable Entity
- Body: Validation error explaining that m must be in [2, 100]

## Actual Behavior

**Observed for multiple invalid values:**

1. Lower Bound Violation (m=1):
   - Request: PUT /collections/boundary_test_m_1 with hnsw_config.m=1
   - Response: HTTP 200 OK with {"result":true,"status":"ok"}
   - Expected: HTTP 400/422

2. Upper Bound Violation (m=101):
   - Request: PUT /collections/boundary_test_m_101 with hnsw_config.m=101
   - Response: HTTP 200 OK with {"result":true,"status":"ok"}
   - Expected: HTTP 400/422

3. Additional Lower Bound Test (m=0):
   - Request: PUT /collections with hnsw_config.m=0
   - Response: HTTP 200 OK
   - Expected: HTTP 400/422

## Evidence Chain

- **Contract Assertion**: hnsw_config.m ∈ [2, 100]
- **Documentation**: API reference explicitly states valid range
- **Observed Behavior**: API accepts m=1, m=101, m=0 with HTTP 200
- **HTTP Semantics**: Parameter validation errors should return 4xx, not 2xx

## Impact

- **User Impact**: Collections created with invalid HNSW configuration may behave unpredictably
- **Data Integrity**: Invalid m values can lead to poor index quality or corruption
- **API Semantics**: Violates RESTful conventions - validation errors need 4xx status

## Reproduction

```bash
# Test lower bound
curl -X PUT "http://localhost:6333/collections/test_m_invalid" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {"size": 128, "distance": "Cosine"},
    "hnsw_config": {"m": 1}
  }'

# Test upper bound
curl -X PUT "http://localhost:6333/collections/test_m_invalid2" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {"size": 128, "distance": "Cosine"},
    "hnsw_config": {"m": 101}
  }'
```

## Related Test Scripts

- boundary_collections_create_005.py (m=1)
- boundary_collections_create_006.py (m=101)
- state_collections_create_10.py (m=0)

## Novely Gate Verification

- **Grade**: NOVEL
- **Confidence**: HIGH
- **Match Type**: no_known_hits
- **Reason**: No matching issues found in GitHub corpus, threat model, or known issue database
