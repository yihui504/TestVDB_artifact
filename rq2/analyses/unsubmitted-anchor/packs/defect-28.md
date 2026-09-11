# 候选缺陷 defect-28

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [negative mixed unnamed+named in one request] status=200 raw={"result":true,"status":"ok","time":0.462744816}
- [mixed-accepted evidence] describe status=200 vectors={"size": 4, "distance": "Cosine"} — rest face: read-back materialized ONLY the unnamed branch; the named entry "img" from the request was silently dropped (no diagnostic)
- [positive unnamed] status=200 raw={"result":true,"status":"ok","time":0.322916213} + [echo unnamed] branch=unnamed vectors={"size": 4, "distance": "Cosine"} — rest face: unnamed oneOf branch accepted and materialized (positive closure)
- [positive named] status=200 raw={"result":true,"status":"ok","time":0.439253377} + [echo named] describe status=200 vectors={"img": {"size": 4, "distance": "Cosine"}} + [named upsert] status=200 + [count named] status=200 count=1 — rest face: named oneOf branch accepted, materialized, data plane usable (positive closure)
- [negative vectors as array] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorsConfig at line 1 column 33"},"time":0.0} — rest face: same untagged-enum machinery DOES reject non-object off-branch forms, isolating the acceptance to the object-with-extra-keys shape
- [negative vectors as string] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorsConfig at line 1 column 21"},"time":0.0}
- [negative unnamed size without distance (required path vectors.distance)] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorsConfig at line 1 column 24"},"time":0.0}

--- 契约（expected，来自该版本文档/契约） ---

assertion: vectors oneOf VectorParams{size, distance} | {name: VectorParams}; named and unnamed forms are mutually exclusive in one request
source_url: 
doc_version: 
