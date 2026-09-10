"""
Test: Behavioral Contract - Collection Visibility After Creation
Attack: Behavioral Contract Violation
Verifies that created collection is immediately visible in GET and LIST operations
"""
import os
import sys
import json
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json_data=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json_data,
            headers=headers,
            timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text

        try:
            body = response.json()
        except:
            body = raw_text

        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

def test_collection_visibility():
    """Verify created collection is immediately visible"""
    collection_name = "test_visibility_immediate"

    payload = {
        "vectors": {
            "size": 128,
            "distance": "Euclidean"
        }
    }

    # Step 1: Create collection
    print(f"Step 1: Creating collection '{collection_name}'")
    status_create, body_create, raw_create = safe_request(
        "PUT",
        f"/collections/{collection_name}",
        json_data=payload
    )

    print(f"Create response status: {status_create}")
    print(f"Create response: {raw_create[:200]}")

    if status_create not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — Collection creation failed: {status_create}")
        sys.exit(2)

    # Step 2: Immediately check if collection exists via GET
    print(f"\nStep 2: Checking GET /collections/{collection_name}")
    status_get, body_get, raw_get = safe_request(
        "GET",
        f"/collections/{collection_name}"
    )

    print(f"GET response status: {status_get}")
    print(f"GET response: {raw_get[:200]}")

    if status_get != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Collection creation returned {status_create} but GET returned {status_get}")
        print(f"Contract violation: Created collection should be immediately visible")
        try:
            safe_request("DELETE", f"/collections/{collection_name}")
        except:
            pass
        sys.exit(1)

    # Step 3: Check if collection appears in LIST
    print(f"\nStep 3: Checking GET /collections (list)")
    status_list, body_list, raw_list = safe_request("GET", "/collections")

    print(f"LIST response status: {status_list}")
    print(f"LIST response: {raw_list[:300]}")

    if status_list != 200:
        print(f"WARNING: List collections returned {status_list}")
    else:
        # Parse response to find our collection
        try:
            collections_data = body_list if isinstance(body_list, dict) else {}
            collections = collections_data.get("result", collections_data.get("collections", []))

            collection_names = []
            if isinstance(collections, list):
                for col in collections:
                    if isinstance(col, dict):
                        name = col.get("name") or col.get("collection_name")
                        if name:
                            collection_names.append(name)

            print(f"Collections in list: {collection_names}")

            if collection_name not in collection_names:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"Collection '{collection_name}' not found in list after creation")
                print(f"Available collections: {collection_names}")
                try:
                    safe_request("DELETE", f"/collections/{collection_name}")
                except:
                    pass
                sys.exit(1)
            else:
                print(f"✓ Collection '{collection_name}' found in list")
        except Exception as e:
            print(f"WARNING: Could not parse list response: {e}")

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    print("\nVERDICT: NO_DEFECT")
    print("Created collection is immediately visible in GET and LIST operations")

if __name__ == "__main__":
    test_collection_visibility()
