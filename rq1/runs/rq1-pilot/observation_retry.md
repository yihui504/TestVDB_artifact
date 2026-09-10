# RQ1 Pilot — retry 子循环观察数据（qdrant v1.18.2，2026-08-20）

> 观察清单 A 项要求：记录每轮坏脚本数 / regen 数 / 修好数 / 超限数。

## 累计数字

| 轮 | 坏脚本 | 分类 | regen(派修) | 修好 | 超限降级 | 备注 |
|---|---|---|---|---|---|---|
| R1 | 2 | verdict_missing×1 + cleanup_unwrapped×1 | 2 | 2 | 0 | 全链路首次验证：feedback json 生成→agent 读修→覆盖原文件→重跑 exit 0 |
| R2 | 27 | cleanup_unwrapped×22 + verdict_missing×5 | 5（verdict 类） | 5 | 0 | 22 个 cleanup 类为 AST 风格项（VERDICT 正常输出），记录不阻断 |
| R3 | 3+3 | verdict_missing×3（f-string 动态 VERDICT）+ SETUP_FAILED×3 | 6 | 6 | 0 | f-string 静态检查不匹配是分类器保守路径；SETUP_FAILED 是集合残留 409 |
| R4 | 3 | VERDICT 空标签×3（vein 模板未填值） | 3 | 3 | 0 | 主进程机械填值重跑 |
| **计** | **38** | — | **16** | **16** | **0** | |

## 机制结论（checklist 1.2 遗留项）

**retry 子循环确认真实工作**：
- ✅ `_classify_script_errors.py` 分类正确（AST 5 类，误报率低——仅 f-string VERDICT 一类保守误报）
- ✅ `{script_id}.retry_feedback.json` 生成且 hint 具体可操作
- ✅ attack agent 读 feedback 修后覆盖原文件，再次执行通过（R1 state_08 / vein_range 两个实锤案例）
- ✅ retry counter 递增（retry_state.json 按 defect_id 计数，max_retry=2）
- ⚠️ 超限降级（3 次后跳过）**未触发样本**——本次无一超限，逻辑存在但无实证
- ⚠️ agent 虚报修复 1 次（R2 vein 4 脚本声称修了未写入）→ 主进程 grep 复核必要

## 已知坑（后续 15 版本全量要防）

1. **executor 忘设 TESTVDB_DB_URL** → 21 脚本全 SCRIPT_ERROR（R2 重派修复）——派发词必须显式带 export 命令
2. **集合残留 409** → vein 脚本重跑 SETUP_FAILED——测试脚本 setup 需先清同名集合
3. **f-string 动态 VERDICT** → 静态检查 verdict_missing 误报——attack agent 规范应要求字面量
4. **vein meta.json 无 param 字段** → 下游（injector/novelty_gate）读空——已加 meta fallback（pipeline 已落盘）+ 本会话手工回填 7 个
5. **子 agent 相对路径漂移** → 派发一律绝对路径
6. **contract-formalizer passport hash 时序 bug** → 主进程按 verify 算法重签兜底
