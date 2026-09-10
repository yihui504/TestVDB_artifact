"""Vein: flatSearchCutoff negative + ef below dynamicEfMin linkage.

Discover: flatSearchCutoff=-50000 accepted (200) and persisted verbatim.
flatSearchCutoff is the HNSW-exit threshold (search flat instead of HNSW
when segment smaller than cutoff). Negative value makes the condition
always-false / inverted vs the documented "> cutoff" semantics.
Deepen: ef=10 with dynamicEfMin=500/dynamicEfMax=600 — ef far below the
declared dynamic floor is also accepted, no cross-check ef vs dynamicEfMin.
Control: flatSearchCutoff=40000 (default) stores fine.
VERDICT: DEFECT_FOUND if negative cutoff persisted with 200.
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
    cls = "VeinFlatCut2"
    safe_request("DELETE", f"/v1/schema/{cls}")
    findings = []

    st, _ = safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "vectorIndexConfig": {"flatSearchCutoff": -50000}})
    st2, rb = safe_request("GET", f"/v1/schema/{cls}")
    v = json.loads(rb)["vectorIndexConfig"]
    if st == 200 and st2 == 200 and v["flatSearchCutoff"] < 0:
        findings.append(f"negative flatSearchCutoff={v['flatSearchCutoff']} persisted with HTTP 200")
    # control: default value path
    safe_request("DELETE", f"/v1/schema/{cls}")
    safe_request("POST", "/v1/schema", {"class": cls, "vectorizer": "none"})
    _, rbc = safe_request("GET", f"/v1/schema/{cls}")
    vc = json.loads(rbc)["vectorIndexConfig"]
    assert vc["flatSearchCutoff"] == 40000
    findings.append(f"control: default 40000 untouched ({vc['flatSearchCutoff']}) => not a readback artifact")

    # deepen: ef << dynamicEfMin
    safe_request("DELETE", f"/v1/schema/{cls}")
    st3, _ = safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "vectorIndexConfig": {"ef": 10, "dynamicEfMin": 500, "dynamicEfMax": 600}})
    _, rb3 = safe_request("GET", f"/v1/schema/{cls}")
    v3 = json.loads(rb3)["vectorIndexConfig"]
    if st3 == 200 and v3["ef"] < v3["dynamicEfMin"]:
        findings.append(f"ef={v3['ef']} below dynamicEfMin={v3['dynamicEfMin']} accepted without cross-check")

    safe_request("DELETE", f"/v1/schema/{cls}")
    for f in findings:
        print("FINDING:", f)
    print("VERDICT: DEFECT_FOUND" if findings else "VERDICT: NOT_FOUND")


try:
    main()
except Exception as e:
    print("SCRIPT_ERROR:", e)
