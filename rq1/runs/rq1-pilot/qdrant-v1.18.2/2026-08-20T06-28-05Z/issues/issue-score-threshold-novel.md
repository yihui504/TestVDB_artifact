# Issue Draft: score_threshold Parameter Validation Missing

**Status**: Novel Defect
**Defect ID**: TESTVDB-QDRANT-006
**Grade**: NOVEL (Novelty Gate: HIGH confidence, no known hits)
**Target**: qdrant v1.18.2
**Endpoint**: POST /collections/{name}/points/search

---

## Summary

The Qdrant REST API for search operations fails to validate that the score_threshold parameter falls within the valid range of [0, 1] for cosine similarity (and other distance metrics). The API accepts invalid threshold values and returns HTTP 200 OK, potentially causing all results to be filtered out or unexpected search behavior.

## Expected Behavior

Per the API documentation contract:
```
score_threshold ∈ [0, 1] (for cosine similarity)
```

**Expected HTTP Response for Invalid Values:**
- Status: 400 Bad Request or 422 Unprocessable Entity
- Body: Validation error explaining threshold range for selected distance metric

## Actual Behavior

**Observed for invalid score_threshold values:**

1. Lower Bound Violation (score_threshold < 0):
   - Request: POST search with score_threshold=-0.5
   - Response: HTTP 200 OK accepting invalid value
   - Expected: HTTP 400/422

2. Upper Bound Violation (score_threshold > 1):
   - Request: POST search with score_threshold=1.5
   - Response: HTTP 200 OK accepting invalid value
   - Expected: HTTP 400/422

## Evidence Chain

- **Contract Assertion**: score_threshold ∈ [0, 1]
- **Documentation**: API reference states valid threshold range
- **Observed Behavior**: API accepts values outside [0, 1] with HTTP 200
- **HTTP Semantics**: Parameter validation errors should return 4xx

## Impact

- **User Impact**: Invalid thresholds accepted silently may cause all results to be filtered out unexpectedly
- **Search Quality**: Unexpected behavior when threshold is outside valid range
- **User Experience**: Confusing results when valid data exists but threshold invalid

## Reproduction

```bash
# Test lower bound
curl -X POST "http://localhost:6333/collections/test_collection/points/search" \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, 0.3],
    "score_threshold": -0.5
  }'

# Test upper bound
curl -X POST "http://localhost:6333/collections/test_collection/points/search" \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, 0.3],
    "score_threshold": 1.5
  }'
```

## Related Test Scripts

- boundary_points_search_004.py
- boundary_points_search_005.py
- semantic_points_search_011.py

## Novely Gate Verification

- **Grade**: NOVEL
- **Confidence**: HIGH
- **Match Type**: no_known_hits
- **Reason**: No matching issues found in GitHub corpus
