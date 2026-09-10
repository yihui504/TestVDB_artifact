# state: concurrent fieldOps ARRAY_APPEND on same pk — lost update / corruption
# Attack: strategy 4 (concurrent) x milvus_state_entities_upsert_fieldops_001
# Blindspot: BS-03 Concurrency Blindness
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (safe_request, code_of, create_collection, load_collection,
                  drop_collection, query_all, unwrap_array_field)

CLS = "st_fo_conc_001"
T = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "8"))
verdict, detail = "NO_DEFECT", ""
try:
    drop_collection(CLS)
    create_collection(CLS)
    load_collection(CLS)
    print("insert:", safe_request("POST", "entities+insert", {"collectionName": CLS, "data": [
        {"id": 1, "vector": [0.1] * 8, "tags": ["a"]} ]})[2])

    errors, codes = [], []
    lock = threading.Lock()

    def worker(i):
        for _ in range(5):
            s, b, raw = safe_request("POST", "entities+upsert", {
                "collectionName": CLS,
                "data": [{"id": 1, "vector": [0.1] * 8, "tags": ["t%d" % i]}],
                "fieldOps": [{"fieldName": "tags", "op": "ARRAY_APPEND"}]})
            c = code_of(b)
            with lock:
                codes.append(c)
                if c != 0:
                    errors.append((c, raw[:200]))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(T)]
    for t in threads: t.start()
    for t in threads: t.join()
    time.sleep(2)

    expected = 1 + T * 5
    s, b, raw = query_all(CLS, output_fields=["tags"])
    print("query:", raw)
    rows = (b or {}).get("data") or []
    if rows:
        tags = unwrap_array_field(rows[0].get("tags", []))
        if len(tags) != expected:
            verdict = "DEFECT_FOUND"
            detail = "lost updates: tags len=%d expected=%d; op codes=%s" % (
                len(tags), expected, sorted(set(codes)))
    else:
        verdict, detail = "SCRIPT_ERROR", "query empty"
    if errors:
        print("op errors count", len(errors), errors[:3])
except Exception as e:
    verdict, detail = "SCRIPT_ERROR", str(e)
finally:
    drop_collection(CLS)
print(detail)
print("VERDICT: %s" % verdict)
