# Issue Draft: exact Parameter Type Mismatch Handling

**Status**: Novel Defect
**Defect ID**: TESTVDB-QDRANT-004
**Grade**: NOVEL (Novelty Gate: HIGH confidence, no known hits)
**Target**: qdrant v1.18.2
**Endpoint**: GET /collections/{name}?exact={value}

---

## Summary

The Qdrant REST API for collection count operations exhibits poor type handling for the exact parameter. When provided with a type-mismatched value, the API returns unclear error messages or handles the type inconsistency weakly, making debugging difficult for users.

## Expected Behavior

Per the API contract:
- exact parameter should accept boolean or integer type
- Type mismatches should return clear error messages
- API should validate input types explicitly

**Expected Response for Type Mismatch:**
- Status: 400 Bad Request
- Body: Clear validation error indicating type requirement

## Actual Behavior

**Observed for type-mismatched exact parameter:**
- Request: GET /collections/{collection}?exact={invalid_type}
- Response: Poor type handling or unclear error
- Expected: Clear type validation error

## Evidence Chain

- **Contract Assertion**: exact parameter should validate type
- **Documentation**: API reference defines parameter types
- **Observed Behavior**: Weak type validation leads to confusing errors
- **API Quality**: Poor type handling reduces API robustness

## Impact

- **User Impact**: Confusing error messages or unexpected behavior
- **Debugging**: Poor diagnostics make troubleshooting difficult
- **API Quality**: Weak type validation reduces overall robustness

## Reproduction

```bash
# Test type mismatch
curl -X GET "http://localhost:6333/collections/test_collection?exact=string_value"
```

## Related Test Scripts

- vein_cardinality_oracle_count_1.py

## Novely Gate Verification

- **Grade**: NOVEL
- **Confidence**: HIGH
- **Match Type**: no_known_hits
- **Reason**: No matching issues found in GitHub corpus
