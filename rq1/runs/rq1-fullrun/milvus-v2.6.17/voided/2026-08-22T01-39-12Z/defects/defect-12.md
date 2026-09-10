# Defect 12: update_password 成功后旧凭证持续有效（双凭证并存）

## Metadata
- defect_id: TESTVDB-MILVUS-012 (boundary_r2_updatepwd_creds_004)
- type: Type4_StateLogicViolation
- param: 旧密码凭证时效（update_password 后）
- novelty: NOVEL

## Reproduction (curl)
```bash
# 合法改密 code:0 后：
curl -s "http://localhost:19530/v2/vectordb/users/list" \
  -H "Authorization: Bearer <base64(user:oldpwd)>"
# 观测: HTTP 200（旧凭证仍有效）；新凭证同时 200 —— 双凭证并存
# 对照: wrong oldPassword -> 1400 "old password not correct ... not authenticated"（校验器正常）
```

## Expected vs Actual
- Expected: update_password 成功后旧凭证应失效（凭据变更即时生效的安全语义）。
- Actual: 脚本 3 次循环（sleep 1s）旧凭证均 200；builder 延伸复测 20s 后仍 200——排除 3s 传播延迟解释；新凭证同时有效 = 双凭证并存。newPassword len 3/73 → 1100 对照一致。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: GAP（契约无旧凭证失效时限断言；锚定 users+create password 族 + Type4 状态不变量类别）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（时效性契约 gap，非逐字断言违背）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_r2_updatepwd_creds_004.py（builder 20s live-recheck 复测）
- Log: output_boundary_r2_updatepwd_creds_004.log
- 源码 impl.go UpdateCredential L5218-5287 → rootcoord alterUserV2AckCallback L86-96（AlterCredential etcd + UpdateCredCache → proxyClientManager.UpdateCredentialCache → priCache.UpdateCredential 改写 credMap）——失效链看似即时，但实测旧 SHA256 仍命中 passwordVerify（util.go:1511-1514）；'旧值继续命中'的确切持有者未定位，源码机制未闭环（如实标注）。verification_outcome: validation_present（链在但未生效）。

## Impact
Type4 状态违规：改密后旧密码（可能已泄露的凭证）在 ≥20s（可能无限期）内仍可访问全部数据，密码轮换的安全目的落空。单节点 standalone 排除多 proxy 传播解释；行为面两次独立复现方向确定，机制持有者待上游定位。D=blindspot（认知库对 credential cache 失效时限零陈述）。
