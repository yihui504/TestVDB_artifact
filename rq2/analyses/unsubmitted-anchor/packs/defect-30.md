# 候选缺陷 defect-30

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [negative sharding_method=None] status=200 raw={"result":true,"status":"ok","time":0.29297212}
- [positive auto] status=200 raw={"result":true,"status":"ok","time":0.33576244}
- [echo auto] sharding_method-like key in describe: True
- [auto upsert] status=200 raw={"result":{"operation_id":1,"status":"completed"},"status":"ok","time":0.003883423}
- [count auto] status=200 count=1
- [observation custom] status=200 raw={"result":true,"status":"ok","time":0.047493571}
- OBSERVATION: custom disposition recorded (in-enum value; usability requires shard-key ops — not defect-adjudicated here)

--- 契约（expected，来自该版本文档/契约） ---

assertion: sharding_method in [auto, custom] per v-1-18-x OpenAPI ShardingMethod enum
source_url: 
doc_version: 
