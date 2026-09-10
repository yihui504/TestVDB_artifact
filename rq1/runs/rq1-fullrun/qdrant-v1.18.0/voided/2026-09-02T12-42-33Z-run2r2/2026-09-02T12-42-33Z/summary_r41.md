# R41 Summary — chunk_points+query+groups(3 单元;25 脚本 6 候选[L1 裁 1])

- 生成:25 脚本(bnd 8/state 8/sem 9);3 单元全覆盖;反思上下文新增
  by-id 伪前提+order_by 前置两先例(全部生效:本轮零误触)
- **C4 事故与处置**:resource_001(limit×group_size 极值组合)OOM 击杀
  容器(137/OOMKilled),23/25 判定作废;executor 重启容器后 22 条
  重跑干净(5 DEFECT/17 NO);resource_001 隔离复跑 OOM 3/3 确定性
  复现;脚本死亡 oracle 原设 SCRIPT_ERROR——按 R11 先例走 8d.5 工单
  打回 boundary agent 修订(仅死亡分支+起跑 healthz 噪声护栏),
  修订版隔离重跑判定 DEFECT_FOUND(Type3)入册
- Stage1 全绿;L1:payload_003 REFUTEd 不进 fan-out(+2 条 R5 旧候选
  复扫 REFUTEd——L1 文件未重写 candidates.jsonl,按派发清单层执行,
  挂账);verify_chain_quotes 一次 PASS(125 链零 mismatch,连续两轮)
- 判定:5 链 2 DEFECT/3 NOT/0 NME(A 机械全轮)
- 累计:65 DEFECT / 60 NOT / 0 NME(41/80)

- 2 DEFECT(同族两独立脚本):group_by 无值字段→200 groups=[] vs
  契约钉死 400(invalid_groupby_001+behavior_001;源码=静默合并
  must_not IsEmpty 过滤器,无路径校验器——group_size 有
  validate(range) 而 group_by 无,B 类 HTTP-semantics 双确证,
  D 锚 silent-failure-missing-ref)
- **resource_001 NOT_DEFECT 机械层铁律案例**:3/3 确定性 OOM
  (aggregator.rs:40 with_capacity(groups*group_size) 预留 1e12
  元素)但契约 range 单元只主张 minima→A REFUTED→NOT 绑定;
  B=CONFIRMED resource boundary 疑点留人工——**对照 R11:当时契约
  有 qdrant_resource_shard_number_001 提取条目,本轮 query-groups
  无同类条目=J1④ formalizer 提取覆盖缺口(6 条 resource_bound
  覆盖 shard/offsets/pairs/facet,漏 query-groups)**
- 2 NOT(behavior):filter/semantics 皆脚本 oracle 工件(fixture
  id 公式 gi*1000+100+k vs oracle 表 1000+gi*100 块;服务端响应
  按重建 fixture 逐字节正确;源码 filter-before-group/top-k 数学
  确认)——**同 seed 公式双脚本共享同一 oracle 错误,脚本间"独立
  互证"不成立的实证案例**
- 环境留痕:executor Step 0 再生 .executor.env(localhost 覆盖固化
  127.0.0.1,两度手工恢复;R41 运行未受影响);OOM 死亡致 3 个
  bqgsR* 残留集合已清理
