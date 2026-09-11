# 候选缺陷 defect-15

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [delete-unknown-alias] status=200 raw={"result":true,"status":"ok","time":0.000017779}
- same log line 7 (rest, same-family create op, provably missing collection): [create-on-missing-collection] status=404 raw={"status":{"error":"Not found: Collection `sem_aup8_1788566091_30c5de_missing_5296680338` doesn't exist!"},"time":0.000018228}
- state_aliases_update_05.log:6 (rest, same unknown-alias semantic, other op key): [rename unknown a1] status=404 raw={"status":{"error":"Not found: Alias tvau5a1_1788566062 does not exists!"},"time":0.000021573}
- state_aliases_update_05.log:7-8 (rest, G9 never-existed vs just-deleted symmetry, both 404): [create -> never-existed] status=404 raw={"status":{"error":"Not found: Collection `tvau5never_1788566062` doesn't exist!"},"time":0.000019966} / [create -> just-deleted] status=404 raw={"status":{"error":"Not found: Collection `tvau5c2_1788566062` doesn't exist!"},"time":0.000014772}
- state_aliases_list_02.log:6 (rest, independent reproduction): [delete_alias unknown tvl2ghost_1788563051] status=200 raw={"result":true,"status":"ok","time":0.000016037} (documented 404/500)
- state_aliases_list_02.log:10 (rest, mutation-free postcondition on the accepted-but-no-op delete): tombstone clean; unknown-alias delete and missing-collection create left the global registry exactly unchanged
- boundary_aliases_update_06.log:8 (rest, batch face — poison action silently swallowed, valid prefix applied): DISPOSITION(poison2): defect:Type1_IllegalSuccess — delete_alias of unknown alias accepted with 200 (prefix alias persisted: True)

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 ok; 404 create_alias on missing collection; unknown-alias delete/rename -> error family (404/500 per knowledge)
source_url: 
doc_version: 
