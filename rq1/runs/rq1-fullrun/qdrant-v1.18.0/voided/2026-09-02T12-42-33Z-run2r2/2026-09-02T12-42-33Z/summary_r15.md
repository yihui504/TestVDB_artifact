# R15 Summary — chunk_collections+list(全局面)

- 生成:12 脚本(bnd 4/state 4/sem 4);C3 一次全绿
- 执行:12/12(10 exit0);st_list_003 脚本自身 setup bug 诚实 SCRIPT_ERROR
- 判定:0 DEFECT / 1 NOT / 0 NME——sem004(POST on GET-only 面空 404)
  NOT:机械 A=REFUTED(violates=false,GET 200 兑现);87 断言无 wrong-verb
  诊断锚;actix 框架默认空 404(无 default_service);**R8 空-404 对裁定
  完全一致(fp=doc/other/同词表)——家族先例稳定**
- residual 信号(三度):OpenAPI 4XX:ErrorResponse 模板 vs 框架空 404
  (R2/R8/R15)——new-class review 通道素材
- 全局面 list 其余全合规(name 键/前缀成员/并发 churn 稳定)
- 累计:45 DEFECT / 22 NOT / 0 NME(15/80 块)
