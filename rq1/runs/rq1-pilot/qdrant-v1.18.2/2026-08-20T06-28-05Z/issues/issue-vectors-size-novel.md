# Issue Draft: vectors.size Parameter Validation Missing

**Status**: Novel Defect
**Defect ID**: TESTVDB-QDRANT-003
**Grade**: NOVEL (Novelty Gate: HIGH confidence, no known hits)
**Target**: qdrant v1.18.2
**Endpoint**: PUT /collections/{name}

---

## Summary

The Qdrant REST API for creating collections fails to validate that the vectors.size parameter falls within the documented valid range of [1, 65535]. The API accepts invalid vector size configurations and returns HTTP 200 OK, potentially leading to runtime failures or index corruption.

## Expected Behavior

Per the API documentation contract:
```
vectors.size ∈ [1, 65535]
```

**Expected HTTP Response for Invalid Values:**
- Status: 400 Bad Request or 422 Unprocessable Entity
- Body: Validation error explaining that size must be in [1, 65535]

## Actual Behavior

**Observed for invalid values:**
- Request: PUT /collections with invalid vectors.size (e.g., negative, zero, or >65535)
- Response: HTTP 200 OK accepting invalid configuration
- Expected: HTTP 400/422

## Evidence Chain

- **Contract Assertion**: vectors.size ∈ [1, 65535]
- **Documentation**: API reference states valid range
- **Observed Behavior**: API accepts invalid sizes with HTTP 200
- **HTTP Semantics**: Parameter validation errors should return 4xx

## Impact

- **User Impact**: Invalid vector sizes may cause memory allocation errors or index corruption
- **System Stability**: Collections created with invalid sizes may crash the service
- **Data Loss**: Runtime failures during insert/search operations

## Reproduction

```bash
# Test invalid vector size
curl -X PUT "http://localhost:6333/collections/test_size_invalid" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {"size": 0, "distance": "Cosine"}
  }'
```

## Related Test Scripts

- state_collections_create_05.py

## Novely Gate Verification

- **Grade**: NOVEL
- **Confidence**: HIGH
- **Match Type**: no_known_hits
- **Reason**: No matching issues found in GitHub corpus
