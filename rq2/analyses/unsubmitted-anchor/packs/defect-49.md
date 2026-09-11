# 候选缺陷 defect-49

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [M1 A vectors size=64] status=200 raw={"result":true,"status":"ok","time":0.015888909}
- [M2 A vectors distance=Euclid] status=200 raw={"result":true,"status":"ok","time":0.019865846}
- [M3 B vectors v size=64 distance=Manhattan] status=200 raw={"result":true,"status":"ok","time":0.020140998}
- [A re-read] status=200 vector_space={"": [4, "Cosine"]} — unnamed face UNCHANGED after M1+M2 (created size=4/Cosine)
- [B re-read] status=200 vector_space={"v": [4, "Dot"]} — named face UNCHANGED after M3 (created size=4/Dot)
- [A 4-dim insert id=900] status=200 raw={"result":{"operation_id":2,"status":"completed"},"status":"ok","time":0.003220251}
- [A 64-dim insert id=901] status=400 raw={"status":{"error":"Wrong input: Vector dimension error: expected dim: 4, got 64"},"time":0.004013685}

--- 契约（expected，来自该版本文档/契约） ---

assertion: index, quantization and disk configurations can be changed after create via update; size/distance of an existing vector cannot be altered through update
source_url: 
doc_version: 
