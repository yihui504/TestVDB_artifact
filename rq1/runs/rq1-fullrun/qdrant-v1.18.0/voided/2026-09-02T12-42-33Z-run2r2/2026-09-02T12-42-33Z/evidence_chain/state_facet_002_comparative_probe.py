#!/usr/bin/env python3
# Comparative-forensics probe for evidence chain state_facet_002.
# Primary observation (from output_state_facet_002.log leg E):
#   after delete_points(filter city=C, wait=true), facet {key: city, exact: true}
#   returned 200 hits [{A:175},{B:100},{C:0}] — a stale zero-count value.
# Same-family face: the facet `exact` toggle (exact=false -> approximate path,
# which filters count>0 at segment level per read_view/facet.rs:115,125).
# This probe replays the scenario on a unique collection and records both faces.
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:6333"


def req(method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, raw
    except Exception as e:
        return 0, str(e)[:120]


PFX = "sf2cp_" + str(int(time.time())) + "_"
C = PFX + "col"

try:
    s, raw = req("PUT", f"/collections/{C}",
                 {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"[create] status={s} raw={raw[:120]}")
    s, raw = req("PUT", f"/collections/{C}/index?wait=true",
                 {"field_name": "city", "field_schema": {"type": "keyword"}})
    print(f"[index city] status={s} raw={raw[:120]}")
    pts = []
    for i, (city, n) in enumerate((("A", 2), ("B", 2), ("C", 1)), start=1):
        for _ in range(n):
            pts.append({"id": i, "vector": [0.1, 0.2, 0.3, 0.4],
                        "payload": {"city": city}})
            i += 1000  # keep ids unique per point instance
    s, raw = req("PUT", f"/collections/{C}/points?wait=true", {"points": pts})
    print(f"[upsert] status={s} raw={raw[:120]}")
    s, raw = req("POST", f"/collections/{C}/facet",
                 {"key": "city", "exact": True})
    print(f"[pre-delete exact=true] status={s} raw={raw[:220]}")
    s, raw = req("POST", f"/collections/{C}/points/delete?wait=true",
                 {"filter": {"must": [{"key": "city", "match": {"value": "C"}}]}})
    print(f"[delete city=C] status={s} raw={raw[:120]}")
    s, raw = req("POST", f"/collections/{C}/facet",
                 {"key": "city", "exact": True})
    print(f"[post-delete exact=true] status={s} raw={raw[:220]}")
    s, raw = req("POST", f"/collections/{C}/facet",
                 {"key": "city", "exact": False})
    print(f"[post-delete exact=false] status={s} raw={raw[:220]}")
    s, raw = req("POST", f"/collections/{C}/points/count",
                 {"exact": True})
    print(f"[post-delete count face] status={s} raw={raw[:160]}")
finally:
    try:
        s, raw = req("DELETE", f"/collections/{C}")
        print(f"[drop] status={s} raw={raw[:80]}")
    except Exception:
        pass
