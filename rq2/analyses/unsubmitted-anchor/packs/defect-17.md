# 候选缺陷 defect-17

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [neg dual-op-keys] status=200 raw={"result":true,"status":"ok","time":0.01550202}
- [pos create_alias] status=200 raw={"result":true,"status":"ok","time":0.014785734} (face=rest; positive control: each legal oneOf branch alone is accepted)
- [pos rename_alias] status=200 raw={"result":true,"status":"ok","time":0.014610593} (face=rest)
- [pos delete_alias] status=200 raw={"result":true,"status":"ok","time":0.013017557} (face=rest)
- [neg unknown-op-key] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum AliasOperations at line 1 column 110"},"time":0.0} (face=rest; same-family discriminator variant, unknown op key 'create_aliases')
- [neg opless-item] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum AliasOperations at line 1 column 16"},"time":0.0} (face=rest; item={})
- [neg scalar-op-payload] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum AliasOperations at line 1 column 47"},"time":0.0} (face=rest; create_alias:"not-an-object")

--- 契约（expected，来自该版本文档/契约） ---

assertion: actions items oneOf create_alias | delete_alias | rename_alias operations
source_url: 
doc_version: 
