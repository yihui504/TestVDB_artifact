# TestVDB Mining Summary

**Session**: 2026-08-21T22-15-23Z
**Target**: milvus v2.6.12
**Date**: 2026-08-22
**Duration**: 05:58 → 07:5x（本地，A1→D7，R1 全量 + R2 COSINE 定向，~2h）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 10 |
| DEFECT | 7 |
| NOT_DEFECT | 2 |
| NME | 1（s04 引文意译回炉未及——同族已由 alter/vein 两链覆盖） |
| NOVEL (gate) | 7/7 endorsed |
| verify (defect-review) | **7 CONFIRMED / 0 FP**（verify VERDICT 提取兼容下划线格式后 47f25ca） |
| doc_coverage_pct | N/A（source-derived diff 模式：v2.6.10→v2.6.12 +1 truncate/88 v2 端点） |
| GT 参数面 | 1/1（metric_type 契约承载） |
| Reach | **0/1 盲评口径**（见单列）；机械口径 1/1 含 s05 假命中已驳回 |

## GT 49059 单列：本环境不复现（COSINE 溢出）

**GT 主张**：COSINE identical 向量 distance >1.0（浮点溢出无 clamp，如 1.0000001192092896；stale-bot 关闭非修复）。

本 session 两轮正面测试均不复现：
1. semantic_r2_cosine_identical_01：120 normalized 128 维自查询，|d-1|=0 全零漂移（FLAT）
2. semantic_r2_gt49059_repro_05（**精确复刻**：IVF_FLAT nlist=128 / dim=128 / 10000 向量严格归一化 / 100 自查询）：over_1.0=0，worst=1.0 恰好边界
3. 辅证：dim 32768 最坏漂移 4e-07；重复查询 bit-stable；COSINE 内部归一化确认

机械口径注记：boundary_s05（metricType accept-and-ignore，param=metric_type）机械命中 1/1——**盲评驳回**（s05 主张"顶层 metricType 被忽略"≠ 49059 的"COSINE 距离溢出"，完全不同缺陷）。

## Confirmed Defects（7）

| # | Defect ID | Type | Param |
|---|-----------|------|-------|
| 1 | boundary_s05_search_metric_mismatch | Type1 | metric_type（顶层 accept-and-ignore） |
| 2 | boundary_s10_quick_full_conflict | Type1 | dimension×schema 互斥缺失（#9 跨版本重现） |
| 3 | state_alter_props_loaded_003 | Type1 | warmup ASYNC create 放行 |
| 4 | vein_warmup_bare_key_001 | Type1 | 裸 warmup key + ASYNC |
| 5 | semantic_search_ids_mode_002 | Type1 | VarChar PK ids 数值 %v 静默转换 |
| 6 | vein_ids_conversion_chain_002 | Type1 | 42.0→'42' 决定性证据 |
| 7 | semantic_default_value_fill_003 | Type1 | default_value 字符串形态绕过 |

## Rejected (2) / NME (1)

NOT_DEFECT：boundary_s11（空串 consistency 默认 Bounded 源码 by_design）、boundary_s12（空稀疏行显式支持）；NME：boundary_s04（bare warmup 引文意译——同族 3/4 号已 DEFECT 覆盖）

## Retry 四数

坏 0 / regen 0 / 修好 2（主进程批量 executor 首跑 cwd+相对路径 bug 全假跑——修正绝对路径重跑）/ 超限 0

## 机制事件记录

1. 主进程批量 executor cwd bug（subprocess 相对路径+cwd 切换冲突，26 脚本全 No such file——修正 abspath+cwd 组合）
2. VERDICT 行格式三态并存（VERDICT: DEFECT / VERDICT_DEFECT / 无标准行）——candidates 提取与 verify 提取各自适配（verify 47f25ca 下划线兼容）
3. 2.6.12 新攻击面验证：search data/ids 互斥矩阵全对、warmup 族校验不对称（create 缺失）实锤
4. GT 机械口径假命中首例：s05 param 撞 GT param 但语义完全不同——盲评第二口径价值实证

SUMMARY-OK
