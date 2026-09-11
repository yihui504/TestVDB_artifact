# 候选缺陷 defect-11

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- LEG poison1: expected=404-error-family+G-absent actual=404 body[:200]='{"status":{"error":"Not found: Collection `bnd_aupd_no_such_collection_06` doesn\'t exist!"},"time":0.014905373}' | DISPOSITION(poison1): defect:Type4_StateLogicViolation — request failed (404) but valid prefix action leaked into the registry: 'bnd_aupd_g_06'->'bnd_aupd_c1_06' (atomicity broken)
- LEG positive: expected=200 actual=200 body[:200]='{"result":true,"status":"ok","time":0.016263815}'
- DISPOSITION(positive): clean (valid batch applied; S->c1 visible)
- LEG poison2: expected=404/500+G2-absent actual=200 body[:200]='{"result":true,"status":"ok","time":0.015412519}'
- DISPOSITION(poison2): defect:Type1_IllegalSuccess — delete_alias of unknown alias accepted with 200 (prefix alias persisted: True)
- rest (state_aliases_update_03.log:8): Type4_StateLogicViolation: partial application after batch A: {'tvau3_1788566059_g1': 'tvau3c1_1788566059', 'tvau3_1788566059_g2': 'tvau3c1_1788566059'} -> {'tvau3_1788566059_g1': 'tvau3c1_1788566059', 'tvau3_1788566059_a1': 'tvau3c1_1788566059', 'tvau3_1788566059_g2': 'tvau3c1_1788566059'}; ... partial application after batch B (interleaved-invalid ordering) and after batch C (unknown-delete) likewise — both orderings leak the valid prefix
- rest (semantic_aliases_update_004.log:8): legN1-valid-then-missing-collection: request rejected (404) but valid sibling action(s) ['sem_aup4_1788566083_bbe847_n1'] were applied — partial commit breaks the atomicity contract (qdrant_state_update_aliases_001); registry=['sem_aup4_1788566083_bbe847_n1', 'sem_aup4_1788566083_bbe847_p1', 'sem_aup4_1788566083_bbe847_p2']

--- 契约（expected，来自该版本文档/契约） ---

assertion: alias actions in one request apply atomically; no collection modifications can happen between alias operations within the request - queries via the alias during the switch always resolve to a live collection
source_url: 
doc_version: 
