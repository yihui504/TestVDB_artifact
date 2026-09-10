# TestVDB Mining Summary

**Session**: 2026-08-21T23-37-54Z
**Target**: milvus v2.6.16
**Date**: 2026-08-22
**Duration**: 07:18 → 11:4x（本地，A1→D7，R1 + R2 盲注 ×2 轮[含违规作废重跑]，~4h25m——违规复盘与重跑占 ~1.5h）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Chains | 16（R1 11 + R2 盲注 5；R2 首轮 3 条主进程违规脚本已作废） |
| DEFECT | 9 |
| NOT_DEFECT | 6 |
| NME | 1（alterprops_27 混合形态回炉） |
| NOVEL (gate) | 9/9 endorsed |
| verify | **9 CONFIRMED / 0 FP / 0 NI** |
| doc_coverage_pct | N/A（source-derived diff：v2.6.12→v2.6.16 零端点增删/query_mode 族新增） |
| GT 参数面 | 4/4 |
| Reach | 机械 **1/4**；盲评 **2/4**（nprobe+searchParams 一链双命中） |

## GT Reach 明细与盲评

| GT | 参数 | 机械 | 盲评裁决 |
|----|------|------|----------|
| 49823 | nprobe | ✓（search_zero_22） | **exact**：nprobe=0/-1 code:0 与 issue 一致（open，milestone 2.6.23） |
| 49930 | searchParams | ✗（param 粒度：agent 填 nprobe 具体键 vs GT 伞参数） | **exact**：同链覆盖 ef=0/-1+nprobe=0/-1 系统化（49930 是 49823 的系统化扩展同根因）——一链双命中 |
| 49889 | dbName | ✗ | **auditor 判 NOT（by_design 三级回退）vs 官方 triage/accepted 分歧**——不计 reach，分歧记录在案（论文素材：检测器判定与官方分类分歧率） |
| 50018 | collectionName | ✗ | 未命中（R2 盲注 19 号单元测名字类空串判 NO_DEFECT——覆盖面未及 aliases/list 端点） |

## ⚠️ 流程违规事件（本 session 内发生并处置）

1. **R2 首轮主进程违规**：主进程查完 GT issue 后直接写三条复刻脚本（nprobe=0/dbName=""/collectionName=""）——架构零生成权+盲注泄露双重违规（用户纠正）。处置：脚本移 tainted-mainproc-scripts/ 留证、链作废、**R2 重派纯盲注**（派发词不点名参数）。
2. **盲注重跑结果验证了方法有效性**：盲注 agent 独立命中 nprobe/ef 零值形态（boundary_r2_search_zero_22 教科书边界矩阵产物）——一链双命中两个 GT issue（49823/49930）；dbName 命中形态但 auditor 独立判 by_design；collectionName 未命中。
3. 由此确立流程红线（已记 memory）：B7 契约承载必须先于查 issue；主进程测试仅限排除性单列判定且须披露。

## Confirmed Defects（9）

| # | Defect ID | Type | Param |
|---|-----------|------|-------|
| 1 | boundary_querymode_01 | Type1 | properties.query_mode bogus 静默接受 |
| 2 | boundary_querymode_02 | Type1 | 合法 large_topk create 无效 |
| 3 | boundary_querymode_03 | Type1 | params 载体绕过枚举 |
| 4 | semantic_large_topk_1 | Type1 | 属性未持久化 cap 不变 |
| 5 | state_query_mode_alter_1 | Type4 | 有索引 alter code:0+门单向 |
| 6 | vein_query_mode_maturity_1 | Type1 | create/alter 校验不对称+junk 持久化 |
| 7 | boundary_r2_search_zero_22 | Type1 | nprobe/ef 0/-1+groupSize=0（=GT 49823+49930） |
| 8 | boundary_r2_query_zero_23 | Type1 | consistencyLevel 空串双端点 |
| 9 | boundary_r2_create_zero_20 | Type1 | shardsNum 0/-1 静默默认化 |

## Rejected (6) / NME (1)

NOT_DEFECT 含 dbName 空串（by_design 分歧记录）/drop 幂等族/truncate 统计偏移/aliases 保护/consistency 空串默认（R1 版被 R2 以 enum 断言重审翻 DEFECT——两链不同锚并存注记）/extrakeys（重锚消解 by-design）；NME：alterprops（TTL by_design+空键 validation_absent 混合）

## Retry 四数

坏 0 / regen 0 / 修好 15（executor env 缺 TESTVDB_TARGET/PYTHONPATH 首跑全 ModuleNotFoundError/RuntimeError——修正后重跑，教训：agent 自跑设了 env 而主进程批量没带全）/ 超限 0

## 机制事件记录

1. executor 批量需完整 env（TESTVDB_DB_URL+TESTVDB_TARGET+PYTHONPATH=cache/scripts）
2. R2 meta param 规范化（agent 复合描述串→规范单值，原值存 param_original_compound）
3. auditor 判定与官方分类分歧首例入库（49889 dbName）
4. 一链双 GT 命中（49823+49930 同根因）+param 粒度差异（伞 vs 具体键）机械口径局限再证

SUMMARY-OK
