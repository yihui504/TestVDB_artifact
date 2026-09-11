# 候选缺陷 defect-12

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- LEG N2: expected=404/500 actual=200 body[:200]='{"result":true,"status":"ok","time":0.000015718}'
- same-log positive control: LEG P1 create T->c1: expected=200 actual=200 body[:200]='{"result":true,"status":"ok","time":0.011087971}' (P2 rename and P3 delete legs also 200-clean with verified registry effects)
- same-log contrast leg (existence gate present for create): LEG N1: expected=404 actual=404 body[:200]='{"status":{"error":"Not found: Collection `bnd_aupd_no_such_collection_08` doesn\'t exist!"},"time":0.000025213}'
- same-log disposition: DISPOSITION(N2): defect:Type4_StateLogicViolation — unknown-alias delete returned the happy-path outcome 200 (silent success)
- comparative-forensics rest-face same-family (sibling script boundary_aliases_update_09.log L1, never-existing alias, rename arm): LEG L1: expected=404/500 actual=404 body[:200]='{"status":{"error":"Not found: Alias bnd_aupd_never_09 does not exists!"},"time":0.000012993}' — same condition, sibling enum member returns 404 with alias-naming diagnostics while delete returns 200
- comparative-forensics rest-face same-family, both sides in one script (output_state_aliases_update_05.log L5-L6, same unknown alias): [re-delete unknown a1] status=200 raw={"result":true,"status":"ok","time":0.000013825}  ||  [rename unknown a1] status=404 raw={"status":{"error":"Not found: Alias tvau5a1_1788566062 does not exists!"},"time":0.000021573}
- multi-script reproduction (semantic_aliases_update_008.log:8): [delete-unknown-alias] status=200 raw={"result":true,"status":"ok","time":0.000017779}

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 ok; 404 create_alias on missing collection; unknown-alias delete/rename -> error family (404/500 per knowledge)
source_url: 
doc_version: 
