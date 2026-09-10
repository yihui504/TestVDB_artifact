# R2 Summary — chunk_aliases+list (GET /aliases 全局面)

- 生成:13 脚本(bnd 5/sem 4/state 4),R1 反思全吸收(信封/前缀/并行容忍/docstring)
- 执行:13/13 全 exit0(本面干净)
- 候选:1(boundary_aliases_list_002 Type2 空 400 诊断体)
- 判定:NOT_DEFECT——三重根因:断言 success-shape only 无诊断条款;参数
  collection_name 系契约 backfill 伪影(文档/spec/源码三面均未声明);
  空 400 = actix-http pre-router 请求行溢出(get_aliases 无 Query extractor,
  1MB body→200/短查询→200 对照)
- classifier 机制坑:cleanup_unwrapped 误报 list.remove() 记账行(挂账:
  匹配需限定 teardown 接收者)
- residual(留人工非判定):vendor OpenAPI 4XX→ErrorResponse 声明从未被
  提取为约束——new-class review 信号(other 通道)
- 累计:10 候选 5 DEFECT / 5 NOT_DEFECT / 0 NME
