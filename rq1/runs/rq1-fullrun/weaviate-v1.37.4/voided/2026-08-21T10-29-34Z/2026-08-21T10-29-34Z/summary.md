# TestVDB Mining Summary — weaviate v1.37.4（全量 #4）

**Session**: weaviate-v1.37.4-2026-08-21T10-29-34Z
**Duration**: A 段起 2026-08-21T07:44:10Z 至收口约 13:50Z ≈ 6h06m（含 runtime.py 机制缺失与 auditor 6000-token 限制的现场修复耗时）

## Results Overview

| Metric | Value |
|---|---|
| Rounds | 2（R1 29 脚本 / R2 vein 2 脚本） |
| 链数 | 18（fan-out 全量） |
| DEFECT / NOT_DEFECT / NME | 10 / 7 / 1 |
| Novelty | 1 NOVEL / 9 BY_DESIGN_SUSPECTED / 0 UNVERIFIED |
| retry 子循环 | 坏脚本 0（regression 无超限；18 verdict_missing 为 f-string 静态误报记录不阻断） |

## GT Reach（2/3，injector param 匹配口径）

| GT | 判定 | 证据 |
|---|---|---|
| 11399 dynamicEfMin 倒置 | **REACHED** | boundary_schema_dynamicEf_inverted + dynamicEfMax_negative + dynamicEfMinOnly（chain DEFECT，A=CONFIRMED 契约配对断言） |
| 11400 flatSearchCutoff 负值 | **REACHED** | boundary_schema_flatSearchCutoff_negative + _zero（chain DEFECT，B=CONFIRMED 数值下界） |
| 11401 replicationFactor=-1 | **NOT_DEFECT 未达** | by_design 显式归一（源码 Factor<1→1）+ R2 实测 POST 响应回显归一值——**GT 描述 "silently normalized" 与 v1.37.4 实际不符**，按 9045 同模式单独分析不进 reach |

## 双确认口径
- injector param 匹配：2/3
- 人工 LLM 盲评：待人工复核（11401 无 DEFECT 链；11399/11400 两条 GT 链为机械 A/B 定案，盲评需复看）

## 关键机制发现（首跑 weaviate 特有）
1. **runtime.py 机制缺失**：规范强制 `from runtime import get_runtime` 但模块从未落盘——23 脚本全 ImportError，主进程应急实现（三态 judge_schema_attack + 三元组 + graphql str body）
2. **auditor 6000-token 输出限制**（用户全局 CLAUDE_CODE_MAX_OUTPUT_TOKENS）：12→6→3→1 链批次全超，改"纯文本判定行+主进程落盘"模式后才过——审计层判定仍 100% 出自 auditor
3. weaviate GET /schema/{class} 返回 class 对象本身（无信封）——2 个 state 脚本的解析 bug 现场修复
4. healthcheck 误报（容器无 curl）——API ready 200 即健康

## 修复与待办（全量后续版本）
- runtime.py 缺失：**待修 pipeline/主插件**（scripts/runtime.py 落盘 + executor 派发词注 sys.path）
- auditor 输出限制：全量 SOP 建议 auditor 固定用"文本判定行"模式
- fetch spec 规则对 weaviate 覆盖不足（POST /schema 无 requestBody）——Go 源码机械提取参数面补位，已工作

## Novelty Gate
1 NOVEL（vein_range_filter_schema_vi_ints_1：HNSW int 参数校验不对称——ef=-5/0、vcm/cleanup/pq.centroids=-1 被 200 持久化，同对象 maxConn/efConstruction 422）
9 BY_DESIGN_SUSPECTED（8 条 PR#11439 + 1 条 PR#12457 + 1 条 PR#11824 关联）

## Coverage
doc_coverage 97.1%（机械核算；raw_knowledge = KNOWLEDGE_DEGRADED 纯 spec 骨架 + Go 源码提取）
契约 101 端点；GT 3 参数全进契约（B7 1/1→实际 3/3 经源码机械提取补位）
