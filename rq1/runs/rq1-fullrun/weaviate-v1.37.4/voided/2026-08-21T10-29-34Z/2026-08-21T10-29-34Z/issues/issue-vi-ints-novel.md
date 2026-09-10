# Issue Draft: HNSW vectorIndexConfig 整数参数校验不对称（ef=0/-5、vectorCacheMaxObjects/cleanupIntervalSeconds/pq.centroids=-1 被静默持久化）

> ⛔ 本地草稿 — 未提交 GitHub。由 TestVDB 会话 weaviate-v1.37.4-2026-08-21T10-29-34Z 的 Novelty Gate 唯一 NOVEL 缺陷生成（gate_grade=NOVEL，endorsement=true，"No known hits"）。
> 提交前需人工复核（双确认口径：injector param 匹配 + 人工 LLM 盲评）。

---

**Title**: Inconsistent validation of HNSW `vectorIndexConfig` int params: `ef=0/-5`, `vectorCacheMaxObjects=-1`, `cleanupIntervalSeconds=-1`, `pq.centroids=-1` silently accepted and persisted (HTTP 200), while `maxConnections`/`efConstruction` are rejected (422) on the same config object

**Labels**: bug, schema, vector-index, hnsw, validation

## Environment
- Weaviate: v1.37.4（单机，默认配置）
- API: REST `POST /schema` / `GET /schema/{className}`
- SDK: weaviate-client v1.37.4

## Summary

Sending a collection definition with invalid integer values inside `vectorIndexConfig` returns HTTP 200, echoes the invalid value in the response, and persists it (confirmed via GET read-back). The same request structure with different parameters (`maxConnections=-1`, `efConstruction=-5`) is rejected with HTTP 422 `invalid hnsw config: ...` on the same config object. Validation is therefore inconsistent across fields of the same object.

Notably `ef=0` / `ef=-5` are persisted even though `ef` is the active HNSW search-time parameter whose only documented sentinel is `-1` ("let Weaviate pick").

## Steps to Reproduce

```bash
# Candidate — silently accepted (HTTP 200, persisted)
curl -s -X POST http://localhost:8080/v1/schema \
  -H 'Content-Type: application/json' \
  -d '{"class":"ReproEfNeg5","vectorIndexConfig":{"ef":-5}}'
# -> 200, response echoes "ef": -5
curl -s http://localhost:8080/v1/schema/ReproEfNeg5 | grep -A2 '"ef"'
# -> "ef": -5  (persisted)

# Same for ef=0, vectorCacheMaxObjects=-1, cleanupIntervalSeconds=-1, pq.centroids=-1
# -> all HTTP 200 and persisted

# Control — rejected with 422
curl -s -X POST http://localhost:8080/v1/schema \
  -H 'Content-Type: application/json' \
  -d '{"class":"ReproCtl","vectorIndexConfig":{"maxConnections":-1}}'
# -> 422: {"error":[{"message":"class.VectorIndexConfig can not parse: parse vector index config: invalid hnsw config: maxConnections..."}]}

curl -s -X POST http://localhost:8080/v1/schema \
  -H 'Content-Type: application/json' \
  -d '{"class":"ReproCtl2","vectorIndexConfig":{"efConstruction":-5}}'
# -> 422: {"error":[{"message":"... invalid hnsw config: efConstruction ..."}]}
```

## Expected Behavior

Invalid integer values (non-sentinel negatives and `0` for `ef`) should be rejected with 422 at config-parse time — consistently with `maxConnections` and `efConstruction` on the same `vectorIndexConfig` object — and must not be persisted to the schema.

## Actual Behavior

| Field | Value | POST | Persisted |
|-------|-------|------|-----------|
| `ef` | -5 | 200 | yes (read-back -5) |
| `ef` | 0 | 200 | yes (read-back 0) |
| `vectorCacheMaxObjects` | -1 | 200 | yes (read-back -1) |
| `cleanupIntervalSeconds` | -1 | 200 | yes (read-back -1) |
| `pq.centroids` | -1 | 200 | yes (read-back -1) |
| `maxConnections` (control) | -1 | **422** | no |
| `efConstruction` (control) | -5 | **422** | no |

## Impact

- `ef=0`/`ef=-5` are persisted silently and take effect at search time — HNSW search with an invalid ef produces degenerate/empty recall with no configuration-time error.
- `cleanupIntervalSeconds=-1` and `vectorCacheMaxObjects=-1` persist invalid maintenance semantics undetectable via API.
- `pq.centroids=-1` can corrupt PQ-enabled index builds; the invalid state is fixed in the schema and propagates to replicas.
- Users cannot infer legal input domains from API behavior: contract exposes no ranges, and validation applies to some fields but not others.

## Suggested Fix

Extend the existing `parse vector index config` validation (the path that already rejects invalid `maxConnections`/`efConstruction`) to cover `ef` (allow only sentinel `-1` or `>= 1`), `vectorCacheMaxObjects`, `cleanupIntervalSeconds`, and `pq.centroids`, mirroring the same 422 error format.

## Notes

- TestVDB Novelty Gate: NOVEL (no known hits; no upstream issue/PR/commit found).
- Evidence: `output_vein_range_filter_schema_vi_ints_1.log` (VERDICT: DEFECT_FOUND Type1_IllegalSuccess).
- Source reference: `entities/vectorindex/hnsw/config.go` — `DefaultEF = -1 // indicates "let Weaviate pick"`.
