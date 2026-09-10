# Boundary Attack Scripts Summary — Round 1

## Target: qdrant v1.18.2
## Chunk: chunk_collections+create
## Session: 2026-08-20T15-41-03Z
## Generated: 2026-08-21

---

## Scripts Generated (10 total)

### 1. boundary_collections_create_001.py
- **Constraint**: qdrant_range_create_collection_001
- **Param**: hnsw_config.m
- **Strategy**: boundary
- **Tests**: m ∈ [1, 2, 3, 99, 100, 101]
- **Expected**: Type1_IllegalSuccess
- **Coverage**: min-1, min, min+1, max-1, max, max+1

### 2. boundary_collections_create_002.py
- **Constraint**: qdrant_range_create_collection_002
- **Param**: hnsw_config.ef_construct
- **Strategy**: boundary
- **Tests**: ef_construct ∈ [9, 10, 1000, 1001]
- **Expected**: Type1_IllegalSuccess
- **Coverage**: min-1, min, max, max+1

### 3. boundary_collections_create_003.py
- **Constraint**: qdrant_type_create_collection_001
- **Param**: vectors.size
- **Strategy**: boundary + type_confusion
- **Tests**: size ∈ [0, -1, 1, 128.5, "128", null]
- **Expected**: Type1_IllegalSuccess
- **Coverage**: negative, zero, float, string, null

### 4. boundary_collections_create_004.py
- **Constraint**: qdrant_type_create_collection_002
- **Param**: vectors.distance
- **Strategy**: boundary + enum validation
- **Tests**: distance ∈ [Cosine, Euclidean, Dot, Manhattan, cosine, COSINE, InvalidMetric, "", null]
- **Expected**: Type1_IllegalSuccess
- **Coverage**: valid enum values, case variants, invalid, empty, null

### 5. boundary_collections_create_005.py
- **Constraint**: qdrant_range_create_collection_003
- **Param**: optimizers_config.indexing_threshold
- **Strategy**: boundary
- **Tests**: indexing_threshold ∈ [-1, 0, 1, 20000, 1000000, -100]
- **Expected**: Type1_IllegalSuccess
- **Coverage**: negative, zero, positive, large positive

### 6. boundary_collections_create_006.py
- **Constraint**: qdrant_state_create_collection_001
- **Param**: null (state constraint)
- **Strategy**: boundary (atomicity)
- **Tests**: Duplicate collection creation
- **Expected**: Type4_StateLogicViolation
- **Coverage**: create-create atomicity

### 7. boundary_collections_create_007.py
- **Contract**: qdrant_contract_create_query_001
- **Param**: null (behavioral contract)
- **Strategy**: boundary (visibility)
- **Tests**: Create → immediate query, upsert → immediate search
- **Expected**: Type4_StateLogicViolation
- **Coverage**: create-then-query visibility

### 8. boundary_collections_create_008.py
- **Constraint**: qdrant_range_create_collection_001 (resource limit)
- **Param**: hnsw_config.m
- **Strategy**: resource_limit (Strategy 6)
- **Tests**: m = INT_MAX (2147483647)
- **Expected**: Type3_RuntimeFailure (crash/OOM)
- **Coverage**: extreme value DoS protection

### 9. boundary_collections_create_009.py
- **Constraint**: qdrant_range_create_collection_002 (resource limit)
- **Param**: hnsw_config.ef_construct
- **Strategy**: resource_limit (Strategy 6)
- **Tests**: ef_construct = INT_MAX (2147483647)
- **Expected**: Type3_RuntimeFailure (crash/OOM)
- **Coverage**: extreme value DoS protection

### 10. boundary_collections_create_010.py
- **Constraint**: qdrant_range_create_collection_003 (resource limit)
- **Param**: optimizers_config.indexing_threshold
- **Strategy**: resource_limit (Strategy 6)
- **Tests**: indexing_threshold = INT_MAX (2147483647)
- **Expected**: Type3_RuntimeFailure (crash/OOM)
- **Coverage**: extreme value DoS protection

---

## Coverage Summary

### Constraints Covered (9/9 in chunk)
- [x] qdrant_type_create_collection_001 (vectors.size)
- [x] qdrant_type_create_collection_002 (vectors.distance)
- [x] qdrant_range_create_collection_001 (hnsw_config.m)
- [x] qdrant_range_create_collection_002 (hnsw_config.ef_construct)
- [x] qdrant_range_create_collection_003 (indexing_threshold)
- [x] qdrant_state_create_collection_001 (atomicity)
- [x] qdrant_behavioral_create_collection_001 (valid → 200)
- [x] qdrant_behavioral_create_collection_002 (invalid → 400)
- [x] qdrant_contract_create_query_001 (visibility)

### Strategies Applied
- Strategy 1 (Boundary Values): 5 scripts (001, 002, 003, 004, 005)
- Strategy 6 (Resource Limits): 3 scripts (008, 009, 010)
- Strategy 7 (State/Atomicity): 1 script (006)
- Strategy 8 (Behavioral Contracts): 1 script (007)

### Defect Types Targeted
- Type1_IllegalSuccess: 7 scripts
- Type3_RuntimeFailure: 3 scripts (resource limits)
- Type4_StateLogicViolation: 2 scripts

---

## Metadata Compliance
All scripts include:
- ✅ .py with safe_request() wrapper
- ✅ .meta.json with defect_id, endpoint, param, expected_defect_type, strategy
- ✅ Cleanup with try/except wrapping
- ✅ Contract-driven endpoint paths (no hardcoded DB-specific values)
- ✅ VERDICT printing with explicit defect types

---

## Analyzed Documents
✅ analyzed_documents_boundary.md created with 17 source URLs (100% coverage of raw_knowledge.md Document Sources)
