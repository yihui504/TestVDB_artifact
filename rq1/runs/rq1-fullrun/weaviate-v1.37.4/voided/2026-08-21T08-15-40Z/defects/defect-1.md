# Defect 1: Compound Property Indexing Not Validated Against Schema Constraints

## Metadata
- Defect ID: TESTVDB-weaviate-1
- Type: Type1_IllegalSuccess
- Severity: Medium
- Endpoint: POST /v1/schema
- Discovered: 2026-08-21T08:15:40Z

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: schema_vectorIndexConfig_dynamicEfMin
- **contract_assertion**: Schema creation with vectorIndexConfig should validate dynamicEfMin <= dynamicEfMax
- **expected_behavior**: System should reject schema configurations where dynamicEfMin > dynamicEfMax (inverted range)
- **source_url**: https://weaviate.io/developers/weaviate/config-refs/schema

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://weaviate.io/developers/weaviate/config-refs/schema
- **doc_version**: v1.37.4
- **doc_quote**: N/A (spec lacks requestBody validation constraints)
- **url_status**: verified
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: POST /v1/schema with vectorIndexConfig.dynamicEfMin=250, dynamicEfMax=100 (inverted)
- **HTTP Response**: 200 OK (schema accepted despite invalid range)
- **Container Logs**: Schema creation succeeded without validation error
- **reproduced_at**: 2026-08-21T08:15:40Z

### Ring 4: Source Code Reference (可选)
- **github_url**: N/A
- **code_snippet**: N/A

## Completeness Check
- Ring 1: {PRESENT | MISSING}
- Ring 2: {PRESENT | DEGRADED | UNREACHABLE}
- Ring 3: {PRESENT | MISSING}
- **Overall**: {COMPLETE | INCOMPLETE_EVIDENCE}

## Reproduction Steps
1. Create schema with POST /v1/schema
2. Set vectorIndexConfig.dynamicEfMin=250, dynamicEfMax=100 (invalid: min > max)
3. Observe 200 OK response instead of 400 Bad Request

## Impact Analysis
Invalid index configurations can be persisted, potentially leading to undefined query behavior or runtime failures when the inverted range is accessed during vector searches.

## Original Execution Log
- Log: `output_vein_compound_and_schema_pairing_1.log`
- Script: `vein_compound_and_schema_pairing_1.py`

## MRE
- Script: `defect-1-script.py`
- Run: `python defect-1-script.py`
