⚠️ reporter-generated=true（内容 100% 出自 reporter agent 交付文本）；main-process fallback 落盘原因：harness 策略拦截 subagent 写 summary.md（"Subagents should not write report files"），重派亦必被拦，故由主进程将 reporter 交付全文原样写入（零内容改写）。—— mine.md 8f 实测门 fallback 条款 + R7 零改写原则

# TestVDB Mining Summary

**Session**: qdrant-1180-r1
**Target**: qdrant v1.18.0
**Date**: 2026-08-23
**Duration**: 2026-08-23T05:48:00Z — 2026-08-23T17:54:53Z（R4 完成；max_rounds 30 未满，会话仍在推进）

---

## Results Overview

| Metric | Value |
|--------|-------|
| Total Rounds | 4（mine_state current_round=4） |
| Scripts Generated | 113（17+29+31+36；mine_state rounds 数组含一条 R2 重复记录，见 Debate Statistics 注） |
| Scripts Passed Debate Stage 1 | N/A（ADR-0008 架构无 Stage1 投票留痕文件） |
| Scripts Executed | 113 派发；缺陷侧 8/8 触发脚本全部执行成功（script_error=false） |
| Execution Passes | N/A（逐脚本 pass 计数不在 reporter 可读面） |
| Defects Confirmed (Debate Stage 2) | 8 |
| Defects Rejected | 32（chain-auditor NOT_DEFECT，累计 R2-R4） |
| False Positives Detected | 32（同上；root cause 分布见 Rejected Candidates 注） |

**数据源说明（留痕）**：final_verdict.json / novelty_gate.json / stage2_aggregation.json 在本 session 未生成（Novelty Gate 尚未运行）。确认源为 `debate_logs/chain_verdicts.json`（ADR-0008 chain-auditor 终判，41 条 verdict：DEFECT 8 / NOT_DEFECT 32 / NEEDS_MORE_EVIDENCE 1）。文件内嵌 summary 块为 R2 时代陈旧值（total 16/defect 4），以 verdicts 数组为准。Novelty Gate 运行后如有翻案，以 final_verdict.json 为准更新本表。

## Confirmed Defects

| ID | Type | Severity | Endpoint | Confidence |
|----|------|----------|----------|------------|
| DEFECT-QDRANT-1（vein_type_mismatch_datetime_range_8） | Type2_PoorDiagnostics | Low | POST /collections/{c}/points/count | Chain-DEFECT（类型恒真；R2/R3 窗口） |
| DEFECT-QDRANT-2（vein_geo_filter_scroll_order_6） | Type2_PoorDiagnostics | Low | POST /points/count + /points/scroll | Chain-DEFECT（C=CONFIRMED + rework2 双轮闭环；human_review 建议） |
| DEFECT-QDRANT-3（vein_type_mismatch_points_count_2） | Type2_PoorDiagnostics | Low | POST /points/count (exact=false) | Chain-DEFECT（终判；perspective_aggregation 残留文本不一致，见数据质量留痕） |
| DEFECT-QDRANT-4（boundary_collections_create_03） | Type1_IllegalSuccess | Medium | PUT /collections/{name} | 机械 A=CONFIRMED → implied DEFECT 定案（最高置信） |
| DEFECT-QDRANT-5（vein_f32_overflow_vector_13） | Type1_IllegalSuccess | Medium | PUT /points + POST /points/query | 机械 B=CONFIRMED → DEFECT（HTTP 语义恒真） |
| DEFECT-QDRANT-6（state_collections_delete_004） | Type3_RuntimeFailure | High | collections+delete 驱动；5xx 落在 points+query/upsert | D==SUPPORTS_DEFECT → DEFECT（human_review 建议） |
| DEFECT-QDRANT-7（vein_compound_or_min_should_15） | Type1_IllegalSuccess | Medium | POST /points/count (+scroll/query) | C=CONFIRMED + D=SUPPORTS_DEFECT；v1.19 上游已修复为 match-none |
| DEFECT-QDRANT-8（vein_type_mismatch_async_upsert_17） | Type1_IllegalSuccess | Medium | PUT /points (?wait) + update_vectors + batch | 机械 B=CONFIRMED → DEFECT；gt_bug_hit=9045 同型留痕 |

**数据质量留痕（人工复核建议）**：defect-2（geo_6）与 defect-3（points_count_2）的 chain verdict 内嵌 `perspective_analysis.aggregation_applied` 文本与终判 `verdict=DEFECT` 字面不一致（geo_6 写"保守分支 NEEDS_MORE_EVIDENCE"、points_count_2 写"SUPPORTS_NOT_DEFECT → NOT_DEFECT"），疑为 rework 前状态或模板残留；两案 rationale 均支持 DEFECT，按 verdict 字段生成报告，此处留痕供复核。

**并行 session 冲突标注（主进程补记）**：defect-2/3/4 三链出自并行 session（f8bfe48a）的 audit-r2c/r2d 终判覆盖（本 session 22:1x 三审曾判 geo_6=NME/points_count_2 为 R1 旧判 NOT_DEFECT/boundary_03 为 L1 排除项）。用户裁决采后判覆盖（16 链版）为基线；三链争议与 DISPATCH-LOG 留痕待人工复核，REPORT 不静默取舍。

**GT reach 双门分歧标注（主进程补记）**：defect-8（async_upsert_17）与 GT bug qdrant_9045（points/wait）现象同型，但 gt_reach_injector 机械 param 匹配未命中（meta param 复合串 "wait=false + points[].vector(...)" 归一化≠"wait"）——GTH 机械输出保持 0/2。机制改进项（复合 param 等值拆分）归档待办，不在本 session 现场改脚本。

## Rejected Candidates

（ADR-0008 无投票计数，Votes 列以 chain-auditor 根因/锚点替代；32 条全列于 chain_verdicts.json，下表为代表样本）

| Script ID | Rejection Reason | Votes (根因/锚点) |
|-----------|-----------------|------------------|
| vein_compound_or_points_count_4 | approx 计数精度为已接受限制 | approximate_by_design（#9523） |
| vein_geo_filter_points_count_5 | 同上 + indexing 未排除取证不足 | approximate_by_design |
| vein_null_check_points_count_3 | CardinalityEstimation::unknown exp=total/2 有单测固化 | approximate_by_design |
| vein_range_filter_points_count_1 | 同向冗余界无文档容差承诺 | approximate_by_design |
| boundary_collections_create_01 | serde #[serde(default)] 显式放行 + payload-only 维护者认可 | mundane_api_semantics |
| semantic_collections_create_017 | {} 为设计空态（Default/empty + TODO sparse） | mundane_api_semantics |
| boundary_collections_delete_01/02/05/12, semantic_collections_delete_001/002/006, state_collections_delete_001 | DELETE 幂等 result:false 为一等响应；契约 404 半边无 doc 授权 | contract_misread |
| semantic_aliases_update_003 | 脚本字段名 alias vs 契约 alias_name，400 正确拒绝 | request_param_typo |
| state_collections_create_002 / semantic_collections_create_018 / state_bhvr_cc001_fail_no_zombie_05 | WinError 10061 连接拒绝，0 请求达服务 | env_noise |
| state_bhvr_cc002_create_visibility_06 | str-in-[{name}] 成员测恒 False，客户端伪影 | script_error |
| vein_missing_endpoint_quotas_locks_12 | cloud/enterprise-only 仓内不可证 | contract_misread（human_review_note 保留） |
| vein_threshold_equality_search_9 | check_threshold 严格不等式为源码显式设计 | mundane_api_semantics（doc 矛盾留 human_review） |
| vein_range_filter_points_count_14 | gte2.5/lt7.5 截断真实但契约无 range 语义约束 | NEEDS_MORE_EVIDENCE（human_review 建议） |

## Coverage Summary

（coverage.json 为 R4 快照口径：units 24/86 = 27.9%，chunks 4/33）

| Endpoint (chunk) | Parameters Covered/Total | Constraints Covered/Total | Defects Found |
|----------|--------------------------|-----------------------------|---------------|
| chunk_aliases+update | — | — | 0 |
| chunk_collections+create-1of2 / -2of2 | 24/86 units attacked | 58 constraints 全局在册 | 累计 1（create_03） |
| chunk_collections+delete | — | — | 累计 1（state_004） |

points 端点族（count/upsert/query）为高产区：8 缺陷中 6 个落在该族。

## Debate Statistics

| Stage | Scripts/Pending | Approved | Rejected | Tie-broken |
|-------|-----------------|----------|----------|------------|
| Stage 1 (Test Gen) | 113（4 轮派发） | N/A（无投票留痕） | N/A | N/A |
| Stage 2 (chain-auditor 终判, ADR-0008) | 41 链（累计 R2-R4） | 8（DEFECT） | 32（NOT_DEFECT） | 1（NME：range_filter_14） |

注：mine_state rounds 数组含一条 round=2 重复记录（10/1 与 9/4 并存），Scripts Generated=113 为四条独立轮求和，重复行未重复计入。

### Evidence Chain Completeness（8 份报告口径）
- Ring 1 present: 4/8（defect-3/4 机械 constraint_id；defect-5/8 builder 重锚；其余 4 案契约结构性缺失，doc+source 锚补位并标注 MISSING）
- Ring 2 present: 8/8（verified 1 — defect-4 curl 200；degraded 7 — domain_blocked，经 alternate reader/本地快照/endpoint_registry 核验）
- Ring 3 present: 8/8（output_*.log 全部落盘含 VERDICT 行，reporter 逐一读取核实）
- Complete chains: 4/8（严格三环全 PRESENT）；4/8 Ring1 doc-anchored（INCOMPLETE_EVIDENCE，按降级策略生成，chain-auditor 终判 DEFECT）
- Incomplete (blocked): 0

## Pre-Submit Gate 留痕
- reporter 本次调用无执行类工具：live curl 复跑与 ai_failure_check.py（M1-M7）未执行。Ring 3 证据 = evidence-builder 双盲取证 + chain-auditor 三查复核 + output_*.log 原始 VERDICT 行（8/8 已由 reporter 直接读取核实，与链内引用一致），待 verify_defects.py 机械验证。
- Ring 2 url_status 如实标注（verified 1 / degraded 7 / unreachable 0），无编造引用。

## Reflection Context (for next round)

```json
{
  "key_learnings": [
    "serde untagged/Option 回退路径吞校验是 qdrant 1.18 高产缺陷面（create_03 datatype、async_upsert_17 同根因家族）",
    "异步 wait=false 反馈通道缺失（send_feedback sender=None 连日志都没有）——校验存在但结果不可达",
    "契约结构性空白是主要断链来源：geo lat 域 / datetime range 界限类型 / min_should / lifecycle 并发——4/8 缺陷 Ring1 MISSING",
    "同请求双路径对照（indexed vs unindexed、exact vs approx、wait=true vs false）是最有效隔离手法"
  ],
  "rejection_patterns": [
    "approximate_by_design：#9523 锚点命中即出局（count 精度类候选全灭）",
    "contract_misread：契约把幂等 result:false 回填为 404 半边，无 doc 授权（collections+delete 族 8 连拒）",
    "env_noise：容器事故窗口 WinError 10061，无服务端行为可观测",
    "mundane semantics：payload-only / lenient parsing 维护者锚点（'fine and expected'）"
  ],
  "high_value_endpoints": [
    "points+count（filter 语义分叉：四缺陷）",
    "points+upsert（async 校验反馈缺失；f32 溢出）",
    "collections+create（untagged 回退）"
  ],
  "exhausted_endpoints": [
    "collections+delete 404-语义族（8 候选全拒，coalescing 幂等被集成测试锁定）",
    "points+count approximate 精度族（#9523 by-design 覆盖，除非发现非估计语义新分叉）"
  ]
}
```

## Output Files

- `defects/defect-1.md` — datetime range integer 界限静默接受 + 语义分叉（Type2）
- `defects/defect-2.md` — geo 极点 lat=90 indexed 路径静默假阴性（geohash 位折叠，Type2）
- `defects/defect-3.md` — approximate count 类型错配返回 N/2 常数（Type2）
- `defects/defect-4.md` — 非法 datatype 200 接受（serde untagged 回退，Type1）
- `defects/defect-5.md` — 超 f32 分量 200 接受 → null 读回 + null score 排第一（Type1）
- `defects/defect-6.md` — delete/recreate 竞态窗口 16x 500（Type3，human_review 建议）
- `defects/defect-7.md` — min_should 空 conditions + min_count>=1 全库匹配（v1.19 已修复，Type1）
- `defects/defect-8.md` — wait=false 写路径非法向量 200-ack 后静默丢弃（gt_bug_hit 9045，Type1）
- `mre/defect-{1..8}-script.py` + `mre/Dockerfile.mre` + `mre/docker-compose.yml` + `mre/README.md` — reporter-mre Agent 产出（另行生成）
- `debate_logs/chain_verdicts.json` — 确认源（41 链终判）

---

*Generated by TestVDB*
