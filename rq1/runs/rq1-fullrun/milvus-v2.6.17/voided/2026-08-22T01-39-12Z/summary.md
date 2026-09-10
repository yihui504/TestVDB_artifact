# TestVDB Mining Summary

**Session**: 2026-08-22T01-39-12Z
**Target**: milvus v2.6.17
**Date**: 2026-08-22
**Duration**: 09:19 → 15:1x（本地，A1→D7，R1 四族 + R2 盲注，~5h50m——含跨版本违规复盘挤占）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 15（R1 11 + R2 4） |
| DEFECT | 12 |
| NOT_DEFECT | 1 |
| NME | 2（search_limit_ids_013 机制矛盾未闭环 / insert_bodykeys_002 数据丢失未逐键隔离） |
| NOVEL (gate) | 12/12 endorsed |
| verify | **12 CONFIRMED / 0 FP / 0 NI** |
| doc_coverage_pct | N/A（source-derived diff：v2.6.16→v2.6.17 零路由增删/fieldOps 族新增） |
| GT 参数面 | 4/4 |
| Reach | 机械 **1/4**（password）；盲评 **1/4 partial + 3 未命中** |

## GT Reach 明细与盲评

| GT | 参数 | 机械 | 盲评裁决 |
|----|------|------|----------|
| 50354 | password | ✓（r2_password_bytes_003 + r2_updatepwd_creds_004 双链） | **同参数面不同子缺陷**：GT 主张=复杂度不强制（"abcdefgh" 接受+docs 8-64 vs API 6-256 错位+HTTP 恒 200）；本 session 挖到=NUL 截断认证绕过+旧密码 ≥20s 存活（同 users/create password 面的更深缺陷）——partial 注记 |
| 49890 | Request-Timeout | ✗ | 未命中（R1/R2 timeout 面测得 408 语义生效/1.5 静默忽略=NO_DEFECT；issue 主张未核验） |
| 50323 | filter | ✗ | 未命中（insert_bodykeys_002 含 filter 错位键但判 NME 回炉） |
| 50353 | limit | ✗ | 未命中（search_limit_ids_013 limit:null 判 NME 回炉） |

注：49890/50323/50353 的 issue 主张本轮未逐条核验（收口时间预算）——论文盲评复核时补。

## Confirmed Defects（12）

| # | Defect ID | Type | Param |
|---|-----------|------|-------|
| 1 | boundary_fieldops_elemtype_004 | Type1 | fieldOps ARRAY_APPEND null→'' |
| 2 | boundary_fieldops_pk_structural_005 | Type1 | fieldOps PK/ghost 字段旁路+拒后状态泄漏 |
| 3 | state_fieldops_concurrent_001 | Type4 | 并发 fieldOps 丢失更新 29/40 |
| 4 | boundary_fieldname_rules_018 | Type1 | 动态字段名七类非法全接受 |
| 5 | boundary_search_consistency_enum_015 | Type1 | consistencyLevel 空值绕枚举 |
| 6 | boundary_datatype_enum_016 | Type1 | quick/full 冲突无校验（三现） |
| 7 | boundary_collections_name_length_011 | Type1 | numShards REST 未接线 |
| 8 | state_rbac_revocation_immediacy_003 | Type3 | grant_privilege 恒 65535 僵尸角色 |
| 9 | vein_rbac_grant_cross_endpoint_001 | Type3 | RBAC 端点分裂 3vs2 |
| 10 | vein_array_readout_proto_leak_002 | Type2 | Array 字段 proto 包装泄漏 |
| 11 | boundary_r2_password_bytes_003 | Type1 | NUL 截断认证绕过 |
| 12 | boundary_r2_updatepwd_creds_004 | Type4 | 旧密码 ≥20s 双凭证并存 |

## Rejected (1) / NME (2)

NOT：dropfunction_tag_009（源码幂等 by-design）；NME：search_limit_ids（limit:null 与 validateLimit(0) 机制矛盾）、insert_bodykeys（错位键吞 by-design+数据丢失未隔离）

## Retry 四数

坏 0 / regen 0 / 修好 1（insert_bodykeys meta agent 漏写主进程机械补登）/ 超限 0

## 机制事件记录

1. **field_name_rules_001 断言继承链披露**：v2.6.17 契约的该断言系 v2.6.10 污染断言经 2612→2616→2617 formalizer 继承传播——对本版 GT（四参数均不相关）无指向性，记录在案不回滚（#9 已回滚源头）
2. v2.6.17 新面：fieldOps 族（REPLACE 显式旁路注释"Accept silently"）+ parser 文法泛化
3. R2 盲注高价值：NUL 截断认证（2 字节凭证生效）与旧密码 20s 存活——auth 面两连发
4. GT 密度 4 的版本两轮盲注 1/4——边界矩阵对"文档-实现错位类"GT（如复杂度规则）覆盖弱于"校验缺失类"（nprobe/ef/空串族）——检测边界画像数据点

SUMMARY-OK
