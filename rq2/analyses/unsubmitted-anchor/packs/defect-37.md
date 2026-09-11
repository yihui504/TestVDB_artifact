# 候选缺陷 defect-37

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [rung shard_number=4294967295] status=-1 elapsed=4.0s raw=('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
- [control shard_number=1] status=200 raw={"result":true,"status":"ok","time":0.332860746} ; [control usable] count status=200 count=2 — spec-ordinary baseline accepted and usable, canary integrity anchor
- [rung shard_number=1024] status=-1 elapsed=60.0s raw=HTTPConnectionPool(host='127.0.0.1', port=6333): Read timed out. (read timeout=60) ; [death-oracle probe after rung 1024] alive=True trace=attempt0:healthz=200/readyz=200 ; OBSERVATION: rung 1024 transport error but service alive — treated as hang/timeout record, not death
- [rung shard_number=65536] status=-1 elapsed=60.0s raw=HTTPConnectionPool(host='127.0.0.1', port=6333): Read timed out. (read timeout=60) ; [death-oracle probe after rung 65536] alive=True trace=attempt0:healthz=200/readyz=200 ; OBSERVATION: rung 65536 transport error but service alive — treated as hang/timeout record, not death
- [death-oracle probe after rung 4294967295] alive=False trace=attempt0:healthz=-1/readyz=-1; attempt1:healthz=-1/readyz=-1; attempt2:healthz=-1/readyz=-1; attempt3:healthz=-1/readyz=-1; attempt4:healthz=-1/readyz=-1; attempt5:healthz=-1/readyz=-1; attempt6:healthz=-1/readyz=-1; attempt7:healthz=-1/readyz=-1; attempt8:healthz=-1/readyz=-1 — liveness dead across the full 9-attempt probe window (not a transient)
- DEATH_ORACLE: spec-legal shard_number=4294967295 killed the service — transport dead AND /healthz+/readyz unresponsive across the full probe window (resource_bound criteria: crash/kill not allowed)
- rest sibling boundary_create2_b12, same ladder terminal rung (different names/rungs, same face and parameter): LEG[shard_number=3] status=200 body[:400]='{"result":true,"status":"ok","time":0.776272853}' ; LEG[shard_number=1000] status=0 body[:400]="HTTPConnectionPool(host='127.0.0.1', port=6333): Read timed out. (read timeout=60)" with OBSERVATION[1000]: /healthz re-probe after 10s wait -> 200 (HANG_SUSPECT) ; LEG[shard_number=4294967295] status=0 body[:400]="('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))" ; DEATH-ORACLE[4294967295]: transport loss; liveness trace = healthz:0; healthz:0; healthz:0 -> alive=False ; LEG-DISPOSITION[shard_number=4294967295]: DEFECT_DEATH

--- 契约（expected，来自该版本文档/契约） ---

assertion: inferred: shard_number has no documented maximum; the server must handle any spec-legal value of this parameter within implementation resource bounds (complete the request, reject it with a documented client error, or return a documented service error); crashing, panicking, or killing the service is not allowed; service liveness after the request is verified via readyz/healthz
source_url: 
doc_version: 
