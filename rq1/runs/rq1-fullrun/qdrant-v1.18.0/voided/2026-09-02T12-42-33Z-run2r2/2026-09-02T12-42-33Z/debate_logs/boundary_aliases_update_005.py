#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input/character-fuzzing on the raw request stream of aliases+update (POST /collections/aliases) x qdrant_behavioral_aliases_update_001 — probes sent as raw bytes via data=: truncated JSON, trailing comma, single quotes, comment, bare NUL byte inside alias_name, JSON-escaped \\u0000 in alias_name, lone surrogate \\ud800 in alias_name, non-UTF8 body bytes
Oracle: every malformed-stream probe is cleanly rejected with 4xx and a non-empty diagnostic body (parser never crashes); 5xx/panic/utf/serde keywords in body = Type3_RuntimeFailure (healthz rechecked); 200 silent-accept of a NUL/surrogate alias name = Type1_IllegalSuccess pending judge-doc verification of alias-name charset semantics; empty-body 4xx = Type2_PoorDiagnostics (constraint qdrant_behavioral_aliases_update_001 — endpoint robustness for its documented 200/404/500 faces)
Constraint: qdrant_behavioral_aliases_update_001 (behavioral assertion, endpoint aliases+update)
Blindspot: BS-01 Parameter Type Coercion Trust (serde assumed to receive well-formed UTF-8 JSON; stream-level malformation must not reach the handler)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Safety wrapper: probes go through data=<bytes> (never json=) so client-side
serialization cannot pre-reject the malformation — the DB behavior is measured.
R1 lesson applied: ownership by unique per-script prefix bau5<uuid>.
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


def liveness():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs, hraw


def alias_names():
    """GET /aliases -> list of alias names (contract: result.aliases[].alias_name)."""
    s, _, raw = safe_request("GET", "/aliases", timeout=30)
    if s != 200:
        return None, f"status={s}"
    try:
        b = json.loads(raw)
        names = [e.get("alias_name") for e in b["result"]["aliases"]
                 if isinstance(e, dict)]
        return names, None
    except Exception as e:
        return None, f"envelope:{e}"


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
    pfx = "bau5" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Positive control (G4): well-formed JSON via the same data= path
        good = json.dumps({"actions": [{"create_alias": {
            "collection_name": coll, "alias_name": pfx + "ok"}}]}).encode("utf-8")
        s, _, raw = safe_request("POST", "/collections/aliases",
                                 params={"timeout": 60}, data=good, timeout=60)
        print(f"positive raw-JSON control -> status={s} raw={raw[:200]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — raw-JSON positive control failed, no defect conclusion")
            return
        names, err = alias_names()
        if err is not None or (pfx + "ok") not in (names or []):
            print(f"VERDICT: SCRIPT_ERROR — positive control alias not observable ({err})")
            return

        # Act: malformed raw streams (bytes; collection_name targets a REAL
        # collection so a silent 200 actually creates state = real signal)
        probes = [
            ("truncated-json",
             b'{"actions": [{"create_alias": {"collection_name": "' + coll.encode() + b'", "alias_name": "'),
            ("trailing-comma",
             b'{"actions": [],}'),
            ("single-quotes",
             b"{'actions': []}"),
            ("comment-in-json",
             b'{"actions": [] // foo}'),
            ("bare-nul-in-name",
             b'{"actions": [{"create_alias": {"collection_name": "' + coll.encode() +
             b'", "alias_name": "' + pfx.encode() + b'a\x00b"}}]}'),
            ("escaped-nul-in-name",
             b'{"actions": [{"create_alias": {"collection_name": "' + coll.encode() +
             b'", "alias_name": "' + pfx.encode() + b'a\\u0000b"}}]}'),
            ("lone-surrogate-in-name",
             b'{"actions": [{"create_alias": {"collection_name": "' + coll.encode() +
             b'", "alias_name": "' + pfx.encode() + b'a\\ud800b"}}]}'),
            ("non-utf8-bytes",
             b'\xff\xfe{"actions": []}'),
        ]
        for label, blob in probes:
            s, _, raw = safe_request("POST", "/collections/aliases",
                                     params={"timeout": 60}, data=blob, timeout=60)
            print(f"probe[{label}] -> status={s}")
            print(f"  raw: {raw[:300]}")
            if s <= 0:
                hs, hraw = liveness()
                print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
                if hs <= 0 or hs >= 500:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — malformed stream "
                          f"[{label}] killed the service (healthz={hs})")
                else:
                    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            low = raw.lower()
            if 500 <= s <= 599 or any(k in low for k in
                                       ("panic", "internal", "serde", "utf", "decode")):
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — malformed stream "
                      f"[{label}] triggered {s}/parser-error leakage")
                return
            if 400 <= s <= 499:
                if not raw.strip():
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — [{label}] "
                          f"rejected {s} with empty diagnostic body")
                    return
                print(f"  OK: cleanly rejected {s} with non-empty diagnostics")
                continue
            if s != 200:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for [{label}]")
                return
            # 200: silent accept — illegal for structurally broken JSON; for
            # NUL/surrogate names it needs judge-doc charset adjudication
            if label in ("bare-nul-in-name", "escaped-nul-in-name", "lone-surrogate-in-name"):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — malformed input "
                      f"[{label}] silently accepted 200 (pending judge-doc verification "
                      f"of alias-name charset semantics)")
                return
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — structurally malformed "
                  f"JSON [{label}] silently accepted 200")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            names, err = alias_names()
            if err is None:
                for n in (names or []):
                    if isinstance(n, str) and n.startswith(pfx):
                        delete_alias(n)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
