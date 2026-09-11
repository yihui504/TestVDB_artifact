# 候选缺陷 defect-14

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- legN1-valid-then-missing-collection: request rejected (404) but valid sibling action(s) ['sem_aup4_1788566083_bbe847_n1'] were applied — partial commit breaks the atomicity contract (qdrant_state_update_aliases_001); registry=['sem_aup4_1788566083_bbe847_n1', 'sem_aup4_1788566083_bbe847_p1', 'sem_aup4_1788566083_bbe847_p2']
- [setup] describe sem_aup4_1788566083_bbe847_missing_target: status=404 (404 expected)  [poisoned target proven absent before the batch]
- [legN1-valid-then-missing-collection] status=404 raw={"status":{"error":"Not found: Collection `sem_aup4_1788566083_bbe847_missing_target` doesn't exist!"},"time":0.012857657}
- [legP] all-valid batch: status=200 raw={"result":true,"status":"ok","time":0.04162911}  [positive control: full commit]
- rest | output_boundary_aliases_update_06.log:6: DISPOSITION(poison1): defect:Type4_StateLogicViolation — request failed (404) but valid prefix action leaked into the registry: 'bnd_aupd_g_06'->'bnd_aupd_c1_06' (atomicity broken)
- rest | output_state_aliases_update_03.log:8: Type4_StateLogicViolation: partial application after batch A: {'tvau3_1788566059_g1': 'tvau3c1_1788566059', 'tvau3_1788566059_g2': 'tvau3c1_1788566059'} -> {'tvau3_1788566059_g1': 'tvau3c1_1788566059', 'tvau3_1788566059_a1': 'tvau3c1_1788566059', 'tvau3_1788566059_g2': 'tvau3c1_1788566059'}; ... ; Type1_IllegalSuccess: batch with unknown-alias delete accepted with 200; ... (same endpoint, valid-prefix-leak reproduced in 3 batches)
- rest | comparative same-family asymmetry: invalid flavor create_alias->missing-collection is rejected 404 WITH partial commit (this log), while the same-family invalid flavor delete_alias->unknown-alias is accepted 200 (state_aliases_update_03 'Type1_IllegalSuccess: batch with unknown-alias delete accepted with 200') - source-level cause: AliasPersistence::remove returns Ok(None) on a missing alias (alias_mapping.rs:72-80), so that flavor never errors

--- 契约（expected，来自该版本文档/契约） ---

assertion: alias actions in one request apply atomically; no collection modifications can happen between alias operations within the request - queries via the alias during the switch always resolve to a live collection
source_url: 
doc_version: 
