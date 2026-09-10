# Defect 1: 空串 tokenization 绕过枚举校验，静默默认 word

## Metadata
- Defect ID: TESTVDB-WEAVIATE-001 (boundary_schema_tokenization_empty_001)
- Type: Type1_IllegalSuccess
- Severity: Medium
- Endpoint: POST /v1/schema
- Param: tokenization
- Novelty: NOVEL (gate, HIGH confidence, no_known_hits) — 对应官方 open issue #11730
- Discovered: 2026-08-21

## Description
`tokenization` 在 OpenAPI spec (v1.38.0) 中声明为 8 值枚举（word, lowercase, whitespace, field, trigram, gse, kagome_ja, kagome_kr），空串不是枚举成员。发送 `tokenization=""` 时服务端返回 HTTP 200 并将集合以默认 `word` 创建——非法输入被静默吞掉并替换为默认值。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"Def1TokenEmpty","properties":[{"name":"txt","dataType":["text"],"tokenization":""}]}'
# 实际: HTTP 200, 响应含 "tokenization":"word"
# 期望: HTTP 422, 错误指出 tokenization 非法枚举值
```

## Expected vs Actual
- Expected: 422 拒绝，报枚举违反（空串不在 8 值枚举内）
- Actual: 200 成功，tokenization 被静默替换为 `word` 并持久化

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `boundary_scripts/boundary_schema_tokenization_empty_001.py`
- Log: `output_boundary_schema_tokenization_empty_001.log`（含 VERDICT 行）
- 源码: `entities/models/property.go` L193-204 `validateTokenization()` — `swag.IsZero(m.Tokenization)` 对空串返回 true 提前 return，枚举校验被完全跳过。call chain: Property.Validate() → validateTokenization() → swag.IsZero() 早退
- Ring 1 (Contract Clause 契约条款) constraint_id: constraint `tokenization` 枚举断言（8 值）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（link/version/content/endpoint 全 PASS）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/boundary_schema_tokenization_empty_001.json`

## Impact
用户拼写失误或客户端序列化 bug 产生的空串被无声吞掉，实际索引行为（word 分词）与用户意图（如 trigram）不符，检索语义静默漂移，排查成本高。
