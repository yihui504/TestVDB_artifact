# R29 Summary — chunk_payload+overwrite(3 单元;key 丢弃 doc-vs-impl 发现)

- 生成:14 脚本(bnd 8/state 6);C3 一次全绿
- 执行:14/14(13 exit0);竞速 5s 无险
- 判定:0 DEFECT / 3 NOT / 0 NME
- **008 key 丢弃(最重要发现)**:doc/schema 在 PUT overwrite 面发布 key
  字段("Assigns payload to each point that satisfy this path")但源码
  硬编码丢弃(update.rs:639-654 + tonic 双胞胎,显式注释 "overwrite
  operation doesn't support payload selector");live 对照同 body 在
  POST set 面 honored/PUT 面 ignored——**真实 doc-vs-impl 分歧**;
  机械 NOT(被引断言字面满足)但 auditor 记录为最强 doc_consistency
  类约束提取候选(人工复核清单+;C=REFUTED 因显式意图注释)
- spow006 NOT(POST set merge 文档明示;bc 只钉 PUT 面;脚本 oracle 自相矛盾)
- bpow006 NOT(Type2 命名无锚,R28 bpd006 同款第三例)
- 累计:50 DEFECT / 32 NOT / 0 NME(29/80)
