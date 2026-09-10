# Defect 11: 含 NUL 密码创建被接受且 NUL 截断认证绕过（2 字节凭证生效）

## Metadata
- defect_id: TESTVDB-MILVUS-011 (boundary_r2_password_bytes_003)
- type: Type1_IllegalSuccess
- param: password（含 NUL 内容字符）
- novelty: NOVEL

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/users/create" \
  -H "Content-Type: application/json" \
  -d '{"userName":"u1","password":"ab\x00cdxxxxxxxxxx"}'
# code:0（长度按 15 字节通过校验）
# 之后 Bearer u1:"ab"（NUL 截断 2 字节）认证 -> HTTP 200 code:0
#       Bearer u1:完整 15 字节密码 -> HTTP 400
```

## Expected vs Actual
- Expected: 密码 6 <= len <= 72（契约 milvus_range_users_create_password_002 在库）且内容应完整生效。
- Actual: 用户持有密码语义上为 15 字节，但实际生效凭证是 NUL 截断的 'ab'（2 字节 < min 6）——等同接受 len 2 密码；提供完整密码反而 400，凭据与输入分裂。对照：73 字节 1100 / 空串 1802 / 6 unicode 字节合规 code:0 全部正确。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_range_users_create_password_002
  - assertion: "6 <= len(password) <= 72 else code 1100"（链引文为端点描述非断言原文 → quote_mismatch → GREY_ZONE；B 数值下界兜底 CONFIRMED → DEFECT）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（长度规则 live 复现；内容字符约束为文档 gap——gap 即缺陷空间）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_r2_password_bytes_003.py（builder 2026-08-22 独立复现同向）
- Log: output_boundary_r2_password_bytes_003.log
- 源码 internal/proxy/util.go:1306-1313 ValidatePassword 仅长度校验，无内容/NUL 校验；util.go:1516 passwordVerify 的 bcrypt.CompareHashAndPassword 对含 NUL []byte 在首个 NUL 截断比较——创建时加密与验证时比较均按截断后 'ab' 生效。verification_outcome: validation_absent。

## Impact
NUL 截断认证绕过：攻击面为密码实际熵仅 2 字节但表面合规 15 字节；用户不知道自己真实密码是什么（完整密码 400、任意同前缀+NUL 串可能均认证通过）。多脚本稳定触发，A 级证据（契约-gap-源码-行为四面对齐）。
