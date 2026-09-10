# Defect 8: Async writes (wait=false) skip validation feedback entirely — invalid vectors 200-acknowledged then silently dropped (upsert/update_vectors/batch)

## Metadata
- Defect ID: TESTVDB-QDRANT-8
- Candidate ID: vein_type_mismatch_async_upsert_17
- Type: Type1_IllegalSuccess
- Severity: Medium（Type1 推断，人工分流参考）
- Endpoint: points+upsert (PUT /collections/{name}/points); corroborating: vectors+update (PUT /collections/{name}/points/vectors), points+batch (POST /collections/{name}/points/batch)
- Discovered: 2026-08-23T17:54:53Z（R4-b2 批；gt_bug_hit: 9045 — 现象与 GT #9045 同型，机械 param 匹配未命中，双门分歧留痕）
- Chain verdict: DEFECT（机械 B=CONFIRMED：HTTP 语义 — 同载荷 wait=true 400 / wait=false 200 且静默丢弃；doc "400 invalid dim mismatch" 无 wait 限定）

## Evidence Chain

### Ring 1: Contract Clause (契约条款引用)
- **constraint_id**: qdrant_behavioral_points_upsert_001（builder 重锚 — 派发 constraint_id 为空串）
- **contract_assertion**: "with wait=false client receives acknowledge-only response immediately; eventual consistency before searchable"（category: response status acknowledged; data may not be retrievable yet）+ doc 行为行（raw_knowledge.md:168，contract source https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points）："behavioral: 200 ok; 400 invalid payload/vector dim mismatch; 404 collection missing; with wait=false client gets acknowledge-only response immediately"
- **expected_behavior**: "400 invalid payload/vector dim mismatch" 无 wait 限定 — 非法向量在两条路径都应产生可感知的拒绝信号；"acknowledged" 语义（may not be retrievable YET）不覆盖 "never retrievable 且客户端永远无从得知"
- **source_url**: https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points

### Ring 2: Document Reference (原始文档引用)
- **source_url**: https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points
- **doc_version**: 1.18.x（versioned）
- **doc_quote**: "behavioral: 200 ok; 400 invalid payload/vector dim mismatch; 404 collection missing; with wait=false client gets acknowledge-only response immediately"（raw_knowledge.md:168）；"wait (boolean, query, optional): default false; if true, wait for changes to become searchable"（line 160，default false 使异步路径成为默认路径）
- **url_status**: degraded（build 期 WebFetch domain_blocked；契约构建期 source_verified=true + 本地 raw_knowledge.md:153-169 全页缓存佐证）
- **version_match**: matched

### Ring 3: Actual Behavior (实际行为证据)
- **HTTP Request**: `PUT {db_base}/collections/vein_c17/points?wait=true` 与 `?wait=false` 各发同一非法载荷（id=10 vector []；id=11 dim3；id=12 dim5；id=13 named {"default":[]}；update_vectors id=1 [1,2]；batch id=20/21 []）（db_base 以原脚本 DB_URL 为准）
- **HTTP Response**: 全部 6 组同型分裂 — wait=true → `400 "Vector dimension error: expected dim: 4, got 0/3/5"`；wait=false → `200 {"status":"acknowledged"}`（无任何业务错误码）；2s 后 readback：非法写全部永久丢弃（仅合法异步对照 id=99 落地），point 1 向量保持原 4 分量不变
- **Container Logs**: output_vein_type_mismatch_async_upsert_17.log
  ```
  empty vector []: wait=true -> 400 | wait=false -> 200 (acknowledged)
  wrong dim 3: wait=true -> 400 | wait=false -> 200 (acknowledged)
  wrong dim 5: wait=true -> 400 | wait=false -> 200 (acknowledged)
  named empty: wait=true -> 400 | wait=false -> 200 (acknowledged)
  update_vectors dim2: wait=true -> 400 | wait=false -> 200
  batch empty vector:  wait=true -> 400 | wait=false -> 200
  readback after 2s: landed ids=[99] (expect only [99])
  point 1 vector after async bad update_vectors: [0.18257418, 0.36514837, 0.5477226, 0.73029673] (unchanged)
  VERDICT: DEFECT_FOUND — all async (wait=false) write paths skip vector validation: every invalid shape is 200-acknowledged then silently dropped (upsert, update_vectors, batch); identical payloads 400 with wait=true; valid async writes land (control)
  ```
- **reproduced_at**: 2026-08-23（R4 执行窗口；log 已落盘，待 verify_defects.py 机械验证）

### Ring 4: Source Code Reference
- **github_url**: https://github.com/qdrant/qdrant/blob/v1.18.0/lib/collection/src/shards/local_shard/shard_ops.rs#L60-L125
- **code_snippet**（链内取证）:
  ```rust
  // shard_ops.rs submit_update: wait=false（WaitUntil::Wal）→ needs_callback()=false → sender=None
  // shard_ops.rs:184-189 await_update_result:
  (None, _) => Ok(UpdateResult { status: UpdateStatus::Acknowledged, .. })  // 立即 200，校验尚未运行
  // update_worker.rs:27-37 send_feedback: sender=None 时 Err(update_err)（WrongVectorDimension）
  //   落入 if-let 缺口 — 静默丢弃，连一行日志都没有
  ```
  完整链：校验存在且会运行（segment/entry.rs:661 check_named_vectors → WrongVectorDimension），但只发生在 HTTP 200 已发出之后的后台 worker；wait=false 路径 sender=None，失败无投递通道。三端点（upsert/update_vectors/batch）共用同一 UpdateSignal 管道，同型分裂。

## Completeness Check
- Ring 1: PRESENT（qdrant_behavioral_points_upsert_001 重锚 + doc 行为行；auditor 复核锚点与 claim 语义匹配）
- Ring 2: DEGRADED（domain_blocked；契约期 verified + 全页缓存）
- Ring 3: PRESENT（6 组 paired 观测 + 合法异步对照 + readback 证永久丢弃）
- **Overall**: COMPLETE

## Reproduction Steps
1. 建集合 vein_c17（size=4, Cosine）。
2. `PUT /points?wait=true` body 含空向量/错维向量 → `400 Vector dimension error`。
3. 同一字节级 body `?wait=false` → `200 {"status":"acknowledged"}`。
4. sleep 2s 后 `POST /points` readback：非法 id 全部缺席（合法异步对照 id=99 已落地）；update_vectors 与 batch 端点同型复现。

## Impact Analysis
wait 默认 false —— 异步是默认写入路径。高吞吐管道中尺寸配置漂移（如 embedding 模型升级 768→1024）时：同步探测 400 可发现，实际批量写入全部 200 acknowledged 然后逐条静默蒸发，无错误码、无日志、无反馈通道；数据"成功写入"的表象与永久丢失的现实之间的差距只会在业务侧晚数小时被发现。文档 "400 invalid payload/vector dim mismatch" 未限定 wait，属文档-实现分裂。现象与 GT #9045 同型（gt_bug_hit 已留痕）。

## Original Execution Log
- Log: `output_vein_type_mismatch_async_upsert_17.log`（含 VERDICT 行）
- Script: `vein_scripts/vein_type_mismatch_async_upsert_17.py`

## MRE
- Script: `defect-8-script.py`（reporter-mre Agent 产出）
- Run: `python defect-8-script.py`
