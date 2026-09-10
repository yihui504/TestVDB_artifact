# DISPATCH-LOG — #1 重跑 qdrant v1.18.0（R1-R11 纪律轮，2026-08-23 起）

> 派发登记义务：R8（model 覆盖披露）+ R6（派发词=纯任务参数）。
> 本轮全部 agent 用插件原生 model（无覆盖）除非单条注明。

## 环境前置（主进程机械操作，A 段）
- A1 gt.json 拷入 cache（231B，2 bugs：9039=points/vector、9045=points/wait⚠️standalone-unreachable 单独报）
- A2 cache 侧 v1.18.0 无旧产物（干净）
- A3 spec 预取：fetch_openapi_spec.py → 62 paths（.sourcedeps/qdrant/v1.18.0/openapi.json）
- A4 容器：QDRANT_VERSION=v1.18.0 compose up → healthy
- A5 版本核验：GET / → 1.18.0 (commit db3fca3)；collections 空
- A6 源码 clone：.qdrant-src-v1.18.0（depth 1，1675 files）——**只进 extractor/formalizer/builder 词，禁入 attack 词（R8）**

## 派发 #1（B1）
- agent: testvdb:knowledge-extractor，name=ext-1180，model=原生（未覆盖），run_in_background
- 派发词逐字：
```
按照 agents/knowledge-extractor.md 规范，为 qdrant v1.18.0 提取 API 文档知识。

任务参数：
- target=qdrant version=v1.18.0（版本锚定：文档、源码、实测均以该版本为准，不得混入其他版本特征）
- 源码位置（该 tag 精确源码，可 Grep/Read 取证）：<HOME>/.claude/plugins/cache/testvdb/testvdb/2.3.0/.qdrant-src-v1.18.0
- 活体实例：http://localhost:6333（qdrant v1.18.0，空库，可实测请求/响应信封）
- 输出：<HOME>/.claude/plugins/cache/testvdb/testvdb/2.3.0/results/qdrant/v1.18.0/raw_knowledge.md
```
- R9 核对：零预期值（未传端点数/信封形态/前版怪癖）✓

## 派发 #2（R1 重派，2026-08-23 15:1x）
- 中断处置落地：四 attack agent 原词重派（GT_HINT 段修正为 injector 原文，其余逐字同 #1；差异说明见 ops-prompts-run2 存档）
- agent: testvdb:attack-boundary@atk-boundary-r1 / attack-state@atk-state-r1 / attack-semantic@atk-semantic-r1 / attack-vein@atk-vein-r1，全部原生 model（未覆盖），run_in_background
- 容器恢复：A4 白名单动作重起（healthy，版本核验 1.18.0/db3fca3 同 A5）
- R8 核对：四词均无源码路径/无方向点名/无跨轮经验 ✓（vein 词的 TESTVDB_DB_URL=http://localhost:6333 为上轮原词字段）

## 进度补记（2026-08-23 晚，R1 收口 → R2 复审；逐字派发词见 docs/ops-prompts-run2/run2-01-qdrant-v1.18.0.txt）
- R1 全轮：17 脚本（12 三套+5 vein）→ 6 候选 → L1 0 REFUTED → 6 链 → auditor 全 NOT_DEFECT
  （approximate_by_design×5 + request_param_typo×1）→ C11 继续条件成立 → R2
- R2 全轮：26+3 脚本 → 46/46 执行（C10 OOM 事故×2：boundary_07 rl_11 容器杀手，处置=b 不重跑+容器恢复）
  → 15 候选 + §4.4 补录 07 = 16 → L1 1 REFUTED（boundary_03 guc_timing）→ 14 UNCERTAIN
  → R2 新 9 候选建链（8 新链 + semantic_003 复用 R1 链）→ audit-r2a 判定：DEFECT=1
  （vein_type_mismatch_datetime_range_8）/ NOT_DEFECT=12 / NME=1（geo_6 带工单）
- 补证轮：boundary_07 补链（20:06）+ geo_6 补证链重写（20:45，重派 b2-bld-vg6-rw2 成功）
- 复审三段波折：20:4x 首派 → 主进程重启中断 → 21:0x 原词重派 → BATCH_LIMIT_EXCEEDED 打回
  （15 .done > 12 上限；boundary_03 "builder_missing" 系误报——L1 REFUTED 排除项留痕在案）
  → 21:1x 分批重派（批1=boundary_07+geo_6 两链，14 已判链不重审）
- 镜像补欠：B 段 6 件 + session 快照 359 文件 → 本目录（R7）

## R2 收口 + R3 派发（2026-08-23 22:1x-22:3x）
- R2 收口：三件套更新（mine_state round2 / coverage 14/86=16.3% / experience_handoff R2 经验）+ strategy_extractor 0 条 + pipeline_state → R3 + 8j restart 核验 1.18.0/db3fca3
- R3 8a 采集：TMA 126 行同模式；GTH 0/2 持平（无倒退 ✓）；strategy 无
- R3 块=chunk_collections+create-2of2（8 单元：range_create_002-004 + state_create_001 + behavioral_create_001-003 + bc_create_query_visibility_001）——mine.md 8b 第 R 轮派 chunks[R-1] 顺序消费
- R3 四 attack 派发（8b 模板逐字；reflection_context=R2 经验；boundary 首调 JSON 损坏重试成功）
- 注：R2 实发词 /tmp 留证随主进程重启丢失；R3 起四词全文直接追加至 docs/ops-prompts-run2/run2-01-qdrant-v1.18.0.txt（R7 教训）
- geo_6 状态：终局上报 NME（rework_order=null，计数 2/3 不增），待用户人工复核，不阻塞流程

## ⚠️ 并行 session 冲突发现与处置（2026-08-23 23:0x，本 session f8bfe48a 记录）
- **事实**：本 session 与另一 session（b20f4b88）在 2026-08-23 晚并行推进同一实验（#1 qdrant v1.18.0，session 2026-08-23T05-48-00Z）。对方在 R1 中断后接管（其 memory："R1 四 attack 中断，SendMessage 恢复被拒"→重派），两主进程先后/交叉向同一 session 目录派发。
- **R2 终态分歧**：
  - 本 session 落盘：16 链 DEFECT=4 / NOT_DEFECT=12 / NME=0（audit-r2c 全量 14 链终判 + audit-r2d 2 链终判；geo_6 经 3 轮补证翻案 DEFECT）
  - 对方 memory 记录：15 链 DEFECT=1 / NME=1（geo_6 三审仍 NME 待人工复核）——系其未见本 session 23:0x 前的终判落盘时的旧状态
  - **以最新落盘 chain_verdicts.json（16 链 DEFECT=4）为准**——判定 100% 出自 auditor，两轮终判均合规，后判覆盖先判（auditor 每轮全量重判语义）
- **处置**：本 session 停止向该 session 目录派发（避免互踩）；对方 session 正在推进 R3（32 个 R3 脚本已落盘，四 attack 进行中）。R2 判定定版如上，R3 及后续由单 session（对方）继续。
- **待用户裁决**：①是否接受并行双 session 事实上的分工（R1 恢复+R2 双轮审计与本 session，R3+ 对方）；②R2 终态以 16 链 DEFECT=4 为准是否确认。

## ⚠️ 并行 session 冲突——b20f4b88（本 session）确认记录（2026-08-23 23:2x）
- 本 session 读到 f8bfe48a 的冲突留痕与 23:00 落盘的 chain_verdicts.json（16 链 DEFECT=4/NME=0），确认并行事实
- **时间线关键点**：本 session 21:0x-22:1x 走完 R2 复审→geo_6 二轮补证→三审（终判 NME，rework_order=null，"契约结构性缺失非取证可解，转人工复核"）并 22:1x 落盘 15 链终态 + R2 收口（三件套/round3/restart）；f8bfe48a 在几乎同一窗口并行做 audit-r2c 全量终判（22:1x，geo_6 判 DEFECT"第3轮补证翻案"）+ null_check_3 补证 + boundary_03 补建链 + audit-r2d（23:0x 落盘 16 链）+ 其自身的 R2 收口
- **本 session 视角的三处疑点**（供用户裁决参考，非判定）：
  1. geo_6：本 session 三审 auditor 终判 NME 且明示 rework_order=null/builder 无可补/工单计数 2/3 不增；f8bfe48a 的 audit-r2c 同链判 DEFECT——两个独立 auditor 对同链相反终判，且其"第 3 轮补证"工单来源与本 session rework_state 记账（2/3 终局）冲突
  2. vein_type_mismatch_points_count_2：R1 audit 判 NOT_DEFECT（approximate_by_design + #9523 认知锚点）；audit-r2c 翻案 DEFECT（类型恒真 B=CONFIRMED）
  3. boundary_collections_create_03：L1 机械闸门 REFUTED（guc_timing，verify_live_l1.json 留痕）的排除项，f8bfe48a 于 22:4x 补建链并判 DEFECT——L1 REFUTED 候选建链偏离 8e.5 流程（除非主张 L1 误杀，需程序性说明）
- 本 session R3 进度（与裁决独立）：四 attack 31 脚本 + semantic runtime 修复闭环 + C6 提取 8 新候选 + 8 builder 建链（7 完成 1 运行中）；**R3 auditor 派发暂缓至裁决**（其增量判定基线取决于 R2 终态版本）
- 双方一致项：对方停止派发、R3+ 归本 session 单线推进、判定 100% 出自各自 auditor（无主进程越权判定）、待用户裁决 R2 终态

## R3 全轮收口 + R4 派发（2026-08-24 00:2x，b20f4b88 单线）
- 冲突后续：用户裁决对面停、本 session 单线；基线=16 链版（后判覆盖），三争议链留痕待人工复核
- R3 audit 批1（8 新链）：DEFECT 1（f32 溢出，机械 B=CONFIRMED）/ NOT 5 / NME 2 → 两 NME 补证（qlock 拆分重做 / thre 对称实验）→ 复审均 NOT_DEFECT（保守收口 / C=REFUTED 真 by-design）
- **全会话终态（R3 后）：24 链 = DEFECT 5 / NOT_DEFECT 19 / NME 0**
- R3 事故披露：semantic runtime import 事故（R2 11 个+R3 9 个同因失败，工具漏检，打回修复闭环）；429 限流中断×3（SendMessage 恢复）；auditor 6000-token 截断×3（SendMessage 恢复）
- C11：GTH 0/2 未 all_reached → R4=最后一轮（满 4 轮收口），块=chunk_collections+delete（2 单元）
- R4 四 attack 已派（8b 模板逐字，词全文落 ops-prompts 存档）

## ✅ #1 重跑终记（2026-08-24 02:4x，b20f4b88 单线收官）
- **R4 判定**：批1（11 链）DEFECT=1（stdel004 race 500，D 盲区命中）/ NOT=10；批2（6 链）DEFECT=2（vein_15 min_should + vein_17 async upsert 机械 B=CONFIRMED）/ NOT=3 / NME=1（vein_14 转人工复核）
- **全会话终态 41 链：DEFECT=8 / NOT_DEFECT=32 / NME=1**；终止=C11 满 4 轮（GTH 0/2 未达标）
- **D 段**：reporter 8 份 defect-N.md（summary.md 主进程 fallback 落盘，harness 拦截 subagent 写报告）→ verify_defects 双门 **8/8 CONFIRMED**（find_logs 模糊匹配缺陷机械修复后过，§4.1 披露）→ novelty_gate：**1 NOVEL**（min_should_15）/ 5 covered-by-PR（#9557×3 geo/datetime/points_count 族、#10291 create_03、stdel004 param 不可用）/ 2 UNVERIFIED（f32_13、async_upsert_17 留位人工复核）→ reporter-mre 8/8（py_compile 全过）→ issues/ 1 份 NOVEL 草稿 + archived/ 5+manifest
- **GT reach**：机械门 0/2（async_upsert_17 与 GT#9045 points/wait 现象同型但复合 param 归一化不匹配——双门分歧留痕 summary.md，机制改进项归档）
- **人工复核清单（5）**：geo_6 / points_count_2 / boundary_03（并行 session 争议翻案链）+ stdel004 / vein_14（auditor 建议复核）+ f32_13 / async_upsert_17（gate UNVERIFIED）
- **总时长**：A1 起 2026-08-23 13:48 本地 → D 段完 2026-08-24 02:45 本地 ≈ 12h57m（含主进程重启×2 + 并行 session 冲突窗口 + 容器事故×3 处置；轮次明细：R1≈3.5h / R2≈5h（含交叉与补证三轮）/ R3≈2h / R4≈2h / D≈0.7h）
- 9c：strategy 0 条；容器 down -v + network rm；终镜像 938 文件 → 论文仓
