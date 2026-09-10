# TestVDB Mining Summary

**Session**: 2026-08-21T15-44-04Z
**Target**: weaviate v1.38.1
**Date**: 2026-08-21/22
**Duration**: 23:23:58 → 00:2x（本地，A1→D7 单轮无中断 ~60min）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 19 |
| DEFECT | 17 |
| NOT_DEFECT | 1 |
| NME (NEEDS_MORE_EVIDENCE) | 1 |
| NOVEL (gate) | 17 |
| COVERED_BY_PR | 0 |
| UNVERIFIED | 0 |
| doc_coverage_pct | 100.0 (110/110) |
| GT 参数面 | 1/1（desiredCount 源码回填契约） |
| Reach (injector 口径) | 1/1 all_reached |

## GT Reach 明细

| GT Issue | 参数 | 命中链 | 判定 | 备注 |
|----------|------|--------|------|------|
| #11729 | desiredCount | boundary_sharding_desiredCount_001 | DEFECT | **exact 命中**：GT issue -1→200/0→422 与本链完全一致；本链附加 phantom 视角（200 但类未实例化 GET 404） |

## 人工 LLM 盲评双确认（第二口径）

| GT | 攻击值形态对比 | 裁决 |
|----|----------------|------|
| 11729 desiredCount | GT issue=`-1`→200/`0`→422 ↔ 本链=`-1`/`-100`→200 phantom、`0`→422 "physical shards unavailable"（完全一致） | 同缺陷 ✓ |

**盲评口径 reach = 1/1 all_reached**（与 injector 口径一致）。

⚠️ GT 特殊性披露：#11729 为 phase3 自报 issue，**已 closed**（2026-06-24 维护者 trengrj 关闭，state_reason completed）——但修复未进 v1.38.1（实测 -1 仍 200，与 1.38.0 行为一致）；且 0 的 422 非前置校验而是运行时 "physical shards unavailable"（与 #5 phantom-class 同族路径）。

## Novelty 披露

17/17 NOVEL。其中：
- 1 条（desiredCount）对应本项目 phase3 自报 **closed** issue #11729（gate 检索 no_known_hits，判 NOVEL；论文口径注明自报已知）
- #5 同族缺陷在本版重现：vein_hnsw_dynamic_ef_cross_1 / boundary_hnsw_EF / flatSearchCutoff / asyncEnabled 等（均未报 issue，gate 判 NOVEL）
- 判定漂移注记：vein_replication_async_input_drop_5（asyncEnabled 输入丢弃）在 #5 判 DEFECT、本版 auditor 判 NME（"纯输出派生 by-design"）——判定权独立致跨版本不一致，两版判定均保留在案

## Retry 四数

| 指标 | 值 |
|------|-----|
| 坏脚本 | 2（容器 DOWN 时段假 SCRIPT_ERROR：014/013） |
| regen | 0 |
| 修好 | 2（容器恢复后主进程重跑，均转 DEFECT_FOUND） |
| 超限 | 0 |

⚠️ 容器事件：boundary_sharding_desiredCount_dos_002（desiredCount=100000/INT_MAX）两度打挂容器（OOM exit 137）——该缺陷本身即 DoS 型（Type3），executor 恢复重跑后 semantic/vein/state 数据为干净终态。

## Confirmed Defects（17，按 chain_verdicts 顺序）

| # | Defect ID | Type | Param | Novelty |
|---|-----------|------|-------|---------|
| 1 | boundary_sharding_desiredCount_001 | Type1_IllegalSuccess | shardingConfig.desiredCount | NOVEL（=GT #11729） |
| 2 | boundary_sharding_desiredCount_dos_002 | Type3_RuntimeFailure | shardingConfig.desiredCount | NOVEL |
| 3 | boundary_replicationFactor_003 | Type1 | replicationConfig.replicationFactor | NOVEL |
| 4 | boundary_hnsw_dynamicEfMin_004 | Type1 | vectorIndexConfig.dynamicEfMin | NOVEL |
| 5 | boundary_flatSearchCutoff_005 | Type1 | flatSearchCutoff | NOVEL |
| 6 | boundary_hnsw_EF_006 | Type1 | vectorIndexConfig.EF | NOVEL |
| 7 | boundary_bm25_params_007 | Type1 | cleanupIntervalSeconds | NOVEL |
| 8 | boundary_distance_metric_enum_008 | Type2 | vectorIndexConfig.distance.name | NOVEL |
| 9 | boundary_gql_limit_negative_009 | Type2 | limit | NOVEL |
| 10 | boundary_nearVector_certainty_010 | Type1 | nearVector.certainty | NOVEL |
| 11 | boundary_property_type_confusion_012 | Type1 | properties.<int>.null | NOVEL |
| 12 | boundary_vector_null_empty_013 | Type1 | vector | NOVEL |
| 13 | state_batch_04 | Type4 | objects（batch 通道） | NOVEL |
| 14 | vein_hnsw_dynamic_ef_cross_1 | Type1 | dynamicEfMin×Max | NOVEL |
| 15 | vein_shard_status_echo_2 | Type1 | status（shards） | NOVEL |
| 16 | vein_bm25_motm_negative_3 | Type2 | minimumOrTokensMatch | NOVEL |
| 17 | vein_schema_silent_drop_nested_4 | Type2 | properties[].indexNullState | NOVEL |

## Rejected / Rework (2)

| Chain | 结果 | 理由 |
|-------|------|------|
| boundary_sharding_virtualPerPhysical_014 | NOT_DEFECT | 脚本字段名错配（virtualPerPhysicalShards≠virtualPerPhysical），200 为未知字段丢弃——request_param_typo 假阳性 |
| vein_replication_async_input_drop_5 | NME | asyncEnabled 纯输出派生（wrappers.go:40 factor>1 shim），保守回炉 |

## DEFECT 分布

| 族 | 数量 |
|----|------|
| boundary | 12 |
| state | 1 |
| semantic | 0（7 单元全合规——契约行为面干净版本） |
| vein | 4（1 NME 另计） |

## 机制事件记录

- injector 容器前缀白名单 +5（shardingconfig/vectorindexconfig/invertedindexconfig/replicationconfig/multitenancyconfig，4exp acb8f1c）——GT 裸名 desiredCount 首个实测命中案例
- 契约 desiredCount 源码回填（spec 无 requestBody，enrich 无法覆盖，主进程 patch POST /schema +3 参数 +1 constraint）
- 容器 OOM ×1（dos_002 DoS 型缺陷自身所致），恢复重跑干净

## Evidence Chain Completeness

| 环 | 状态 |
|----|------|
| contract | 4/19 专属锚；15 泛锚/断裂（契约仅 4+2 条 inferred 约束）——A 层断裂不等于无缺陷，B/C/D 补强 |
| doc | DOC_PARTIAL 为主（constraint source 为 go 引用非 http，本地源码核对代替） |
| behavior | 19/19 有 log 逐字观测 |
| source | 17/19 精确定位（014 键错配/013 丢弃点未全定位） |

## Output Files

- defects/defect-1.md … defect-17.md
- 证据链 evidence_chain/ ×19；判定 debate_logs/chain_verdicts.json + novelty_gate.json

SUMMARY-OK
