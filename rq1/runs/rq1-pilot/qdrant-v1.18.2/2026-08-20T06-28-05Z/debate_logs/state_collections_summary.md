# State Attack Scripts Summary — chunk_collections+create

## Generated Scripts: 10

### Coverage Map

| Script | Strategy | Constraint Coverage | Test Focus |
|--------|----------|---------------------|------------|
| state_collections_create_01 | atomic_creation | qdrant_behavioral_create_collection_001, qdrant_behavioral_create_collection_002 | Create atomicity & repeat create behavior |
| state_collections_create_02 | concurrent_create | qdrant_state_create_collection_001 | Concurrent create race conditions |
| state_collections_create_03 | lifecycle_concurrent_access | qdrant_behavioral_create_visibility_001, qdrant_invariant_create_query_001 | Lifecycle concurrent access (create/delete) |
| state_collections_create_04 | create_persistence | qdrant_behavioral_create_visibility_001, qdrant_invariant_create_query_001 | State persistence & eventual consistency |
| state_collections_create_05 | create_boundary_values | qdrant_type_create_collection_001, qdrant_type_create_collection_002, qdrant_range_create_collection_001, qdrant_range_create_collection_002 | Boundary validation (size, distance, HNSW params) |
| state_collections_create_06 | multi_config_create | qdrant_behavioral_create_visibility_001, qdrant_invariant_create_query_001 | Multi-config consistency (4 metrics × 5 sizes) |
| state_collections_create_07 | high_concurrency_create | qdrant_state_create_collection_001 | High concurrency stress (20 threads) |
| state_collections_create_08 | rapid_lifecycle_cycles | qdrant_behavioral_create_visibility_001, qdrant_behavioral_delete_invisibility_001 | Rapid lifecycle pressure (3 cycles × 30 iterations) |
| state_collections_create_09 | create_special_names | qdrant_type_create_collection_001, qdrant_behavioral_create_visibility_001 | Name validation (special chars, empty, spaces) |
| state_collections_create_10 | create_config_combos | qdrant_range_create_collection_001, qdrant_range_create_collection_002 | Config interaction (HNSW × optimizer × on_disk) |

### Strategy Distribution

- **Strategy 1 (CRUD COUNT)**: 4 scripts (04, 05, 06, 10) - Config validation & persistence
- **Strategy 2 (DELETE consistency)**: 1 script (01) - Adapted for CREATE
- **Strategy 4 (Concurrency)**: 2 scripts (02, 07) - Concurrent operations
- **Strategy 7 (Lifecycle)**: 2 scripts (03, 08) - Lifecycle concurrent access
- **State persistence**: 1 script (09) - Special name handling

### Parameter Coverage

| Parameter | Test Coverage |
|-----------|---------------|
| collection_name | Special chars, empty, spaces, validation |
| vectors.size | 0, 1, 128, 65536, -1 |
| vectors.distance | Cosine, Euclidean, Dot, Manhattan, Unknown |
| hnsw_config.m | 1-2 (min), 16 (default), 100 (max), 101 (above max) |
| hnsw_config.ef_construct | 9 (below min), 10 (min), 100 (default), 1000 (max), 1001 (above max) |
| optimizers_config.indexing_threshold | 0, 20000, 100000 |
| on_disk | true, false |

### Blindspot Annotations

All scripts annotated with:
- **BS-03 (Concurrency Blindness)**: State visibility under concurrent operations

### Constraint Coverage from chunks.json

**Chunk: chunk_collections+create** (3 units covered)

1. ✅ assertions::qdrant_behavioral_create_collection_001 - Valid config → 200 OK
2. ✅ assertions::qdrant_behavioral_create_collection_002 - Existing collection → 400 Bad Request
3. ✅ behavioral_contracts::qdrant_behavioral_create_visibility_001 - Create → visible in get+list

### Testing Dimensions

- **Atomicity**: 01 (repeat create), 02 (concurrent create)
- **Visibility**: 01, 03, 04, 06, 09 (get+list after create)
- **Persistence**: 04 (immediate & delayed), 06 (config persistence)
- **Concurrency**: 02, 03, 07, 08 (various concurrency patterns)
- **Validation**: 05 (boundary), 09 (name validation), 10 (config combos)
- **Resource**: 08 (rapid lifecycle), 07 (high concurrency)

### Expected Defect Types

- **Type4_StateLogicViolation**: 8 scripts (state inconsistency)
- **Type3_RuntimeFailure**: 2 scripts (concurrency crashes)

### Files Generated

- Python scripts: 10 (state_collections_create_01.py to state_collections_create_10.py)
- Metadata JSON: 10 (state_collections_create_01.meta.json to state_collections_create_10.meta.json)
- Documentation: analyzed_documents_state.md (17 source URLs, ≥ 60% coverage)
- Summary: This file

### Compliance Checklist

- ✅ All scripts use safe_request() wrapper
- ✅ All scripts have VERDICT output lines
- ✅ All cleanup wrapped in try/except
- ✅ All scripts target qdrant v1.18.2 REST API
- ✅ No hardcoded ports/URLs (BASE_URL from env)
- ✅ Response keys extracted dynamically from body
- ✅ All scripts annotated with Blindspot BS-03
- ✅ Metadata JSON files include param/endpoint/strategy
- ✅ Document coverage ≥ 60% (17/17 URLs)

### Testing Quality Indicators

- **Total test assertions**: ~150+ individual checks across all scripts
- **Concurrency scenarios**: 4 distinct patterns
- **Boundary conditions**: 25+ parameter combos
- **Config combinations**: 5 × 3 × 2 = 30 HNSW × optimizer × on_disk tests
- **Special cases**: Empty names, spaces, special chars, extreme values

---

Generated: 2026-08-20
Agent: testvdb:attack-state
Target: qdrant v1.18.2
Chunk: chunk_collections+create
Session: qdrant-v1.18.2-2026-08-20T06-28-05Z
