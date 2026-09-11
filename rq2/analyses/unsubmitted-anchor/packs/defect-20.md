# 候选缺陷 defect-20

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [leg] unknown-collection: status=400 raw={"status":{"error":"Bad request: Distributed mode disabled"},"time":7.149e-6}  (semantic_cluster_collection_update_003.log:8 — POST /collections/{unknown}/cluster with fully valid move_shard body, only the path collection_name unknown)
- [ledger] unknown-collection: expected=404 actual=400 -> DEFECT Type2_PoorDiagnostics (disposition mismatch; note: disabled-mode gate observed to run BEFORE collection existence on this deployment — confound recorded for review)  (semantic_cluster_collection_update_003.log:9)
- [leg] accepted-op: status=400 raw={"status":{"error":"Bad request: Distributed mode disabled"},"time":4.442e-6} / [ledger] accepted-op: expected=2xx actual=400 -> precondition-blocked (distributed mode disabled; acceptance face unavailable — not adjudicated as Type1 per G8)  (semantic_cluster_collection_update_003.log:22-23)
- [G9] invalid-peer family dispositions across 6 faces: [('move_shard-invalid-peer', 'canonical-400-class'), ('replicate_shard-invalid-peer', 'canonical-400-class'), ('abort_transfer-invalid-peer', 'canonical-400-class'), ('restart_transfer-invalid-peer', 'canonical-400-class'), ('drop_replica-invalid-peer', 'canonical-400-class'), ('move_shard-invalid-shard', 'canonical-400-class')] -> uniform=True  (semantic_cluster_collection_update_003.log:24 — all six 400-class legs match the numeric class, though for the gate's reason, not peer/shard validation)
- FALLBACK_TRIGGERED: cluster+status yields no peer set (status=disabled: {"result":{"status":"disabled"},"status":"ok","time":2.34e-6}) -> static out-of-topology sentinel peers 1/2  (semantic_cluster_collection_update_003.log:6 — deployment-mode evidence: cluster status reports disabled)
- rest face, state_cluster_collection_update_02.log:7-8: [post-delete valid op] status=400 raw={"status":{"error":"Bad request: Distributed mode disabled"},"time":5.21e-6} / [post-delete valid op] non-404 4xx (400); recorded, not adjudicated (validation-order gray zone)
- rest face, GET-vs-POST asymmetry same deployment: state_cluster_collection_update_02.log:9: [post-delete info] status=404 — the GET cluster-info face 404s the same deleted collection while the POST cluster-update face 400s it (source-grounded: do_get_collection_cluster checks existence with no mode gate)

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 ok on accepted operation; 400 invalid peer/shard; 404 collection
source_url: 
doc_version: 
