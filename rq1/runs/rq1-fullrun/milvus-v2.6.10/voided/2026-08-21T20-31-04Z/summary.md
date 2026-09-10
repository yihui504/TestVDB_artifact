# TestVDB Mining Summary

**Session**: 2026-08-21T20-31-04Z
**Target**: milvus v2.6.10
**Date**: 2026-08-22
**Duration**: 03:57 → 06:1x（本地，A1→D7，R1 全量 + R2 定向补强，~2h20m）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 27（R1 21 + R2 6） |
| DEFECT | 16 |
| NOT_DEFECT | 9 |
| NME | 2（limitdefault_08 / v1_internal_path_leak_5——rework 未及，保守留档） |
| NOVEL (gate) | 16/16 endorsed |
| verify (defect-review) | **16 CONFIRMED / 0 FP / 0 NI** |
| doc_coverage_pct | N/A（source-derived：87 v2+10 v1 端点自 handler 路由提取） |
| GT 参数面 | 5/5（R2 补 fieldName 规则 + 动态字段一致性两契约） |
| Reach (injector) | **5/5 all_reached** |

## GT Reach 明细与盲评双确认

| GT | 参数 | 命中链 | injector | 盲评裁决 |
|----|------|--------|----------|----------|
| 47729 | nprobe | semantic_r2_nprobe_02 | ✓ | **同根因不同触发值**：GT=0 值接受，本链=字符串 "4" 强转；同透传无校验缺口/同修复点（utils.go L2125 %v）→ 判同缺陷，形态注记 |
| 47752 | ef | vein_searchparams_silent_default_3 | ✓ | **exact**：GT=ef:0 HNSW 接受，本链六非法值含 0 全静默默认；GT closed by foxspy（milestone 2.6.14 修复）→ 修复在 2.6.10 之后，本版复现一致 ✓ |
| 47755 | filter | semantic_filterdiag_04 | ✓ | **同参数面不同子形态**：GT=降序范围/空范围语义校验过松，本链=dyn 集合未知字段静默空结果；同"filter 校验过松"族——盲评记 partial（子形态未重合） |
| 47763 | fieldName | boundary_r2_dynfield_name_insert_01 / upsert_03 | ✓ | **exact**：非法动态字段名 insert code:0 + query "parse output field name failed" 数据不可读——与 GT issue 逐字一致 |
| 47766 | dataType | boundary_r2_dyn_type_matrix_04 / upsert_05 | ✓ | **exact**：动态字段混型全接受——与 GT issue 一致（GT 演示 string→int，本链含该组合） |

**双口径 reach**：injector **5/5**（机械 param 匹配）；盲评严格口径 **3 exact + 1 同根因（nprobe）+ 1 同参数面子形态差（filter）**——论文呈现两口径并注记（同 #5 11732 模式：同根因不同触发值判同缺陷；子形态差异留读者裁量）。

GT 全为 phase3 自报（<submitter> 2026-02）；47752/47755 真实修复关闭（milestone 2.6.14>本版，复现一致）；47763/47766 stale-bot 关闭非修复；47729 open（reopened，milestone 3.0.1）。

## Novelty 披露

16/16 NOVEL。其中 5 个 GT 参数面族对应自报 issue（上表）；新发现：quick/schema 冲突无校验、shardsNum 旁路、未 load search code:0（双脚本互证）、query limit 漂移、Int64 "5" 强转、hybrid 子搜索不对称、partition 名选择性缺失、v1 内部路径泄漏（NME 留档）等 11 条全新。

## Retry 四数

坏 3（semantic grouping/hybridrrf SCRIPT_ERROR 建表形状坑 + radius ValueError——非 GT 关键，弃）/ regen 0 / 修好 0 / 超限 0。R2 补测覆盖 grouping/radius（quick-create 形态成功，NO_DEFECT）。

## Confirmed Defects（16）

| # | Defect ID | Type | Param |
|---|-----------|------|-------|
| 1 | boundary_quick_schema_conflict_003 | Type1 | dimension×schema 互斥缺失 |
| 2 | boundary_shards_16_010 | Type1 | shardsNum 旁路（REST 键丢弃） |
| 3 | boundary_load_double_021 | Type2 | 未 load search code:0 + 双 load code:0 |
| 4 | semantic_filterdiag_04 | Type1 | filter 未知字段（dyn）静默 |
| 5 | semantic_loadcycle_03 | Type4 | load 前 search code:0 |
| 6 | boundary_topk_limit_013 | Type1 | limit 边界 |
| 7 | vein_insert_type_coercion_2 | Type2 | Int64 "5" 强转 |
| 8 | vein_searchparams_silent_default_3 | Type2 | ef 六非法值静默默认（=GT 47752） |
| 9 | vein_query_limit_semantic_drift_4 | Type3 | query/search limit 两面漂移 |
| 10 | vein_hybrid_subsearch_params_7 | Type2 | hybrid 子搜索 params 不对称 |
| 11 | boundary_r2_dynfield_name_insert_01 | Type1 | 非法动态字段名+数据不可读（=GT 47763） |
| 12 | boundary_r2_dynfield_name_upsert_03 | Type1 | 同 47763 upsert 通道 |
| 13 | boundary_r2_dyn_type_matrix_04 | Type1 | 混型矩阵（=GT 47766） |
| 14 | boundary_r2_dyn_type_upsert_05 | Type1 | 同 47766 跨通道 |
| 15 | boundary_r2_partition_alias_index_name_06 | Type1 | partition 名选择性缺失 |
| 16 | semantic_r2_nprobe_02 | Type1 | nprobe 字符串强转（=GT 47729 同根因） |

## Rejected (9) / NME (2) 摘要

NOT_DEFECT 含跨轮翻案：rowCount 概念未涉及（2.6 正常）/COSINE 相似度语义（2.3 判 NOT 后 2.6 未再犯）/name_len（首字符 _ 源码允许）/consistency 默认/idType 别名/refresh_load 65535（断言域外）/drop-with-alias（显式前置）/dyn 未知字段（vein_1——R1 版本判 NOT，R2 的 semantic_filterdiag_04 因新契约锚判 DEFECT，两链不同锚并存）/outputFields/efrecall/unknown_field/dimmismatch（重锚消解）。

## 机制事件记录

1. auditor 批量硬上限（≤12）首次触发拒批——两批 12+9 合规重派（2026-08-18 串扰规则）
2. 契约 R2 补强两 verified 条目（字段命名规则/动态字段一致性，官方 limitations.md 引文）——B7 参数面职责；R2 命中 fieldName/dataType 依赖此补强
3. 白名单 +searchparams 等 5 前缀（4exp 092e9be）——GT ef 首个命中案例
4. 2.6 新知识路径验证：code:0 成功信封（vs 2.3 的 200）、full-schema dim 位置/fields+add 形状/load 前必须建索引三个构建怪癖入档
5. R1→R2 GT 轨迹 2/5→5/5（契约补强+定向轮）

SUMMARY-OK


---

## ⚠️ R2-rerun 更新（2026-08-22 用户拍板 B，本节覆盖上文 R2 相关记录）

**原 R2 六链 tainted 作废**：两条契约断言（字段命名规则/动态字段一致性）系查完 GT issue 47763/47766 后补（GT 语义传导）+ semantic 派发词点名 nprobe——六链移 tainted-r2-guided/ 留证，契约回滚（type_constraints 11→9）重签。

**R2b 纯盲注重跑结果**（派发词零点名，hint 2/5）：
- 28 链 15 DEFECT / 10 NOT / 3 NME；verify **15/15 CONFIRMED**
- **GT 5/5 all_reached 全干净**（injector+盲评一致）：
  - 47752 ef ← R1 vein_searchparams（六非法值含 0）
  - 47755 filter ← R1 semantic_filterdiag（盲评同参数面子形态差注记保留）
  - 47763 fieldName ← **R2b boundary_r2b_rowfield_names_01**（非法行键 insert code:0 ‖ 回读 65535——盲注独立命中）
  - 47766 dataType ← **R2b boundary_r2b_dyn_crosstype_02**（跨 6 型+upsert 改写——盲注独立命中）
  - 47729 nprobe ← **R2b semantic_r2b_nprobe_domain_01**（4.5/-1/0/INT_MAX 无效化——盲注独立命中）
- **方法论结论**：三个 GT 参数在无引导契约+零点名派发下由 agent 常规边界矩阵独立挖到——盲注管线有效性实证（与 #11 重跑互为印证）
- 新发现：get(*)-vs-query 点名读写路径不一致（NME 回炉）/searchParams 拼写错误静默忽略/upsert 标量强转/请求级未知键丢弃

**修订总表**：Total 28 链 | DEFECT 15 | NOT 10 | NME 3 | NOVEL 15 | verify 15/15 | GT 5/5 双口径 | 时长修订 +~1h（重跑）
