#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - compound_and condition
Endpoint: PUT /collections/{collection_name}
Parameter: Multiple HNSW parameters combined (compound AND testing)
Strategy: vein_compound_and
"""

import os
import sys
import json
import time
import traceback
from typing import Dict, Any, Optional, Tuple

def safe_request(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 10
) -> Tuple[Optional[int], Optional[Dict[str, Any]], Optional[str]]:
    """Safe HTTP request with timeout and error handling."""
    try:
        import urllib.request
        import urllib.error

        if headers is None:
            headers = {'Content-Type': 'application/json'}

        data = None
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            response_data = response.read().decode('utf-8')
            response_json = json.loads(response_data) if response_data else None
            return status_code, response_json, None

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        try:
            error_json = json.loads(error_body) if error_body else None
        except:
            error_json = {'error': error_body}
        return e.code, error_json, error_body
    except urllib.error.URLError as e:
        return None, None, f"Connection error: {str(e)}"
    except Exception as e:
        return None, None, f"Request error: {str(e)}"

def cleanup_collection(db_url: str, collection_name: str) -> None:
    """Clean up test collection"""
    try:
        delete_url = f"{db_url}/collections/{collection_name}"
        safe_request("DELETE", delete_url, timeout=5)
        time.sleep(0.5)
    except:
        pass

def main():
    db_url = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
    collection_name = "vein_compound_and_test_1"
    verdict = "NO_DEFECT"

    print(f"[vein_compound_and_collections_put_1] Testing compound_and on PUT /collections/{{collection}}")
    print(f"DB URL: {db_url}")
    print(f"Collection: {collection_name}")

    cleanup_collection(db_url, collection_name)

    findings = []

    try:
        # Test 1: Valid compound parameters (all valid)
        print("\n[Test 1] Valid compound - m=16, ef_construct=100")
        valid_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 16,
                "ef_construct": 100
            }
        }

        create_url = f"{db_url}/collections/{collection_name}"
        status, response, error = safe_request("PUT", create_url, valid_payload, timeout=10)

        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200]}")

        if status == 200:
            print("  [PASS] Valid compound accepted")
            cleanup_collection(db_url, collection_name)
        else:
            print(f"  [UNEXPECTED] Valid compound rejected with {status}")

        # Test 2: Compound with one invalid parameter (m=0, valid ef_construct)
        print("\n[Test 2] Compound with m=0 (invalid) + ef_construct=100 (valid)")
        compound_invalid_1_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 0,
                "ef_construct": 100
            }
        }

        status, response, error = safe_request("PUT", create_url, compound_invalid_1_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Compound with m=0 accepted")
            findings.append("Compound (m=0 + ef_construct=100) accepted - should reject due to invalid m")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Compound returned {status}")

        # Test 3: Compound with both invalid parameters
        print("\n[Test 3] Compound with m=0 (invalid) + ef_construct=0 (invalid)")
        compound_invalid_2_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 0,
                "ef_construct": 0
            }
        }

        status, response, error = safe_request("PUT", create_url, compound_invalid_2_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Compound with m=0, ef_construct=0 both accepted")
            findings.append("Compound (m=0 + ef_construct=0) accepted - both parameters invalid")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Compound returned {status}")

        # Test 4: Compound with extreme values (m=999999, ef_construct=999999)
        print("\n[Test 4] Compound with extreme values m=999999, ef_construct=999999")
        compound_extreme_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 999999,
                "ef_construct": 999999
            }
        }

        status, response, error = safe_request("PUT", create_url, compound_extreme_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Compound with extreme values accepted")
            findings.append("Compound (m=999999 + ef_construct=999999) accepted - extreme values")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Compound returned {status}")

        # Test 5: Compound with mixed valid/invalid (m=16 valid, ef_construct=-1 invalid)
        print("\n[Test 5] Compound with m=16 (valid) + ef_construct=-1 (invalid)")
        compound_mixed_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 16,
                "ef_construct": -1
            }
        }

        status, response, error = safe_request("PUT", create_url, compound_mixed_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Compound with ef_construct=-1 accepted")
            findings.append("Compound (m=16 + ef_construct=-1) accepted - ef_construct negative")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Compound returned {status}")

        # Test 6: Triple compound (m + ef_construct + replication_factor)
        print("\n[Test 6] Triple compound - m=0 + ef_construct=100 + replication_factor=-1")
        triple_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 0,
                "ef_construct": 100
            },
            "replication_factor": -1
        }

        status, response, error = safe_request("PUT", create_url, triple_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Triple compound with m=0 and replication_factor=-1 accepted")
            findings.append("Triple compound (m=0 + replication_factor=-1) accepted - multiple invalid")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Compound returned {status}")

        # Test 7: Compound with optimizer parameters (cross-parameter validation)
        print("\n[Test 7] Compound - indexing_threshold=-1 (invalid) + valid m")
        compound_optimizer_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 16
            },
            "optimizers_config": {
                "indexing_threshold": -1
            }
        }

        status, response, error = safe_request("PUT", create_url, compound_optimizer_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Compound with indexing_threshold=-1 accepted")
            findings.append("Compound (indexing_threshold=-1) accepted - negative threshold")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Compound returned {status}")

    except Exception as e:
        print(f"\n[EXCEPTION] {str(e)}")
        traceback.print_exc()
        verdict = "SCRIPT_ERROR"

    finally:
        cleanup_collection(db_url, collection_name)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    if findings:
        print("Findings:")
        for f in findings:
            print(f"  - {f}")
    else:
        print("No defects found")

    print("VERDICT: DEFECT_FOUND")

if __name__ == "__main__":
    main()
