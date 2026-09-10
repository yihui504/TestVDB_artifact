# R7 Summary — chunk_cluster+recover(500 错误分类轮,GT 9039 面)

- 生成:12 脚本(bnd 4/state 4/sem 4);st001 探针可见性返工(第 4 次同坑)
- 执行:12/12;sem 4 诚实收工(distributed deployment detected)
- 判定:6 DEFECT / 1 NOT / 0 NME
- **核心缺陷:POST /cluster/recover standalone 一律 500**("Service internal
  error: running in standalone mode",body 无关 8 脚本确定性,含 documented
  no-body control)vs 文档只记 200 面;**同文件三兄弟面(remove_peer/
  cluster collection ops/sharding-key)同条件用 bad_request→400**——家族
  处置不一致为最强佐证;= pilot GT 9039 记录现象("standalone 500→4xx
  可触发")的再现
- bnd001 NOT 诚实(状态约束域外未行使,violates=false;信号由 6 兄弟链承载)
- by_design doubt(C=WEAK_REFUTED×7:purpose-written gate 无处置类注解)
  留人工复核清单
- 累计:24 DEFECT / 13 NOT / 0 NME
