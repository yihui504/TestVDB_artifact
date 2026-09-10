"""Vein: phantom class left behind after failed create (shardingConfig).

Discover: POST /v1/schema with shardingConfig {virtualPerPhysical:0,
desiredCount:0} returns 422 ("physical shards unavailable") but the class
IS registered in the schema — GET /v1/schema/{class} returns 200 with
actualCount=0. The failed creation is not rolled back.
Deepen: writing an object into the phantom class returns HTTP 500
"import into non-existing index" — the class exists for schema reads but
has no backing index, leaving the DB in an inconsistent state that the
user cannot distinguish from a usable class.
Control: desiredCount=1 create succeeds normally (200, usable).
VERDICT: DEFECT_FOUND if 422 create leaves GET-reachable class.
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
    cls = "VeinGhost4"
    findings = []
    safe_request("DELETE", f"/v1/schema/{cls}")

    # attack: invalid sharding -> 422 but class persists
    st, body = safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "shardingConfig": {"virtualPerPhysical": 0, "desiredCount": 0}})
    st2, rb = safe_request("GET", f"/v1/schema/{cls}")
    if st == 422 and st2 == 200:
        sc = json.loads(rb).get("shardingConfig", {})
        findings.append(
            f"create returned 422 yet class persists in schema (GET 200, shardingConfig={sc}) — no rollback")
        # deepen: phantom class is not usable — writes 500
        st3, body3 = safe_request("POST", "/v1/objects", {
            "class": cls, "id": "22222222-2222-2222-2222-222222222222"})
        if st3 == 500:
            findings.append(f"write into phantom class -> HTTP 500 ({body3[:120]})")
    # control: valid sharding works
    safe_request("DELETE", f"/v1/schema/{cls}")
    stc, _ = safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none", "shardingConfig": {"desiredCount": 1}})
    stc2, rbc = safe_request("GET", f"/v1/schema/{cls}")
    assert stc == 200 and stc2 == 200, "control must succeed"
    findings.append("control: desiredCount=1 create+readback OK => failure path uniquely leaks state")

    safe_request("DELETE", f"/v1/schema/{cls}")
    for f in findings:
        print("FINDING:", f)
    print("VERDICT: DEFECT_FOUND" if findings else "VERDICT: NOT_FOUND")


try:
    main()
except Exception as e:
    print("SCRIPT_ERROR:", e)
