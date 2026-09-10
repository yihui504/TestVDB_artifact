# R17 Summary — chunk_collections+update(5 单元;PATCH 面)

- 生成:25 脚本(bnd 13/state 7/sem 5);C3 一次全绿
- 执行:25/25(20 exit0/5 非零);**executor 日志落 debate_logs/ 子目录 →
  extract_candidates 顶层扫描漏 3 DEFECT**(cp 后重提取;机制坑挂账)
- 判定:3 DEFECT / 0 NOT / 0 NME
- **3 DEFECT = doccons indexing_threshold**(三独立脚本同测值):doc 生成
  schema 双矛盾句(OptimizersConfig "10,000" vs OptimizersConfigDiff
  "20,000" stale comment config_diff.rs:150)而运行时全部默认构造解析
  10000(DEFAULT_INDEXING_THRESHOLD_KB=10_000 零 20000 代码路径)——
  **run2r #1 defect-9/11/14 精确复现**,doc_consistency 类别首次批量
- PATCH 面其余合规(immutability 读回/range 闭包/200-echo/404 处置)
- 累计:48 DEFECT / 22 NOT / 0 NME(17/80)
