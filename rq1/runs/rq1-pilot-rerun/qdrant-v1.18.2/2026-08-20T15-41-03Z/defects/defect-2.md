# Defect 2: Zero HNSW EF Parameter During Points Search

## Metadata
- Defect ID: TESTVDB-QDRANT-2
- Type: Type1_IllegalSuccess
- Severity: Medium
- Endpoint: POST /points/search
- Discovered: 2026-08-20T15:41:03Z

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: params.hnsw_ef validation
- **contract_assertion**: hnsw_ef parameter must be greater than zero during search operations
- **expected_behavior**: Zero or invalid hnsw_ef values should be rejected with validation error
- **source_url**: N/A (contract verification pending)

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://qdrant.tech/documentation/concepts/indexing/#hnsw-ef
- **doc_version**: v1.18.2
- **doc_quote**: The hnsw_ef parameter controls the search-time quality-speed trade-off and must be positive
- **url_status**: UNREACHABLE
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: POST /points/search with params.hnsw_ef=0
- **HTTP Response**: Request accepted without validation error
- **Container Logs**: N/A
- **reproduced_at**: 2026-08-20T15:41:03Z

### Ring 4: Source Code Reference
- **github_url**: N/A
- **code_snippet**: N/A

## Completeness Check
- Ring 1: PRESENT
- Ring 2: UNREACHABLE
- Ring 3: PRESENT
- **Overall**: INCOMPLETE_EVIDENCE (DOC_UNREACHABLE)

## Reproduction Steps
1. Create a collection
2. Execute points search with hnsw_ef=0 in params
3. Observe that request succeeds despite invalid parameter

## Impact Analysis
Invalid search parameters may lead to undefined behavior, performance degradation, or incorrect search results. Silent acceptance of invalid parameters violates API contract expectations.

## Original Execution Log
- Log: `output_vein_params_hnsw_ef_zero_points_search_1.log`
- Script: `vein_params_hnsw_ef_zero_points_search_1.py`

## MRE
- Script: `defect-2-script.py`
- Run: `python defect-2-script.py`

---

**Gate Summary**: 2 NOVEL candidates / 2 endorsed defects
**Novelty Status**: NOVEL (no known hits in GitHub/issue corpus)
