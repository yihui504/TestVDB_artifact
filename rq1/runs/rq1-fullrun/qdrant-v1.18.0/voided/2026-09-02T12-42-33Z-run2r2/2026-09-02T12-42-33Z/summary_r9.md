# R9 Summary — chunk_cluster+telemetry(200-promise vs standalone 500 第 2 例)

- 生成:21 脚本(bnd 8/state 4/sem 9,含越块预演 chunk_telemetry 8 个——
  挂起留 chunk 75 复用);C3 一次全绿
- 执行:13/13(仅 cluster_telemetry);7 SCRIPT_ERROR 中 3 个=control 500
  诚实中止
- 判定终态:5 DEFECT / 1 NOT / 0 NME(**首个 NME 补证轮闭环实证**:
  2 条 EVIDENCE_GAP(cid 括注/空)one-field 修复后机械重裁 CONFIRMED→
  DEFECT,与兄弟一致)
- 核心缺陷:GET /cluster/telemetry standalone 一律 500 "Could not get
  telemetry from cluster"(参数无关 13 脚本);同文件兄弟端点有显式
  standalone guard 此 handler 三无(无 guard/无本地回退/无意图注解);
  文档示例 number_of_peers:1 暗示单 peer 应 200——**200-promise vs
  standalone 500 家族第 2 例(R7 recover 之后),家族先例稳固**
- bnd002 NOT 诚实(range 未违,'+1'→1 合规)
- 累计:30 DEFECT / 18 NOT / 0 NME
