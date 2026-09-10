#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_healthz_001
# strategy: concurrent
# endpoint: healthz
# constraint_ids: qdrant_behavioral_healthz_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/healthz
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (concurrency on the liveness face — health-state signaling
#   stability under sequential + parallel probing; the unit itself is the
#   liveness face every sibling script re-probes, so its 200-semantics are
#   asserted here as the unit under test, not as an auxiliary probe)
"""
Attack: concurrent (Strategy 4) + temporal state-stability of the liveness
  face x qdrant_behavioral_healthz_001 (endpoint healthz — GET /healthz, the
  only unit in chunk_healthz; assertion: HTTP 200 while the service is
  healthy, HTTP 503 when unhealthy; v-1-18-x OpenAPI 200 body = text/plain
  "healthz check passed" — NO JSON envelope). Read-only face; no collections
  needed; no state mutation exists on this endpoint. Positive legs (G4):
  (0) 12 settled sequential probes spaced 200 ms + (1) 2 parameterized probes
  carrying the contract-declared optional api-key query face + (3) 3 tail
  probes after the burst — all must return exactly HTTP 200 on the healthy
  sandbox instance (bracketing: same status before and after the burst).
  Negative constructions (G4/G5): (2) concurrent probe burst
  (TESTVDB_CONCURRENT_THREADS workers x 5) challenging the same 200 promise
  under parallel load — 5xx / connection loss here = Type3 channel; any
  response status outside the documented {200, 503} set observed while
  immediate inline /healthz re-probes prove the face alive =
  Type3_RuntimeFailure (crash-class status on the liveness path; the OpenAPI
  shape oracle sanctions only 200 and 503); recovered 503 samples are
  spec-compliant (the assertion's own unhealthy branch — a momentary genuine
  unhealthiness is indistinguishable from false signaling, so they are
  recorded, never claimed); recovered transport anomalies (status 0) require
  >=2 reproductions before a Type3 claim (strategy-7 race discipline).
Oracle: every probe on the healthy instance returns HTTP 200 (0 anomalies);
  a non-{200,503} status or transport loss followed by >=1 immediate 200
  /healthz re-probe = DEFECT (1+ non-503 spec-violating status = Type3
  Type3_RuntimeFailure; >=2 recovered transport losses = Type3); persistent
  non-200 across re-probes / no aliveness proof after the burst =
  SCRIPT_ERROR (unhealthy branch or dead service not adjudicable read-only);
  sole 503-with-recovery samples = NO_DEFECT with observations printed
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

N_SEQ = 12
N_TAIL = 3
SPACING = 0.2
BURST_PER_WORKER = 5
PROBE_TIMEOUT = 15


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; path_key from rt.PATHS only ("healthz" -> /healthz)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_maybe_json(raw):
    """Envelope guard: healthz 200 body is text/plain (NOT JSON) per the
    v-1-18-x OpenAPI shape — never crash on it; return parsed only if it
    happens to be JSON (used for an informational envelope NOTE)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, (dict, list)) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"   # unique run token (log correlation)
    print(f"[state_healthz_001] run_token={TS} base={BASE_URL}")
    NOTES = []
    DEFECTS = []
    obs503 = []          # (tag, raw) recovered 503 samples — recorded, not claimed
    trans_anoms = []     # (tag, raw) recovered transport losses (status 0)
    spec_viol = []       # (tag, status, raw, repro) status outside {200,503}

    def probe(tag, query_params=None):
        """One measured GET /healthz probe. Returns (status, raw)."""
        s, raw = safe_request("GET", "healthz", query_params=query_params,
                              timeout=PROBE_TIMEOUT)
        print(f"[{tag}] GET /healthz status={s} raw={str(raw)[:100]!r}")
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

    def repro3(tag):
        """D3b/R19: transport & anomaly branches carry inline /healthz
        re-probes (the liveness face coincides with the unit under test, so
        the same lightweight face is the correct liveness re-check)."""
        out = []
        for i in range(3):
            s, raw = safe_request("GET", "healthz", timeout=10)
            out.append(s)
            print(f"[{tag} repro{i + 1}] status={s} raw={str(raw)[:80]!r}")
            if i < 2:
                time.sleep(0.1)
        return out

    def handle_anomaly(tag, s, raw):
        """Serial-context anomaly handler: repro3 then classify.

        Returns "ENV" (service not answering liveness — SCRIPT_ERROR class),
        "DEFECT" (claim appended to DEFECTS), or "OK" (recorded observation).
        """
        repro = repro3(tag)
        alive = any(x == 200 for x in repro)
        if not alive:
            NOTES.append(f"{tag}: original status={s} AND none of the 3 "
                         f"immediate /healthz re-probes returned 200 "
                         f"(repro={repro}) — environment-class: the service "
                         f"does not answer its own liveness face; the "
                         f"spec-sanctioned 503-when-unhealthy branch cannot "
                         f"be distinguished from a dead service on a read-only "
                         f"face, so no unit verdict is attempted")
            return "ENV"
        if s == 503:
            obs503.append((tag, str(raw)[:100]))
            NOTES.append(f"{tag}: HTTP 503 that RECOVERED (repro={repro}) — "
                         f"spec-compliant unhealthy-branch sample on an "
                         f"otherwise-alive face; recorded, not claimed (the "
                         f"assertion sanctions 503 when unhealthy, and a "
                         f"momentary genuine unhealthiness is not a false "
                         f"signal)")
            return "OK"
        if s == 0:
            trans_anoms.append((tag, str(raw)[:100]))
            NOTES.append(f"{tag}: transport loss (status 0) that RECOVERED "
                         f"(repro={repro}) — race discipline: single "
                         f"occurrences are not claimed; counted for the "
                         f">=2-reproduction rule")
            return "OK"
        # any other status (4xx, 500, 502, ...) while the face is proven alive
        spec_viol.append((tag, s, str(raw)[:150], repro))
        return "DEFECT"

    def serial_leg(tag_prefix, count, query_params=None, spacing=SPACING):
        """count settled probes; anomalies handled inline with repro3.

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
                                    query_params={"api-key": "statehz_garbage"})
        if env1:
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"

        # ---- phase (2): concurrent burst (Strategy 4) ----
        t_count = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
        t_count = max(1, min(t_count, 200))
        print(f"== phase 2: concurrent burst — {t_count} workers x "
              f"{BURST_PER_WORKER} probes = {t_count * BURST_PER_WORKER} "
              f"parallel GET /healthz ==")
        burst_results = []
        res_lock = threading.Lock()

        def worker(wid):
            for j in range(BURST_PER_WORKER):
                try:
                    s, raw = safe_request("GET", "healthz",
                                          timeout=PROBE_TIMEOUT)
                except Exception as e:  # worker-level guard (req never raises,
                    s, raw = 0, str(e)  # but keep the thread alive regardless)
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

        # ---- phase (3): tail probes — collective liveness re-check for the
        #      burst anomalies + state bracketing (same face status after
        #      the burst as before it) ----
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

        # ---- adjudicate burst anomalies against the tail aliveness proof ----
        if burst_bad:
            if not tail_alive:
                print(f"[burst adjudication] tail probes after the burst: "
                      f"{tail} — no aliveness proof; the service does not "
                      f"answer its liveness face post-burst -> cannot "
                      f"distinguish a load crash from environment death")
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            for (w, j, s, r) in burst_bad:
                if s == 503:
                    obs503.append((f"burst{w}#{j}", str(r)[:100]))
                    NOTES.append(f"burst worker={w} #{j}: HTTP 503 that "
                                 f"RECOVERED (tail={tail}) — spec-compliant "
                                 f"unhealthy-branch sample; recorded, not "
                                 f"claimed")
                elif s == 0:
                    trans_anoms.append((f"burst{w}#{j}", str(r)[:100]))
                    NOTES.append(f"burst worker={w} #{j}: transport loss "
                                 f"recovered by tail={tail} — counted for the "
                                 f">=2-reproduction rule")
                else:
                    spec_viol.append((f"burst{w}#{j}", s, str(r)[:150], tail))
            print(f"[burst adjudication] tail aliveness proof={tail} — "
                  f"claims per status: "
                  f"spec_viol={[x[1] for x in spec_viol if str(x[0]).startswith('burst')]} "
                  f"transport={[t for (t, _) in trans_anoms if str(t).startswith('burst')]}")

        # ---- tail anomalies handled serially (own 3x repro each) ----
        for (tag, s, raw) in tail_bad:
            if handle_anomaly(tag, s, raw) == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"

        # ---- verdict assembly ----
        # Type3 claims: every spec-violating status observed while the face
        # was proven alive (individually conclusive — a status outside the
        # OpenAPI-sanctioned {200,503} set on a live liveness face is a
        # crash-class runtime anomaly)
        for (tag, s, raw, repro) in spec_viol:
            band = "5xx" if 500 <= s <= 599 else "4xx/other"
            DEFECTS.append(
                f"[{tag}] GET /healthz returned status {s} (outside the "
                f"documented {{200, 503}} set, {band} band) while immediate "
                f"inline re-probes returned 200 (repro={repro}) — "
                f"Type3_RuntimeFailure on the liveness face — "
                f"raw={raw!r}")
        # transport anomalies: >=2 reproductions required (race discipline)
        if len(trans_anoms) >= 2:
            DEFECTS.append(
                f"{len(trans_anoms)} transport losses (status 0) on "
                f"GET /healthz each recovered by immediate 200 re-probes "
                f"({[t for (t, _) in trans_anoms]}) — repeated liveness-face "
                f"connection instability on an alive service — "
                f"Type3_RuntimeFailure")
        if obs503:
            NOTES.append(f"{len(obs503)} recovered HTTP 503 sample(s) "
                         f"recorded (spec-compliant unhealthy-branch "
                         f"observations, not claims): "
                         f"{[t for (t, _) in obs503]}")

        measured = N_SEQ + 2 + N_TAIL + len(burst_results)
        ok_total = seq_ok + param_ok + burst_ok + tail_ok
        print(f"[summary] ok={ok_total}/{measured} measured probes "
              f"(seq {seq_ok}/{N_SEQ}, param {param_ok}/2, burst "
              f"{burst_ok}/{len(burst_results)}, tail {tail_ok}/{N_TAIL})")
        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("liveness-face verification complete: every probe returned "
              "HTTP 200 (healthy-state 200 semantics held across sequential, "
              "parameterized, concurrent and post-burst probes); no "
              "spec-violating status, no reproducible transport loss — "
              "NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # read-only face — no collections, no aliases, nothing to tear down;
        # the trailing healthz probe below is informational only and must
        # never flip the verdict (cleanup discipline: no drops needed here)
        try:
            hs, hraw = safe_request("GET", "healthz", timeout=10)
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
