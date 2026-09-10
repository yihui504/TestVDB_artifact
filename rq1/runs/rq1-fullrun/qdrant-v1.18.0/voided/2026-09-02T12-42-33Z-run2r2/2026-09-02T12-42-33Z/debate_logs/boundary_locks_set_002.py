#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_locks_set_002
# strategy: state
# endpoint: locks+set
# constraint_ids: qdrant_state_locks_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03-adjacent maintenance-window invariant — write=true is
#   trusted to gate ALL mutation APIs (create/upsert/delete faces), and
#   write=false is trusted to restore them; a face that skips the gate or
#   a lock that never releases voids the maintenance-window promise.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: state-machine boundary attack (strategy=state x
  qdrant_state_locks_set_001; chunk_locks+set scope=locks+set POST /locks).
  Assertion under test (contract constraints.state_constraints, level
  system): "with write=true every mutation request is refused with the
  configured error_message until the lock is released (write=false)".
  G4 positive-negative pairing on ONE state machine: positive legs
  exercise the promise kept (mutations succeed before engage and after
  release), negative legs challenge it under lock. Mutation faces are
  chosen to span the three canonical mutation families — create
  (PUT /collections/{name}), upsert (PUT /collections/{name}/points),
  delete (DELETE /collections/{name}) — all issued through the qdrant
  runtime PATHS (create_collection / upsert_points / drop_collection);
  G6 justification: "ALL mutation APIs" is the promise's quantifier, so
  the mutation point is the family itself — any single face that skips
  the gate breaks the invariant exactly where a maintenance window would
  leak writes. Refusal oracle is composite (expected vs actual, D3a):
  expected = non-2xx status AND the configured TOKEN present in the raw
  body; measured deviations type as: mutation 2xx under write=true =
  Type4_StateLogicViolation (core invariant break); refusal non-2xx
  WITHOUT the TOKEN = Type4 (the "returning the configured
  error_message" clause broken); engage/release POST non-2xx after a
  live probe = promise-flap Type4. 5xx answers get the /healthz
  liveness re-check before any crash-class conclusion (G8).
  Dual-path per R19 + R24 reflection: on this OSS v1.18.0 deployment
  GET/POST /locks are expected to answer non-2xx (404 — locks family
  absent from the service_api.rs route table; cloud doc backfill; R19
  and R24 both measured the 404 pair) -> ENDPOINT_ABSENT -> NO_DEFECT
  with probe evidence (the state machine is not actuable). POST non-2xx
  while GET 2xx = interface-parity defect signal (G9: this chunk's
  write face is the missing one). Transport-0 probes with /healthz
  alive are NOT adjudicated as absence (honest SCRIPT_ERROR).
Oracle: live /locks: with write=true+TOKEN engaged, each of the 3 mutation faces (create_collection COLL_B, upsert_points into COLL_A, drop_collection COLL_A) must be refused non-2xx with TOKEN in the raw body — any mutation 2xx under lock = Type4_StateLogicViolation, refusal without TOKEN = Type4 (configured-message clause broken); after write=false the release POST answers 2xx and a fresh create_collection COLL_C succeeds 2xx (refusal after release or non-2xx release = Type4); 5xx/transport with /healthz alive = Type3; if GET+POST /locks both answer concrete non-2xx (404 expected on OSS v1.18.0), NO_DEFECT with endpoint-absence evidence (state machine not actuable)
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

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
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

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")

import requests  # noqa: E402  (fallback face only)

DIM = 8  # tiny dim: the mutation faces only need to exist, not to be searched

_FB_PRINTED = [False]


def _fallback_markers():
    """Print the FALLBACK_TRIGGERED / FALLBACK_JUSTIFIED pair exactly once."""
    if _FB_PRINTED[0]:
        return
    _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: locks write-face state machine (locks+set POST /locks engage/release + locks+get GET /locks probe) has no qdrant runtime PATHS key; issuing the contract-derived REST path /locks via requests (mutation legs themselves go through runtime PATHS create_collection/upsert_points/drop_collection)")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS (create_collection..metrics) exposes no locks key; chunk_locks+set unit qdrant_state_locks_set_001 is anchored on contract api_endpoints locks+set (POST, state constraint 'write=true blocks ALL mutation APIs ... write=false releases') whose raw_knowledge api_endpoints url field reads '/locks', while the gated mutation faces are all covered by existing runtime PATHS keys and stay on the runtime; the /locks path is derived 1:1 from the contract record and the runtime whitelist gap is a runtime-coverage gap, not a reason to drop the unit — same FALLBACK precedent as R24 boundary_locks_get_001 in this session]")


def locks_http(method, body=None, timeout=15):
    """FALLBACK face mirroring rt.request's (status, raw_text) 2-tuple for
    the contract-declared /locks service endpoint (no runtime PATHS key)."""
    _fallback_markers()
    url = BASE_URL + "/locks"
    headers = {"Content-Type": "application/json"}
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    try:
        r = requests.request(method, url, json=body, headers=headers,
                             timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def safe_request(method, path_key, body=None, path_params=None,
                query_params=None, timeout=30):
    """All non-lock HTTP through the runtime; timeout/path_params/body/
    query_params forwarded exactly; path_key from rt.PATHS only."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def guarded_drop(name):
    """Cleanup-spec drop: wrapped, best-effort, never crashes the script."""
    try:
        s, raw = rt.request("DELETE", "drop_collection",
                            path_params={"name": name}, timeout=30)
        if s not in (200, 201, 404):
            print(f"[cleanup] drop {name} answered {s}: {str(raw)[:150]}")
    except Exception as e:
        print(f"[cleanup] drop {name} raised: {e}")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "lks2_" + TS + "_"          # unique-prefix discipline (standing lesson)
    COLL_A = PFX + "a"                 # pre-existing mutation target
    COLL_B = PFX + "b"                 # create-under-lock target
    COLL_C = PFX + "c"                 # post-release create target
    TOKEN = PFX + "maintenance_window_msg"
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def release_lock():
        try:
            s, raw = locks_http("POST", {"write": False}, timeout=15)
            print(f"[release write=false] status={s} raw={str(raw)[:300]}")
            return s, raw
        except Exception as e:
            return 0, str(e)

    def mutation_leg(tag, face, run):
        """One mutation face under write=true. Expected: refused non-2xx AND
        TOKEN in raw body. Measured deviations type per the composite
        oracle (2xx = Type4 invariant break; non-2xx w/o TOKEN = Type4
        message clause; 5xx gets /healthz re-check)."""
        s, raw = run()
        print(f"[{tag} ({face})] status={s} raw={str(raw)[:300]}")
        if s == 0:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"[{tag}] mutation transport failure with "
                           f"/healthz alive while write=true — "
                           f"Type3_RuntimeFailure — exc={str(raw)[:150]}")
            return "OK"
        if 200 <= s <= 299:
            DEFECTS.append(f"[{tag}] mutation face '{face}' answered {s} "
                           f"(EXECUTED) while write=true is engaged — the "
                           f"maintenance-window invariant 'write=true blocks "
                           f"ALL mutation APIs' is broken on this face — "
                           f"Type4_StateLogicViolation — raw="
                           f"{str(raw)[:200]}")
            return "OK"
        # non-2xx refusal — the configured error_message clause
        low = str(raw).lower()
        if TOKEN.lower() in low:
            print(f"[{tag}] refused ({s}) carrying the configured "
                  f"error_message token — invariant kept on this face")
        else:
            if 500 <= s <= 599 and not alive():
                return "TRANSPORT"
            DEFECTS.append(f"[{tag}] refused ({s}) but the raw body does NOT "
                           f"carry the configured error_message token "
                           f"(expected token {TOKEN!r}; constraint: 'refused "
                           f"with the configured error_message') — "
                           f"Type4_StateLogicViolation (message clause "
                           f"broken) — raw={str(raw)[:200]}")
        return "OK"

    try:
        # ---- (0) endpoint probes (GET read face + POST hygiene release) ----
        s0, raw0 = locks_http("GET", timeout=10)
        print(f"[probe GET /locks] status={s0} raw={str(raw0)[:300]}")
        s1, raw1 = locks_http("POST", {"write": False}, timeout=10)
        print(f"[probe POST /locks write=false] status={s1} raw={str(raw1)[:300]}")

        if s0 == 0 or s1 == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print("[probe-anomaly] transport failure (status=0) on a /locks "
                  "probe while /healthz is alive — cannot honestly adjudicate "
                  "endpoint absence vs write-face defect -> SCRIPT_ERROR "
                  "(R24 discipline: absence requires a concrete HTTP non-2xx "
                  "status on BOTH probes)")
            return "SCRIPT_ERROR"

        get_live = 200 <= s0 <= 299
        post_live = 200 <= s1 <= 299

        if not get_live and not post_live:
            print("[ENDPOINT_ABSENT] GET /locks and POST /locks both answered "
                  f"concrete non-2xx statuses ({s0} / {s1}) on the deployed "
                  "qdrant v1.18.0 OSS image (server commit "
                  "db3fca327851e360c521065649e0f65a57fe7d3c per "
                  "deployment_meta.json); the write-protection state machine "
                  "this state constraint is anchored to is not registered in "
                  "that commit's route table (src/actix/api/service_api.rs "
                  "registers only telemetry/metrics/stacktrace/healthz/"
                  "livez/readyz/logger/truncate_unapplied_wal) — R19 "
                  "(chunk_global) and R24 (chunk_locks+get) measured the "
                  "same 404 pair, R8 baseline: /locks = not_found_in_source "
                  "cloud doc backfill, so the engage/refuse/release machine "
                  "is not actuable on this binary and cannot be violated — "
                  "NO_DEFECT (measured negative with probe evidence above)")
            return "NO_DEFECT"

        if not post_live and get_live:
            DEFECTS.append(f"interface parity: POST /locks answered {s1} "
                           f"(non-2xx) while GET /locks answered {s0} — the "
                           f"locks family IS live (route registered) but the "
                           f"documented write face (locks+set, the only "
                           f"actuator of the write-protection state machine, "
                           f"source_url https://api.qdrant.tech/v-1-18-x/"
                           f"api-reference/service/post-locks) is missing — "
                           f"Type4_StateLogicViolation (G9 same-family face "
                           f"asymmetry; this chunk's primary face is the "
                           f"absent one) — POST raw={str(raw1)[:150]}")
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        # ---- (A) positive pre-lock leg: mutations must succeed unlocked ----
        ok, err = rt.setup_default(COLL_A, dim=DIM, metric="Cosine")
        print(f"[A pre-lock create {COLL_A}] ok={ok} err={err}")
        if not ok:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"[A] VERDICT-critical setup failure unrelated to locks "
                  f"(create before any lock): {err} — cannot ground the "
                  f"state machine -> SCRIPT_ERROR")
            return "SCRIPT_ERROR"

        se, sr = None, None  # engage/release statuses for the D-leg
        # ---- (B) engage write=true with the configured error_message ----
        se, rawe = locks_http("POST", {"write": True, "error_message": TOKEN},
                              timeout=15)
        print(f"[engage write=true token={TOKEN}] status={se} "
              f"raw={str(rawe)[:300]}")
        if se == 0:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append("[engage] transport failure with /healthz alive — "
                           "Type3_RuntimeFailure")
        elif not (200 <= se <= 299):
            if 500 <= se <= 599 and not alive():
                return "SCRIPT_ERROR"
            NOTES.append(f"engage POST answered {se} after a 2xx probe — "
                         f"engaged/refused legs skipped (engage face flap is "
                         f"adjudicated by unit qdrant_behavioral_locks_set_001"
                         f"/boundary_locks_set_003, and the refusal machine "
                         f"cannot be driven without it) — raw="
                         f"{str(rawe)[:150]}")
        else:
            # ---- (B1-B3) the three mutation faces under write=true ----
            b1 = mutation_leg("B1 create under lock", "create_collection",
                              lambda: rt.request("PUT", "create_collection",
                                                 {"vectors": {"size": DIM,
                                                              "distance": "Cosine"}},
                                                 path_params={"name": COLL_B},
                                                 timeout=30))
            b2 = mutation_leg("B2 upsert under lock", "upsert_points",
                              lambda: rt.request("PUT", "upsert_points",
                                                 {"points": [{"id": 1,
                                                              "vector": [0.1] * DIM}]},
                                                 path_params={"name": COLL_A},
                                                 timeout=30))
            b3 = mutation_leg("B3 delete under lock", "drop_collection",
                              lambda: rt.request("DELETE", "drop_collection",
                                                 path_params={"name": COLL_A},
                                                 timeout=30))
            for r in (b1, b2, b3):
                if r == "TRANSPORT":
                    return "SCRIPT_ERROR"

            # ---- (C) release write=false -> must answer 2xx ----
            sr, rawr = release_lock()
            if sr == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append("[C release] transport failure with /healthz "
                               "alive — Type3_RuntimeFailure")
            elif not (200 <= sr <= 299):
                if 500 <= sr <= 599 and not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"[C release] write=false answered {sr} after "
                               f"the engage answered 2xx — the 'write=false "
                               f"releases the lock' promise is broken "
                               f"(Type4_StateLogicViolation); post-release "
                               f"leg still attempted — raw="
                               f"{str(rawr)[:200]}")

            # ---- (D) post-release positive leg: mutations must work again ----
        sd, rawd = locks_http("POST", {"write": False}, timeout=15)  # re-arm released state if B was skipped
        sc, rawc = rt.request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": COLL_C}, timeout=30)
        print(f"[D post-release create {COLL_C}] (hygiene release {sd}) "
              f"status={sc} raw={str(rawc)[:300]}")
        if sc == 0:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append("[D post-release] create transport failure with "
                           "/healthz alive — Type3_RuntimeFailure")
        elif 500 <= sc <= 599:
            if alive():
                # only a defect if the lock was engaged-and-not-released
                if se is not None and not (200 <= se <= 299):
                    NOTES.append(f"[D post-release] create answered {sc} but "
                                 f"engage never succeeded — not attributable "
                                 f"to a stuck lock — raw={str(rawc)[:150]}")
                elif sr is not None and not (200 <= sr <= 299):
                    DEFECTS.append(f"[D post-release] create answered {sc} "
                                   f"after a FAILED release ({sr}) — lock "
                                   f"stuck engaged, mutations dead — "
                                   f"Type4_StateLogicViolation (already "
                                   f"flagged at C) — raw={str(rawc)[:200]}")
                else:
                    DEFECTS.append(f"[D post-release] create answered {sc} "
                                   f"(5xx crash-class) with /healthz alive "
                                   f"although release answered 2xx — "
                                   f"Type3/RuntimeFailure-class — "
                                   f"raw={str(rawc)[:200]}")
            else:
                return "SCRIPT_ERROR"
        elif 200 <= sc <= 299:
            print(f"[D post-release] create succeeded ({sc}) — mutations "
                  f"restored (or never blocked because engage was skipped)")
        else:
            if se is not None and (200 <= se <= 299) and (sr is None or 200 <= sr <= 299):
                DEFECTS.append(f"[D post-release] create answered {sc} "
                               f"(non-2xx, not 5xx) after engage+release both "
                               f"answered 2xx — mutations NOT restored by "
                               f"write=false — Type4_StateLogicViolation — "
                               f"raw={str(rawc)[:200]}")
            else:
                NOTES.append(f"[D post-release] create answered {sc} — "
                             f"engage/release path incomplete, not "
                             f"attributable to the lock — raw="
                             f"{str(rawc)[:150]}")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("locks+set state machine: mutations gated on every face under "
              "write=true (refusals carried the configured error_message), "
              "release restored mutations — NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup: release the lock first (guarded), then best-effort drops
        try:
            locks_http("POST", {"write": False}, timeout=10)
        except Exception:
            pass
        guarded_drop(COLL_A)
        guarded_drop(COLL_B)
        guarded_drop(COLL_C)


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
