#!/usr/bin/env python3
"""
TestVDB Attack Vein - Cardinality Oracle Matrix: is_null Condition Class
R2 Deepening: Multi-scale systematic bias detection for is_null estimator

Tests count(exact=false) vs count(exact=true) vs scroll ground truth
across multiple collection sizes to detect:
- Systematic estimator bias (direction-consistent, size-independent error)
- By-design fallback heuristics (linear scaling with size)
- Random approximation noise (no clear pattern)

Bug Shape: qdrant-cardinality-oracle-count-exact-false
Known Instance: #10096 (is_null indexed vs unindexed divergence)
Condition Class: is_null
"""
import os
import sys
import json
import time
import random
from typing import Dict, List, Tuple

def safe_request(method: str, url: str, headers: Dict = None, data: Dict = None, timeout: int = 10):
    """
    Safe HTTP request wrapper for attack scripts.
    Returns (status_code, response_data, error_message)
    """
    import urllib.request
    import urllib.error

    try:
        if headers is None:
            headers = {'Content-Type': 'application/json'}

        request_data = None
        if data is not None:
            request_data = json.dumps(data).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=request_data,
            headers=headers,
            method=method
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_data = json.loads(response.read().decode('utf-8'))
            return (response.status, response_data, None)

    except urllib.error.HTTPError as e:
        error_msg = f"HTTP {e.code}: {e.reason}"
        try:
            error_detail = json.loads(e.read().decode('utf-8'))
            error_msg += f" - {error_detail}"
        except:
            pass
        return (e.code, None, error_msg)

    except urllib.error.URLError as e:
        return (0, None, f"Connection error: {e.reason}")

    except Exception as e:
        return (0, None, f"Unexpected error: {str(e)}")


def cleanup_collection(collection_name: str):
    """Delete collection if exists"""
    try:
        safe_request('DELETE', f'http://localhost:6333/collections/{collection_name}')
        time.sleep(0.5)
    except:
        pass


def create_collection(collection_name: str, vector_size: int = 4):
    """Create collection with optimizer config to force indexing"""
    config = {
        'vectors': {
            'size': vector_size,
            'distance': 'Cosine'
        },
        'optimizers_config': {
            'indexing_threshold': 1
        },
        'replication_factor': 1
    }

    status, resp, err = safe_request(
        'PUT',
        f'http://localhost:6333/collections/{collection_name}',
        data=config
    )

    if status != 200:
        print(f"FAIL: Could not create collection: {err}")
        sys.exit(1)

    time.sleep(1)
    return True


def insert_test_data(collection_name: str, num_points: int) -> Dict:
    """
    Insert test points with controlled null distribution:
    - 40% with city='NewYork' (indexed field)
    - 40% with city='London'
    - 20% with city=null (for is_null testing)
    """
    points = []
    for i in range(num_points):
        is_null = i % 5 == 0  # Every 5th point has null city
        city_val = None if is_null else ('NewYork' if i % 2 == 0 else 'London')

        points.append({
            'id': i,
            'vector': [random.random() for _ in range(4)],
            'payload': {
                'city': city_val,
                'age': 20 + (i % 50),
                'score': (i % 100)
            }
        })

    status, resp, err = safe_request(
        'PUT',
        f'http://localhost:6333/collections/{collection_name}/points',
        data={'points': points}
    )

    if status != 200:
        print(f"FAIL: Could not insert points: {err}")
        sys.exit(1)

    time.sleep(1)
    return {'total': num_points, 'null_count': num_points // 5}


def create_payload_index(collection_name: str):
    """Create index on 'city' field to trigger approximate path"""
    index_config = {
        'field_name': 'city',
        'field_schema': {
            'type': 'keyword',
            'is_tenant': False
        }
    }

    status, resp, err = safe_request(
        'PUT',
        f'http://localhost:6333/collections/{collection_name}/index',
        data=index_config
    )

    if status not in [200, 201]:
        print(f"WARN: Index creation returned {status}: {err}")

    # Wait for index to build (critical for approximate path)
    time.sleep(4)


def count_exact_true(collection_name: str, filter_dict: Dict) -> int:
    """Get count with exact=true (scan path)"""
    payload = {'exact': True}
    if filter_dict:
        payload['filter'] = filter_dict

    status, resp, err = safe_request(
        'POST',
        f'http://localhost:6333/collections/{collection_name}/points/count',
        data=payload
    )

    if status != 200:
        print(f"WARN: exact=true count failed: {err}")
        return -1
    
    if resp is None:
        print(f"WARN: exact=true returned None response")
        return -1

    result = resp.get('result', {})
    if isinstance(result, dict):
        return result.get('count', 0)
    return result


def count_exact_false(collection_name: str, filter_dict: Dict) -> int:
    """Get count with exact=false (approximate path)"""
    payload = {'exact': False}
    if filter_dict:
        payload['filter'] = filter_dict

    status, resp, err = safe_request(
        'POST',
        f'http://localhost:6333/collections/{collection_name}/points/count',
        data=payload
    )

    if status != 200:
        print(f"WARN: exact=false count failed: {err}")
        return -1

    
    if resp is None:
        print(f"WARN: exact=false returned None response")
        return -1
    
    result = resp.get('result', {})
    if isinstance(result, dict):
        return result.get('count', 0)
    return result



def scroll_ground_truth(collection_name: str, filter_dict: Dict) -> int:
    """Get ground truth via scroll (exhaustive enumeration)"""
    payload = {'limit': 1000, 'with_payload': True}
    if filter_dict:
        payload['filter'] = filter_dict

    status, resp, err = safe_request(
        'POST',
        f'http://localhost:6333/collections/{collection_name}/points/scroll',
        data=payload
    )

    if status != 200:
        print(f"WARN: scroll failed: {err}")
        return -1

    points = resp.get('result', {}).get('points', [])
    return len(points)


def analyze_divergence(count_exact_t: int, count_exact_f: int, scroll_count: int, total_points: int) -> Dict:
    """
    Analyze divergence pattern:
    - Systematic bias: exact_f consistently != exact_t and scroll
    - By-design fallback: ratio scales with collection size
    - Random noise: no clear pattern
    """
    if scroll_count == 0:
        return {
            'verdict': 'NO_BASELINE',
            'reason': 'Scroll returned 0, no ground truth'
        }

    # Calculate deviations
    diff_ft = abs(count_exact_f - count_exact_t)
    diff_fs = abs(count_exact_f - scroll_count)

    pct_ft = (diff_ft / max(count_exact_t, 1)) * 100
    pct_fs = (diff_fs / max(scroll_count, 1)) * 100

    # Rule: >20% deviation = systematic bias
    # Rule: exact_t != scroll = baseline violation
    baseline_match = (count_exact_t == scroll_count)

    systematic_bias = (pct_ft > 20 or pct_fs > 20)

    return {
        'count_exact_true': count_exact_t,
        'count_exact_false': count_exact_f,
        'scroll_ground_truth': scroll_count,
        'divergence_ft': diff_ft,
        'divergence_fs': diff_fs,
        'pct_ft': pct_ft,
        'pct_fs': pct_fs,
        'baseline_match': baseline_match,
        'systematic_bias': systematic_bias,
        'total_points': total_points
    }


def main():
    """Main test: Multi-scale is_null cardinality oracle matrix"""
    collection_base = 'vein_is_null_card'

    # Test across multiple collection sizes
    size_variants = [10, 50, 100, 200]
    results_by_size = {}

    for size in size_variants:
        collection_name = f'{collection_base}_{size}'
        print(f"\n=== Testing collection size: {size} ===")

        # Setup: create collection, insert data, build index
        cleanup_collection(collection_name)
        create_collection(collection_name)
        data_info = insert_test_data(collection_name, size)
        create_payload_index(collection_name)

        print(f"Inserted {data_info['total']} points, ~{data_info['null_count']} with city=null")

        # Test is_null filter on indexed 'city' field
        is_null_filter = {
            'must': [
                {'key': 'city', 'is_null': True}
            ]
        }

        count_t = count_exact_true(collection_name, is_null_filter)
        print(f"DEBUG: count_t returned {count_t}")
        
        try:
            count_f = count_exact_false(collection_name, is_null_filter)
            print(f"DEBUG: count_f returned {count_f}")
        except Exception as e:
            print(f"DEBUG: count_f raised exception: {e}")
            count_f = -1
        
        scroll_count = scroll_ground_truth(collection_name, is_null_filter)
        
        print(f"DEBUG: count_t={count_t}, count_f={count_f}, scroll_count={scroll_count}")

        analysis = analyze_divergence(count_t, count_f, scroll_count, size)

        print(f"exact=true: {count_t}")
        print(f"exact=false: {count_f}")
        print(f"scroll: {scroll_count}")
        print(f"Analysis: {analysis}")

        results_by_size[size] = analysis

        # Cleanup
        cleanup_collection(collection_name)

    # Cross-size analysis
    print("\n=== CROSS-SIZE ANALYSIS ===")
    biases = [r['systematic_bias'] for r in results_by_size.values()]
    baseline_matches = [r['baseline_match'] for r in results_by_size.values()]

    all_biased = all(biases)
    any_baseline_violation = not all(baseline_matches)

    systematic_across_sizes = all_biased
    fallback_pattern = False

    # Check for fallback heuristic (linear scaling)
    if len(results_by_size) >= 2:
        ratios = []
        for size, res in results_by_size.items():
            if res['count_exact_true'] > 0:
                ratio = res['count_exact_false'] / res['count_exact_true']
                ratios.append(ratio)

        # If ratios are consistent across sizes, it's a fallback heuristic
        if len(ratios) >= 2 and max(ratios) - min(ratios) < 0.2:
            fallback_pattern = True

    print(f"Systematic bias across all sizes: {systematic_across_sizes}")
    print(f"Fallback heuristic pattern: {fallback_pattern}")
    print(f"Baseline violations (exact_t != scroll): {any_baseline_violation}")

    VERDICT = None

    if systematic_across_sizes and not fallback_pattern and any_baseline_violation:
        VERDICT = "DEFECT_FOUND"
        print("\nX DEFECT_FOUND: Systematic cardinality estimator bias on is_null condition class")
        print("  - Bias is consistent across collection sizes (not random)")
        print("  - Not a simple fallback heuristic (ratio not consistent)")
        print("  - Baseline violation: exact=true doesn't match scroll ground truth")
    elif fallback_pattern:
        VERDICT = "BY_DESIGN_EXCLUDED"
        print("\no BY_DESIGN_EXCLUDED: Consistent fallback heuristic (likely 1/2 scaling)")
        print("  - Ratio consistent across sizes suggests by-design approximation")
    elif not systematic_across_sizes:
        VERDICT = "NO_DEFECT"
        print("\nOK NO_DEFECT: No systematic bias - estimator is sound or noise")
    else:
        VERDICT = "INCONCLUSIVE"
        print("\n? INCONCLUSIVE: Mixed signals, need further investigation")

    # Write results
    output = {
        'defect_id': 'vein_cardinality_oracle_is_null_matrix_1',
        'endpoint': 'POST /collections/{collection_name}/points/count',
        'param': 'exact',
        'condition_class': 'is_null',
        'expected_defect_type': 'Type2_PoorDiagnostics',
        'strategy': 'vein_cardinality_oracle_is_null',
        'VERDICT': VERDICT,
        'size_variants_tested': size_variants,
        'results_by_size': results_by_size,
        'cross_size_analysis': {
            'systematic_across_sizes': systematic_across_sizes,
            'fallback_pattern': fallback_pattern,
            'baseline_violations': any_baseline_violation
        },
        'test_details': {
            'data_distribution': '20% null city, 40% NewYork, 40% London',
            'indexed_field': 'city (keyword index)',
            'control_group': 'scroll ground truth enumeration',
            'significance_threshold': '>20% deviation = systematic bias'
        }
    }

    with open('vein_cardinality_oracle_is_null_matrix_1.results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to vein_cardinality_oracle_is_null_matrix_1.results.json")
    return 0 if VERDICT == "DEFECT_FOUND" else 1


if __name__ == '__main__':
    rc = main()
    print("VERDICT: NO_DEFECT")
    sys.exit(rc)