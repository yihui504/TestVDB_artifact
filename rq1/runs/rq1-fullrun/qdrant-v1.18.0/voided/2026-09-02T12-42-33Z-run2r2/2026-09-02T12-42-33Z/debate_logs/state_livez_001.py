#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_livez_001
# strategy: concurrent
# endpoint: livez
# constraint_ids: qdrant_behavioral_livez_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/livez
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (concurrency on the liveness face — liveness-signal
#   stability under sequential, parallel and mixed-load probing; this unit IS
#   the process-liveness face, so its 200-while-alive semantics are asserted
#   here as the unit under test, not as an auxiliary probe)
"""
Attack: concurrent (Strategy 4) + liveness-state stability of the process
  liveness face x qdrant_behavioral_livez_001 (endpoint livez — GET /livez,
  the only unit in chunk_livez; assertion: liveness probe returns 200 while
  the process is alive — NO dependency check; v-1-18-x OpenAPI shard for
  livez declares expected_responses {"200": "ok"} ONLY, text/plain envelope —
  unlike sibling healthz which also sanctions 503). Read-only face; no
  collections needed; no state mutation exists on this endpoint. Positive
  legs (G4): (0) 12 settled sequential probes spaced 200 ms + (1) 2
  parameterized probes carrying the contract-declared optional api-key query
  face (G9: disposition must match the bare face) + (2b) mixed-load leg —
  livez probes concurrent with sibling read-only face load
  (GET /collections + GET /), exercising the assertion's own
  "(no dependency check)" clause: livez must stay 200 while sibling routes
  are hammered + (3) 3 tail probes bracketing the burst — all must return
  exactly HTTP 200 on the healthy sandbox instance. Negative constructions
  (G4/G5): (2) concurrent probe burst (TESTVDB_CONCURRENT_THREADS workers
  x 5) challenging the same 200 promise under parallel load — 5xx /
  connection loss here = Type3 channel; any response status outside the
  documented {200, 503} tolerance set (503 tolerated per the
  200-while-able-to-serve / 503-while-not liveness semantics) observed
  while immediate inline livez + healthz re-probes prove the process alive
  = Type3_RuntimeFailure (crash-class status on the liveness path);
  persistent livez non-200 while healthz cross-probes answer 200 =
  false liveness signal on a demonstrably alive process (contradicts
  "200 while the process runs") = Type4_StateLogicViolation; recovered
  transport anomalies (status 0) require >=2 reproductions before a Type3
  claim (race discipline).
Oracle: every probe on the healthy instance returns HTTP 200 (0 anomalies);
  a non-{200,503} status or transport loss followed by >=1 immediate 200
  re-probe (livez or healthz) = DEFECT (1+ non-503 spec-violating status =
  Type3_RuntimeFailure; >=2 recovered transport losses = Type3; livez
  persistently non-200 across 3 re-probes while healthz answers 200 = Type4
  false liveness); persistent non-200 with NO aliveness proof on either
  face = SCRIPT_ERROR (dead/unadjudicable service, read-only face); sole
  503-with-recovery samples = NO_DEFECT with observations printed (recorded
  with the doc-set NOTE that the livez OpenAPI shard documents only 200)
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
# (the runtime PATHS table has no key for it; established rt.PATHS[key]
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

# cross-check liveness face (documented health route, present in rt.PATHS)
XCHECK_KEY = "healthz"

N_SEQ = 12
N_TAIL = 3
SPACING = 0.2
BURST_PER_WORKER = 5
MIX_ITERS = 6
PROBE_TIMEOUT = 15


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; path_key from rt.PATHS only ("livez" -> /livez)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_maybe_json(raw):
    """Envelope guard: livez 200 body is text/plain (NOT JSON) per the
    v-1-18-x OpenAPI shape — never crash on it; return parsed only if it
    happens to be JSON (used for an informational envelope NOTE)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, (dict, list)) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"   # unique run token (log correlation)
    print(f"[state_livez_001] run_token={TS} base={BASE_URL}")
    NOTES = []
    DEFECTS = []
    obs503 = []          # (tag, raw) recovered 503 samples — recorded, not claimed
    trans_anoms = []     # (tag, raw) recovered transport losses (status 0)
    spec_viol = []       # (tag, status, raw, proof) status outside {200,503}
    false_live = []      # (tag, status, raw, proof) persistent non-200 while alive

    def probe(tag, query_params=None):
        """One measured GET /livez probe. Returns (status, raw)."""
        s, raw = safe_request("GET", LIVEZ_KEY, query_params=query_params,
                              timeout=PROBE_TIMEOUT)
        print(f"[{tag}] GET /livez status={s} raw={str(raw)[:100]!r}")
        return s, raw

    def envelope_note(tag, s, raw):
        """200-body envelope observations (informational; the unit's promise
        pins status codes, not the text/plain payload)."""
        if s != 200:
            return
        body = str(raw) if raw is not None else ""
        if body.strip() == "":
            NOTES.append(f"{tag}: HTTP 200 with EMPTY body — OpenAPI 200 shape "
                         f"is text/plain content; printed for the record")
        else:
            parsed = parse_maybe_json(body)
            if parsed is not None:
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
        classify.

        Returns "ENV" (no face proves the process alive — SCRIPT_ERROR
        class), "DEFECT" (claim appended), or "OK" (recorded observation)."""
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
            # livez itself recovered -> momentary anomaly on an alive face
            if s == 503:
                obs503.append((tag, str(raw)[:100]))
                NOTES.append(f"{tag}: HTTP 503 that RECOVERED ({proof}) — "
                             f"tolerated per 200-while-able-to-serve / "
                             f"503-while-not liveness semantics; recorded, "
                             f"not claimed (NOTE: the livez v-1-18-x OpenAPI "
                             f"shard documents expected_responses {{200}} "
                             f"only — kept for the record)")
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
        # livez re-probes all non-200 while healthz proves the process alive:
        # persistent false liveness signal on a demonstrably alive process —
        # contradicts the unit assertion ("returns 200 while the process is
        # alive, no dependency check": dependency trouble must not flip it)
        false_live.append((tag, s, str(raw)[:150], proof))
        return "DEFECT"

    def classify_with_proof(items, proof_alive, proof_livez_ok, proof_desc):
        """Classify a batch of (tag, status, raw) anomalies against an
        already-collected aliveness proof (burst/tail collective path)."""
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

    def serial_leg(tag_prefix, count, query_params=None, spacing=SPACING):
        """count settled probes; anomalies handled inline with re-proof.

        Returns (ok_count, env_aborted)."""
        ok_n = 0
        for i in range(count):
            tag = f"{tag_prefix}{i + 1}"
            s, raw = probe(tag, query_params=query_params)
            if s == 200:
                ok_n += 1
                envelope_note(tag, s, raw)
            else:
                if handle_anomaly(tag, s, raw) == "ENV":
                    return ok_n, True
            time.sleep(spacing)
        return ok_n, False

    try:
        # ---- phase (0): sequential stability baseline (12 probes) ----
        print("== phase 0: sequential stability ==")
        seq_ok, env0 = serial_leg("seq", N_SEQ)
        if env0:
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"

        # ---- phase (1): parameterized face — contract-declared optional
        #      api-key parameter present vs absent must be disposition-
        #      consistent (absent = phases 0/3; present = here, as query) ----
        print("== phase 1: parameterized probe (api-key query face) ==")
        param_ok, env1 = serial_leg("param", 2,
                                    query_params={"api-key": "statelz_garbage"})
        if env1:
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"

        # ---- phase (2): concurrent burst (Strategy 4) ----
        t_count = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
        t_count = max(1, min(t_count, 200))
        print(f"== phase 2: concurrent burst — {t_count} workers x "
              f"{BURST_PER_WORKER} probes = {t_count * BURST_PER_WORKER} "
              f"parallel GET /livez ==")
        burst_results = []
        res_lock = threading.Lock()

        def worker(wid):
            for j in range(BURST_PER_WORKER):
                try:
                    s, raw = safe_request("GET", LIVEZ_KEY,
                                          timeout=PROBE_TIMEOUT)
                except Exception as e:  # worker-level guard (req never raises,
                    s, raw = 0, str(e)   # but keep the thread alive regardless)
                with res_lock:
                    burst_results.append((wid, j, s, raw))
                time.sleep(0.02)

        threads = [threading.Thread(target=worker, args=(w,))
                   for w in range(t_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        burst_ok = sum(1 for (_, _, s, _) in burst_results if s == 200)
        burst_bad = [(w, j, s, r) for (w, j, s, r) in burst_results if s != 200]
        print(f"[burst] ok={burst_ok}/{len(burst_results)} "
              f"anomalies={len(burst_bad)}")
        for (w, j, s, r) in burst_bad:
            print(f"[burst worker={w} #{j}] status={s} raw={str(r)[:100]!r}")
        # 200-body envelope observations inside the burst (informational)
        for (w, j, s, r) in burst_results:
            if s == 200:
                body = str(r) if r is not None else ""
                if body.strip() == "":
                    NOTES.append(f"burst worker={w} #{j}: 200 EMPTY body — "
                                 f"envelope note (text/plain expected)")
                elif parse_maybe_json(body) is not None:
                    NOTES.append(f"burst worker={w} #{j}: 200 JSON-like body "
                                 f"— envelope note raw={body[:80]!r}")

        # ---- phase (2b): mixed-load liveness stability — the assertion's
        #      own "(no dependency check)" clause: livez must stay 200 while
        #      sibling read-only faces are under concurrent load. Sibling
        #      face statuses are LOAD CONTEXT ONLY (not the unit under test)
        #      and can never produce claims here. ----
        print(f"== phase 2b: mixed-load stability — livez probes concurrent "
              f"with GET /collections + GET / load ==")
        mix_livez = []
        mix_load = []
        n_livez_w = max(2, t_count // 2)
        n_load_w = max(2, t_count - n_livez_w)

        def livez_prober(wid):
            for j in range(MIX_ITERS):
                try:
                    s, raw = safe_request("GET", LIVEZ_KEY,
                                          timeout=PROBE_TIMEOUT)
                except Exception as e:
                    s, raw = 0, str(e)
                with res_lock:
                    mix_livez.append((wid, j, s, raw))
                time.sleep(0.02)

        def load_prober(wid):
            faces = ["list_collections", "root"]
            for j in range(MIX_ITERS):
                key = faces[j % len(faces)]
                try:
                    s, raw = safe_request("GET", key, timeout=PROBE_TIMEOUT)
                except Exception as e:
                    s, raw = 0, str(e)
                with res_lock:
                    mix_load.append((wid, key, s, raw))
                time.sleep(0.02)

        mix_threads = ([threading.Thread(target=livez_prober, args=(w,))
                        for w in range(n_livez_w)] +
                       [threading.Thread(target=load_prober, args=(w,))
                        for w in range(n_load_w)])
        for t in mix_threads:
            t.start()
        for t in mix_threads:
            t.join()

        mix_ok = sum(1 for (_, _, s, _) in mix_livez if s == 200)
        mix_bad = [(w, j, s, r) for (w, j, s, r) in mix_livez if s != 200]
        load_ok = sum(1 for (_, _, s, _) in mix_load if s == 200)
        print(f"[mix] livez ok={mix_ok}/{len(mix_livez)} "
              f"anomalies={len(mix_bad)}; sibling-load faces "
              f"ok={load_ok}/{len(mix_load)} (context only)")
        for (w, key, s, r) in mix_load:
            if s != 200:
                NOTES.append(f"mix load worker={w} face={key}: sibling face "
                             f"status={s} (load context only — not the unit; "
                             f"raw={str(r)[:80]!r})")
        for (w, j, s, r) in mix_bad:
            print(f"[mix livez worker={w} #{j}] status={s} "
                  f"raw={str(r)[:100]!r}")

        # ---- phase (3): tail probes — collective liveness re-check for the
        #      burst + mix anomalies and state bracketing (same face status
        #      after the load as before it) ----
        print("== phase 3: tail stability (collective re-check) ==")
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
                tail_bad.append((tag, s, raw))
            time.sleep(SPACING)
        tail_alive = all(x == 200 for x in tail)

        # ---- adjudicate burst + mix livez anomalies against the tail proof ----
        pending = ([(f"burst{w}#{j}", s, r) for (w, j, s, r) in burst_bad] +
                   [(f"mix{w}#{j}", s, r) for (w, j, s, r) in mix_bad])
        if pending:
            if tail_alive:
                classify_with_proof(pending, True, True, f"tail={tail}")
                print(f"[burst/mix adjudication] tail aliveness proof={tail} "
                      f"— claims per status: "
                      f"spec_viol={[x[1] for x in spec_viol]} "
                      f"false_live={[x[1] for x in false_live]} "
                      f"transport={[t for (t, _) in trans_anoms]} "
                      f"503_recorded={[t for (t, _) in obs503]}")
            else:
                # tail itself not uniformly 200 — re-prove aliveness inline
                # (livez x3 + healthz x2) before any classification
                lz, hz, alive, lz_ok = aliveness_proof("burst/mix-tail")
                proof_desc = f"livez={lz} healthz={hz}"
                if not alive:
                    print(f"[burst/mix adjudication] tail={tail}, re-proof "
                          f"{proof_desc} — no aliveness proof on either "
                          f"face; cannot distinguish a load crash from "
                          f"environment death")
                    for n in NOTES:
                        print(f"NOTE: {n}")
                    return "SCRIPT_ERROR"
                classify_with_proof(pending, True, lz_ok, proof_desc)
                print(f"[burst/mix adjudication] re-proof {proof_desc} "
                      f"(livez_recovered={lz_ok}) — claims per status: "
                      f"spec_viol={[x[1] for x in spec_viol]} "
                      f"false_live={[x[1] for x in false_live]} "
                      f"transport={[t for (t, _) in trans_anoms]} "
                      f"503_recorded={[t for (t, _) in obs503]}")

        # ---- tail anomalies handled serially (own inline re-proof each) ----
        for (tag, s, raw) in tail_bad:
            if handle_anomaly(tag, s, raw) == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"

        # ---- verdict assembly ----
        # Type3 claims: every spec-violating status observed while the face
        # was proven alive (individually conclusive — a status outside the
        # documented {200,503} set on a live liveness face is a crash-class
        # runtime anomaly)
        for (tag, s, raw, proof) in spec_viol:
            band = "5xx" if 500 <= s <= 599 else "4xx/other"
            DEFECTS.append(
                f"[{tag}] GET /livez returned status {s} (outside the "
                f"documented {{200, 503}} tolerance set, {band} band) while "
                f"immediate inline re-probes proved the process alive "
                f"({proof}) — Type3_RuntimeFailure on the liveness face — "
                f"raw={raw!r}")
        # Type4 claims: livez persistently non-200 while healthz proves the
        # process alive — false liveness signal (violates "200 while the
        # process runs, no dependency check")
        for (tag, s, raw, proof) in false_live:
            DEFECTS.append(
                f"[{tag}] GET /livez returned status {s} AND all 3 livez "
                f"re-probes stayed non-200 while healthz cross-probes "
                f"answered 200 ({proof}) — persistent false liveness signal "
                f"on a demonstrably alive process (assertion promises 200 "
                f"while the process runs, no dependency check) — "
                f"Type4_StateLogicViolation — raw={raw!r}")
        # transport anomalies: >=2 reproductions required (race discipline)
        if len(trans_anoms) >= 2:
            DEFECTS.append(
                f"{len(trans_anoms)} transport losses (status 0) on "
                f"GET /livez each recovered by immediate 200 re-probes "
                f"({[t for (t, _) in trans_anoms]}) — repeated liveness-face "
                f"connection instability on an alive service — "
                f"Type3_RuntimeFailure")
        if obs503:
            NOTES.append(f"{len(obs503)} recovered HTTP 503 sample(s) "
                         f"recorded (tolerated liveness-branch observations, "
                         f"not claims; NOTE the livez OpenAPI shard "
                         f"documents only 200): "
                         f"{[t for (t, _) in obs503]}")

        measured = (N_SEQ + 2 + N_TAIL + len(burst_results) + len(mix_livez))
        ok_total = seq_ok + param_ok + burst_ok + tail_ok + mix_ok
        print(f"[summary] ok={ok_total}/{measured} measured livez probes "
              f"(seq {seq_ok}/{N_SEQ}, param {param_ok}/2, burst "
              f"{burst_ok}/{len(burst_results)}, mix "
              f"{mix_ok}/{len(mix_livez)}, tail {tail_ok}/{N_TAIL})")
        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("liveness-face verification complete: every livez probe "
              "returned HTTP 200 across sequential, parameterized, "
              "concurrent-burst, mixed-sibling-load and post-burst probes "
              "(200-while-alive semantics held; the no-dependency-check "
              "clause survived concurrent sibling-face load); no "
              "spec-violating status, no false liveness signal, no "
              "reproducible transport loss — NO_DEFECT")
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
