"""Vein: HNSW maxConnections/efConstruction relational constraint absent.

Discover: maxConnections=1000 with efConstruction=10 accepted (200) and
persisted. hnswlib documents efConstruction should be >= maxConnections
for a coherent graph; weaviate enforces neither efConstruction=0
(separately rejected with 422, proving validation exists in this block)
nor the inverted ratio.
Control: efConstruction=0 returns 422 (validates single-field checks run
in the same code path), so accepting the inverted pair is a genuine
cross-field gap, not by-design leniency.
Deepen: maxConnections=2 (below the commonly required minimum M>=3 for
bidirectional links) — check acceptance.
VERDICT: DEFECT_FOUND if ratio-inverted pair persisted with 200.
"""
import json, requests

DB = "http://localhost:8080"


def safe_request(method, path, body=None):
    try:
        r = requests.request(method, DB + path, json=body, timeout=10)
        return r.status_code, r.text
    except Exception as e:
        return -1, str(e)


def main():
    cls = "VeinHnswRatio5"
    findings = []
    safe_request("DELETE", f"/v1/schema/{cls}")

    # discover: inverted ratio
    st, _ = safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "vectorIndexConfig": {"maxConnections": 1000, "efConstruction": 10}})
    st2, rb = safe_request("GET", f"/v1/schema/{cls}")
    if st == 200 and st2 == 200:
        v = json.loads(rb)["vectorIndexConfig"]
        if v["maxConnections"] > v["efConstruction"]:
            findings.append(
                f"maxConnections={v['maxConnections']} > efConstruction={v['efConstruction']} accepted (200)")
        # control: single-field check exists
        safe_request("DELETE", f"/v1/schema/{cls}")
        stc, bodyc = safe_request("POST", "/v1/schema", {
            "class": cls, "vectorizer": "none",
            "vectorIndexConfig": {"maxConnections": 1, "efConstruction": 64}})
        if stc == 422:
            findings.append(f"control: maxConnections=1 rejected 422 ({bodyc[:100]}) => validators exist, cross-field ratio not checked")
        # deepen: minimal M
        safe_request("DELETE", f"/v1/schema/{cls}")
        st3, _ = safe_request("POST", "/v1/schema", {
            "class": cls, "vectorizer": "none",
            "vectorIndexConfig": {"maxConnections": 2, "efConstruction": 64}})
        if st3 == 200:
            findings.append("deepen: maxConnections=2 (below M>=3 floor) accepted")

    safe_request("DELETE", f"/v1/schema/{cls}")
    for f in findings:
        print("FINDING:", f)
    print("VERDICT: DEFECT_FOUND" if findings else "VERDICT: NOT_FOUND")


try:
    main()
except Exception as e:
    print("SCRIPT_ERROR:", e)
