# R31 Summary — chunk_per_collection(6 不变量;全部 HOLD 确认)

- 生成:8 脚本(state 单族;6 不变量全覆盖含三真并发)
- 执行:8/8;并发三脚本(20 线程 count/delete×overwrite 竞速/索引
  构建锤)全过内存峰值 203MiB 无险——R8 基线不变量在对抗下确认 HOLD
- 判定:0 DEFECT / 2 NOT——两候选均 script 层失误:
  * 001:自注册错 URL /points/get(raw_knowledge 实为 /points;grep
    零命中;同错复制入 2 兄弟)
  * 007:R27 归一化误报变体(三点共用点 1 单基线向量,基线即差
    0.22/0.35;T1 标记从未写入的点 3=逻辑不可能)
- 不变量族真验证负=方法阴性基线再确认
- 累计:51 DEFECT / 35 NOT / 0 NME(31/80)
