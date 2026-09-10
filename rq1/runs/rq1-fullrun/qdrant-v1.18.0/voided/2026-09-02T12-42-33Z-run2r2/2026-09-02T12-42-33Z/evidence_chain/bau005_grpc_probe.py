#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gRPC-face probe for boundary_aliases_update_005 (evidence-builder).
qdrant-client gRPC: real U+0000 char in alias_name (no JSON escaping layer)."""
import sys
import uuid

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from qdrant_client import QdrantClient

BASE = "http://127.0.0.1:6333"
PFX = "bau5eg" + uuid.uuid4().hex[:6]
COLL = PFX + "c1"

c_rest_put = QdrantClient(url=BASE, prefer_grpc=False, timeout=30)
try:
    c_rest_put.create_collection(collection_name=COLL, vectors_config={"size": 4, "distance": "Cosine"})
    print(f"[setup] created collection {COLL}")
finally:
    c_rest_put.close()

cg = QdrantClient(url=BASE, prefer_grpc=True, timeout=30)
created = []
try:
    ops = [{"create_alias": {"collection_name": COLL, "alias_name": PFX + "g\x00h"}}]
    try:
        cg.update_collection_aliases(change_aliases_operations=ops)
        print(f"[grpc] create_alias alias_name={PFX}g<NUL>h (real U+0000) -> OK (no exception)")
        created.append(PFX + "g\x00h")
    except Exception as e:
        print(f"[grpc] create_alias alias_name={PFX}g<NUL>h (real U+0000) -> REJECTED: {type(e).__name__}: {str(e)[:250]}")

    # state check via REST
    cr = QdrantClient(url=BASE, prefer_grpc=False, timeout=30)
    try:
        names = [a.alias_name for a in cr.get_aliases().aliases]
        mine = [n for n in names if isinstance(n, str) and n.startswith(PFX)]
        print(f"[grpc->state] REST GET /aliases sees prefix aliases: {mine!r} (any with real NUL: {any(chr(0) in n for n in mine)})")
    finally:
        cr.close()
finally:
    # cleanup
    try:
        for n in created:
            cg.update_collection_aliases(change_aliases_operations=[{"delete_alias": {"alias_name": n}}])
        print("[cleanup] grpc-created aliases deleted")
    except Exception as e:
        print(f"[cleanup] issue: {e}")
    cg.close()
    cd = QdrantClient(url=BASE, prefer_grpc=False, timeout=30)
    try:
        cd.delete_collection(collection_name=COLL)
        print(f"[cleanup] dropped {COLL}")
    finally:
        cd.close()
