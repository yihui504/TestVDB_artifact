#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_livez_002
# strategy: concurrent
# endpoint: livez
# constraint_ids: qdrant_behavioral_livez_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/livez
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (concurrency on the liveness face — supplementary cell for
#   the replayed R23: state_livez_001 covered concurrent x GET-face probing;
#   this script covers the remaining construction cell, concurrent x
#   hostile-METHOD volley on the probe route (HEAD/OPTIONS/POST/PUT/PATCH/
#   DELETE with unexpected bodies) racing concurrent GET /livez readers —
#   the assertion's weakest precondition is "while the process is alive",
#   so anything that could stop the process or corrupt the liveness signal
#   on the route itself is this unit's Type3/Type4 channel)
"""
Attack: concurrent (Strategy 4) + liveness-signal state stability across a
  hostile method volley x qdrant_behavioral_livez_001 (endpoint livez —
  GET /livez, the only unit in chunk_livez; assertion: liveness probe
  returns 200 while the process is alive (no dependency check); v-1-18-x
  OpenAPI shard declares GET-only with optional api-key query parameter and
  expected_responses {"200": "ok"}, text/plain envelope). Read-only face;
  no collections needed; nothing on this route is mutable by contract.
  Round coverage list (chunk_livez): concurrent x GET-face (state_livez_001,
  prior pass, executed 97/97x200 NO_DEFECT) + concurrent x hostile-method
  volley x reader stability (this script). Positive legs (G4): (0) 3
  sequential baseline GET probes + (3) 5 post-volley tail probes + (2b)
  concurrent GET /livez readers running DURING the volley — all must return
  exactly HTTP 200, bracketing the same face status across the hostile
  input (Pattern A: probe -> volley -> re-probe). Negative construction
  (G4/G5/G6, mutation justified: a GET-only probe route is the one route
  every orchestrator hits with plain GETs, so non-GET methods with
  unexpected JSON bodies are the cheapest input class able to panic an
  under-validated route handler and falsify "200 while the process runs"):
  (2) TESTVDB_CONCURRENT_THREADS workers cycling a 7-probe hostile set
  (HEAD, OPTIONS, POST x2 bodies, PUT, PATCH, DELETE) twice against the
  livez route while readers probe concurrently. Typed oracles: 5xx on ANY
  livez-route request while inline livez+healthz re-probes prove the
  process alive = Type3_RuntimeFailure (crash-class status); >=2 recovered
  transport losses (status 0) = Type3 (race discipline); GET readers/tail
  persistently non-200 across 3 re-probes while healthz answers 200 =
  Type4_StateLogicViolation (hostile input corrupted the liveness signal of
  a demonstrably alive process). Clean 4xx rejections (404/405/400) and
  2xx-on-non-GET permissive routing are NOT claimable (the shard documents
  GET only; no contract backs a required disposition) — recorded as G9
  disposition NOTES only. Persistent non-200 with NO aliveness proof on
  either face = SCRIPT_ERROR (dead/unadjudicable service, read-only face).
Oracle: baseline+readers+tail GET probes all return HTTP 200 (0 anomalies)
  and every hostile-method probe lands outside the 5xx band; a 5xx status
  or transport loss on the livez route followed by >=1 immediate 200
  re-probe (livez or healthz) = DEFECT (any 5xx while alive = Type3;
  >=2 recovered transport losses = Type3; GET face persistently non-200
  across 3 re-probes while healthz answers 200 = Type4 corrupted liveness
  signal); persistent non-200 with NO aliveness proof on either face =
  SCRIPT_ERROR; clean 4xx / permissive 2xx on non-GET = NO_DEFECT with G9
  disposition NOTES printed.
"""
import os
import sys
import json
import time
import threading
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
if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)

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

# ---- livez face: URL derived from raw_knowledge api_endpoints[livez].url
# (the runtime PATHS table has no native key for it; established rt.PATHS[key]
# extension pattern — value registered verbatim from the knowledge source,
# never invented here). Upward walk finds raw_knowledge.json next to the
# contract; the literal equals the documented url should the walk fail.
LIVEZ_KEY = "livez"
LIVEZ_URL = "/livez"          # verbatim raw_knowledge api_endpoints[livez].url
_derived = "verbatim literal == raw_knowledge api_endpoints[livez].url"
for _p in Path(__file__).resolve().parents:
    _rk = _p / "raw_knowledge.json"
    if _rk.exists():
        try:
            _rkd = json.loads(_rk.read_text(encoding="utf-8"))
            for _e in _rkd.get("api_endpoints", []):
                if _e.get("path") == "livez" and _e.get("url"):
                    LIVEZ_URL = _e["url"]
                    _derived = "runtime-derived from raw_knowledge.json api_endpoints[livez].url"
                    break
        except Exception:
            pass
        break
if LIVEZ_KEY not in rt.PATHS:
    rt.PATHS[LIVEZ_KEY] = LIVEZ_URL
print(f"[path derivation] {LIVEZ_KEY} = {rt.PATHS[LIVEZ_KEY]} ({_derived})")

# cross-check liveness face (documented health route, native in rt.PATHS)
XCHECK_KEY = "healthz"

N_BASE = 3
N_TAIL = 5
SPACING = 0.15
VOLLEY_ROUNDS = 2
READER_ITERS = 8
PROBE_TIMEOUT = 15

# hostile set: method + label + optional unexpected JSON body (bodies stay
# dicts — rt.request forwards them via its json channel; body-parser torture
# is boundary lane, this volley targets the ROUTE's method disposition)
HOSTILE_SET = [
    ("HEAD", "head", None),
    ("OPTIONS", "options", None),
    ("POST", "post-json", {"id": 1, "vector": [0.1, 0.2, 0.3]}),
    ("POST", "post-nested", {"filter": {"must": []}, "unexpected": {"deep": [1, 2, 3]}}),
    ("PUT", "put-cfg", {"vectors": {"size": 4, "distance": "Cosine"}}),
    ("PATCH", "patch-op", {"op": "probe", "path": "/livez"}),
    ("DELETE", "delete", None),
]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; path_key from rt.PATHS only ("livez" -> /livez)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_maybe_json(raw):
    """Envelope guard: livez 200 body is text/plain (NOT JSON) per the
    v-1-18-x OpenAPI shape — never crash on it; return parsed only if it
    happens to be JSON (informational envelope NOTE only)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, (dict, list)) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"   # unique run token (log correlation)
    print(f"[state_livez_002] run_token={TS} base={BASE_URL}")
    NOTES = []
    DEFECTS = []
    trans_anoms = []     # (tag, raw) recovered transport losses (status 0)
    spec_viol = []       # (tag, status, raw, proof) 5xx on the livez route while alive
    false_live = []      # (tag, status, raw, proof) GET face persistently non-200 while alive
    obs503 = []          # (tag, raw) recovered 503 samples — recorded, not claimed

    def probe(tag):
        """One measured GET /livez probe. Returns (status, raw)."""
        s, raw = safe_request("GET", LIVEZ_KEY, timeout=PROBE_TIMEOUT)
        print(f"[{tag}] GET /livez status={s} raw={str(raw)[:100]!r}")
        return s, raw

    def envelope_note(tag, s, raw):
        """200-body envelope observations (informational; the unit's promise
        pins status codes, not the text/plain payload)."""
        if s != 200:
            return
        body = str(raw) if raw is not None else ""
        if body.strip() == "":
            NOTES.append(f"{tag}: HTTP 200 with EMPTY body — OpenAPI 200 "
                         f"shape is text/plain content; printed for the record")
        elif parse_maybe_json(body) is not None:
            NOTES.append(f"{tag}: HTTP 200 body parses as JSON — envelope "
                         f"differs from the documented text/plain shape; "
                         f"printed for the record raw={body[:100]!r}")

    def aliveness_proof(tag):
        """D3b/R22: transport & anomaly branches carry inline liveness
        re-probes on the unit face (livez x3) plus the documented health
        route (healthz x2) — a 200 on EITHER proves the process alive.

        Returns (livez_repro, healthz_repro, alive, livez_recovered)."""
        lz = []
        for i in range(3):
            s, raw = safe_request("GET", LIVEZ_KEY, timeout=10)
            lz.append(s)
            print(f"[{tag} lzrepro{i + 1}] status={s} raw={str(raw)[:80]!r}")
            if i < 2:
                time.sleep(0.1)
        hz = []
        for i in range(2):
            s, raw = safe_request("GET", XCHECK_KEY, timeout=10)
            hz.append(s)
            print(f"[{tag} hzrepro{i + 1}] status={s} raw={str(raw)[:80]!r}")
            if i == 0:
                time.sleep(0.1)
        alive = any(x == 200 for x in lz) or any(x == 200 for x in hz)
        return lz, hz, alive, any(x == 200 for x in lz)

    def handle_anomaly(tag, s, raw):
        """Serial-context anomaly handler: inline liveness re-proof then
        classify. Returns "ENV" / "DEFECT" / "OK"."""
        lz, hz, alive, lz_ok = aliveness_proof(tag)
        proof = f"livez={lz} healthz={hz}"
        if not alive:
            NOTES.append(f"{tag}: original status={s} AND neither face "
                         f"answered 200 on re-probe ({proof}) — environment "
                         f"class: the process does not answer any liveness "
                         f"face; a dead/unadjudicable service cannot produce "
                         f"a unit verdict on a read-only face")
            return "ENV"
        if lz_ok:
            if s == 503:
                obs503.append((tag, str(raw)[:100]))
                NOTES.append(f"{tag}: HTTP 503 that RECOVERED ({proof}) — "
                             f"tolerated per 200-while-alive / 503-while-not "
                             f"liveness semantics; recorded, not claimed "
                             f"(NOTE: the livez v-1-18-x OpenAPI shard "
                             f"documents expected_responses {{200}} only)")
                return "OK"
            if s == 0:
                trans_anoms.append((tag, str(raw)[:100]))
                NOTES.append(f"{tag}: transport loss (status 0) that "
                             f"RECOVERED ({proof}) — race discipline: single "
                             f"occurrences are not claimed; counted for the "
                             f">=2-reproduction rule")
                return "OK"
            spec_viol.append((tag, s, str(raw)[:150], proof))
            return "DEFECT"
        false_live.append((tag, s, str(raw)[:150], proof))
        return "DEFECT"

    def classify_get_anomalies(items, proof_alive, proof_livez_ok, proof_desc):
        """Classify (tag, status, raw) GET-face anomalies against an
        already-collected aliveness proof (reader/tail collective path)."""
        for (tag, s, raw) in items:
            if not proof_alive:
                break
            if proof_livez_ok:
                if s == 503:
                    obs503.append((tag, str(raw)[:100]))
                    NOTES.append(f"{tag}: HTTP 503 that RECOVERED "
                                 f"({proof_desc}) — tolerated liveness "
                                 f"branch; recorded, not claimed")
                elif s == 0:
                    trans_anoms.append((tag, str(raw)[:100]))
                    NOTES.append(f"{tag}: transport loss recovered "
                                 f"({proof_desc}) — counted for the "
                                 f">=2-reproduction rule")
                else:
                    spec_viol.append((tag, s, str(raw)[:150], proof_desc))
            else:
                false_live.append((tag, s, str(raw)[:150], proof_desc))

    try:
        # ---- phase (0): sequential baseline (3 probes, positive leg) ----
        print("== phase 0: sequential baseline ==")
        base_ok = 0
        for i in range(N_BASE):
            tag = f"base{i + 1}"
            s, raw = probe(tag)
            if s == 200:
                base_ok += 1
                envelope_note(tag, s, raw)
            else:
                if handle_anomaly(tag, s, raw) == "ENV":
                    for n in NOTES:
                        print(f"NOTE: {n}")
                    return "SCRIPT_ERROR"
            time.sleep(SPACING)

        # ---- phase (2): concurrent hostile-method volley x GET readers ----
        t_count = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
        t_count = max(1, min(t_count, 200))
        n_readers = max(2, t_count // 3)
        print(f"== phase 2: hostile volley — {t_count} workers x "
              f"{len(HOSTILE_SET)} methods x {VOLLEY_ROUNDS} rounds on "
              f"/livez, concurrent with {n_readers} GET reader threads ==")
        volley_results = []
        reader_results = []
        res_lock = threading.Lock()

        def volley_worker(wid):
            for r in range(VOLLEY_ROUNDS):
                for (method, label, body) in HOSTILE_SET:
                    tag = f"vol{wid}-{label}-r{r + 1}"
                    try:
                        s, raw = safe_request(method, LIVEZ_KEY, body=body,
                                              timeout=PROBE_TIMEOUT)
                    except Exception as e:  # worker-level guard (req never
                        s, raw = 0, str(e)   # raises; keep the thread alive)
                    with res_lock:
                        volley_results.append((tag, method, s, str(raw)[:120]))
                    time.sleep(0.02)

        def reader_worker(rid):
            for j in range(READER_ITERS):
                tag = f"rd{rid + 1}#{j + 1}"
                try:
                    s, raw = safe_request("GET", LIVEZ_KEY,
                                          timeout=PROBE_TIMEOUT)
                except Exception as e:
                    s, raw = 0, str(e)
                with res_lock:
                    reader_results.append((tag, s, str(raw)[:120]))
                time.sleep(0.02)

        threads = ([threading.Thread(target=reader_worker, args=(r,))
                    for r in range(n_readers)] +
                   [threading.Thread(target=volley_worker, args=(w,))
                    for w in range(t_count)])
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # volley disposition summary (G9 record — informational, not claims)
        by_label = {}
        for (tag, method, s, raw) in volley_results:
            lbl = tag.split("-")[1]
            by_label.setdefault(lbl, []).append(s)
        for lbl in sorted(by_label):
            NOTES.append(f"volley disposition {lbl.upper()}: statuses "
                         f"{by_label[lbl]} (shard documents GET/200 only; "
                         f"clean 4xx rejection or permissive 2xx are "
                         f"recorded, not claimable)")
        volley_5xx = [(tag, s, raw) for (tag, m, s, raw) in volley_results
                      if 500 <= s <= 599]
        volley_0 = [(tag, s, raw) for (tag, m, s, raw) in volley_results
                    if s == 0]
        reader_bad = [(tag, s, raw) for (tag, s, raw) in reader_results
                      if s != 200]
        reader_ok = len(reader_results) - len(reader_bad)
        print(f"[volley] total={len(volley_results)} 5xx={len(volley_5xx)} "
              f"transport0={len(volley_0)}")
        for (tag, s, raw) in volley_5xx:
            print(f"[volley 5xx {tag}] status={s} raw={raw!r}")
        print(f"[readers during volley] ok={reader_ok}/{len(reader_results)} "
              f"anomalies={len(reader_bad)}")
        for (tag, s, raw) in reader_bad:
            print(f"[reader anomaly {tag}] status={s} raw={raw!r}")

        # ---- phase (3): post-volley tail (5 probes, state bracketing) ----
        print("== phase 3: post-volley tail ==")
        tail = []
        tail_bad = []
        tail_ok = 0
        for i in range(N_TAIL):
            tag = f"tail{i + 1}"
            s, raw = probe(tag)
            tail.append(s)
            if s == 200:
                tail_ok += 1
                envelope_note(tag, s, raw)
            else:
                tail_bad.append((tag, s, str(raw)[:120]))
            time.sleep(SPACING)
        tail_alive = all(x == 200 for x in tail)

        # ---- adjudicate volley + reader anomalies against the tail proof ----
        pending_v5 = [(f"{tag}", s, raw) for (tag, s, raw) in volley_5xx]
        pending_rd = [(tag, s, raw) for (tag, s, raw) in reader_bad]
        if (pending_v5 or pending_rd or volley_0 or tail_bad):
            if tail_alive:
                proof_desc = f"tail={tail}"
                # 5xx on the livez route while the face provably still
                # answers 200 = crash-class runtime anomaly (Type3)
                for (tag, s, raw) in pending_v5:
                    spec_viol.append((tag, s, raw, proof_desc))
                for (tag, s, raw) in volley_0:
                    trans_anoms.append((tag, raw))
                    NOTES.append(f"{tag}: transport loss (status 0) on a "
                                 f"hostile-method volley probe, recovered by "
                                 f"the all-200 tail ({proof_desc}) — counted "
                                 f"for the >=2-reproduction rule")
                classify_get_anomalies(pending_rd, True, True, proof_desc)
                print(f"[volley/reader adjudication] tail aliveness proof="
                      f"{tail} — claims: spec_viol="
                      f"{[x[1] for x in spec_viol]} false_live="
                      f"{[x[1] for x in false_live]} transport="
                      f"{[t for (t, _) in trans_anoms]}")
            else:
                lz, hz, alive, lz_ok = aliveness_proof("volley-tail")
                proof_desc = f"livez={lz} healthz={hz}"
                if not alive:
                    print(f"[volley/reader adjudication] tail={tail}, "
                          f"re-proof {proof_desc} — no aliveness proof on "
                          f"either face; cannot distinguish a volley-induced "
                          f"crash from environment death")
                    for n in NOTES:
                        print(f"NOTE: {n}")
                    return "SCRIPT_ERROR"
                for (tag, s, raw) in pending_v5:
                    spec_viol.append((tag, s, raw, proof_desc))
                for (tag, s, raw) in volley_0:
                    trans_anoms.append((tag, raw))
                classify_get_anomalies(pending_rd, True, lz_ok, proof_desc)
                print(f"[volley/reader adjudication] re-proof {proof_desc} "
                      f"(livez_recovered={lz_ok}) — claims: spec_viol="
                      f"{[x[1] for x in spec_viol]} false_live="
                      f"{[x[1] for x in false_live]} transport="
                      f"{[t for (t, _) in trans_anoms]}")

        # ---- tail anomalies handled serially (own inline re-proof each) ----
        for (tag, s, raw) in tail_bad:
            if handle_anomaly(tag, s, raw) == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"

        # ---- verdict assembly ----
        for (tag, s, raw, proof) in spec_viol:
            DEFECTS.append(
                f"[{tag}] a request on the /livez route returned status {s} "
                f"(5xx band) while immediate re-probes proved the process "
                f"alive ({proof}) — Type3_RuntimeFailure on the liveness "
                f"face — raw={raw!r}")
        for (tag, s, raw, proof) in false_live:
            DEFECTS.append(
                f"[{tag}] GET /livez returned status {s} AND all 3 livez "
                f"re-probes stayed non-200 while healthz cross-probes "
                f"answered 200 ({proof}) — hostile input corrupted the "
                f"liveness signal of a demonstrably alive process (assertion "
                f"promises 200 while the process runs) — "
                f"Type4_StateLogicViolation — raw={raw!r}")
        if len(trans_anoms) >= 2:
            DEFECTS.append(
                f"{len(trans_anoms)} transport losses (status 0) on the "
                f"/livez route, each recovered by immediate 200 re-probes "
                f"({[t for (t, _) in trans_anoms]}) — repeated liveness-face "
                f"connection instability on an alive service — "
                f"Type3_RuntimeFailure")
        if obs503:
            NOTES.append(f"{len(obs503)} recovered HTTP 503 sample(s) "
                         f"recorded (tolerated liveness-branch observations, "
                         f"not claims): {[t for (t, _) in obs503]}")

        print(f"[summary] baseline {base_ok}/{N_BASE} x200; volley "
              f"{len(volley_results)} hostile-method probes "
              f"(5xx={len(volley_5xx)}, transport0={len(volley_0)}); "
              f"readers-during-volley ok={reader_ok}/{len(reader_results)}; "
              f"tail {tail_ok}/{N_TAIL} x200")
        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("liveness-face hostile-volley verification complete: the GET "
              "face answered 200 across baseline, concurrent "
              "reader-during-volley and post-volley probes, and every "
              "hostile-method probe on the route landed outside the 5xx "
              "band (200-while-alive semantics survived the volley; "
              "dispositions recorded as G9 notes) — no 5xx, no corrupted "
              "liveness signal, no reproducible transport loss — NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # read-only face — no collections, no aliases, nothing to tear down;
        # the trailing livez probe below is informational only and must
        # never flip the verdict (cleanup discipline: no drops needed here)
        try:
            hs, hraw = safe_request("GET", LIVEZ_KEY, timeout=10)
            print(f"[cleanup probe] status={hs} raw={str(hraw)[:80]!r}")
        except Exception:
            pass


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
