# qdrant v1.18.2 RQ1 Pilot 汇总

```json
{
  "session": "qdrant v1.18.2 RQ1 pilot (4 rounds)",
  "chain_verdicts": {
    "DEFECT": 26,
    "NOT_DEFECT": 15
  },
  "total": 41,
  "novelty_gate": {
    "NOVEL": 12,
    "UNVERIFIED": 9,
    "BY_DESIGN": 5
  },
  "gt_reach": {
    "reached": [
      "qdrant_9017 (hnsw_ef, via vein_hnsw_ef_null_search_1 DEFECT)"
    ],
    "not_reached": [
      "qdrant_9421 (cluster+recover — endpoint 不在契约)",
      "qdrant_9520 (collections+create shard_number — 参数不在契约)",
      "qdrant_9522 (points+query lookup_from — 参数不在契约)"
    ],
    "note": "本契约下 GT 理论上限 = 1/4（仅 hnsw_ef 可达）；reach 口径 = chain_verdicts DEFECT 全集（含 UNVERIFIED/BY_DESIGN 候选），非 Gate-Endorsed 集"
  },
  "retry_stats": {
    "R1": "2 坏 → 2 regen → 2 修好 → 0 超限",
    "R2": "27 坏(22 cleanup_unwrapped + 5 verdict_missing) → 5 verdict 类全修；22 cleanup 类为 AST 风格项记录不阻断",
    "R3": "vein 3 个 SETUP_FAILED(集合残留 409) → 清残留重跑 OK；3 个 f-string VERDICT 静态检查不匹配 → 改字面量",
    "R4": "vein 3 个 VERDICT 空标签 → 机械填值重跑 OK"
  },
  "mechanism_verdicts": {
    "A_retry": "真实工作（R1 全链路验证：feedback 生成→agent 修→覆盖原文件→重跑通过；超限降级逻辑存在但未触发）",
    "B_gt_hint": "真实工作（R1 0/4 → R4 后 1/4 正确递增；4 agents 同文本盲注；NOT_DEFECT 不计数）",
    "C_novelty": "真实工作（gate 产出 grade/UNVERIFIED 保守路径 9 次；0 NON_NOVEL → archived 分支未触发，全 NOVEL/BY_DESIGN/UNVERIFIED）"
  },
  "pilot_pitfalls": [
    "子 agent 相对路径漂移 → 必须绝对路径派发",
    "contract-formalizer passport hash 时序 bug → 主进程重签兜底",
    "executor 忘设 TESTVDB_DB_URL → 21 脚本全 SCRIPT_ERROR（重派修复）",
    "chain-auditor verdicts 无 param 字段 → injector/novelty_gate 双消费方都读空（meta.json fallback 修复，已在 pipeline 落盘）",
    "vein meta.json 无 param 字段 → 手工回填 7 个",
    "auditor >12 链拒绝整批 → 分批派发（机制正确）",
    "agent 虚报修复（4 vein VERDICT 声称修了没写入）→ 主进程 grep 复核",
    "extract_candidates 只扫 SESSION_DIR 根 output_*.log → vein 自跑日志在 vein_scripts/ 需拷根"
  ]
}
```
