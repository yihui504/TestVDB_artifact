#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comparative-forensics probe for boundary_aliases_update_005 (evidence-builder).
Same value class (JSON-escaped \\u0000, i.e. U+0000) sent to same-family
String name fields / faces of qdrant v1.18.0 POST /collections/aliases.
Ownership prefix: bau5eb<tag>. Cleanup: deletes own aliases + collection."""
import json
import sys
import uuid

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6333"
PFX = "bau5eb" + uuid.uuid4().hex[:6]
COLL = PFX + "c1"


def req(method, path, data=None, timeout=30):
    r = requests.request(method, BASE + path, data=data,
                         headers={"Content-Type": "application/json"}, timeout=timeout)
    return r.status_code, r.text


tag = uuid.uuid4().hex[:8]
s, raw = req("PUT", f"/collections/{COLL}", json.dumps({"vectors": {"size": 4, "distance": "Cosine"}}).encode())
print(f"[setup] PUT /collections/{COLL} -> {s}")

# P0: reproducibility re-run of the PRIMARY observation (escaped-nul in alias_name, create face)
body = json.dumps({"actions": [{"create_alias": {"collection_name": COLL, "alias_name": PFX + "a\\u0000b"}}]}).encode("utf-8")
# NOTE: json.dumps of the string containing literal backslash-u sequence:
# we must send raw bytes containing the escape sequence itself, like the original script:
body = b'{"actions": [{"create_alias": {"collection_name": "' + COLL.encode() + b'", "alias_name": "' + PFX.encode() + b'a\\u0000b"}}]}'
s, raw = req("POST", "/collections/aliases", data=body)
print(f"[P0 re-run primary] create_alias alias_name='...a\\u0000b' (rest) -> status={s} raw={raw[:200]}")

# P1: same value class on the OTHER String field of the same CreateAlias struct: collection_name
body = b'{"actions": [{"create_alias": {"collection_name": "' + PFX.encode() + b'x\\u0000y", "alias_name": "' + PFX.encode() + b"c2\"}}]}"
s, raw = req("POST", "/collections/aliases", data=body)
print(f"[P1 same-struct other field] create_alias collection_name='...x\\u0000y' (rest) -> status={s} raw={raw[:200]}")

# P2: same value class on rename face: new_alias_name (create a clean alias first, then rename to NUL name)
body = json.dumps({"actions": [{"create_alias": {"collection_name": COLL, "alias_name": PFX + "clean"}}]}).encode()
s, raw = req("POST", "/collections/aliases", data=body)
print(f"[P2 setup] create clean alias -> {s}")
body = b'{"actions": [{"rename_alias": {"old_alias_name": "' + PFX.encode() + b'clean", "new_alias_name": "' + PFX.encode() + b'r\\u0000n"}}]}'
s, raw = req("POST", "/collections/aliases", data=body)
print(f"[P2 rename face] rename_alias new_alias_name='...r\\u0000n' (rest) -> status={s} raw={raw[:200]}")

# P3: delete face with NUL name (unknown alias with NUL)
body = b'{"actions": [{"delete_alias": {"alias_name": "' + PFX.encode() + b'd\\u0000e"}}]}'
s, raw = req("POST", "/collections/aliases", data=body)
print(f"[P3 delete face] delete_alias alias_name='...d\\u0000e' (unknown, rest) -> status={s} raw={raw[:200]}")

# P4: state round-trip: does the NUL alias appear in GET /aliases?
s, raw = req("GET", "/aliases")
has_nul = "\\u0000" in raw
names = []
try:
    names = [e["alias_name"] for e in json.loads(raw)["result"]["aliases"] if isinstance(e, dict) and str(e.get("alias_name", "")).startswith(PFX)]
except Exception:
    pass
print(f"[P4 state round-trip] GET /aliases status={s} contains_escaped_nul_in_body={has_nul} prefix_aliases={names!r}")

# P5: gRPC face — qdrant-client if available
try:
    from qdrant_client import QdrantClient
    from qdrant_client.grpc import AliasOperations as GrpcAliasOperations, CreateAlias as GrpcCreateAlias
    have_grpc = True
except Exception as e:
    have_grpc = False
    print(f"[P5 grpc face] sdk unavailable: {type(e).__name__}: {e}")
if have_grpc:
    try:
        c = QdrantClient(url=BASE, prefer_grpc=True, timeout=15)
        info = c.info_about_search()  # force grpc handshake? not needed; just try
        try:
            c.update_collection_aliases(
                change_aliases_operations=[{
                    "create_alias": {
                        "collection_name": COLL,
                        "alias_name": PFX + "g\\u0000h",
                    }
                }]
            )
            print(f"[P5 grpc face] create_alias alias_name with real U+0000 (grpc) -> OK (no exception)")
        except Exception as e:
            print(f"[P5 grpc face] create_alias alias_name with real U+0000 (grpc) -> REJECTED: {type(e).__name__}: {str(e)[:200]}")
        # also try with a real NUL char (not escape) through grpc — grpc strings carry real U+0000 bytes
        try:
            c.update_collection_aliases(
                change_aliases_operations=[{
                    "create_alias": {
                        "collection_name": COLL,
                        "alias_name": PFX + "g2\x00h",
                    }
                }]
            )
            print("[P5 grpc face] create_alias alias_name with real NUL char (grpc) -> OK (no exception)")
        except Exception as e:
            print(f"[P5 grpc face] create_alias alias_name with real NUL char (grpc) -> REJECTED: {type(e).__name__}: {str(e)[:200]}")
    except Exception as e:
        print(f"[P5 grpc face] grpc connect failed: {type(e).__name__}: {str(e)[:200]}")

# cleanup
try:
    s, raw = req("GET", "/aliases")
    names = [e["alias_name"] for e in json.loads(raw)["result"]["aliases"] if isinstance(e, dict) and str(e.get("alias_name", "")).startswith(PFX)]
    for n in names:
        req("POST", "/collections/aliases", json.dumps({"actions": [{"delete_alias": {"alias_name": n}}]}).encode())
    print(f"[cleanup] deleted own aliases: {[n for n in names]}")
except Exception as e:
    print(f"[cleanup] alias cleanup issue: {e}")
req("DELETE", f"/collections/{COLL}")
print(f"[cleanup] dropped collection {COLL}")
