#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_list_004
# strategy: diagnosis_quality
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the method-mismatch branch of
#   the listing face must still diagnose: which verb is wrong, what the face
#   accepts; a bare status code with no diagnostic text is exactly the
#   generic-'internal error'-is-fine blindspot) + BS-01 adjacent face
#   (robustness of the read face under type-confused query params)
"""
Attack: diagnosis_quality (S2, Type-2 focused) + method-face graceful
  degradation x qdrant_behavioral_collections_list_001 (chunk_collections+list
  unit assertions::qdrant_behavioral_collections_list_001; strategy coverage
  slot "diagnosis_quality + method-face graceful degradation x list_001" -
  see _001's Attack block for the full chunk coverage list).
Oracle: leg 1 (method confusion) - POST /collections is rejected in the 4xx
  family when sent with a create-style body to the GET-declared listing face
  (405 ideal;
  400/404/406/422 all legitimate rejection dispositions for an unmatched
  verb-route) carrying a NON-EMPTY diagnostic text; 2xx = Type1_IllegalSuccess
  (method confusion - the face answered/acted on a verb it does not declare),
  4xx with empty/no error text = Type2_PoorDiagnostics, 5xx with /healthz
  alive = Type3; leg 2 (graceful degradation) - GET /collections carrying
  junk/type-confused query params (wait=notabool, limit=999999999, offset=-1,
  foo=[bar) on a face that declares no query params stays EITHER 200 with
  the intact promised array and unchanged prefix scope OR a clean 4xx with
  non-empty text - 5xx/hang = Type3/transport, 200 with corrupted array or
  mutated prefix scope = Type4_StateLogicViolation, and a follow-up clean GET
  must return the same prefix scope (read must not mutate state); transport
  failure with healthy /healthz = SCRIPT_ERROR (G8).

Why the generic judge helper is not used verbatim on leg 1 (D3a-2
  hand-written path, expectation declared first): rt.expect_rejected /
  judge_4xx map 404 to SCRIPT_ERROR (business-route-miss assumption); for a
  verb probe on a face whose only declared method is GET (raw_knowledge
  api_endpoints[collections+list].method = GET), 404/405/400/406/422 are all
  legitimate rejections of the unsupported verb, so the disposition matrix is
  adjudicated explicitly with the expected-vs-actual comparison below.

Type-2 rubric (spec S2): parameter_named (1pt) + format_hint (1pt) +
  actionable (1pt) on the rejection diagnostic; the DEFECT bar is score 0
  (no diagnostic at all) - present-but-thin messages are passed with their
  score printed for the reporter (thin-vs-absent keeps the oracle falsifiable
  without hanging a defect on subjective phrasing).
"""

import os
import sys
import json
import time
import uuid
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

LIST_KEY = "list_collections"
print(f"[path derivation] {LIST_KEY} = {rt.PATHS[LIST_KEY]} (runtime PATHS; "
      f"matches raw_knowledge api_endpoints[collections+list].url /collections, "
      f"method GET, parameters = api-key header only)")

PFX = "scl04" + uuid.uuid4().hex[:6]
JUNK_PARAMS = {"wait": "notabool", "limit": "999999999",
               "offset": "-1", "foo": "[bar"}


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/
    path_params/query_params/timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): True if adjudicable, False after recording."""
    if st <= 0:
        v = healthz_ladder(label)
        if v:
            findings.append((1, v))
        else:
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' failed with healthy /healthz: {str(raw)[:150]}"))
        return False
    if 500 <= st <= 599:
        v = healthz_ladder(label)
        findings.append((1, v if v else
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; body: {str(raw)[:200]}"))
        return False
    return True


def extract_error(raw):
    """Pull diagnostic text out of an error envelope. The runtime-verified
    qdrant error body is {'status': {'error': ...}}; fallback keys cover the
    generic family. Envelope field NAMES themselves are not part of the
    contract (by-design note) - only the presence of non-empty text is."""
    try:
        env = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return raw.strip() if isinstance(raw, str) and raw.strip() else None
    if not isinstance(env, dict):
        return None
    st = env.get("status")
    if isinstance(st, dict) and isinstance(st.get("error"), str) and st.get("error"):
        return st["error"]
    for k in ("err", "error", "message", "detail"):
        v = env.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def type2_score(text):
    """Spec S2 rubric on the diagnostic text: problem-named (1) +
    format/expectation hint (1) + actionable steer (1)."""
    t = (text or "").lower()
    score = 0
    if any(k in t for k in ("method", "post", "get", "verb", "route", "path")):
        score += 1
    if any(k in t for k in ("must", "expected", "should", "valid", "only",
                            "supported", "allowed", "instead")):
        score += 1
    if any(k in t for k in ("use", "try", "refer", "documentation", "allowed",
                            "instead", "correct")):
        score += 1
    return min(score, 3), 3


def parse_scoped(raw):
    """Prefix-scoped name rows from a listing payload; None when the
    promised array is missing/unparseable (name-key extraction, R8 lesson)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        b = None
    entries = None
    if isinstance(b, dict):
        res = b.get("result")
        if isinstance(res, dict) and isinstance(res.get("collections"), list):
            entries = res["collections"]
        elif isinstance(res, list):
            entries = res
    if entries is None:
        return None
    return sorted(it["name"] for it in entries
                  if isinstance(it, dict) and isinstance(it.get("name"), str)
                  and it["name"].startswith(PFX))


def cleanup():
    """Teardown: nothing is created by this script; if the POST probe
    nonetheless materialized something under this script's prefix, drop it.
    Only self-prefixed names are ever touched; failure non-fatal."""
    try:
        st, raw = safe_request("GET", LIST_KEY, timeout=30)
        for name in parse_scoped(raw) or []:
            if isinstance(name, str) and name.startswith(PFX):
                try:
                    rt.drop_collection(name)
                except Exception:
                    pass
    except Exception as e:
        print(f"cleanup warning (prefix sweep): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: the listing face rejected the undeclared POST verb in 4xx with a "
          "non-empty diagnostic, and tolerated the junk query params without "
          "5xx, payload corruption, or state mutation")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- baseline snapshot: prefix scope (script creates nothing) ----
        st, raw = safe_request("GET", LIST_KEY, timeout=30)
        print(f"[baseline GET /collections] status={st} raw={str(raw)[:300]}")
        if not transport_gate("baseline list", st, raw, findings):
            finish(findings)
            return
        baseline = parse_scoped(raw)
        if baseline is None:
            findings.append((3, "SCRIPT-ERROR-baseline: the promised array is "
                                "missing/unparseable before any probe: "
                                f"{str(raw)[:200]!r}"))
            finish(findings)
            return
        print(f"[baseline] prefix-scope={baseline}")

        # ---- leg 1: method confusion - POST on the GET-declared face ----
        st, raw = safe_request("POST", LIST_KEY,
                               body={"vectors": {"size": 4, "distance": "Cosine"}},
                               timeout=30)
        print(f"[leg1 POST /collections] status={st} raw={str(raw)[:400]}")
        if not transport_gate("leg1 POST probe", st, raw, findings):
            finish(findings)
            return
        if 200 <= st <= 299:
            findings.append((2, f"Type1_IllegalSuccess: POST /collections with a "
                                f"create-style body was answered with HTTP {st} - "
                                f"the listing face declares GET only (raw_knowledge "
                                f"method=GET); verb confusion: {str(raw)[:250]!r}"))
            finish(findings)
            return
        if not (400 <= st <= 499):
            findings.append((2, f"Type4_StateLogicViolation: POST probe answered "
                                f"with HTTP {st} (expected a 4xx rejection): "
                                f"{str(raw)[:250]!r}"))
            finish(findings)
            return
        msg = extract_error(raw)
        print(f"[leg1] rejected with {st}; diagnostic={msg!r}")
        if not msg:
            findings.append((2, f"Type2_PoorDiagnostics: POST on the GET-only "
                                f"listing face was rejected with HTTP {st} but the "
                                f"body carries NO diagnostic text (empty/missing "
                                f"error message) - the user cannot tell which "
                                f"method/parameter is wrong: {str(raw)[:250]!r}"))
        else:
            score, mx = type2_score(msg)
            print(f"[Type2 score] {score}/{mx} - diagnostic names the problem, "
                  f"gives a format hint, and/or an actionable steer "
                  f"(score 0 would be a Type2 defect; 1-3 passes with quality note)")

        # ---- leg 2: graceful degradation under junk/type-confused query params ----
        st, raw = safe_request("GET", LIST_KEY, query_params=JUNK_PARAMS,
                               timeout=30)
        print(f"[leg2 GET /collections junk-params] status={st} raw={str(raw)[:400]}")
        if not transport_gate("leg2 junk-params probe", st, raw, findings):
            finish(findings)
            return
        if 400 <= st <= 499:
            msg = extract_error(raw)
            print(f"[leg2] clean 4xx disposition ({st}); diagnostic={msg!r}")
            if not msg:
                findings.append((2, f"Type2_PoorDiagnostics: junk query params on "
                                    f"the listing face were rejected with HTTP {st} "
                                    f"but the body carries NO diagnostic text: "
                                    f"{str(raw)[:250]!r}"))
        elif st == 200:
            scoped = parse_scoped(raw)
            if scoped is None:
                findings.append((2, "Type4_StateLogicViolation: junk query params "
                                    "degraded the 200 payload - the promised "
                                    "array is missing/unparseable: "
                                    f"{str(raw)[:250]!r}"))
                finish(findings)
                return
            print(f"[leg2] 200 disposition with intact array; prefix-scope={scoped}")
            if scoped != baseline:
                findings.append((2, f"Type4_StateLogicViolation: junk query params "
                                    f"on a read-only face changed the prefix scope: "
                                    f"{baseline} -> {scoped}"))
                finish(findings)
                return
        else:
            findings.append((2, f"Type4_StateLogicViolation: junk query params "
                                f"answered with unexpected HTTP {st} (acceptable: "
                                f"200 intact or clean 4xx): {str(raw)[:250]!r}"))
            finish(findings)
            return

        # ---- post-probe purity: a clean GET must see the baseline scope ----
        st, raw = safe_request("GET", LIST_KEY, timeout=30)
        print(f"[post-probe GET /collections] status={st} raw={str(raw)[:300]}")
        if not transport_gate("post-probe list", st, raw, findings):
            finish(findings)
            return
        scoped = parse_scoped(raw)
        if scoped is None:
            findings.append((2, "Type4_StateLogicViolation: after the probes the "
                                "promised array is missing/unparseable: "
                                f"{str(raw)[:250]!r}"))
        elif scoped != baseline:
            findings.append((2, f"Type4_StateLogicViolation: the read-face probes "
                                f"mutated the prefix scope: {baseline} -> {scoped}"))
        finish(findings)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
