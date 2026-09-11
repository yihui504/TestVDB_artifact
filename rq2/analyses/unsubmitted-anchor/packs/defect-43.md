# 候选缺陷 defect-43

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- PHASE-A concurrent DELETE #1: status=200 result=False raw[:250]='{"result":false,"status":"ok","time":0.008483416}'
- DISPOSITION[concurrent_delete_1]: DEFECT_FOUND (Type4_StateLogicViolation) — 200 without result=true
- PHASE-A concurrent DELETE #0: status=200 result=True raw[:250]='{"result":true,"status":"ok","time":0.008386971}'
- PHASE-A post-race describe: status=404 raw[:250]='{"status":{"error":"Not found: Collection `bcd4_37848_race` doesn\'t exist!"},"time":9.614e-6}' [face=rest GET — same missing name: GET/describe 404s while DELETE returned 200]
- PHASE-C ghost-knob missing-delete (force=true&peer_id=1): status=200 raw[:250]='{"result":false,"status":"ok","time":0.000062465}' [same 200-on-missing disposition on an unclaimed leg; recorded as OBSERVATION/SKIPPED by the script per threat_model idempotent-DELETE carve-out]
- PHASE-C delete-existing with documented minimum ?timeout=1: status=200 raw[:200]='{"result":true,"status":"ok","time":0.012260364}' [timeout=1 legal minimum accepted]
- PHASE-B recreate same name: status=200 / PHASE-B second delete: status=200 result=true [recovery legs all NO_DEFECT]

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 ok on existing collection; 404 on missing collection
source_url: 
doc_version: 
