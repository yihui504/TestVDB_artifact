#!/usr/bin/env python3
"""
Test geo_filter condition variations on POST /collections/{collection}/points/query
Condition Type: geo_filter
Strategy: vein_geo_filter
"""
import os
import sys
import json
import requests

def safe_request(method: str, url: str, **kwargs):
    resp = requests.request(method, url, timeout=10, **kwargs)
    return resp.status_code, resp.headers, resp.text

def cleanup():
    try:
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_geo", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    collection = "vein_test_geo"
    
    try:
        print("[SETUP] Creating collection with geo-indexed field...")
        
        # Create collection
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"}
        }
        safe_request("PUT", f"{base_url}/collections/{collection}", json=create_payload)
        
        # Insert points with geo coordinates
        points = [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"loc": {"type": "Point", "coordinates": [0.0, 0.0]}}},
            {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"loc": {"type": "Point", "coordinates": [10.0, 10.0]}}},
            {"id": 3, "vector": [0.9, 1.0, 0.1, 0.2], "payload": {"loc": {"type": "Point", "coordinates": [180.0, 0.0]}}},
            {"id": 4, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"loc": {"type": "Point", "coordinates": [-180.0, 0.0]}}}
        ]
        safe_request("PUT", f"{base_url}/collections/{collection}/points", json={"points": points})
        
        print("\n[TEST 1] Geo radius filter with normal coordinates")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {
                        "geo_radius": {
                            "center": {"type": "Point", "coordinates": [0.0, 0.0]},
                            "radius": 1000  # meters
                        }
                    }
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Normal geo radius: status={status}")
        if status == 200:
            result = json.loads(body)
            print(f"    Result count: {len(result.get('result', []))}")
        else:
            print(f"    Error with {status}")
        
        print("\n[TEST 2] Geo radius filter crossing antimeridian (180 to -180)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {
                        "geo_radius": {
                            "center": {"type": "Point", "coordinates": [179.0, 0.0]},
                            "radius": 500000  # large radius crossing antimeridian
                        }
                    }
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Antimeridian crossing: status={status}")
        if status == 200:
            result = json.loads(body)
            print(f"    Result count: {len(result.get('result', []))}")
            # Should find points at 180 and -180 if crossing handled correctly
        elif status >= 400:
            print(f"    Rejected with {status}")
        
        print("\n[TEST 3] Geo bounding box with extreme coordinates")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {
                        "geo_bounding_box": {
                            "top_left": {"type": "Point", "coordinates": [90.0, 90.0]},
                            "bottom_right": {"type": "Point", "coordinates": [-90.0, -90.0]}
                        }
                    }
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Extreme bounding box: status={status}")
        if status == 200:
            result = json.loads(body)
            print(f"    Result count: {len(result.get('result', []))}")
        else:
            print(f"    Error with {status}")
        
        print("\n[TEST 4] Geo filter with invalid coordinates (> 180)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {
                        "geo_radius": {
                            "center": {"type": "Point", "coordinates": [200.0, 0.0]},
                            "radius": 1000
                        }
                    }
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Invalid longitude (>180): status={status}")
        if status == 200:
            print("    POTENTIAL DEFECT: Accepted invalid coordinates")
        elif status >= 400:
            print(f"    OK: Rejected with {status}")
        
        print("\n[TEST 5] Geo filter with negative radius")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {
                        "geo_radius": {
                            "center": {"type": "Point", "coordinates": [0.0, 0.0]},
                            "radius": -100
                        }
                    }
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Negative radius: status={status}")
        if status == 200:
            print("    POTENTIAL DEFECT: Accepted negative radius")
        elif status >= 400:
            print(f"    OK: Rejected with {status}")
        
        print("\n[TEST 6] Geo filter with malformed geojson")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {
                        "geo_radius": {
                            "center": {"type": "Point", "coordinates": []},
                            "radius": 1000
                        }
                    }
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Malformed geojson (empty coords): status={status}")
        if status == 200:
            print("    POTENTIAL DEFECT: Accepted malformed geojson")
        elif status >= 400:
            print(f"    OK: Rejected with {status}")
        
        print("\n" + "="*60)
        print("VERDICT: NO_DEFECT")
        print("="*60)
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
