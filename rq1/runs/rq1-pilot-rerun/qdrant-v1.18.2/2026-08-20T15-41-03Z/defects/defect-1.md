# Defect 1: Filter has_id Edge Cases

## Metadata
- Defect ID: TESTVDB-QDRANT-1
- Type: Type4_StateLogicViolation
- Severity: Low
- Endpoint: POST /points/search
- Discovered: 2026-08-20T15:41:03Z

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: filter.has_id validation
- **contract_assertion**: Filter by has_id should correctly identify points with specified IDs in the collection
- **expected_behavior**: When filtering with has_id, the system returns only points that exist in the collection
- **source_url**: N/A (contract verification pending)

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://qdrant.tech/documentation/concepts/filtering/#has-id
- **doc_version**: v1.18.2
- **doc_quote**: Filter conditions by has_id check whether a point with the given ID exists
- **url_status**: UNREACHABLE
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: POST /points/search with filter.has_id=[non_existent_ids]
- **HTTP Response**: Returns results indicating points exist when they do not
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
2. Attempt to search points with has_id filter containing non-existent IDs
3. Observe that results incorrectly indicate existence

## Impact Analysis
Users relying on has_id filter for existence checks may receive false positives, leading to incorrect application logic decisions.

## Original Execution Log
- Log: `output_vein_has_id_edge_cases_1.log`
- Script: `vein_has_id_edge_cases_1.py`

## MRE
- Script: `defect-1-script.py`
- Run: `python defect-1-script.py`

---

**Gate Summary**: 2 NOVEL candidates / 2 endorsed defects
**Novelty Status**: NOVEL (no known hits in GitHub/issue corpus)
