# weaviate v1.37.4 · RQ1 全量 #4 · 汇总（session 2026-08-21T08-15-40Z）

> ⚠️ reporter-generated=false (main-process fallback)——reporter 未落盘 summary（实测门 SUMMARY-MISSING），主进程代写

## 时长
A1 2026-08-21T07:44:10Z → 收口 09:43Z ≈ **2h**（B 段降级处理 ~30m / R1 单轮 ~60m / 补证×2 ~20m）

## 核心结果：单轮达成 GT 3/3 all_reached ✅
| GT | param | 命中链 |
|---|---|---|
| weaviate_11399 | dynamicEfMin | boundary_schema_dynamicEf_inverted + Min 系列（DEFECT） |
| weaviate_11400 | flatSearchCutoff | boundary_schema_flatSearchCutoff_negative（DEFECT） |
| weaviate_11401 | replicationFactor | boundary_schema_replicationFactor_negative（补证翻案 DEFECT） |

## 判定流
- 1 轮 11 链 = **10 DEFECT / 1 NOT_DEFECT / 0 NME**（终态）
- 两次补证：①replicationFactor NOT_DEFECT→DEFECT（回读矩阵 -1→1 静默 vs 2→422 拒绝的不一致性 + 三无源码 + 官方 issue 语义）②membership NME→NOT_DEFECT（auto-schema by-design 源码证实）
- Gate：**1 NOVEL**（vein_compound_and_schema_pairing_1，已出 issue 草稿）/ 8 BY_DESIGN_SUSPECTED / 1 UNVERIFIED
- **强交叉印证：8 条配置面 DEFECT 全挂 PR#11439**——正是 GT 三 bugs 的官方修复 PR，发现面与官方修复 100% 重合（非 endorsed 但作为「已报告 bug 重合」证据价值等价）

## weaviate 首跑特记（SOP 素材）
1. GitHub tag spec 规则 OK（69 paths）但 **spec 无 requestBody**、embedded_spec.go 也无 index 参数枚举——源码 Go struct（hnsw/config.go json tag）是 index 配置参数唯一可靠来源；formalizer 源码参数块 + enrich（205 字段）补齐，B7 3/3
2. KNOWLEDGE_DEGRADED 最重形态：extractor 400 + 无旧版本可复用 → 纯 spec 骨架降级（概念文档缺失，constraints 近空，A 视角多为 GREY_ZONE——B/C 裁决仍达成 all_reached）
3. 无 threat_model（intelligence 未采集）——vein 纯 contract 自判仍工作；D 视角标 NOT_AVAILABLE
4. 容器 healthcheck 误报 unhealthy（镜像无 curl）——API 实测 ready 200 放行

## 产出
defects/defect-1.md + issues/issue-vein_compound_and_schema_pairing_1.md（NOVEL 唯一 endorsed）
