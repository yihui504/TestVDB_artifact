# 候选缺陷 defect-60

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [TERMINAL group_size=5000000] firing ONE request (timeout=120s); no escalation beyond 5e6 per dispatch | [TERMINAL group_size=5000000] status=-1 raw=Remote end closed connection without response | [healthz] probe 1/12: status=-1 (dead window observed) | [healthz] probe 12/12: status=-1 (dead window observed) | Type3_RuntimeFailure: TERMINAL group_size=5e6 dropped the connection / timed out AND a /healthz dead window was observed (recovered=False) — OOM-kill repro signature; docker-logs corroboration (expect 'Killed ./qdrant') is main-process's job | VERDICT: DEFECT_FOUND
- [staged group_size=100000] status=200 raw={"result":{"groups":[{"hits":[{"id":1,"version":1,"score":1.0},{"id":4,"version":1,"score":4.0},{"id":7,"version":1,"score":7.0}],"id":"a"},...
- [staged group_size=100000] /healthz alive -> safe-zone NO_DEFECT evidence
- [staged group_size=1000000] status=200 raw={"result":{"groups":[{"hits":[{"id":1,"version":1,"score":1.0},{"id":4,"version":1,"score":4.0},{"id":7,"version":1,"score":7.0}],"id":"a"},...
- [staged group_size=1000000] /healthz alive -> safe-zone NO_DEFECT evidence
- execution_r38.json retry2_notes: 'Phase C: state_grp_gs_oom_05.py ran 106s (600s cap unused), exit=1, VERDICT: DEFECT_FOUND; its terminal kill leg dropped the server (healthz=000 immediately after) as designed'
- _r38_health_raw.txt: 'health=000' ; 'restarted: HTTP 200 on /healthz after docker start (container was down post-OOM-script, connection refused; now healthy)'

--- 契约（expected，来自该版本文档/契约） ---

assertion: inferred: limit is minimum-bounded but unbounded above; the server must handle any spec-legal value of this parameter within implementation resource bounds (complete the request, reject it with a documented client error, or return a documented service error); crashing, panicking, or killing the service is not allowed; service liveness after the request is verified via readyz/healthz
source_url: 
doc_version: 
