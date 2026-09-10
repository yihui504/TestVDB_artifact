# Analyzed Documents — semantic (milvus v2.6.10)

## Scripts produced (9)

| script_id | strategy | endpoint | param | expected defect |
|---|---|---|---|---|
| semantic_dualenvelope_01 | behavioral_contract | entities+search | consistencyLevel | Type4 (envelope) |
| semantic_visibility_02 | behavioral_contract | entities+search | consistencyLevel | Type4 (visibility) |
| semantic_loadcycle_03 | behavioral_contract | collections+load | null | Type4 (state machine) |
| semantic_filterdiag_04 | diagnosis_quality | entities+delete | filter | Type2 |
| semantic_radius_05 | search_correctness | entities+search | radius | Type4 |
| semantic_efrecall_06 | search_correctness | entities+search | ef | Type4 / Type1 |
| semantic_hybridrrf_07 | metamorphic | entities+hybrid_search | rerank | Type4 / Type1 |
| semantic_limitdefault_08 | illegal_rejection | entities+search | limit | Type1_IllegalSuccess |
| semantic_grouping_09 | search_correctness | entities+search | groupingField | Type4 |

Coverage of the 5 behavioral_contracts:
- milvus_bc_envelope_v2_001 + milvus_bc_envelope_v1_002 -> semantic_dualenvelope_01
- milvus_bc_crud_visibility_001 + milvus_bc_delete_invisibility_001 -> semantic_visibility_02 (+ create/describe used in every setup)
- milvus_bc_load_release_001 -> semantic_loadcycle_03

Constraints covered: milvus_type_entities_search_001 (enum), milvus_type_entities_delete_001 (filter), milvus_range_entities_search_001/002 (limit), searchParams.ef (verified param).

## R2 scripts produced (6) — data-integrity semantics + R1 dropped-test backfill

| script_id | strategy | endpoint | param | verdict |
|---|---|---|---|---|
| semantic_r2_outputfields_01 | behavioral_contract | entities+query | outputFields | NO_DEFECT (invalid outputField silently dropped, code 0 — permissive note) |
| semantic_r2_nprobe_02 | type_coercion | entities+search | nprobe | DEFECT_FOUND Type1 — string nprobe='4' silently accepted (searchParams passthrough) |
| semantic_r2_dyntype_03 | filter_semantics | entities+query | filter | NO_DEFECT (mixed-type dynamic field: numeric/string filters correctly partitioned) |
| semantic_r2_grouping_04 | search_correctness | entities+search | groupSize | NO_DEFECT (strictGroupSize exact; non-strict under-fill EVIDENCE logged) |
| semantic_r2_radiusband_05 | search_correctness | entities+search | radius | NO_DEFECT (band/monotonicity correct; inverted band -> 65535 assert error w/ message) |
| semantic_r2_getvsquery_06 | metamorphic | entities+get | outputFields | NO_DEFECT (get/query/search readback identical incl. dynamic fields) |

## Analyzed Documents — semantic
- .milvus-src-2610/internal/distributed/proxy/httpserver/handler.go
- .milvus-src-2610/internal/distributed/proxy/httpserver/handler_v1.go
- .milvus-src-2610/internal/distributed/proxy/httpserver/handler_v2.go
- .milvus-src-2610/internal/distributed/proxy/httpserver/request_v2.go
- .milvus-src-2610/internal/distributed/proxy/httpserver/constant.go
- .milvus-src-2610/internal/distributed/proxy/httpserver/wrapper.go
- .milvus-src-2610/pkg/util/merr/errors.go
- .milvus-src-2610/pkg/util/merr/utils.go
- .milvus-src-2610/internal/distributed/proxy/service.go
- .milvus-src-2610/pkg/util/paramtable/component_param.go
- .milvus-src-2610/pkg/util/paramtable/quota_param.go
- .milvus-src-2610/internal/proxy/util.go
- live instance http://localhost:19530
