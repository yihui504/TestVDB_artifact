# 候选缺陷 defect-40

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [pos wal minima] status=500 raw={"status":{"error":"Service internal error: Tokio task join error: task 7914 panicked with message \"called `Option::unwrap()` on a `None` value\""},"time":1.24306981}
- rest sibling boundary_create2_a02, same-family param wal_capacity_mb=0 (below declared min 1): LEG[wal_capacity_mb=0 expect_reject=True] PUT collections+create name=bc2a02_0: status=422 body[:300]='{"status":{"error":"Validation error in JSON body: [wal_config.wal_capacity_mb: value 0 invalid, must be 1 or larger]"},"time":0.0}'
- rest sibling boundary_create2_a02, same-family param at its minimum: LEG[wal_capacity_mb=1 expect_reject=False] PUT collections+create name=bc2a02_3: status=200 body[:300]='{"result":true,"status":"ok","time":0.320085136}' and LEG[wal_segments_ahead=0 expect_reject=False] PUT collections+create name=bc2a02_5: status=200 body[:300]='{"result":true,"status":"ok","time":0.337034164}'
- rest sibling boundary_create2_a02, exact same param+value (wal_retain_closed=0): LEG[wal_retain_closed=0 expect_reject=False] PUT collections+create name=bc2a02_6: status=500 body[:300]='{"status":{"error":"Service internal error: Tokio task join error: task 61342 panicked with message \\"called `Option::unwrap()` on a `None` value\\""},"time":1.249311998}'
- rest sibling semantic_create2_a02, single-field isolation: [leg] P1 wal_config.wal_capacity_mb=1 (pinned minimum - must be accepted): status=200 raw={"result":true,"status":"ok","time":0.334582973} ; [leg] P2 wal_config.wal_segments_ahead=0 (pinned minimum - must be accepted): status=200 raw={"result":true,"status":"ok","time":0.422663463} ; [leg] P3 wal_config.wal_retain_closed=0 (pinned minimum - must be accepted): status=500 raw={"status":{"error":"Service internal error: Tokio task join error: task 61827 panicked with message \"called `Option::unwrap()` on a `None` value\""},"time":1.199932962}
- rest sibling boundary_create2_b02, all-three-minima combined body: LEG[wal-all-minima] PUT collections+create name=bc2b02_allmin: status=500 body[:300]='{"status":{"error":"Service internal error: Tokio task join error: task 61402 panicked with message \\"called `Option::unwrap()` on a `None` value\\""},"time":1.200565291}' ; semantic_create2_b02 same 500 (task 61915)
- behavior live replay by builder 2026-09-05T08:25:30Z against the same sandbox instance (127.0.0.1:6333): PUT /collections/eb_replay_wrc0 with {"vectors":{"size":4,"distance":"Cosine"},"wal_config":{"wal_capacity_mb":1,"wal_segments_ahead":0,"wal_retain_closed":0}} -> HTTP/1.1 500 with {"status":{"error":"Service internal error: Tokio task join error: task 11212 panicked with message \"called `Option::unwrap()` on a `None` value\""},"time":1.207204973} ; healthz=200 immediately after ; describe of the failed name -> 404 {"status":{"error":"Not found: Collection `eb_replay_wrc0` doesn't exist!"}} (no residue, name left free — matches the constraint's rejection hygiene on the failed create)

--- 契约（expected，来自该版本文档/契约） ---

assertion: wal_config.wal_capacity_mb >= 1; wal_config.wal_segments_ahead >= 0; wal_config.wal_retain_closed >= 0
source_url: 
doc_version: 
