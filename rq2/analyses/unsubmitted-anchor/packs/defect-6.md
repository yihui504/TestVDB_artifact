# 候选缺陷 defect-6

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- STEP5 listing(after drop): expected=404 actual=200 body[:300]='{"result":{"aliases":[]},"status":"ok","time":5.513e-6}'
- STEP4 describe(after drop): expected=404 actual=404 body[:200]='{"status":{"error":"Not found: Collection `bnd_aliases_coll_09` doesn\'t exist!"},"time":6.512e-6}' [face: rest describe GET /collections/{name} — SAME collection_name correctly 404s with a diagnostic naming it; deletion thereby confirmed]
- STEP2 listing(before delete): expected=200+'bnd_alias_a09' actual=200 body[:300]='{"result":{"aliases":[{"alias_name":"bnd_alias_a09","collection_name":"bnd_aliases_coll_09"}]},"status":"ok","time":8.516e-6}' [face: rest per-collection aliases — positive direction of the promise holds pre-delete]
- DISPOSITION: defect:Type4_StateLogicViolation — listing answered 200 for a deleted collection [triggering log's own disposition line]
- [post-delete per-collection tva2c_1788526086] status=200 raw={"result":{"aliases":[]},"status":"ok","time":6.987e-6} [face: rest per-collection aliases, other script state_aliases_collection_list_02 — same phenomenon]
- [post-delete global aliases] status=200 raw={"result":{"aliases":[]},"status":"ok","time":6.833e-6} [face: rest global GET /aliases — alias removed together with the collection, no dangling entry]
- [post-recreate per-collection tva2c_1788526086] status=200 raw={"result":{"aliases":[]},"status":"ok","time":6.085e-6} [face: rest per-collection aliases after recreation — still 200 empty, deterministic not stale]

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 list of {alias_name, collection_name}; 404 unknown collection
source_url: 
doc_version: 
