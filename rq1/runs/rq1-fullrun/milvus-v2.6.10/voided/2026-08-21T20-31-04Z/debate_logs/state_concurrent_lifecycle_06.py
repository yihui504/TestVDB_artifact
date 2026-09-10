# state_concurrent_lifecycle_06.py
# Attack: collection lifecycle (drop/recreate) racing concurrent insert/search/query (strategy 7, mode C)
# Covers: collections+drop / collections+create / collections+load / entities+insert / entities+search / entities+query
# Defect signal: generic code 65535 / HTTP 500 / panic on access during lifecycle race (graceful = 100/101)
# Blindspot: BS-03 Concurrency Blindness
import os, sys, time, threading, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
CLS = "stt_race_06"; DIM = 4
N_THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
errors_65535 = []   # generic unexpected errors
errors_http5 = []

def safe_request(method, path, payload=None):
    try:
        r = requests.request(method, f"{BASE_URL}/v2/vectordb/{path}", headers=H, json=payload or {}, timeout=60)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, f"EXC:{e}"

def ok(b): return b is not None and b.get("code") == 0

def lifecycle_worker(stop):
    # continuously drop -> create -> load the same collection name
    while not stop.is_set():
        s, b, raw = safe_request("POST", "collections/drop", {"collectionName": CLS})
        if s >= 500: errors_http5.append(("drop", s, raw[:100]))
        time.sleep(0.1)
        s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
        if s >= 500: errors_http5.append(("create", s, raw[:100]))
        elif not ok(b):
            code = (b or {}).get("code")
            if code == 65535: errors_65535.append(("create", code, (b.get('message') or '')[:100]))
        time.sleep(0.1)
        safe_request("POST", "collections/load", {"collectionName": CLS})
        time.sleep(0.2)

def access_worker(stop, wid):
    while not stop.is_set():
        # insert
        s, b, raw = safe_request("POST", "entities/insert",
            {"collectionName": CLS, "data": [{"id": wid*100000 + int(time.time()*1000) % 99999,
                                              "vector": [0.1]*DIM}]})
        if s >= 500: errors_http5.append(("insert", s, raw[:100]))
        elif b is not None and b.get("code") == 65535:
            errors_65535.append(("insert", b.get("code"), (b.get('message') or '')[:150]))
        # search
        s, b, raw = safe_request("POST", "entities/search",
            {"collectionName": CLS, "data": [[0.1]*DIM], "limit": 1})
        if s >= 500: errors_http5.append(("search", s, raw[:100]))
        elif b is not None and b.get("code") == 65535:
            errors_65535.append(("search", b.get("code"), (b.get('message') or '')[:150]))
        # query
        s, b, raw = safe_request("POST", "entities/query",
            {"collectionName": CLS, "filter": "id >= 0", "limit": 1})
        if s >= 500: errors_http5.append(("query", s, raw[:100]))
        elif b is not None and b.get("code") == 65535:
            errors_65535.append(("query", b.get("code"), (b.get('message') or '')[:150]))
        time.sleep(0.05)

def final_verdict():
    # tolerate 100/101/102 (not exist / not loaded / rate) — those are graceful race outcomes
    if errors_http5:
        print(f"DEFECT: HTTP 5xx during lifecycle race: {errors_http5[:5]}")
        print("VERDICT: DEFECT_FOUND"); sys.exit(1)
    # only count distinct message shapes to avoid single-race flakiness; require >=2 occurrences
    from collections import Counter
    shapes = Counter((op, msg[:60]) for op, c, msg in errors_65535)
    serious = {k: v for k, v in shapes.items() if v >= 2}
    if serious:
        print(f"DEFECT: repeated generic 65535 during lifecycle race (>=2x): {serious}")
        print("VERDICT: DEFECT_FOUND"); sys.exit(1)
    if errors_65535:
        print(f"NOTE: single-occurrence 65535 observed (not confirmed): {errors_65535[:3]}")
    print("VERDICT: NO_DEFECT"); sys.exit(0)

try:
    safe_request("POST", "collections/drop", {"collectionName": CLS})
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": DIM})
    if not ok(b): print(raw); print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    safe_request("POST", "collections/load", {"collectionName": CLS})
    time.sleep(3)

    stop = threading.Event()
    lt = threading.Thread(target=lifecycle_worker, args=(stop,))
    ats = [threading.Thread(target=access_worker, args=(stop, i)) for i in range(min(N_THREADS, 6))]
    lt.start()
    for t in ats: t.start()
    time.sleep(25)  # race window
    stop.set()
    lt.join(); [t.join() for t in ats]

    print(f"http5={len(errors_http5)} code65535={len(errors_65535)}")
    for e in errors_65535[:8]: print(f"  65535: {e}")
    for e in errors_http5[:8]: print(f"  5xx: {e}")

    final_verdict()
finally:
    try: safe_request("POST", "collections/drop", {"collectionName": CLS})
    except Exception: pass
