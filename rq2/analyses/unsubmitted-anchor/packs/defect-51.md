# 候选缺陷 defect-51

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [reader 5xx] tid=18 face=get status=500 raw={"status":{"error":"Service internal error: 0 of 0 read operations failed"},"time":0.005333698}
- [reader tally] 200=1071 404=987 503=0 5xx=25 transport=0 other=0 (25 500s out of 2083 reader requests across 20 threads / 3 faces; all six sampled 5xx lines are face=get)
- [cycle 0] create=200 ({"result":true,"status":"ok","time":0.402773275}) delete=200 ({"result":true,"status":"ok","time":0.008804969}) (all 6 lifecycle cycles 2xx — the DELETE face itself never failed)
- [end-state] get=404 exists=200/False count=404 list-present=False (delete-gone invariant held on all four faces after settle)
- [end-state raw] get={"status":{"error":"Not found: Collection `tvcd061788607909` doesn't exist!"},"time":8.959e-6} exists={"result":{"exists":false},"status":"ok","time":5.847e-6} count={"status":{"error":"Not found: Collection `tvcd061788607909` doesn't exist!"},"time":2.754e-6} (comparative, same face: settled-phase GET on the missing collection returns 404, churn-phase GET returned 500)
- Type3_RuntimeFailure: 25 reader 500s during lifecycle churn (temporarily-absent collection must be 404/503, not internal error) (script's threshold-2 declaration: >=2 distinct 500 events while /healthz=200)
- rest-face same-phenomenon search: '0 of 0 read operations failed' appears in no other output_*.log this session (other 500s are different phenomena: wal_retain_closed Tokio panic in create scripts, telemetry 500)

--- 契约（expected，来自该版本文档/契约） ---

assertion: inferred: DELETE on a missing collection name returns a not-found client error, not success
source_url: 
doc_version: 
