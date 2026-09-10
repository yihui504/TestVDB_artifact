# TestVDB Mining Summary

**Session**: 2026-08-21T17-17-51Z
**Target**: weaviate v1.38.2
**Date**: 2026-08-22
**Duration**: 01:03 → 02:1x（本地，A1→D7 单轮无中断 ~75min）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 17 |
| DEFECT | 15 |
| NOT_DEFECT | 1 |
| NME | 1 |
| NOVEL (gate) | 15 |
| doc_coverage_pct | 100.0 (110/110) |
| GT 参数面 | 1/1（match 源码回填契约） |
| Reach (injector) | 1/1 all_reached |

## GT Reach 明细

| GT Issue | 参数 | 命中链 | 判定 | 备注 |
|----------|------|--------|------|------|
| #12041 | match | semantic_match_missing_01（injector 命中链）；同根因互证 5 链：boundary_bd_match_where_01/class_02/empty_08/resources_09 + vein_batchdelete_validation_channel_01 | DEFECT | **exact 命中**：GT issue Case A（缺 match.where）/Case B（空 match）→500 与本 session 观测完全一致；源码同定位 batch_delete.go L128/132/136 裸 errors.New + handlers L194-197 映射缺口 |

## 人工 LLM 盲评双确认（第二口径）

| GT | 对比 | 裁决 |
|----|------|------|
| 12041 match | GT=缺 where/空 match → 500 应 422 ↔ 本 session 5 变体（缺失/null/空对象/缺 class/缺 where）全 500，行为/攻击值/源码定位完全一致 | 同缺陷 ✓ |

**盲评口径 reach = 1/1 all_reached**（与 injector 一致）。GT #12041 为 phase3 自报 **closed** issue（2026-07-08 dirkkul 关闭）但修复未进 v1.38.2（本版实测 Case A/B 均 500 复现）——issue 正文引用的邻接修复 PR#11497 正是 #4 (v1.37.4) GT 官方修复 PR。

## Novelty 披露

15/15 NOVEL。其中 6 链 match 族对应本项目 phase3 自报 closed issue #12041（修复未进本版，实测复现）；desiredCount/shardcount 族为 #6 已发现缺陷在同版重现（未报 issue，gate 判 NOVEL）；新发现：deletetime 哨兵/gql limit 负值/ef 字符串 coerce 0/停用词 500/shardstatus 500+phantom 等。

## Retry 四数

坏 0 / regen 0 / 修好 0 / 超限 0（executor 36/36 一次过，容器全程健康零事件）

## Confirmed Defects（15）

| # | Defect ID | Type | Param |
|---|-----------|------|-------|
| 1 | boundary_bd_ef_types_05b | Type1 | dynamicEfMin（字符串 coerce 0） |
| 2 | boundary_bd_gql_limit_07 | Type1 | limit=-1 |
| 3 | boundary_bd_hnsw_pair_04 | Type1 | efMin>efMax 持久化 |
| 4 | boundary_bd_match_class_02 | Type3 | match.class 缺失 500 |
| 5 | boundary_bd_match_empty_08 | Type3 | 空 match 四变体 500 |
| 6 | boundary_bd_match_resources_09 | Type3 | class 空串 500 |
| 7 | boundary_bd_match_where_01 | Type3 | match.where 缺失 500 |
| 8 | boundary_bd_shardcount_03 | Type1 | desiredCount=-1 接受 |
| 9 | semantic_deletetime_04 | Type2 | 零值时间哨兵泄漏 |
| 10 | semantic_match_missing_01 | Type3 | match 五变体 500 |
| 11 | semantic_shardcount_02 | Type4 | desiredCount 负值幻影成功 |
| 12 | vein_batchdelete_stopword_500_02 | Type3 | 停用词 REST 500 |
| 13 | vein_batchdelete_validation_channel_01 | Type3 | 校验通道分裂 |
| 14 | vein_shardstatus_500_invalidstatus_04 | Type3 | 枚举外 status 500 |
| 15 | vein_shardstatus_phantom_03 | Type4 | 幻影 shard 200 no-op（多节点 by-design 疑点留人工复核） |

## Rejected / Rework (2)

| Chain | 结果 | 理由 |
|-------|------|------|
| vein_nodes_shardsnull_05 | NOT_DEFECT | auditor 本机实测 ?output=verbose 时 shards 完整填充——minimal 默认 null 为 verbosity 分层 by-design，仅文档缺口 |
| semantic_diag_quality_06 | NME | 静默差诊断属实但不属任何客观约束类且契约无声称，灰区保守打回 |

## DEFECT 分布

boundary 8 / state 0（8 单元全合规）/ semantic 4 / vein 3

## 机制事件记录

- 契约 match 源码回填（+5 参数 +1 verified 级 type_constraint，spec 无 requestBody 同 #6 模式）；patch 后 passport hash 手动重算回填（--compute-hash 只输出不回填）
- 候选提取条件修正：'DEFECT' in content 会误收 NO_DEFECT（36 误提→VERDICT 行正则精提 17）
- weaviate 三连版 GT 全为 phase3 自报 issue（11730/11732/11741 open；11729/12041 closed 但修复未进对应版本——时间线证明 closed≠该版已修）

SUMMARY-OK
