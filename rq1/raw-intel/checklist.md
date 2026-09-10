# Phase 1 issue 分类人工核对清单 (124 issues + 2 PRs = 126 条)

生成: 2026-08-13 | 数据: pipelinehost/data/vdbms-issues.csv

## 分类标准

| 分类                     | 硬判据                                                       |
| ---------------------- | --------------------------------------------------------- |
| `TP_FIXED_PR`          | 真修复: timeline 有 cross-ref PR 或 maintainer 明说 fixed via PR |
| `TP_ACK_OPEN`          | bug 确认未修: open + maintainer triage/accepted label         |
| `TP_ACK_CLOSED_NOFIX`  | bug 确认但关闭时无 PR                                            |
| `TP_DUP_TRACKED`       | maintainer "closed as dup", bug 归母 issue 跟踪               |
| `BY_DESIGN`            | by-design/wontfix label 或 state\_reason=not\_planned      |
| `FP_BY_DESIGN`         | maintainer 评论反驳为设计行为 (label 无 by-design 但评论判定)            |
| `FP_NOT_REPRO`         | maintainer 无法复现                                           |
| `STALE_NO_FIX`         | stale\[bot] 自动关, 无修复证据                                    |
| `PENDING_SELF_LABELED` | open + bug label, 无 maintainer accept                     |
| `SELF_CLOSED`          | closed, 无 bug label, closed\_by=<submitter>                  |
| `OPEN_NO_LABEL`        | open, 无 bug label                                         |
| `SELF_PR_OPEN`         | 自己提交的修复 PR, open (maintainer review 中)                    |
| `SELF_PR_CLOSED`       | 自己提交的修复 PR, 已关未 merge                                     |

核对方法: 每行 `- [ ]` 打钩=同意当前分类; 打 `x` 并注明新分类+理由。证据列给了判定依据。

## milvus-io/milvus (63)

### TP\_FIXED\_PR (4)

- [ ] **#47763** | `TP_FIXED_PR` | \[Bug]:  Field name validation missing - accepts invalid field names causing data inaccessibility | maintainer xiaofan-luan: "final fix I made: Relaxed dynamic field key validation"
- [ ] **#49890** | `TP_FIXED_PR` | \[Bug]: REST API v2 accepts non-integer `Request-Timeout` header values | timeline PR #50195 "fix: validate REST request timeout header" (xiaofan-luan), sre-ci-robot 关
- [ ] **#51084** | `TP_FIXED_PR` | \[Bug]: REST API silently substitutes invalid `consistencyLevel` enum value with default instead of rejecting | maintainer yanliang567: "i have made a pr to fix it"
- [ ] **#51085** | `TP_FIXED_PR` | \[Bug]: REST API silently substitutes invalid `vectorFieldType` enum value with default instead of rejecting | maintainer yanliang567: "i had pr to fix it"

### TP\_ACK\_OPEN (14)

- [ ] **#47729** | `TP_ACK_OPEN` | \[Bug]: Index parameter nprobe validation missing - accepts nprobe=0 | open/reopened | labels: kind/bug|triage/accepted
- [ ] **#49823** | `TP_ACK_OPEN` | \[Bug]: REST API v2 accepts nprobe=0 in search requests without validation | open/ | labels: kind/bug|triage/accepted
- [ ] **#49889** | `TP_ACK_OPEN` | \[Bug]: REST API v2 accepts empty string for `dbName` parameter | open/ | labels: kind/bug|triage/accepted
- [ ] **#49930** | `TP_ACK_OPEN` | \[Bug]: REST API v2 accepts invalid searchParams (ef=0/-1 for HNSW, nprobe=0/-1 for IVF\_FLAT) without validation | open/ | labels: kind/bug|triage/accepted
- [ ] **#50323** | `TP_ACK_OPEN` | \[Bug]: Delete endpoint accepts both filter and ids (mutually exclusive) silently | open/ | labels: kind/bug|triage/accepted
- [ ] **#50353** | `TP_ACK_OPEN` | \[Bug]: REST API v2: search returns HTTP 200 for limit=0/-1 and dimension mismatch | open/ | labels: kind/bug|triage/accepted
- [ ] **#50354** | `TP_ACK_OPEN` | \[Bug]: REST API v2: password complexity not enforced — "abcdefgh" accepted on users/create | open/ | labels: kind/bug|triage/accepted
- [x] **#50355** | `TP_ACK_OPEN` | \[Bug]: Upsert fails on autoID=true collections despite documentation claiming support | open/ | labels: kind/bug|triage/accepted：开发者事实上提到了已经合并的文档修复，应算TP\_FIXED\_PR
- [x] **#52309** | `TP_ACK_OPEN` | \[Bug]: REST API v2 `entities/search` accepts `group_size=0` and `-1` (gRPC rejects as "negative") | open/ | labels: kind/bug|triage/accepted：开发者提到了已经合并的修复，应算TP\_FIXED\_PR
- [x] **#52311** | `TP_ACK_OPEN` | \[Bug]: REST API v2 silently accepts `group_by_field` on vector fields (gRPC rejects "unsupported data type") | open/ | labels: kind/bug|triage/accepted：开发者提到了已经合并的修复，应算TP\_FIXED\_PR
- [x] **#52313** | `TP_ACK_OPEN` | \[Bug]: entities/insert JSON field — plain strings stored in inconsistent formats across REST/gRPC; written values unreadable via gRPC (round-trip failure) | open/ | labels: kind/bug|triage/accepted：开发者提到了已经合并的修复，应算TP\_FIXED\_PR
- [ ] **#52314** | `TP_ACK_OPEN` | \[Bug]: REST API v2 `entities/upsert` silently coerces scalar types (string→DOUBLE, string→BOOL, int→BOOL, string→INT16) | open/ | labels: kind/bug|triage/accepted
- [x] **#52315** | `TP_ACK_OPEN` | \[Bug]: REST API v2 `entities/insert` accepts string-encoded vector values (gRPC rejects) | open/ | labels: kind/bug|triage/accepted：开发者提到了已经合并的修复，应算TP\_FIXED\_PR
- [x] **#52325** | `TP_ACK_OPEN` | \[Bug]: REST v2 entities/search silently ignores strictGroupSize | open/ | labels: kind/bug|triage/accepted：开发者提到了已经合并的修复，应算TP\_FIXED\_PR

### TP\_ACK\_CLOSED\_NOFIX (2)

- [ ] **#47752** | `TP_ACK_CLOSED_NOFIX` | \[Bug]: Index parameter ef validation missing - accepts ef=0 | foxspy 分析: ef validation 仅 HNSW path 生效, 小数据集 brute-force path 有缺口; 关时无 PR
- [ ] **#47755** | `TP_ACK_CLOSED_NOFIX` | \[Bug]: Filter expression validation too lenient | xiaofan-luan "suggestion is overall good" + zhengbuqian "misunderstanding of in expr"; 关时无 PR

### TP\_DUP\_TRACKED (4)

- [x] **#52307** | `TP_DUP_TRACKED` | \[Bug]: entities/upsert JSON field — plain string overwrites valid JSON; written value unreadable via gRPC; REST/gRPC store inconsistent formats | yanliang567: "closed as dup"：开发者在提fix pr的时候仍引用了该issue，相反的，开发者在提fix pr的时候并未引用**52308、52310、52312，所以放在**TP\_DUP\_TRACKED可能不合适。
- [ ] **#52308** | `TP_DUP_TRACKED` | \[Bug]: REST API v2 `entities/insert` accepts string numbers for Int64 primary key (type coercion gap; gRPC rejects) | yanliang567: "close as dep"
- [ ] **#52310** | `TP_DUP_TRACKED` | \[Bug]: REST API v2 `entities/insert` silently coerces scalar types (string→Int64, int→VarChar, string→Bool); gRPC rejects all | yanliang567: "lets track the issue in the dup issues above"
- [ ] **#52312** | `TP_DUP_TRACKED` | \[Bug]: REST API v2 `entities/upsert` accepts string numbers for Int64 primary key (gRPC rejects) | yanliang567: "closed as dup"

### BY\_DESIGN (12)

- [ ] **#47767** | `BY_DESIGN` | \[Bug]: Empty query vector accepted in search - no validation error | closed/completed | labels: resolution/by-design
- [ ] **#49928** | `BY_DESIGN` | \[Bug]: Default proxy.maxDimension=32768 is too permissive, potential DoS risk via high-dimensional collection creation | closed/completed | labels: resolution/by-design
- [ ] **#49929** | `BY_DESIGN` | \[Bug]: REST API and PyMilvus SDK have inconsistent default index creation behavior | closed/completed | labels: resolution/by-design
- [ ] **#50192** | `BY_DESIGN` | \[Bug] Concurrent rename and create with same target name both succeed, causing state violation | open/ | labels: resolution/by-design
- [ ] **#50193** | `BY_DESIGN` | \[Bug] get\_stats returns rowCount=0 after successful insert and load (v2.6.16, regression from #30663) | open/ | labels: resolution/by-design
- [ ] **#50194** | `BY_DESIGN` | \[Bug] Concurrent delete and search returns stale/deleted data | open/ | labels: resolution/by-design
- [ ] **#50319** | `BY_DESIGN` | \[Bug]: Search on unloaded collection returns valid results (code=0) | open/ | labels: kind/bug|resolution/by-design
- [ ] **#50321** | `BY_DESIGN` | \[Bug]: Duplicate collection creation returns code=0 instead of error | open/ | labels: kind/bug|resolution/by-design
- [ ] **#50322** | `BY_DESIGN` | \[Bug]: Drop non-existent collection returns code=0 instead of code=4 | open/ | labels: kind/bug|resolution/by-design
- [ ] **#50325** | `BY_DESIGN` | \[Bug]: Collection names with leading underscore accepted despite naming rules | closed/completed | labels: kind/bug|resolution/by-design
- [ ] **#50351** | `BY_DESIGN` | \[Bug]: REST API v2: shardsNum=0/-1/65535 accepted with HTTP 200 + code=200 | closed/completed | labels: kind/bug|resolution/by-design
- [ ] **#50352** | `BY_DESIGN` | \[Bug]: REST API v2: metricType="" and consistencyLevel="None" silently accepted on collections/create | closed/completed | labels: kind/bug|resolution/by-design

### FP\_BY\_DESIGN (2)

- [ ] **#49844** | `FP_BY_DESIGN` | \[Bug]: REST API v2 query accepts null/missing filter and silently returns all entities | MrPresent-Han: "not a real server-side bug... breaking validation"
- [ ] **#50324** | `FP_BY_DESIGN` | \[Bug]: REST API: Insert accepts 101 entities (exceeding documented 100 limit) | yanliang567: "sounds like a document issue, share the doc link"

### STALE\_NO\_FIX (6)

- [x] **#47635** | `STALE_NO_FIX` | \[Bug]: Search fails with Code 0 immediately after Collection.load() returns success | yanliang567: "milvus 2.3 is very old, upgrade to 2.5.26/2.6.10" + stale\[bot] 关：毕竟是TP且没被修，更适合算`TP_ACK_CLOSED_NOFIX `
- [ ] **#47636** | `STALE_NO_FIX` | \[Bug]: Expr parser returns code=0 (Success) and leaks internal lexer errors | yanliang567: "please retry on milvus 2.5.26 or 2.6.10" + stale\[bot] 关
- [x] **#47766** | `STALE_NO_FIX` | \[Bug]: Data type validation missing - accepts integer into string field | 仅 assign @liliu-z 后无下文, stale\[bot] 关：毕竟是TP且没被修，更适合算`TP_ACK_CLOSED_NOFIX `
- [x] **#49059** | `STALE_NO_FIX` | \[Bug]: COSINE Metric Returns Distance > 1.0 for Identical Vectors (Precision Overflow) | xiaofan-luan "good suggestion", 社区 kailash360 认领后无下文, stale\[bot] 关：毕竟是TP且没被修，更适合算`TP_ACK_CLOSED_NOFIX `
- [x] **#49843** | `STALE_NO_FIX` | \[Bug]: REST API v2 silently drops negative collection.ttl.seconds on collection create | stale\[bot] 30d 自动关, 无修复证据：开发者事实上在一个fix pr提到了，可能需要转`TP_FIXED_PR`
- [x] **#50018** | `STALE_NO_FIX` | \[Bug]: REST API v2 aliases/list accepts empty collectionName while other endpoints properly reject it | yanliang567: "not a big problem, could make an improvement" + stale\[bot] 关：毕竟是TP且没被修，更适合算`TP_ACK_CLOSED_NOFIX `

### SELF\_CLOSED (17)

- [ ] **#49824** | `SELF_CLOSED` | \[Bug]: REST API v2 returns success when creating a collection with a duplicate name | closed/completed
- [ ] **#49849** | `SELF_CLOSED` | \[Bug]: REST API v2 insert returns insertCount=1 for duplicate primary key (upsert semantics) | closed/completed
- [ ] **#49850** | `SELF_CLOSED` | \[Bug]: REST API v2 describe indexes requires indexName, cannot list all indexes | closed/completed
- [ ] **#50305** | `SELF_CLOSED` | \[Bug] Search on unloaded collection returns valid results (code=0) | closed/completed
- [ ] **#50306** | `SELF_CLOSED` | \[Bug] Duplicate collection creation returns code=0 instead of error | closed/completed
- [ ] **#50307** | `SELF_CLOSED` | \[Bug] Drop non-existent collection returns code=0 instead of code=4 | closed/completed
- [ ] **#50308** | `SELF_CLOSED` | \[Bug] Delete accepts both filter and ids (mutually exclusive) silently | closed/completed
- [ ] **#50309** | `SELF_CLOSED` | \[Bug] Consistency level silently accepts invalid values and defaults to Bounded | closed/completed
- [ ] **#50310** | `SELF_CLOSED` | \[Bug] REST API: Insert accepts 101 entities (exceeding documented 100 limit) | closed/completed
- [ ] **#50311** | `SELF_CLOSED` | \[Bug] REST API: Unicode-only collection names silently accepted | closed/completed
- [ ] **#50312** | `SELF_CLOSED` | \[Bug] Rename collection to its own name returns code=0 | closed/completed
- [ ] **#50313** | `SELF_CLOSED` | \[Bug] Search on unloaded collection returns valid results (code=0) | closed/completed
- [ ] **#50314** | `SELF_CLOSED` | \[Bug] Duplicate collection creation returns code=0 instead of error | closed/completed
- [ ] **#50315** | `SELF_CLOSED` | \[Bug] Drop non-existent collection returns code=0 instead of code=4 | closed/completed
- [ ] **#50316** | `SELF_CLOSED` | \[Bug] Delete endpoint accepts both filter and ids (mutually exclusive) silently | closed/completed
- [ ] **#50317** | `SELF_CLOSED` | \[Bug] REST API: Insert accepts 101 entities (exceeding documented 100 limit) | closed/completed
- [ ] **#50318** | `SELF_CLOSED` | \[Bug] Collection names with leading underscore accepted despite naming rules | closed/completed

### SELF\_PR\_OPEN (1)

- [ ] **#51809** | `SELF_PR_OPEN` | PR: fix: validate vector search params via knowhere Config::Load at plan creation (#47729) | PR (Fixes #47729): rewrite 版, xiaofan-luan 两轮 review + CI 全绿, 等 final approve

### SELF\_PR\_CLOSED (1)

- [ ] **#47785** | `SELF_PR_CLOSED` | PR: fix: add nprobe parameter validation for IVF index search (Fixes #47729) | PR (Fixes #47729): 第一版 nprobe validation 修复, stale\[bot] 关未 merge, 被 #51809 rewrite 取代

## qdrant/qdrant (33)

### TP\_FIXED\_PR (4)

- [ ] **#9017** | `TP_FIXED_PR` | hnsw\_ef accepts 0 | timvisee: "Fixed via PR #9320"
- [ ] **#9039** | `TP_FIXED_PR` | Bug: Async upsert silently discards dimension-mismatched vectors (Poor Diagnostics) | timeline PR #9058 "validate vector dimensions before WAL write", generall 关
- [ ] **#9045** | `TP_FIXED_PR` | Bug: Empty vector `[]` upsert with `wait=false` can trigger server panic (zero-length assertion failure) | timvisee: "Fixed in PR #9070, included in Qdrant 1.18.1"
- [ ] **#9149** | `TP_FIXED_PR` | shard\_number=0 and negative values accepted during collection creation | timvisee: "already covered by PR #9178"

### BY\_DESIGN (3)

- [ ] **#9027** | `BY_DESIGN` | score\_threshold\_range\_issue | closed/not\_planned | labels: bug
- [ ] **#9371** | `BY_DESIGN` | Bug: Batch operations not atomic — valid points persisted despite HTTP 400 error | open/ | labels: wontfix
- [ ] **#9523** | `BY_DESIGN` | Search offset pagination returns duplicate point IDs across pages (HNSW approximation) | closed/not\_planned | labels: bug

### FP\_BY\_DESIGN (5)

- [ ] **#9416** | `FP_BY_DESIGN` | `vectors={}` silently accepted during collection creation — produces unusable collection | coszio: "not an unusable collection, allows payload-only collection"
- [ ] **#9417** | `FP_BY_DESIGN` | Missing `vectors` field silently accepted during collection creation — produces unusable collection | coszio: "See #9416" (同 9416 判定)
- [ ] **#9418** | `FP_BY_DESIGN` | `filter.should=null` silently accepted in query/search — null filter condition ignored | coszio: "This is fine and expected... would be a breaking change"
- [ ] **#9419** | `FP_BY_DESIGN` | `filter.must_not` accepts object instead of array — type mismatch silently ignored | coszio: "supports null/object/array. fine and expected"
- [ ] **#9420** | `FP_BY_DESIGN` | `query=null` silently accepted — returns all points instead of being rejected | coszio: "breaking change... not worth it"

### FP\_NOT\_REPRO (2)

- [ ] **#9255** | `FP_NOT_REPRO` | Payload filter returns points with missing payload field (payload=None) | 0xDjole: "failed to reproduce on 1.18.1" (comment 提到 1.8.1 为笔误, 复测 1.18.1)
- [ ] **#9373** | `FP_NOT_REPRO` | Bug: Payload index silently returns severely incomplete results — 2/25 matching points after wait:true | generall: "not sure I am able to reproduce without exotic params"

### PENDING\_SELF\_LABELED (15)

- [ ] **#8688** | `PENDING_SELF_LABELED` | \[Bug]: Cosine similarity score strictly exceeds upper bound of 1.0 for identical vectors | open/ | labels: bug
- [ ] **#9044** | `PENDING_SELF_LABELED` | Collection creation accepts `size=65536` despite FAQ stating maximum is 65,535 (off-by-one) | open/ | labels: bug
- [ ] **#9372** | `PENDING_SELF_LABELED` | Strict mode inconsistently validates zero values — allows creation of unusable collections | open/ | labels: bug
- [x] **#9421** | `PENDING_SELF_LABELED` | `POST /cluster/recover` returns HTTP 500 in standalone mode — should return 4xx | open/ | labels: bug：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [x] **#9520** | `PENDING_SELF_LABELED` | Server crash on collection creation with shard\_number=INT\_MAX — missing upper-bound validation unlike replication\_factor | open/ | labels: bug：建议查清情况，允许的话提TP\_FIXED\_PR，bot在fix pr中提及该issue
- [ ] **#9521** | `PENDING_SELF_LABELED` | Silent data loss: named vector upsert in single-vector collection returns 200 OK but point is discarded | open/ | labels: bug
- [x] **#9522** | `PENDING_SELF_LABELED` | Query API silently returns 200 OK when lookup\_from references a non-existent collection | open/ | labels: bug：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#9525** | `PENDING_SELF_LABELED` | Systemic: serde deserialization errors across 7 endpoints expose Rust internal types (usize/u32/f32) and lack parameter names | open/ | labels: bug
- [ ] **#9869** | `PENDING_SELF_LABELED` | Write operations accept `timeout=0` despite the OpenAPI schema declaring `minimum: 1` | open/ | labels: bug
- [ ] **#9942** | `PENDING_SELF_LABELED` | OpenAPI schema for `VectorParams.size` is missing the enforced `maximum: 65536` constraint | open/ | labels: bug
- [x] **#10120** | `PENDING_SELF_LABELED` | `count` `exact=false` on `is_empty` under-counts \~35% consistently; `is_null` on the same field is correct | open/ | labels: bug：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#10124** | `PENDING_SELF_LABELED` | `count` `exact=false` on numeric/datetime `range` filter returns bidirectionally-wrong counts (histogram estimator) | open/ | labels: bug
- [ ] **#10125** | `PENDING_SELF_LABELED` | `count` `exact=false` on compound filter under-counts 20-60% when conditions touch the same field (independence assumption) | open/ | labels: bug
- [ ] **#10126** | `PENDING_SELF_LABELED` | `count` `exact=false` on `geo_radius` degenerates: medium radii collapse to a fixed value, large radii return the collection total | open/ | labels: bug
- [ ] **#10127** | `PENDING_SELF_LABELED` |  `count` `exact=false` on `match_any` (multi-value) under-counts, increasingly with value count (independent-OR assumption) | open/ | labels: bug

### SELF\_CLOSED (3)

- [ ] **#9364** | `SELF_CLOSED` | Bug: Batch operations partially apply despite returning HTTP 400 error (atomicity violation) | closed/completed
- [ ] **#9365** | `SELF_CLOSED` | Bug: Payload index returns incorrect filtered results — index corruption after creation | closed/completed
- [ ] **#9366** | `SELF_CLOSED` | Bug: Named vector lifecycle operations (update+delete) corrupt search — returns 400 | closed/completed

### OPEN\_NO\_LABEL (1)

- [ ] **#9524** | `OPEN_NO_LABEL` | Invalid filter conditions silently accepted (200 OK) with poor error diagnostics across search/query/scroll endpoints | open/

## weaviate/weaviate (30)

### TP\_FIXED\_PR (2)

- [ ] **#11729** | `TP_FIXED_PR` | shardingConfig.desiredCount accepts negative values but rejects zero | timeline PR #11824 "fix(sharding): reject negative desiredCount (gh-11729)", trengrj 关
- [ ] **#12041** | `TP_FIXED_PR` | Batch delete returns HTTP 500 instead of 422 when match.where or match.class is missing | timeline PR #12049 "gh-12041 return 422 for batch delete", dirkkul 关

### BY\_DESIGN (1)

- [ ] **#11436** | `BY_DESIGN` | Negative `ef` value (-1) accepted in vectorIndexConfig without validation error | closed/not\_planned | labels: bug|community

### FP\_BY\_DESIGN (1)

- [ ] **#11981** | `FP_BY_DESIGN` | POST /v1/batch/objects accepts empty vector `[]` and reports per-item SUCCESS (singular POST /v1/objects rejects with 422) | dudanogueira: "working as intended, OpenAPI claim does not hold"

### PENDING\_SELF\_LABELED (21)

- [ ] **#11399** | `PENDING_SELF_LABELED` | dynamicEfMin > dynamicEfMax accepted during collection creation (no validation) | open/ | labels: bug|community：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#11400** | `PENDING_SELF_LABELED` | flatSearchCutoff accepts negative values (no validation) | open/ | labels: bug|community：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#11401** | `PENDING_SELF_LABELED` | replicationFactor=-1 accepted and silently normalized to 1 (no validation) | open/ | labels: bug|community：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#11402** | `PENDING_SELF_LABELED` | bq.rescoreLimit=-1 accepted and silently discarded (no validation) | open/ | labels: bug|community
- [ ] **#11660** | `PENDING_SELF_LABELED` | REST API GET /v1/objects silently accepts negative limit parameter | open/ | labels: bug|community
- [ ] **#11661** | `PENDING_SELF_LABELED` | REST API GET /v1/objects returns HTTP 500 instead of 4xx when limit exceeds QUERY\_MAXIMUM\_RESULTS | open/ | labels: bug|community
- [ ] **#11730** | `PENDING_SELF_LABELED` | tokenization accepts empty string despite explicit OpenAPI enum constraint | open/ | labels: bug|community：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#11731** | `PENDING_SELF_LABELED` | replicationConfig.deletionStrategy accepts empty string outside explicit OpenAPI enum | open/ | labels: bug|community
- [ ] **#11732** | `PENDING_SELF_LABELED` | vectorIndexConfig.distance silently accepts null and defaults to cosine | open/ | labels: bug|community：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#11734** | `PENDING_SELF_LABELED` | multiTenancyConfig accepts null for boolean fields autoTenantCreation and autoTenantActivation | open/ | labels: bug|community
- [ ] **#11735** | `PENDING_SELF_LABELED` | int64 boundary value 9223372036854775807 silently truncated to 9223372036854776000 | open/ | labels: bug|community
- [ ] **#11736** | `PENDING_SELF_LABELED` | blob accepts long non-base64 garbage string without validation | open/ | labels: bug|community
- [ ] **#11737** | `PENDING_SELF_LABELED` | date accepts year 0000 and pre-1970 values without proper RFC3339 validation | open/ | labels: bug|community
- [ ] **#11738** | `PENDING_SELF_LABELED` | phoneNumber.defaultCountry accepts invalid ISO 3166-1 alpha-2 code "ZZ" | open/ | labels: bug|community
- [ ] **#11739** | `PENDING_SELF_LABELED` | phoneNumber.input accepts alphabetic characters like "CALL-NOW" without validation | open/ | labels: bug|community
- [ ] **#11740** | `PENDING_SELF_LABELED` | GraphQL queries accept negative limit values | open/ | labels: bug|community
- [ ] **#11741** | `PENDING_SELF_LABELED` | Tenant creation accepts empty string for activityStatus | open/ | labels: bug|community：：建议提TP\_FIXED\_PR，开发者在fix pr中提及该issue
- [ ] **#11742** | `PENDING_SELF_LABELED` | PQ bitCompression accepts string "true" instead of requiring boolean true | open/ | labels: bug|community
- [ ] **#11743** | `PENDING_SELF_LABELED` | text property accepts strings containing NUL bytes (\x00) without validation | open/ | labels: bug|community
- [ ] **#11744** | `PENDING_SELF_LABELED` | Text property accepts strings containing lone UTF-16 surrogates | open/ | labels: bug|community
- [ ] **#11745** | `PENDING_SELF_LABELED` | Text property accepts strings containing ASCII control characters (SOH, STX, ETX) | open/ | labels: bug|community

### SELF\_CLOSED (5)

- [ ] **#11395** | `SELF_CLOSED` | \[Bug]: dynamicEfMin > dynamicEfMax accepted during collection creation (no validation) | closed/completed
- [ ] **#11396** | `SELF_CLOSED` | \[Bug]: flatSearchCutoff accepts negative values (no validation) | closed/completed
- [ ] **#11397** | `SELF_CLOSED` | \[Bug]: replicationFactor=-1 accepted and silently normalized to 1 (no validation) | closed/completed
- [ ] **#11398** | `SELF_CLOSED` | \[Bug]: bq.rescoreLimit=-1 accepted and silently discarded (no validation) | closed/completed
- [ ] **#11433** | `SELF_CLOSED` | \[Schema Validation] Negative `ef` value (-1) accepted in vectorIndexConfig without validation error | closed/completed | labels: community

