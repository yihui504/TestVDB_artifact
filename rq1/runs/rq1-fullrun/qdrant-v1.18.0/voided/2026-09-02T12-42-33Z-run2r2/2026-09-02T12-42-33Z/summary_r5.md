# R5 Summary — chunk_cluster+collection+update(部署边界轮)

- 生成:21 脚本(bnd 8/state 6/sem 7);preverify REJECT 5(bnd007/008 缺
  shard_key)打回修复
- 执行:21/21;11 SCRIPT_ERROR(standalone 部署边界:拒 create_sharding_key
  carrier/无 peers——agent 诚实收工拒硬编码 peer_id)
- 判定:1 DEFECT / 3 NOT / 0 NME
- 3 NOT=oneOf 压平 artifact 破案:flat {"operation":...} body 不匹配
  untagged enum(需单键包裹)——根因 raw_knowledge 把 oneOf 压平成 operation
  字段(J1 新成员③);standalone "Distributed mode disabled" gate 使
  404/200 面不可达(bnd007 schema-valid 对照实证)
- 1 DEFECT(st_ccu_002)= resharding_operations 缺字段第 6 次机械确认
  (同 R4,by-design doubt 留痕;链断 contract=约束代换)
- 累计:18 DEFECT / 11 NOT / 0 NME
