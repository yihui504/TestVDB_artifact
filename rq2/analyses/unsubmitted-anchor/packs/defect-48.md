# 候选缺陷 defect-48

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [missing-delete never-created] status=200 raw={"result":false,"status":"ok","time":0.00008364}
- [setup create tvcd02real1788607902] status=200 raw={"result":true,"status":"ok","time":0.311631882}
- [DELETE existing tvcd02real1788607902] status=200 raw={"result":true,"status":"ok","time":0.008307468} (positive control: delete-existing disposition correct)
- [missing-delete second-delete-after-real] status=200 raw={"result":false,"status":"ok","time":0.000089101} (double-delete)
- [missing-delete repeat-1] status=200 raw={"result":false,"status":"ok","time":0.000064925}
- [missing-delete repeat-2] status=200 raw={"result":false,"status":"ok","time":0.00006505}
- [missing-delete repeat-3] status=200 raw={"result":false,"status":"ok","time":0.00006244} (3x repeat, G9)

--- 契约（expected，来自该版本文档/契约） ---

assertion: inferred: DELETE on a missing collection name returns a not-found client error, not success
source_url: 
doc_version: 
