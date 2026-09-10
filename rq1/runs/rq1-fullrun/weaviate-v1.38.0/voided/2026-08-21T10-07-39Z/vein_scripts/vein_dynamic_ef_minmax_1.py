"""Vein: dynamicEfMin/dynamicEfMax cross-field constraint (HNSW dynamic ef).

Discover: POST /v1/schema accepts dynamicEfMin=500 > dynamicEfMax=100 (and
negative values) with 200 and persists them verbatim. Control case with
min<max behaves identically => no normalization; cross-field invariant
Min <= Max is never enforced anywhere.
Deepen: same via PUT /v1/schema/{class} update path; and ef=10 << dynamicEfMin=500.
Expected defect: Type2 - invalid config silently persisted; search-time ef
clamping semantics become inverted (max < min).
VERDICT: DEFECT_FOUND if readback shows dynamicEfMin > dynamicEfMax (200).
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
    cls = "VeinDynEf1"
    safe_request("DELETE", f"/v1/schema/{cls}")
    findings = []

    # discover: min > max
    st, body = safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "vectorIndexConfig": {"ef": 128, "dynamicEfMin": 500, "dynamicEfMax": 100}})
    st2, rb = safe_request("GET", f"/v1/schema/{cls}")
    v = json.loads(rb).get("vectorIndexConfig", {})
    if st == 200 and st2 == 200 and v.get("dynamicEfMin", 0) > v.get("dynamicEfMax", 0):
        findings.append(f"POST accepted dynamicEfMin={v['dynamicEfMin']} > dynamicEfMax={v['dynamicEfMax']}")

    # control: valid min < max
    stc, _ = safe_request("DELETE", f"/v1/schema/{cls}")
    safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "vectorIndexConfig": {"dynamicEfMin": 50, "dynamicEfMax": 500}})
    stc2, rbc = safe_request("GET", f"/v1/schema/{cls}")
    vc = json.loads(rbc)["vectorIndexConfig"]
    assert vc["dynamicEfMin"] < vc["dynamicEfMax"], "control must be valid"
    findings.append(f"control min<max stored verbatim ({vc['dynamicEfMin']},{vc['dynamicEfMax']}) => no normalization either way")

    # deepen: PUT update path to inverted values
    st3, _ = safe_request("PUT", f"/v1/schema/{cls}", {
        "class": cls, "vectorizer": "none",
        "vectorIndexConfig": {"dynamicEfMin": 9999, "dynamicEfMax": 1}})
    st4, rb4 = safe_request("GET", f"/v1/schema/{cls}")
    v4 = json.loads(rb4)["vectorIndexConfig"]
    if st3 == 200 and st4 == 200 and v4["dynamicEfMin"] > v4["dynamicEfMax"]:
        findings.append(f"PUT update also accepts inverted ({v4['dynamicEfMin']},{v4['dynamicEfMax']})")

    # deepen: negative
    safe_request("DELETE", f"/v1/schema/{cls}")
    safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "vectorIndexConfig": {"dynamicEfMin": -100, "dynamicEfMax": -50}})
    st5, rb5 = safe_request("GET", f"/v1/schema/{cls}")
    v5 = json.loads(rb5)["vectorIndexConfig"]
    if v5["dynamicEfMin"] < 0:
        findings.append(f"negative values persisted ({v5['dynamicEfMin']},{v5['dynamicEfMax']})")

    safe_request("DELETE", f"/v1/schema/{cls}")
    for f in findings:
        print("FINDING:", f)
    print("VERDICT: DEFECT_FOUND" if findings else "VERDICT: NOT_FOUND")


try:
    main()
except Exception as e:
    print("SCRIPT_ERROR:", e)
