# R1 Summary — qdrant v1.18.0 (run2r #2, EN 2.4.0 代际)

- 块:chunk_aliases+collection+list(1 单元 qdrant_behavioral_aliases_collection_list_001)
- 生成:13 脚本(bnd 5/sem 4/state 4);C3 全绿(semantic 4 oracle docstring retry 闭环)
- 执行:13/13(7×exit0);候选 9(DEFECT_FOUND×9);L1 9/9 UNCERTAIN
- 判定:5 DEFECT / 4 NOT_DEFECT / 0 GREY_ZONE / 0 CONFLICT(A 判定权全轮)
- **5 DEFECT 同一缺陷**:GET /collections/{name}/aliases 无 collection 存在性检查
  (collections.rs:167→toc/mod.rs:434→alias_mapping.rs:114 纯 map 扫描),
  unknown/dropped collection → 200 {aliases:[]} vs 契约断言 404;
  写路径与 describe/count 面同名 404(面不对称实证);gRPC 同构
- 4 NOT_DEFECT 全机械 REFUTED:1 parser 信封误判 + 3 残留集合污染(env_noise)
- **人工复核标记(未改判定)**:断言 404 条款文档地基仅 batch 级——v1.18.x
  OpenAPI 只声明 generic 4XX,文档页只写 200(bnd005 curl 实证,
  agent_suspects_contract_wrong=true);doc-as-ground 翻案权留人工
- candidate_class:5 strict_defect/4 rejected/0 exploratory
- 环境缺口:35 历史残留集合(跨 session 持久容器)→ R2 前清理
- 引文返工 5 处(拼接→逐字子串),verify_chain_quotes 终检 9/9 PASS
