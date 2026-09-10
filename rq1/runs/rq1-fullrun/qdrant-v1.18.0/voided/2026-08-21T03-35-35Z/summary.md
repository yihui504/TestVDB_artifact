# qdrant v1.18.0 · RQ1 全量 #1 · 汇总（session 2026-08-21T03-35-35Z）

## 时长
- A1 起 2026-08-21T03:12:53Z → D7 收 2026-08-21T05:25:21Z = **2h12m**（R1 ~70m / R2 ~30m / R3 ~30m 含收口）

## 判定流
- 3 轮（R1 upsert/search 块 / R2 vector 静默丢弃纵深 / R3 wait 语义 + scroll 补面）
- 15 证据链 = **10 DEFECT / 5 NOT_DEFECT / 0 NME**（2 次 NME 补证轮：vector_dim ×2 源码补证、wait constraint 错位修正）
- Novelty gate：**0 NOVEL / 3 COVERED_BY_PR / 7 BY_DESIGN / 0 UNVERIFIED**
  - COVERED_BY_PR（已归档 archived/manifest.json）：batch 上限 PR#9261、维度校验 ×2 PR#4312——「发现已被报告 bug」列 3 条
  - 无 NOVEL → 不产 issue 草稿（符合规范）

## GT reach（双确认口径）
| 口径 | 结果 | 明细 |
|---|---|---|
| injector param 匹配 | **1/2** | wait ✓（vein_wait_semantics_points_upsert_1 DEFECT）；vector 未中——命名粒度缺口（GT 裸名 vector vs meta param "points[].vector (dimension)"） |
| 语义对齐（LLM 盲评待复核） | **2/2** | GT 9039（dimension-mismatch 静默丢弃）↔ dim_001 + type_mismatch_upsert_1 双链 DEFECT；GT 9045（空vector）↔ dim_002 + type_mismatch_upsert_2 + wait_semantics 三链 DEFECT（9045 的 panic 路径档1.5 已证 standalone-unreachable，静默丢弃路径已测达） |

## 契约与覆盖
- doc_coverage **97.3%**（73/75 机械核对）；契约 19 端点全带参（enrich 回填 67 字段）；GT 参数面 2/2
- KNOWLEDGE_DEGRADED：extractor glm proxy 400×2 → Task 4a 降级（复用 v1.18.2 概念 + v1.18.0 spec 机械补全 65 骨架）

## 过程修复（retry/脚本质量，全记录）
- vein 6 个 f-string VERDICT → 字面量（log 结论保真回填）
- state ×2 scroll 字段 data→points（假 SCRIPT_ERROR 根因）
- boundary_malformed headers 重复传参
- R3 三脚本 POST→PUT 建集合 + data= 签名（修正前 3 个假 NO_DEFECT，修正后 2 翻 DEFECT）
- semantic id_types 判定逻辑（正确拒绝 ≠ SCRIPT_ERROR）
- compound_and_points_upsert 重跑翻 NO_DEFECT（时序抖动，诚实记录不改判）

## 系统性发现（跨版本关注）
1. **GT param 粗名 vs agent param 路径名的粒度缺口**：vector/wait 类 GT 裸名在 injector 白名单对不上复合路径名——建议后续版本 meta param 用裸参数名（已在 R3 派发词要求，R1/R2 产物带说明括号）
2. reporter summary.md 虚报未落盘再现（规范 test -s 自验证未被执行）——本文件为主进程代写
3. v1.18.0 精确源码 clone（.qdrant-src-1180）显著提升 NME 补证轮质量——后续版本 SOP 建议加"源码预 clone"步骤
