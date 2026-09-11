# 候选缺陷 defect-21

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [defect] error family replicate_shard-invalid-to_peer_id (status 400) scored 0/3 — the message names neither the offending parameter nor any format/actionable hint: Bad request: Distributed mode disabled
- [rubric] replicate_shard-invalid-to_peer_id: score=0/3 (parameter_named=False, format_hint=False, actionable=False); existence-wording=False; message=Bad request: Distributed mode disabled
- [defect] error family drop_replica-invalid-peer_id (status 400) scored 0/3 — the message names neither the offending parameter nor any format/actionable hint: Bad request: Distributed mode disabled
- [defect] error family abort_transfer-invalid-peers (status 400) scored 0/3 — the message names neither the offending parameter nor any format/actionable hint: Bad request: Distributed mode disabled
- [defect] error family move_shard-invalid-shard_id (status 400) scored 0/3 — the message names neither the offending parameter nor any format/actionable hint: Bad request: Distributed mode disabled
- [family] unknown-collection-404-family: status=400 raw={"status":{"error":"Bad request: Distributed mode disabled"},"time":4.463e-6} — status drift: assertion pins '404 collection', probe returned 400 (preempted by the mode gate)
- [confound] replicate_shard-invalid-to_peer_id: deployment runs with distributed mode disabled — the business-layer gate preempts peer/shard/collection validation, so the measured message answers a different rejection reason (recorded for review alongside the rubric score)

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 ok on accepted operation; 400 invalid peer/shard; 404 collection
source_url: 
doc_version: 
