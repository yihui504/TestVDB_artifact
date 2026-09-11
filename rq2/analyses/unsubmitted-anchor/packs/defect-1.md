# 候选缺陷 defect-1

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- LEG unknown-collection listing: expected=404 (4xx tolerated with note) actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":0.000010428}'
- PRECHECK describe('bnd_no_such_coll_02_x7q'): expected=404 actual=404 body[:200]='{"status":{"error":"Not found: Collection `bnd_no_such_coll_02_x7q` doesn't exist!"},"time":8.905e-6}' — rest face, same name, sibling face rejects (proves the collection is nonexistent at test time)
- DISPOSITION: defect:Type4_StateLogicViolation — alias listing served (200) for a provably nonexistent collection
- builder live repro 2026-09-04, rest face, sandbox qdrant 1.18.0 commit db3fca3: GET /collections/bnd_no_such_coll_02_x7q/aliases -> http=200 body {"result":{"aliases":[]},"status":"ok","time":7.964e-6} — identical pattern reproduced
- comparative rest face, same unknown name: GET /collections/bnd_no_such_coll_02_x7q -> http=404 {"status":{"error":"Not found: Collection `bnd_no_such_coll_02_x7q` doesn't exist!"}}
- comparative rest face, same unknown name: GET /collections/bnd_no_such_coll_02_x7q/cluster -> http=404 (identical 'doesn't exist!' error)
- comparative rest face, same unknown name: GET /collections/bnd_no_such_coll_02_x7q/shards -> http=404 (identical 'doesn't exist!' error) — same-family per-collection listing face rejects unknown collection

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 list of {alias_name, collection_name}; 404 unknown collection
source_url: 
doc_version: 
