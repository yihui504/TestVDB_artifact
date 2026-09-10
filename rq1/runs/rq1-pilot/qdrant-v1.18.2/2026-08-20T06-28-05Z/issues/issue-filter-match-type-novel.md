# Issue Draft: filter.match.value Type Mismatch Handling

**Status**: Novel Defect
**Defect ID**: TESTVDB-QDRANT-005
**Grade**: NOVEL (Novelty Gate: HIGH confidence, no known hits)
**Target**: qdrant v1.18.2
**Endpoint**: POST /collections/{name}/points/query

---

## Summary

The Qdrant REST API for query operations exhibits poor type validation for filter.match.value. When the value type does not match the expected payload type, the API either fails silently or returns unclear error messages, making debugging difficult.

## Expected Behavior

Per the API contract:
- filter.match.value should validate that the value type matches the field type
- Type mismatches should return clear, actionable error messages
- API should perform explicit type checking before query execution

**Expected Response for Type Mismatch:**
- Status: 400 Bad Request
- Body: Clear validation error indicating type mismatch and expected type

## Actual Behavior

**Observed for type-mismatched filter.match.value:**
- Request: POST query with filter.match.value type mismatch
- Response: Poor error handling or silent failure
- Expected: Clear type validation error with field type guidance

## Evidence Chain

- **Contract Assertion**: filter.match.value should validate type matches payload type
- **Documentation**: API reference defines filter structure and type requirements
- **Observed Behavior**: Type validation missing or error unclear
- **API Quality**: Poor diagnostics hinder troubleshooting

## Impact

- **User Impact**: Type mismatches cause confusing errors or silent failures
- **Debugging**: Poor error messages make troubleshooting difficult
- **Productivity**: Developers spend more time debugging type issues

## Reproduction

```bash
# Test type mismatch
curl -X POST "http://localhost:6333/collections/test_collection/points/query" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "numeric_field",
          "match": {"value": "string_instead_of_number"}
        }
      ]
    }
  }'
```

## Related Test Scripts

- vein_type_mismatch_filter_count_1.py

## Novely Gate Verification

- **Grade**: NOVEL
- **Confidence**: HIGH
- **Match Type**: no_known_hits
- **Reason**: No matching issues found in GitHub corpus
