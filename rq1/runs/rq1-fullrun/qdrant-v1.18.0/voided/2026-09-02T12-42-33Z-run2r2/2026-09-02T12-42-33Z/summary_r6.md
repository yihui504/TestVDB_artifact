# R6 Summary — chunk_cluster+peer+delete(单 peer 保护轮)

- 生成:16 脚本(bnd 6/state 5/sem 5);classify 2 REJECT(st001/002 oracle+
  探针可见性)返工;sem wrapper 缺 timeout 签名执行期崩溃×5 修复重跑
- 执行:16/16;VERDICT 13 NO + 2 SCRIPT_ERROR(st002/005 部署边界诚实收工)
  + 1 DEFECT(sem_002 Type2)
- 判定:0 DEFECT / 1 NOT / 0 NME——peer 删除面在 standalone 部署全部
  正确 4xx 拒绝(boundary 6 脚本全 NO);唯一候选 Type2 链断 doc
  (rubric 仅测试侧,契约无错误质量承诺;4xx 已兑现 violates=false)
- 源码趣味信号(留档非判定):validation_error_handler 已注册但全仓不可达
  (所有路由用 web::Path 非 actix_web_validator::Path)
- 累计:18 DEFECT / 12 NOT / 0 NME
