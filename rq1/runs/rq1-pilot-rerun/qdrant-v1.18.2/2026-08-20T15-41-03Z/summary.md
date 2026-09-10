# qdrant v1.18.2 RQ1 Pilot Rerun 汇总（session 2026-08-20T15-41-03Z）

## 核心结果：GT reach 4/4（all_reached=true）

| GT bug | param | 命中链 | 现象 |
|---|---|---|---|
| qdrant_9017 | hnsw_ef | vein_params_hnsw_ef_zero_points_search_1 (DEFECT) | params.hnsw_ef=0 被接受，SearchParams 无下界校验 |
| qdrant_9421 | recover | vein_cluster_standalone_1 (DEFECT) | POST /cluster/recover standalone 返 500 应 4xx（issue #9421 同现象复现） |
| qdrant_9520 | shard_number | vein_replication_gt_shards_collections_create_1 (DEFECT) | replication_factor>shard_number 无效组合被接受（多值 param 拆分命中） |
| qdrant_9522 | lookup_from | vein_lookup_from_points_query_1 (DEFECT) | lookup_from 引不存在 collection 静默 200 |

上轮 pilot：reach 1/4（GT 3/4 不在 10 端点契约）。本轮 4/4。

## 与上轮 pilot 对比（修复效果验证）

| 维度 | 上轮 (06-28-05Z) | 本轮 (15-41-03Z) | 驱动修复 |
|---|---|---|---|
| 契约端点 | 10 | 76 | fetch_openapi_spec + spec 机械补全 |
| doc_coverage | 自报 100%(70/70) 实为 12% | 97.3% (73/75 机械核对) | validate_doc_coverage 机械覆写 |
| chunking units | 20（constraints 0 进块） | 42（constraints 19 全进） | chunk_contract 三桶归一化 |
| vein meta param | 7/7 缺失 | 2/2 R1 + R3 4/4 全带 | attack-vein.md 内联模板 |
| GT reach | 1/4 | 4/4 | 契约扩容 + _norm_multi 拆分 + 白名单后缀对齐 |
| novelty gate | 12 NOVEL / 0 已报告 | 2 NOVEL / 2 COVERED_BY_PR(PR#1463) / 11 UNVERIFIED | gate 参数路径修复后查到真实 PR |

## 判定流数字

- 轮次：3（R1 collections+create / R2 query+cluster 纵深 / R3 params+分布式配置）
- 脚本：33 老三套 + 16 vein
- 证据链：17（15 DEFECT / 2 NOT_DEFECT）
- Novelty gate：2 NOVEL（has_id / hnsw_ef=0）+ 2 COVERED_BY_PR（m/ef_construct 下界，PR#1463 已归档）+ 11 UNVERIFIED（保守路径）
- Issue 草稿：2（NOVEL only）；MRE 待生成

## 途中事件（诚实记录）

1. **容器内存打满**（R1 执行中 1.87G/2G）：资源极限类脚本耗尽内存 → 后续请求全超时 → builder 识别 8 条链 Grade D → 主进程重启容器 + 全部 33 脚本健康重跑（19 候选替代 21，2 翻 NO_DEFECT）。教训：资源极限策略脚本应有容器内存监控/轮间重启
2. **extractor 3×HTTP 400**（glm proxy）→ Task 4a 降级：复用上轮 knowledge + spec 机械补全 65 端点骨架（97.3% 覆盖）
3. **formalizer 不消费骨架条目**（65 端点 0 parameters）→ 主进程从 spec 机械搬参数（21 端点 patched + create collection 字段补全）——机制级修复待落 formalizer 规范
4. **vein 脚本 URL 缺 /collections/ 前缀 ×2**（geo/lookup 404 假象）→ 修复后 lookup_from 命中 GT
5. **injector 匹配粒度**：GT 裸名 vs agent 路径名（params.hnsw_ef）不匹配 → _reached 白名单后缀对齐 + _norm_multi 多值拆分（shard_number 命中）

## 遗留待办

- [ ] formalizer 消费 spec 骨架条目的机制化（本轮主进程手工 patch）
- [ ] reporter summary.md 虚报未落盘（本轮主进程代写）——reporter.md 规范需加落盘自验证
- [ ] MRE 生成（2 NOVEL）
- [ ] 11 UNVERIFIED 的 GitHub API 深查（当前 token 限流下查重不全）
