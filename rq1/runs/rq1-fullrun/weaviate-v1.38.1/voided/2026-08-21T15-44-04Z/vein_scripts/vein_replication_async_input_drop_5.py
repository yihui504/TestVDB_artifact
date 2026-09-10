"""Vein: replicationConfig.asyncEnabled input silently ignored (state drift).

Discover: POST /v1/schema with replicationConfig.asyncEnabled=true and
factor=1 returns 200, but GET /v1/schema/{class} readback reports
asyncEnabled=false. The input field is never consumed: it is a REST output
shim derived at read time as factor>1 && !globallyDisabled
(.weaviate-src-1381/adapters/handlers/rest/restcompat/wrappers.go:40
wrapReplicationConfig). The user sets asyncEnabled=true explicitly and gets
false back with no error and no warning.

Control: any other replicationConfig misconfiguration (factor=2 on a
1-node cluster) IS validated loudly with 422.
"""
import json
import urllib.request

BASE = "http://localhost:8080"


def safe_request(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"raw": raw}


def main():
    verdict = "NO_DEFECT"
    cls = "VeinAsyncDrop"
    try:
        safe_request("DELETE", "/v1/schema/" + cls)
    except Exception:
        pass

    s, _ = safe_request("POST", "/v1/schema", {
        "class": cls,
        "replicationConfig": {"factor": 1, "asyncEnabled": True},
    })
    gs, g = safe_request("GET", "/v1/schema/" + cls)
    rc = g.get("replicationConfig", {})
    print("create status=%s readback replicationConfig=%s" % (
        s, json.dumps(rc)))

    # control: invalid factor is loudly rejected
    s2, r2 = safe_request("POST", "/v1/schema", {
        "class": cls + "Ctl",
        "replicationConfig": {"factor": 2},
    })
    print("control factor=2: status=%s err=%s" % (
        s2, json.dumps(r2)[:120]))

    if (s == 200 and rc.get("asyncEnabled") is False
            and rc.get("factor") == 1 and s2 == 422):
        verdict = "DEFECT_FOUND"

    for c in (cls, cls + "Ctl"):
        try:
            safe_request("DELETE", "/v1/schema/" + c)
        except Exception:
            pass
    print("VERDICT: " + verdict)


if __name__ == "__main__":
    main()
