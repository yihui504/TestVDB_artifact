#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-6 (state_collections_delete_004): HTTP 500 on
points/query and points+upsert during collection delete/recreate lifecycle
race (no 404 mapping, timing-dependent).

Defect: while thread A loops DELETE -> PUT recreate on a collection, 10
concurrent access threads running query/count/upsert receive 500
"Service internal error: Expected at least one response for one query"
(query) and 500 "Failed to apply operation to at least one `Active`
replica" (upsert). Expected per contract semantics: 200 or 404, never 5xx.
Census >= 2 events confirms (avoids single-race false positive).

Source: defects/defect-6.md; log output_state_collections_delete_004.log
(16 events observed on v1.18.0).
"""
import os, sys, json, time, threading, random
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

COLL = "mre_q6_lc"
DIM = 4
CYCLES = 8
ITERS = 40
N_ACCESS = 10

error_events = []
lock = threading.Lock()


def safe_request(method, path, **kwargs):
    try:
        resp = requests.request(method, f"{DB_URL}{path}", timeout=30,
                                headers=HEADERS, **kwargs)
        try:
            body = resp.json() if resp.text else {}
        except Exception:
            body = resp.text
        return resp.status_code, body
    except Exception as e:
        return 0, str(e)


def note_error(kind, status, raw):
    with lock:
        error_events.append((kind, status, (raw or "")[:160]))


def lifecycle_thread():
    for _ in range(CYCLES):
        st, raw = safe_request("DELETE", f"/collections/{COLL}")
        if isinstance(raw, dict):
            raw = json.dumps(raw)
        if st >= 500 or st == 0:
            note_error("lifecycle_delete", st, raw)
        time.sleep(0.05)
        st, raw = safe_request("PUT", f"/collections/{COLL}",
                               json={"vectors": {"size": DIM, "distance": "Cosine"}})
        if isinstance(raw, dict):
            raw = json.dumps(raw)
        if st >= 500 or st == 0:
            note_error("lifecycle_create", st, raw)
        time.sleep(0.05)


def access_thread(tid):
    for i in range(ITERS):
        st, raw = safe_request("POST", f"/collections/{COLL}/points/query",
                               json={"query": [0.1] * DIM, "limit": 3})
        if isinstance(raw, dict):
            raw = json.dumps(raw)
        if st >= 500 or st == 0:
            note_error(f"query[t{tid}]", st, raw)
        st, raw = safe_request("POST", f"/collections/{COLL}/points/count",
                               json={"exact": True})
        if isinstance(raw, dict):
            raw = json.dumps(raw)
        if st >= 500 or st == 0:
            note_error(f"count[t{tid}]", st, raw)
        if i % 2 == 0:
            pts = [{"id": tid * 1000 + i, "vector": [0.1] * DIM}]
            st, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
                                   json={"points": pts})
            if isinstance(raw, dict):
                raw = json.dumps(raw)
            if st >= 500 or st == 0:
                note_error(f"upsert[t{tid}]", st, raw)
        time.sleep(0.03)


def reproduce():
    random.seed(6)
    # Step 1: setup - clean slate, initial create, seed 20 points
    safe_request("DELETE", f"/collections/{COLL}")
    time.sleep(0.3)
    st, raw = safe_request("PUT", f"/collections/{COLL}",
                           json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"initial create: {st}")
    if st not in (200, 201):
        print(f"Body: {raw}")
        print("\nVERDICT: NOT_REPRODUCED (setup failed - is the DB running?)")
        return False
    seed = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in range(20)]
    st, _ = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
                         json={"points": seed})
    print(f"seed upsert: {st}")

    # Step 2: trigger - lifecycle race (8 delete/recreate cycles vs 10 access threads)
    threads = [threading.Thread(target=lifecycle_thread)]
    for tid in range(N_ACCESS):
        threads.append(threading.Thread(target=access_thread, args=(tid,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(1)

    # Step 3: census and post-race health check
    print(f"ERROR_CENSUS: {len(error_events)} events (threshold for DEFECT: 2)")
    for ev in error_events[:20]:
        print(f"  error_event: {ev}")

    safe_request("DELETE", f"/collections/{COLL}")
    time.sleep(0.3)
    st, _ = safe_request("PUT", f"/collections/{COLL}",
                         json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"post-race recreate: {st}")
    pts = [{"id": i, "vector": [0.05 * (i + 1)] * DIM} for i in range(25)]
    st, _ = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
                         json={"points": pts})
    print(f"post-race upsert: {st}")
    time.sleep(0.5)
    st, body = safe_request("POST", f"/collections/{COLL}/points/count",
                            json={"exact": True})
    print(f"post-race count: {st} {body}")

    # Verify: >= 2 events of 5xx/transport failure on access calls during the race
    reproduced = len(error_events) >= 2
    if reproduced:
        print("\nVERDICT: DEFECT_REPRODUCED")
    else:
        print("\nVERDICT: NOT_REPRODUCED (0-1 events; race window is "
              "timing-dependent - rerun if 1 event)")
    return reproduced


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except Exception:
            pass
