# R10 Summary — chunk_collections+create-1of2(12 单元大块)

- 生成:41 脚本(bnd 12/state 14/sem 15);state 9 脚本探针可见性返工
- 执行:41/41(24 exit0/17 exit1);健康事件零
- 判定:5 DEFECT / 2 NOT / 0 NME(引文预检一次 PASS 零返工——cid 纪律生效)
- **5 DEFECT**:
  * **wal_retain_closed=0 panic 500**×2(bnd011/sem014,新缺陷,run2r #1
    未发现):documented create-min-0 → NonZeroUsize::new(0).unwrap() panic;
    WalConfigDiff 无 range attr(兄弟 wal_capacity_mb 有)+merge 不重验;
    Diff/resolved 双网格不对称的冲突区实炸
  * **memory enum docs-ahead-of-code**×2(bnd006/sem007):served spec 文档
    Memory enum 但 v1.18.0 源码无此字段(shard 含 1.18.3+ 内容);任意值
    (含非枚举 'hot')静默 200 丢弃;人工复核:版本钉扎问题
  * sparse []→struct-from-seq×1(sem003):serde 宽容解析→default struct
    200(同位置 int 得 400 对照)
- 2 NOT:vectors={} 空/省略×2——by_design 强证据(shell-then-fill 工作流
  端到端实证;served OpenAPI 无 required;gRPC Option 同构)
- 累计:35 DEFECT / 20 NOT / 0 NME
