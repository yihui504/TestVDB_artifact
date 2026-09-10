# VOIDED — run2r2 qdrant v1.18.0（会话 2026-09-02T12-42-33Z）

**作废单位**：本次 run 全部产物（ATTACK_GEN 阶段中止时读数：round 42/30，phase 未达 DONE）。
**拍板**：用户 2026-09-04 决定中止、修复后以插件 2.5.0 重跑（本目录为完整留证镜像，来源 `plugins\cache\testvdb\testvdb\2.4.0\results\qdrant\v1.18.0\`，4808 文件 / 37M，校验一致）。

## 作废理由（Step 6.5 未执行 → 全程无策略预绑定）

1. `structured_contract.json` 的 75 条约束**全部无 `bound_strategies` 字段**、无顶层 `_strategy_binding` 汇总——mine.md Step 6.5（`scripts/bind_strategies.py`）从未执行。按 discipline 总纲"流程一致（不跳步骤）"，属流程违规。
2. 根因（2026-09-04 探查实证）：Step 6.5 只存在于 orchestrator.md/mine.md 两处纯 Markdown SOP，无任何 gate/状态机强制；派发词与 chunk unit 均不携带绑定信息，缺失静默。
3. 修复（插件 2.5.0，main 47c2221+83c7764 / 4exp 5bceeca）：D2 v3.5 消费语义改为 A+B 叠加 + pipeline_gate 症状④（契约有约束但无 `_strategy_binding` → Stop 拦停）。本次 run 的生成条件与 2.5.0 不可比，不能中途套用（同 run 语义漂移），故整体作废重跑。

## 存档参考数字（2.4.0 代际、无绑定=B-only 形态；仅供参考，不进论文口径）

- 记忆存档（rq1-run2r2-progress，R23 暂停点）：R1-R23 累计 50 DEFECT / 23 NOT_DEFECT / 0 NME。
- 中止时 pipeline_state：phase=ATTACK_GEN，current_round=42 / max_rounds=30（超轮未收敛）。
- 顶层同目录的 `2026-08-23T05-48-00Z/` 是更早的 run2 世代镜像（含已废弃 vein_scripts），与本次无关。

## 重跑入口

插件 2.5.0 就绪后对 qdrant v1.18.0 全新 mine run：Step 6.5 实跑（预期 18 type + 22 range 端点级绑 builtin 基线；3 state 端点级 + 32 system 级空绑定）→ gate 症状④验证 → ATTACK_GEN 按 D2 v3.5（路径 A 绑定直生 + 路径 B 全量 G1–G10 双向）消费。
