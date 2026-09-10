=== 候选缺陷 qdrant_014 ===
[vendor=qdrant version=1.18.2 defect_type=behavior endpoint=cluster+recover]

--- 观察到的行为（observed） ---
观察摘要（probe 产出）：
- [setup] GET /cluster -> status=disabled
- [c1] cluster recover in standalone -> status=500, body: Service internal error: Qdrant is running in standalone mode

执行日志全文（output_qdrant_014.log）：
=== REQ 1 ===
GET http://localhost:6333/cluster
=== RESP 1 ===
status: 200
body: {"result":{"status":"disabled"},"status":"ok","time":2.37e-6}

=== REQ 2 ===
POST http://localhost:6333/cluster/recover
=== RESP 2 ===
status: 500
body: {"status":{"error":"Service internal error: Qdrant is running in standalone mode"},"time":0.015995971}

=== REQ 3 ===
GET http://localhost:6333/cluster
=== RESP 3 ===
status: 200
body: {"result":{"status":"disabled"},"status":"ok","time":3.173e-6}

=== REQ 4 ===
POST http://localhost:6333/cluster/recover
=== RESP 4 ===
status: 500
body: {"status":{"error":"Service internal error: Qdrant is running in standalone mode"},"time":0.018369187}



--- 契约依据（expected，来自该版本 API 契约） ---
[契约中无 endpoint=cluster+recover 的约束条目]

API 模板：endpoint=cluster+recover doc_quote='Recover current peer Raft state' source=None

VERDICT: UNKNOWN (replay capture — no attack-agent assertion output; raw HTTP only)
