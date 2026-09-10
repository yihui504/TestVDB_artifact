# R40 Summary — chunk_points+query+batch(1 单元;24 脚本 7 候选)

- 生成:24 脚本(bnd 10/state 7/sem 7);单元=assertions::
  qdrant_behavioral_points_query_batch_001;反思上下文带 R33 键丢弃
  /R37 批整拒/R39 query 面教训
- 执行:24/24(20 exit0);executor 标记 order_by 缺 range index 共享
  前置失败疑点(positive_001/mixed_008/malformed_010)——builder 全取证
  确证为脚本 fixture 缺陷(order_by 需先建数值索引,源码
  order_by.rs numeric_index_for 硬前置+错误自述)
- Stage1 全绿;L1:7 候选 UNCERTAIN;verify_chain_quotes 一次 PASS
  (120 链零 mismatch——引文纪律前置生效,本轮零返工)
- 判定:7 候选 2 DEFECT/5 NOT/0 NME(A 机械全轮;两 DEFECT 均
  A=CONFIRMED 机械通道,dualkey 另有 B=CONFIRMED 互斥参数类)
- 累计:63 DEFECT / 57 NOT / 0 NME(40/80)

- 2 DEFECT:
  * dualkey_005:query-batch 内 Query oneOf 双键 200 受用且 order_by
    静默丢弃(指纹隔离证 winner=nearest;serde untagged Nearest 先到
    先得+无 deny_unknown_fields+零 oneOf 排他校验——**R33 键丢弃家族
    第三例,首次落在 query 包装器**;doc 层 undiscriminatedUnion 渲染
    留 auditor note)
  * lifecycle_006:teardown 竞速批面再现——it34 1/40 HTTP 200 但
    result 形状破缺(单面 query_api.rs .pop() 守卫→500 风味 vs 批面
    query_api.rs:167-185 无 result 完备性守卫→畸形 200;D 盲区命中
    concurrent shard restart safety;**与 R39 lifecycle_008 同根源
    不同面,面不对称新证据**)
- 5 NOT 三主题:order_by 前置 400×2(脚本 setup 缺索引,by-design
  in source+错误自述)——executor 疑点全证伪收编;by-id 自排除×3
  (exclude_referenced_ids 显式 doc comment 设计;对齐/幂等/删除
  一致性子检查全 PASS,DEFECT 行皆由额外契约外 oracle 期望误触发)
- 分布:cat type1/state1/other5;fp source=5;cc strict2/rejected5
- 教训:by-id oracle "必含自身" 对 qdrant 是伪前提(家族第 4-7 例
  误触,一并 NOT)——反射上下文应加 by-id 自排除先例
