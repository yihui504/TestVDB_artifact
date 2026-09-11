# 候选缺陷 defect-3

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- LEG cjk-emoji: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":4.474e-6}'
- LEG baseline-plain-ascii: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":5.111e-6}' — the plain-ASCII unknown name is ALSO accepted, so the phenomenon is value-class-independent, not special-value-specific
- NOTE (script line 21): baseline plain-ASCII unknown name itself defective — the asymmetry comparison is moot; defect already reported | DEFECT SUMMARY: 9/9 legs defective | VERDICT: DEFECT_FOUND (all 8 special-value legs: cjk-emoji, sql-injection, json-operator, json-escape, rtl-override, zero-width, trailing-dot, tab-char -> http=200 aliases=[])
- sibling boundary_aliases_col_list_02: LEG unknown-collection listing: expected=404 (4xx tolerated with note) actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":0.000010428}' DISPOSITION: defect:Type4_StateLogicViolation — same endpoint, same pattern, different script
- comparative rest face (live 2026-09-04, healthy container self-reporting version 1.18.0 commit db3fca3): GET /collections/bnd_plain_unknown_04 -> http=404 '{"status":{"error":"Not found: Collection `bnd_plain_unknown_04` doesn't exist!"}}' — SAME unknown name rejected by the collection-info face
- comparative rest faces (live 2026-09-04): GET /collections/bnd_plain_unknown_04/cluster -> http=404; GET .../shards -> http=404; GET .../snapshots -> http=404 (all 'Not found: Collection ... doesn't exist!') — every sibling collection-scoped read face 404s the same name; only the aliases face returns 200
- comparative rest face (live 2026-09-04): GET /collections/bnd_plain_unknown_04/aliases -> http=200 '{"result":{"aliases":[]},"status":"ok"}' (primary repro); CJK+emoji name and a%09b name -> identical 200 — byte-similar to the log

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 list of {alias_name, collection_name}; 404 unknown collection
source_url: 
doc_version: 
