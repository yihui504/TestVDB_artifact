# 候选缺陷 defect-16

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [delete-unknown-alias] status=200 raw={"result":true,"status":"ok","time":0.000026368}
- output_semantic_aliases_update_009.log L8 (verdict line of the same primary observation): delete-unknown-alias: expected documented error family, got 2xx 200: {"result":true,"status":"ok","time":0.000026368}
- output_semantic_aliases_update_009.log L4 (positive control, create leg DID stay in family): [create-on-missing-collection] status=404 raw={"status":{"error":"Not found: Collection `sem_aup9_1788566093_87574e_missing_59c508e95b` doesn't exist!"},"time":0.000017707}
- output_semantic_aliases_update_009.log L5 (Type-2 rubric leg, reported only, no verdict): [create-on-missing-collection] score=1/3 (parameter_named=Y; format_hint=N; actionable=N; (existence-wording ext=Y, reported only)) text="Not found: Collection `sem_aup9_1788566093_87574e_missing_59c508e95b` doesn't exist!"
- COMPARATIVE face=rest same-family (sibling, rename of unknown alias on the SAME endpoint -> 404, asymmetric disposition vs delete -> 200): output_state_aliases_update_05.log L6: [rename unknown a1] status=404 raw={"status":{"error":"Not found: Alias tvau5a1_1788566062 does not exists!"},"time":0.000021573}
- multi-script repro 1 (face=rest): output_boundary_aliases_update_06.log L8: DISPOSITION(poison2): defect:Type1_IllegalSuccess — delete_alias of unknown alias accepted with 200 (prefix alias persisted: True)
- multi-script repro 2 (face=rest): output_state_aliases_list_02.log L6: [delete_alias unknown tvl2ghost_1788563051] status=200 raw={"result":true,"status":"ok","time":0.000016037} (documented 404/500)

--- 契约（expected，来自该版本文档/契约） ---

assertion: "expected_behavior": "200 ok; 404 create_alias on missing collection; unknown-alias delete/rename -> error family (404/500 per knowledge)"
source_url: 
doc_version: 
