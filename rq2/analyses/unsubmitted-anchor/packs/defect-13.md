# 候选缺陷 defect-13

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [leg] item-two-op-keys: status=200 raw={"result":true,"status":"ok","time":0.010493592} — one actions item carrying BOTH create_alias {alias_name:<ns>_x2, collection_name:<ns>_c} AND delete_alias {alias_name:<ctrl>} accepted with HTTP 200 success
- rest | [pos-control] create_alias sem_aup1_1788566079_84d1ad_ctrl: 200 {"result":true,"status":"ok","time":0.023735713} (G4 positive control: well-formed single-discriminator item accepted — endpoint is live and processing, so the 200 on the dual-key leg is not an environment artifact)
- rest | [leg] item-empty-object: status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum AliasOperations at line 1 column 16"},"time":0.0} (same closed-set enum domain, zero-key item: rejected)
- rest | [leg] item-unknown-op-key (create_aliases): status=400 raw={"status":{"error":"Format error in JSON body: data did not match any variant of untagged enum AliasOperations at line 1 column 132"},"time":0.0} (unknown discriminator: rejected — same-family comparative observation: zero-key and unknown-key items get 400, only the dual-key item gets 200)
- rest | output_boundary_aliases_update_02.log: 'LEG L2 dual discriminator: expected=4xx actual=200 body[:200]='{"result":true,"status":"ok","time":0.017621301}'' plus 'DISPOSITION(final): defect:Type1_IllegalSuccess residue — oneOf-violating legs left alias state behind: {'bnd_aupd_x_02': 'bnd_aupd_c1_02'}' (cross-script reproduction: the create branch of the dual-key item landed in the registry while its embedded delete_alias was silently swallowed)
- rest | output_state_aliases_update_01.log: '[neg dual-op-keys] status=200 raw={"result":true,"status":"ok","time":0.01550202}' plus 'registry delta=['tvau1n2_1788566057']' (cross-script reproduction: dual-key item mutated the alias registry via its first operation key)
- face_unavailable: gRPC/SDK faces not probed in this sandbox (all scripts exercise the REST face only); source-level comparative fact recorded instead — the gRPC AliasOperations.action is a prost oneof (lib/api/src/grpc/qdrant.rs:1702, tags 1,2,3), structurally inexpressible as a dual-key payload on the gRPC wire; the permissiveness is specific to the REST/serde-untagged face

--- 契约（expected，来自该版本文档/契约） ---

assertion: actions items oneOf create_alias | delete_alias | rename_alias operations
source_url: 
doc_version: 
