# Defect 1: HNSW vectorIndexConfig 整数参数校验不对称 — ef/vectorCacheMaxObjects/cleanupIntervalSeconds/pq.centroids 非法值被 200 持久化，同对象 maxConnections/efConstruction 被 422 拒绝

## Metadata
- Defect ID: TESTVDB-WEAVIATE-1
- Type: Type1_IllegalSuccess
- Severity: Medium（ADR-0008：判定管线已不产 severity；由 Type 推断 Type1→Medium，仅人工分流参考）
- Endpoint: POST /schema
- Discovered: 2026-08-21T13:47:15Z

## Novelty Gate 汇总（本报告依据）
- **gate_grade**: NOVEL（gate 层，`no_known_hits`，confidence HIGH，endorsement=true）
- **gate_evidence_url**: （无 — Novelty Gate 未检索到已知 issue/PR/官方修复记录）
- **endorsement_reason**: "No known hits"
- **同链其余 9 条候选**: BY_DESIGN_SUSPECTED（corrector 层，PR#11439/PR#12457/PR#11824 关联），**不生成 issue、不纳入本报告**

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: `POST /schema` 端点契约（structured_contract.json api_endpoints["/schema"].POST）+ 源派生参数契约 `ef`（raw_knowledge.md "Source-derived Index Config Parameters"）
- **contract_assertion**: `vectorIndexConfig` 整数参数经 POST /schema 提交时，非法值（超出有效域、非哨兵值）应被一致性拒绝；`ef` 的合法哨兵值仅为 `-1`（含义 "let Weaviate pick"），其余负值与 0 不属于有效输入域
- **expected_behavior**: 同一 vectorIndexConfig 对象内的整数参数应使用一致的校验规则——非法值返回 4xx 且**不持久化**。实测对照：同对象 `maxConnections=-1`、`efConstruction=-5` 返回 422，则 `ef=-5/0`、`vectorCacheMaxObjects=-1`、`cleanupIntervalSeconds=-1`、`pq.centroids=-1` 应同样被拒绝
- **source_url**: https://github.com/weaviate/weaviate（entities/vectorindex/hnsw/config.go，v1.37.4 源码机械提取）
- **备注**: structured_contract.json 中 `constraints.range_constraints` 为空（type/range/state 均无显式约束）——本缺陷正是"契约未声明边界 + 实现校验不对称"的组合：部分参数有运行时校验（422），部分参数无校验（200 静默持久化）

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://github.com/weaviate/weaviate（entities/vectorindex/hnsw/config.go，tag v1.37.4）
- **doc_version**: v1.37.4（与目标版本一致）
- **doc_quote**: `DefaultEF = -1 // indicates "let Weaviate pick"`（raw_knowledge.md 源派生参数表，v1.37.4 Go 源码机械提取；另含 `MaxConnections int \`json:"maxConnections"\``、`EFConstruction int \`json:"efConstruction"\``、`EF int \`json:"ef"\``、`VectorCacheMaxObjects int \`json:"vectorCacheMaxObjects"\`` 等 json tag）
- **url_status**: degraded（本会话 judge-doc 为 N/A，未直接 curl 验证 GitHub 源码 URL；原始文档为 raw_knowledge.md 机械提取的 v1.37.4 Go 源码内容，版本匹配）
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)
执行日志 `output_vein_range_filter_schema_vi_ints_1.log`（会话根目录，Read 实测验证，含 VERDICT 行）逐行证据：

| 候选/对照 | 参数值 | HTTP | 读回（GET read-back） |
|-----------|--------|------|----------------------|
| candidate ef | -5 | **POST=200** | **readback=-5**（持久化） |
| candidate efZero | 0 | **POST=200** | **readback=0**（持久化） |
| candidate vectorCacheMaxObjects | -1 | **POST=200** | **readback=-1**（持久化） |
| candidate cleanupIntervalSeconds | -1 | **POST=200** | **readback=-1**（持久化） |
| candidate pq.centroids | -1 | **POST=200** | **readback=-1**（持久化） |
| control maxConnections | -1 | POST=422 | `{"error":[{"message":"class.VectorIndexConfig can not parse: parse vector index config: invalid hnsw config: maxConnecti...` |
| control efConstruction | -5 | POST=422 | `{"error":[{"message":"class.VectorIndexConfig can not parse: parse vector index config: invalid hnsw config: efConstruct...` |

- **VERDICT 行**: `VERDICT: DEFECT_FOUND (Type1_IllegalSuccess): vectorIndexConfig int params inconsistently validated: [('ef', -5, -5), ('efZero', 0, 0), ('vectorCacheMaxObjects', -1, -1), ('cleanupIntervalSeconds', -1, -1), ('pq.centroids', -1, -1)] accepted AND persisted (HTTP 200, response echoes value, GET read-back confirms) while controls maxConnections=422, efConstruction=422 are rejected on the same config object. ef=-5/0 is especially notable: ef is the active HNSW search-time param (documented default sentinel is -1); -5/0 are invalid values persisted silently.`
- **reproduced_at**: 2026-08-21T13:47:15Z（final_verdict.json generated_at；脚本执行于本轮 mining 会话）

### Ring 4: Source Code Reference (可选)
- **github_url**: https://github.com/weaviate/weaviate/blob/v1.37.4/entities/vectorindex/hnsw/config.go
- **code_snippet**（raw_knowledge.md 机械提取，v1.37.4）:
  ```go
  DefaultEF = -1 // indicates "let Weaviate pick"
  ...
  MaxConnections        int `json:"maxConnections"`
  EFConstruction        int `json:"efConstruction"`
  EF                    int `json:"ef"`
  VectorCacheMaxObjects int `json:"vectorCacheMaxObjects"`
  ```
  校验不对称源于 Go 端参数解析路径不一致：maxConnections/efConstruction 走 `parse vector index config` 校验（422），而 ef/vectorCacheMaxObjects/cleanupIntervalSeconds/pq.centroids 缺同等校验，非法值直达 schema 持久化。

## Completeness Check
- Ring 1: PRESENT
- Ring 2: DEGRADED（DOC_UNREACHABLE 非阻塞；raw_knowledge 源派生内容已版本匹配）
- Ring 3: PRESENT（output_*.log 实测，含 VERDICT 行）
- **Overall**: COMPLETE

## Reproduction Steps
1. 启动 weaviate v1.37.4 单机实例（`docker run -p 8080:8080 cr.weaviate.io/semitechnologies/weaviate:1.37.4`）
2. `POST /schema`，body 含 `{"class":"ReproEfNeg5","vectorIndexConfig":{"ef":-5}}` → 观察返回 200 且响应回显 `ef: -5`
3. `GET /schema/ReproEfNeg5` → 读回 `vectorIndexConfig.ef == -5`（已持久化）
4. 依次以 `ef:0`、`vectorCacheMaxObjects:-1`、`cleanupIntervalSeconds:-1`、`pq.centroids:-1` 重复步骤 2-3 → 均 200 且持久化
5. 对照：同一请求结构提交 `{"class":"ReproCtl","vectorIndexConfig":{"maxConnections":-1}}` → 422 `invalid hnsw config: maxConnections`
6. 对照：提交 `{"class":"ReproCtl2","vectorIndexConfig":{"efConstruction":-5}}` → 422 `invalid hnsw config: efConstruction`
7. 对比步骤 2-4（200 静默持久化）与步骤 5-6（422 拒绝）→ 同一配置对象内校验不一致

## Impact Analysis
- **静默无效状态**: 用户提交 `ef=0`（HNSW 搜索时实际生效参数）或 `ef=-5` 时收到 200 成功回显，实际查询路径上该值不可用，可能产生退化/空召回而**无任何配置期报错**——配置错误仅在运行时以难诊断的形式暴露
- **运维资源异常**: `cleanupIntervalSeconds=-1`（负清理间隔）与 `vectorCacheMaxObjects=-1` 被持久化后，清理/缓存行为偏离预期且无法从 schema 层面察觉
- **PQ 配置损坏**: `pq.centroids=-1` 被持久化，若后续启用 PQ 量化，负质心数量可能导致索引构建失败或损坏——而错误已在 schema 层固化并可传播到副本
- **契约/实现不一致**: 官方文档与源码未声明这些参数的合法域（structured_contract.json 无 range 约束），叠加校验不对称，用户无法从 API 行为推断合法输入——违反最小惊讶原则
- **修复建议**: 在 `parse vector index config` 路径中对 ef（合法值 -1 哨兵或 ≥1）、vectorCacheMaxObjects、cleanupIntervalSeconds、pq.centroids 增加与 maxConnections/efConstruction 一致的边界校验

## Original Execution Log
- Log: `output_vein_range_filter_schema_vi_ints_1.log`（会话根目录实测存在；含 VERDICT 行，供 verify_defects.py 机械验证）
- Script: `vein_range_filter_schema_vi_ints_1.py`（原 attack script；本会话目录未检出脚本副本，执行行为由上述 output_*.log 完整还原）

## MRE
- Script: `defect-1-script.py`（由 reporter-mre Agent 生成，位于 `mre/`）
- Run: `python defect-1-script.py`
