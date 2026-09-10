# R33 Summary — chunk_points+batch(批量写入面;serde 双键第三例)

- 生成:16 脚本(bnd 6+state 10);C3 一次全绿
- 执行:16/16(10 exit0/6 exit1);并发内存 205MiB 无险
- 判定:1 DEFECT / 6 NOT / 0 NME(补证轮闭环:NME→NOT,cid 裸值)
- **1 DEFECT = serde untagged 双键静默丢弃第三例**(ops_003:两 variant
  键一个 op 200 受理,声明序决定,第二键丢弃;与前两例同机制家族:
  R3 aliases/R21 field_schema)——机械 CONFIRMED 锁定
- **重要阴性:points+batch 位置依赖部分提交为真但 NOT**(reject404_007+
  atomicity_006 双链互证:poison-last 400+前缀落盘/fail-first 零落盘;
  源码 for 循环早退无回滚——但 doc 无原子性承诺(对比 aliases+update
  有 ATOMIC 明文);**D 消费:维护者 "batch ops not promissed to be
  atomic" 认知条目→SUPPORTS_NOT_DEFECT**;reject404_007 归
  exploratory_candidate 行为异常通道留报告)
- 4 script 工件全击杀(反转/算术/归一化/id 碰撞,全日志内自相矛盾)
- 累计:52 DEFECT / 41 NOT / 0 NME(33/80)
