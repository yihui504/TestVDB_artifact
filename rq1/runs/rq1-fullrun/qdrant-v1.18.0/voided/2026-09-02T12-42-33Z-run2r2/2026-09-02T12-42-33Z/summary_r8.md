# R8 Summary — chunk_cluster+status(disabled 信封轮,J1④ 实锤)

- 生成:10 脚本;C3 一次全绿零返工(reflection 传递到位)
- 判定:1 DEFECT / 4 NOT / 0 NME
- **J1 第 4 项失真实锤**:契约平坦四字段网格(顶层 raft_state/commit_index)
  在任何版本已发布 OpenAPI 均不存在(v0.10-v1.18 全扫;enabled 形状实为
  raft_info.role/commit 嵌套)——网格在任何部署任何版本不可满足;文档
  oneOf disabled 变体=观察 payload 的规范示例;by_design(schemars 生成链
  types.rs:243 tagged enum → ytt)
- bnd001 vs sem002 同现象违反声明分裂(violates true/false)——bnd001 机械
  DEFECT 留存(E2),最强人工复核候选(与 R4 resharding 同归并处理)
- 2 个 Type2 空 404 NOT(无契约锚;actix 默认路由 miss;residual:qdrant
  自有 OpenAPI response() 模板声明 4XX:ErrorResponse 未兑现——new-class
  通道信号,同 R2 sem003 residual)
- 链层 builder 教训:constraint_id 保持裸值勿嵌括注(st001 A=NEUTRAL
  artifact)
- 累计:25 DEFECT / 17 NOT / 0 NME
