# State Attack Scripts — Round 3 (chunk_points+search)

## Coverage Summary

**Target Endpoint:** points+search
**Block Constraints:** qdrant_behavioral_search_points_001, qdrant_behavioral_search_points_002
**Related State Constraints:** qdrant_state_search_points_001, qdrant_invariant_search_visibility_001, qdrant_invariant_delete_invisibility_001

## Generated Scripts (6)

### state_points_search_01
- **Strategy:** count_consistency
- **Test:** CRUD after upsert — verify search results match upserted point count
- **Constraint IDs:** qdrant_state_search_points_001, qdrant_invariant_search_visibility_001
- **Defect Type:** Type4_StateLogicViolation
- **Description:** Insert 50 points in batches, verify search returns all points

### state_points_search_02
- **Strategy:** delete_consistency
- **Test:** DELETE points → verify search invisibility
- **Constraint IDs:** qdrant_invariant_delete_invisibility_001, qdrant_behavioral_delete_visibility_001
- **Defect Type:** Type4_StateLogicViolation
- **Description:** Delete even IDs, verify deleted points not searchable, kept points searchable

### state_points_search_03
- **Strategy:** concurrent
- **Test:** Concurrent upsert+search — verify state consistency
- **Constraint IDs:** qdrant_state_search_points_001, qdrant_state_upsert_points_001
- **Defect Type:** Type4_StateLogicViolation
- **Description:** 20 threads concurrent upsert/search, verify final count matches expected

### state_points_search_04
- **Strategy:** count_consistency
- **Test:** Empty collection search — verify returns empty array
- **Constraint IDs:** qdrant_behavioral_search_points_002
- **Defect Type:** Type4_StateLogicViolation
- **Description:** Search empty collection, verify 200 OK with empty result array

### state_points_search_05
- **Strategy:** concurrent
- **Test:** Concurrent delete+search — verify deleted points invisible
- **Constraint IDs:** qdrant_invariant_delete_invisibility_001, qdrant_state_upsert_points_001
- **Defect Type:** Type4_StateLogicViolation
- **Description:** 20 threads concurrent delete/search, verify deleted points never visible

### state_points_search_06
- **Strategy:** upsert_idempotence
- **Test:** Upsert idempotence — verify duplicate upserts handled correctly
- **Constraint IDs:** qdrant_state_upsert_points_001, qdrant_behavioral_upsert_points_001
- **Defect Type:** Type4_StateLogicViolation
- **Description:** Upsert same IDs twice, verify count unchanged and data updated

## Contract Grounding

All scripts grounded in structured_contract.json:
- Source URLs: https://api.qdrant.tech/api-reference/points/search-points
- Doc Version: 1.19.x
- All endpoint paths from contract.api_endpoints
- All constraint_ids from contract.constraints + contract.assertions

## Testing Directions Covered

1. **Count Consistency:** Search results match upserted point count
2. **Delete Invisibility:** Deleted points not returned in search
3. **Concurrent State:** Concurrent operations maintain consistency
4. **Empty Collection Behavior:** Search on empty collection returns empty array
5. **Idempotence:** Duplicate upserts don't create duplicate points

## Blindspot Coverage

- **BS-03 (Concurrency Blindness):** Scripts 03, 05 test concurrent operation scenarios
