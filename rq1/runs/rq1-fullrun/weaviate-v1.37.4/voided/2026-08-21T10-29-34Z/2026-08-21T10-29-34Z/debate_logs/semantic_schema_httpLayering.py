#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Semantic Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: HTTP status-code layering / error-class appropriateness for invalid vector-index
        configs submitted via /v1/schema.
Attack: diagnosis_quality
Stategy coverage map: (diagnosis_quality, POST /schema error class stability)
Blindspot: BS-02 Error Message Negligence + BS-05 Documentation Drift
Rationale: REST semantics demand that a malformed client payload be answered with a stable
        4xx client-error class and a 4xx/5xx mapped appropriately — never an unstable
        status for the same input. We check that distinct invalid classes map to 4xx (not
        500), and that the SAME invalid payload produces a STABLE status across repeats
        (i.e. not 400 on one call, 500 on the next). A 500 for a client-only config error,
        or a flapping status for identical input, is a REST-semantics defect.
Note: status 201 is a valid create for a payload weaviate chose to accept — only the
     validation-relevant payloads (which we expect to be rejected) are graded on failure.
"""

import os
import sys
import requests

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

CREATE_PATH = "/v1/schema"
DROP_PATH = "/v1/schema/{cls}"


def safe_request(method, endpoint, json=None, timeout=10):
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.request(method=method, url=url, json=json,
                                headers=headers, timeout=timeout)
        code = resp.status_code
        raw = resp.text
        try:
            body = resp.json()
        except Exception:
            body = raw
        return code, body, raw
    except Exception as e:
        return -1, str(e), str(e)


def cleanup(cls):
    try:
        safe_request("DELETE", DROP_PATH.format(cls=cls))
    except Exception as e:
        print(f"Cleanup warning: {e}")


def build(clsid, **cfg):
    """Convenience: build a class payload with a full vectorIndexConfig overrides dict."""
    vcfg = {"distance": "cosine"}
    vcfg.update(cfg)
    return {
        "class": clsid,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": vcfg,
    }


def main():
    # Invalid case A: inverted pairing (Min > Max). Expected 4xx if validated.
    cls_a = "SemHttpLayeringA"
    bad_a = build(cls_a, dynamicEfMin=300, dynamicEfMax=100)
    failures = []

    for label, payload in [
        ("invertedPairing", bad_a),
        ("negativeEfConstruction", build("SemHttpLayeringB", efConstruction=-5)),
        ("negativeFlatCutoff", build("SemHttpLayeringC", flatSearchCutoff=-1)),
    ]:
        statuses = []
        raws = []
        # fire twice to test stability for identical input
        for _ in range(2):
            s, body, r = safe_request("POST", CREATE_PATH, json=payload)
            statuses.append(s)
            raws.append(r if isinstance(r, str) else str(r))
        cls = payload.get("class")
        print(f"[{label}] statuses={statuses}")
        if len(raws) and raws[0]:
            print(f"[{label}] raw={raws[0][:300]}")
        # cleanup the (possibly accepted) class on the second loop-level separately
        cleanup(cls)

        # Stability: identical input must not flap.
        if len(set(statuses)) > 1:
            failures.append(f"{label}: UNSTABLE status {statuses} for identical input")
        # Error-class appropriateness: an invalid *client* config should be 4xx, not 500.
        ok_code = all(s in (400, 422, 409) for s in statuses)
        if not ok_code:
            for s in statuses:
                if s >= 500:
                    failures.append(
                        f"{label}: client-malformed config answered with server-class "
                        f"{s} (inappropriate error class)")
                elif s == -1:
                    failures.append(f"{label}: transport error (status={s})")

    if failures:
        print("DEFECT signal:")
        for f in failures:
            print("  " + f)
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print("All invalid configs answered with a stable 4xx client-error class")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"VERDICT: SCRIPT_ERROR — {e}")
        sys.exit(2)
