# 候选缺陷 defect-42

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [upsert-face timeout=0] status=200 raw={"result":{"operation_id":2,"status":"wait_timeout"},"status":"ok","time":0.00141134}
- [minimum timeout=1 create] status=200 raw={"result":true,"status":"ok","time":0.313577343}  [rest create face - G4 positive anchor: the documented minimum itself accepted]
- [below-minimum create zero timeout=0] status=422 raw={"status":{"error":"Validation error in query parameters: [timeout: value 0 invalid, must be 1 or larger]"},"time":0.0}  [rest create face - the SAME value rejected; note: dispatch claim said 400, observed 422]
- [below-minimum create negative timeout=-5] status=400 raw={"status":{"error":"Deserialize error in query parameters: invalid digit found in string"},"time":0.0}  [rest create face - negative below-minimum rejected at deserialize]
-   [rejected cleanly] 'tvcc40b1788603552' absent from list after 422
-   [rejected cleanly] 'tvcc40c1788603552' absent from list after 400
- [min-face usability] upsert=200 count_status=200 count=2 raw={"result":{"count":2},"status":"ok","time":0.000455618}

--- 契约（expected，来自该版本文档/契约） ---

assertion: "assertion_id": "qdrant_behavioral_create_collection_004",
      "endpoint": "collections+create",
      "description": "inferred: timeout below the documented minimum is rejected",
      "category": "behavioral",
      "expected_behavior": "timeout=0 or negative -> client-error rejection, not silent acceptance",
      "evidence_tier": "inferred",
      "source_url": "https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection",
      "source_status": "reachable",
      "source_verified": false,
      "doc_version": "1.18.x (versioned v-1-18-x api-reference)",
      "level": "endpoint",
      "defect_type_if_violated": "Type1_IllegalSuccess"
source_url: 
doc_version: 
