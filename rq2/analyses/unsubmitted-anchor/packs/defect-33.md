# 候选缺陷 defect-33

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [negative datatype=None] status=200 raw={"result":true,"status":"ok","time":0.458852388}
- same log: Type1_IllegalSuccess: negative create (datatype=None) accepted with 200: {"result":true,"status":"ok","time":0.458852388}
- same log (closure enforced for non-null non-members): [negative datatype='float64'] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorsConfig at line 1 column 69"},"time":0.0}
- same log: [negative datatype='int8'] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorsConfig at line 1 column 66"},"time":0.0}
- same log: [negative datatype=7] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorsConfig at line 1 column 61"},"time":0.0}
- same log (case-mutated member): [negative datatype='FLOAT32'] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum VectorsConfig at line 1 column 69"},"time":0.0}
- same log (positive closure, all three): [positive datatype='float32'] status=200 raw={"result":true,"status":"ok","time":0.445217947} (float16 and uint8 likewise 200)

--- 契约（expected，来自该版本文档/契约） ---

assertion: datatype in [float32, uint8, float16, turbo4]; uint8 dense vectors hold integers in range 0-255; turbo4 cannot be configured for sparse vectors
source_url: 
doc_version: 
