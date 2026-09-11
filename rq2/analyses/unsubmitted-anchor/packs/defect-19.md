# 候选缺陷 defect-19

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [re-delete unknown a1] status=200 raw={"result":true,"status":"ok","time":0.000013825}
- [delete a1] status=200 raw={"result":true,"status":"ok","time":0.018305249}
- [scroll via deleted a1] status=404 raw={"status":{"error":"Not found: Collection `tvau5a1_1788566062` doesn't exist!"},"time":1.543e-6}
- [rename unknown a1] status=404 raw={"status":{"error":"Not found: Alias tvau5a1_1788566062 does not exists!"},"time":0.000021573}
- [create -> never-existed] status=404 raw={"status":{"error":"Not found: Collection `tvau5never_1788566062` doesn't exist!"},"time":0.000019966}
- [create -> just-deleted] status=404 raw={"status":{"error":"Not found: Collection `tvau5c2_1788566062` doesn't exist!"},"time":0.000014772}
- [recreate a1] status=200 raw={"result":true,"status":"ok","time":0.016868577}

--- 契约（expected，来自该版本文档/契约） ---

assertion: "expected_behavior": "200 ok; 404 create_alias on missing collection; unknown-alias delete/rename -> error family (404/500 per knowledge)"
source_url: 
doc_version: 
