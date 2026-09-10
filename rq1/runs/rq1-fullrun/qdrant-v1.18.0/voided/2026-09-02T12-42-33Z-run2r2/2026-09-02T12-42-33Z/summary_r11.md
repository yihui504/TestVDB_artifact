# R11 Summary — chunk_collections+create-2of2(7 单元)

- 生成:23 脚本(三族自检零 REJECT 纪律内化);C3 一次全绿
- 执行:23/23;**shard_number=4294967295 三脚本独立杀死服务**(OOM
  exit 134,12min outage);环境事故 2 起处置(R3 残留循环 kill——污染
  范围核实仅 R11 首批;死 DB 批次重跑留档 dbdown_pass)
- 判定:3 DEFECT / 1 NOT / 0 NME
- **shard OOM 缺陷**(resource_bound 类别首秀):spec-legal uint32-max
  → shard_distribution.rs:91 物化 4.29B entries → OOM;**同族对照实测:
  replication_factor 同值被 cmp::min clamp → 200 存活**;梯度完备
  (1000/100000 timeout-alive,仅 max 致死);lib/build.rs 同 registry
  中 size 有 max=65536 而 shard_number 无上界
- sem023 NOT:visibility 延迟系 script id-键解析 bug(raw body 实含
  name;兄弟脚本正解全过)
- 累计:38 DEFECT / 21 NOT / 0 NME
