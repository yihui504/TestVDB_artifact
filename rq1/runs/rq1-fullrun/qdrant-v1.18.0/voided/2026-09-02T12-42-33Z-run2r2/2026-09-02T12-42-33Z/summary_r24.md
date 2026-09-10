# R24 Summary — chunk_locks+get(OSS 端点缺席;零候选轮 6)

- 生成:3 脚本(boundary 单族,type+behavioral+malformed 三覆盖;
  双路径设计:活→全 oracle;缺→ENDPOINT_ABSENT 诚实阴性)
- 执行:3/3 全 exit0——**预期路径确认**:GET/POST /locks 双 404 →
  ENDPOINT_ABSENT → NO_DEFECT(探针证据+源码路由表交叉;R19 同测)
- C3 注意:verdict FAIL 系 R22 已执行补脚本 st_index_delete_010 的
  cleanup_unwrapped 词法误报(severities=None→默认 REJECT 已知坑;
  脚本已 NO_DEFECT 不返工)——locks_get 本身零错误
- 判定:0 DEFECT(locks 契约单元在 OSS 部署不可致动)
- 累计:50 DEFECT / 23 NOT / 0 NME(24/80;零候选轮:R13/16/19/20/23/24)
