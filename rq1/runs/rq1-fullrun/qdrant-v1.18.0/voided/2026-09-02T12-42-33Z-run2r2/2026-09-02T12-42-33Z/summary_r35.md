# R35 Summary — chunk_points+delete(破坏性 filter 受理轮;3D)

- 生成:10 脚本(bnd 6/state 4);C3 一次全绿
- 执行:10/10(9 exit0);write/delete 竞速 1s 无险
- 判定:3 DEFECT / 0 NOT / 0 NME(全机械 CONFIRMED 锁定)
- **3 DEFECT 破坏性 filter 受理族**:
  * if004:matcher-less FieldCondition(must_not 仅 key 无 match)200
    受理+**全库 wipe 6→0**(全 None 条件匹配零物→must_not 反转匹配
    万物);**源码自己的 validator("At least one field condition")存在
    但 REST 路径从未调用,gRPC 面先验**=面间不对称
  * sel005:双选择器(points AND filter)200 静默 points 分支消歧
    (untagged 首变体胜+PointIdsList 无 deny_unknown_fields;同族
    Filter 分支有——严格性存在恰缺在获胜变体上);doc 明文 OR 语法
  * spd002:should:null 200+wipe(MaybeOneOrMany null→None by-design
    抗辩留人工,m3 key-only 无抗辩)
- **与 R34 ftype003 NOT 的区别实证**:count 面读操作宽容无害 vs delete
  面破坏性;断言明示 400 on invalid filter
- 累计:55 DEFECT / 43 NOT / 0 NME(35/80)
