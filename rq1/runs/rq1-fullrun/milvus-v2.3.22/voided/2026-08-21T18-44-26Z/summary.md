# TestVDB Mining Summary

**Session**: 2026-08-21T18-44-26Z
**Target**: milvus v2.3.22
**Date**: 2026-08-22
**Duration**: 02:02 → 04:0x（本地，A1→D7，R1 全量轮 + R2 定向补证轮，~2h05m）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 21（R1 18 + R2 3） |
| DEFECT | 15 |
| NOT_DEFECT | 5 |
| NME | 1（vein_v1v2_autoid_005：字段与 rationale 自相矛盾，保守取字段） |
| NOVEL (gate) | 15/15 endorsed |
| verify (defect-review) | **14 CONFIRMED / 1 FALSE_POSITIVE** |
| doc_coverage_pct | **N/A**（milvus 无 spec 规则；知识路径 source-derived：54 端点全部提取自 handler_v1/v2.go 路由注册） |
| GT 参数面 | 1/1（load 生命周期 invariant + 5 个 load 端点） |
| Reach | **0/1**（injector 与盲评一致——见 GT 单列） |

## GT Reach：47635 单列（standalone-unreachable 模式，同 qdrant 9045 先例）

**GT #47635**（phase3 自报 2026-02-06，**closed by stale-bot 2026-03-26——非修复关闭**）：load() 返回成功后立即 search() 报 `MilvusException code=0`（Success 码承载失败）竞态。issue 自述：Method 1 standalone 低复现率 / Method 2 distributed 100%。

本 session 证据：
- **state_r2_load_immediacy_001 正面测**（0/10/50/100ms 延迟梯度×5 轮）：load 返回即 200 可搜，无 code=0 异常——standalone 不复现
- state_r2_concurrent_loadsearch_003（10 线程并发 load+search）：30/30 全 200
- 相关发现 state_r2_release_inflight_004（release 竞态 delegator 65535 泄漏）是相邻现象（in-flight 查询撞上卸载而非加载）

**结论**：47635 为 distributed-only 竞态，standalone 环境不可达——单列不进 reach 分母（9045 模式）。

## Novelty 披露

15/15 NOVEL（gate endorsed）。其中 rowCount 族 3 链（boundary_016/semantic_visibility_04/vein_stats_rowcount_001 + R2_005 四方复现）后被 R2 auditor 按 datacoord flush 语义源码翻案 by-design（见事件记录）——gate 的 NOVEL 是检索维度（无已知 issue 命中），与行为判定维度独立。

## Retry 四数

坏 0 / regen 0 / 修好 0 / 超限 0（R1 36/36 + R2 8/8 一次过，容器全程健康；milvus 2.3.22 v2 create 拒绝嵌套 schema dimension 的构建差异由 agent 现场适配）

## Confirmed Defects（verify 14；按 defect-N 顺序）

| # | Defect ID | Type | Param |
|---|-----------|------|-------|
| 1 | boundary_idtype_datatype_003 | Type1 | idType='int64' 绕过枚举 |
| 2 | boundary_limit_offset_008 | Type1 | v2 query limit=0/-1 全量返回 |
| 3 | boundary_metric_enum_002 | Type1 | metricType ''/None 绕枚举 |
| 4 | boundary_search_required_005 | Type2 | v1 id 默认数字（版本漂移 http_param.go:42） |
| 5 | boundary_stats_rowcount_016 | Type4 | rowCount 恒 0 ⚠️R2 翻案 by-design（flush 语义） |
| 6 | boundary_v2_params_types_007 | Type1 | params null 绕类型约束 |
| 7 | semantic_filter_expr_05 | Type2 | 非法 filter 65535 非 1804-family |
| 8 | semantic_visibility_04 | Type4 | rowCount 恒 0 ⚠️同上 R2 翻案注记 |
| 9 | vein_drop_idempotent_004 | Type2 | drop 不存在静默 200 vs load 100 |
| 10 | vein_dupcreate_msg_006 | Type2 | v2 identical 重复创建静默成功 |
| 11 | vein_query_limit0_002 | Type2 | limit=0 全量（与 #2 互证） |
| 12 | vein_stats_rowcount_001 | Type4 | rowCount 三方对照 ⚠️R2 翻案注记 |
| 13 | vein_typo_filter_003 | Type2 | 未知字段 filter 吞成空结果 |
| 14 | state_r2_upsert_delete_race_007 | Type3+2 | 并发 delete C++ Assert 透出（ExecExprVisitor.cpp:325→EasyAssert.h:122 结构保证） |
| — | state_r2_release_inflight_004 | Type3 | **verify FALSE_POSITIVE**（复跑 log NO_DEFECT vs 首跑转述 DEFECT——flaky 竞态双门分歧，降级不可确认） |

## Rejected (5) / NME (1)

NOT_DEFECT：dim_mismatch_004（v1 search 静默维度不匹配——无契约断言）、nanninf_vector_015、cosine_range_03（官方测试固化相似度语义）、load_state_07（R2 重锚后行为==契约）、insert_search_visibility_005（rowCount flush by-design 翻案）；NME：v1v2_autoid_005（字段/rationale 矛盾保守取）

## DEFECT 分布

boundary 6 / state 2（R2） / semantic 2 / vein 5

## 机制事件记录

1. **rowCount 族翻案链**：R1 三链 DEFECT → R2 auditor 按 datacoord meta.go:265（rowCount 仅计已 flush segment）+ querynode growing 可搜分属两子系统判 by-design（NOT_DEFECT 方向），但 gate/verify 维度仍保留原判定——**契约未披露 flush 语义**（auditor 留言主进程），已记入契约修订待办
2. **契约自冲突消解**（R2 主进程）：inv_load_lifecycle 加 v2 auto-load 例外（handler_v2.go:1165）+ 新增 milvus_range_v2_query_limit_001——两条 NME 链消解（load_state_07→NOT_DEFECT / limit_offset_008→DEFECT）
3. **auditor summary 计数漂移**（中止条款 2）：条目 15/5/1 vs summary 13/7/0——主进程机械校正
4. **vein_v1v2_autoid_005 判定字段/rationale 自相矛盾**：保守取字段 NME，记录在案
5. **defect-14 双机械门分歧**：auditor（源码机械触发）DEFECT vs verify（复跑 log）FALSE_POSITIVE——flaky 竞态如实降级
6. milvus 首跑三件套适配：source-derived 知识路径（无 spec）、错误信封判定锚（HTTP 200+code）、v2 create 拒绝嵌套 schema dimension 的构建差异

SUMMARY-OK
