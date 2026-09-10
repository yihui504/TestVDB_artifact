#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input fuzzing on aliases+list (raw-body malformation: truncated JSON / trailing comma / single quotes / comment body / bare NUL bytes / escaped lone surrogate / 1MB overlong string; plus URL-crafted %00 and UTF-8-encoded lone surrogate in the query) × qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases)
Oracle: for every malformed probe GET /aliases answers 200 with the documented envelope intact (result.aliases array present, prefix-owned alias still listed) or a 4xx with non-empty diagnostics — never 5xx/panic (5xx = Type3_RuntimeFailure); a 200 whose envelope lost result.aliases = Type4_StateLogicViolation; after all probes one clean GET /aliases must still return 200 with the alias listed, and a transport failure only counts as Type3 if the /healthz liveness re-check also fails (constraint qdrant_behavioral_aliases_list_001)
Constraint: qdrant_behavioral_aliases_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name} across all collections")
Blindspot: BS-01 Parameter Coercion Trust / serde layer robustness (parser is trusted to receive well-formed input streams)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Raw bytes go through data= (never json=) so client-side serialization
cannot pre-reject the malformed input; URL-crafted probes bypass params=
re-encoding. R1 lesson applied: envelope nests at result.aliases.
"""

import json
import os
import sys
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, params=params,
            data=data, headers=headers, timeout=timeout,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def parse_alias_envelope(raw):
    """Parse a GET /aliases 200 envelope per contract response_shape
    (list nested at result.aliases). Returns (aliases_list, err)."""
    try:
        b = json.loads(raw) if raw else None
    except Exception:
        return None, "non_json"
    if not isinstance(b, dict):
        return None, "non_json"
    if "result" not in b:
        return None, "no_result"
    r = b["result"]
    if not isinstance(r, dict):
        return None, "bad_result_type"
    if "aliases" not in r:
        return None, "no_aliases"
    a = r["aliases"]
    if not isinstance(a, list):
        return None, "bad_aliases_type"
    return a, None


def find_alias(entries, alias_name):
    for e in entries:
        if isinstance(e, dict) and e.get("alias_name") == alias_name:
            return e
    return None


def liveness():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs, hraw


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def delete_alias(name):
    try:
        safe_request("POST", "/collections/aliases", params={"timeout": 60},
                     json={"actions": [{"delete_alias": {"alias_name": name}}]}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bal3" + tag
    coll = pfx + "c1"
    alias = pfx + "a1"
    print(f"ownership prefix: {pfx} (collection={coll}, alias={alias})")

    # Arrange: existing collection + alias so the listed envelope is populated
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201, 409):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                             json={"actions": [{"create_alias": {
                                 "collection_name": coll, "alias_name": alias}}]}, timeout=60)
    print(f"create alias status={s} raw={raw[:300]}")
    if s != 200:
        print("VERDICT: SCRIPT_ERROR — alias setup failed, no defect conclusion")
        return

    try:
        # Baseline (clean GET must list our alias before we start corrupting inputs)
        s0, _, raw0 = safe_request("GET", "/aliases", timeout=30)
        if s0 <= 0:
            hs, hraw = liveness()
            print(f"transport failure on baseline GET (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s0 != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — baseline GET /aliases "
                  f"returned {s0} (promise: 200 with list)")
            return
        entries0, err0 = parse_alias_envelope(raw0)
        if err0 == "non_json":
            print(f"VERDICT: SCRIPT_ERROR — 200 but body not usable JSON: {raw0[:300]}")
            return
        if err0 is not None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — baseline envelope "
                  f"violates response_shape ({err0})")
            return
        if find_alias(entries0, alias) is None:
            print("VERDICT: SCRIPT_ERROR — baseline list lacks our alias; setup inconsistent")
            return
        print(f"OK: baseline lists {alias} -> {coll}")

        # Act: malformed raw-body probes (data= keeps client serialization out of the way)
        body_probes = [
            ("truncated-json", b'{"collection_name": "x"'),
            ("trailing-comma", b'{"collection_name": "x",}'),
            ("single-quotes", b"{'collection_name': 'x'}"),
            ("comment-body", b'// comment\n{"a": 1}'),
            ("bare-nul-bytes", b"\x00\x01\x02\x03"),
            ("escaped-lone-surrogate", b'{"x": "\\ud800"}'),
            ("overlong-1mb-string", b'{"x": "' + b"a" * 1000000 + b'"}'),
        ]
        # URL-crafted probes (pre-encoded; bypass params= re-encoding)
        url_probes = [
            ("url-utf8-lone-surrogate", "/aliases?collection_name=%ED%A0%80"),
            ("url-nul-percent00", "/aliases?collection_name=a%00b"),
        ]

        def judge(label, s, raw):
            """Expected: 200 with intact envelope or 4xx with diagnostics; never 5xx."""
            if s <= 0:
                hs, hraw = liveness()
                print(f"  transport failure on {label} (healthz status={hs}: {str(hraw)[:200]})")
                if hs == 200:
                    print("VERDICT: SCRIPT_ERROR — transport flake (healthz alive), no defect conclusion")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — malformed input "
                          f"[{label}] crashed the service (healthz also down)")
                return False
            if 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — malformed input "
                      f"[{label}] triggered {s}: {raw[:200]}")
                return False
            if 400 <= s <= 499:
                if not raw.strip():
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — [{label}] "
                          f"rejected with {s} but empty diagnostic body")
                    return False
                print(f"  OK: [{label}] rejected {s} with non-empty diagnostics")
                return True
            if s != 200:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — [{label}] returned "
                      f"unexpected status {s}")
                return False
            entries, err = parse_alias_envelope(raw)
            if err == "non_json":
                print(f"VERDICT: SCRIPT_ERROR — 200 after [{label}] but body not usable "
                      f"JSON: {raw[:300]}")
                return False
            if err is not None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 after "
                      f"[{label}] with corrupted envelope ({err}); promise: result.aliases "
                      f"array of {{alias, collection_name}}")
                return False
            if find_alias(entries, alias) is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 after "
                      f"[{label}] but prefix-owned alias {alias} vanished from the list")
                return False
            print(f"  OK: [{label}] -> 200, envelope intact, alias still listed")
            return True

        for label, payload in body_probes:
            s, _, raw = safe_request("GET", "/aliases", data=payload, timeout=30)
            print(f"probe[{label}] len={len(payload)} -> status={s}")
            print(f"  raw: {raw[:300]}")
            if not judge(label, s, raw):
                return

        for label, url_suffix in url_probes:
            s, _, raw = safe_request("GET", url_suffix, timeout=30)
            print(f"probe[{label}] url={url_suffix} -> status={s}")
            print(f"  raw: {raw[:300]}")
            if not judge(label, s, raw):
                return

        # Post-condition: one clean GET must still work (service unharmed)
        sf, _, rawf = safe_request("GET", "/aliases", timeout=30)
        print(f"final clean GET /aliases -> status={sf}")
        if sf <= 0:
            hs, hraw = liveness()
            print(f"transport failure on final GET (healthz status={hs}: {str(hraw)[:200]})")
            if hs == 200:
                print("VERDICT: SCRIPT_ERROR — transport flake (healthz alive), no defect conclusion")
            else:
                print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — service degraded "
                      "after malformed-input sequence (healthz also down)")
            return
        if 500 <= sf <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — clean GET /aliases "
                  f"returns {sf} after malformed-input sequence")
            return
        if sf != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — clean GET /aliases "
                  f"returns {sf} after malformed-input sequence (promise: 200)")
            return
        entriesf, errf = parse_alias_envelope(rawf)
        if errf is not None or find_alias(entriesf or [], alias) is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — final GET envelope "
                  f"degraded after malformed-input sequence (err={errf})")
            return
        print("OK: service unharmed — final clean GET lists the alias in a documented envelope")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            delete_alias(alias)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
