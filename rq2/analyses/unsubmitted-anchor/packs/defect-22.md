# 候选缺陷 defect-22

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [attack] GET /cluster: status=200 raw={"result":{"status":"disabled"},"status":"ok","time":0.000029068}
- [context] result keys observed: ['status'] (recorded; only constraint-asserted fields are adjudicated) (same log)
- VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) (same log)
- 200 response violates the declared ClusterStatus shape (constraint qdrant_type_cluster_status_001, evidence_tier=explicit):  - peer_id: MISSING from result / - raft_state: MISSING from result (absent at both raft_state and raft_info.role) / - commit_index: MISSING from result (absent at both commit_index and raft_info.commit_index) / - peers: MISSING from result / observed result body: {"status": "disabled"} (same log)
- [env-confound] single-node default deployment (R4 live evidence: result is {"status":"disabled"} on /cluster); the constraint asserts these fields for the standalone response, so omission is adjudicated in-scope; flag surfaced for the judge per R4 audit convention (same log)
- rest reproduction script 2 (output_semantic_cluster_status_002.log): [attack] GET /cluster: status=200 raw={"result":{"status":"disabled"},"status":"ok","time":0.000024801} -> VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)
- rest reproduction script 2 cross-face leg: [G9 face asymmetry] the SAME server serializes peer_id=285485119185529 on the cluster+collection+info face - the declared field family is producible on this build, so the omission is specific to the named status face, not a global serialization impossibility (output_semantic_cluster_status_002.log)

--- 契约（expected，来自该版本文档/契约） ---

assertion: response ClusterStatus {peer_id uint64, raft_state in [Follower, Candidate, Leader, PreCandidate], commit_index uint64, peers map}
source_url: 
doc_version: 
