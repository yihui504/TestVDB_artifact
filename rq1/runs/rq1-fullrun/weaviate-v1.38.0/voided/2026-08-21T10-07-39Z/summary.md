# TestVDB Mining Summary

**Session**: 2026-08-21T10-07-39Z
**Target**: weaviate v1.38.0
**Date**: 2026-08-21
**Duration**: R1 前半场 2026-08-21 17:25–18:18（本地，含 A/B 段 + boundary 族）；R1b 补齐 2026-08-21 22:15 起三族 + 审计 + 收口（跨 compact 中断后恢复）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 17 |
| DEFECT | 10 |
| NOT_DEFECT | 7 |
| NME (NEEDS_MORE_EVIDENCE) | 0 |
| NOVEL (gate) | 10 |
| COVERED_BY_PR | 0 |
| UNVERIFIED | 0 |
| doc_coverage_pct | 97.3 (107/110) |
| GT 参数面 | 3/3 |
| Reach (injector 口径) | 3/3 all_reached |

## GT Reach 明细

| GT Issue | 参数 | 命中链 | 判定 | 备注 |
|----------|------|--------|------|------|
| #11730 | tokenization | boundary_schema_tokenization_empty_001 | DEFECT | 空串绕过枚举 |
| #11732 | distance | boundary_schema_distance_empty_009 | DEFECT | ⚠️ GT issue 描述 null 静默默认；本链攻击值为空串 "" 持久化。null 语义链 boundary_schema_distance_null_semantics 被 auditor 判 NOT_DEFECT by-design——pending 人工盲评双确认 |
| #11741 | activityStatus | boundary_tenants_activitystatus_empty_011 | DEFECT | 空串绕过枚举 + 误导诊断（报多租户错误） |

## Novelty 披露

10/10 NOVEL。其中 3 条 GT 命中链对应官方仓库 open issue **#11730 / #11732 / #11741**（2026-06-16 由本项目 phase3 提交，label bug+community，无关联修复 PR）——**非官方已知**（open issue 不属 gate 的 COVERED_BY_PR 口径），gate 判 NOVEL 正确。其余 7 条为全新发现。

## Retry 四数

| 指标 | 值 |
|------|-----|
| 坏脚本 | 0 |
| regen | 0 |
| 修好 | 0 |
| 超限 | 0 |

executor 20/20 一次通过；6 个 exit=1 为 DEFECT 检测预期路径（脚本以非零退出报告缺陷），非坏脚本。

## Confirmed Defects（按 chain_verdicts DEFECT 顺序）

| # | Defect ID | Type | Endpoint | Param | Novelty |
|---|-----------|------|----------|-------|---------|
| 1 | boundary_schema_tokenization_empty_001 | Type1_IllegalSuccess | POST /schema | tokenization | NOVEL |
| 2 | boundary_schema_distance_empty_009 | Type1_IllegalSuccess | POST /schema | distance | NOVEL |
| 3 | boundary_tenants_activitystatus_empty_011 | Type2_PoorDiagnostics | POST /schema/{class}/tenants | activityStatus | NOVEL |
| 4 | semantic_aggregate_math_06 | Type2_PoorDiagnostics | POST /graphql | Aggregate.groupBy | NOVEL |
| 5 | semantic_graphql_diag_03 | Type2_PoorDiagnostics | POST /graphql | where on text[] | NOVEL |
| 6 | state_batch_partial_002 | Type3_RuntimeFailure | DELETE /batch/objects | objects (no match) | NOVEL |
| 7 | vein_dynamic_ef_minmax_1 | Type1_IllegalSuccess | POST/PUT /schema | dynamicEfMin | NOVEL |
| 8 | vein_flat_search_cutoff_2 | Type1_IllegalSuccess | POST /schema | flatSearchCutoff | NOVEL |
| 9 | vein_phantom_class_failed_create_4 | Type4_StateLogicViolation | POST /schema + GET + POST /objects | desiredCount | NOVEL |
| 10 | vein_replication_async_silent_flip_3 | Type2_PoorDiagnostics | POST/GET /schema | asyncEnabled | NOVEL |

## Rejected Candidates (NOT_DEFECT, 7)

| Chain | Reason (auditor rationale) |
|-------|---------------------------|
| boundary_tenants_activitystatus_invalid_013 | 非法值正确 422 并列枚举全集，validation_present |
| boundary_tenants_activitystatus_lowercase_014 | 小写 hot 正确 422 含枚举列表，大小写敏感枚举 |
| boundary_schema_distance_null_semantics | null 静默默认 cosine 为 by_design_in_source，readback 可见默认值（⚠️ pending 人工盲评） |
| semantic_batch_report_04 | swagger body 层整批 422 为生成代码标准行为，诊断精确到 objects.2.id |
| state_shard_readonly_007 | READONLY 写拒绝 500 为服务端状态拒绝设计取舍 |
| state_tenant_visibility_003 | X-Weaviate-Tenant-Header 从未在 REST 文档声明，sdk_rest_confusion |
| vein_hnsw_maxconn_efc_5 | efC>=maxConn 仅 hnswlib 惯例，契约文档双缺失，封闭校验集合为显式设计选择 |

## DEFECT 分布（按族）

| 族 | 数量 | 明细 |
|----|------|------|
| boundary | 3 | tokenization/distance/activityStatus 空串绕过 swag.IsZero 枚举校验 |
| state | 1 | batch_delete.go 500 错误通道（维护者注释证明同类已知） |
| semantic | 2 | groupBy 误导诊断（filter-path 解析器复用）、text[] Equal 静默空集 |
| vein | 4 | hnsw/config.go validate() 封闭集合缺口 ×2（dynamicEfMin/Max、flatSearchCutoff）、wrappers.go:40 asyncEnabled 静默翻转（派生公式覆盖输入）、phantom class 失败创建无回滚（读写通道分裂） |

## 机制事件记录

- R1 期间：injector / novelty_gate 对 chain_verdicts 双形态（debate_logs 两段式转写 vs session 根 auditor 旧直写；verdict vs final_verdict 字段）兼容修复（pipeline d25438a / 主插件 f7554a3）
- R1 前半场跨 compact 中断后恢复，R1b 补齐三族（semantic/state/vein）+ 审计 + 收口
- auditor 两段式输出模式（文本判定行 + 主进程机械转写）首次全量使用：17 链一次过，无超限

## Evidence Chain Completeness

| 环 | 状态 |
|----|------|
| contract | 5/10 完整锚（1,2,3,7,9）；4,5,6,8,10 为弱锚/无专属 constraint，由 behavior+source 补强 |
| doc | 5/10 DOC_VERIFIED（1,2,3,7,9）；5/10 DOC_PARTIAL（4,5,6,8,10，docs.weaviate.io domain_blocked，不阻塞） |
| behavior (log) | 10/10 grade A/B/C 全部 aligned，script_error=0 |
| source | 10/10 精确定位（validation_absent 8 / by_design_in_source 2） |

## Output Files

- `defects/defect-1.md` — tokenization 空串绕过枚举（#11730）
- `defects/defect-2.md` — distance 空串绕过枚举（#11732，空串口径，null 链 pending）
- `defects/defect-3.md` — activityStatus 空串 + 误导诊断（#11741）
- `defects/defect-4.md` — 多属性 groupBy 误导诊断
- `defects/defect-5.md` — text[] Equal+valueString 静默空集
- `defects/defect-6.md` — batch delete 空 match 500 非 422
- `defects/defect-7.md` — dynamicEfMin>Max 持久化
- `defects/defect-8.md` — flatSearchCutoff 负值持久化
- `defects/defect-9.md` — 幻影类失败创建无回滚
- `defects/defect-10.md` — asyncEnabled 静默翻转
- 证据链：`evidence_chain/<defect_id>.json` ×10；判定：`debate_logs/chain_verdicts.json`、`debate_logs/novelty_gate.json`

SUMMARY-OK
