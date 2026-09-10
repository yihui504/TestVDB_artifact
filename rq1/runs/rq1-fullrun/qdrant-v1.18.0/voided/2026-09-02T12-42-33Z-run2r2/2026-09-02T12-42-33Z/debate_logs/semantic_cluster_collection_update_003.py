#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_update_003
# strategy: diagnosis_quality
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - Type-2 diagnostics quality of the documented 400 faces)
"""
Attack: diagnosis_quality x qdrant_behavioral_cluster_collection_update_001 (chunk_cluster+collection+update; strategy 2 - Type-2 rubric on both documented 400 faces: invalid peer and invalid shard)
Oracle: on an existing collection, move_shard with to_peer_id=424242 and replicate_shard with shard_id=987654 (peer live-derived) each return exactly HTTP 400 and their rejection text scores >= 1/3 on the rubric (named 1pt + format hint 1pt + actionable 1pt) - a 400 face scoring 0/3 (names neither the offending parameter nor any format hint nor any action, e.g. bare 'internal error') is Type2_PoorDiagnostics; a 2xx on either face is Type1_IllegalSuccess (disposition, cross-ref script 001); a 5xx with /healthz alive is Type3

Assertion qdrant_behavioral_cluster_collection_update_001 (evidence_tier=explicit):
  "valid cluster operation returns HTTP 200 (accepted); invalid peer/shard
  returns 400; missing collection returns 404". This script grades the QUALITY
  of the two 400 rejection paths (spec strategy 2; BS-02: distributed-hands
  error paths historically degrade to generic messages).

Type-2 rubric (spec strategy 2), adapted to the invalid peer/shard faces and
declared here per G7 (envelope field names like status/error are implementation
detail per the threat model, so the whole body text is scanned):
  criterion 1 (named):  the offending parameter name or its value appears -
                        "peer", "to_peer_id", "shard", "shard_id", or the probe
                        value itself ("424242" / "987654");
  criterion 2 (hint):   a format/range statement - "must be", "expected",
                        "should be", "valid", "range", "type", "positive",
                        "non-zero", "unknown", "not found", "no such",
                        "doesn't exist", "invalid";
  criterion 3 (action): an actionable suggestion - "correct", "try", "use",
                        "change", "specify", "provide", "check", "verify",
                        "list".
A 0/3 rejection leaves the operator unable to tell WHICH of peer_id/shard_id
was wrong or what to do next - exactly the Type2 class (cluster misconfig is
the hardest ops surface to debug blind).

G4 positive control first: an existing collection must answer cluster info 200,
otherwise error-path probing is groundless. G9: both documented 400 faces
(invalid peer face and invalid shard face) are graded; both must clear the
threshold.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster POST/GET = raw_knowledge url
/collections/{collection_name}/cluster; cluster_status / healthz); literal
paths forbidden; 2-tuple (status, raw). Transport-failure branches re-check
liveness via an inline safe_request("GET","healthz") probe with a printed
status.
"""
import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

SETUP_OK = False


# ---------------- helpers ----------------
def safe_request(method, path_key, body=None, path_params=None, query_params=None):
    """All HTTP exits through this visible wrapper (R4 lesson); thin delegation, 2-tuple."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params)


def parse_result(raw):
    """Extract the result object from a qdrant envelope (lesson: result.<field>)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if isinstance(b, dict):
        return b.get("result")
    return None


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def score_diagnostics(raw, probe_value):
    """Type-2 rubric (spec strategy 2). Returns (score, max, hits-list).
    body may be JSON or non-JSON text - scan the whole payload lowercased."""
    text = (raw or "").lower()
    score = 0
    hits = []

    # Criterion 1: parameter named (or the offending value echoed)
    named_tokens = ["peer", "to_peer_id", "from_peer_id", "peer_id", "shard", "shard_id", str(probe_value).lower()]
    if any(tok in text for tok in named_tokens):
        score += 1
        hits.append("named")

    # Criterion 2: format/range/existence hint
    format_hints = ["must be", "expected", "should be", "valid", "range", "type",
                    "positive", "non-zero", "unknown", "not found", "no such",
                    "doesn't exist", "does not exist", "invalid", "not exist", "missing"]
    if any(h in text for h in format_hints):
        score += 1
        hits.append("format_hint")

    # Criterion 3: actionable suggestion
    action_hints = ["correct", "try", "use ", "change", "specify", "provide",
                    "check", "verify", "list"]
    if any(h in text for h in action_hints):
        score += 1
        hits.append("actionable")

    return score, 3, hits


def probe_400_face(op_body, probe_value, face_name):
    """Run one documented-400 face: exact-400 disposition + Type-2 rubric.
    Non-400 dispositions are typed defects (same classes as script 001)."""
    st, raw = safe_request("POST", "collection_cluster", op_body,
                           path_params={"name": COL})
    print(f"{face_name}: status={st} raw={raw[:400]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure probing {face_name} (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"{face_name}: 5xx status {st} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"{face_name}: documented 400 face answered server error {st} while /healthz is 200; raw={raw[:200]}")
    if 200 <= st < 300:
        defect("Type1_IllegalSuccess",
               f"{face_name}: assertion promises HTTP 400; got {st} with a success payload; raw={raw[:200]}")
    if st != 400:
        defect("Type4_StateLogicViolation",
               f"{face_name}: assertion pins 400; got unexpected status {st} (wrong rejection class); raw={raw[:200]}")
    score, max_score, hits = score_diagnostics(raw, probe_value)
    print(f"{face_name} diagnostics: score={score}/{max_score} hits={hits}")
    if score == 0:
        defect("Type2_PoorDiagnostics",
               f"{face_name}: rejection scores 0/3 on the Type-2 rubric - the message names neither the "
               f"offending parameter/value nor any format hint nor any action; operator cannot tell which "
               f"of peer_id/shard_id was wrong; body: {raw[:300]}")
    return score


TS = str(int(time.time()))
PREFIX = f"s5cu3_{TS}_"
COL = PREFIX + "col"
BAD_PEER = 424242
BAD_SHARD = 987654


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- setup + positive control (G4): existing collection answers cluster info 200 ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True

    st, raw = safe_request("GET", "collection_cluster", path_params={"name": COL})
    print(f"positive control - cluster info of '{COL}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on positive control (status=0, /healthz={hs}); no defect conclusion")
    if st != 200:
        script_error(f"positive control failed - existing collection cluster info status={st}: {raw[:300]}")

    st, raw = safe_request("GET", "cluster_status")
    res = parse_result(raw)
    peer_id = res.get("peer_id") if isinstance(res, dict) else None
    if st != 200 or peer_id is None:
        script_error(f"cannot derive live peer_id from cluster status (status={st}); raw={raw[:200]}")
    print(f"derived live peer_id={peer_id}")

    # ---- face 1: invalid peer (move_shard to_peer_id=424242, from live peer) ----
    s1 = probe_400_face({
        "operation": "move_shard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": BAD_PEER,
    }, BAD_PEER, "invalid-peer face (move_shard to_peer_id=424242)")

    # ---- face 2: invalid shard (replicate_shard shard_id=987654, to live peer) ----
    s2 = probe_400_face({
        "operation": "replicate_shard",
        "shard_id": BAD_SHARD,
        "to_peer_id": peer_id,
    }, BAD_SHARD, "invalid-shard face (replicate_shard shard_id=987654)")

    print(f"both 400 faces cleared the Type-2 threshold: peer-face={s1}/3, shard-face={s2}/3")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
