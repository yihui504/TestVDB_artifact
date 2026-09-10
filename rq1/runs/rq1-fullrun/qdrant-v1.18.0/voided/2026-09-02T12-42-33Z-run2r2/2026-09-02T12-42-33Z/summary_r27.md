# R27 Summary — chunk_payload+clear(归一化误报族;零候选轮 9)

- 生成:11 脚本(bnd 6/state 5);C3 一次全绿
- 执行:11/11(7 exit0/4 exit1);并发竞速内存无险
- 判定:0 DEFECT / 4 NOT / 0 NME——**4 候选全同源:脚本 oracle 比错基线**
  (setup_default Cosine→upsert 时 cosine_preprocess L2 归一化入库,
  simple.rs:228 显式 by-design 注释;脚本拿 scroll 回读比原始未归一化
  上传向量;各日志自己的 pre-clear baseline 即已归一化、post-clear
  逐字节一致;clear 路径零向量访问;无 oracle 的 7 兄弟脚本全 NO)
- payload clear 面实际全合规(选择性/幂等/竞速/filter 语义/lifecycle)
- 机制教训:Cosine 集合的向量回读比对必须以 baseline 回读为基线,
  不能比上传原值(setup_default 的隐含语义)
- 累计:50 DEFECT / 27 NOT / 0 NME(27/80;零候选轮 9)
