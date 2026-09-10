# R19 Summary — chunk_global(锁不变量;不可致动诚实阴性)

- 生成:2 脚本(state 双路径:端点活→6 面拒绝矩阵+竞速;端点死→诚实 NO)
- /locks 实测 404(OSS v1.18.0 无 handler,源码取证+主进程实测一致)
- 执行:2/2 全 exit0 NO_DEFECT——不变量不可致动(与 run2r #1 R8 阴性
  基线同结论:锁不变量在 OSS standalone 无法验证,诚实验证负)
- 累计:48 DEFECT / 23 NOT / 0 NME(19/80;零候选轮:R13/R16/R19)
