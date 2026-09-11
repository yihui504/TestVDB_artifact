# 候选缺陷 defect-61

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [D3a with_lookup wrong type] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum WithLookupInterface at line 1 column 142"},"time":0.0}
- [D3b with_lookup empty object] status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum WithLookupInterface at line 1 column 125"},"time":0.0}
- [D2a group_size=0] status=422 raw={"status":{"error":"Validation error in JSON body: [search_group_request.group_request.group_size: value 0 invalid, must be 1 or larger]"},"time":0.0} — IN-LOG CONTRAST: validator-class error names the FULL parameter path
- [D2b limit=0] status=422 raw={"status":{"error":"Validation error in JSON body: [search_group_request.group_request.limit: value 0 invalid, must be 1 or larger]"},"time":0.0} — IN-LOG CONTRAST
- [D1 missing group_by] status=400 raw={"status":{"error":"Format error in JSON body: missing field `group_by` at line 1 column 60"},"time":0.0} — IN-LOG CONTRAST: missing-FIELD form DOES name the field; the no-variant untagged form does not
- [D4 group_by empty] status=400 raw={"status":{"error":"Format error in JSON body: Invalid json path: '' at line 1 column 103"},"time":0.0} — third Type2 leg in the same verdict; NOTE already booked as PRIMARY by boundary_grp_typeA_01 (grade A, same endpoint, incl. live re-probes 2026-09-08) — dedup for the adjudicator, not a new booking
- [builder live re-probe 2026-09-08 P1, same-day reproduction] with_lookup={"collection":123} POST query/groups -> http=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum WithLookupInterface at line 1 column 115"},"time":0.0}

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 {groups: [{id, hits}]}; requires payload values on the group_by field; offset not allowed
source_url: 
doc_version: 
