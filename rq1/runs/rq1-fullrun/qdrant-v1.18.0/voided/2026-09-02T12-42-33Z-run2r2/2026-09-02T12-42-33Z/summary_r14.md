# R14 Summary — chunk_collections+get(describe 面)

- 生成:18 脚本(bnd 6/state 6/sem 6);C3 一次全绿
- 执行:18/18;1 候选
- 判定:1 DEFECT / 0 NOT——**churn describe 500 "0 of 0 read operations
  failed"×48 = run2r #1 defect-16 精确复现**(源码全溯源:create/drop
  生命期窗口内 replica-set 操作流为空→vacuous 错误串→500;同窗口
  exists/cluster-info 面零异常——500 隔离到 describe 路径)
- describe 面其余全合规(200/404 处置/config 回读保真/alias 解析/
  points_count 真实性)
- 累计:45 DEFECT / 21 NOT / 0 NME(14/80 块)
