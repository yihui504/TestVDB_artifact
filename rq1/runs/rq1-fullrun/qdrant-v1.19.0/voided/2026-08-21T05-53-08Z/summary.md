# qdrant v1.19.0 · RQ1 全量 #3 · 汇总（session 2026-08-21T05-53-08Z）

> ⚠️ reporter-generated=false (main-process fallback)——reporter 两次未落盘，主进程实测门（mine.md 8f）代写

## 时长
A1 2026-08-21T05:37:44Z → 收口 07:28:52Z = **1h51m**（R1 ~75m / R2 ~35m）

## 判定流
- 2 轮 14 链 = **7 DEFECT / 7 NOT_DEFECT / 0 NME**
- Novelty gate：0 NOVEL / 3 BY_DESIGN / 2 BY_DESIGN_SUSPECTED（score_threshold ×2 挂 PR#9561）/ 2 UNVERIFIED
- 归档分支未触发（0 COVERED_BY_PR 终态）

## GT reach：1/1 all_reached ✅
- qdrant_10120（exact）↔ vein_cardinality_oracle_is_empty_matrix_1 **DEFECT**
- 翻案过程（方法论亮点）：R1 is_null 链被 approximate_by_design 驳 → R2 直击 GT 触发面 is_empty：4 规模矩阵（10/50/100/200 全 ~65% 比率方向一致）+ **对照组 is_null 0% 散度**（估计器可精确）+ 根因指认（只数 MISSING 漏 NULL 公式级缺陷）→ DEFECT 终判
- **官方交叉印证**：GT 10120 fix PR#10128 "stop underestimating is_empty cardinality by 1/3"——现象/条件/根因方向全对上；gate 独立查到相邻 PR#10116（初判 COVERED_BY_PR 降 UNVERIFIED 保守）

## 契约与覆盖
- doc_coverage 97.3%（73/75 机械）；契约 75 端点 56 带参（enrich 352 字段）；GT 参数面 1/1（count 端点带 exact）
- KNOWLEDGE_DEGRADED：extractor 400 → Task 4a（复用 v1.18.2 概念 + v1.19.0 spec 补全）

## 过程事件（全记录）
1. executor 未设 TESTVDB_DB_URL ×31 全超时假象 → 主进程批量重跑（13 DEFECT/16 NO_DEFECT/2 SE）
2. NaN/Inf 2 脚本：客户端 InvalidJSONError 判定修正（服务端不可测路径，NO_DEFECT-client-layer）
3. vein 3 脚本 bare .json() 合规化（json.loads）
4. 2 脚本 sys.exit(main()) 吞 VERDICT → rc 中转打印修复
5. auditor summary 计数错 1 次（5/8 vs 实际 6/7）——中止条款 2 触发，机械校正
6. builder 主动识别 2 个假阳性（verdict 与 log 矛盾）——链层质量把关有效
7. reporter summary 两次未落盘（实测门 SUMMARY-MISSING 确认后 fallback 代写）

## 系统性观察
- executor env 遗漏跨版本复现（pilot rerun + 本版）——C4 派发词已带指令但仍漏，考虑 executor agent 规范里加 Step 0 env assert
- approximate_by_design 抗辩的对抗证据模式（规模矩阵+同端点对照组）已验证有效，GT 10120 翻案即例证
