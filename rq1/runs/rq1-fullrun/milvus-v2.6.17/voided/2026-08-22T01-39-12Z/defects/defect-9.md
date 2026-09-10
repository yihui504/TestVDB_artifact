# Defect 9: 同凭据同参数族跨 RBAC 端点行为分裂（3 code:0 vs 2 恒 65535）

## Metadata
- defect_id: TESTVDB-MILVUS-009 (vein_rbac_grant_cross_endpoint_001)
- type: Type3_RuntimeFailure
- param: privilege/role 参数族（5 个 RBAC 端点对照）
- novelty: NOVEL

## Reproduction (curl)
```bash
# 同 Bearer root 凭据、同部署：
users+create            -> code:0   (CTRL)
roles+create            -> code:0   (CTRL)
users+grant_role        -> code:0   (CTRL)
roles+grant_privilege   -> code:65535 "fail to get authorization from the md"  (EXP)
roles+grant_privilege_v2-> code:65535 同消息  (EXP)
```

## Expected vs Actual
- Expected: 同参数族、同凭据、同部署的兄弟 RBAC 端点应有一致的认证语义。
- Actual: grade A 对照设计下 3 CTRL code:0 与 2 EXP 恒 65535 分裂，全部 HTTP 200。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（vein 类跨端点一致性命题，契约库无 constraint）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_rbac_grant_cross_endpoint_001.py（state_rbac_revocation_immediacy_003.py 独立脚本同日复现）
- Log: output_vein_rbac_grant_cross_endpoint_001.log
- 源码对照式定位：operateRoleToUser（handler_v2.go:2454）与 operatePrivilegeToRole（L2545）走同一 wrapperProxy 注入同样的空-username ctx；差异在 impl 层——OperateUserRole（impl.go:5415）不读 ctx 用户直接转发；OperatePrivilege（impl.go:5657）与 OperatePrivilegeV2（impl.go:5581）均硬依赖 GetCurUserFromContext（auth-md 缺失时恒错，context_util.go:98）。verification_outcome: validation_absent。

## Impact
与 defect-8 同根因双视角（state=僵尸角色后果，vein=跨端点分歧形态）：5 个端点同一外部契约形态，仅 2 个在内部链路上无条件依赖 HTTP 层（auth 关闭时）不会提供的元数据。对照设计排除凭据/参数归因；D=blindspot 灰区裁决 DEFECT。
