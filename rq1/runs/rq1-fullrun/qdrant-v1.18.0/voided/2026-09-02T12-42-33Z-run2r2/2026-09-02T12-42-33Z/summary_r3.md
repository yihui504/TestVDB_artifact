# R3 Summary — chunk_aliases+update(3 单元)

- 生成:22 脚本(bnd 10/state 5/sem 7);C3 全绿;C4 localhost 故障重跑(state 5,127.0.0.1)
- 候选:9;判定 7 DEFECT / 2 NOT / 0 NME
- **7 DEFECT 三族**:
  * batch 原子性×3(st001/bnd008/sem002):404 拒批部分残留——validate-then-apply
    循环 ? 早退+insert 即落盘;文档原文 "Alias changes are atomic"(OpenAPI
    :11093)——run2r #1 defect-1 家族复现 ✓
  * delete-unknown×3(bnd004/sem004/st002):200 vs 契约 {404,500};**人工复核
    优先**:2 链 chain_broken_at=doc(契约条款系 synthesis,OpenAPI 只 200)+
    C=REFUTED("Delete alias if exists" 维护者措辞)
  * 双键元素×1(sem006):serde untagged 双 discriminator 静默丢弃第二键;
    bnd002 同现象 NOT(violates=false)——auditor 忠实转录不对称,DEFECT 承载
- 2 NOT:双键(bnd002 anyOf 允许)/NUL 别名(bnd005 无 charset 条款)
- 跨链一致性信号:auditor #9255 自检过;new-class 信号 other=6(行为状态码
  断言类无正式类别——Rule 2.9 promotion-review)
- 累计:19 候选 12 DEFECT / 7 NOT / 0 NME
