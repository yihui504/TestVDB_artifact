# Attack: batch delete timestamp semantics (novel candidate)
# DELETE /batch/objects response field deletionTimeUnixMilli observed as -62135596800000,
# the Go zero-time sentinel (0001-01-01). A field named "deletion time (unix ms)" must reflect
# wall-clock deletion time, not a zero value. Type4/Type2.
import os, sys, time, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/")
S = requests.Session()

CLS = "TSemDelTime04"
try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass
S.post(f"{BASE}/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "cat", "dataType": ["string"]}]})
for i in (1, 2):
    S.post(f"{BASE}/v1/objects", json={"class": CLS,
        "id": f"{i:08d}-0000-0000-0000-{i:012d}", "properties": {"cat": "x"}})

before_ms = int(time.time() * 1000)
r = S.delete(f"{BASE}/v1/batch/objects", json={
    "match": {"class": CLS, "where": {"operator": "Equal", "path": ["cat"], "valueText": "x"}},
    "output": "minimal"})
after_ms = int(time.time() * 1000)
print("status:", r.status_code)
body = r.json()
dt = body.get("deletionTimeUnixMilli")
print(f"deletionTimeUnixMilli={dt}  plausible window=[{before_ms}, {after_ms}]")

defect = None
if not isinstance(dt, (int, float)):
    defect = f"deletionTimeUnixMilli not numeric: {dt!r}"
elif not (before_ms - 60000 <= dt <= after_ms + 60000):
    defect = (f"deletionTimeUnixMilli={dt} is not a plausible wall-clock deletion time "
              f"(window ~{before_ms}); it is the Go zero-time sentinel "
              f"(-62135596800000 = 0001-01-01T00:00:00Z), a misleading timestamp in a public API field")

try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass

if defect:
    print("VERDICT: DEFECT_FOUND")
    print("DEFECT:", defect)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
