#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_003
# strategy: upsert_idempotence
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Pattern B (duplicate creation) on PUT /collections/{name}
  (collections+create). raw_knowledge expected_responses documents a
  "409-conflict family — collection already exists" disposition. Sequence:
  (A) create {size:4, distance:"Cosine"} -> 200, readback confirms the
  identity config; (B) create the SAME name with a different valid config
  {size:16, distance:"Dot"} -> must NOT succeed (409 expected; any 2xx
  contradicts the documented conflict disposition); (C) readback again —
  the first config must still be intact (size=4/Cosine). A 2xx duplicate
  that overwrites the config = state destroyed without a delete
  (Type4_StateLogicViolation); a 2xx no-op = Type1_IllegalSuccess.
  (D) control: drop then recreate the same name with config B -> 200 and
  readback shows config B (proves the (B) rejection was name-state driven,
  not config-B invalidity).
  [chunk_collections+create-1of2 coverage: upsert_idempotence (create-side
   analog: repeated create must not duplicate/overwrite state) x
   qdrant_type_collections_create_001]
Oracle: duplicate create on an existing name -> 409 (2xx = defect; 400
  recorded as family-consistent observation); post-duplicate readback
  vectors.size==4 and vectors.distance=="Cosine" (overwrite = Type4);
  drop+recreate same name -> 200 with the new config readable
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def read_vectors(name):
    """GET describe -> (status, vectors_dict_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        vec = ((cfg or {}).get("params") or {}).get("vectors") if isinstance(cfg, dict) else None
        return s, (vec if isinstance(vec, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr3_" + TS + "_"
    C = PFX + "col"
    CFG_A = {"vectors": {"size": 4, "distance": "Cosine"}}
    CFG_B = {"vectors": {"size": 16, "distance": "Dot"}}
    DEFECTS = []

    try:
        # ---- (A) initial create + identity readback ----
        s, raw = safe_request("PUT", "create_collection",
                              path_params={"name": C}, body=CFG_A)
        print(f"[A create] status={s} raw={raw[:200]}")
        if s == 0 or 500 <= s <= 599 or s not in (200, 201):
            hs, hraw = safe_request("GET", "healthz")
            print(f"[A liveness] healthz status={hs} raw={str(hraw)[:120]}")
            print(f"SETUP_ERROR: initial create returned {s}")
            return "SCRIPT_ERROR"
        gs, vec, graw = read_vectors(C)
        if gs != 200 or vec is None:
            print("SETUP_ERROR: readback after create failed")
            return "SCRIPT_ERROR"
        print(f"[A readback] vectors={vec}")

        # ---- (B) duplicate create, same name, different valid config ----
        s2, raw2 = safe_request("PUT", "create_collection",
                                path_params={"name": C}, body=CFG_B)
        print(f"[B duplicate-create] status={s2} raw={raw2[:300]}")
        if s2 == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[B transport] healthz status={hs} raw={str(hraw)[:120]}")
            return "SCRIPT_ERROR"
        if 500 <= s2 <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[B liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(B) duplicate create returned {s2} (5xx; 409 conflict family "
                f"expected, service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={raw2[:200]}"
            )
        elif 200 <= s2 < 300:
            print("OBSERVATION (B): duplicate create returned 2xx — typed via (C) readback")
        elif s2 == 409:
            print("[B] clean conflict rejection (409) as documented")
        else:
            print(f"OBSERVATION (B): duplicate create rejected with {s2} "
                  f"(documented disposition is the 409 family) — recorded")

        # ---- (C) readback: first config must be intact ----
        gs2, vec2, graw2 = read_vectors(C)
        print(f"[C readback] status={gs2} vectors={vec2}")
        if gs2 != 200 or vec2 is None:
            print("SETUP_ERROR: post-duplicate readback failed")
            return "SCRIPT_ERROR"
        if 200 <= s2 < 300:
            if vec2.get("size") == 16 or vec2.get("distance") == "Dot":
                DEFECTS.append(
                    f"(C) duplicate create overwrote existing collection state "
                    f"without a delete: readback vectors={vec2!r} (was "
                    f"size=4/Cosine) — Type4_StateLogicViolation — raw={graw2[:200]}"
                )
            else:
                DEFECTS.append(
                    f"(B/C) duplicate create accepted with {s2} (2xx) but "
                    f"documented disposition is the 409 conflict family — "
                    f"Type1_IllegalSuccess — raw={raw2[:200]}"
                )
        else:
            if vec2.get("size") != 4 or vec2.get("distance") != "Cosine":
                DEFECTS.append(
                    f"(C) rejected duplicate still mutated state: readback "
                    f"vectors={vec2!r} (expected size=4/Cosine) — "
                    f"Type4_StateLogicViolation"
                )

        # ---- (D) control: drop + recreate same name with CFG_B ----
        ds, draw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[D drop] status={ds} raw={draw[:160]}")
        if ds not in (200, 201, 404):
            print(f"SETUP_ERROR: drop returned {ds}")
            return "SCRIPT_ERROR"
        s3, raw3 = safe_request("PUT", "create_collection",
                                path_params={"name": C}, body=CFG_B)
        print(f"[D recreate] status={s3} raw={raw3[:200]}")
        if s3 not in (200, 201):
            DEFECTS.append(
                f"(D) recreate after verified drop rejected with {s3} — "
                f"stale conflict state blocks reuse of the name — "
                f"Type4_StateLogicViolation — raw={raw3[:200]}"
            )
        else:
            gs3, vec3, _ = read_vectors(C)
            if gs3 == 200 and isinstance(vec3, dict) and vec3.get("size") != 16:
                DEFECTS.append(
                    f"(D) recreated collection did not adopt the new config: "
                    f"readback vectors={vec3!r} (expected size=16) — "
                    f"Type4_StateLogicViolation"
                )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
