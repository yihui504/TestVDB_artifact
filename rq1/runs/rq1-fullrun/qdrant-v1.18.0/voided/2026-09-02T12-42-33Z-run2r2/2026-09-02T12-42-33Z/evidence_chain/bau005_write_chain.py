#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generator: writes evidence_chain/boundary_aliases_update_005.json (valid JSON via json.dump)."""
import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boundary_aliases_update_005.json")

excerpt = """lib/storage/src/content_manager/toc/collection_meta_ops.rs:298-338 (qdrant v1.18.0 clone):
298:    /// performs several alias changes in an atomic fashion
299:    async fn update_aliases(
300:        &self,
301:        operation: ChangeAliasesOperation,
302:    ) -> Result<bool, StorageError> {
303:        // Lock all collections for alias changes
304:        // Prevent search on partially switched collections
305:        let collection_lock = self.collections.write().await;
306:        let mut alias_lock = self.alias_persistence.write().await;
307:        for action in operation.actions {
308:            match action {
309:                AliasOperations::CreateAlias(CreateAliasOperation {
310:                    create_alias:
311:                        CreateAlias {
312:                            collection_name,
313:                            alias_name,
314:                        },
315:                }) => {
316:                    collection_lock.validate_collection_exists(&collection_name)?;
317:                    collection_lock.validate_collection_not_exists(&alias_name)?;
318:
319:                    alias_lock.insert(alias_name, collection_name)?;
320:                }
321:                AliasOperations::DeleteAlias(DeleteAliasOperation {
322:                    delete_alias: DeleteAlias { alias_name },
323:                }) => {
324:                    alias_lock.remove(&alias_name)?;
325:                }
326:                AliasOperations::RenameAlias(RenameAliasOperation {
327:                    rename_alias:
328:                        RenameAlias {
329:                            old_alias_name,
330:                            new_alias_name,
331:                        },
332:                }) => {
333:                    alias_lock.rename_alias(&old_alias_name, new_alias_name)?;
334:                }
335:            };
336:        }
337:        Ok(true)
338:    }

lib/storage/src/content_manager/alias_mapping.rs:66-70:
66:    pub fn insert(&mut self, alias: String, collection_name: String) -> Result<(), StorageError> {
67:        self.alias_mapping.0.insert(alias, collection_name);   // plain HashMap insert, no charset/pattern/length check
68:        self.alias_mapping.save(&self.data_path)?;             // persisted to JSON on disk as-is
69:        Ok(())
70:    }

lib/storage/src/content_manager/collection_meta_ops.rs:36-41 (no #[validate] attributes on either String field):
36: #[derive(Debug, Deserialize, Serialize, JsonSchema, PartialEq, Eq, Hash, Clone)]
37: #[serde(rename_all = "snake_case")]
38: pub struct CreateAlias {
39:     pub collection_name: String,
40:     pub alias_name: String,
41: }"""

chain = {
  "defect_id": "boundary_aliases_update_005",
  "endpoint": "aliases+update (POST /collections/aliases)",
  "defect_type": "Type1",
  "built_by": "evidence-builder",
  "steps": {
    "doc_verification": {
      "result": "DOC_VERIFIED",
      "link_reachability": "PASS",
      "version_match": "PASS",
      "content_consistency": "PASS",
      "endpoint_precision": "PASS",
      "sdk_rest_confusion": False,
      "detail": ("reachability: WebFetch to api.qdrant.tech blocked by environment (domain_blocked); page verified reachable 2026-09-03 via secondary fetcher returning the full 'Update collection aliases' page, plus endpoint_registry P1.0 record verified_at 2026-09-02T12:34:08Z (doc_quote present) and raw_knowledge document_sources fetched_at 2026-09-02T11:45:00Z. "
                 "version: v-1-18-x versioned shard, page header v1.18.x, target v1.18.0 -> 1.18 major.minor match. "
                 "content: the assertion's faces are documented (200 Successful envelope with result:boolean live-verified on the page; 404/500 faces per endpoint_registry doc_quote and raw_knowledge expected_responses; shipped docs/redoc/v1.18.x/openapi.json carries 200 + generic 4XX/default ErrorResponse). "
                 "CRITICAL for the claim: NO alias-name charset/pattern/length constraint exists anywhere - not on the page (request body documented only as 'Alias update operations / actions list of objects Required'), not in the shipped OpenAPI (CreateAlias.alias_name is type string with no pattern/minLength/maxLength), not in the SPEC. The script oracle flagged 'pending judge-doc verification of alias-name charset semantics' - that verification resolves to: the documentation is SILENT on alias-name charset. "
                 "endpoint: aliases+update found in endpoint_registry with matching source_url (PASS)."),
      "evidence_source": "doc"
    },
    "execution_evidence": {
      "grade": "B",
      "log_pattern": "probe[escaped-nul-in-name] -> status=200 / raw: {\"result\":true,\"status\":\"ok\",\"time\":0.014362911}",
      "secondary_observations": [
        "main log line 4 [rest, control]: positive raw-JSON control -> status=200 raw={\"result\":true,\"status\":\"ok\",\"time\":0.012455726}",
        "main log lines 17-19 [rest, same value class U+0000, UNescaped form]: probe[bare-nul-in-name] -> status=400 / raw: {\"status\":{\"error\":\"Format error in JSON body: control character (\\u0000-\\u001F) found while parsing a string at line 1 column 97\"},\"time\":0.0} - raw control byte rejected by JSON grammar (RFC 8259 forbids unescaped U+0000-U+001F in strings)",
        "main log lines 5-16 [rest]: truncated-json / trailing-comma / single-quotes / comment-in-json all -> status=400 with non-empty serde_json diagnostics (parser never crashes, no 5xx)",
        "evidence-builder re-run 2026-09-03 [P0, rest, reproducibility]: create_alias alias_name='bau5eb7f625ba\\u0000b' -> status=200 raw={\"result\":true,\"status\":\"ok\",\"time\":0.011035412}",
        "comparative 2026-09-03 [P1, rest, same-struct other String field]: create_alias collection_name='bau5eb7f625bx\\u0000y' -> status=404 raw={\"status\":{\"error\":\"Not found: Collection `bau5eb7f625bx\\u0000y` doesn't exist!\"},\"time\":0.000046582} - NUL in collection_name implicitly rejected via existence check, AND the 404 error text itself embeds the raw NUL char",
        "comparative 2026-09-03 [P2, rest, rename face, same value class]: rename_alias new_alias_name='bau5eb7f625br\\u0000n' -> status=200 raw={\"result\":true,\"status\":\"ok\",\"time\":0.015870269} - NUL accepted on the rename face as well",
        "comparative 2026-09-03 [P3, rest, delete face]: delete_alias alias_name='bau5eb7f625bd\\u0000e' (unknown) -> status=200 raw={\"result\":true,\"status\":\"ok\",\"time\":0.000072377} - co-observes sibling boundary_aliases_update_004's delete-unknown-returns-200 pattern",
        "comparative 2026-09-03 [P4, rest, state round-trip]: GET /aliases -> prefix_aliases=['bau5eb7f625br\\x00n', 'bau5eb7f625ba\\x00b'] with contains_escaped_nul_in_body=True - the U+0000-containing alias is genuinely persisted in state and round-trips through the API (cleanup required real delete_alias calls)",
        "grpc face 2026-09-03 [P5]: qdrant-client 1.18.0 prefer_grpc create_alias with real U+0000 char -> REJECTED client-side: ValueError: invalid AliasOperations model: {'create_alias': {...alias_name: 'bau5eg4aba5bg\\x00h'}} - SDK model validation pre-rejects before any request is sent; server-side gRPC disposition NOT measured -> face_unavailable",
        "probes 6-7 of the script (lone-surrogate-in-name, non-utf8-bytes) never executed - the script returns on the first DEFECT_FOUND verdict"
      ],
      "claim_alignment": "aligned",
      "http_semantics": {
        "client_error_returned_as": "N/A",
        "note": ("The primary observation is NOT an error-masked-as-2xx case: the body b'...\"alias_name\": \"bau5e22431d5a\\u0000b\"...' is well-formed JSON (RFC 8259 permits \\uXXXX escapes of any code point), targets an existing collection, and the documented face for a valid create batch is exactly 200 - the server returned a true success. "
                 "Genuinely malformed bodies (raw NUL control char, truncation, trailing comma, single quotes, comment) correctly returned HTTP 400 with non-empty serde_json diagnostics. "
                 "Secondary note: the delete face (P3; sibling 004's primary) does return a business-level no-op as HTTP 200 result:true for unknown aliases.")
      },
      "reproducibility": "single script",
      "script_error": False,
      "triggering_scripts": ["boundary_aliases_update_005"],
      "evidence_source": "behavior"
    },
    "contract_grounding": {
      "constraint_id": "qdrant_behavioral_aliases_update_001",
      "assertion_text_quoted": ("description: \"returns 200 ok; 404 on create_alias of a missing collection; 404/500 on delete_alias of an unknown alias\"; "
                                "expected_behavior: \"valid alias batch returns HTTP 200; create_alias on a missing collection returns 404; delete/rename of an unknown alias returns 404 or 500\""),
      "api_violates_assertion": False,
      "note": ("violates-declaration self-check: violates=false because the observed parameter (alias_name charset: JSON-escaped \\u0000 -> U+0000) lies OUTSIDE the assertion's constraint domain. "
               "The assertion constrains only the status-code semantics of the create/delete/rename branches; the escaped-NUL probe was an otherwise-valid create_alias on an EXISTING collection, whose documented and asserted face is exactly HTTP 200. "
               "No cited contract text, no doc prose, and no OpenAPI schema constrains alias_name charset - the claim's 'expected 4xx' premise has no grounding rule in the cited constraint. "
               "The observed phenomenon itself is genuine (NUL-containing alias created, persisted, round-trips)."),
      "evidence_source": "doc"
    },
    "chain_trace": {
      "chain_links": [
        "contract: qdrant_behavioral_aliases_update_001 exists (structured_contract.json assertions[50], endpoint aliases+update, evidence_tier explicit, source_url api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases) - asserts ONLY status-code semantics (200 ok / 404 create-on-missing / 404-500 delete-rename-unknown); contains NO alias_name charset clause",
        "doc: source_url reachable (web reader 2026-09-03 + endpoint_registry verified_at 2026-09-02T12:34:08Z); page documents 200 Successful envelope, actions list-of-objects Required, timeout>=1; shipped docs/redoc/v1.18.x/openapi.json declares CreateAlias.alias_name type string with no pattern/length; doc is SILENT on alias-name charset semantics",
        "script: boundary_aliases_update_005 sent raw bytes via data= containing b'\"alias_name\": \"bau5e22431d5a\\u0000b\"' - the backslash-u-0-0-0-0 is a 6-character legal JSON escape encoding U+0000 (NOT malformed JSON); script oracle honestly self-flagged 'pending judge-doc verification of alias-name charset semantics'",
        "log: probe[escaped-nul-in-name] -> status=200 {\"result\":true,\"status\":\"ok\",\"time\":0.014362911}; observation verified genuine by evidence-builder state round-trip 2026-09-03 (alias 'bau5eb7f625ba\\x00b' present in GET /aliases and required a real delete in cleanup); log faithfully records the HTTP exchange"
      ],
      "chain_broken_at": "contract",
      "break_detail": ("The four links are internally consistent (contract<->doc match; script<->log match), but the DEFECT_FOUND verdict has no grounding rule at the contract link: constraint qdrant_behavioral_aliases_update_001's domain is status-code semantics only, and the primary observation (200 on a JSON-legal \\u0000 escape in alias_name of an otherwise-valid create on an existing collection) violates no clause of it - in fact 200 is exactly the asserted face for that request shape. "
                       "The doc link compounds this: documentation (page + shipped OpenAPI + SPEC) contains no alias-name charset/pattern/length constraint that could ground an 'expected 4xx'. "
                       "The script's own oracle anticipated this ('pending judge-doc verification'). "
                       "The observation (unvalidated NUL acceptance, NUL persisted in state, NUL echoed inside a 404 error text) is real and recorded, but the cited constraint cannot adjudicate it as a violation."),
      "evidence_source": "doc+behavior"
    },
    "source_grounding": {
      "grep_queries": [
        "alias_name in lib/api/src (files_with_matches)",
        "alias in lib/api/src/rest/validate.rs (content, case-insensitive)",
        "AliasOperations in whole tree",
        "update_aliases in whole tree",
        "pub struct ChangeAliasesOperation|pub struct CreateAliasOperation|pub struct CreateAlias { in lib/**",
        "fn insert|fn rename_alias|fn remove in lib/storage/src/content_manager",
        "validate in lib/api/src/rest/*.rs (content)",
        "alias_name schemas in docs/redoc/v1.18.x/openapi.json (python json inspection)"
      ],
      "files_examined": [
        "src/actix/api/collections_api.rs (update_aliases handler, lines 181-196)",
        "lib/storage/src/content_manager/toc/collection_meta_ops.rs (update_aliases, lines 298-338)",
        "lib/storage/src/content_manager/alias_mapping.rs (insert/remove/rename_alias, lines 66-112)",
        "lib/storage/src/content_manager/collection_meta_ops.rs (CreateAlias/DeleteAlias/RenameAlias/ChangeAliasesOperation structs, lines 36-80 and 346-353)",
        "lib/api/src/rest/validate.rs (grep-verified: validates only vector/query structures, zero alias entries)",
        "docs/redoc/v1.18.x/openapi.json (alias paths + schemas)"
      ],
      "source_excerpt": excerpt,
      "call_chain_traced": ("REST chain: actix src/actix/api/collections_api.rs:181-196 update_aliases(operation: Json<ChangeAliasesOperation>) - handler applies NO field validation; the Json extractor deserializes via serde, and the JSON escape \\u0000 decodes to a real U+0000 code point, which is valid UTF-8 and thus admissible in a Rust String "
                            "-> dispatcher.submit_collection_meta_op(ChangeAliases) -> lib/storage/src/content_manager/toc/collection_meta_ops.rs:298-338: CreateAlias branch performs ONLY collection_lock.validate_collection_exists(&collection_name) (StorageError::NotFound -> 404, empirically confirmed by the P1 probe) and validate_collection_not_exists(&alias_name) (name-collision check), then alias_lock.insert "
                            "-> lib/storage/src/content_manager/alias_mapping.rs:66-70: plain HashMap insert + JSON persist to disk, no charset/pattern/length check. "
                            "RenameAlias face calls alias_lock.rename_alias (old-unknown -> StorageError::not_found, but new_alias_name unchecked - confirmed by P2 probe 200). "
                            "DeleteAlias face calls alias_lock.remove which returns Ok(None) for unknown aliases without error (-> 200, confirmed by P3 probe and consistent with sibling 004). "
                            "CreateAlias fields carry no #[validate] attributes (collection_meta_ops.rs:36-41); ChangeAliasesOperation derives Validate but declares no validation rules (collection_meta_ops.rs:349-353); lib/api/src/rest/validate.rs has zero alias-related entries. "
                            "By contrast the JSON-stream layer DOES enforce RFC 8259 grammar (raw control byte -> 400 'control character (\\u0000-\\u001F) found while parsing a string'), which is why bare-NUL was rejected and escaped-NUL was not."),
      "verification_outcome": "validation_absent",
      "verification_outcome_note": ("Scope-critical: charset/pattern/length validation on alias_name is ABSENT across the entire chain (handler -> storage -> persistence) - matching the claim's expected-but-missing charset check (label per v3.4 rule: unannotated silent behavior -> validation_absent, NOT by_design_in_source; no 'intentionally/by design/we don't guarantee' comment exists anywhere in the examined alias code). "
                                   "HOWEVER, the cited assertion qdrant_behavioral_aliases_update_001 requires only status-code semantics, and THOSE validations ARE present in source (validate_collection_exists -> 404; validate_collection_not_exists; rename-unknown -> StorageError::not_found) and behaved as documented in this chain's probes. "
                                   "The absent charset validation contradicts no cited contract text and no documented schema constraint (OpenAPI alias_name: plain string)."),
      "sufficiency_check": "grep_hit_pursued",
      "evidence_source": "source"
    },
    "mundane_explanation": {
      "excluded": [
        "env (container testvdb-qdrant-standalone healthy throughout; positive control 200; exit code 0)",
        "concurrency (single sequential request serialized under alias_persistence write lock)",
        "cache-delay (state verified persisted via GET /aliases round-trip 2026-09-03; cleanup required real delete_alias calls for the NUL names)",
        "request-parameter typo (raw bytes composed programmatically; identical result on evidence-builder re-run P0)"
      ],
      "surviving": None
    }
  }
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(chain, f, ensure_ascii=False, indent=1)
print("written:", OUT, "bytes:", os.path.getsize(OUT))
