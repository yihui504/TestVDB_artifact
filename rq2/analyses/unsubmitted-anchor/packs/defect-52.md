# 候选缺陷 defect-52

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- LEG S1 idle: expected=200-with-ClusterStatus actual=200 body[:250]='{"result":{"status":"disabled"},"status":"ok","time":0.000056731}'
- DISPOSITION(S1): defect:Type2_PoorDiagnostics (declared defect_type_if_violated) — 200 on a standalone node without the promised ClusterStatus content; missing=['peer_id', 'raft_state', 'commit_index', 'peers'], actual result={'status': 'disabled'} [ENV-CONFOUND ledger: deployment=single-node with distributed mode disabled (supported default; registry doc_quote 'valid on single-node deployment'); R4 disabled-gate precedent family; adjudication deferred to judge with this flag]
- DISPOSITION(S4): defect:Type2_PoorDiagnostics (declared defect_type_if_violated) — 200 on a standalone node without the promised ClusterStatus content; missing=['peer_id', 'raft_state', 'commit_index', 'peers'], actual result={'status': 'disabled'} [ENV-CONFOUND ledger: deployment=single-node with distributed mode disabled (supported default; registry doc_quote 'valid on single-node deployment'); R4 disabled-gate precedent family; adjudication deferred to judge with this flag]
- OBSERVATION(F2): info-face peer_id=285485119185529 (independent reconciliation source)
- OBSERVATION(face-parity): G9 inconsistent-disposition signal, recorded — the per-collection face exposes peer_id while the global status face does not (info-face=285485119185529); same-parameter two-face asymmetry on a single node
- TYPE2-ASSESSMENT: names_condition=True names_capability=False suggests_remedy=False -> score 1/3 poor diagnostics: the 200 body neither identifies the capability nor suggests a remedy
- VERDICT: DEFECT_FOUND

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 ClusterStatus {peer_id, raft_state, commit_index, peers} on a standalone node
source_url: 
doc_version: 
