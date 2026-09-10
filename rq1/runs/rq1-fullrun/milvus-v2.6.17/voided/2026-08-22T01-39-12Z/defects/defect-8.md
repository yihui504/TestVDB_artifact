# Defect 8: root 凭据 grant_privilege 恒 65535 失败并留下不可授权的僵尸角色

## Metadata
- defect_id: TESTVDB-MILVUS-008 (state_rbac_revocation_immediacy_003)
- type: Type3_RuntimeFailure
- param: roles+grant_privilege（root 凭据）
- novelty: NOVEL

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/roles/create" \
  -H "Authorization: Basic cm9vdDpNaWx2dXM=" -H "Content-Type: application/json" \
  -d '{"roleName":"r1"}'        # code:0 成功
curl -s -X POST "http://localhost:19530/v2/vectordb/roles/grant_privilege" \
  -H "Authorization: Basic cm9vdDpNaWx2dXM=" -H "Content-Type: application/json" \
  -d '{"roleName":"r1","objectType":"Collection","objectName":"*","privilege":"Search"}'
# 观测: {"code":65535,"message":"fail to get authorization from the md, authorization:[token]"}
```

## Expected vs Actual
- Expected: root 凭据的合法授权操作 → code:0（同凭据 roles+create / users+grant_role 均 code:0）。
- Actual: roles+grant_privilege 恒 65535 "fail to get authorization from the md"；roles+describe 返回存在但零权限的角色——僵尸角色永远无法经 REST 授予。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（契约库 45 constraints 无 grant_privilege 条目；锚定 RBAC 功能语义）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（RBAC 专项页未单独核）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/state_rbac_revocation_immediacy_003.py（vein_scripts/vein_rbac_grant_cross_endpoint_001.py 同日同部署复现）
- Log: output_state_rbac_revocation_immediacy_003.log
- 源码三文件闭环：(1) service.go L188-196 auth 关闭时 ginHandler `c.Set(ContextUsername, "")`；(2) util.go L1452 NewContextWithMetadata 空用户名不注入 authorization metadata；(3) impl.go L5645+ OperatePrivilege 无条件 `GetCurUserFromContext(ctx)` 失败即 context_util.go:98 65535。对照组 OperateUserRole（impl.go:5415）不调用 GetCurUserFromContext 直接转发——故同部署跨端点分裂。verification_outcome: validation_absent。

## Impact
auth-disabled 默认部署下 REST RBAC 授权链路全瘫：角色可建不可授权，形成不可用僵尸角色；同凭据同部署 5 端点行为分裂（3 code:0 vs 2 恒 65535）排除凭据归因。注意：'revocation immediacy' 原命题未测到（语义漂移已标注），judged phenomenon 为 grant 全瘫；D=blindspot（认知库对 RBAC REST 层零陈述）。
