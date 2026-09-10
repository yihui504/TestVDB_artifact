# Defect 3: activityStatus 空串绕过枚举且报误导性多租户错误

## Metadata
- Defect ID: TESTVDB-WEAVIATE-003 (boundary_tenants_activitystatus_empty_011)
- Type: Type2_PoorDiagnostics
- Severity: Low
- Endpoint: POST /v1/schema/{className}/tenants
- Param: activityStatus
- Novelty: NOVEL (gate, HIGH confidence, no_known_hits) — 对应官方 open issue #11741
- Discovered: 2026-08-21

## Description
`activityStatus` 为 10 值枚举（ACTIVE, INACTIVE, OFFLOADED, OFFLOADING, ONLOADING, HOT, COLD, FROZEN, FREEZING, UNFREEZING）。空串同样绕过 `swag.IsZero` 枚举校验；请求最终 422，但错误消息是 `updating schema: TYPE_ADD_TENANT: multi-tenancy is not enabled for class`——与 activityStatus 枚举违反完全无关的误导性诊断。

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema/Def3Class/tenants" \
  -H "Content-Type: application/json" \
  -d '[{"name":"tenantA","activityStatus":""}]'
# 实际: HTTP 422 "multi-tenancy is not enabled for class"（误导）
# 期望: HTTP 422，错误指向 activityStatus 非法枚举值
```

## Expected vs Actual
- Expected: 422 + 枚举违反诊断（对照：非法值 013、小写 014 均正确 422 并列出枚举全集）
- Actual: 422 但报多租户未启用——错误通道语义错位

## Evidence Chain
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: `boundary_scripts/boundary_tenants_activitystatus_empty_011.py`
- Log: `output_boundary_tenants_activitystatus_empty_011.log`
- 源码: `entities/models/tenant.go` L109-120 `validateActivityStatus()` — 与 defect-1 同款 `swag.IsZero('')` 早退模式；多租户检查先于校验触发
- Ring 1 (Contract Clause 契约条款) constraint_id: constraint `activityStatus` 10 值枚举
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（全 PASS）
- source_grounding: validation_absent
- Evidence chain: `evidence_chain/boundary_tenants_activitystatus_empty_011.json`

## Impact
用户收到"多租户未启用"会去改 multiTenancyConfig 而非修正 activityStatus，诊断南辕北辙，浪费排障时间。
