# Defect 3: params 载体同样绕过 query_mode 枚举闭集校验（code 0 接受 'bogus'）

## Metadata
- Defect ID: TESTVDB-MILVUS-3 (boundary_querymode_03)
- Type: Type1_IllegalSuccess
- Param: query_mode（params 载体）
- Novelty: NOVEL (match_type: no_known_hits, confidence HIGH, endorsement true)
- Endpoint: POST /v2/vectordb/collections/create
- Discovered: 2026-08-21T23-37-54Z session (fullrun#11)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/collections/create" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"bnd_qm_03","schema":{...},"params":{"query_mode":"bogus"}}'
```

## Expected vs Actual
- Expected（契约 create_009，断言明确覆盖 `properties/params.query_mode` 双载体）: 非枚举值 => code 65535
- Actual: `HTTP 200 {"code":0,"data":{}}`；CONTROL（state_query_mode_alter_1 D 行）同值 alter 路径返回 65535

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_type_collections_create_009（断言域名文覆盖 params 载体，violates=true）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（common.go:513-526 ValidateQueryMode + task.go:449，本地 clone v2.6.16 全 PASS）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: boundary_scripts/boundary_querymode_03.py（多脚本稳定触发：boundary_querymode_03 / boundary_querymode_01 / vein_query_mode_maturity_1；双载体同型 code 0）
- Log: output_boundary_querymode_03.log（`Status: 200 / Raw: {"code":0,"data":{}} / VERDICT: DEFECT_FOUND`）
- 源码 文件:行号+摘录:
  - `handler_v2.go:2037-2049` — `for _, key := range []string{ common.WarmupScalarFieldKey, ... } { if _, ok := httpReq.Params[key]; ok { req.Properties = append(...) } }` — 转发白名单仅 warmup.* 等键，query_mode 及一切未识别 params 键被静默忽略
  - `common.go:516-517` — 枚举校验存在但 REST 路径绕过
  - 调用链: httpReq.Params['query_mode'] → 不在白名单 → 未达 proxy.CreateCollection → ValidateQueryMode 未调用 → code 0

## Impact
query_mode 取值域为闭集 {unset, large_topk}，枚举外值被接受即客观违规；两种载体（properties/params）一致绕过，说明是结构性的 REST 绑定层缺口而非单键遗漏。最终判 DEFECT（LLM兜底B=CONFIRMED，枚举闭集判据命中）。
