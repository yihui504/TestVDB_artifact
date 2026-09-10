# Defect 3: 并发 upsert fieldOps 无锁 read-modify-write 导致丢失更新

## Metadata
- defect_id: TESTVDB-MILVUS-003 (state_fieldops_concurrent_001)
- type: Type4_StateLogicViolation
- param: 并发 upsert + fieldOps ARRAY_APPEND（8 线程 × 5 次）
- novelty: NOVEL

## Reproduction (curl)
```bash
# 8 个并发 worker 各发起 5 次：
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/upsert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"t","id":1,"fieldOps":[{"fieldName":"tags","op":"ARRAY_APPEND","elements":["t1"]}]}'
# 全部 40 次 code:0；readback tags 仅 12 元素（期望 41），丢失 29 次 append
```

## Expected vs Actual
- Expected: 全部 40 次 code:0 成功的 ARRAY_APPEND 应全部落盘（tags len=41）。
- Actual: readback tags=["a","t6","t4","t2","t7","t3","t4","t4","t5","t2","t1","t2"]，len=12，丢失 29 次追加，且无任何错误信号（op codes=[0]）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: milvus_state_entities_upsert_fieldops_001
  - assertion: "any(fieldOps structural violation) => code 1100, no rows modified"（'成功必须正确落盘'语义引申；契约原文无并发条款，如实标注）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_VERIFIED（limitations.md 可达；无并发承诺明文——弱链接）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/state_fieldops_concurrent_001.py
- Log: output_state_fieldops_concurrent_001.log
- 源码 internal/proxy/task_upsert.go L237 queryPreExecute：retrieveByPKs 读旧值 → 内存 merge（task_upsert_partial_op.go applyArrayPartialOpOnRow）→ 整体写回。grep 'lock|Lock|concurren' 在 task_upsert.go 零命中——read-modify-write 全程无 per-pk 互斥，无乐观并发控制，后写者胜。verification_outcome: validation_absent。

## Impact
任何多客户端并发使用 partial update（ARRAY_APPEND/REMOVE）都会静默丢数据：返回成功但追加丢失。单轮运行为减分项（run-to-run 方差未排除），但机制（无锁 RMW）与观测数字闭合。
